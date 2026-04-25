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


# ---------------------------------------------------------------------------
# Spec 6 extension — section-aware manifest writing.
# Adds new functions without modifying anything above. Existing
# write_initial / write_final / _write are unchanged.
# ---------------------------------------------------------------------------

def write_section_manifest(
    session_dir: "Path",
    session: "CaptureSession",
    config: "CaptureConfig",
    sections: list,
    profile_match: dict | None = None,
) -> None:
    """
    Extended manifest writer that includes section discovery
    results and profile match information.
    Writes to manifest.json alongside existing fields.
    """
    from pathlib import Path

    base_data = _build_base(session, config)
    base_data["sections_discovered"] = [
        s.as_dict() if hasattr(s, "as_dict") else s
        for s in sections
    ]
    base_data["profile_match"] = profile_match or {
        "profile_matched": False,
        "profile_name": "",
        "profile_match_confidence": 0.0,
        "profile_match_reason": [],
        "mode": "none",
    }
    manifest_path = Path(session_dir) / "manifest.json"
    manifest_path.write_text(
        json.dumps(base_data, indent=2),
        encoding="utf-8",
    )


def _build_base(session: "CaptureSession", config: "CaptureConfig") -> dict:
    """
    Build the base manifest dict shared by all write functions.
    """
    return {
        "session_id": session.session_id,
        "created_at": session.created_at.isoformat(),
        "capture_mode": "region",
        "region_coordinates": config.region.as_dict(),
        "delay_ms": config.delay_ms,
        "similarity_threshold": config.similarity_threshold,
        "screenshot_count": session.screenshot_count,
        "screenshot_filenames": session.screenshot_filenames,
        "stopped_by_user": session.stopped_by_user,
        "capture_status": session.capture_status,
        "app_version": APP_VERSION,
        "updated_at": datetime.now().isoformat(),
    }
