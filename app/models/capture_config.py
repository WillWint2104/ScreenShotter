from __future__ import annotations
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from PIL.Image import Image as PILImage


@dataclass
class RegionCoords:
    x: int
    y: int
    width: int
    height: int

    def as_dict(self) -> dict:
        return {"x": self.x, "y": self.y,
                "width": self.width, "height": self.height}

    def is_valid(self) -> bool:
        return self.width > 10 and self.height > 10


@dataclass
class CaptureConfig:
    region: RegionCoords
    delay_ms: int = 800
    similarity_threshold: float = 0.98
    end_reference: PILImage | None = field(default=None, repr=False)
