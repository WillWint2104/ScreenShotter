"""
capture_validator.py

Assesses the quality of a capture session.
Capture quality only — not task quality, not content evaluation.

Produces evaluation.json per session with the locked output
contract from ARCHITECTURE.md.

See ARCHITECTURE.md:
  "Critical Boundary: Capture Validator is not a Task Evaluator"

Assesses:
  - Section completeness (were all expected sections found?)
  - Screenshot count per section (is coverage sufficient?)
  - OCR quality estimate (is text legible in captures?)
  - Contamination from batcher (are section boundaries clean?)
  - Missing sections
  - Duplicate detection

Never assesses:
  - Task correctness
  - Response quality
  - Scoring criteria
  - Content meaning of any kind
"""
import json
import logging
from datetime import datetime
from pathlib import Path

from PIL import Image

from app.models.evaluation import (
    CaptureEvaluation,
    OcrQualitySummary,
    SectionScore,
)
from app.models.batch import BatchResult
from app.core.tagger import Tagger
from app.core.profile_manager import ProfileManager

logger = logging.getLogger(__name__)

# Minimum screenshots per section to consider it adequately captured
MIN_SCREENSHOTS_PER_SECTION = 1

# OCR quality thresholds
# Estimated from image contrast and text pixel density
OCR_QUALITY_GOOD       = 0.75
OCR_QUALITY_ACCEPTABLE = 0.50

# Overall confidence thresholds for recommended_action
CONFIDENCE_ACCEPT = 0.72
CONFIDENCE_REVIEW = 0.45


class CaptureValidator:
    """
    Validates capture quality for a completed session.

    This class is restricted to capture quality assessment.
    It has no knowledge of task content, scoring, or evaluation logic.

    Critical Boundary (from ARCHITECTURE.md):
        Capture Validator is not a Task Evaluator.

    Assesses (capture quality only):
        - section completeness, screenshot count per section
        - OCR legibility estimate from image properties
        - contamination flags forwarded from the batcher
        - duplicate-filename detection

    Never assesses:
        - whether Response A is better than Response B
        - whether a task response is correct
        - whether scoring criteria are met
        - whether project instructions are followed
        - any dimension of task quality

    This boundary is permanent. Every method on this class must stay
    within capture quality assessment only.
    """

    def __init__(self, session_dir: Path) -> None:
        self._session_dir = session_dir
        self._screenshots_dir = session_dir / "screenshots"
        self._eval_path = session_dir / "evaluation.json"

    def validate(
        self,
        batch_result: BatchResult,
        tagger: Tagger,
        profile_manager: ProfileManager | None = None,
        profile_name: str = "",
    ) -> CaptureEvaluation:
        """
        Run all capture quality checks and produce a CaptureEvaluation.
        Write evaluation.json to the session folder.
        Optionally feed result back to profile proficiency.
        """
        logger.info(
            "Validating capture quality for session: %s",
            self._session_dir.name,
        )

        section_scores = self._score_sections(batch_result, tagger)
        ocr_quality    = self._assess_ocr_quality(tagger)
        missing        = list(batch_result.missing_sections)
        duplicates     = self._find_duplicates(tagger)
        contaminated   = batch_result.contamination_detected

        overall_raw = self._compute_overall_confidence(
            section_scores=section_scores,
            ocr_quality=ocr_quality.overall,
            missing_count=len(missing),
            contaminated=contaminated,
            duplicate_count=len(duplicates),
        )
        # Round once and use the same value for every downstream
        # decision so threshold-edge captures (e.g., 0.7199 -> 0.72)
        # cannot end up with a recommended_action that disagrees
        # with the persisted overall_capture_confidence.
        overall = round(overall_raw, 4)

        action = self._recommend_action(overall, missing, contaminated)

        capture_complete = (
            not missing
            and not contaminated
            and overall >= CONFIDENCE_ACCEPT
        )

        evaluation = CaptureEvaluation(
            session_id=self._session_dir.name,
            evaluated_at=datetime.now().isoformat(),
            capture_complete=capture_complete,
            section_scores=section_scores,
            missing_sections=missing,
            duplicate_sections=duplicates,
            ocr_quality=ocr_quality,
            overall_capture_confidence=overall,
            recommended_action=action,
        )

        write_ok = self._write(evaluation)

        # Feed back to profile proficiency only when the evaluation
        # was actually persisted. If the disk write failed we don't
        # want profile proficiency to drift away from the evidence
        # on disk — the next session would have no persisted record
        # to reconcile with.
        if profile_manager and profile_name:
            if write_ok:
                profile_manager.record_session_result(
                    profile_name=profile_name,
                    capture_confidence=overall,
                    success=(action == "accept"),
                )
                logger.info(
                    "Proficiency updated for profile '%s': confidence=%.3f",
                    profile_name, overall,
                )
            else:
                logger.warning(
                    "Skipping proficiency update for '%s' — "
                    "evaluation.json write failed.",
                    profile_name,
                )

        return evaluation

    def validate_from_session(
        self,
        profile_manager: ProfileManager | None = None,
        profile_name: str = "",
    ) -> CaptureEvaluation | None:
        """
        Load batch and tags from an existing session folder
        and run validation. Used for post-hoc validation.
        """
        from app.core.batcher import Batcher

        tagger = Tagger(self._session_dir)
        if not tagger.load_from_session():
            logger.warning(
                "Cannot validate: no tags.json in %s",
                self._session_dir,
            )
            return None

        batcher = Batcher(self._session_dir)
        batch_result = batcher.batch_from_session()

        return self.validate(
            batch_result=batch_result,
            tagger=tagger,
            profile_manager=profile_manager,
            profile_name=profile_name,
        )

    # ----------------------------------------------------------
    # Section scoring — capture quality only
    # ----------------------------------------------------------

    def _score_sections(
        self,
        batch_result: BatchResult,
        tagger: Tagger,
    ) -> dict[str, SectionScore]:
        scores: dict[str, SectionScore] = {}
        tags_by_section = tagger.tags_by_section()

        for group_name, group in batch_result.groups.items():
            shot_count  = len(group.screenshots)
            found       = shot_count >= MIN_SCREENSHOTS_PER_SECTION
            confidence  = group.confidence
            issues: list[str] = []

            if group.missing:
                issues.append("section_missing")
            if group.contamination_flags:
                issues.extend(group.contamination_flags)
            if shot_count == 0 and not group.missing:
                issues.append("no_screenshots_assigned")

            # OCR quality per section
            section_tags = tags_by_section.get(group_name, [])
            ocr = self._ocr_quality_for_files(
                [t.filename for t in section_tags]
            )
            if ocr < OCR_QUALITY_ACCEPTABLE and found:
                issues.append("ocr_quality_below_threshold")

            scores[group_name] = SectionScore(
                found=found,
                confidence=round(confidence, 4),
                screenshot_count=shot_count,
                ocr_quality=round(ocr, 4),
                issues=issues,
            )

        return scores

    # ----------------------------------------------------------
    # OCR quality estimation — capture quality only
    # ----------------------------------------------------------

    def _assess_ocr_quality(self, tagger: Tagger) -> OcrQualitySummary:
        """
        Estimate OCR readability from image properties.
        Uses contrast and edge density as proxies for text legibility.
        Does not read or interpret text content.
        """
        tags_by_section = tagger.tags_by_section()
        by_section: dict[str, float] = {}
        all_scores: list[float] = []

        for section_type, tags in tags_by_section.items():
            filenames = [t.filename for t in tags]
            score = self._ocr_quality_for_files(filenames)
            by_section[section_type] = round(score, 4)
            all_scores.extend([score] * len(filenames))

        overall = (
            round(sum(all_scores) / len(all_scores), 4)
            if all_scores else 0.0
        )
        return OcrQualitySummary(overall=overall, by_section=by_section)

    def _ocr_quality_for_files(self, filenames: list[str]) -> float:
        if not filenames:
            return 0.0
        # Treat unreadable/missing screenshots as 0.0 so they pull
        # the section average down. Silently dropping them would let
        # a section that lost most of its captures still report the
        # OCR score of its few surviving images.
        scores: list[float] = []
        for filename in filenames:
            path = self._screenshots_dir / filename
            score = self._estimate_ocr_quality(path)
            scores.append(score if score is not None else 0.0)
        return round(sum(scores) / len(scores), 4)

    def _estimate_ocr_quality(self, path: Path) -> float | None:
        """
        Estimate text legibility from image contrast and edge density.
        Returns 0.0-1.0. Higher = more likely to OCR well.
        Does not read or interpret any text content.
        """
        try:
            if not path.exists():
                return None
            with Image.open(path) as img:
                grey = img.convert("L")
                pixels = list(grey.getdata())
                if not pixels:
                    return None

                # Contrast: standard deviation of pixel values
                mean = sum(pixels) / len(pixels)
                variance = sum((p - mean) ** 2 for p in pixels) / len(pixels)
                std_dev = variance ** 0.5

                # Normalise: std_dev of ~60+ suggests good contrast for text
                contrast_score = min(std_dev / 80.0, 1.0)

                # Edge density: fraction of pixels that differ
                # significantly from their neighbours (proxy for text edges)
                w, h = grey.size
                edge_count = 0
                sample_step = max(1, (w * h) // 2000)
                sample_pixels = pixels[::sample_step]
                prev = sample_pixels[0]
                for px in sample_pixels[1:]:
                    if abs(px - prev) > 20:
                        edge_count += 1
                    prev = px
                edge_score = min(edge_count / max(len(sample_pixels), 1), 1.0)
                edge_score = edge_score * 2.5  # scale up — text is edge-rich

                combined = (contrast_score * 0.6) + (min(edge_score, 1.0) * 0.4)
                return round(min(combined, 1.0), 4)
        except Exception as exc:
            logger.debug("OCR quality estimation failed for %s: %s", path, exc)
            return None

    # ----------------------------------------------------------
    # Duplicate detection
    # ----------------------------------------------------------

    def _find_duplicates(self, tagger: Tagger) -> list[str]:
        """
        Find filenames that appear more than once in the tag list.
        Indicates a capture loop error, not a content problem.
        """
        seen: dict[str, int] = {}
        for tag in tagger.get_tags():
            seen[tag.filename] = seen.get(tag.filename, 0) + 1
        return [f for f, count in seen.items() if count > 1]

    # ----------------------------------------------------------
    # Scoring and recommendation
    # ----------------------------------------------------------

    def _compute_overall_confidence(
        self,
        section_scores: dict[str, SectionScore],
        ocr_quality: float,
        missing_count: int,
        contaminated: bool,
        duplicate_count: int,
    ) -> float:
        if not section_scores:
            return 0.0

        # Base: average section confidence weighted by screenshot count
        total_weight = 0
        weighted_sum = 0.0
        for score in section_scores.values():
            weight = max(score.screenshot_count, 1)
            weighted_sum += score.confidence * weight
            total_weight += weight
        base = weighted_sum / total_weight if total_weight > 0 else 0.0

        # OCR contributes 25%
        combined = base * 0.75 + ocr_quality * 0.25

        # Penalties
        combined -= missing_count * 0.08
        if contaminated:
            combined -= 0.15
        combined -= duplicate_count * 0.03

        return max(round(combined, 4), 0.0)

    def _recommend_action(
        self,
        confidence: float,
        missing: list[str],
        contaminated: bool,
    ) -> str:
        if contaminated:
            return "retry"
        critical_missing = {"prompt", "response_a", "response_b"}
        if critical_missing & set(missing):
            return "retry"
        # Any other missing section blocks 'accept'. The current
        # batcher only flags critical sections as missing, so this
        # branch is forward-compat: if a future batcher starts
        # tracking non-critical absences, an incomplete capture
        # never returns 'accept'.
        if missing:
            return "review" if confidence >= CONFIDENCE_REVIEW else "retry"
        if confidence >= CONFIDENCE_ACCEPT:
            return "accept"
        if confidence >= CONFIDENCE_REVIEW:
            return "review"
        return "retry"

    # ----------------------------------------------------------
    # Write
    # ----------------------------------------------------------

    def _write(self, evaluation: CaptureEvaluation) -> bool:
        try:
            self._eval_path.write_text(
                json.dumps(evaluation.as_dict(), indent=2),
                encoding="utf-8",
            )
            logger.info(
                "evaluation.json written: action=%s confidence=%.3f",
                evaluation.recommended_action,
                evaluation.overall_capture_confidence,
            )
            return True
        except Exception as exc:
            logger.warning("Failed to write evaluation.json: %s", exc)
            return False
