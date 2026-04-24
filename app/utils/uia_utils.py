"""
uia_utils.py — Windows UI Automation foundation.

Spec 1 of 9 (see docs/ARCHITECTURE.md). This module is the UIA foundation
every higher layer (section_discoverer, profile_manager, expander,
field_mapper) builds on. It is intentionally generic — it answers "what
is on screen and what can I do with it?" — and knows nothing about
sessions, batches, profiles, or evaluations.

Design rules (enforced per function):
- Every UIA/Win32 call is wrapped in try/except.
- A failure returns None or False, never raises.
- All rects returned are in LOGICAL pixels (physical / scale_factor).
- Scale factor comes from app.utils.screen_utils.get_scale_factor().
"""
from __future__ import annotations

import ctypes
import logging
import os
from ctypes import wintypes
from typing import Any, Optional

from app.utils.screen_utils import get_scale_factor

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Win32 handles — declare restype/argtypes once so HANDLE/HWND/HMONITOR are
# treated as pointer-sized on 64-bit Python (ctypes otherwise defaults to
# c_int and truncates the high 32 bits of pointer-sized returns).
#
# Guarded behind os.name == "nt" so importing this module on Linux/macOS
# (CI, static analysis, test collection) does not raise AttributeError on
# ctypes.windll. Every public function still degrades to None/False when
# _k32/_u32 are None, matching the "failure returns None/False, never
# raises" contract in the module docstring.
# ---------------------------------------------------------------------------

_k32: Optional[Any] = None
_u32: Optional[Any] = None

if os.name == "nt":  # pragma: no branch - module is Windows-only in practice
    _k32 = ctypes.windll.kernel32
    _u32 = ctypes.windll.user32

    _k32.OpenProcess.restype = wintypes.HANDLE
    _k32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    _k32.QueryFullProcessImageNameW.restype = wintypes.BOOL
    _k32.QueryFullProcessImageNameW.argtypes = [
        wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD),
    ]
    _k32.CloseHandle.restype = wintypes.BOOL
    _k32.CloseHandle.argtypes = [wintypes.HANDLE]

    _u32.GetForegroundWindow.restype = wintypes.HWND
    _u32.GetForegroundWindow.argtypes = []
    _u32.GetWindowThreadProcessId.restype = wintypes.DWORD
    _u32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
    _u32.GetWindowRect.restype = wintypes.BOOL
    _u32.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
    _u32.MonitorFromWindow.restype = wintypes.HMONITOR
    _u32.MonitorFromWindow.argtypes = [wintypes.HWND, wintypes.DWORD]
    _u32.IsWindowVisible.restype = wintypes.BOOL
    _u32.IsWindowVisible.argtypes = [wintypes.HWND]
    _u32.GetWindowTextLengthW.restype = ctypes.c_int
    _u32.GetWindowTextLengthW.argtypes = [wintypes.HWND]
    _u32.GetWindowTextW.restype = ctypes.c_int
    _u32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
    _u32.EnumWindows.restype = wintypes.BOOL
    _u32.EnumWindows.argtypes = [ctypes.c_void_p, wintypes.LPARAM]
    _u32.EnumDisplayMonitors.restype = wintypes.BOOL
    _u32.EnumDisplayMonitors.argtypes = [
        wintypes.HDC, ctypes.POINTER(wintypes.RECT), ctypes.c_void_p, wintypes.LPARAM,
    ]

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_BROWSER_EXES = {"chrome.exe": "chrome", "msedge.exe": "edge", "firefox.exe": "firefox"}

# Tokens that must never be clicked. Case-insensitive substring match
# against element name and accessible value. See ARCHITECTURE.md
# "Protected elements — never clicked under any circumstances".
_PROTECTED_TOKENS = (
    "abort", "back", "cancel", "close", "complete", "dismiss", "done",
    "escape", "finish", "flag", "next", "skip", "submit",
)

# Approximate vertical reservation for browser chrome (tabs + address bar)
# measured from the top of a browser window in logical pixels. Used to
# filter out chrome-region scrollables in get_scrollable_regions.
_BROWSER_CHROME_PX = 140

# UIA pattern / property IDs (comtypes exposes these but we pin them to
# avoid a dependency on the generated module loading at import time).
_UIA_ScrollPatternId = 10004
_UIA_ExpandCollapsePatternId = 10005
_UIA_ValuePatternId = 10002
_TreeScope_Descendants = 4

# ScrollPattern amounts (see UIA ScrollAmount enum).
_ScrollAmount_LargeDecrement = 0
_ScrollAmount_SmallDecrement = 1
_ScrollAmount_NoAmount = 2
_ScrollAmount_LargeIncrement = 3
_ScrollAmount_SmallIncrement = 4

# Win32
_PROCESS_QUERY_LIMITED_INFORMATION = 0x1000

# ---------------------------------------------------------------------------
# UIA singleton
# ---------------------------------------------------------------------------

_uia_instance = None
_uia_init_failed = False


def _get_uia() -> Optional[Any]:
    """Return an IUIAutomation instance, lazily initialised. None on failure."""
    global _uia_instance, _uia_init_failed
    if _uia_instance is not None:
        return _uia_instance
    if _uia_init_failed:
        return None
    try:
        import comtypes.client
        comtypes.client.GetModule("UIAutomationCore.dll")
        from comtypes.gen import UIAutomationClient as _UIA
        _uia_instance = comtypes.client.CreateObject(
            _UIA.CUIAutomation, interface=_UIA.IUIAutomation
        )
        return _uia_instance
    except Exception as exc:  # noqa: BLE001
        logger.warning("UIA initialisation failed: %s", exc)
        _uia_init_failed = True
        return None


# ---------------------------------------------------------------------------
# Coordinate helpers
# ---------------------------------------------------------------------------

def _physical_to_logical(x: int, y: int, w: int, h: int) -> dict:
    """Convert a physical pixel rect to a logical pixel rect dict."""
    scale = get_scale_factor() or 1.0
    return {
        "x": round(x / scale),
        "y": round(y / scale),
        "width": round(w / scale),
        "height": round(h / scale),
    }


def _logical_to_physical_point(x: int, y: int) -> tuple[int, int]:
    scale = get_scale_factor() or 1.0
    return round(x * scale), round(y * scale)


def _rect_from_uia(element_ref) -> Optional[dict]:
    """Read BoundingRectangle (physical) and return logical dict."""
    try:
        r = element_ref.CurrentBoundingRectangle
        w = int(r.right) - int(r.left)
        h = int(r.bottom) - int(r.top)
        return _physical_to_logical(int(r.left), int(r.top), w, h)
    except Exception as exc:  # noqa: BLE001
        logger.warning("rect read failed: %s", exc)
        return None


# ---------------------------------------------------------------------------
# Process / window helpers
# ---------------------------------------------------------------------------

def _process_exe_name(pid: int) -> str:
    """Return lowercase basename of the executable owning pid, or ''."""
    try:
        handle = _k32.OpenProcess(_PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
        if not handle:
            return ""
        try:
            buf = ctypes.create_unicode_buffer(1024)
            size = wintypes.DWORD(1024)
            ok = _k32.QueryFullProcessImageNameW(handle, 0, buf, ctypes.byref(size))
            if not ok:
                return ""
            return os.path.basename(buf.value).lower()
        finally:
            _k32.CloseHandle(handle)
    except Exception as exc:  # noqa: BLE001
        logger.warning("process name lookup failed for pid %s: %s", pid, exc)
        return ""


def _hwnd_browser_tag(hwnd: int) -> Optional[str]:
    """Return 'chrome' | 'edge' | 'firefox' if hwnd is a browser window, else None."""
    try:
        pid = wintypes.DWORD()
        _u32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        return _BROWSER_EXES.get(_process_exe_name(pid.value))
    except Exception as exc:  # noqa: BLE001
        logger.warning("browser tag lookup failed for hwnd %s: %s", hwnd, exc)
        return None


def _hwnd_rect_logical(hwnd: int) -> Optional[dict]:
    try:
        rect = wintypes.RECT()
        if not _u32.GetWindowRect(hwnd, ctypes.byref(rect)):
            return None
        return _physical_to_logical(
            rect.left, rect.top, rect.right - rect.left, rect.bottom - rect.top
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("GetWindowRect failed for hwnd %s: %s", hwnd, exc)
        return None


def _hwnd_monitor_index(hwnd: int) -> int:
    """Return 0-based index of the monitor the window is primarily on."""
    try:
        MONITOR_DEFAULTTONEAREST = 2
        target = _u32.MonitorFromWindow(hwnd, MONITOR_DEFAULTTONEAREST)
        monitors: list[int] = []
        MONITORENUMPROC = ctypes.WINFUNCTYPE(
            wintypes.BOOL, wintypes.HMONITOR, wintypes.HDC,
            ctypes.POINTER(wintypes.RECT), wintypes.LPARAM,
        )

        def _cb(hmon, _hdc, _rect, _lparam):  # pragma: no cover - ctypes cb
            monitors.append(int(hmon))
            return 1

        _u32.EnumDisplayMonitors(0, None, MONITORENUMPROC(_cb), 0)
        if target and int(target) in monitors:
            return monitors.index(int(target))
        return 0
    except Exception as exc:  # noqa: BLE001
        logger.warning("monitor lookup failed for hwnd %s: %s", hwnd, exc)
        return 0


def _enum_browser_windows() -> list[tuple[int, str]]:
    """Return [(hwnd, browser_tag), ...] for all visible top-level browser windows."""
    results: list[tuple[int, str]] = []
    try:
        WNDENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

        def _cb(hwnd, _lparam):  # pragma: no cover - ctypes cb
            try:
                if not _u32.IsWindowVisible(hwnd):
                    return 1
                length = _u32.GetWindowTextLengthW(hwnd)
                if length <= 0:
                    return 1
                tag = _hwnd_browser_tag(hwnd)
                if tag:
                    results.append((hwnd, tag))
            except Exception:  # noqa: BLE001
                pass
            return 1

        _u32.EnumWindows(WNDENUMPROC(_cb), 0)
    except Exception as exc:  # noqa: BLE001
        logger.warning("EnumWindows failed: %s", exc)
    return results


def _hwnd_title(hwnd: int) -> str:
    try:
        length = _u32.GetWindowTextLengthW(hwnd)
        if length <= 0:
            return ""
        buf = ctypes.create_unicode_buffer(length + 1)
        _u32.GetWindowTextW(hwnd, buf, length + 1)
        return buf.value
    except Exception as exc:  # noqa: BLE001
        logger.warning("window title read failed for hwnd %s: %s", hwnd, exc)
        return ""


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def get_active_browser_window() -> Optional[dict]:
    """Return info about the active browser window, or None."""
    try:
        fg = int(_u32.GetForegroundWindow() or 0)
        candidate_hwnd: Optional[int] = None
        browser_tag: Optional[str] = None
        if fg:
            tag = _hwnd_browser_tag(fg)
            if tag:
                candidate_hwnd, browser_tag = fg, tag
        if candidate_hwnd is None:
            browsers = _enum_browser_windows()
            if not browsers:
                return None
            candidate_hwnd, browser_tag = browsers[0]
        rect = _hwnd_rect_logical(candidate_hwnd)
        if rect is None or browser_tag is None:
            return None
        return {
            "hwnd": int(candidate_hwnd),
            "title": _hwnd_title(candidate_hwnd),
            "browser": browser_tag,
            "rect": rect,
            "monitor": _hwnd_monitor_index(candidate_hwnd),
        }
    except Exception as exc:  # noqa: BLE001
        logger.warning("get_active_browser_window failed: %s", exc)
        return None


def _depth_from_root(element_ref, root) -> int:
    """Count TreeWalker parent steps from element_ref up to root. Cap at 64."""
    try:
        uia = _get_uia()
        if uia is None or root is None:
            return 0
        walker = uia.ControlViewWalker
        depth = 0
        cursor = element_ref
        while cursor is not None and depth < 64:
            try:
                if uia.CompareElements(cursor, root):
                    return depth
            except Exception:  # noqa: BLE001
                pass
            cursor = walker.GetParentElement(cursor)
            depth += 1
        return depth
    except Exception:  # noqa: BLE001
        return 0


def get_scrollable_regions(hwnd: int) -> list[dict]:
    """Return all scrollable UIA containers in the given browser window."""
    results: list[dict] = []
    uia = _get_uia()
    if uia is None:
        return results
    try:
        root = uia.ElementFromHandle(hwnd)
        if root is None:
            return results
        window_rect = _hwnd_rect_logical(hwnd) or {"x": 0, "y": 0, "width": 0, "height": 0}
        chrome_cutoff_y = window_rect["y"] + _BROWSER_CHROME_PX
        cond = uia.CreatePropertyCondition(
            30034,  # UIA_IsScrollPatternAvailablePropertyId
            True,
        )
        found = root.FindAll(_TreeScope_Descendants, cond)
        count = found.Length if found is not None else 0
        for i in range(count):
            try:
                el = found.GetElement(i)
                rect = _rect_from_uia(el)
                if rect is None or rect["width"] < 100 or rect["height"] < 100:
                    continue
                if rect["y"] < chrome_cutoff_y and rect["height"] < 200:
                    continue  # likely browser chrome
                pattern = el.GetCurrentPattern(_UIA_ScrollPatternId)
                if pattern is None:
                    continue
                from comtypes.gen.UIAutomationClient import IUIAutomationScrollPattern
                sp = pattern.QueryInterface(IUIAutomationScrollPattern)
                v = bool(sp.CurrentVerticallyScrollable)
                h = bool(sp.CurrentHorizontallyScrollable)
                vp = float(sp.CurrentVerticalScrollPercent) if v else -1.0
                hp = float(sp.CurrentHorizontalScrollPercent) if h else -1.0
                percent = vp if v else hp if h else 0.0
                results.append({
                    "element_ref": el,
                    "rect": rect,
                    "can_scroll_vertical": v,
                    "can_scroll_horizontal": h,
                    "scroll_percent": max(0.0, percent),
                    "depth": _depth_from_root(el, root),
                })
            except Exception as exc:  # noqa: BLE001
                logger.warning("scrollable region %d read failed: %s", i, exc)
                continue
    except Exception as exc:  # noqa: BLE001
        logger.warning("get_scrollable_regions failed: %s", exc)
    results.sort(key=lambda r: r["rect"]["y"])
    return results


def scroll_element(element_ref, direction: str, amount: str) -> bool:
    """Scroll via UIA ScrollPattern. Returns False if pattern unavailable
    or if direction/amount are not one of the documented values."""
    if amount not in ("small", "large"):
        logger.warning("scroll_element: unknown amount %r", amount)
        return False
    if direction not in ("up", "down"):
        logger.warning("scroll_element: unknown direction %r", direction)
        return False
    try:
        pattern = element_ref.GetCurrentPattern(_UIA_ScrollPatternId)
        if pattern is None:
            return False
        from comtypes.gen.UIAutomationClient import IUIAutomationScrollPattern
        sp = pattern.QueryInterface(IUIAutomationScrollPattern)
        if direction == "down":
            v = _ScrollAmount_LargeIncrement if amount == "large" else _ScrollAmount_SmallIncrement
        else:
            v = _ScrollAmount_LargeDecrement if amount == "large" else _ScrollAmount_SmallDecrement
        sp.Scroll(_ScrollAmount_NoAmount, v)
        return True
    except Exception as exc:  # noqa: BLE001
        logger.warning("scroll_element failed (%s/%s): %s", direction, amount, exc)
        return False


def get_element_at_point(x: int, y: int) -> Optional[dict]:
    """Return element info at logical screen coordinates x, y."""
    uia = _get_uia()
    if uia is None:
        return None
    try:
        px, py = _logical_to_physical_point(x, y)

        class _POINT(ctypes.Structure):
            _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]

        el = uia.ElementFromPoint(_POINT(px, py))
        if el is None:
            return None
        rect = _rect_from_uia(el) or {"x": 0, "y": 0, "width": 0, "height": 0}
        is_scrollable = False
        try:
            is_scrollable = el.GetCurrentPattern(_UIA_ScrollPatternId) is not None
        except Exception:  # noqa: BLE001
            pass
        return {
            "element_ref": el,
            "rect": rect,
            "is_scrollable": is_scrollable,
            "role": getattr(el, "CurrentLocalizedControlType", "") or "",
            "name": getattr(el, "CurrentName", "") or "",
        }
    except Exception as exc:  # noqa: BLE001
        logger.warning("get_element_at_point(%d,%d) failed: %s", x, y, exc)
        return None


def is_protected_element(element_ref) -> bool:
    """Return True if element must never be clicked (safety list)."""
    try:
        name = str(getattr(element_ref, "CurrentName", "") or "")
        value = ""
        try:
            vp = element_ref.GetCurrentPattern(_UIA_ValuePatternId)
            if vp is not None:
                from comtypes.gen.UIAutomationClient import IUIAutomationValuePattern
                value = str(vp.QueryInterface(IUIAutomationValuePattern).CurrentValue or "")
        except Exception:  # noqa: BLE001
            value = ""
        haystack = f"{name} {value}".lower()
        return any(token in haystack for token in _PROTECTED_TOKENS)
    except Exception as exc:  # noqa: BLE001
        logger.warning("is_protected_element failed: %s", exc)
        return False


def get_element_metadata(element_ref) -> dict:
    """Return a complete metadata dict. All fields always present."""
    meta = {
        "name": "",
        "role": "",
        "rect": {"x": 0, "y": 0, "width": 0, "height": 0},
        "is_scrollable": False,
        "is_expandable": False,
        "is_protected": False,
        "depth": 0,
        "children_count": 0,
    }
    try:
        meta["name"] = str(getattr(element_ref, "CurrentName", "") or "")
        meta["role"] = str(getattr(element_ref, "CurrentLocalizedControlType", "") or "")
        rect = _rect_from_uia(element_ref)
        if rect is not None:
            meta["rect"] = rect
        try:
            meta["is_scrollable"] = element_ref.GetCurrentPattern(_UIA_ScrollPatternId) is not None
        except Exception:  # noqa: BLE001
            meta["is_scrollable"] = False
        try:
            meta["is_expandable"] = element_ref.GetCurrentPattern(_UIA_ExpandCollapsePatternId) is not None
        except Exception:  # noqa: BLE001
            meta["is_expandable"] = False
        meta["is_protected"] = is_protected_element(element_ref)
        uia = _get_uia()
        if uia is not None:
            walker = uia.ControlViewWalker
            # children: iterate GetNextSiblingElement, stopping on COM errors
            count = 0
            try:
                child = walker.GetFirstChildElement(element_ref)
            except Exception:  # noqa: BLE001
                child = None
            while child is not None and count < 4096:
                count += 1
                try:
                    child = walker.GetNextSiblingElement(child)
                except Exception:  # noqa: BLE001
                    break
            meta["children_count"] = count
            # depth: walk up via GetParentElement, stopping on None or COM errors
            depth = 0
            try:
                parent = walker.GetParentElement(element_ref)
            except Exception:  # noqa: BLE001
                parent = None
            while parent is not None and depth < 4096:
                depth += 1
                try:
                    parent = walker.GetParentElement(parent)
                except Exception:  # noqa: BLE001
                    break
            meta["depth"] = depth
    except Exception as exc:  # noqa: BLE001
        logger.warning("get_element_metadata failed: %s", exc)
    return meta
