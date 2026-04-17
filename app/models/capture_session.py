from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Literal

CaptureStatus = Literal["pending", "running", "complete", "stopped", "error"]


@dataclass
class CaptureSession:
    session_id: str
    session_dir: Path
    created_at: datetime = field(default_factory=datetime.now)
    capture_status: CaptureStatus = "pending"
    screenshot_filenames: list[str] = field(default_factory=list)
    stopped_by_user: bool = False

    @property
    def screenshot_count(self) -> int:
        return len(self.screenshot_filenames)
