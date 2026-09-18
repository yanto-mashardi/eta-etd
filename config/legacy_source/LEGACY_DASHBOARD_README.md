# Dashboard Replay 20% Uji

Dashboard ini adalah prototipe replay terhadap 20% leg uji kronologis ML1. Ia bukan sumber pelatihan model dan tidak mengubah bobot model.

1. Jalankan `python integration/validate_contract.py`.
2. Jalankan `python integration/build_multimodel_tick_outputs.py`.
3. Jalankan `python integration/build_visual_tracks_5min.py`.
4. Jalankan `python integration/build_daily_operation_schedule.py`.
5. Jalankan `python integration/build_operation_state_5min.py`.
6. Jalankan `python -m streamlit run dashboard/app.py`.

`build_multimodel_tick_outputs.py` melakukan inferensi RF dan XGBoost pada setiap
tick, lalu menghasilkan `output/simulation_input_5min_multimodel.csv`. Berkas ini
memuat dua ETA terkoreksi dan empat kombinasi DTA (2 pilihan ML1 × 2 pilihan ML2).
Dashboard membaca berkas tersebut dan menyediakan pilihan metode ML1 serta ML2.

`operation_state_5min.csv` adalah satu-satunya input operasional dashboard. Ia
memuat state kapal, state terminal, ETA/DTA kedua model, kapasitas, dan antrean.
