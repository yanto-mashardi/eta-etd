# ML1 — Koreksi ETA berbasis AIS

ML1 memprediksi **residual ETA**, bukan ETA dari nol. ETA dasar pada setiap pesan AIS saat kapal berada dalam kondisi sailing dihitung dengan:

`ETA_dasar = jarak tersisa ke terminal tujuan / SOG × 60 menit`

Model mempelajari selisih antara ETA dasar dan waktu tiba aktual. Dua model dibandingkan: Random Forest dan XGBoost.

## Struktur

```text
ml1_eta_correction/
├── input/                     # Salin ais_raw.csv ke sini
│   ├── raw/                    # ais_raw_2024.csv
│   └── processed/              # Dibuat otomatis
├── preprocessing/              # Rekonstruksi sampel ETA dan residual
├── modelling/                  # Pelatihan dan model tersimpan
├── output/                     # tables/ dan figures/
├── analysis_interpretation/    # reports/ interpretasi hasil
├── config.yaml                 # Lokasi terminal dan parameter
└── run_ml1.py                  # Menjalankan semua tahap
```

## Sebelum dijalankan

1. Salin data AIS CSV menjadi `input/raw/ais_raw_2024.csv`.
2. `config.yaml` sudah memuat dua titik dermaga di Bengkalis dan dua titik di Pakning. Radius zona kedatangan awal adalah 0,15 NM dan perlu diuji terhadap sebaran titik berhenti AIS.
3. Isi nama kolom pada `config.yaml` jika pendeteksian otomatis gagal. Minimal diperlukan: waktu, MMSI, latitude, longitude, dan SOG. COG dianjurkan.
4. Dari folder proyek, instal dependensi dan jalankan:

```bash
pip install -r requirements.txt
python run_ml1.py
```

## Pembagian dan komparasi

Unit pemisahan ialah **service leg** menurut waktu tiba aktual. Leg disusun dari Januari ke akhir periode; 80% leg awal menjadi data latih dan 20% leg terakhir menjadi data uji. Dengan cara ini, pesan AIS dari pelayaran yang sama tidak bocor ke data uji.

Hasil utama tersedia di `output/tables/metrics_comparison.csv`, `output/tables/test_predictions.csv`, `output/figures/mae_model_comparison.png`, dan `analysis_interpretation/reports/interpretasi_ml1.md`.

Kolom `actual_remaining_min` hanya untuk evaluasi historis. Waktu tiba aktual didefinisikan sebagai *destination entry*—pesan pertama saat kapal memasuki zona 0,15 NM dari dermaga terdekat di terminal tujuan. Pada simulasi real-time nilai itu belum tersedia; sistem memakai `eta_baseline_min` dan model residual tersimpan untuk membentuk ETA terkoreksi.
