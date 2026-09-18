"""Normalize the migrated legacy replay into the BIMA2 ETA/ETD integration contract.

This script does not retrain ML1 or ML2. It is intended only for the migrated
historical prototype snapshot. Legacy DTA fields are preserved as compatibility
aliases and equivalent ETD fields are added.
"""
from __future__ import annotations

import json
import shutil
from pathlib import Path
import sys

import pandas as pd
import yaml

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path: sys.path.insert(0, str(ROOT))
from scripts.v3_paths import output_root, processed_root, model_artifact_root, logs_root
LEGACY_OUTPUT = ROOT / "outputs"
REPLAY = LEGACY_OUTPUT / "04_replay_dashboard"
RUN_OUTPUT = output_root(ROOT)
INTEGRATION = RUN_OUTPUT / "03_eta_etd_integration"
RUN_REPLAY = RUN_OUTPUT / "04_replay_dashboard"
PUBLISHED = LEGACY_OUTPUT / "published"
LOGS = logs_root(ROOT)


def main() -> None:
    INTEGRATION.mkdir(parents=True, exist_ok=True)
    RUN_REPLAY.mkdir(parents=True, exist_ok=True)
    LOGS.mkdir(parents=True, exist_ok=True)
    cfg = yaml.safe_load((ROOT / "config" / "project_config.yaml").read_text(encoding="utf-8"))

    source = REPLAY / "simulation_input_5min_multimodel.csv"
    if not source.exists():
        raise FileNotFoundError(f"Legacy multimodel replay tidak ditemukan: {source}")

    df = pd.read_csv(source, low_memory=False)
    dta_cols = [c for c in df.columns if str(c).startswith("dta_")]
    for col in dta_cols:
        etd_col = col.replace("dta_", "etd_", 1)
        if etd_col not in df.columns:
            df[etd_col] = df[col]

    df["bima2_snapshot_status"] = "LEGACY_PROTOTYPE_SIMULATED_VEHICLE"
    df["operational_claim_allowed"] = False
    target = INTEGRATION / "simulation_input_5min_multimodel.csv"
    df.to_csv(target, index=False)

    # Copy immutable legacy replay support files into this V3 run folder.
    for name in ["visual_track_5min.csv", "daily_operation_schedule.csv", "legacy_simulation_input_5min.csv"]:
        src = REPLAY / name
        if not src.exists():
            raise FileNotFoundError(f"Legacy replay support file tidak ditemukan: {src}")
        shutil.copy2(src, RUN_REPLAY / name)

    # Reuse the published contract profiles as immutable migration inputs.
    for name in ["eta_state_5min.csv", "vehicle_rate_5min.csv"]:
        src = PUBLISHED / name
        if not src.exists():
            raise FileNotFoundError(f"Published legacy contract tidak ditemukan: {src}")
        shutil.copy2(src, INTEGRATION / name)

    report = {
        "mode": "legacy_snapshot_normalization",
        "run_id": cfg.get("run_id"),
        "rows": int(len(df)),
        "legacy_dta_columns": dta_cols,
        "etd_alias_columns": [c.replace("dta_", "etd_", 1) for c in dta_cols],
        "vehicle_provenance": cfg.get("provenance", {}).get("vehicle_manifest_current"),
        "operational_claim_allowed": False,
        "output": str(target.relative_to(ROOT)),
    }
    (LOGS / "latest_integration_migration.json").write_text(
        json.dumps(report, indent=2), encoding="utf-8"
    )
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
