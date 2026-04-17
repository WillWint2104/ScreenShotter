"""
region_selector.py

Full-screen transparent overlay. User clicks and drags to select a
rectangular screen region. Emits region_selected(x, y, w, h) on release.
"""
from PySide6.QtWidgets import QWidget
from PySide6.QtCore import Qt, Signal, QRect, QPoint
from PySide6.QtGui import QPainter, QColor, QPen, QCursor, QScreen
from PySide6.QtWidgets import QApplication


class RegionSelector(QWidget):
    region_selected = Signal(int, int, int, int)   # x, y, w, h
    cancelled       = Signal()

    def __init__(self) -> None:
        super().__init__()
        self._origin: QPoint | None = None
        self._current: QPoint | None = None
        self._selecting = False
        self._setup()

    def _setup(self) -> None:
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint |
            Qt.WindowType.WindowStaysOnTopHint |
            Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self.setCursor(QCursor(Qt.CursorShape.CrossCursor))

        # Cover all screens
        virtual_geom = QRect()
        for screen in QApplication.screens():
            virtual_geom = virtual_geom.united(screen.geometry())
        self.setGeometry(virtual_geom)
        self.showFullScreen()

    # ------------------------------------------------------------------
    def paintEvent(self, _event) -> None:
        painter = QPainter(self)

        # Dim overlay
        painter.fillRect(self.rect(), QColor(0, 0, 0, 90))

        if self._origin and self._current and self._selecting:
            rect = QRect(self._origin, self._current).normalized()

            # Cut-out: clear the selected region
            painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_Clear)
            painter.fillRect(rect, QColor(0, 0, 0, 0))

            # Border
            painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceOver)
            pen = QPen(QColor(232, 255, 71), 2)
            painter.setPen(pen)
            painter.drawRect(rect)

            # Size label
            painter.setPen(QColor(232, 255, 71))
            painter.drawText(
                rect.x() + 4,
                rect.y() - 6,
                f"{rect.width()} × {rect.height()}"
            )

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._origin = event.pos()
            self._current = event.pos()
            self._selecting = True
            self.update()

    def mouseMoveEvent(self, event) -> None:
        if self._selecting:
            self._current = event.pos()
            self.update()

    def mouseReleaseEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton and self._selecting:
            self._selecting = False
            rect = QRect(self._origin, event.pos()).normalized()
            self.close()
            if rect.width() > 10 and rect.height() > 10:
                self.region_selected.emit(rect.x(), rect.y(), rect.width(), rect.height())
            else:
                self.cancelled.emit()

    def keyPressEvent(self, event) -> None:
        if event.key() == Qt.Key.Key_Escape:
            self.close()
            self.cancelled.emit()
