"""Run the BIMA2 ETA/ETD integration in either migration or model-rebuild mode."""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path: sys.path.insert(0, str(ROOT))
from scripts.v3_paths import output_root, processed_root, model_artifact_root, logs_root
PROV = processed_root(ROOT) / "ml2" / "source_provenance.json"


def run(script: str, extra: list[str] | None = None) -> None:
    p = ROOT / "scripts" / "integration" / script
    print(f"\n=== {script} ===")
    subprocess.run([sys.executable, str(p), *(extra or [])], check=True, cwd=ROOT)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--rebuild-from-models", action="store_true")
    ap.add_argument("--allow-simulated", action="store_true")
    args = ap.parse_args()

    operational_ml2 = False
    source_status = "NO_PROCESSED_ML2"
    if PROV.exists():
        prov = json.loads(PROV.read_text(encoding="utf-8"))
        source_status = str(prov.get("source_status", "UNKNOWN"))
        operational_ml2 = bool(prov.get("operational_claim_allowed", False))

    if args.rebuild_from_models:
        if not operational_ml2 and not args.allow_simulated:
            raise RuntimeError(
                "ML2 belum mempunyai sumber operasional tervalidasi. "
                "Gunakan --allow-simulated hanya untuk reproduksi prototype historis."
            )
        run("build_multimodel_tick_outputs.py", ["--allow-simulated"] if args.allow_simulated else [])
        run("build_visual_tracks_5min.py")
        run("build_daily_operation_schedule.py")
    else:
        print(f"Mode migrasi snapshot dipilih; ML2 source status={source_status}.")
        run("normalize_legacy_snapshot.py")

    run("build_operation_state_5min.py")
    run("validate_contract.py")


if __name__ == "__main__":
    main()
