from dataclasses import dataclass, field
from typing import Any

SectionType = str
# Known values: conversation_history, prompt, response_a,
# response_b, instructions, examples, ui_fields, buttons, unknown

@dataclass
class SectionRect:
    x: int
    y: int
    width: int
    height: int

    def as_dict(self) -> dict:
        return {"x": self.x, "y": self.y,
                "width": self.width, "height": self.height}

@dataclass
class DiscoveredSection:
    section_id: str
    section_type: SectionType
    confidence: float
    rect: SectionRect
    element_ref: Any        # UIA element reference, opaque to this model
    depth: int
    can_scroll_vertical: bool
    can_scroll_horizontal: bool
    scroll_percent: float
    source: str             # "profile" | "heuristic"
    notes: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "section_id": self.section_id,
            "section_type": self.section_type,
            "confidence": self.confidence,
            "rect": self.rect.as_dict(),
            "depth": self.depth,
            "can_scroll_vertical": self.can_scroll_vertical,
            "can_scroll_horizontal": self.can_scroll_horizontal,
            "scroll_percent": self.scroll_percent,
            "source": self.source,
            "notes": self.notes,
        }

@dataclass
class TaggedScreenshot:
    filename: str
    capture_index: int
    section_id: str
    section_type: SectionType
    scroll_position: float
    rect: SectionRect
    timestamp: str

    def as_dict(self) -> dict:
        return {
            "filename": self.filename,
            "capture_index": self.capture_index,
            "section_id": self.section_id,
            "section_type": self.section_type,
            "scroll_position": self.scroll_position,
            "rect": self.rect.as_dict(),
            "timestamp": self.timestamp,
        }
