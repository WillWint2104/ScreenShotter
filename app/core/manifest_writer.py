import json
from datetime import datetime
from app.models.capture_session import CaptureSession
from app.models.capture_config import CaptureConfig

APP_VERSION = "0.3.0"


def write_initial(session: CaptureSession, config: CaptureConfig) -> None:
    _write(session, config)


def write_final(session: CaptureSession, config: CaptureConfig) -> None:
    _write(session, config)


def _write(session: CaptureSession, config: CaptureConfig) -> None:
    data = {
        "session_id":           session.session_id,
        "created_at":           session.created_at.isoformat(),
        "capture_mode":         "region",
        "region_coordinates":   config.region.as_dict(),
        "delay_ms":             config.delay_ms,
        "similarity_threshold": config.similarity_threshold,
        "screenshot_count":     session.screenshot_count,
        "screenshot_filenames": session.screenshot_filenames,
        "stopped_by_user":      session.stopped_by_user,
        "capture_status":       session.capture_status,
        "app_version":          APP_VERSION,
        "updated_at":           datetime.now().isoformat(),
    }
    manifest_path = session.session_dir / "manifest.json"
    manifest_path.write_text(
        json.dumps(data, indent=2), encoding="utf-8"
    )
