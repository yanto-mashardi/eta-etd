"""Compare trusted Local Run reference predictions with deployed bundle outputs."""
import argparse,json,math
from pathlib import Path
from engine import load_release,predict,ROLES
from importlib.metadata import version
def run(root,fixture):
    root=Path(root);rid=json.loads((root/"active.json").read_text())["release_id"]
    manifest=json.loads((root/"releases"/rid/"manifest.json").read_text())
    deps=manifest["dependencies"]
    for name in ("joblib","numpy","pandas","scikit-learn"):
        if name not in deps:raise ValueError("Missing dependency "+name)
    for name,wanted in deps.items():
        if version(name)!=wanted:raise ValueError("Dependency mismatch: "+name)
    release,models=load_release(root)
    cases=json.loads(Path(fixture).read_text())
    if cases["release_id"]!=release:raise ValueError("Fixture release mismatch")
    errors={r:[] for r in ROLES}
    for row in cases["cases"]:
        role=row["role"];expected=float(row["expected_duration_min"])
        actual=predict(models[role],row["features"])["duration_min"]
        if not math.isfinite(expected):raise ValueError("Nonfinite reference")
        errors[role].append(abs(expected-actual))
    report={r:{"n":len(v),"max_abs_diff_min":max(v,default=None)} for r,v in errors.items()}
    ok=all(len(v)>=10 and max(v)<=1e-6 for v in errors.values())
    return {"release":release,"status":"PASS" if ok else "FAIL","components":report}
if __name__=="__main__":
    p=argparse.ArgumentParser();p.add_argument("models");p.add_argument("fixture");a=p.parse_args()
    r=run(a.models,a.fixture);print(json.dumps(r,indent=2));raise SystemExit(0 if r["status"]=="PASS" else 1)
