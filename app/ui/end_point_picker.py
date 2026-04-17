"""
end_point_picker.py

Floating toolbar shown while the user scrolls to their desired
end position. Sits away from the capture region (same placement
logic as CaptureOverlay). Also draws a horizontal guide line
across the region so the user can see the boundary.

Emits:
    confirmed()  — user clicked Confirm or pressed Enter
    cancelled()  — user clicked Cancel or pressed Escape
"""
from __future__ import annotations
from PySide6.QtWidgets import (
    QWidget, QHBoxLayout, QLabel, QPushButton, QApplication,
)
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QPainter, QColor, QPen, QKeySequence, QShortcut
from app.models.capture_config import RegionCoords


class EndPointPicker(QWidget):
    """Small floating bar: 'Scroll to end position → [✓ Confirm] [✗ Cancel]'"""

    confirmed = Signal()
    cancelled = Signal()

    def __init__(self, region: RegionCoords) -> None:
        super().__init__()
        self._region = region
        self._build_ui()
        self._setup_window()
        self._setup_hotkeys()
        self._guide = _EndGuide(region)

    def _setup_window(self) -> None:
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint |
            Qt.WindowType.WindowStaysOnTopHint |
            Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setFixedHeight(32)
        self.setMinimumWidth(300)

    def _build_ui(self) -> None:
        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 0, 10, 0)
        layout.setSpacing(8)

        label = QLabel("Scroll to end position")
        label.setStyleSheet(
            "color: #ccc; font-size: 11px;"
        )
        layout.addWidget(label)

        layout.addStretch()

        confirm_btn = QPushButton("\u2713  Confirm")
        confirm_btn.setFixedHeight(22)
        confirm_btn.setStyleSheet("""
            QPushButton {
                background: #1a2e1a;
                border: 1px solid #66cc66;
                border-radius: 3px;
                color: #66cc66;
                font-size: 11px;
                padding: 0 10px;
            }
            QPushButton:hover { background: #66cc66; color: #0e0e0f; }
        """)
        confirm_btn.clicked.connect(self._on_confirm)
        layout.addWidget(confirm_btn)

        cancel_btn = QPushButton("\u2717")
        cancel_btn.setFixedSize(22, 22)
        cancel_btn.setStyleSheet("""
            QPushButton {
                background: #2a1a1a;
                border: 1px solid #ff4444;
                border-radius: 3px;
                color: #ff4444;
                font-size: 11px;
            }
            QPushButton:hover { background: #ff4444; color: #fff; }
        """)
        cancel_btn.clicked.connect(self._on_cancel)
        layout.addWidget(cancel_btn)

        self.setStyleSheet("""
            QWidget {
                background: rgba(20, 20, 22, 230);
                border: 1px solid #444;
                border-radius: 4px;
            }
        """)

    def _setup_hotkeys(self) -> None:
        sc_confirm = QShortcut(QKeySequence("Return"), self)
        sc_confirm.setContext(Qt.ShortcutContext.ApplicationShortcut)
        sc_confirm.activated.connect(self._on_confirm)

        sc_cancel = QShortcut(QKeySequence("Escape"), self)
        sc_cancel.setContext(Qt.ShortcutContext.ApplicationShortcut)
        sc_cancel.activated.connect(self._on_cancel)

    def _on_confirm(self) -> None:
        self.confirmed.emit()
        self._guide.hide()
        self.hide()

    def _on_cancel(self) -> None:
        self.cancelled.emit()
        self._guide.hide()
        self.hide()

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self._place_away_from_region()
        self._guide.show()

    def _place_away_from_region(self) -> None:
        screen = QApplication.primaryScreen().geometry()
        self.adjustSize()
        w = self.width()
        h = self.height()
        margin = 16
        r = self._region

        candidates = [
            (screen.right() - w - margin, screen.top() + margin),
            (screen.left() + margin, screen.top() + margin),
            (screen.right() - w - margin, screen.bottom() - h - margin),
            (screen.left() + margin, screen.bottom() - h - margin),
        ]

        def overlaps(ox: int, oy: int) -> bool:
            return not (
                ox + w < r.x or ox > r.x + r.width or
                oy + h < r.y or oy > r.y + r.height
            )

        for x, y in candidates:
            if not overlaps(x, y):
                self.move(x, y)
                return
        self.move(candidates[0][0], candidates[0][1])


class _EndGuide(QWidget):
    """
    Horizontal line drawn across the bottom edge of the capture region.
    Transparent to mouse — user can scroll the page underneath.
    """

    def __init__(self, region: RegionCoords) -> None:
        super().__init__()
        self._region = region
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint |
            Qt.WindowType.WindowStaysOnTopHint |
            Qt.WindowType.Tool |
            Qt.WindowType.WindowTransparentForInput
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)

        r = self._region
        line_h = 20
        self.setGeometry(r.x - 10, r.y + r.height - line_h // 2,
                         r.width + 20, line_h)

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        colour = QColor(102, 204, 102, 200)  # green
        pen = QPen(colour, 2)
        pen.setStyle(Qt.PenStyle.DashLine)
        painter.setPen(pen)

        mid_y = self.height() // 2
        painter.drawLine(0, mid_y, self.width(), mid_y)

        # Small label
        painter.setPen(QColor(102, 204, 102, 255))
        from PySide6.QtGui import QFont
        font = QFont("Segoe UI", 8)
        painter.setFont(font)
        painter.drawText(4, mid_y - 4, "END")
