# Migration Audit — JAES_SIMULASI_BIMA2

## Status

Migration from the legacy Ferry Prediction System into `LOCAL_RUN/JAES_SIMULASI_BIMA2` is structurally complete for the historical replay prototype.

## Migrated and retained

- Historical AIS `ais_raw_2024.csv` is stored under `data/input/ais/raw/`.
- Vessel capacity is stored under `data/reference/vessel_master/`.
- Port/berth coordinates are stored centrally in `config/ports_berths.yaml`.
- Legacy ML1 Random Forest and XGBoost model artifacts are retained in `models/ML1_ETA_CORRECTION/06_model_saved/`.
- Legacy ML2 selected model is retained in `models/ML2_TURNAROUND_CORRECTION/06_model_saved/` with explicit simulated-data provenance.
- Legacy ML1 split, metrics, and prediction artifacts are retained with `legacy_` prefixes in the ML1 model validation/metrics/prediction folders.
- Legacy replay artifacts are retained under `outputs/04_replay_dashboard/`.
- The source project is preserved; migration did not delete the legacy source folder.

## Quarantined simulated ML2 artifacts

The following artifacts are isolated in `data/input/audit_quarantine/` and must not be interpreted as observed operational data:

- `SIMULATED_dummy_manifest_ML2_2024.xlsx`
- `SIMULATED_LEGACY_turnaround_training_dataset.csv`
- `SIMULATED_LEGACY_ml2_model_metrics.csv`
- `SIMULATED_LEGACY_vessel_capacity_derived.csv`
- `SIMULATED_LEGACY_vehicle_rate_5min.csv`

Notebook 02 and the ML2 scripts block simulated-data training by default. Simulated replay requires an explicit opt-in.

## Legacy source archive

Original configuration, READMEs, and dependency files are retained in `config/legacy_source/`. Active BIMA2 scripts do not depend on the legacy directory structure.

## ETD normalization

`DTA` is deprecated in BIMA2. Historical DTA columns remain only as compatibility aliases. The active published contract contains equivalent ETD fields:

- `etd_random_forest_random_forest`
- `etd_random_forest_xgboost`
- `etd_xgboost_random_forest`
- `etd_xgboost_xgboost`

The active `operation_state_5min.csv` also contains `bima2_snapshot_status` and `operational_claim_allowed`.

## Audit results

Static LOCAL_RUN path audit: **PASS**.

Historical migration-mode integration test: **PASS**.

- Integration replay states: 4,819
- Published operation-state records: 57,080
- Vessel-state records: 37,496
- Terminal-state records: 19,584
- Run ID: `2024_holdout20_replay_bima2_migrated`
- ETD contract: four ML1/ML2 combinations available
- Operational claim allowed: `false`

The published snapshot remains a historical prototype because the ML2 vehicle source is simulated legacy data and current CCTV observations have not yet replaced it.

## Remaining scientific step

For an operationally defensible BIMA2 result, replace the quarantined/simulated ML2 vehicle source with observed historical or CCTV-compatible data, rerun Notebook 02, chronologically validate ML2, then run Notebook 03 with model-rebuild mode.
