# Active Configuration Policy — BIMA2 Year 2

**Single active configuration:** `config/project_config.yaml`

All active Python services and model pipelines must read this file. Legacy configuration files are archived under `config/archive/` and are read-only references only.

`config/project_config.json` is a legacy file that could not be moved by the Drive integration because of file-specific write permission. It is **not an active configuration** and no aligned V12 script reads it.

Active auxiliary data (not duplicate project configs):
- `config/registry/active_model_config.yaml` — model registry pointer/status only.
- `config/vessel_capacity_realtime_v4.csv` — vessel master/capacity + provenance.

Method version: `BIMA2_YEAR2_METHOD_ALIGNED_V12`.
