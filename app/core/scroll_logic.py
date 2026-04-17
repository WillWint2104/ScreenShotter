"""
scroll_logic.py

Sends scroll commands to the currently focused window.
No mouse interaction. No wheel option.
"""
from __future__ import annotations
import time
from app.models.capture_config import RegionCoords


def scroll_down(region: RegionCoords) -> None:
    import pyautogui
    pyautogui.PAUSE = 0
    _focus_window_at(region)
    time.sleep(0.05)
    pyautogui.press("pagedown")


def _focus_window_at(region: RegionCoords) -> None:
    """Activate the window under the region center without clicking."""
    import ctypes

    user32 = ctypes.windll.user32
    kernel32 = ctypes.windll.kernel32

    cx = region.x + region.width // 2
    cy = region.y + region.height // 2

    class POINT(ctypes.Structure):
        _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]

    hwnd = user32.WindowFromPoint(POINT(cx, cy))
    if not hwnd:
        return

    GA_ROOT = 2
    root = user32.GetAncestor(hwnd, GA_ROOT)
    if root:
        hwnd = root

    # SetForegroundWindow is restricted unless our thread is attached
    # to the foreground window's thread input queue.
    fg = user32.GetForegroundWindow()
    if fg == hwnd:
        return  # Already focused

    fg_tid = user32.GetWindowThreadProcessId(fg, None)
    our_tid = kernel32.GetCurrentThreadId()

    attached = False
    if fg_tid != our_tid:
        attached = user32.AttachThreadInput(our_tid, fg_tid, True)

    user32.SetForegroundWindow(hwnd)

    if attached:
        user32.AttachThreadInput(our_tid, fg_tid, False)


def scroll_back_to(
    region: RegionCoords,
    start_reference,
    similarity_threshold: float = 0.98,
    max_attempts: int = 60,
) -> None:
    """
    Scroll up until the current view matches start_reference.
    Uses Page Up + frame comparison to find the original position.
    """
    import time
    import mss
    from PIL import Image
    from app.utils.screen_utils import logical_to_physical
    import pyautogui

    pyautogui.PAUSE = 0
    _focus_window_at(region)
    time.sleep(0.2)

    px, py, pw, ph = logical_to_physical(
        region.x, region.y, region.width, region.height
    )
    mon = {"top": py, "left": px, "width": pw, "height": ph}

    # Scroll up until we match the start reference
    with mss.mss() as sct:
        for _ in range(max_attempts):
            shot = sct.grab(mon)
            current = Image.frombytes("RGB", shot.size, shot.rgb)
            if _frames_similar(current, start_reference, similarity_threshold):
                return  # Found the start position
            pyautogui.press("pageup")
            time.sleep(0.15)


def _frames_similar(
    a, b, threshold: float
) -> bool:
    """Quick 64x64 pixel comparison (same logic as capture_engine)."""
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
