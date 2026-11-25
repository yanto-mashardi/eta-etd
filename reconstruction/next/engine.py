"""Algorithm-independent residual inference; no training or live event fabrication."""
from pathlib import Path
import json, hashlib, math, re
from datetime import datetime,timedelta
import joblib
import pandas as pd
import numpy as np

ROLES=("eta","vtt_early","vtt_conventional")
CAT={"mmsi","origin_port","destination_port"}
def digest(p):
    with p.open("rb") as f: return hashlib.file_digest(f,"sha256").hexdigest()

def load_release(root):
    root=Path(root)
    rid=json.loads((root/"active.json").read_text())["release_id"]
    if not re.fullmatch(r"[A-Za-z0-9_-]+",rid): raise ValueError("Invalid release ID")
    folder=root/"releases"/rid
    manifest=json.loads((folder/"manifest.json").read_text())
    if manifest["release_id"]!=rid: raise ValueError("Release ID mismatch")
    from importlib.metadata import version
    deps=manifest["dependencies"]
    for name in ("joblib","numpy","pandas","scikit-learn"):
        if name not in deps: raise ValueError("Missing dependency "+name)
    for name,wanted in deps.items():
        if version(name)!=wanted: raise ValueError("Dependency mismatch: "+name)
    models={}
    for role in ROLES:
        entry=manifest["models"][role]
        p=folder/(role+".joblib")
        if digest(p)!=entry["sha256"]: raise ValueError("Hash mismatch: "+role)
        # Only load locally trusted, operator-approved artifacts; pickle executes code.
        b=joblib.load(p)
        if b["role"]!=role: raise ValueError("Role mismatch")
        if not (b.get("trained_model") is not None or b.get("estimator") is not None):
            raise ValueError("Missing trained estimator")
        if not b["feature_names"] or len(set(b["feature_names"]))!=len(b["feature_names"]): raise ValueError("Invalid schema")
        issue=b.get("issue_time", {"EARLY_D0":"D0","CONVENTIONAL_A":"A"}.get(b.get("issue_class")))
        if issue!=("A" if role=="vtt_conventional" else "D0"): raise ValueError("Issue mismatch")
        models[role]=b
    return rid,models

def predict(b,features):
    names=b["feature_names"]
    missing=set(names)-features.keys()
    if missing: raise ValueError("Missing features: "+",".join(sorted(missing)))
    x=pd.DataFrame([{k:features[k] for k in names}])
    cat=set(b.get("categorical_features",CAT))
    for k in names:
        if k in cat: x[k]=x[k].fillna("UNKNOWN").astype(str)
        else: x[k]=pd.to_numeric(x[k],errors="coerce").replace([np.inf,-np.inf],np.nan)
    prefix="sailing" if b["role"]=="eta" else "vtt"
    keys=["hist_"+g+"_"+prefix+"_median_min" for g in ("pair","vessel","port","global")]
    base=float(b["fallback_median_min"])
    for k in keys:
        if k not in features: raise ValueError("Missing baseline feature "+k)
        try: val=float(features[k])
        except (ValueError,TypeError): continue
        if math.isfinite(val): base=val;break
    base=max(0,base)
    est=b.get("trained_model")
    if est is None: est=b["estimator"]
    delta=float(est.predict(x)[0])
    if not math.isfinite(delta) or not math.isfinite(base): raise ValueError("Nonfinite prediction")
    return {"baseline_min":base,"residual_min":delta,"duration_min":max(0,base+delta),"algorithm":b.get("algorithm",b.get("estimator_name","unknown"))}

def estimate(models,issue_utc,features,phase):
    t=datetime.fromisoformat(issue_utc.replace("Z","+00:00"))
    if t.tzinfo is None: raise ValueError("Timezone required")
    if phase=="D0":
        eta=predict(models["eta"],features); vtt=predict(models["vtt_early"],features)
        arrival=t+timedelta(minutes=eta["duration_min"])
        return {"phase":phase,"eta":arrival.isoformat(),"etd":(arrival+timedelta(minutes=vtt["duration_min"])).isoformat(),"eta_components":eta,"vtt_components":vtt}
    if phase=="A":
        vtt=predict(models["vtt_conventional"],features)
        return {"phase":phase,"ata":t.isoformat(),"etd":(t+timedelta(minutes=vtt["duration_min"])).isoformat(),"vtt_components":vtt}
    raise ValueError("Unsupported issue phase")
