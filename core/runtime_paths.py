"""Shared filesystem paths for runtime artifacts."""

import os
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent


def graphs_dir() -> Path:
    """Return and create the directory shared by graph writers and HTTP serving."""
    path = Path(os.getenv("GRAPHS_DIR", PROJECT_ROOT / "data" / "graphs"))
    path.mkdir(parents=True, exist_ok=True)
    return path
