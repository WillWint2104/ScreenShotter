"""
region_preview.py

Persistent translucent border shown around the selected capture
region so the user can visually confirm what was selected.
Stays visible until capture starts or the user resets.
Transparent to all mouse input — does not interfere with the
underlying page.
"""
from __future__ import annotations
from PySide6.QtWidgets import QWidget
from PySide6.QtCore import Qt
from PySide6.QtGui import QPainter, QColor, QPen
from app.models.capture_config import RegionCoords


class RegionPreview(QWidget):
    """Always-on-top border that outlines the selected capture region."""

    def __init__(self, region: RegionCoords) -> None:
        super().__init__()
        self._region = region
        self._setup_window()
        self._position()

    def _setup_window(self) -> None:
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint |
            Qt.WindowType.WindowStaysOnTopHint |
            Qt.WindowType.Tool |
            Qt.WindowType.WindowTransparentForInput
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)

    def _position(self) -> None:
        r = self._region
        border = 3
        self.setGeometry(
            r.x - border,
            r.y - border,
            r.width + border * 2,
            r.height + border * 2,
        )

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        colour = QColor(232, 255, 71, 100)  # yellow at ~40% opacity
        pen = QPen(colour, 2)
        pen.setStyle(Qt.PenStyle.DashLine)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        rect = self.rect().adjusted(2, 2, -2, -2)
        painter.drawRect(rect)
