"""
capture_engine.py

Runs the region capture loop in a background QThread.
Emits signals for progress, cycle state, and completion.
Always-on bottom detection via frame similarity.
"""
from __future__ import annotations
import time
from pathlib import Path

import mss
import mss.tools
from PIL import Image
from PySide6.QtCore import QThread, Signal

from app.core import file_manager, manifest_writer
from app.core.scroll_logic import scroll_down
from app.models.capture_config import CaptureConfig
from app.models.capture_session import CaptureSession


class CaptureWorker(QThread):
    progress  = Signal(int)   # current shot count
    cycle     = Signal(str)   # CAPTURING / SCROLLING / WAITING
    status    = Signal(str)   # status message for main window
    flash     = Signal()
    finished  = Signal(str)   # session folder path
    error     = Signal(str)   # error message

    def __init__(self, config: CaptureConfig) -> None:
        super().__init__()
        self._config = config
        self._stop_flag = False

    def request_stop(self) -> None:
        self._stop_flag = True

    def run(self) -> None:
        config = self._config
        session: CaptureSession | None = None

        try:
            session = file_manager.create_session()
            session.capture_status = "running"
            manifest_writer.write_initial(session, config)
            self.status.emit(f"Session: {session.session_id}")

            from app.utils.screen_utils import logical_to_physical
            px, py, pw, ph = logical_to_physical(
                config.region.x,
                config.region.y,
                config.region.width,
                config.region.height,
            )
            mon = {
                "top":    py,
                "left":   px,
                "width":  pw,
                "height": ph,
            }

            prev_image: Image.Image | None = None

            # Wait for main window to fully minimise before first capture
            self.cycle.emit("WAITING")
            time.sleep(0.8)

            with mss.mss() as sct:
                while not self._stop_flag:

                    # --- CAPTURE ---
                    self.cycle.emit("CAPTURING")
                    shot = sct.grab(mon)
                    dest = file_manager.next_screenshot_path(session)
                    mss.tools.to_png(shot.rgb, shot.size, output=str(dest))
                    session.screenshot_filenames.append(dest.name)
                    self.progress.emit(session.screenshot_count)
                    self.flash.emit()
                    self.status.emit(f"Captured {dest.name}")

                    # --- BOTTOM DETECTION ---
                    current_image = Image.frombytes("RGB", shot.size, shot.rgb)
                    if prev_image is not None:
                        if _similar(prev_image, current_image,
                                    config.similarity_threshold):
                            self.cycle.emit("BOTTOM")
                            self.status.emit("Page bottom detected \u2014 stopping.")
                            break
                    prev_image = current_image

                    # --- END POINT DETECTION ---
                    if config.end_reference is not None:
                        if _similar(current_image, config.end_reference,
                                    config.similarity_threshold):
                            self.cycle.emit("ENDPOINT")
                            self.status.emit("End point reached \u2014 stopping.")
                            break

                    # --- WAIT ---
                    self.cycle.emit("WAITING")
                    time.sleep(config.delay_ms / 1000.0)

                    if self._stop_flag:
                        break

                    # --- SCROLL ---
                    self.cycle.emit("SCROLLING")
                    scroll_down(config.region)

                    # --- WAIT AFTER SCROLL ---
                    self.cycle.emit("WAITING")
                    time.sleep(config.delay_ms / 1000.0)

            session.stopped_by_user = self._stop_flag
            session.capture_status = (
                "stopped" if self._stop_flag else "complete"
            )
            manifest_writer.write_final(session, config)
            self.finished.emit(str(session.session_dir))

        except Exception as exc:
            if session:
                session.capture_status = "error"
                try:
                    manifest_writer.write_final(session, config)
                except Exception:
                    pass
            self.error.emit(str(exc))


def _similar(a: Image.Image, b: Image.Image, threshold: float) -> bool:
    if a.size != b.size:
        return False
    a_small = a.resize((64, 64))
    b_small = b.resize((64, 64))
    a_pixels = list(a_small.getdata())
    b_pixels = list(b_small.getdata())
    matches = sum(
        1 for pa, pb in zip(a_pixels, b_pixels)
        if all(abs(ca - cb) < 10 for ca, cb in zip(pa, pb))
    )
    return matches / len(a_pixels) >= threshold
