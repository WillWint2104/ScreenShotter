"""
scrollable_detector.py

Full-screen hover detector. Uses Windows UI Automation via
comtypes to find scrollable containers under the cursor.
Highlights one region at a time as the cursor moves.
Click to lock. Falls back to manual drag if no scrollable
region found.

Emits:
  region_selected(x, y, w, h)  -- locked region in logical pixels
  cancelled()                   -- user pressed Escape
"""
from __future__ import annotations
import threading
from PySide6.QtWidgets import QWidget, QApplication
from PySide6.QtCore import Qt, Signal, QPoint, QRect, QTimer
from PySide6.QtGui import QPainter, QColor, QPen, QCursor, QFont
from app.utils.screen_utils import get_scale_factor


class ScrollableDetector(QWidget):
    region_selected = Signal(int, int, int, int)
    cancelled       = Signal()

    # How often to poll UI Automation (ms)
    POLL_MS = 120

    def __init__(self) -> None:
        super().__init__()
        self._current_rect: QRect | None = None
        self._locked = False
        self._lock_rect: QRect | None = None
        self._uia_available = False
        self._drag_origin: QPoint | None = None
        self._dragging = False
        self._setup_window()
        self._check_uia()
        self._poll_timer = QTimer(self)
        self._poll_timer.timeout.connect(self._poll_uia)
        self._poll_timer.start(self.POLL_MS)

    def _setup_window(self) -> None:
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint |
            Qt.WindowType.WindowStaysOnTopHint |
            Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self.setMouseTracking(True)

        # Cover all screens
        virtual_geom = QRect()
        for screen in QApplication.screens():
            virtual_geom = virtual_geom.united(screen.geometry())
        self.setGeometry(virtual_geom)
        self.showFullScreen()
        self.setCursor(QCursor(Qt.CursorShape.CrossCursor))

    def _check_uia(self) -> None:
        try:
            import comtypes.client
            comtypes.client.GetModule("UIAutomationCore.dll")
            self._uia_available = True
        except Exception:
            self._uia_available = False

    def _poll_uia(self) -> None:
        if self._locked or self._dragging:
            return
        if not self._uia_available:
            return

        pos = QCursor.pos()
        scale = get_scale_factor()
        phys_x = int(pos.x() * scale)
        phys_y = int(pos.y() * scale)

        rect = _find_scrollable_at(phys_x, phys_y, scale)
        if rect != self._current_rect:
            self._current_rect = rect
            self.update()

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)

        # Dim overlay
        painter.fillRect(self.rect(), QColor(0, 0, 0, 60))

        if self._locked and self._lock_rect:
            self._draw_region(
                painter, self._lock_rect,
                QColor(71, 255, 176),   # green when locked
                "LOCKED"
            )
        elif self._current_rect and not self._dragging:
            self._draw_region(
                painter, self._current_rect,
                QColor(232, 255, 71),   # yellow when hovering
                "SCROLLABLE — click to lock"
            )
        elif self._dragging and self._drag_origin:
            pos = self.mapFromGlobal(QCursor.pos())
            rect = QRect(self._drag_origin, pos).normalized()
            self._draw_region(
                painter, rect,
                QColor(100, 180, 255),  # blue for manual drag
                "MANUAL SELECTION"
            )

    def _draw_region(
        self,
        painter: QPainter,
        rect: QRect,
        colour: QColor,
        label: str
    ) -> None:
        # Clear overlay inside region
        painter.setCompositionMode(
            QPainter.CompositionMode.CompositionMode_Clear
        )
        painter.fillRect(rect, QColor(0, 0, 0, 0))

        painter.setCompositionMode(
            QPainter.CompositionMode.CompositionMode_SourceOver
        )

        # Border
        border_colour = QColor(colour)
        border_colour.setAlpha(220)
        pen = QPen(border_colour, 2)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRect(rect)

        # Corner label
        font = QFont("Segoe UI", 9)
        font.setWeight(QFont.Weight.Medium)
        painter.setFont(font)

        label_text = (
            f"{label}  "
            f"{rect.width()}\u00d7{rect.height()}px"
        )
        text_colour = QColor(colour)
        text_colour.setAlpha(255)
        painter.setPen(text_colour)

        tx = rect.x() + 6
        ty = rect.y() - 6 if rect.y() > 20 else rect.y() + 16
        painter.drawText(tx, ty, label_text)

    # ------------------------------------------------------------------
    # Mouse events
    # ------------------------------------------------------------------

    def mousePressEvent(self, event) -> None:
        if event.button() != Qt.MouseButton.LeftButton:
            return

        if self._current_rect and not self._locked:
            # Lock onto detected scrollable region
            self._lock_rect = self._current_rect
            self._locked = True
            self._poll_timer.stop()
            self.update()
            QTimer.singleShot(600, self._confirm_lock)
        else:
            # No detected region — start manual drag
            self._dragging = True
            self._drag_origin = event.pos()
            self._poll_timer.stop()
            self.update()

    def mouseMoveEvent(self, event) -> None:
        if self._dragging:
            self.update()

    def mouseReleaseEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            if self._dragging and self._drag_origin:
                self._dragging = False
                rect = QRect(
                    self._drag_origin, event.pos()
                ).normalized()
                if rect.width() > 10 and rect.height() > 10:
                    self._lock_rect = rect
                    self._locked = True
                    self.update()
                    QTimer.singleShot(400, self._confirm_lock)
                else:
                    self.cancelled.emit()
                    self.close()

    def _confirm_lock(self) -> None:
        if self._lock_rect:
            r = self._lock_rect
            self.region_selected.emit(r.x(), r.y(), r.width(), r.height())
            self.close()

    def keyPressEvent(self, event) -> None:
        if event.key() == Qt.Key.Key_Escape:
            self._poll_timer.stop()
            self.cancelled.emit()
            self.close()


# ------------------------------------------------------------------
# UI Automation helper — runs synchronously (fast enough at 120ms)
# ------------------------------------------------------------------

def _find_scrollable_at(
    phys_x: int,
    phys_y: int,
    scale: float
) -> QRect | None:
    """
    Query Windows UI Automation for a scrollable element
    under the given physical screen coordinates.
    Returns a QRect in LOGICAL pixels or None.
    """
    try:
        import comtypes
        import comtypes.client

        UIA = comtypes.client.CreateObject(
            "{ff48dba4-60ef-4201-aa87-54103eef594e}",
            interface=comtypes.gen.UIAutomationClient.IUIAutomation
        )
        element = UIA.ElementFromPoint(
            comtypes.gen.UIAutomationClient.tagPOINT(phys_x, phys_y)
        )
        if element is None:
            return None

        # Walk up the ancestor tree looking for a scrollable container
        MAX_DEPTH = 8
        current = element
        for _ in range(MAX_DEPTH):
            try:
                h_scroll = current.CurrentIsScrollPatternAvailable
                v_scroll = current.CurrentIsScrollPatternAvailable
                if h_scroll or v_scroll:
                    rect = current.CurrentBoundingRectangle
                    if rect.right - rect.left > 50 and rect.bottom - rect.top > 50:
                        return QRect(
                            int(rect.left / scale),
                            int(rect.top / scale),
                            int((rect.right - rect.left) / scale),
                            int((rect.bottom - rect.top) / scale)
                        )
            except Exception:
                pass
            try:
                current = current.CurrentParent
                if current is None:
                    break
            except Exception:
                break
    except Exception:
        pass
    return None
