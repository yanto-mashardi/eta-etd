"""Validate BIMA2 structure, model artifacts, and the published ETA/ETD contract."""
from __future__ import annotations

import json
from pathlib import Path
import sys

import pandas as pd
import yaml

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path: sys.path.insert(0, str(ROOT))
from scripts.v3_paths import output_root, processed_root, model_artifact_root, logs_root
LOGS = logs_root(ROOT)


def main() -> None:
    LOGS.mkdir(parents=True, exist_ok=True)
    cfg = yaml.safe_load((ROOT / "config" / "project_config.yaml").read_text(encoding="utf-8"))

    migration_report = LOGS / "latest_integration_migration.json"
    migration_mode = False
    if migration_report.exists():
        try:
            migration_info = json.loads(migration_report.read_text(encoding="utf-8-sig"))
            migration_mode = migration_info.get("mode") == "legacy_snapshot_normalization"
        except Exception:
            migration_mode = False

    required = {
        "project marker": ROOT / ".local_run_project",
        "AIS raw": ROOT / "data/input/ais/raw/ais_raw_2024.csv",
        "ML1 RF model": model_artifact_root(ROOT) / "ML1_ETA_CORRECTION/06_model_saved/ml1_random_forest.joblib",
        "ML1 XGB model": model_artifact_root(ROOT) / "ML1_ETA_CORRECTION/06_model_saved/ml1_xgboost.joblib",
        "ML2 selected legacy model": model_artifact_root(ROOT) / "ML2_TURNAROUND_CORRECTION/06_model_saved/ml2_turnaround_selected.joblib",
        "vessel capacity": ROOT / "data/reference/vessel_master/vessel_capacity.csv",
        "ports/berths": ROOT / "config/ports_berths.yaml",
        "published operation state": output_root(ROOT) / "published/operation_state_5min.csv",
    }
    if migration_mode:
        required["migrated ETA state"] = output_root(ROOT) / "03_eta_etd_integration/eta_state_5min.csv"
        required["migrated multimodel snapshot"] = output_root(ROOT) / "03_eta_etd_integration/simulation_input_5min_multimodel.csv"
    else:
        required["ML1 replay"] = processed_root(ROOT) / "ml1/replay_20pct/eta_state_rf_source.csv"
    missing = {k: str(v) for k, v in required.items() if not v.exists()}

    state_path = required["published operation state"]
    state_check = {}
    if state_path.exists():
        sample = pd.read_csv(state_path, nrows=50, low_memory=False)
        expected = [
            "simulation_tick", "record_type", "eta_baseline_display_min",
            "eta_corrected_display_min",
            "estimated_arrival_random_forest",
            "estimated_departure_random_forest_random_forest",
            "etd_random_forest_random_forest",
            "etd_random_forest_xgboost",
            "etd_xgboost_random_forest",
            "etd_xgboost_xgboost",
            "bima2_snapshot_status", "operational_claim_allowed",
        ]
        state_check = {
            "missing_columns": [c for c in expected if c not in sample.columns],
            "has_legacy_dta_alias": any(str(c).startswith("dta_") for c in sample.columns),
            "has_etd_fields": all(c in sample.columns for c in expected[6:10]),
        }

    report = {
        "project": cfg.get("project_name"),
        "architecture_version": cfg.get("architecture_version"),
        "integration_mode": "legacy_snapshot_normalization" if migration_mode else "model_rebuild",
        "missing_required_files": missing,
        "published_contract": state_check,
        "vehicle_provenance": cfg.get("provenance", {}).get("vehicle_manifest_current"),
        "operational_claim_allowed": bool(cfg.get("provenance", {}).get("operational_claim_allowed", False)),
        "status": "PASS" if not missing and not state_check.get("missing_columns") else "FAIL",
    }
    (LOGS / "latest_contract_audit.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))
    if report["status"] != "PASS":
        raise RuntimeError("BIMA2 contract audit gagal. Lihat logs/latest_contract_audit.json")


if __name__ == "__main__":
    main()
