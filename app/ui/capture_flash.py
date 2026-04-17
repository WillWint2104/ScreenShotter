"""
capture_flash.py

Draws a brief coloured border around the captured region
after each screenshot is taken. Confirms visually that the
correct area was grabbed. Fades out after 400ms.
Does not appear inside screenshots.
"""
from __future__ import annotations
from PySide6.QtWidgets import QWidget
from PySide6.QtCore import Qt, QTimer, QRect
from PySide6.QtGui import QPainter, QColor, QPen
from app.models.capture_config import RegionCoords
from app.utils.screen_utils import logical_to_physical


class CaptureFlash(QWidget):
    """Borderless always-on-top widget that flashes around capture region."""

    FLASH_MS = 400

    def __init__(self, region: RegionCoords) -> None:
        super().__init__()
        self._region = region
        self._opacity = 1.0
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
        # Use logical coordinates for Qt window positioning
        r = self._region
        border = 3
        self.setGeometry(
            r.x - border,
            r.y - border,
            r.width + border * 2,
            r.height + border * 2
        )

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        colour = QColor(232, 255, 71, int(255 * self._opacity))
        pen = QPen(colour, 3)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        rect = self.rect().adjusted(2, 2, -2, -2)
        painter.drawRect(rect)

    def flash(self) -> None:
        """Show the flash border and fade out after FLASH_MS."""
        self._opacity = 1.0
        self.show()
        self.raise_()
        QTimer.singleShot(self.FLASH_MS, self._fade_out)

    def _fade_out(self) -> None:
        self._opacity = 0.0
        self.update()
        QTimer.singleShot(80, self.hide)
