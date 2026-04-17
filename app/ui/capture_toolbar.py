"""
capture_toolbar.py

Unified floating toolbar that handles the entire capture flow
after region selection, in three phases:

  Phase 1 — END POINT:  "Scroll to END → Enter | Esc = full page"
  Phase 2 — RETURNING:  "Returning to top…"  (auto scroll-back)
  Phase 3 — CAPTURING:  Shot count, cycle state, F9 to stop

F9 uses a Win32 global hotkey (RegisterHotKey) so it works even
when the target application has focus, not the toolbar.

Signals:
    end_point_set()   — user pressed Enter (capture reference, scroll back)
    skip_end_point()  — user pressed Esc (capture full page from here)
    stop_requested()  — user pressed F9 or clicked stop
    cancelled()       — user cancelled during end-point phase
"""
from __future__ import annotations
import ctypes
import ctypes.wintypes
from enum import Enum, auto

from PySide6.QtWidgets import QWidget, QHBoxLayout, QLabel, QPushButton, QApplication
from PySide6.QtCore import Qt, Signal, QTimer
from PySide6.QtGui import QKeySequence, QShortcut, QColor, QPainter, QPen, QFont

from app.models.capture_config import RegionCoords

# Win32 constants for global hotkey
_VK_F9 = 0x78
_MOD_NOREPEAT = 0x4000
_WM_HOTKEY = 0x0312
_HOTKEY_ID_F9 = 1


class _MSG(ctypes.Structure):
    _fields_ = [
        ("hwnd", ctypes.wintypes.HWND),
        ("message", ctypes.wintypes.UINT),
        ("wParam", ctypes.wintypes.WPARAM),
        ("lParam", ctypes.wintypes.LPARAM),
        ("time", ctypes.wintypes.DWORD),
        ("pt", ctypes.wintypes.POINT),
    ]


class Phase(Enum):
    END_POINT = auto()
    RETURNING = auto()
    CAPTURING = auto()


class CaptureToolbar(QWidget):
    end_point_set  = Signal()
    skip_end_point = Signal()
    stop_requested = Signal()
    cancelled      = Signal()

    def __init__(self, region: RegionCoords) -> None:
        super().__init__()
        self._region = region
        self._phase = Phase.END_POINT
        self._f9_registered = False
        self._hotkey_timer: QTimer | None = None
        self._build_ui()
        self._setup_window()
        self._setup_hotkeys()
        self._guide = _EndGuide(region)

    # ------------------------------------------------------------------
    # Window setup
    # ------------------------------------------------------------------

    def _setup_window(self) -> None:
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint |
            Qt.WindowType.WindowStaysOnTopHint |
            Qt.WindowType.Tool
        )
        self.setFixedHeight(32)
        self.setMinimumWidth(320)

    def _build_ui(self) -> None:
        self._layout = QHBoxLayout(self)
        self._layout.setContentsMargins(10, 0, 10, 0)
        self._layout.setSpacing(8)

        # --- Phase 1: end-point widgets ---
        self._ep_label = QLabel("Scroll to END \u2192 Enter  |  Esc = full page")
        self._ep_label.setStyleSheet("color: #ccc; font-size: 11px;")
        self._layout.addWidget(self._ep_label)

        # --- Phase 2: returning widgets ---
        self._ret_label = QLabel("Returning to start\u2026")
        self._ret_label.setStyleSheet("color: #e8ff47; font-size: 11px;")
        self._ret_label.hide()
        self._layout.addWidget(self._ret_label)

        # --- Phase 3: capture widgets ---
        self._cap_dot = QLabel("\u25cf")
        self._cap_dot.setStyleSheet("color: #ff4444; font-size: 10px;")
        self._cap_dot.hide()
        self._layout.addWidget(self._cap_dot)

        self._shot_label = QLabel("000")
        self._shot_label.setStyleSheet(
            "color: #e8ff47; font-family: monospace; font-size: 11px;"
            " min-width: 28px;"
        )
        self._shot_label.hide()
        self._layout.addWidget(self._shot_label)

        self._state_label = QLabel("STARTING")
        self._state_label.setStyleSheet(
            "color: #888; font-family: monospace; font-size: 10px;"
            " min-width: 72px;"
        )
        self._state_label.hide()
        self._layout.addWidget(self._state_label)

        self._layout.addStretch()

        # F9 hint (capture phase)
        self._f9_hint = QLabel("F9")
        self._f9_hint.setStyleSheet(
            "color: #555; font-size: 10px; font-family: monospace;"
        )
        self._f9_hint.hide()
        self._layout.addWidget(self._f9_hint)

        # Stop button (capture phase)
        self._stop_btn = QPushButton("\u25a0")
        self._stop_btn.setFixedSize(20, 20)
        self._stop_btn.setStyleSheet("""
            QPushButton {
                background: #2a1a1a;
                border: 1px solid #ff4444;
                border-radius: 3px;
                color: #ff4444;
                font-size: 10px;
            }
            QPushButton:hover { background: #ff4444; color: #fff; }
        """)
        self._stop_btn.clicked.connect(self.stop_requested)
        self._stop_btn.hide()
        self._layout.addWidget(self._stop_btn)

        self.setStyleSheet("""
            QWidget {
                background: rgba(20, 20, 22, 230);
                border: 1px solid #444;
                border-radius: 4px;
            }
        """)

    def _setup_hotkeys(self) -> None:
        # Enter/Esc for end-point phase (Qt shortcuts, toolbar has focus)
        self._sc_enter = QShortcut(QKeySequence("Return"), self)
        self._sc_enter.setContext(Qt.ShortcutContext.ApplicationShortcut)
        self._sc_enter.activated.connect(self._on_enter)

        self._sc_esc = QShortcut(QKeySequence("Escape"), self)
        self._sc_esc.setContext(Qt.ShortcutContext.ApplicationShortcut)
        self._sc_esc.activated.connect(self._on_escape)

    # ------------------------------------------------------------------
    # Phase transitions
    # ------------------------------------------------------------------

    def enter_returning_phase(self) -> None:
        """Switch to 'Returning to start…' display."""
        self._phase = Phase.RETURNING
        self._ep_label.hide()
        self._guide.hide()
        self._ret_label.show()
        self.update()

    def enter_capture_phase(self) -> None:
        """Switch to capture overlay display. Does NOT steal focus."""
        self._phase = Phase.CAPTURING

        # Don't steal focus from the target application
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)

        self._ep_label.hide()
        self._ret_label.hide()
        self._guide.hide()

        self._cap_dot.show()
        self._shot_label.show()
        self._state_label.show()
        self._f9_hint.show()
        self._stop_btn.show()

        # Register global F9 hotkey (works even when target app has focus)
        self._register_global_f9()
        self.update()

    # ------------------------------------------------------------------
    # Capture-phase updates
    # ------------------------------------------------------------------

    def update_count(self, count: int) -> None:
        self._shot_label.setText(f"{count:03d}")

    def update_cycle(self, state: str) -> None:
        colours = {
            "CAPTURING": "#e8ff47",
            "SCROLLING": "#47b0ff",
            "WAITING":   "#888888",
            "BOTTOM":    "#47ffb0",
            "ENDPOINT":  "#47ffb0",
        }
        colour = colours.get(state, "#888888")
        self._state_label.setStyleSheet(
            f"color: {colour}; font-family: monospace; font-size: 10px;"
            f" min-width: 72px;"
        )
        self._state_label.setText(state)

    # ------------------------------------------------------------------
    # Key handlers
    # ------------------------------------------------------------------

    def _on_enter(self) -> None:
        if self._phase == Phase.END_POINT:
            self.end_point_set.emit()

    def _on_escape(self) -> None:
        if self._phase == Phase.END_POINT:
            self._guide.hide()
            self.skip_end_point.emit()

    def _on_f9(self) -> None:
        if self._phase == Phase.CAPTURING:
            self.stop_requested.emit()

    # ------------------------------------------------------------------
    # Global F9 hotkey (Win32 RegisterHotKey)
    # ------------------------------------------------------------------

    def _register_global_f9(self) -> None:
        self._f9_registered = ctypes.windll.user32.RegisterHotKey(
            None, _HOTKEY_ID_F9, _MOD_NOREPEAT, _VK_F9
        )
        if self._f9_registered:
            self._hotkey_timer = QTimer(self)
            self._hotkey_timer.setInterval(100)
            self._hotkey_timer.timeout.connect(self._poll_hotkey)
            self._hotkey_timer.start()

    def _unregister_global_f9(self) -> None:
        if self._hotkey_timer:
            self._hotkey_timer.stop()
            self._hotkey_timer = None
        if self._f9_registered:
            ctypes.windll.user32.UnregisterHotKey(None, _HOTKEY_ID_F9)
            self._f9_registered = False

    def _poll_hotkey(self) -> None:
        msg = _MSG()
        PM_REMOVE = 0x0001
        while ctypes.windll.user32.PeekMessageW(
            ctypes.byref(msg), None,
            _WM_HOTKEY, _WM_HOTKEY,
            PM_REMOVE
        ):
            if msg.wParam == _HOTKEY_ID_F9:
                self._on_f9()
                return

    # ------------------------------------------------------------------
    # Show / hide
    # ------------------------------------------------------------------

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self._place_away_from_region()
        if self._phase == Phase.END_POINT:
            self._guide.show()
            # Only take focus during end-point phase (needs Enter/Esc)
            self.activateWindow()
        self.raise_()

    def hideEvent(self, event) -> None:
        super().hideEvent(event)
        self._guide.hide()
        self._unregister_global_f9()

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


# ------------------------------------------------------------------
# End-point guide line (transparent to mouse)
# ------------------------------------------------------------------

class _EndGuide(QWidget):
    """
    Horizontal dashed green line across the bottom of the capture
    region. Transparent to mouse so the user can scroll freely.
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
        self.setGeometry(
            r.x - 10, r.y + r.height - line_h // 2,
            r.width + 20, line_h,
        )

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        colour = QColor(102, 204, 102, 200)
        pen = QPen(colour, 2)
        pen.setStyle(Qt.PenStyle.DashLine)
        painter.setPen(pen)

        mid_y = self.height() // 2
        painter.drawLine(0, mid_y, self.width(), mid_y)

        painter.setPen(QColor(102, 204, 102, 255))
        font = QFont("Segoe UI", 8)
        painter.setFont(font)
        painter.drawText(4, mid_y - 4, "END")
