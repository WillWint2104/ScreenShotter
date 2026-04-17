# Architecture

## Module responsibilities

### app/main.py
Entry point. Creates QApplication and MainWindow, starts event loop.

### app/ui/main_window.py
Top-level window. Owns ControlsPanel and ProgressPanel. Wires signals to core logic.

### app/ui/controls_panel.py
All user inputs: URL, overlap, delay, checkbox, start/stop buttons.
Emits: start_requested, stop_requested, open_folder_requested.

### app/ui/progress_panel.py
Progress bar, shot counter, status text, last session path.

### app/core/capture_engine.py
Orchestrates a full capture run. Calls browser_session, scroll_logic, file_manager.
Runs in a worker thread; emits progress signals back to the UI.

### app/core/browser_session.py
Playwright lifecycle: launch, navigate, read dimensions, scroll, screenshot, close.

### app/core/scroll_logic.py
Pure functions: compute step size, detect page bottom, guard against duplicate final shots.

### app/core/file_manager.py
Create session folder tree. Write PNG files. Return paths.

### app/core/manifest_writer.py
Read/write manifest.json. Accepts a CaptureSession model and serialises it.

### app/core/config_manager.py
Persist user preferences (last URL, slider positions) between launches.

### app/core/export_preparer.py
Validate a completed session. Build ExportSummary. Copy files to export/.

### app/models/capture_config.py
Dataclass: all settings for a single capture run (url, overlap, delay, etc).

### app/models/capture_session.py
Dataclass: runtime state of a session (session_id, paths, screenshot list, status).

### app/utils/paths.py
Windows-safe path helpers. Session slug generation from URL + timestamp.

### app/utils/logging_utils.py
Configure per-session rotating log file in the session folder.

### app/utils/image_utils.py
Image validation helpers (check PNG is non-empty, get dimensions).
