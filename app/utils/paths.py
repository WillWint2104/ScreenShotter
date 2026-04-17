import re
from datetime import datetime
from pathlib import Path

# Root of the project (capture_app/)
PROJECT_ROOT = Path(__file__).resolve().parents[3]
SESSIONS_DIR = PROJECT_ROOT / "data" / "sessions"


def sessions_root() -> Path:
    SESSIONS_DIR.mkdir(parents=True, exist_ok=True)
    return SESSIONS_DIR


def new_session_dir(label: str = "") -> Path:
    """
    Create and return a new session directory.
    Name format: 20240411_143022_<slug>
    """
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    slug = _slugify(label)[:40] if label else "region"
    name = f"{ts}_{slug}"
    path = sessions_root() / name
    path.mkdir(parents=True, exist_ok=True)
    return path


def _slugify(text: str) -> str:
    text = text.lower().strip()
    text = re.sub(r"[^\w\s-]", "", text)
    text = re.sub(r"[\s_-]+", "_", text)
    return text.strip("_") or "session"
