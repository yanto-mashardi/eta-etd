# Modul pengarsipan AIS raw harian ke Google Drive

Target: folder Drive ID `1S3QALsal7ztEwu13vhpRMz-H-VmtagUc`
(https://drive.google.com/drive/folders/1S3QALsal7ztEwu13vhpRMz-H-VmtagUc).

Modul ini terpisah dari receiver, MySQL, dashboard, dan inferensi ML1/ML2.
Sumber: `data/01_DATA_SOURCE/AIS/realtime/raw/ais_api_raw_YYYYMMDD.jsonl`
yang ditulis oleh `scripts/data_source/ais/poll_ais_api_realtime.py`.

## Langkah VPS Linux DediRock

1. Deploy GitHub terbaru di VPS. Pastikan konfigurasi aktif `config/project_config.yaml`
   memiliki `ais.api.store_raw_payload: true`. **Restart service polling AIS**
   agar perubahan konfigurasi dibaca; sebelum diaktifkan raw lama tidak bisa dipulihkan dari file realtime.
   Pastikan juga receiver yang berjalan benar-benar menggunakan script polling tersebut.
2. Pasang rclone sesuai sistem VPS (misalnya `sudo apt install rclone`).
3. Jalankan `rclone config`, buat remote bernama `aisdrive`, tipe `drive`.
   Atur `root_folder_id` ke `1S3QALsal7ztEwu13vhpRMz-H-VmtagUc`.
   Otorisasi akun Google pemilik folder. Jika VPS headless, gunakan opsi autentikasi
   rclone dari komputer dengan browser. Akun yang diotorisasi harus punya izin tulis.
   JANGAN commit file `rclone.conf`, token, maupun kredensial ke GitHub.
   Uji: `rclone lsf aisdrive:`.
4. Uji arsip lokal setelah beberapa raw masuk:
   `python3 scripts/archive/ais_daily_gdrive.py --date YYYY-MM-DD --local-only`
5. Uji unggah:
   `python3 scripts/archive/ais_daily_gdrive.py --date YYYY-MM-DD`.
   Verifikasi hasil di folder Drive target. Filename `AIS_RAW_YYYY-MM-DD.csv`.
6. Jadwalkan menggunakan `crontab -e` (pada user yang sama dengan konfigurasi rclone):
   `CRON_TZ=Asia/Jakarta`
   `10 0 * * * cd /opt/JAES_SIMULASI_BIMA2 && /opt/JAES_SIMULASI_BIMA2/.venv/bin/python scripts/archive/ais_daily_gdrive.py --cleanup-uploaded >> /var/log/ais_gdrive_archive.log 2>&1`
   **Perhatikan:** CRON_TZ tidak selalu mengubah zona waktu pemicu cron pada semua distro.
   Pastikan timezone VPS/cron sesuai WIB (`timedatectl`) atau sesuaikan jam cron
   terhadap timezone server. Script selalu mengelompokkan isi CSV berdasarkan WIB.
   Ganti path proyek dan log di atas sesuai VPS sebenarnya.

## Desain data dan keselamatan

- Satu baris CSV per item payload raw. Kolom `raw_json` mempertahankan objek pesan utuh
  termasuk field tidak dikenal dan nested; kolom terpilih memudahkan analisis.
- `received_at_wib` menjadi acuan pembagian hari; timestamp asli tetap disimpan.
- Semua MMSI yang datang tercatat; whitelist/koridor tidak dipakai pada arsip.
- Perintah dijalankan ulang secara idempoten terhadap nama tujuan: file Drive tanggal
  yang sama diganti (bukan membuat banyak versi). `--days-back 2` membantu menangani
  data yang terlambat masuk ke raw JSONL.
- Proses ekspor tidak menghapus JSONL maupun CSV lokal. **Jangan aktifkan penghapusan
  lokal otomatis** sampai retensi dan verifikasi arsip diuji dengan data operasional.
- Semua penulisan CSV menggunakan berkas sementara dan penggantian atomik; ukuran
  file Drive diperiksa sesudah upload. Proses yang gagal mengembalikan exit code 1.
- CSV mungkin berukuran besar; kemampuan storage VPS/Drive harus dimonitor.
- Jika API tidak mengirim setiap paket AIS, arsip ini berarti seluruh pesan yang
  diterima *melalui API tersebut*, bukan semua transmisi AIS dari pemancar kapal.
- Pengeksporan satu tanggal memerlukan raw JSONL sumber. Baris JSONL rusak
  menyebabkan tanggal itu gagal diekspor (tidak diam-diam menghapus record).
- Jika VPS merekam raw melalui pipeline berbeda, sesuaikan input sebelum aktivasi.

## Perintah

```bash
python3 scripts/archive/ais_daily_gdrive.py --date 2026-11-18 --local-only
python3 scripts/archive/ais_daily_gdrive.py --date 2026-11-18
python3 scripts/archive/ais_daily_gdrive.py --days-back 3
```

## Implementasi khusus VPS DediRock yang sudah aktif

Pada VPS ini proyek berada di `/opt/JAES_SIMULASI_BIMA2` tanpa folder `.git`.
Unduh modul saja (jangan `git pull` atau menimpa konfigurasi VPS):

```bash
cd /opt/JAES_SIMULASI_BIMA2
mkdir -p scripts/archive
curl -fL --retry 3 https://raw.githubusercontent.com/yanto-mashardi/eta-etd/main/scripts/archive/ais_daily_gdrive.py -o scripts/archive/ais_daily_gdrive.py
.venv/bin/python -m py_compile scripts/archive/ais_daily_gdrive.py
```

Setelah `rclone config` selesai, remote `aisdrive` diarahkan dengan root folder ID di atas.
Jalankan `rclone lsf aisdrive:`; lalu untuk tanggal WIB **kemarin yang lengkap**:

```bash
.venv/bin/python scripts/archive/ais_daily_gdrive.py --local-only
.venv/bin/python scripts/archive/ais_daily_gdrive.py --cleanup-uploaded
```

**PENTING:** sebelum menerima cleanup otomatis, periksa CSV hasil unggah di Drive.
Perintah terakhir tidak menghapus raw apabila unggahan gagal, tanggal yang sama
belum lengkap, ada error parsing, atau file masih ditulis receiver. Ia tidak
menghapus apa pun di tabel MySQL. Jalankan cron hanya setelah pengujian sukses.

Untuk VPS dengan timezone UTC gunakan cron `10 17 * * *` (17:10 UTC = 00:10 WIB).
Pada VPS yang timezone sistemnya Asia/Jakarta gunakan `10 0 * * *`.
Gunakan hanya salah satu. Jalankan crontab pada user yang menyimpan konfigurasi rclone.
