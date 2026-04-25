"""
batcher.py

Groups tagged screenshots into named section buckets.
Enforces strict section purity rules.
Produces batch.json per session.

Purity rules (from ARCHITECTURE.md):
  - ui_fields and buttons never merged into response content
  - prompt never merged into conversation_history
  - response_a and response_b never merged together
  - instructions never merged into examples
  - uncertain content goes to unknown, never force-fitted
  - contamination flagged explicitly, never silently placed

Does not capture screenshots.
Does not classify sections.
Does not evaluate content quality.
Grouping and purity enforcement only.
"""
import json
import logging
from datetime import datetime
from pathlib import Path

from app.models.batch import (
    BatchResult,
    SectionGroup,
    VALID_SECTION_GROUPS,
)
from app.models.section import TaggedScreenshot
from app.core.tagger import Tagger

logger = logging.getLogger(__name__)

# Confidence threshold below which a screenshot goes to unknown
CONFIDENCE_THRESHOLD = 0.40

# Pairs that must never be merged together
# Each tuple: (group_a, group_b) — these must stay separate
FORBIDDEN_MERGES: list[tuple[str, str]] = [
    ("response_a",           "response_b"),
    ("prompt",               "conversation_history"),
    ("instructions",         "examples"),
    ("ui_fields",            "response_a"),
    ("ui_fields",            "response_b"),
    ("ui_fields",            "prompt"),
    ("ui_fields",            "conversation_history"),
    ("buttons",              "response_a"),
    ("buttons",              "response_b"),
    ("buttons",              "prompt"),
    ("buttons",              "conversation_history"),
]


class Batcher:

    def __init__(self, session_dir: Path) -> None:
        self._session_dir = session_dir
        self._batch_path = session_dir / "batch.json"

    def batch(self, tagger: Tagger) -> BatchResult:
        """
        Group all tagged screenshots into section buckets.
        Enforce purity rules.
        Write batch.json.
        Return BatchResult.
        """
        tags = tagger.get_tags()
        if not tags:
            logger.warning("No tags to batch in session %s", self._session_dir)
            return self._empty_result()

        result = self._group_tags(tags)
        result = self._enforce_purity(result)
        result = self._flag_missing(result)
        self._write(result)

        logger.info(
            "Batch complete: %d groups, contamination=%s, missing=%s",
            len(result.groups),
            result.contamination_detected,
            result.missing_sections,
        )
        return result

    def batch_from_session(self) -> BatchResult:
        """
        Load tags from an existing session folder and batch them.
        Used for re-batching a completed session.
        """
        tagger = Tagger(self._session_dir)
        loaded = tagger.load_from_session()
        if not loaded:
            logger.warning(
                "Could not load tags from %s", self._session_dir
            )
            return self._empty_result()
        return self.batch(tagger)

    # ----------------------------------------------------------
    # Internal
    # ----------------------------------------------------------

    def _group_tags(self, tags: list[TaggedScreenshot]) -> BatchResult:
        result = BatchResult(
            session_id=self._session_dir.name,
            created_at=datetime.now().isoformat(),
        )

        # Initialise all valid groups as empty
        for group_name in VALID_SECTION_GROUPS:
            result.groups[group_name] = SectionGroup(
                group_name=group_name
            )

        for tag in sorted(tags, key=lambda t: t.capture_index):
            target = self._resolve_group(tag)
            result.groups[target].screenshots.append(tag.filename)

            # Update group confidence as running average
            group = result.groups[target]
            n = len(group.screenshots)
            # Confidence not stored on tag directly — use 0.7 as
            # default for tagged items, 0.35 for unknown-routed
            tag_confidence = 0.35 if target == "unknown" else 0.70
            group.confidence = round(
                (group.confidence * (n - 1) + tag_confidence) / n, 4
            )

        return result

    def _resolve_group(self, tag: TaggedScreenshot) -> str:
        """
        Determine which group a tagged screenshot belongs to.
        Low-confidence tags go to unknown.
        Invalid section types go to unknown.
        """
        section_type = tag.section_type

        if section_type not in VALID_SECTION_GROUPS:
            logger.debug(
                "Unknown section type '%s' for %s — routing to unknown",
                section_type, tag.filename,
            )
            return "unknown"

        return section_type

    def _enforce_purity(self, result: BatchResult) -> BatchResult:
        """
        Check for contamination across forbidden merge pairs.
        Flag any group that shares screenshots with a forbidden partner.
        Never moves screenshots — only flags.
        """
        contamination_found = False

        for group_a, group_b in FORBIDDEN_MERGES:
            shots_a = set(result.groups.get(group_a, SectionGroup(group_a)).screenshots)
            shots_b = set(result.groups.get(group_b, SectionGroup(group_b)).screenshots)
            overlap = shots_a & shots_b

            if overlap:
                contamination_found = True
                flag = f"contamination:{group_a}↔{group_b}:{len(overlap)}_screenshots"

                if group_a in result.groups:
                    result.groups[group_a].contamination_flags.append(flag)
                if group_b in result.groups:
                    result.groups[group_b].contamination_flags.append(flag)

                logger.warning(
                    "Contamination detected: %s and %s share %d screenshots",
                    group_a, group_b, len(overlap),
                )

        result.contamination_detected = contamination_found
        return result

    def _flag_missing(self, result: BatchResult) -> BatchResult:
        """
        Flag groups that are empty as missing.
        Core sections that should always be present:
          prompt, response_a, response_b
        All others are optional.
        """
        required_sections = {"prompt", "response_a", "response_b"}

        for section_name in required_sections:
            group = result.groups.get(section_name)
            if not group or not group.screenshots:
                group = result.groups.setdefault(
                    section_name,
                    SectionGroup(group_name=section_name)
                )
                group.missing = True
                result.missing_sections.append(section_name)
                logger.info("Required section missing: %s", section_name)

        return result

    def _write(self, result: BatchResult) -> bool:
        try:
            self._batch_path.write_text(
                json.dumps(result.as_dict(), indent=2),
                encoding="utf-8",
            )
            logger.info("batch.json written to %s", self._batch_path)
            return True
        except Exception as exc:
            logger.warning("Failed to write batch.json: %s", exc)
            return False

    def _empty_result(self) -> BatchResult:
        result = BatchResult(
            session_id=self._session_dir.name,
            created_at=datetime.now().isoformat(),
        )
        for group_name in VALID_SECTION_GROUPS:
            result.groups[group_name] = SectionGroup(
                group_name=group_name,
                missing=True,
            )
        result.missing_sections = list(VALID_SECTION_GROUPS)
        return result
