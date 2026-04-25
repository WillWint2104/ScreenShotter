"""
improvement_engine.py

Reads accumulated capture evaluation results.
Identifies recurring failure patterns across sessions.
Produces human-reviewable improvement recommendations.

NEVER modifies profiles, parameters, or rules automatically.
ALL changes require human review and approval.
Approved changes are recorded and traceable.

See ARCHITECTURE.md — Improvement Engine Constraints.
"""
import json
import logging
import re
import uuid
from datetime import datetime
from pathlib import Path

from app.models.improvement import (
    ImprovementRecommendation,
    ImprovementReport,
)

logger = logging.getLogger(__name__)

# Minimum sessions before pattern analysis is meaningful
MIN_SESSIONS_FOR_ANALYSIS = 3

# Fraction of sessions an issue must appear in to trigger recommendation
PATTERN_THRESHOLD = 0.40

# Paths
_DATA_DIR        = Path(__file__).resolve().parents[2] / "data"
_EVALUATIONS_DIR = _DATA_DIR / "evaluations"
_IMPROVEMENTS_DIR = _DATA_DIR / "improvements"

# Whitelist for session_id slugs used in index_evaluation: alnum,
# underscore, hyphen, dot. Anything else is stripped to block path
# traversal (e.g. '../etc/passwd') and unexpected subdirectories.
_SESSION_ID_SAFE = re.compile(r"[^A-Za-z0-9._-]+")
_SESSION_ID_MAX_LEN = 96


class ImprovementEngine:
    """
    Analyses accumulated evaluation results and produces
    recommendations only. Never applies changes automatically.

    Constraints (from ARCHITECTURE.md — Improvement Engine):
        - NEVER modifies profiles automatically
        - NEVER modifies capture parameters automatically
        - NEVER auto-applies expander rules
        - NEVER changes classification thresholds without approval
        - All changes require human review and explicit approval
        - Every recommendation starts in 'pending' status
        - Every applied change must trace back to a specific
          recommendation; this engine does not apply changes —
          a separate human-driven step does that.
    """

    def __init__(self) -> None:
        _IMPROVEMENTS_DIR.mkdir(parents=True, exist_ok=True)
        _EVALUATIONS_DIR.mkdir(parents=True, exist_ok=True)

    # ----------------------------------------------------------
    # Analysis entry point
    # ----------------------------------------------------------

    def analyse(
        self,
        profile_name: str = "",
        min_sessions: int = MIN_SESSIONS_FOR_ANALYSIS,
    ) -> ImprovementReport | None:
        """
        Load all evaluation results (optionally filtered by profile),
        detect patterns, produce a recommendation report.
        Write report to data/improvements/.
        Return the report or None if too few sessions to analyse.
        """
        evaluations = self._load_evaluations(profile_name)

        if len(evaluations) < min_sessions:
            logger.info(
                "Too few sessions to analyse: %d (minimum %d)",
                len(evaluations), min_sessions,
            )
            return None

        logger.info(
            "Analysing %d evaluation results (profile='%s')",
            len(evaluations), profile_name or "all",
        )

        recommendations: list[ImprovementRecommendation] = []
        patterns: list[str] = []

        # Run all pattern detectors
        detectors = [
            self._detect_missing_sections,
            self._detect_low_ocr_quality,
            self._detect_contamination_pattern,
            self._detect_low_overall_confidence,
            self._detect_retry_rate,
        ]
        for detector in detectors:
            recs, found_patterns = detector(evaluations)
            recommendations.extend(recs)
            patterns.extend(found_patterns)

        report = ImprovementReport(
            report_id=str(uuid.uuid4())[:8],
            generated_at=datetime.now().isoformat(),
            sessions_analysed=len(evaluations),
            recommendations=recommendations,
            patterns_detected=list(set(patterns)),
            summary=self._summarise(evaluations, recommendations),
        )

        # If persistence fails the report_id we'd advertise points at
        # nothing on disk, so approve_recommendation/reject_recommendation
        # would fail to find it. Surface the failure to the caller
        # rather than handing back a phantom report.
        if not self._write_report(report):
            logger.error(
                "Improvement report %s failed to persist — discarding.",
                report.report_id,
            )
            return None
        logger.info(
            "Improvement report generated: %d recommendations, "
            "%d patterns detected",
            len(recommendations), len(patterns),
        )
        return report

    # ----------------------------------------------------------
    # Approval workflow
    # ----------------------------------------------------------

    def approve_recommendation(
        self,
        report_id: str,
        recommendation_id: str,
        approved_by: str = "human",
    ) -> bool:
        """
        Mark a recommendation as approved.
        Does not apply any change — approval is recorded only.
        Actual change must be applied separately by a human or
        a dedicated apply step.
        """
        report_path = _IMPROVEMENTS_DIR / f"report_{report_id}.json"
        if not report_path.exists():
            logger.warning("Report not found: %s", report_id)
            return False

        try:
            data = json.loads(report_path.read_text(encoding="utf-8"))
            for rec in data.get("recommendations", []):
                if rec["recommendation_id"] == recommendation_id:
                    # Stick to the ImprovementRecommendation model
                    # (Spec 2): only approval_status and approved_by
                    # are dedicated fields. The timestamp is appended
                    # to 'notes' for the audit trail without inventing
                    # off-model keys. 'applied_at' stays empty —
                    # approval is not application.
                    rec["approval_status"] = "approved"
                    rec["approved_by"] = approved_by
                    timestamp = datetime.now().isoformat()
                    existing = rec.get("notes", "") or ""
                    sep = "\n" if existing else ""
                    rec["notes"] = (
                        f"{existing}{sep}approved at {timestamp} "
                        f"by {approved_by}"
                    )
                    report_path.write_text(
                        json.dumps(data, indent=2), encoding="utf-8"
                    )
                    logger.info(
                        "Recommendation %s approved by %s",
                        recommendation_id, approved_by,
                    )
                    return True
            logger.warning(
                "Recommendation %s not found in report %s",
                recommendation_id, report_id,
            )
            return False
        except (OSError, json.JSONDecodeError, KeyError, TypeError) as exc:
            logger.warning(
                "Failed to approve recommendation: %s", exc, exc_info=True,
            )
            return False

    def reject_recommendation(
        self,
        report_id: str,
        recommendation_id: str,
    ) -> bool:
        """
        Mark a recommendation as rejected.
        No change is applied.
        """
        report_path = _IMPROVEMENTS_DIR / f"report_{report_id}.json"
        if not report_path.exists():
            return False
        try:
            data = json.loads(report_path.read_text(encoding="utf-8"))
            for rec in data.get("recommendations", []):
                if rec["recommendation_id"] == recommendation_id:
                    rec["approval_status"] = "rejected"
                    timestamp = datetime.now().isoformat()
                    existing = rec.get("notes", "") or ""
                    sep = "\n" if existing else ""
                    rec["notes"] = f"{existing}{sep}rejected at {timestamp}"
                    report_path.write_text(
                        json.dumps(data, indent=2), encoding="utf-8"
                    )
                    logger.info(
                        "Recommendation %s rejected", recommendation_id
                    )
                    return True
            return False
        except (OSError, json.JSONDecodeError, KeyError, TypeError) as exc:
            logger.warning(
                "Failed to reject recommendation: %s", exc, exc_info=True,
            )
            return False

    def list_reports(self) -> list[dict]:
        """
        List all improvement reports with summary info.
        """
        reports = []
        for path in sorted(_IMPROVEMENTS_DIR.glob("report_*.json")):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                reports.append({
                    "report_id":          data.get("report_id"),
                    "generated_at":       data.get("generated_at"),
                    "sessions_analysed":  data.get("sessions_analysed"),
                    "recommendation_count": len(data.get("recommendations", [])),
                    "patterns_detected":  data.get("patterns_detected", []),
                    "summary":            data.get("summary", ""),
                })
            except (OSError, json.JSONDecodeError) as exc:
                logger.warning("Failed to read report %s: %s", path.name, exc)
        return reports

    def index_evaluation(
        self, session_id: str, evaluation_path: Path
    ) -> bool:
        """
        Copy or symlink an evaluation.json into the evaluations index.
        Called after each session completes.

        session_id is sanitized (whitelist [A-Za-z0-9._-], capped at
        96 chars) before being used in the destination filename so a
        hostile or malformed value cannot escape _EVALUATIONS_DIR.
        Defence-in-depth: the resolved destination path is verified
        to live inside _EVALUATIONS_DIR before writing.
        """
        safe_id = _safe_session_id(session_id)
        if not safe_id:
            logger.warning(
                "Rejected index_evaluation: empty session_id after "
                "sanitization (input=%r)", session_id,
            )
            return False
        try:
            _EVALUATIONS_DIR.mkdir(parents=True, exist_ok=True)
            dest = (
                _EVALUATIONS_DIR / f"{safe_id}_evaluation.json"
            ).resolve()
            if _EVALUATIONS_DIR.resolve() not in dest.parents:
                logger.warning(
                    "Rejected index_evaluation: path escape (input=%r, "
                    "resolved=%s)", session_id, dest,
                )
                return False
            dest.write_text(
                evaluation_path.read_text(encoding="utf-8"),
                encoding="utf-8",
            )
            logger.debug("Indexed evaluation for session %s", safe_id)
            return True
        except (OSError, ValueError) as exc:
            logger.warning(
                "Failed to index evaluation for %s: %s",
                session_id, exc, exc_info=True,
            )
            return False

    # ----------------------------------------------------------
    # Pattern detectors — each returns (recommendations, patterns)
    # ----------------------------------------------------------

    def _detect_missing_sections(
        self, evaluations: list[dict]
    ) -> tuple[list[ImprovementRecommendation], list[str]]:
        recs: list[ImprovementRecommendation] = []
        patterns: list[str] = []
        n = len(evaluations)

        section_missing_counts: dict[str, list[str]] = {}
        for ev in evaluations:
            for section in ev.get("missing_sections", []):
                section_missing_counts.setdefault(section, []).append(
                    ev.get("session_id", "unknown")
                )

        for section, sessions in section_missing_counts.items():
            rate = len(sessions) / n
            if rate >= PATTERN_THRESHOLD:
                pattern = f"missing_section:{section}:{rate:.0%}_of_sessions"
                patterns.append(pattern)
                recs.append(ImprovementRecommendation(
                    recommendation_id=str(uuid.uuid4())[:8],
                    type="uia_search_depth",
                    issue=f"section_{section}_frequently_missing",
                    pattern_evidence=sessions[:5],
                    suggestion=(
                        f"'{section}' missing in {rate:.0%} of sessions. "
                        f"Increase UIA search depth or add detection hint "
                        f"for this section type."
                    ),
                    current_value="depth=8",
                    recommended_value="depth=12",
                    affected_sessions=sessions,
                ))

        return recs, patterns

    def _detect_low_ocr_quality(
        self, evaluations: list[dict]
    ) -> tuple[list[ImprovementRecommendation], list[str]]:
        recs: list[ImprovementRecommendation] = []
        patterns: list[str] = []
        n = len(evaluations)

        low_ocr_sessions = [
            ev.get("session_id", "unknown")
            for ev in evaluations
            if ev.get("ocr_quality", {}).get("overall", 1.0) < 0.55
        ]
        rate = len(low_ocr_sessions) / n

        if rate >= PATTERN_THRESHOLD:
            patterns.append(f"low_ocr_quality:{rate:.0%}_of_sessions")
            recs.append(ImprovementRecommendation(
                recommendation_id=str(uuid.uuid4())[:8],
                type="capture_param",
                issue="ocr_quality_consistently_low",
                pattern_evidence=low_ocr_sessions[:5],
                suggestion=(
                    f"OCR quality below threshold in {rate:.0%} of sessions. "
                    f"Increase browser zoom level before capture."
                ),
                current_value="browser_zoom=150%",
                recommended_value="browser_zoom=175%",
                affected_sessions=low_ocr_sessions,
            ))

        return recs, patterns

    def _detect_contamination_pattern(
        self, evaluations: list[dict]
    ) -> tuple[list[ImprovementRecommendation], list[str]]:
        recs: list[ImprovementRecommendation] = []
        patterns: list[str] = []
        n = len(evaluations)

        contaminated_sessions = [
            ev.get("session_id", "unknown")
            for ev in evaluations
            if any(
                len(score.get("issues", [])) > 0 and
                any("contamination" in issue
                    for issue in score.get("issues", []))
                for score in ev.get("section_scores", {}).values()
            )
        ]
        rate = len(contaminated_sessions) / n

        if rate >= PATTERN_THRESHOLD:
            patterns.append(f"section_contamination:{rate:.0%}_of_sessions")
            recs.append(ImprovementRecommendation(
                recommendation_id=str(uuid.uuid4())[:8],
                type="classification_rule",
                issue="section_boundary_contamination_recurring",
                pattern_evidence=contaminated_sessions[:5],
                suggestion=(
                    f"Section boundary contamination in {rate:.0%} of "
                    f"sessions. Review section classification thresholds "
                    f"and tighten boundary detection rules."
                ),
                current_value="confidence_threshold=0.40",
                recommended_value="confidence_threshold=0.55",
                affected_sessions=contaminated_sessions,
            ))

        return recs, patterns

    def _detect_low_overall_confidence(
        self, evaluations: list[dict]
    ) -> tuple[list[ImprovementRecommendation], list[str]]:
        recs: list[ImprovementRecommendation] = []
        patterns: list[str] = []
        n = len(evaluations)

        low_confidence_sessions = [
            ev.get("session_id", "unknown")
            for ev in evaluations
            if ev.get("overall_capture_confidence", 1.0) < 0.50
        ]
        rate = len(low_confidence_sessions) / n

        if rate >= PATTERN_THRESHOLD:
            patterns.append(
                f"low_overall_confidence:{rate:.0%}_of_sessions"
            )
            recs.append(ImprovementRecommendation(
                recommendation_id=str(uuid.uuid4())[:8],
                type="profile_edit",
                issue="overall_capture_confidence_consistently_low",
                pattern_evidence=low_confidence_sessions[:5],
                suggestion=(
                    f"Overall capture confidence below 0.50 in {rate:.0%} "
                    f"of sessions. Review and update the active profile's "
                    f"section definitions and detection hints."
                ),
                current_value="profile_confidence_baseline=general_heuristics",
                recommended_value="profile_confidence_baseline=tuned_profile",
                affected_sessions=low_confidence_sessions,
            ))

        return recs, patterns

    def _detect_retry_rate(
        self, evaluations: list[dict]
    ) -> tuple[list[ImprovementRecommendation], list[str]]:
        recs: list[ImprovementRecommendation] = []
        patterns: list[str] = []
        n = len(evaluations)

        retry_sessions = [
            ev.get("session_id", "unknown")
            for ev in evaluations
            if ev.get("recommended_action") == "retry"
        ]
        rate = len(retry_sessions) / n

        if rate >= PATTERN_THRESHOLD:
            patterns.append(f"high_retry_rate:{rate:.0%}_of_sessions")
            recs.append(ImprovementRecommendation(
                recommendation_id=str(uuid.uuid4())[:8],
                type="capture_param",
                issue="high_retry_rate",
                pattern_evidence=retry_sessions[:5],
                suggestion=(
                    f"Retry recommended in {rate:.0%} of sessions. "
                    f"Increase post-scroll delay to allow page content "
                    f"to fully render before capture."
                ),
                current_value="delay_ms=800",
                recommended_value="delay_ms=1200",
                affected_sessions=retry_sessions,
            ))

        return recs, patterns

    # ----------------------------------------------------------
    # Helpers
    # ----------------------------------------------------------

    def _load_evaluations(self, profile_name: str = "") -> list[dict]:
        """
        Load every *_evaluation.json from the evaluations index.

        When profile_name is non-empty, return only evaluations whose
        stored 'profile_name' field matches. CaptureValidator does not
        currently embed profile_name in evaluation.json — once it does,
        this filter activates without further changes here.
        """
        evaluations = []
        for path in sorted(_EVALUATIONS_DIR.glob("*_evaluation.json")):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                if profile_name and data.get("profile_name") != profile_name:
                    continue
                evaluations.append(data)
            except (OSError, json.JSONDecodeError) as exc:
                logger.warning(
                    "Failed to load evaluation %s: %s", path.name, exc
                )
        return evaluations

    def _summarise(
        self,
        evaluations: list[dict],
        recommendations: list[ImprovementRecommendation],
    ) -> str:
        n = len(evaluations)
        accept_count = sum(
            1 for ev in evaluations
            if ev.get("recommended_action") == "accept"
        )
        accept_rate = accept_count / n if n > 0 else 0.0
        return (
            f"Analysed {n} sessions. "
            f"Accept rate: {accept_rate:.0%}. "
            f"{len(recommendations)} recommendation(s) generated."
        )

    def _write_report(self, report: ImprovementReport) -> bool:
        try:
            path = _IMPROVEMENTS_DIR / f"report_{report.report_id}.json"
            path.write_text(
                json.dumps(report.as_dict(), indent=2),
                encoding="utf-8",
            )
            logger.info("Improvement report written: %s", path)
            return True
        except (OSError, TypeError, ValueError) as exc:
            logger.warning(
                "Failed to write improvement report: %s",
                exc, exc_info=True,
            )
            return False


def _safe_session_id(session_id: str) -> str:
    """Sanitize a session_id into a safe filesystem token.

    Strips every character outside [A-Za-z0-9._-], caps at 96 chars,
    returns '' on empty result so the caller can reject. Used by
    index_evaluation() to block path traversal and unexpected
    subdirectories from caller-supplied IDs.
    """
    raw = (session_id or "").strip()
    cleaned = _SESSION_ID_SAFE.sub("", raw)[:_SESSION_ID_MAX_LEN]
    # Strip leading dots so '.' / '..' / '...' cannot ever produce
    # a non-empty cleaned slug that still references a parent.
    cleaned = cleaned.lstrip(".")
    return cleaned
