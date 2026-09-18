# BIMA2 Dashboard Change Log

Dokumen ini menjadi catatan perubahan teknis dashboard. Setiap patch berikutnya harus menambah entri baru di file ini sebelum deployment.

## V13.1 — CCTV browser path + public readability

Tanggal: 2026-09-18

### Inspection
- Mempertahankan dua terminal pada menu CCTV: Bengkalis dan Pakning.
- Bengkalis menampilkan CCTV RAW dan YOLO + ByteTrack berdampingan.
- Pakning tetap tampil pada struktur Inspection, tetapi diberi status eksplisit bahwa CCTV belum terpasang/diaktifkan; tidak dibuat stream palsu.
- Browser player menggunakan path HLS MediaMTX melalui reverse proxy domain yang sama:
  - `/cctv-hls/cctv_bengkalis/`
  - `/cctv-hls/cctv_bengkalis_yolo/`
- Hasil validasi sebelum patch: kedua path pada VPS berhasil mencapai `HTTP 200` setelah redirect MediaMTX diikuti.
- Menambahkan informasi path stream pada Inspection untuk mempermudah audit jalur RAW/YOLO.

### Dashboard publik
- Layout desktop 1080p dipadatkan agar halaman utama tidak memerlukan scroll vertikal pada viewport desktop normal.
- Ukuran teks tabel tidak diperkecil secara ekstrem; header tabel minimal 10 px dan isi utama 11–13 px pada mode 1080p.
- Kolom Arrival/Departure diberi `minmax()` yang eksplisit agar teks tidak saling menimpa.
- Nama kapal dan keterangan panjang memakai ellipsis ketika ruang tidak cukup.
- Status dapat membungkus teks di dalam selnya sendiri dan tidak menimpa kolom sebelah.
- Peta dipertahankan, tetapi proporsi kolom diberikan lebih besar ke board agar tabel tetap terbaca.

### Tidak diubah
- ML1, ML2, model registry, AIS inference, queue engine, `project_config.yaml`, dan definisi `terminal_berth_arrival` tidak diubah oleh patch ini.

## V13 — draft sebelumnya
- Menambahkan konsep dua terminal untuk CCTV Inspection.
- Menambahkan placeholder Pakning.
- Menambahkan draft compact layout desktop.
- V13.1 menggantikan V13 sebagai patch yang harus dipakai.
