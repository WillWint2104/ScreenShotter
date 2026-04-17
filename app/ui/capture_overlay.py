"""
capture_overlay.py

Small always-on-top corner overlay shown during capture.
Never steals focus. Shows shot count and cycle state.
F9 stops capture from any window.
Repositions away from the selected capture region.
"""
from __future__ import annotations
from PySide6.QtWidgets import QWidget, QHBoxLayout, QLabel, QPushButton
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QKeySequence, QShortcut
from app.models.capture_config import RegionCoords


class CaptureOverlay(QWidget):
    stop_requested = Signal()

    def __init__(self, region: RegionCoords) -> None:
        super().__init__()
        self._region = region
        self._build_ui()
        self._setup_window()
        self._setup_hotkey()

    def _setup_window(self) -> None:
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint |
            Qt.WindowType.WindowStaysOnTopHint |
            Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setFixedHeight(28)
        self.setMinimumWidth(200)

    def _build_ui(self) -> None:
        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 0, 8, 0)
        layout.setSpacing(8)

        self._dot = QLabel("\u25cf")
        self._dot.setStyleSheet("color: #ff4444; font-size: 10px;")
        layout.addWidget(self._dot)

        self._shot_label = QLabel("000")
        self._shot_label.setStyleSheet(
            "color: #e8ff47; font-family: monospace; font-size: 11px;"
            " min-width: 28px;"
        )
        layout.addWidget(self._shot_label)

        self._state_label = QLabel("STARTING")
        self._state_label.setStyleSheet(
            "color: #888; font-family: monospace; font-size: 10px;"
            " min-width: 72px;"
        )
        layout.addWidget(self._state_label)

        layout.addStretch()

        hint = QLabel("F9")
        hint.setStyleSheet(
            "color: #555; font-size: 10px; font-family: monospace;"
        )
        layout.addWidget(hint)

        stop_btn = QPushButton("\u25a0")
        stop_btn.setFixedSize(20, 20)
        stop_btn.setStyleSheet("""
            QPushButton {
                background: #2a1a1a;
                border: 1px solid #ff4444;
                border-radius: 3px;
                color: #ff4444;
                font-size: 10px;
            }
            QPushButton:hover { background: #ff4444; color: #fff; }
        """)
        stop_btn.clicked.connect(self.stop_requested)
        layout.addWidget(stop_btn)

        self.setStyleSheet("""
            QWidget {
                background: rgba(20, 20, 22, 220);
                border: 1px solid #333;
                border-radius: 4px;
            }
        """)

    def _setup_hotkey(self) -> None:
        sc = QShortcut(QKeySequence("F9"), self)
        sc.setContext(Qt.ShortcutContext.ApplicationShortcut)
        sc.activated.connect(self.stop_requested)

    def update_count(self, count: int) -> None:
        self._shot_label.setText(f"{count:03d}")

    def update_cycle(self, state: str) -> None:
        colours = {
            "CAPTURING": "#e8ff47",
            "SCROLLING": "#47b0ff",
            "WAITING":   "#888888",
            "BOTTOM":    "#47ffb0",
        }
        colour = colours.get(state, "#888888")
        self._state_label.setStyleSheet(
            f"color: {colour}; font-family: monospace; font-size: 10px;"
            f" min-width: 72px;"
        )
        self._state_label.setText(state)

    def place_away_from_region(self) -> None:
        from PySide6.QtWidgets import QApplication
        screen = QApplication.primaryScreen().geometry()
        self.adjustSize()
        w = self.width()
        h = self.height()
        margin = 16
        r = self._region

        # Four candidate corners: top-right, top-left, bottom-right, bottom-left
        candidates = [
            (screen.right() - w - margin,  screen.top() + margin),
            (screen.left() + margin,        screen.top() + margin),
            (screen.right() - w - margin,  screen.bottom() - h - margin),
            (screen.left() + margin,        screen.bottom() - h - margin),
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

        # Fallback: top-right regardless
        self.move(candidates[0][0], candidates[0][1])

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self.place_away_from_region()
