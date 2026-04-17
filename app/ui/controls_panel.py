from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QSlider, QPushButton, QCheckBox,
)
from PySide6.QtCore import Qt, Signal
from app.models.capture_config import RegionCoords


class ControlsPanel(QWidget):
    go_requested              = Signal()
    stop_requested            = Signal()
    select_region_requested   = Signal()
    reset_requested           = Signal()
    open_folder_requested     = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._region: RegionCoords | None = None
        self._build_ui()

    def region(self) -> RegionCoords | None:
        return self._region

    def set_region(self, x: int, y: int, w: int, h: int) -> None:
        self._region = RegionCoords(x, y, w, h)
        self.region_label.setText(f"x={x}  y={y}  {w}\u00d7{h}px")
        self.region_label.setStyleSheet(
            "color: #e8ff47; font-family: monospace; font-size: 11px;"
        )
        self._update_buttons()

    def clear_region(self) -> None:
        self._region = None
        self.region_label.setText("No region selected")
        self.region_label.setStyleSheet(
            "color: #666; font-size: 11px; font-family: monospace;"
        )
        self._update_buttons()

    def delay_ms(self) -> int:
        return self.delay_slider.value()

    def wants_end_point(self) -> bool:
        return self.end_point_check.isChecked()

    def set_capturing(self, capturing: bool) -> None:
        self.go_btn.setEnabled(not capturing)
        self.stop_btn.setEnabled(capturing)
        self.select_btn.setEnabled(not capturing)
        self.reset_btn.setEnabled(not capturing and self._region is not None)

    def set_output_path(self, path: str) -> None:
        self.output_label.setText(path or "\u2014")
        self.open_folder_btn.setEnabled(bool(path))

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(14)

        # Region
        layout.addWidget(self._section_label("Capture region"))

        region_row = QHBoxLayout()
        self.select_btn = QPushButton("\u22b9  Select Region")
        self.select_btn.setObjectName("selectBtn")
        self.select_btn.clicked.connect(self.select_region_requested)
        region_row.addWidget(self.select_btn)

        self.reset_btn = QPushButton("Reset")
        self.reset_btn.setEnabled(False)
        self.reset_btn.clicked.connect(self.reset_requested)
        region_row.addWidget(self.reset_btn)
        layout.addLayout(region_row)

        self.region_label = QLabel("No region selected")
        self.region_label.setStyleSheet(
            "color: #666; font-size: 11px; font-family: monospace;"
        )
        layout.addWidget(self.region_label)

        # Delay
        layout.addWidget(self._section_label("Delay between shots (ms)"))
        delay_row, self.delay_slider, self.delay_val_label = \
            self._slider_row(200, 3000, 800, "ms", 100)
        layout.addLayout(delay_row)

        # End point toggle
        self.end_point_check = QCheckBox("Set end point before capture")
        self.end_point_check.setStyleSheet("font-size: 11px; color: #aaa;")
        self.end_point_check.setChecked(False)
        layout.addWidget(self.end_point_check)

        # Output
        layout.addWidget(self._section_label("Session output"))
        self.output_label = QLabel("\u2014")
        self.output_label.setWordWrap(True)
        self.output_label.setStyleSheet("color: #888; font-size: 11px;")
        layout.addWidget(self.output_label)

        self.open_folder_btn = QPushButton("Open output folder")
        self.open_folder_btn.setEnabled(False)
        self.open_folder_btn.clicked.connect(self.open_folder_requested)
        layout.addWidget(self.open_folder_btn)

        layout.addStretch()

        # Go / Stop
        self.go_btn = QPushButton("\u25b6  Go")
        self.go_btn.setObjectName("startBtn")
        self.go_btn.clicked.connect(self.go_requested)

        self.stop_btn = QPushButton("\u25a0  Stop")
        self.stop_btn.setEnabled(False)
        self.stop_btn.clicked.connect(self.stop_requested)

        btn_layout = QHBoxLayout()
        btn_layout.addWidget(self.go_btn)
        btn_layout.addWidget(self.stop_btn)
        layout.addLayout(btn_layout)

    def _update_buttons(self) -> None:
        self.reset_btn.setEnabled(self._region is not None)

    @staticmethod
    def _section_label(text: str) -> QLabel:
        lbl = QLabel(text.upper())
        lbl.setStyleSheet("font-size: 10px; color: #888; letter-spacing: 1px;")
        return lbl

    @staticmethod
    def _slider_row(
        minimum: int, maximum: int, default: int,
        suffix: str, step: int = 1
    ) -> tuple[QHBoxLayout, QSlider, QLabel]:
        slider = QSlider(Qt.Orientation.Horizontal)
        slider.setMinimum(minimum)
        slider.setMaximum(maximum)
        slider.setValue(default)
        slider.setSingleStep(step)
        slider.setPageStep(step)

        val_label = QLabel(f"{default}{suffix}")
        val_label.setFixedWidth(52)
        val_label.setAlignment(
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
        )
        val_label.setStyleSheet("font-family: monospace; font-size: 12px;")
        slider.valueChanged.connect(lambda v: val_label.setText(f"{v}{suffix}"))

        row = QHBoxLayout()
        row.addWidget(slider)
        row.addWidget(val_label)
        return row, slider, val_label
