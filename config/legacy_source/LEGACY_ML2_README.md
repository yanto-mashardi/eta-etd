# ML2 Turnaround dan Kendaraan

Input utama terdiri dari manifest historis, kapasitas kapal, dan hitungan kendaraan CCTV lima menit. Pada run awal, manifest dummy menjadi sumber `SIMULATED`; model tidak boleh diberi status operasional sebelum CCTV aktual tersedia dan rekonsiliasi dilakukan.

Jalankan `python run_ml2_pipeline.py`. Hasil model, tabel evaluasi, dan artefak terpilih dibuat pada `output/` dan `modelling/models/`.
