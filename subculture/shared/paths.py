"""Where things live on disk, independent of which module asks."""

from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
LOCAL_DIR = PROJECT_ROOT / ".local"
