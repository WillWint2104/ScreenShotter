"""
profile_manager.py

Loads, saves, matches, and tracks proficiency for page profiles.
Uses silent assisted mode (Option C from ARCHITECTURE.md):
  - Match found: load profile + keep heuristics active
  - No match: use heuristics only
  - Never interrupts capture workflow
  - Records which profile was used in session manifest
"""
import json
import logging
import re
from datetime import datetime
from pathlib import Path

from app.models.profile import (
    CaptureProfile, PageFingerprint,
    ProfileMatchResult, SectionDefinition,
)

logger = logging.getLogger(__name__)

# Whitelist for profile filename slugs: alnum, underscore, hyphen only.
# Anything outside this set is stripped to prevent path traversal or
# invalid filenames from profile.name values the user may supply.
_SLUG_SAFE = re.compile(r"[^a-z0-9_-]+")
_SLUG_MAX_LEN = 64

# Profiles live here regardless of where the app is installed
_PROFILES_DIR = Path(__file__).resolve().parents[2] / "data" / "config" / "profiles"
MATCH_THRESHOLD = 0.75
SIGNAL_WEIGHTS = {
    "url_pattern":                0.25,
    "container_count":            0.20,
    "container_geometry_ratios":  0.15,
    "landmark_words":             0.15,
    "field_label_signature":      0.10,
    "section_header_tokens":      0.10,
    "layout_region_count":        0.05,
}


class ProfileManager:

    def __init__(self) -> None:
        _PROFILES_DIR.mkdir(parents=True, exist_ok=True)
        self._profiles: dict[str, CaptureProfile] = {}
        self._load_all()

    # ----------------------------------------------------------
    # Load / save
    # ----------------------------------------------------------

    def _load_all(self) -> None:
        for path in _PROFILES_DIR.glob("*.json"):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                profile = _profile_from_dict(data)
                self._profiles[profile.name] = profile
            except Exception as exc:
                logger.warning("Failed to load profile %s: %s", path.name, exc)

    def save_profile(self, profile: CaptureProfile) -> bool:
        try:
            _PROFILES_DIR.mkdir(parents=True, exist_ok=True)
            slug = _safe_slug(profile.name)
            path = (_PROFILES_DIR / f"{slug}.json").resolve()
            # Defence-in-depth: even with the slug whitelist, verify the
            # resolved path stays inside _PROFILES_DIR before writing.
            if Path(_PROFILES_DIR).resolve() not in path.parents:
                logger.warning(
                    "Rejected profile path escape: %s (from name %r)",
                    path, profile.name,
                )
                return False
            # Slug collision: two distinct profile.name values can
            # sanitize to the same slug (e.g., 'My Profile' and
            # 'my_profile'). Refuse to silently overwrite a file
            # that belongs to a different profile name.
            if path.exists():
                try:
                    existing = json.loads(path.read_text(encoding="utf-8"))
                    existing_name = existing.get("name", "")
                    if existing_name and existing_name != profile.name:
                        logger.warning(
                            "Slug collision: %r sanitizes to %s.json which "
                            "already belongs to %r. Rejecting save.",
                            profile.name, slug, existing_name,
                        )
                        return False
                except Exception as exc:
                    logger.warning(
                        "Could not read existing %s for collision check: %s",
                        path.name, exc,
                    )
            path.write_text(
                json.dumps(profile.as_dict(), indent=2),
                encoding="utf-8"
            )
            self._profiles[profile.name] = profile
            logger.info("Saved profile: %s", profile.name)
            return True
        except Exception as exc:
            logger.warning("Failed to save profile %s: %s", profile.name, exc)
            return False

    def get_profile(self, name: str) -> CaptureProfile | None:
        return self._profiles.get(name)

    def list_profiles(self) -> list[str]:
        return list(self._profiles.keys())

    # ----------------------------------------------------------
    # Fingerprint and match
    # ----------------------------------------------------------

    def match(self, fingerprint: PageFingerprint) -> ProfileMatchResult:
        """
        Compare fingerprint against all saved profiles.
        Returns best match if confidence >= MATCH_THRESHOLD.
        Always uses assisted mode (Option C).
        No single signal determines the result.
        """
        best_name = ""
        best_score = 0.0
        best_reasons: list[str] = []

        for name, profile in self._profiles.items():
            score, reasons = _score_fingerprint(
                fingerprint, profile.fingerprint
            )
            if score > best_score:
                best_score = score
                best_name = name
                best_reasons = reasons

        if best_score >= MATCH_THRESHOLD:
            logger.info(
                "Profile matched: %s (confidence=%.2f)", best_name, best_score
            )
            return ProfileMatchResult(
                profile_matched=True,
                profile_name=best_name,
                profile_match_confidence=round(best_score, 3),
                profile_match_reason=best_reasons,
                mode="assisted",
            )

        logger.info("No profile matched (best=%.2f). Using heuristics.", best_score)
        return ProfileMatchResult(
            profile_matched=False,
            profile_name="",
            profile_match_confidence=round(best_score, 3),
            profile_match_reason=[],
            mode="none",
        )

    # ----------------------------------------------------------
    # Proficiency tracking
    # ----------------------------------------------------------

    def record_session_result(
        self,
        profile_name: str,
        capture_confidence: float,
        success: bool,
    ) -> None:
        """
        Update proficiency score for a profile after a capture session.
        Recent sessions are weighted more than early ones.
        """
        profile = self._profiles.get(profile_name)
        if not profile:
            return

        # Clamp caller-supplied confidence to [0.0, 1.0] so a bad
        # call site cannot push proficiency outside valid bounds.
        try:
            clamped = max(0.0, min(1.0, float(capture_confidence)))
        except (TypeError, ValueError):
            logger.warning(
                "Invalid capture_confidence %r for profile %s; using 0.0",
                capture_confidence, profile_name,
            )
            clamped = 0.0

        profile.total_sessions += 1
        if success:
            profile.successful_sessions += 1

        # Weighted rolling average: 70% existing, 30% new score
        profile.proficiency_score = round(
            profile.proficiency_score * 0.70 + clamped * 0.30, 4
        )
        profile.check_proficiency()
        self.save_profile(profile)
        logger.info(
            "Profile %s proficiency updated: score=%.3f sessions=%d proficient=%s",
            profile_name,
            profile.proficiency_score,
            profile.successful_sessions,
            profile.is_proficient,
        )

    def build_fingerprint(self, page_data: dict) -> PageFingerprint:
        """
        Build a PageFingerprint from raw page discovery data.
        page_data keys (all optional, use safe defaults):
          url, scrollable_regions, landmark_words,
          field_labels, section_headers, layout_region_count
        """
        url = page_data.get("url", "")
        url_pattern = _extract_url_pattern(url)

        regions = page_data.get("scrollable_regions", [])
        count = len(regions)
        ratios = _geometry_ratios(regions)

        return PageFingerprint(
            url_pattern=url_pattern,
            scrollable_container_count=count,
            container_geometry_ratios=ratios,
            landmark_words=page_data.get("landmark_words", []),
            field_label_signature=page_data.get("field_labels", []),
            section_header_tokens=page_data.get("section_headers", []),
            layout_region_count=page_data.get("layout_region_count", 0),
        )


# ----------------------------------------------------------
# Private helpers
# ----------------------------------------------------------

def _safe_slug(name: str) -> str:
    """Sanitize a profile name into a safe filesystem slug.

    Strips every character outside [a-z0-9_-], caps length, and
    falls back to 'unnamed' on empty results. Used by save_profile
    to block path traversal and invalid filename characters.
    """
    raw = (name or "").lower().replace(" ", "_")
    cleaned = _SLUG_SAFE.sub("", raw)[:_SLUG_MAX_LEN]
    return cleaned or "unnamed"


def _score_fingerprint(
    candidate: PageFingerprint,
    reference: PageFingerprint,
) -> tuple[float, list[str]]:
    reasons: list[str] = []
    total = 0.0

    # URL pattern
    if reference.url_pattern and candidate.url_pattern:
        if _url_patterns_match(candidate.url_pattern, reference.url_pattern):
            total += SIGNAL_WEIGHTS["url_pattern"]
            reasons.append("url_pattern_match")

    # Container count
    if reference.scrollable_container_count > 0:
        diff = abs(
            candidate.scrollable_container_count
            - reference.scrollable_container_count
        )
        if diff == 0:
            total += SIGNAL_WEIGHTS["container_count"]
            reasons.append("container_count_match")
        elif diff == 1:
            total += SIGNAL_WEIGHTS["container_count"] * 0.5

    # Container geometry ratios
    if reference.container_geometry_ratios and candidate.container_geometry_ratios:
        sim = _list_similarity(
            candidate.container_geometry_ratios,
            reference.container_geometry_ratios,
        )
        total += SIGNAL_WEIGHTS["container_geometry_ratios"] * sim
        if sim >= 0.8:
            reasons.append("container_geometry_match")

    # Landmark words
    if reference.landmark_words:
        overlap = _set_overlap(
            candidate.landmark_words, reference.landmark_words
        )
        total += SIGNAL_WEIGHTS["landmark_words"] * overlap
        if overlap >= 0.5:
            reasons.append("landmark_words_match")

    # Field label signature
    if reference.field_label_signature:
        overlap = _set_overlap(
            candidate.field_label_signature,
            reference.field_label_signature,
        )
        total += SIGNAL_WEIGHTS["field_label_signature"] * overlap
        if overlap >= 0.5:
            reasons.append("field_label_signature_match")

    # Section header tokens
    if reference.section_header_tokens:
        overlap = _set_overlap(
            candidate.section_header_tokens,
            reference.section_header_tokens,
        )
        total += SIGNAL_WEIGHTS["section_header_tokens"] * overlap
        if overlap >= 0.5:
            reasons.append("section_header_tokens_match")

    # Layout region count
    if reference.layout_region_count > 0:
        if candidate.layout_region_count == reference.layout_region_count:
            total += SIGNAL_WEIGHTS["layout_region_count"]
            reasons.append("layout_region_count_match")

    return min(total, 1.0), reasons


def _url_patterns_match(a: str, b: str) -> bool:
    """Match on domain + shared path prefix segments.

    Both patterns come from _extract_url_pattern(), which keeps the
    netloc followed by up to the first two stable path segments.

    Host-only patterns (no path segments) are treated as "no URL
    signal" and return False so a bare-domain profile cannot
    blanket-match every page on that domain. At least one path
    segment on each side is required for a URL match to count.
    """
    try:
        a_parts = [p for p in a.lower().split("/") if p]
        b_parts = [p for p in b.lower().split("/") if p]
        if len(a_parts) < 2 or len(b_parts) < 2:
            return False  # host-only is not a distinguishing signal
        if a_parts[0] != b_parts[0]:
            return False
        shared = min(len(a_parts), len(b_parts))
        return a_parts[:shared] == b_parts[:shared]
    except Exception:
        return False


def _extract_url_pattern(url: str) -> str:
    try:
        from urllib.parse import urlparse
        parsed = urlparse(url)
        parts = parsed.path.strip("/").split("/")
        stable = parts[:2] if len(parts) >= 2 else parts
        return parsed.netloc + "/" + "/".join(stable)
    except Exception:
        return url


def _geometry_ratios(regions: list[dict]) -> list[float]:
    if not regions:
        return []
    total_h = sum(r.get("rect", {}).get("height", 0) for r in regions)
    if total_h == 0:
        return []
    return [
        round(r.get("rect", {}).get("height", 0) / total_h, 3)
        for r in regions
    ]


def _set_overlap(a: list[str], b: list[str]) -> float:
    if not a or not b:
        return 0.0
    set_a = {x.lower() for x in a}
    set_b = {x.lower() for x in b}
    intersection = set_a & set_b
    union = set_a | set_b
    return len(intersection) / len(union) if union else 0.0


def _list_similarity(a: list[float], b: list[float]) -> float:
    # Compare the overlapping prefix of two float lists; unpaired
    # tail elements reduce the score by inflating the denominator,
    # so different-length vectors score lower than equal-length ones.
    if not a or not b:
        return 0.0
    pairs = zip(a[:len(b)], b[:len(a)])
    scores = [1.0 - min(abs(x - y), 1.0) for x, y in pairs]
    return sum(scores) / max(len(a), len(b))


def _profile_from_dict(data: dict) -> CaptureProfile:
    fp_data = data.get("fingerprint", {})
    fingerprint = PageFingerprint(
        url_pattern=fp_data.get("url_pattern", ""),
        scrollable_container_count=fp_data.get("scrollable_container_count", 0),
        container_geometry_ratios=fp_data.get("container_geometry_ratios", []),
        landmark_words=fp_data.get("landmark_words", []),
        field_label_signature=fp_data.get("field_label_signature", []),
        section_header_tokens=fp_data.get("section_header_tokens", []),
        layout_region_count=fp_data.get("layout_region_count", 0),
    )
    section_defs = [
        SectionDefinition(
            section_type=s.get("section_type", "unknown"),
            detection_hints=s.get("detection_hints", []),
            position_hint=s.get("position_hint", "any"),
            min_width_ratio=s.get("min_width_ratio", 0.0),
            min_height_px=s.get("min_height_px", 0),
        )
        for s in data.get("section_definitions", [])
    ]
    return CaptureProfile(
        name=data.get("name", "unnamed"),
        created_at=data.get("created_at", datetime.now().isoformat()),
        fingerprint=fingerprint,
        section_definitions=section_defs,
        capture_params=data.get("capture_params", {}),
        expander_triggers=data.get("expander_triggers", []),
        protected_patterns=data.get("protected_patterns", []),
        proficiency_score=data.get("proficiency_score", 0.0),
        successful_sessions=data.get("successful_sessions", 0),
        total_sessions=data.get("total_sessions", 0),
        is_proficient=data.get("is_proficient", False),
        notes=data.get("notes", ""),
    )
