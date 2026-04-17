from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QProgressBar,
)
from PySide6.QtCore import Qt


class ProgressPanel(QWidget):
    """Bottom panel: progress bar, shot counter, and status text."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._build_ui()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def set_status(self, message: str) -> None:
        self.status_label.setText(message)

    def set_progress(self, current: int, total: int) -> None:
        if total > 0:
            self.progress_bar.setMaximum(total)
            self.progress_bar.setValue(current)
            self.counter_label.setText(f"{current} / {total}")
        else:
            self.progress_bar.setMaximum(0)  # indeterminate
            self.progress_bar.setValue(0)
            self.counter_label.setText("")

    def set_last_path(self, path: str) -> None:
        self.last_path_label.setText(path or "—")

    def reset(self) -> None:
        self.progress_bar.setValue(0)
        self.progress_bar.setMaximum(100)
        self.counter_label.setText("")
        self.status_label.setText("Ready")
        self.last_path_label.setText("—")

    def set_complete(self) -> None:
        self.progress_bar.setMaximum(100)
        self.progress_bar.setValue(100)

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 8, 12, 12)
        layout.setSpacing(6)

        # Progress row
        bar_row = QHBoxLayout()
        self.progress_bar = QProgressBar()
        self.progress_bar.setValue(0)
        self.progress_bar.setMaximum(100)
        self.progress_bar.setTextVisible(False)
        self.progress_bar.setFixedHeight(6)

        self.counter_label = QLabel("")
        self.counter_label.setFixedWidth(64)
        self.counter_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.counter_label.setStyleSheet("font-family: monospace; font-size: 11px; color: #888;")

        bar_row.addWidget(self.progress_bar)
        bar_row.addWidget(self.counter_label)
        layout.addLayout(bar_row)

        # Status text
        self.status_label = QLabel("Ready")
        self.status_label.setStyleSheet("font-size: 12px; color: #aaa;")
        layout.addWidget(self.status_label)

        # Last saved path
        path_row = QHBoxLayout()
        path_lbl = QLabel("Last session:")
        path_lbl.setStyleSheet("font-size: 11px; color: #666;")
        self.last_path_label = QLabel("—")
        self.last_path_label.setStyleSheet("font-size: 11px; color: #888;")
        self.last_path_label.setWordWrap(True)
        path_row.addWidget(path_lbl)
        path_row.addWidget(self.last_path_label, stretch=1)
        layout.addLayout(path_row)
