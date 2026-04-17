"""
screen_utils.py

Detects the physical DPI scaling factor of the primary screen at runtime.
Used to convert Qt logical pixel coordinates to physical pixel coordinates
for mss screen capture.
"""
from __future__ import annotations


def get_scale_factor() -> float:
    """
    Return the physical pixel scale factor for the primary screen.

    Qt reports coordinates in logical pixels. mss captures in physical
    pixels. On a 150% scaled display, physical = logical * 1.5.

    Returns 1.0 if scaling cannot be determined.
    """
    try:
        from PySide6.QtWidgets import QApplication
        from PySide6.QtGui import QScreen
        app = QApplication.instance()
        if app is None:
            return 1.0
        screen: QScreen = app.primaryScreen()
        # devicePixelRatio gives the exact physical/logical ratio
        return screen.devicePixelRatio()
    except Exception:
        return 1.0


def logical_to_physical(x: int, y: int, w: int, h: int) -> tuple[int, int, int, int]:
    """
    Convert logical pixel coordinates to physical pixel coordinates.
    """
    scale = get_scale_factor()
    return (
        int(x * scale),
        int(y * scale),
        int(w * scale),
        int(h * scale),
    )
