# JAES_SIMULASI_BIMA2

BIMA2 adalah implementasi LOCAL_RUN untuk sistem prediksi dan replay ETA–ETD Bengkalis–Pakning.

Empat layer project:

1. ML1 — koreksi residual ETA dari AIS menggunakan Random Forest/XGBoost.
2. ML2 — koreksi turnaround dari bukti kendaraan/manifest.
3. Integration — menyatukan ETA, turnaround, ETD, posisi kapal, dermaga, dan antrean pada timeline lima menit.
4. Dashboard — hanya membaca `outputs/published/operation_state_5min.csv`; dashboard tidak melakukan training model.

Struktur mengikuti `LOCAL_RUN_STANDARD_V2` dan menggunakan shared Python environment `C:\LOCAL_RUN_venv\.venv`.

## Quick start

Pertama kali: `01_CHECK_BIMA2_LOCAL.bat`.

Jika check PASS: `04_BUILD_AND_RUN_DASHBOARD_LOCAL.bat`.

Dashboard: `http://localhost:8501`.

## Status provenance

Current AIS: historical/observed. Current vehicle/ML2 legacy material: `SIMULATED_LEGACY`. Historical replay dapat direproduksi dan disimulasikan; klaim kondisi operasional aktual tetap dinonaktifkan sampai vehicle/CCTV-compatible observed data tersedia dan ML2 direvalidasi.

Baca `docs/START_HERE_BIMA2.md`, `docs/RUN_GUIDE.md`, `docs/MIGRATION_AUDIT.md`, dan `docs/MODEL_PROVENANCE.md`.
