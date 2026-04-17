# ScrollCapture

Region-based screen capture tool with scroll automation. Captures a
user-selected area on each scroll step and stitches or exports the
resulting sequence.

## Run

```bat
.venv\Scripts\python.exe launch.py
```

Or double-click `run_app.bat`.

## Requirements

Python 3.12+ and the packages in [requirements.txt](requirements.txt).
Windows-only: uses UI Automation for scrollable region detection.

## Layout

- `app/core/` — capture engine, session/manifest, scroll logic
- `app/ui/`   — PySide6 windows, overlays, region detector
- `app/models/` — capture config and session dataclasses
- `app/utils/` — screen coords, logging, paths
- `docs/` — architecture notes
