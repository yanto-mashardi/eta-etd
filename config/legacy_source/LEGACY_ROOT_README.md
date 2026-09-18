# Ferry Prediction System

Struktur ini memisahkan pelatihan historis dari inferensi dashboard.

- `01_ML1_ETA_AIS`: model koreksi ETA dari AIS dan replay uji kronologis 20%.
- `02_ML2_TURNAROUND_VEHICLE`: model koreksi turnaround dari manifest, CCTV, dan kapasitas.
- `03_REALTIME_REPLAY_DASHBOARD`: integrasi keluaran terpublikasi ML1 dan ML2.

`run_id` ditetapkan pada `00_SHARED/config/project_config.yaml`. Input tahun baru diletakkan pada folder `input/raw/<period>/`, konfigurasi periode diubah, lalu pipeline ML1 dan ML2 dijalankan ulang. Dashboard hanya memuat artefak pada folder `published`.
