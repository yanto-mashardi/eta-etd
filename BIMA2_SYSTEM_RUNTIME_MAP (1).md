# BIMA2 Runtime & Deployment Map

## Tujuan
Dokumen ini menjadi referensi tetap untuk konfigurasi runtime, deployment, database, dan rollback proyek `JAES_SIMULASI_BIMA2`. Jangan mengasumsikan interpreter, host database, atau nama service tanpa merujuk dokumen ini dan kondisi runtime aktual.

## Lokasi Utama
- Laptop utama: `H:\My Drive\LOCAL_RUN\JAES_SIMULASI_BIMA2`
- PC Lab: `G:\My Drive\LOCAL_RUN\JAES_SIMULASI_BIMA2`
- VPS: `/opt/JAES_SIMULASI_BIMA2`
- Domain: `https://eta-etd.gudang-apps.my.id`
- Dashboard Bengkalis: `https://eta-etd.gudang-apps.my.id/bengkalis`

## Pembagian Peran
### PC Lab
Dipakai untuk runtime CCTV dan YOLO:
- MediaMTX / RTSP
- FFmpeg
- YOLO / ByteTrack
- sinkron `vehicle_state.json`
- reverse tunnel video ke VPS

PC Lab bukan mesin utama untuk deployment source aplikasi.

### Laptop Utama
Dipakai untuk:
- edit/source di Google Drive
- local test
- backup/deployment source ke VPS melalui SCP
- maintenance aplikasi

### VPS
Menjalankan:
- AIS realtime
- operation state
- FastAPI
- Next.js dashboard
- CCTV monitor/tunnel
- database history recorder

## Python Runtime VPS
Runtime aplikasi menggunakan virtual environment proyek:

`/opt/JAES_SIMULASI_BIMA2/.venv/bin/python3`

Contoh service API:
`/opt/JAES_SIMULASI_BIMA2/.venv/bin/uvicorn scripts.api.main:app --host 127.0.0.1 --port 8000`

Jangan menggunakan `/usr/bin/python3` untuk modul proyek sebelum memastikan dependency yang diperlukan memang terpasang di sana.

## Service Systemd yang Diketahui
- `bima2-ais.service`
- `bima2-api.service`
- `bima2-cctv-watch.service`
- `bima2-dashboard.service`
- `bima2-state.service`
- `bima2-history.service` (akan digunakan untuk history recorder jika sudah dibuat)

## Konfigurasi Environment
File environment VPS:

`/etc/bima2.env`

Jangan menaruh password/secrets di dokumen ini.

Untuk memuat environment secara manual:
```bash
set -a
source /etc/bima2.env
set +a
```

Variabel database yang digunakan oleh kode harus dibaca dari `/etc/bima2.env`. Jangan mengasumsikan `127.0.0.1:3306` sebelum memeriksa nilai aktual `BIMA2_DB_HOST` dan `BIMA2_DB_PORT`.

## Prosedur Deployment Wajib
1. Uji lokal pada laptop utama.
2. Jalankan `py_compile`.
3. Uji import modul.
4. Uji fungsi kritis secara lokal.
5. Backup file aktif di VPS.
6. SCP source baru ke VPS.
7. Jalankan `py_compile` menggunakan runtime VPS.
8. Verifikasi koneksi database.
9. Verifikasi/migrasikan schema.
10. Baru restart service terkait.
11. Verifikasi endpoint, state, database, dan log.
12. Simpan backup sampai sistem terbukti stabil.

## Backup Deployment 2026-09-17
Backup VPS:

`/opt/JAES_SIMULASI_BIMA2/backups/20260917_queue_service/`

Backup ini jangan dihapus sebelum:
- database history berjalan,
- queue service berjalan,
- API dan dashboard sehat,
- verifikasi satu siklus keberangkatan berhasil,
- rekap harian tersimpan.

## Queue Service
Raw YOLO state tidak boleh ditimpa oleh proses queue service.

Raw CCTV:
`data/01_DATA_SOURCE/CCTV/output/vehicle_state.json`

Queue/service ledger:
`outputs/realtime/queue_service_state.json`

Event loading/departure:
`outputs/realtime/queue_service_events.jsonl`

Aturan:
- antrean bertambah dari kendaraan ENTRY,
- antrean tidak berkurang hanya karena kapal tiba,
- pengurangan terjadi satu kali ketika kapal benar-benar berangkat dari dermaga setelah loading,
- kapasitas kapal dibaca sebagai PCE,
- motor menggunakan faktor PCE 0.25,
- event keberangkatan harus idempotent agar tidak dihitung dua kali.

## Database History
Target tabel:
- `queue_service_event`
- `daily_port_summary`

`daily_port_summary` harus di-update sepanjang hari agar data hari berjalan sudah tersimpan sebelum tanggal berganti.

## Aturan Keselamatan Operasional
- Jangan restart `bima2-ais` atau `bima2-cctv-watch` bila tidak ada perubahan pada keduanya.
- Jangan install package ke Python sistem bila aplikasi berjalan dari `.venv`.
- Jangan menghapus backup sebelum verifikasi end-to-end selesai.
- Jangan mengasumsikan database lokal; cek `/etc/bima2.env`.
- Setiap perubahan struktur runtime harus memperbarui dokumen ini.

## INSPECTION AUTHENTICATION & PASSWORD RESET

### Current architecture
- Inspection login endpoint: `POST /api/auth/login`.
- User accounts are stored in MySQL/MariaDB database `jaes_bima2`, table `users`, joined to `roles`.
- Passwords are stored only as bcrypt hashes in `users.password_hash`.
- API database connection uses `BIMA2_DB_HOST`, `BIMA2_DB_PORT`, `BIMA2_DB_NAME`, `BIMA2_DB_PASSWORD`, and optional `BIMA2_DB_USER` (default `root`).
- Do not store actual Inspection passwords in this document.

### Initial Master Admin
- Username is supplied by `BIMA2_ADMIN_USERNAME` (default `Admin`).
- Password MUST be supplied through `BIMA2_ADMIN_PASSWORD`; there is no hard-coded default password in the corrected seed script.
- Run `scripts/database/create_tables.sql`, then `seed_roles_permissions.sql`, then `seed_initial_admin.py`.
- `seed_initial_admin.py` creates the MasterAdmin when absent, or resets its bcrypt password and activates the account when it already exists.

### In-application password management
- Authenticated user can change their own password through `POST /api/auth/change-password` by supplying the current password and a new password.
- MasterAdmin can reset any user through `POST /api/inspection/users/{username}/reset-password`.
- Minimum new-password length: 8 characters.
- Inspection UI > User Management includes:
  1. Change My Password.
  2. Reset User Password (MasterAdmin).
  3. Add User.

### Recovery procedure when login is unavailable
1. Load `/etc/bima2.env` without printing passwords.
2. Set `BIMA2_ADMIN_USERNAME` and a temporary `BIMA2_ADMIN_PASSWORD` in the shell.
3. Run `/opt/JAES_SIMULASI_BIMA2/.venv/bin/python3 scripts/database/seed_initial_admin.py`.
4. Verify login through `/api/auth/login`.
5. Immediately change the temporary password through Inspection > User Management.

### Configuration drift warning (2026-09-17)
An older VPS copy of `seed_initial_admin.py` attempted to connect as `bima2_app`, while the active database configuration used `root`. Source was corrected to use `BIMA2_DB_USER` with default `root`. During deployment, always copy the current Drive source to VPS before running seed scripts.

## Dashboard Public/Inspection V10 (2026-09-17)

Public dashboard dipisahkan tegas dari Inspection.

### Public Bengkalis & Pakning
- Tetap memakai peta realtime sebagai elemen utama.
- Papan kapal menggunakan layout arrival/departure seperti airport board.
- Informasi publik per kapal dibatasi pada: nama kapal, rute, ETA, ETD, kecepatan, jarak, dan status operasional publik.
- Detail teknis ML1/ML2, correction, CCTV/YOLO, reliability, training, logs, dan parameter inspection tidak ditampilkan di halaman publik.
- Halaman Bengkalis dan Pakning memakai struktur UI sama tetapi konteks port dan dermaga berbeda.
- Daftar 5 kapal dirancang muat pada desktop tanpa card bertumpuk/scroll panjang halaman.
- Status `ON TIME` hanya boleh berasal dari field schedule/public status yang benar-benar tersedia. Jika tidak tersedia, UI memakai state faktual seperti `EN ROUTE`, `BERTHED`, `ARRIVING`, atau `DATA DELAY`.

### Inspection
Inspection mempertahankan dan mengonsolidasikan:
- Overview operasional.
- CCTV & YOLO Audit.
- ETA & ETD Reliability.
- Model Correction.
- Model Training.
- MFAR.
- Logs.
- User Management.

User Management:
- Hanya `MasterAdmin` yang dapat menambah user dan reset password user lain.
- Semua user yang sudah login dapat mengganti password miliknya sendiri.
- Password tidak pernah disimpan plaintext di dokumen/runtime map.

### Source V10 di Google Drive
- `web/ferry-dashboard/components/PublicDashboard_FINAL_V10.tsx`
- `web/ferry-dashboard/components/VesselMap_FINAL_V10.tsx`
- `web/ferry-dashboard/app/globals_FINAL_V10.css`
- `web/ferry-dashboard/app/inspection/Inspection_FINAL_V10.tsx`
- root project: `DEPLOY_BIMA2_DASHBOARD_V10.ps1`

### Deployment V10
Gunakan `DEPLOY_BIMA2_DASHBOARD_V10.ps1` dari laptop utama. Script melakukan satu kali eksekusi:
1. upload source V10 ke `/tmp` VPS,
2. membuat backup source aktif di `/opt/JAES_SIMULASI_BIMA2/backups/<timestamp>_DASHBOARD_V10`,
3. mengganti public dashboard, map, CSS, Inspection UI, API auth, dan seed admin,
4. menjalankan `py_compile` dan `npm run build`,
5. restart hanya `bima2-api` dan `bima2-dashboard`,
6. memeriksa HTTP `/bengkalis`, `/pakning`, `/inspection` dan status service.


## Method Alignment V12 — BIMA Tahun 2

Mulai 18 Sep 2026, `config/project_config.yaml` adalah satu-satunya project configuration aktif. Konfigurasi lama dipindahkan ke `config/archive/` dan bersifat read-only.

Metode final: ETA menargetkan **terminal berth arrival**; sailing filter 3–15 kn, KPI reliable speed 7–9 kn; ML1 mengoreksi ETA baseline; ML2 mengoreksi turnaround dengan fitur predicted historical demand, observed CCTV bila tersedia, kapasitas kapal, turnaround baseline, demand/capacity ratio, dan low-demand flag. Poin simulated-training policy belum diubah sesuai keputusan proyek.

Realtime serving menggunakan `outputs/realtime/current_operation_state.json`; histori penelitian immutable menggunakan `outputs/history/operation_state_5min.csv` pada tick 5 menit. AIS lebih tua dari 300 s boleh tetap divisualisasikan, tetapi tidak boleh dipakai untuk inference. Queue service merupakan modul operational simulation dan bukan ML2.

Dokumen rujukan: `BIMA2_METHOD_ALIGNMENT_V12.md`.
