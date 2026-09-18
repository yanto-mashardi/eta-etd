# BIMA Tahun 2 — Method Alignment V12

Status: diterapkan pada source Drive; poin 6 (simulated-training policy) sengaja tidak diubah sesuai keputusan proyek.

1. ETA target = terminal berth arrival, radius 0.15 NM dan SOG <= 0.8 kn.
2. Sailing filter 3–15 kn; reliability KPI 7–9 kn.
3. ML1 tetap residual correction atas ETA baseline; RF/XGBoost.
4. ML2 = turnaround correction, bukan queue model.
5. ML2 features: vessel, terminal, time, capacity, turnaround base, predicted historical demand, observed CCTV, demand/capacity ratio, low-demand flag.
6. Simulated-data training policy: tidak diubah sementara.
7. CCTV realtime adalah observed demand; Pakning boleh unavailable dan fallback historical prediction.
8. ETD = ETA corrected + turnaround base + ML2 correction.
9. Vessel capacity menyimpan provenance fields; nilai existing tetap ditandai project master sampai sumber resmi diverifikasi.
10. Motorcycle PCE 0.25 dipindah ke config dan diberi sensitivity 0.20/0.25/0.30.
11. Queue deduction dipisahkan sebagai operational simulation, bukan ML2.
12. Realtime state JSON dan immutable operation_state_5min research history dipisahkan.
13. project_config.yaml adalah satu-satunya project configuration aktif; config lama diarsipkan read-only.
14. Output path disatukan: outputs/realtime untuk serving; outputs/history untuk research history.
15. AIS normalized history diaktifkan untuk audit penelitian; MySQL tetap historical sink.
16. AIS >300 s boleh tetap terlihat pada peta, tetapi tidak boleh masuk inference.
17. Validation dikunci chronological 80/20, split per service leg/turnaround event, service window 07:00–23:55, operational holdout bulan Maret.
