# ScrollCapture

A standalone desktop app that captures any on-screen region as sequential, ordered PNG screenshots.

---

## Quickstart

### Easiest — double-click to launch (Windows)
```
run_app.bat
```
Or right-click `run_app.ps1` → Run with PowerShell.

### From terminal
```bash
python launch.py
```

---

## First-time setup

```bash
# 1. Create and activate a virtual environment
python -m venv .venv
.venv\Scripts\activate        # Windows
# source .venv/bin/activate   # macOS/Linux

# 2. Install dependencies
pip install -r requirements.txt
```

---

## Usage

1. Launch the app (see above)
2. Click **Select Region** — app hides, drag a box over the content to capture
3. Adjust delay and scroll method if needed
4. Click **Start Capture** then immediately click the target window to give it focus
5. Click **Stop** when done

Screenshots save to:
```
data/sessions/{timestamp}_region/screenshots/
  capture_001.png
  capture_002.png
  ...
```

---

## If the app doesn't launch

Run from terminal so you can see the error:
```bash
python launch.py
```

Common fixes:

| Error | Fix |
|---|---|
| `Missing dependency: PySide6` | `pip install PySide6` |
| `Missing dependency: mss` | `pip install mss pyautogui Pillow` |
| `No module named 'app'` | Run from the `capture_app/` folder |

---

## Manual launch (fallback)
```bash
cd capture_app
python -m app.main
```

---

## Output structure

```
data/sessions/{timestamp}_{slug}/
  screenshots/      <- PNGs saved here
  extracted/
  review/
  export/
  manifest.json     <- session metadata
```
