# Run Guide — JAES_SIMULASI_BIMA2

## Status saat ini

BIMA2 siap dijalankan sebagai **historical replay prototype**. Published contract berada di `outputs/published/operation_state_5min.csv`. Vehicle/ML2 provenance masih `SIMULATED_LEGACY`; karena itu `operational_claim_allowed` tetap `false` dan dashboard wajib menampilkan warning.

## Shared environment

Python environment: `C:\LOCAL_RUN_venv\.venv`.

Jika `requirements_base.txt` berubah atau launcher melaporkan package belum tersedia, jalankan sekali dari root `LOCAL_RUN`:

`00_SETUP_LOCAL_ENV.ps1`

Script tidak membuat ulang environment jika `.venv` sudah ada; ia menyinkronkan dependency berdasarkan requirements terbaru.

## Launcher yang dipakai

1. `01_CHECK_BIMA2_LOCAL.bat` — preflight check package, replay source, dan dashboard contract.
2. `02_BUILD_HISTORICAL_REPLAY_LOCAL.bat` — rebuild migration snapshot, `operation_state_5min.csv`, lalu contract audit.
3. `03_RUN_DASHBOARD_LOCAL.bat` — membuka Streamlit dari published contract yang sudah ada.
4. `04_BUILD_AND_RUN_DASHBOARD_LOCAL.bat` — satu klik untuk rebuild historical replay lalu membuka dashboard.
5. `05_AUDIT_BIMA2_LOCAL.bat` — static project audit + published contract validation.
6. `00_RUN_JAES_SIMULASI_BIMA2_LOCAL.bat` — membuka JupyterLab untuk penelitian, debugging, dan run notebook.

## Urutan pertama kali pada laptop

Jalankan `01_CHECK_BIMA2_LOCAL.bat`. Bila dependency belum lengkap, jalankan `..\00_SETUP_LOCAL_ENV.ps1`, kemudian ulangi check. Bila `CHECK PASS`, jalankan `04_BUILD_AND_RUN_DASHBOARD_LOCAL.bat`.

Dashboard berjalan pada `http://localhost:8501`. Tutup dashboard dengan `Ctrl+C` pada jendela command/PowerShell yang menjalankan Streamlit.

## Pipeline yang dijalankan launcher

Historical replay default:

`outputs/04_replay_dashboard/simulation_input_5min_multimodel.csv`
→ normalisasi DTA legacy ke ETD compatibility
→ `outputs/03_eta_etd_integration/`
→ rebuild `outputs/published/operation_state_5min.csv`
→ contract validation
→ Streamlit dashboard.

Mode ini tidak melakukan retraining ML1/ML2.

## Notebook penelitian

- `01_ML1_ETA_CORRECTION.ipynb`: rebuild/train/validate ML1 dari AIS.
- `02_ML2_TURNAROUND_CORRECTION.ipynb`: rebuild/train/validate ML2. `ALLOW_SIMULATED=False` tetap default untuk kerja ilmiah/operasional.
- `03_ETA_ETD_INTEGRATION.ipynb`: integrasi ETA–ETD.
- `04_REPLAY_DASHBOARD.ipynb`: dokumentasi/launch dashboard dari notebook.

## Mode model-derived berikutnya

Setelah ML2 mempunyai data observasi tervalidasi:

`python scripts/integration/run_integration.py --rebuild-from-models`

Reproduksi legacy simulated hanya jika sengaja dilakukan:

`python scripts/integration/run_integration.py --rebuild-from-models --allow-simulated`

## Logging

Runtime launcher menulis:

- `logs/latest_runtime.log`
- `logs/latest_runtime_status.json`

Audit/integration juga menulis file `latest_*_audit.json` dan migration log. Jika run gagal, periksa log ini terlebih dahulu.
