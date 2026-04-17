import sys
import os
import logging
from pathlib import Path

# Ensure the project root is on the path regardless of working directory
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Log crashes to file instead of console (no console with pythonw)
_log_dir = Path(__file__).parent / "data"
_log_dir.mkdir(parents=True, exist_ok=True)
logging.basicConfig(
    filename=str(_log_dir / "crash.log"),
    level=logging.ERROR,
    format="%(asctime)s %(levelname)s %(message)s",
)


def main():
    try:
        from PySide6.QtWidgets import QApplication
    except ImportError:
        logging.error("Missing dependency: PySide6")
        sys.exit(1)

    try:
        import mss
    except ImportError:
        logging.error("Missing dependency: mss")
        sys.exit(1)

    try:
        from app.main import main as run_app
        run_app()
    except Exception:
        import traceback
        logging.error("ScrollCapture crashed:\n%s", traceback.format_exc())
        sys.exit(1)


if __name__ == "__main__":
    main()
