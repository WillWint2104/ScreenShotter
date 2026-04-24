"""
section_discoverer.py

Finds and classifies all scrollable sections in the active
browser window. Uses profile rules if a profile is matched,
falls back to general heuristics if not.

Returns an ordered list of DiscoveredSection objects,
top-to-bottom by vertical position on screen.

Does not capture screenshots.
Does not scroll.
Does not click anything.
Discovery only.
"""
import logging
import uuid
from typing import Any

from app.models.section import DiscoveredSection, SectionRect, SectionType
from app.models.profile import CaptureProfile, ProfileMatchResult
from app.utils.uia_utils import (
    get_active_browser_window,
    get_scrollable_regions,
    get_element_metadata,
)

logger = logging.getLogger(__name__)

# Heuristic classification rules
# Each entry: (section_type, position_hint, min_width_ratio, keywords)
# position_hint: "top" | "middle" | "bottom" | "any"
# min_width_ratio: fraction of browser window width (0.0-1.0)
HEURISTIC_RULES: list[tuple[str, str, float, list[str]]] = [
    ("conversation_history", "top",    0.2, ["conversation", "history", "chat", "message"]),
    ("prompt",               "top",    0.3, ["prompt", "question", "task", "instruction"]),
    ("response_a",           "middle", 0.3, ["response a", "option a", "answer a", "model a"]),
    ("response_b",           "middle", 0.3, ["response b", "option b", "answer b", "model b"]),
    ("instructions",         "top",    0.4, ["instruction", "guideline", "overview", "project"]),
    ("examples",             "any",    0.3, ["example", "sample", "reference"]),
    ("ui_fields",            "bottom", 0.3, ["score", "rating", "field", "input", "select"]),
    ("buttons",              "bottom", 0.1, ["submit", "next", "save", "flag", "skip"]),
]


class SectionDiscoverer:

    def __init__(
        self,
        profile: CaptureProfile | None = None,
        profile_match: ProfileMatchResult | None = None,
    ) -> None:
        self._profile = profile
        self._profile_match = profile_match

    def discover(self) -> list[DiscoveredSection]:
        """
        Find the active browser window and return all
        classified scrollable sections within it,
        sorted top-to-bottom.

        Returns empty list if no browser window found.
        """
        browser = get_active_browser_window()
        if not browser:
            logger.warning("No active browser window found.")
            return []

        logger.info(
            "Browser found: %s on monitor %d rect=%s",
            browser["browser"],
            browser["monitor"],
            browser["rect"],
        )

        raw_regions = get_scrollable_regions(browser["hwnd"])
        if not raw_regions:
            logger.warning("No scrollable regions found in browser window.")
            return []

        logger.info("Raw scrollable regions found: %d", len(raw_regions))

        browser_rect = browser["rect"]
        sections: list[DiscoveredSection] = []

        for region in raw_regions:
            section = self._classify_region(region, browser_rect)
            if section:
                sections.append(section)

        # Sort top-to-bottom
        sections.sort(key=lambda s: s.rect.y)

        logger.info(
            "Sections discovered: %d — %s",
            len(sections),
            [s.section_type for s in sections],
        )
        return sections

    def _classify_region(
        self,
        region: dict,
        browser_rect: dict,
    ) -> DiscoveredSection | None:
        rect_data = region.get("rect", {})
        rect = SectionRect(
            x=rect_data.get("x", 0),
            y=rect_data.get("y", 0),
            width=rect_data.get("width", 0),
            height=rect_data.get("height", 0),
        )

        # Skip tiny regions
        if rect.width < 100 or rect.height < 100:
            return None

        element_ref = region.get("element_ref")
        depth = region.get("depth", 0)

        # Try profile-based classification first
        if self._profile:
            result = self._classify_with_profile(rect, element_ref, browser_rect)
            if result:
                section_type, confidence, notes = result
                return DiscoveredSection(
                    section_id=str(uuid.uuid4())[:8],
                    section_type=section_type,
                    confidence=confidence,
                    rect=rect,
                    element_ref=element_ref,
                    depth=depth,
                    can_scroll_vertical=region.get("can_scroll_vertical", False),
                    can_scroll_horizontal=region.get("can_scroll_horizontal", False),
                    scroll_percent=region.get("scroll_percent", 0.0),
                    source="profile",
                    notes=notes,
                )

        # Fall back to heuristics
        section_type, confidence, notes = self._classify_with_heuristics(
            rect, element_ref, browser_rect
        )
        return DiscoveredSection(
            section_id=str(uuid.uuid4())[:8],
            section_type=section_type,
            confidence=confidence,
            rect=rect,
            element_ref=element_ref,
            depth=depth,
            can_scroll_vertical=region.get("can_scroll_vertical", False),
            can_scroll_horizontal=region.get("can_scroll_horizontal", False),
            scroll_percent=region.get("scroll_percent", 0.0),
            source="heuristic",
            notes=notes,
        )

    def _classify_with_profile(
        self,
        rect: SectionRect,
        element_ref: Any,
        browser_rect: dict,
    ) -> tuple[str, float, list[str]] | None:
        if not self._profile or not self._profile.section_definitions:
            return None

        browser_width = browser_rect.get("width", 1)
        browser_height = browser_rect.get("height", 1)
        width_ratio = rect.width / browser_width
        rel_y = rect.y / browser_height

        for defn in self._profile.section_definitions:
            if rect.width < defn.min_width_ratio * browser_width:
                continue
            if rect.height < defn.min_height_px:
                continue
            if defn.position_hint != "any":
                if defn.position_hint == "top" and rel_y > 0.4:
                    continue
                if defn.position_hint == "middle" and (rel_y < 0.2 or rel_y > 0.8):
                    continue
                if defn.position_hint == "bottom" and rel_y < 0.6:
                    continue

            # Check element name against hints
            meta = _safe_get_metadata(element_ref)
            name_lower = meta.get("name", "").lower()
            hint_matches = [
                h for h in defn.detection_hints
                if h.lower() in name_lower
            ]
            confidence = 0.6 + (0.1 * len(hint_matches))
            confidence = min(confidence, 0.95)

            return (
                defn.section_type,
                round(confidence, 3),
                [f"profile_rule:{defn.section_type}"] + hint_matches,
            )

        return None

    def _classify_with_heuristics(
        self,
        rect: SectionRect,
        element_ref: Any,
        browser_rect: dict,
    ) -> tuple[str, float, list[str]]:
        browser_width = browser_rect.get("width", 1)
        browser_height = browser_rect.get("height", 1)
        rel_y = rect.y / browser_height if browser_height > 0 else 0.5
        width_ratio = rect.width / browser_width if browser_width > 0 else 0.5

        meta = _safe_get_metadata(element_ref)
        name_lower = meta.get("name", "").lower()

        for section_type, position_hint, min_w_ratio, keywords in HEURISTIC_RULES:
            if width_ratio < min_w_ratio:
                continue

            if position_hint == "top" and rel_y > 0.45:
                continue
            if position_hint == "middle" and (rel_y < 0.15 or rel_y > 0.85):
                continue
            if position_hint == "bottom" and rel_y < 0.55:
                continue

            matches = [k for k in keywords if k in name_lower]
            if matches:
                confidence = 0.5 + (0.08 * len(matches))
                return (
                    section_type,
                    round(min(confidence, 0.85), 3),
                    [f"keyword:{m}" for m in matches],
                )

        # Position-based fallback when no keywords match
        section_type, notes = _position_fallback(rel_y, width_ratio)
        return section_type, 0.35, notes


def _position_fallback(
    rel_y: float,
    width_ratio: float,
) -> tuple[str, list[str]]:
    if rel_y < 0.25:
        return "prompt", ["position:top"]
    if rel_y > 0.75 and width_ratio > 0.6:
        return "ui_fields", ["position:bottom_wide"]
    if 0.25 <= rel_y <= 0.75:
        if width_ratio > 0.45:
            return "response_a", ["position:middle_wide"]
        return "conversation_history", ["position:middle_narrow"]
    return "unknown", ["position:unclassified"]


def _safe_get_metadata(element_ref: Any) -> dict:
    if element_ref is None:
        return {"name": "", "role": ""}
    try:
        meta = get_element_metadata(element_ref)
        return meta if meta else {"name": "", "role": ""}
    except Exception:
        return {"name": "", "role": ""}
