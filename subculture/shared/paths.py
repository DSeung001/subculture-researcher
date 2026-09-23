"""Where things live on disk, independent of which module asks."""

import os
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
LOCAL_DIR = PROJECT_ROOT / ".local"
FIGURE_PROJECT_ENV = "FIGURE_PROJECT_DIR"
DEFAULT_FIGURE_PROJECT_DIR = Path.home() / "figure_project"


def figure_project_dir() -> Path:
    """Folder shared with figure-cutout; `FIGURE_PROJECT_DIR` (.env) overrides ~/figure_project."""
    value = os.environ.get(FIGURE_PROJECT_ENV, "").strip()
    return Path(value).expanduser() if value else DEFAULT_FIGURE_PROJECT_DIR


def image_export_dir() -> Path:
    """Export records and portable zips; originals live in figure_project_dir()/images."""
    return figure_project_dir() / "exports"
