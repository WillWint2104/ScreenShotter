from datetime import datetime
from pathlib import Path
from app.models.capture_session import CaptureSession
from app.utils.paths import new_session_dir


def create_session(label: str = "") -> CaptureSession:
    """Create session directory and return an initialised CaptureSession."""
    session_dir = new_session_dir(label)

    return CaptureSession(
        session_id=session_dir.name,
        session_dir=session_dir,
    )


def next_screenshot_path(session: CaptureSession) -> Path:
    n = session.screenshot_count + 1
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"{n:03d}_{ts}.png"
    return session.session_dir / filename
