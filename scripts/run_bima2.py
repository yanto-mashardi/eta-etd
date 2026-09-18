from __future__ import annotations

import argparse
import importlib
import json
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path: sys.path.insert(0,str(ROOT))
from scripts.v3_paths import output_root, processed_root, logs_root
LOG_DIR = logs_root(ROOT)
LOG_DIR.mkdir(parents=True, exist_ok=True)
LATEST_RUNTIME = LOG_DIR / "latest_runtime.log"
LATEST_STATUS = LOG_DIR / "latest_runtime_status.json"

REQUIRED_PACKAGES = {
    "pandas": "pandas",
    "yaml": "PyYAML",
    "joblib": "joblib",
    "sklearn": "scikit-learn",
    "xgboost": "xgboost",
    "streamlit": "streamlit",
    "pydeck": "pydeck",
}

DASHBOARD_REQUIRED = [
    ROOT / "config" / "project_config.yaml",
    ROOT / "config" / "ports_berths.yaml",
    output_root(ROOT) / "published" / "operation_state_5min.csv",
    ROOT / "scripts" / "dashboard" / "app.py",
]

REPLAY_REQUIRED = [
    output_root(ROOT) / "04_replay_dashboard" / "simulation_input_5min_multimodel.csv",
    output_root(ROOT) / "04_replay_dashboard" / "visual_track_5min.csv",
    output_root(ROOT) / "04_replay_dashboard" / "daily_operation_schedule.csv",
    output_root(ROOT) / "published" / "eta_state_5min.csv",
    output_root(ROOT) / "published" / "vehicle_rate_5min.csv",
    ROOT / "scripts" / "integration" / "run_integration.py",
]


def timestamp() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def log(message: str) -> None:
    line = f"[{timestamp()}] {message}"
    print(line, flush=True)
    with LATEST_RUNTIME.open("a", encoding="utf-8") as f:
        f.write(line + "\n")


def write_status(status: str, **extra) -> None:
    payload = {
        "project": "JAES_SIMULASI_BIMA2",
        "status": status,
        "time": timestamp(),
        "python": sys.executable,
        "project_root": str(ROOT),
    }
    payload.update(extra)
    LATEST_STATUS.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")


def check_packages() -> dict[str, str]:
    versions: dict[str, str] = {}
    missing = []
    for module_name, package_name in REQUIRED_PACKAGES.items():
        try:
            module = importlib.import_module(module_name)
            versions[package_name] = str(getattr(module, "__version__", "installed"))
        except Exception as exc:
            missing.append(f"{package_name}: {type(exc).__name__}: {exc}")
    if missing:
        raise RuntimeError(
            "Dependency belum lengkap:\n- " + "\n- ".join(missing)
            + "\nJalankan 00_SETUP_LOCAL_ENV.ps1 dari root LOCAL_RUN sekali lagi."
        )
    return versions


def check_files(paths: list[Path], label: str) -> None:
    missing = [str(p.relative_to(ROOT)) for p in paths if not p.exists()]
    if missing:
        raise FileNotFoundError(f"{label} belum lengkap:\n- " + "\n- ".join(missing))


def dashboard_contract_check() -> dict:
    import pandas as pd

    path = output_root(ROOT) / "published" / "operation_state_5min.csv"
    sample = pd.read_csv(path, nrows=500, low_memory=False)
    required_cols = [
        "simulation_tick", "record_type", "mmsi", "latitude", "longitude",
        "eta_baseline_min", "eta_corrected_random_forest_min",
        "eta_corrected_xgboost_min", "turnaround_base_min",
        "etd_random_forest_random_forest", "etd_random_forest_xgboost",
        "etd_xgboost_random_forest", "etd_xgboost_xgboost",
        "bima2_snapshot_status", "operational_claim_allowed",
    ]
    missing = [c for c in required_cols if c not in sample.columns]
    if missing:
        raise RuntimeError("Kontrak dashboard kehilangan kolom: " + ", ".join(missing))

    record_types = sorted(sample["record_type"].dropna().astype(str).unique().tolist())
    return {
        "sample_rows_checked": int(len(sample)),
        "columns": int(len(sample.columns)),
        "record_types_in_sample": record_types,
        "snapshot_status": str(sample["bima2_snapshot_status"].dropna().iloc[0])
        if sample["bima2_snapshot_status"].notna().any() else "UNKNOWN",
        "operational_claim_allowed": bool(sample["operational_claim_allowed"].fillna(False).astype(bool).all()),
    }


def run_script(relative_path: str, extra: list[str] | None = None) -> None:
    script = ROOT / relative_path
    cmd = [sys.executable, str(script), *(extra or [])]
    log("RUN " + " ".join(cmd))
    subprocess.run(cmd, cwd=ROOT, check=True)


def check_runtime(require_replay_sources: bool = False) -> dict:
    log("Memeriksa shared Python environment...")
    versions = check_packages()
    log("Dependency Python: PASS")
    check_files(DASHBOARD_REQUIRED, "File dashboard")
    log("File dashboard: PASS")
    if require_replay_sources:
        check_files(REPLAY_REQUIRED, "Sumber historical replay")
        log("Sumber historical replay: PASS")
    contract = dashboard_contract_check()
    log("Kontrak operation_state_5min.csv: PASS")
    result = {"packages": versions, "contract": contract}
    write_status("CHECK_PASS", **result)
    return result


def replay() -> None:
    check_runtime(require_replay_sources=True)
    log("Membangun ulang historical replay BIMA2 dari migrated snapshot...")
    run_script("scripts/integration/run_integration.py")
    contract = dashboard_contract_check()
    log("Historical replay dan contract validation: PASS")
    write_status("REPLAY_READY", contract=contract)


def dashboard(port: int) -> None:
    result = check_runtime(require_replay_sources=False)
    log(f"Menjalankan dashboard Streamlit pada http://localhost:{port}")
    write_status("DASHBOARD_STARTING", port=port, contract=result["contract"])
    cmd = [
        sys.executable, "-m", "streamlit", "run",
        str(ROOT / "scripts" / "dashboard" / "app.py"),
        "--server.address", "127.0.0.1",
        "--server.port", str(port),
        "--server.headless", "false",
        "--browser.gatherUsageStats", "false",
    ]
    subprocess.run(cmd, cwd=ROOT, check=True)


def audit() -> None:
    check_runtime(require_replay_sources=False)
    run_script("scripts/audit_project.py")
    run_script("scripts/integration/validate_contract.py")
    log("Project audit: PASS")
    write_status("AUDIT_PASS")


def main() -> None:
    parser = argparse.ArgumentParser(description="JAES BIMA2 local runtime controller")
    parser.add_argument("mode", choices=["check", "replay", "dashboard", "replay-dashboard", "audit"])
    parser.add_argument("--port", type=int, default=8501)
    args = parser.parse_args()

    LATEST_RUNTIME.write_text("", encoding="utf-8")
    log(f"BIMA2 runtime controller | mode={args.mode}")
    try:
        if args.mode == "check":
            result = check_runtime(require_replay_sources=True)
            print(json.dumps(result, indent=2))
        elif args.mode == "replay":
            replay()
        elif args.mode == "dashboard":
            dashboard(args.port)
        elif args.mode == "replay-dashboard":
            replay()
            dashboard(args.port)
        elif args.mode == "audit":
            audit()
    except Exception as exc:
        log(f"ERROR {type(exc).__name__}: {exc}")
        write_status("ERROR", error_type=type(exc).__name__, error=str(exc))
        raise


if __name__ == "__main__":
    main()
