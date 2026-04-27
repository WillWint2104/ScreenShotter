"""
orchestrator.py

CapturePipelineWorker — wraps CaptureWorker and runs the
full ScreenShotter pipeline in a background QThread.

Pipeline sequence:
  1. Find active browser window
  2. Build page fingerprint
  3. Match profile (silent assisted mode)
  4. Discover sections via UI Automation
  5. Expand collapsed content (safe, gated by 4 conditions)
  6. Capture each section using CaptureWorker
  7. Tag every screenshot with section metadata
  8. Write section manifest
  9. Batch screenshots by section
  10. Validate capture quality
  11. Index evaluation for improvement engine

Emits the same six signals as CaptureWorker so MainWindow
requires no UI changes beyond swapping which worker it uses.

Legacy CaptureWorker is not modified.
"""
import logging
import time
from pathlib import Path
from typing import Any

import mss
import mss.tools
from PIL import Image
from PySide6.QtCore import QThread, Signal

from app.core import file_manager, manifest_writer
from app.core.batcher import Batcher
from app.core.capture_validator import CaptureValidator
from app.core.expander import Expander
from app.core.improvement_engine import ImprovementEngine
from app.core.profile_manager import ProfileManager
from app.core.section_discoverer import SectionDiscoverer
from app.core.tagger import Tagger
from app.core.scroll_logic import scroll_down
from app.models.capture_config import CaptureConfig
from app.models.capture_session import CaptureSession
from app.models.section import DiscoveredSection
from app.utils.screen_utils import logical_to_physical

logger = logging.getLogger(__name__)


class CapturePipelineWorker(QThread):
    """
    Full ScreenShotter pipeline worker.
    Emits identical signals to CaptureWorker for UI compatibility.
    """
    progress = Signal(int)    # total screenshot count so far
    cycle    = Signal(str)    # DISCOVERING / EXPANDING / CAPTURING /
                              # SCROLLING / WAITING / BATCHING /
                              # VALIDATING / BOTTOM / DONE
    status   = Signal(str)    # human-readable status message
    flash    = Signal()       # trigger capture flash overlay
    finished = Signal(str)    # session folder path on completion
    error    = Signal(str)    # error message

    def __init__(self, config: CaptureConfig) -> None:
        super().__init__()
        self._config = config
        self._stop_flag = False
        self._profile_manager = ProfileManager()
        self._improvement_engine = ImprovementEngine()

    def request_stop(self) -> None:
        self._stop_flag = True

    # ----------------------------------------------------------
    # Main pipeline
    # ----------------------------------------------------------

    def run(self) -> None:
        config = self._config
        session: CaptureSession | None = None

        try:
            # --- STEP 1: Session init ---
            session = file_manager.create_session()
            session.capture_status = "running"
            manifest_writer.write_initial(session, config)
            self.status.emit(f"Session: {session.session_id}")

            # --- STEP 2: Browser discovery ---
            self.cycle.emit("DISCOVERING")
            self.status.emit("Finding browser window...")
            from app.utils.uia_utils import get_active_browser_window
            browser = get_active_browser_window()
            if not browser:
                raise RuntimeError(
                    "No browser window found. "
                    "Open Chrome, Edge, or Firefox and try again."
                )
            self.status.emit(
                f"Browser found: {browser['browser']} "
                f"on monitor {browser['monitor']}"
            )

            # --- STEP 3: Profile match ---
            page_data = {
                "url": browser.get("title", ""),
                "scrollable_regions": [],
                "landmark_words": [],
                "field_labels": [],
                "section_headers": [],
                "layout_region_count": 0,
            }
            fingerprint = self._profile_manager.build_fingerprint(page_data)
            match = self._profile_manager.match(fingerprint)
            profile = (
                self._profile_manager.get_profile(match.profile_name)
                if match.profile_matched else None
            )
            if match.profile_matched:
                self.status.emit(
                    f"Profile matched: {match.profile_name} "
                    f"({match.profile_match_confidence:.0%})"
                )
            else:
                self.status.emit("No profile matched — using heuristics")

            # --- STEP 4: Section discovery ---
            self.cycle.emit("DISCOVERING")
            self.status.emit("Discovering sections...")
            discoverer = SectionDiscoverer(
                profile=profile,
                profile_match=match,
            )
            sections = discoverer.discover()

            if not sections:
                self.status.emit(
                    "No sections found — falling back to full-region capture"
                )
                sections = [_make_fallback_section(config)]

            self.status.emit(
                f"Found {len(sections)} section(s): "
                f"{[s.section_type for s in sections]}"
            )

            # --- STEP 5: Expansion ---
            if not self._stop_flag:
                self.cycle.emit("EXPANDING")
                self.status.emit("Expanding collapsed content...")
                extra_triggers = (
                    profile.expander_triggers
                    if profile else []
                )
                expander = Expander(
                    extra_trigger_words=extra_triggers,
                    hwnd=browser.get("hwnd"),
                )
                expansion_report = expander.expand_all(sections)
                self.status.emit(
                    f"Expansion complete: "
                    f"{expansion_report.expanded_count} expanded, "
                    f"{expansion_report.blocked_count} blocked"
                )

            # --- STEP 6 + 7: Capture + tag each section ---
            tagger = Tagger(session.session_dir)
            global_index = 0

            for section_num, section in enumerate(sections, 1):
                if self._stop_flag:
                    break
                self.status.emit(
                    f"Capturing section {section_num}/{len(sections)}: "
                    f"{section.section_type}"
                )
                global_index = self._capture_section(
                    section=section,
                    session=session,
                    config=config,
                    tagger=tagger,
                    global_index=global_index,
                )

            tagger.flush()
            self.status.emit(
                f"Capture complete: {session.screenshot_count} screenshots"
            )

            # --- STEP 8: Section manifest ---
            self.cycle.emit("BATCHING")
            manifest_writer.write_section_manifest(
                session_dir=session.session_dir,
                session=session,
                config=config,
                sections=sections,
                profile_match=match.as_dict(),
            )

            # --- STEP 9: Batch ---
            self.status.emit("Batching screenshots by section...")
            batcher = Batcher(session.session_dir)
            batch_result = batcher.batch(tagger)
            self.status.emit(
                f"Batch complete: "
                f"contamination={batch_result.contamination_detected}, "
                f"missing={batch_result.missing_sections}"
            )

            # --- STEP 10: Validate ---
            self.cycle.emit("VALIDATING")
            self.status.emit("Validating capture quality...")
            validator = CaptureValidator(session.session_dir)
            evaluation = validator.validate(
                batch_result=batch_result,
                tagger=tagger,
                profile_manager=self._profile_manager,
                profile_name=match.profile_name,
            )
            self.status.emit(
                f"Validation: {evaluation.recommended_action} "
                f"(confidence={evaluation.overall_capture_confidence:.2f})"
            )

            # --- STEP 11: Index for improvement engine ---
            eval_path = session.session_dir / "evaluation.json"
            if eval_path.exists():
                self._improvement_engine.index_evaluation(
                    session.session_dir.name, eval_path
                )

            session.stopped_by_user = self._stop_flag
            session.capture_status = (
                "stopped" if self._stop_flag else "complete"
            )
            manifest_writer.write_final(session, config)

            self.cycle.emit("DONE")
            self.finished.emit(str(session.session_dir))

        except Exception as exc:
            logger.exception("Pipeline error: %s", exc)
            if session:
                session.capture_status = "error"
                try:
                    manifest_writer.write_final(session, config)
                except Exception:
                    pass
            self.error.emit(str(exc))

    # ----------------------------------------------------------
    # Per-section capture loop
    # ----------------------------------------------------------

    def _capture_section(
        self,
        section: DiscoveredSection,
        session: CaptureSession,
        config: CaptureConfig,
        tagger: Tagger,
        global_index: int,
    ) -> int:
        """
        Capture one section completely using mss.
        Tags each screenshot immediately after saving.
        Returns updated global_index.
        """
        # Convert section rect to physical pixels for mss
        px, py, pw, ph = logical_to_physical(
            section.rect.x,
            section.rect.y,
            section.rect.width,
            section.rect.height,
        )
        mon = {
            "top": py, "left": px,
            "width": pw, "height": ph,
        }

        prev_image: Image.Image | None = None

        # Scroll section to top via UIA if possible
        if section.element_ref:
            try:
                from app.utils.uia_utils import scroll_element
                scroll_element(section.element_ref, "up", "large")
                scroll_element(section.element_ref, "up", "large")
                time.sleep(0.3)
            except Exception:
                pass

        with mss.mss() as sct:
            while not self._stop_flag:

                # Capture
                self.cycle.emit("CAPTURING")
                shot = sct.grab(mon)
                dest = file_manager.next_screenshot_path(session)
                mss.tools.to_png(shot.rgb, shot.size, output=str(dest))

                global_index += 1
                session.screenshot_filenames.append(dest.name)
                self.progress.emit(session.screenshot_count)
                self.flash.emit()
                self.status.emit(
                    f"[{section.section_type}] {dest.name}"
                )

                # Tag immediately
                scroll_pct = 0.0
                if section.element_ref:
                    try:
                        from app.utils.uia_utils import get_element_metadata
                        meta = get_element_metadata(section.element_ref)
                        # scroll_percent not in metadata — use index as proxy
                        scroll_pct = global_index / max(global_index + 1, 1)
                    except Exception:
                        pass
                tagger.tag(
                    filename=dest.name,
                    capture_index=global_index,
                    section=section,
                    scroll_position=scroll_pct,
                )

                # Bottom detection
                current_image = Image.frombytes("RGB", shot.size, shot.rgb)
                if prev_image is not None:
                    if _similar(prev_image, current_image,
                                config.similarity_threshold):
                        self.cycle.emit("BOTTOM")
                        self.status.emit(
                            f"[{section.section_type}] Bottom reached"
                        )
                        break
                prev_image = current_image

                # Wait
                self.cycle.emit("WAITING")
                time.sleep(config.delay_ms / 1000.0)

                if self._stop_flag:
                    break

                # Scroll section via UIA element if available
                self.cycle.emit("SCROLLING")
                scrolled = False
                if section.element_ref:
                    try:
                        from app.utils.uia_utils import scroll_element
                        scrolled = scroll_element(
                            section.element_ref, "down", "large"
                        )
                    except Exception:
                        pass
                if not scrolled:
                    # Fallback to keyboard scroll
                    scroll_down(section.rect)

                time.sleep(config.delay_ms / 1000.0)

        return global_index


# ----------------------------------------------------------
# Helpers
# ----------------------------------------------------------

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


def _make_fallback_section(config: CaptureConfig) -> DiscoveredSection:
    """
    When no sections are discovered, treat the entire
    configured region as one unknown section.
    Preserves legacy single-region behaviour.
    """
    from app.models.section import DiscoveredSection, SectionRect
    return DiscoveredSection(
        section_id="fallback",
        section_type="unknown",
        confidence=0.5,
        rect=SectionRect(
            x=config.region.x,
            y=config.region.y,
            width=config.region.width,
            height=config.region.height,
        ),
        element_ref=None,
        depth=0,
        can_scroll_vertical=True,
        can_scroll_horizontal=False,
        scroll_percent=0.0,
        source="heuristic",
        notes=["fallback: no sections discovered"],
    )
