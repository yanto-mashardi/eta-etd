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
