"""Run lengkap ML1 dari preprocessing sampai interpretasi."""
import subprocess, sys
from pathlib import Path
PROJECT_ROOT=Path(__file__).resolve().parents[2]
STEPS=[PROJECT_ROOT/"scripts/ml1/build_ml1_dataset.py", PROJECT_ROOT/"scripts/ml1/train_ml1.py", PROJECT_ROOT/"scripts/ml1/report_ml1.py"]
for step in STEPS:
    print(f"\n=== {step.name} ===")
    subprocess.run([sys.executable, str(step)], check=True, cwd=PROJECT_ROOT)
