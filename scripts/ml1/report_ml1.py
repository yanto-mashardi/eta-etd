"""Membuat ringkasan interpretasi komparasi ML1 yang dapat diaudit."""
from pathlib import Path
import pandas as pd

root = Path(__file__).resolve().parents[2]
import sys
if str(root) not in sys.path: sys.path.insert(0,str(root))
from scripts.v3_paths import output_root
OUT_ROOT = output_root(root)
metrics = pd.read_csv(OUT_ROOT / "01_ml1_eta" / "tables" / "metrics_comparison.csv")
base = metrics.iloc[0]
best = metrics.loc[metrics.index[1:].to_series().map(metrics.MAE_min.get).idxmin()] if len(metrics) > 1 else base
improvement = (base.MAE_min - best.MAE_min) / base.MAE_min * 100
text = f"""# Interpretasi ML1 — Koreksi ETA

## Definisi model

ETA dasar dihitung hanya setelah kapal memenuhi ambang kecepatan pelayaran:

`ETA_dasar (menit) = jarak tersisa (nautical mile) / SOG (knot) × 60`

Target pembelajaran adalah residual: `waktu tersisa aktual − ETA_dasar`. ETA terkoreksi diperoleh dari `ETA_dasar + residual prediksi`.

## Pembagian data

Pemisahan dilakukan secara kronologis pada tingkat service leg: 80% leg dengan waktu tiba paling awal menjadi pelatihan dan 20% leg terakhir menjadi pengujian. Ini mencegah satu pelayaran hadir pada kedua kelompok.

## Hasil pada data uji

| Model | MAE (menit) | RMSE (menit) | Bias (menit) | R² |
|---|---:|---:|---:|---:|
"""
for _, r in metrics.iterrows():
    text += f"| {r.model} | {r.MAE_min:.2f} | {r.RMSE_min:.2f} | {r.Bias_min:.2f} | {r.R2:.3f} |\n"
text += f"\nModel dengan MAE terkecil adalah **{best.model}**. Perubahan MAE terhadap ETA dasar: **{improvement:.1f}%**. Nilai ini merupakan bukti pada holdout kronologis, bukan jaminan akurasi untuk periode operasi yang pola layanannya berubah.\n"
out = OUT_ROOT / "01_ml1_eta" / "analysis_interpretation" / "reports"
out.mkdir(parents=True, exist_ok=True)
(out / "interpretasi_ml1.md").write_text(text, encoding="utf-8")
print(out / "interpretasi_ml1.md")
