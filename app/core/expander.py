"""
expander.py

Expands collapsed content on a page before capture begins.
Operates top-to-bottom within discovered sections.

Safety rules (all four required before any click):
  1. Element not on protected list
  2. Element near likely content section, not browser chrome
  3. Element appears expandable by role or affordance
  4. Post-click state change detected

Logs every expansion attempt.
Never retries a false candidate.
Never clicks protected elements under any circumstances.

See ARCHITECTURE.md — Expander Safety Rules.
"""
import logging
import time
from dataclasses import dataclass, field
from typing import Any

from app.models.section import DiscoveredSection
from app.utils.uia_utils import (
    get_scrollable_regions,
    get_element_metadata,
    is_protected_element,
)

logger = logging.getLogger(__name__)

# How long to wait after a click before checking state change (seconds)
POST_CLICK_WAIT = 0.6

# Minimum height increase (px) to count as a meaningful state change
MIN_HEIGHT_CHANGE_PX = 10

# Element roles that suggest expandability
EXPANDABLE_ROLES = {
    "button", "togglebutton", "treeitem",
    "tab", "menuitem", "link",
}

# Words in element names that suggest expandability
EXPANDABLE_TRIGGER_WORDS = [
    "show more", "read more", "expand", "see more",
    "view more", "load more", "show all", "more details",
    "show details", "show full", "view full",
]


@dataclass
class ExpansionAttempt:
    element_name: str
    element_role: str
    container_id: str
    pre_height: int
    post_height: int
    state_changed: bool
    action_result: str          # "expanded" | "no_change" | "blocked"

    def as_dict(self) -> dict:
        return {
            "element_name": self.element_name,
            "element_role": self.element_role,
            "container_id": self.container_id,
            "pre_height": self.pre_height,
            "post_height": self.post_height,
            "state_changed": self.state_changed,
            "action_result": self.action_result,
        }


@dataclass
class ExpansionReport:
    attempts: list[ExpansionAttempt] = field(default_factory=list)
    expanded_count: int = 0
    blocked_count: int = 0
    no_change_count: int = 0

    def add(self, attempt: ExpansionAttempt) -> None:
        self.attempts.append(attempt)
        if attempt.action_result == "expanded":
            self.expanded_count += 1
        elif attempt.action_result == "blocked":
            self.blocked_count += 1
        else:
            self.no_change_count += 1

    def as_dict(self) -> dict:
        return {
            "expanded_count": self.expanded_count,
            "blocked_count": self.blocked_count,
            "no_change_count": self.no_change_count,
            "attempts": [a.as_dict() for a in self.attempts],
        }


class Expander:

    def __init__(
        self,
        extra_trigger_words: list[str] | None = None,
        hwnd: int | None = None,
    ) -> None:
        self._trigger_words = EXPANDABLE_TRIGGER_WORDS.copy()
        if extra_trigger_words:
            self._trigger_words.extend(
                w.lower() for w in extra_trigger_words
            )
        self._hwnd = hwnd
        self._false_candidates: set[str] = set()

    def expand_all(
        self,
        sections: list[DiscoveredSection],
    ) -> ExpansionReport:
        """
        Scan all discovered sections for expandable elements.
        Click each safe candidate top-to-bottom.
        Return a full expansion report.
        """
        report = ExpansionReport()

        for section in sorted(sections, key=lambda s: s.rect.y):
            if not section.element_ref:
                continue
            candidates = self._find_candidates_in_section(section)
            for candidate in candidates:
                attempt = self._attempt_expansion(candidate, section)
                report.add(attempt)
                logger.info(
                    "Expansion attempt: %s",
                    attempt.as_dict(),
                )

        logger.info(
            "Expansion complete: expanded=%d blocked=%d no_change=%d",
            report.expanded_count,
            report.blocked_count,
            report.no_change_count,
        )
        return report

    def _find_candidates_in_section(
        self,
        section: DiscoveredSection,
    ) -> list[dict]:
        """
        Find child elements within a section that look expandable.
        Returns list of element metadata dicts with element_ref attached.
        """
        candidates = []
        try:
            element = section.element_ref
            if element is None:
                return []

            children = _get_children(element)
            for child in children:
                meta = _safe_metadata(child)
                if not meta:
                    continue
                if self._is_expandable_candidate(meta, section):
                    meta["element_ref"] = child
                    candidates.append(meta)
        except Exception as exc:
            logger.warning(
                "Error finding candidates in section %s: %s",
                section.section_id, exc,
            )
        return candidates

    def _is_expandable_candidate(
        self,
        meta: dict,
        section: DiscoveredSection,
    ) -> bool:
        """
        Condition 1: not protected
        Condition 2: near content section (not browser chrome)
        Condition 3: role or name suggests expandability
        Condition 4 checked at click time (state change)
        """
        element_ref = meta.get("element_ref")

        # Condition 1 — protected check
        if element_ref and is_protected_element(element_ref):
            return False
        name_lower = meta.get("name", "").lower()
        if any(p in name_lower for p in _PROTECTED_WORDS):
            return False

        # Condition 2 — must be within section bounds
        elem_rect = meta.get("rect", {})
        if not _within_section(elem_rect, section.rect):
            return False

        # Condition 3 — role or trigger word match
        role = meta.get("role", "").lower()
        role_match = role in EXPANDABLE_ROLES
        word_match = any(w in name_lower for w in self._trigger_words)

        return role_match or word_match

    def _attempt_expansion(
        self,
        candidate: dict,
        section: DiscoveredSection,
    ) -> ExpansionAttempt:
        element_ref = candidate.get("element_ref")
        name = candidate.get("name", "")
        role = candidate.get("role", "")
        container_id = section.section_id

        # Skip known false candidates
        candidate_key = f"{container_id}:{name}:{role}"
        if candidate_key in self._false_candidates:
            return ExpansionAttempt(
                element_name=name,
                element_role=role,
                container_id=container_id,
                pre_height=0,
                post_height=0,
                state_changed=False,
                action_result="blocked",
            )

        # Measure pre-click state
        pre_height = _get_section_height(section)

        # Click the element
        try:
            _invoke_element(element_ref)
        except Exception as exc:
            logger.warning("Click failed on '%s': %s", name, exc)
            return ExpansionAttempt(
                element_name=name,
                element_role=role,
                container_id=container_id,
                pre_height=pre_height,
                post_height=pre_height,
                state_changed=False,
                action_result="blocked",
            )

        # Wait for DOM to settle
        time.sleep(POST_CLICK_WAIT)

        # Condition 4 — measure post-click state change
        post_height = _get_section_height(section)
        state_changed = (post_height - pre_height) >= MIN_HEIGHT_CHANGE_PX

        if not state_changed:
            self._false_candidates.add(candidate_key)
            return ExpansionAttempt(
                element_name=name,
                element_role=role,
                container_id=container_id,
                pre_height=pre_height,
                post_height=post_height,
                state_changed=False,
                action_result="no_change",
            )

        return ExpansionAttempt(
            element_name=name,
            element_role=role,
            container_id=container_id,
            pre_height=pre_height,
            post_height=post_height,
            state_changed=True,
            action_result="expanded",
        )


# ----------------------------------------------------------
# Private helpers
# ----------------------------------------------------------

_PROTECTED_WORDS = {
    "submit", "escape", "cancel", "skip", "next",
    "back", "flag", "close", "dismiss", "abort",
    "finish", "complete", "done",
}


def _safe_metadata(element_ref: Any) -> dict | None:
    try:
        from app.utils.uia_utils import get_element_metadata
        return get_element_metadata(element_ref)
    except Exception:
        return None


def _get_children(element_ref: Any) -> list[Any]:
    try:
        import comtypes
        walker = None
        children = []
        try:
            import comtypes.client
            UIA = comtypes.client.CreateObject(
                "{ff48dba4-60ef-4201-aa87-54103eef594e}",
                interface=comtypes.gen.UIAutomationClient.IUIAutomation,
            )
            walker = UIA.ControlViewWalker
            child = walker.GetFirstChildElement(element_ref)
            while child is not None:
                children.append(child)
                child = walker.GetNextSiblingElement(child)
        except Exception:
            pass
        return children
    except Exception:
        return []


def _within_section(
    elem_rect: dict,
    section_rect: "SectionRect",
) -> bool:
    if not elem_rect:
        return False
    ex = elem_rect.get("x", 0)
    ey = elem_rect.get("y", 0)
    return (
        section_rect.x <= ex <= section_rect.x + section_rect.width
        and section_rect.y <= ey <= section_rect.y + section_rect.height
    )


def _get_section_height(section: DiscoveredSection) -> int:
    try:
        meta = _safe_metadata(section.element_ref)
        if meta:
            return meta.get("rect", {}).get("height", section.rect.height)
    except Exception:
        pass
    return section.rect.height


def _invoke_element(element_ref: Any) -> None:
    try:
        import comtypes
        import comtypes.gen.UIAutomationClient as UIA
        invoke = element_ref.GetCurrentPattern(UIA.UIA_InvokePatternId)
        if invoke:
            invoke.QueryInterface(UIA.IUIAutomationInvokePattern).Invoke()
            return
    except Exception:
        pass
    try:
        element_ref.SetFocus()
        import pyautogui
        pyautogui.press("space")
    except Exception:
        pass
