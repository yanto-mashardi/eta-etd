"""Static audit for LOCAL_RUN paths, required structure, and legacy leakage."""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LOGS = ROOT / "logs"
FORBIDDEN = [
    "drive.mount(", "/content/drive", "H:\\\\My Drive", "G:\\\\My Drive",
    "03_REALTIME_REPLAY_DASHBOARD", "02_ML2_TURNAROUND_VEHICLE", "01_ML1_ETA_AIS",
    "../00_SHARED/config",
]


def main() -> None:
    required_dirs = ["data", "notebooks", "models", "outputs", "config", "scripts", "docs", "logs"]
    missing_dirs = [d for d in required_dirs if not (ROOT / d).is_dir()]
    findings = []
    for base in [ROOT / "scripts", ROOT / "notebooks", ROOT / "config"]:
        for p in base.rglob("*"):
            if not p.is_file() or p.suffix.lower() not in {".py", ".ipynb", ".yaml", ".yml", ".json"}:
                continue
            if p.resolve() == Path(__file__).resolve():
                continue
            text = p.read_text(encoding="utf-8", errors="ignore")
            for token in FORBIDDEN:
                if token in text:
                    findings.append({"file": str(p.relative_to(ROOT)), "token": token})
    report = {
        "architecture": "LOCAL_RUN_STANDARD_V2",
        "missing_required_dirs": missing_dirs,
        "forbidden_legacy_path_findings": findings,
        "status": "PASS" if not missing_dirs and not findings else "FAIL",
    }
    LOGS.mkdir(parents=True, exist_ok=True)
    (LOGS / "latest_static_audit.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))
    if report["status"] != "PASS":
        raise RuntimeError("Static audit gagal; lihat logs/latest_static_audit.json")


if __name__ == "__main__":
    main()
