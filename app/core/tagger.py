"""
tagger.py

Attaches section metadata to screenshots as they are saved.
Produces a TaggedScreenshot record for every captured frame.
Writes a tags index (tags.json) into the session folder.

Does not capture screenshots.
Does not scroll.
Does not classify sections.
Tagging only.
"""
import json
import logging
from datetime import datetime
from pathlib import Path

from app.models.section import (
    DiscoveredSection,
    SectionRect,
    TaggedScreenshot,
)

logger = logging.getLogger(__name__)


class Tagger:

    def __init__(self, session_dir: Path) -> None:
        self._session_dir = session_dir
        self._tags: list[TaggedScreenshot] = []
        self._tags_path = session_dir / "tags.json"

    def tag(
        self,
        filename: str,
        capture_index: int,
        section: DiscoveredSection,
        scroll_position: float = 0.0,
    ) -> TaggedScreenshot:
        """
        Create and store a tag for one screenshot.
        Called immediately after each screenshot is saved.
        """
        # Snapshot the rect: store a fresh SectionRect so later
        # mutations of section.rect (live UIA bounds shift, etc.)
        # cannot retroactively change historical tags.
        rect_snapshot = SectionRect(
            x=section.rect.x,
            y=section.rect.y,
            width=section.rect.width,
            height=section.rect.height,
        )
        tagged = TaggedScreenshot(
            filename=filename,
            capture_index=capture_index,
            section_id=section.section_id,
            section_type=section.section_type,
            scroll_position=round(scroll_position, 4),
            rect=rect_snapshot,
            timestamp=datetime.now().isoformat(),
        )
        self._tags.append(tagged)
        logger.debug(
            "Tagged %s as %s (section=%s index=%d)",
            filename,
            section.section_type,
            section.section_id,
            capture_index,
        )
        return tagged

    def flush(self) -> bool:
        """
        Write all accumulated tags to tags.json.
        Call once after capture is complete.
        Safe to call multiple times — overwrites previous flush.
        """
        try:
            data = {
                "total_screenshots": len(self._tags),
                "flushed_at": datetime.now().isoformat(),
                "tags": [t.as_dict() for t in self._tags],
            }
            self._tags_path.write_text(
                json.dumps(data, indent=2),
                encoding="utf-8",
            )
            logger.info(
                "Tags flushed: %d entries to %s",
                len(self._tags),
                self._tags_path,
            )
            return True
        except (OSError, TypeError, ValueError) as exc:
            logger.warning("Failed to flush tags: %s", exc, exc_info=True)
            return False

    def get_tags(self) -> list[TaggedScreenshot]:
        return list(self._tags)

    def tags_by_section(self) -> dict[str, list[TaggedScreenshot]]:
        """
        Return tags grouped by section_type.
        Useful for batcher and capture validator.
        """
        grouped: dict[str, list[TaggedScreenshot]] = {}
        for tag in self._tags:
            grouped.setdefault(tag.section_type, []).append(tag)
        return grouped

    def load_from_session(self) -> bool:
        """
        Load tags from an existing tags.json in the session folder.
        Used when resuming or validating a completed session.
        """
        if not self._tags_path.exists():
            logger.warning("No tags.json found at %s", self._tags_path)
            return False
        try:
            data = json.loads(
                self._tags_path.read_text(encoding="utf-8")
            )
            # Build into a temporary list first so a malformed entry
            # cannot leave self._tags half-loaded on failure.
            loaded_tags: list[TaggedScreenshot] = []
            for entry in data.get("tags", []):
                rect_data = entry.get("rect", {})
                rect = SectionRect(
                    x=rect_data.get("x", 0),
                    y=rect_data.get("y", 0),
                    width=rect_data.get("width", 0),
                    height=rect_data.get("height", 0),
                )
                loaded_tags.append(TaggedScreenshot(
                    filename=entry.get("filename", ""),
                    capture_index=entry.get("capture_index", 0),
                    section_id=entry.get("section_id", ""),
                    section_type=entry.get("section_type", "unknown"),
                    scroll_position=entry.get("scroll_position", 0.0),
                    rect=rect,
                    timestamp=entry.get("timestamp", ""),
                ))
            self._tags = loaded_tags
            logger.info(
                "Loaded %d tags from %s",
                len(self._tags),
                self._tags_path,
            )
            return True
        except (
            OSError, json.JSONDecodeError, TypeError, ValueError,
            KeyError, AttributeError,
        ) as exc:
            logger.warning("Failed to load tags: %s", exc, exc_info=True)
            return False

    @property
    def count(self) -> int:
        return len(self._tags)
