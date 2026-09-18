# START HERE — JAES_SIMULASI_BIMA2

Project saat ini siap untuk **historical replay prototype**. Sumber kendaraan ML2 masih berstatus `SIMULATED_LEGACY`, sehingga dashboard wajib menampilkan status prototype dan `operational_claim_allowed = false`.

## Environment

Semua project LOCAL_RUN menggunakan:

`C:\LOCAL_RUN_venv\.venv`

Jika shared requirements baru saja berubah, jalankan satu kali dari root `LOCAL_RUN`:

`00_SETUP_LOCAL_ENV.ps1`

Environment tidak dibuat ulang bila sudah ada; dependency yang belum tersedia akan dipasang.

## Urutan pertama kali

1. Double-click `01_CHECK_BIMA2_LOCAL.bat`.
2. Jika `CHECK PASS`, double-click `02_BUILD_HISTORICAL_REPLAY_LOCAL.bat`.
3. Jika replay selesai, double-click `03_RUN_DASHBOARD_LOCAL.bat`.
4. Browser akan membuka Streamlit di `http://localhost:8501`.

Cara paling ringkas setelah check pertama berhasil:

`04_BUILD_AND_RUN_DASHBOARD_LOCAL.bat`

File tersebut rebuild historical replay, memvalidasi contract, lalu menjalankan dashboard.

## Fungsi launcher

- `00_RUN_JAES_SIMULASI_BIMA2_LOCAL.bat` — membuka JupyterLab pada project.
- `01_CHECK_BIMA2_LOCAL.bat` — cek package, source replay, dan dashboard contract.
- `02_BUILD_HISTORICAL_REPLAY_LOCAL.bat` — rebuild migration snapshot dan `operation_state_5min.csv`.
- `03_RUN_DASHBOARD_LOCAL.bat` — menjalankan dashboard dari published contract yang sudah ada.
- `04_BUILD_AND_RUN_DASHBOARD_LOCAL.bat` — satu klik rebuild + dashboard.
- `05_AUDIT_BIMA2_LOCAL.bat` — audit struktur dan published contract.

## Output utama

Dashboard hanya membaca:

`outputs/published/operation_state_5min.csv`

Integration menghasilkan/menjaga:

- `outputs/03_eta_etd_integration/simulation_input_5min_multimodel.csv`
- `outputs/03_eta_etd_integration/eta_state_5min.csv`
- `outputs/03_eta_etd_integration/vehicle_rate_5min.csv`
- `outputs/published/operation_state_5min.csv`

## Catatan ilmiah

Mode default adalah `migration_snapshot`. Mode ini dipakai untuk menjalankan ulang prototype historis tanpa mengklaim ML2 sebagai model operasional tervalidasi. Training/rebuild ML2 dengan sumber aktual akan menjadi tahap terpisah setelah data manifest/CCTV tervalidasi tersedia.
