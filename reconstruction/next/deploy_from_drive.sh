#!/usr/bin/env bash
# Reuse downloaded Local Run artifacts. No training, no legacy service changes.
set -euo pipefail
ROOT=/opt/BIMA2_NEXT
PY="$ROOT/model_venv/bin/python"
cd "$ROOT/app"
mkdir -p "$ROOT/incoming"
# Inspect only trusted joblib files after matching Local Run SHA256.
SK=$("$PY" - "$ROOT/local_run/models" <<'PYCODE'
import json,hashlib,zlib,re,sys
from pathlib import Path
p=Path(sys.argv[1]);s=json.loads((p/'ML_V2_VALIDATION_SUMMARY.json').read_text(encoding='utf-8-sig'))
assert s['status']=='PASS_ML_V2_VALIDATION_RESEARCH'
versions=set()
for role,alg in s['selected_ML_algorithms'].items():
 f=p/f'ML_V2_{role}_{alg}.joblib';raw=f.read_bytes()
 assert hashlib.sha256(raw).hexdigest()==s['candidate_models_saved'][role][alg],f'Hash mismatch {f}'
 try:raw=zlib.decompress(raw)
 except zlib.error:pass
 # Protocol 4/5 SHORT_BINUNICODE field followed by MEMOIZE and version string.
 matches=re.findall(rb'(?:sklearn_version|_sklearn_version)\x94\x8c([\x01-\x7f])([0-9][0-9.a-zA-Z+-]*)',raw)
 found={v.decode() for n,v in matches if len(v)==n[0] and re.fullmatch(rb'[0-9]+\.[0-9]+\.[0-9]+(?:[a-z0-9]+)?',v)}
 if len(found)!=1:raise SystemExit(f'Cannot determine unique sklearn version for {f}: {found}')
 versions.update(found)
if len(versions)!=1:raise SystemExit(f'Mixed sklearn versions: {versions}')
print(versions.pop())
PYCODE
)
echo "Training scikit-learn: $SK"
"$PY" -m pip install --only-binary=:all: "scikit-learn==$SK"
"$PY" -m pip check
DATA="$ROOT/local_run/data"
getfile(){ local f; f=$(find "$DATA" -type f -name "$1" -print -quit); test -s "$f" || { echo "Missing $1" >&2; return 1; }; printf '%s' "$f"; }
ETA=$(getfile AIS_2025_ML1_ETA_DATASET.csv)
EARLY=$(getfile AIS_2025_ML2_VTT_EARLY_DATASET.csv)
CONV=$(getfile AIS_2025_ML2_VTT_CONVENTIONAL_DATASET.csv)
HISTORY=$(getfile AIS_2025_VOYAGE_CYCLES_QC_PASS.csv)
RID="release_$(date -u +%Y%m%d_%H%M%S)"
"$PY" export_release.py --results "$ROOT/local_run/models" --history "$HISTORY" --eta-data "$ETA" --early-data "$EARLY" --conventional-data "$CONV" --output "$ROOT/incoming" --release "$RID"
bash activate_release.sh "$RID"
curl -fsS http://127.0.0.1:8766/api/status | python3 -c 'import json,sys;d=json.load(sys.stdin);print(d["models"]);print("History:",d["event_engine"]["history_seed_count"])'
