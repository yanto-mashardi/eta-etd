from __future__ import annotations
from pathlib import Path
from typing import Optional


PROJECT_MARKERS = (".local_run_project", ".oe_project_root")


def find_project_root(start: Optional[Path] = None) -> Path:
    """Find a LOCAL_RUN project root from cwd or one of its parents."""
    p = Path(start or Path.cwd()).resolve()
    for candidate in (p, *p.parents):
        if any((candidate / marker).exists() for marker in PROJECT_MARKERS):
            return candidate
    raise FileNotFoundError(
        "Project root tidak ditemukan. Pastikan .local_run_project "
        "(atau marker legacy .oe_project_root) tersedia di root project."
    )


def ensure_standard_dirs(project_root: Path) -> None:
    project_root = Path(project_root)
    dirs = [
        "data/input",
        "data/reference",
        "data/processed",
        "notebooks",
        "models",
        "outputs/model_runs",
        "config",
        "scripts",
        "docs",
        "logs",
    ]
    for rel in dirs:
        (project_root / rel).mkdir(parents=True, exist_ok=True)
