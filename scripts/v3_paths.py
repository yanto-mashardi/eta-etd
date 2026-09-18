from __future__ import annotations
import json
import os
from pathlib import Path


def project_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _state_run_root(root: Path, state_file: str, expected_status: str | None = None) -> Path | None:
    """Resolve a run folder recorded in a V3 state file.

    Supports both absolute ``run_root`` and project-relative ``run_folder``.
    JSON is read with utf-8-sig so files with or without BOM are accepted.
    """
    p = root / state_file
    if not p.exists():
        return None
    try:
        d = json.loads(p.read_text(encoding="utf-8-sig"))
        if expected_status and str(d.get("status", "")).upper() != expected_status.upper():
            return None
        raw = d.get("run_root") or d.get("run_folder")
        if not raw:
            return None
        rr = Path(raw)
        if not rr.is_absolute():
            rr = root / rr
        rr = rr.resolve()
        return rr if rr.exists() else None
    except Exception:
        return None


def _run_root(root: Path | None = None) -> Path | None:
    root = Path(root or project_root()).resolve()

    # 1) Explicit run root injected by the V3 launcher/Jupyter process.
    env = os.environ.get("LOCAL_RUN_RUN_ROOT")
    if env:
        p = Path(env)
        if not p.is_absolute():
            p = root / p
        p = p.resolve()
        if p.exists():
            return p

    # 2) Active run, when one is currently open.
    active = _state_run_root(root, "current_run.json", expected_status="ACTIVE")
    if active:
        return active

    # 3) No active run: use the latest successfully closed run.
    latest = _state_run_root(root, "latest_successful_run.json", expected_status="SUCCESS")
    if latest:
        return latest

    return None


def output_root(root: Path | None = None) -> Path:
    root = Path(root or project_root()).resolve()
    return _run_root(root) or (root / "outputs")


def processed_root(root: Path | None = None) -> Path:
    root = Path(root or project_root()).resolve()
    rr = _run_root(root)
    return (rr / "data_processed") if rr else (root / "data" / "processed")


def model_artifact_root(root: Path | None = None) -> Path:
    root = Path(root or project_root()).resolve()
    rr = _run_root(root)
    return (rr / "model_artifacts") if rr else (root / "models")


def logs_root(root: Path | None = None) -> Path:
    root = Path(root or project_root()).resolve()
    rr = _run_root(root)
    return (rr / "logs") if rr else (root / "logs")
