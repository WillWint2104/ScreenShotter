import subprocess
import sys
import time
from pathlib import Path

import mss
from PIL import Image
from PySide6.QtWidgets import QMainWindow, QWidget, QVBoxLayout, QFrame
from PySide6.QtCore import Qt, QTimer, QThread, Signal as QSignal

from app.ui.controls_panel import ControlsPanel
from app.ui.progress_panel import ProgressPanel
from app.ui.scrollable_detector import ScrollableDetector
from app.ui.capture_toolbar import CaptureToolbar
from app.ui.capture_flash import CaptureFlash
from app.ui.region_preview import RegionPreview
from app.core.capture_engine import CaptureWorker
from app.core.orchestrator import CapturePipelineWorker
from app.core.scroll_logic import scroll_back_to
from app.models.capture_config import CaptureConfig, RegionCoords

APP_VERSION = "0.4.0"


class _ScrollBackWorker(QThread):
    """Runs scroll_back_to in a background thread."""
    done = QSignal()

    def __init__(self, region, start_ref):
        super().__init__()
        self._region = region
        self._start_ref = start_ref

    def run(self):
        scroll_back_to(self._region, self._start_ref)
        self.done.emit()


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self._worker: CaptureWorker | None = None
        self._toolbar: CaptureToolbar | None = None
        self._flash_overlay: CaptureFlash | None = None
        self._region_preview: RegionPreview | None = None
        self._start_reference: Image.Image | None = None
        self._end_reference: Image.Image | None = None
        self._scroll_worker: _ScrollBackWorker | None = None
        self._last_output_path: Path | None = None
        self._setup_window()
        self._build_ui()
        self._connect_signals()

    def _setup_window(self) -> None:
        self.setWindowTitle(f"ScrollCapture  v{APP_VERSION}")
        self.setMinimumSize(440, 460)
        self.resize(480, 500)
        self._apply_stylesheet()

    def _build_ui(self) -> None:
        root = QWidget()
        self.setCentralWidget(root)
        layout = QVBoxLayout(root)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self.controls = ControlsPanel()
        layout.addWidget(self.controls, stretch=1)

        divider = QFrame()
        divider.setFrameShape(QFrame.Shape.HLine)
        divider.setStyleSheet("color: #2a2a2e;")
        layout.addWidget(divider)

        self.progress = ProgressPanel()
        layout.addWidget(self.progress)

    def _connect_signals(self) -> None:
        self.controls.go_requested.connect(self._on_go)
        self.controls.stop_requested.connect(self._on_stop)
        self.controls.select_region_requested.connect(self._on_select_region)
        self.controls.reset_requested.connect(self._on_reset)
        self.controls.open_folder_requested.connect(self._on_open_folder)

    # ------------------------------------------------------------------
    # Region selection (standalone, before Go)
    # ------------------------------------------------------------------

    def _on_select_region(self) -> None:
        self._hide_region_preview()
        self.hide()
        self._detector = ScrollableDetector()
        self._detector.region_selected.connect(self._on_region_confirmed)
        self._detector.cancelled.connect(self._on_region_cancelled)

    def _on_region_confirmed(self, x: int, y: int, w: int, h: int) -> None:
        self.show()
        self.controls.set_region(x, y, w, h)
        region = RegionCoords(x, y, w, h)
        self._region_preview = RegionPreview(region)
        self._region_preview.show()
        self.progress.set_status(f"Region set: {w}\u00d7{h}px at ({x}, {y})")

    def _on_region_cancelled(self) -> None:
        self.show()
        self.progress.set_status("Region selection cancelled.")

    def _on_reset(self) -> None:
        self._end_reference = None
        self._hide_region_preview()
        self.controls.clear_region()
        self.progress.set_status("Reset \u2014 select a new region to begin.")

    def _hide_region_preview(self) -> None:
        if self._region_preview:
            self._region_preview.hide()
            self._region_preview = None

    # ------------------------------------------------------------------
    # Go — unified single-pass flow
    # ------------------------------------------------------------------

    def _on_go(self) -> None:
        """Single entry point: Go button clicked."""
        region = self.controls.region()
        if region and region.is_valid():
            # Region already set — skip straight to toolbar
            self._begin_toolbar_phase(region)
        else:
            # No region — open detector first, then continue
            self._hide_region_preview()
            self.showMinimized()
            self._detector = ScrollableDetector()
            self._detector.region_selected.connect(self._on_go_region_confirmed)
            self._detector.cancelled.connect(self._on_go_cancelled)

    def _on_go_region_confirmed(self, x: int, y: int, w: int, h: int) -> None:
        """Region selected during Go flow — save it and continue."""
        self.controls.set_region(x, y, w, h)
        region = RegionCoords(x, y, w, h)
        # Don't show main window — go straight to toolbar
        self._begin_toolbar_phase(region)

    def _on_go_cancelled(self) -> None:
        self.show()
        self.progress.set_status("Cancelled.")

    def _begin_toolbar_phase(self, region: RegionCoords) -> None:
        """Start the capture flow. Shows end-point toolbar only if toggled on."""
        self._start_reference = None
        self._end_reference = None
        self._hide_region_preview()
        if not self.isMinimized():
            self.showMinimized()

        self._toolbar = CaptureToolbar(region)
        self._toolbar.end_point_set.connect(self._on_end_point_set)
        self._toolbar.skip_end_point.connect(self._on_skip_end_point)
        self._toolbar.stop_requested.connect(self._on_stop)

        if self.controls.wants_end_point():
            # Capture the start reference before user scrolls away
            self._start_reference = self._grab_region(region)
            # Show toolbar for end-point selection
            self._toolbar.show()
        else:
            # Skip straight to capture
            self._start_capture()

    # ------------------------------------------------------------------
    # End-point phase responses
    # ------------------------------------------------------------------

    def _grab_region(self, region: RegionCoords) -> Image.Image:
        """Capture a screenshot of the region at physical resolution."""
        from app.utils.screen_utils import logical_to_physical
        px, py, pw, ph = logical_to_physical(
            region.x, region.y, region.width, region.height
        )
        mon = {"top": py, "left": px, "width": pw, "height": ph}
        with mss.mss() as sct:
            shot = sct.grab(mon)
            return Image.frombytes("RGB", shot.size, shot.rgb)

    def _on_end_point_set(self) -> None:
        """User pressed Enter — capture end reference, scroll back to start."""
        region = self.controls.region()
        self._end_reference = self._grab_region(region)

        # Hide toolbar so it doesn't interfere with frame comparison
        if self._toolbar:
            self._toolbar.hide()

        # Scroll back in a background thread
        self._scroll_worker = _ScrollBackWorker(region, self._start_reference)
        self._scroll_worker.done.connect(self._on_scroll_back_done)
        self._scroll_worker.start()

    def _on_scroll_back_done(self) -> None:
        """Scroll-back finished — start capture after brief settle."""
        self._scroll_worker = None
        QTimer.singleShot(600, self._start_capture)

    def _on_skip_end_point(self) -> None:
        """User pressed Esc — capture full page from current position."""
        self._end_reference = None
        self._start_capture()

    # ------------------------------------------------------------------
    # Capture
    # ------------------------------------------------------------------

    def _start_capture(self) -> None:
        """Create worker and begin capturing."""
        region = self.controls.region()
        if not region:
            return

        config = CaptureConfig(
            region=region,
            delay_ms=self.controls.delay_ms(),
            end_reference=self._end_reference,
        )

        self._worker = CapturePipelineWorker(config)
        self._worker.progress.connect(self._on_progress)
        self._worker.cycle.connect(self._on_cycle)
        self._worker.status.connect(self.progress.set_status)
        self._worker.finished.connect(self._on_finished)
        self._worker.error.connect(self._on_error)

        self._flash_overlay = CaptureFlash(region)
        self._worker.flash.connect(self._flash_overlay.flash)

        # Connect toolbar signals before starting worker
        if self._toolbar:
            self._toolbar.enter_capture_phase()
            self._worker.progress.connect(self._toolbar.update_count)
            self._worker.cycle.connect(self._toolbar.update_cycle)

        self.controls.set_capturing(True)
        self.progress.reset()

        # Start worker FIRST — its 0.8s initial sleep gives time to settle.
        # Show toolbar AFTER so it doesn't steal focus before capture begins.
        self._worker.start()
        if self._toolbar:
            self._toolbar.show()

    def _on_stop(self) -> None:
        if self._worker:
            self._worker.request_stop()
        self._close_overlays()
        self.showNormal()
        self.activateWindow()
        self.controls.set_capturing(False)
        self.progress.set_status("Stopping\u2026")
        self._show_region_preview()

    def _on_cycle(self, state: str) -> None:
        pass  # toolbar handles display

    def _on_progress(self, count: int) -> None:
        self.progress.set_progress(count, 0)

    def _on_finished(self, session_path: str) -> None:
        self._close_overlays()
        self.showNormal()
        self.activateWindow()
        self._last_output_path = Path(session_path)
        self.controls.set_capturing(False)
        self.controls.set_output_path(session_path)
        self.progress.set_last_path(session_path)
        self.progress.set_complete()
        self.progress.set_status("Done \u2014 session saved.")
        self._show_region_preview()

    def _on_error(self, message: str) -> None:
        self._close_overlays()
        self.showNormal()
        self.activateWindow()
        self.controls.set_capturing(False)
        self.progress.set_status(f"Error: {message}")
        self._show_region_preview()

    def _close_overlays(self) -> None:
        if self._toolbar:
            self._toolbar.hide()
            self._toolbar = None
        if self._flash_overlay:
            self._flash_overlay.hide()
            self._flash_overlay = None

    def _show_region_preview(self) -> None:
        """Re-show region preview if a region is still set."""
        region = self.controls.region()
        if region and region.is_valid():
            self._region_preview = RegionPreview(region)
            self._region_preview.show()

    # ------------------------------------------------------------------
    # Open folder
    # ------------------------------------------------------------------

    def _on_open_folder(self) -> None:
        if self._last_output_path and self._last_output_path.exists():
            if sys.platform == "win32":
                subprocess.Popen(["explorer", str(self._last_output_path)])
            elif sys.platform == "darwin":
                subprocess.Popen(["open", str(self._last_output_path)])
            else:
                subprocess.Popen(["xdg-open", str(self._last_output_path)])

    # ------------------------------------------------------------------
    # Stylesheet
    # ------------------------------------------------------------------

    def _apply_stylesheet(self) -> None:
        self.setStyleSheet("""
            QMainWindow, QWidget {
                background-color: #0e0e0f;
                color: #e0e0e0;
                font-family: "Segoe UI", "SF Pro Text", system-ui, sans-serif;
                font-size: 13px;
            }
            QComboBox {
                background: #1a1a1c; border: 1px solid #2a2a2e;
                border-radius: 5px; padding: 5px 8px; color: #f0f0f0;
            }
            QComboBox::drop-down { border: none; width: 20px; }
            QComboBox QAbstractItemView {
                background: #1a1a1c; border: 1px solid #2a2a2e;
                color: #f0f0f0; selection-background-color: #2a2a2e;
            }
            QSlider::groove:horizontal {
                height: 3px; background: #2a2a2e; border-radius: 2px;
            }
            QSlider::handle:horizontal {
                background: #e8ff47; width: 14px; height: 14px;
                margin: -6px 0; border-radius: 7px;
            }
            QSlider::sub-page:horizontal {
                background: #e8ff47; border-radius: 2px;
            }
            QPushButton {
                background: #1a1a1c; border: 1px solid #2a2a2e;
                border-radius: 6px; padding: 8px 14px;
                color: #e0e0e0; font-size: 12px;
            }
            QPushButton:hover { border-color: #444; background: #222224; }
            QPushButton:pressed { background: #111113; }
            QPushButton:disabled { color: #444; border-color: #1e1e20; }
            QPushButton#startBtn {
                background: #e8ff47; color: #0e0e0f;
                border: none; font-weight: 600;
            }
            QPushButton#startBtn:hover { background: #d4eb3a; }
            QPushButton#startBtn:disabled { background: #3a3d20; color: #666; }
            QPushButton#selectBtn {
                background: #1a1a1c; border: 1px solid #444;
                color: #e8ff47; font-weight: 500;
            }
            QPushButton#selectBtn:hover {
                background: #222224; border-color: #e8ff47;
            }
            QProgressBar {
                background: #1a1a1c; border: none; border-radius: 3px;
            }
            QProgressBar::chunk { background: #e8ff47; border-radius: 3px; }
        """)
