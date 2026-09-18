# Model Provenance — JAES_SIMULASI_BIMA2

## ML1 ETA correction

Legacy artifacts retained:

- `ml1_random_forest.joblib`
- `ml1_xgboost.joblib`

The associated legacy chronological split, metrics, and test predictions are retained under the ML1 model validation, metrics, and prediction folders with `legacy_` prefixes. BIMA2 can rebuild ML1 directly from `data/input/ais/raw/ais_raw_2024.csv`.

## ML2 turnaround correction

Legacy artifact retained:

- `ml2_turnaround_selected.joblib`

Its historical training source was simulated vehicle-manifest data. It is therefore retained for prototype reproducibility and must not be interpreted as an operationally validated model.

BIMA2 ML2 training is blocked by default when the source is `SIMULATED`. Valid operational use requires observed historical or CCTV-compatible vehicle data followed by chronological validation.

## Published historical snapshot

The current published `operation_state_5min.csv` is a normalized BIMA2 migration of the legacy historical replay. It is explicitly marked:

- `bima2_snapshot_status = LEGACY_PROTOTYPE_SIMULATED_LEGACY`
- `operational_claim_allowed = false`

The contract exposes ETA, turnaround, ETD, vessel state, berth state, and terminal queue fields at a five-minute timeline while preserving legacy DTA columns solely as compatibility aliases.
