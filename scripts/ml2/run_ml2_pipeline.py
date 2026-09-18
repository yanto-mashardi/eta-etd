"""Run the BIMA Year-2 ML2 pipeline using the aligned historical-demand + CCTV feature schema."""
from pathlib import Path
import subprocess, sys

ROOT=Path(__file__).resolve().parents[2]
steps=[
    ROOT/'scripts/ml2/build_ml2_history_dataset.py',
    ROOT/'scripts/ml2/train_ml2_manifest.py',
]
for script in steps:
    print(f"\n=== {script.name} ===", flush=True)
    subprocess.run([sys.executable,str(script)],check=True,cwd=ROOT)
print("\nML2 METHOD-ALIGNED PIPELINE COMPLETE")
