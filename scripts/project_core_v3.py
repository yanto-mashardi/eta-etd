from __future__ import annotations

import json
import os
import platform
import re
from pathlib import Path
from typing import Optional

PROJECT_MARKERS = ('.local_run_project', '.oe_project_root')
CURRENT_RUN_FILE = 'current_run.json'
LATEST_SUCCESS_FILE = 'latest_successful_run.json'


def find_project_root(start: Optional[Path] = None) -> Path:
    p = Path(start or Path.cwd()).resolve()
    for candidate in (p, *p.parents):
        if any((candidate / marker).exists() for marker in PROJECT_MARKERS):
            return candidate
    raise FileNotFoundError('LOCAL_RUN project root tidak ditemukan.')


def machine_id() -> str:
    raw = os.environ.get('LOCAL_RUN_MACHINE_ID') or os.environ.get('COMPUTERNAME') or platform.node() or 'UNKNOWN_PC'
    clean = re.sub(r'[^A-Za-z0-9_-]+', '_', str(raw).strip()).strip('_')
    return clean or 'UNKNOWN_PC'


def load_json(path: Path, default=None):
    try:
        return json.loads(Path(path).read_text(encoding='utf-8-sig'))
    except FileNotFoundError:
        return default


def load_current_run(project_root: Optional[Path] = None):
    root = find_project_root(project_root)
    return load_json(root / CURRENT_RUN_FILE, None)


def get_current_run_root(project_root: Optional[Path] = None) -> Optional[Path]:
    root = find_project_root(project_root)
    ctx = load_current_run(root)
    if not ctx:
        return None
    rel = ctx.get('run_folder') or ctx.get('run_root')
    if not rel:
        return None
    p = Path(rel)
    return p if p.is_absolute() else root / p


def get_output_root(project_root: Optional[Path] = None) -> Path:
    root = find_project_root(project_root)
    return get_current_run_root(root) or (root / 'outputs')


def get_logs_dir(project_root: Optional[Path] = None) -> Path:
    root = find_project_root(project_root)
    run_root = get_current_run_root(root)
    return (run_root / 'logs') if run_root else (root / 'logs')


def ensure_standard_dirs(project_root: Path) -> None:
    root = Path(project_root)
    for rel in ['data/input','data/reference','data/processed','notebooks','outputs','config','scripts','docs','logs']:
        (root / rel).mkdir(parents=True, exist_ok=True)
