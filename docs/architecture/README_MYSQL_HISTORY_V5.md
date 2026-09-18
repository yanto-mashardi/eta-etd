# MySQL History Architecture V5

Realtime files are ephemeral and only support dashboard inference/monitoring. Historical analysis data is written to MySQL by `history_recorder_mysql.py` at a configurable interval (default 60 seconds).

Tables:
- `ais_observation`
- `cctv_observation`
- `prediction_history`
- `actual_event`
- authentication/RBAC/audit/model-registry tables

`vehicle_state.json` remains the lightweight current CCTV state and is overwritten continuously. `vehicle_observation_5min.csv` is not part of the active architecture.

CSV is export-only, generated on demand from MySQL for research/reporting.
