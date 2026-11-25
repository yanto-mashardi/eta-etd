#!/usr/bin/env bash
set -euo pipefail
ROOT=/opt/BIMA2_NEXT
RID="${1:?release ID}"
[[ "$RID" =~ ^[A-Za-z0-9_-]+$ ]]
exec 9>"$ROOT/.release.lock"
flock -n 9
SRC="$ROOT/incoming/$RID"
DEST="$ROOT/models/releases/$RID"
test -d "$SRC"; test ! -e "$DEST"
systemctl is-active --quiet bima2-ais.service
systemctl is-active --quiet bima2-ais-gdrive.timer
systemctl is-active --quiet bima2-next.service
# Dedicated environment, never modify legacy Python.
mkdir -p "$ROOT/envs"
python3 -m venv "$ROOT/envs/$RID"
PY="$ROOT/envs/$RID/bin/python"
# Check manifest and requirements before installing. Trusted local artifacts only.
"$PY" - "$SRC" "$RID" <<'PYCODE'
import json,sys,hashlib,re,platform
from pathlib import Path
p=Path(sys.argv[1]);m=json.loads((p/'manifest.json').read_text())
assert m['release_id']==sys.argv[2]
assert m['python_version'].split('.')[:2]==platform.python_version().split('.')[:2]
for role in ('eta','vtt_early','vtt_conventional'):
 with (p/(role+'.joblib')).open('rb') as f:assert hashlib.file_digest(f,'sha256').hexdigest()==m['models'][role]['sha256']
for name,key in [('historical_cycles.csv','history_sha256'),('validation_fixture.json','fixture_sha256')]:
 with (p/name).open('rb') as f:assert hashlib.file_digest(f,'sha256').hexdigest()==m[key]
deps=m['dependencies']
assert all(re.fullmatch(r'[A-Za-z0-9_-]+',k) and re.fullmatch(r'[A-Za-z0-9.+!-]+',v) for k,v in deps.items())
assert set((p/'requirements.txt').read_text().splitlines())=={k+'=='+v for k,v in deps.items()}
PYCODE
"$PY" -m pip install --only-binary=:all: -r "$SRC/requirements.txt" fastapi uvicorn
"$PY" -m pip check
# Candidate validation root independent of active production pointer.
CHECK=$(mktemp -d "$ROOT/check.XXXXXX")
trap 'rm -rf "$CHECK"' EXIT
mkdir "$CHECK/releases"
ln -s "$SRC" "$CHECK/releases/$RID"
printf '{"release_id":"%s"}\n' "$RID" > "$CHECK/active.json"
cd "$ROOT/app"
OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 "$PY" validate_release.py "$CHECK" "$SRC/validation_fixture.json"
"$PY" -c 'from events import read_seed;import sys;print(len(read_seed(sys.argv[1])))' "$SRC/historical_cycles.csv"
# Candidate activation only; preserve all old state and previous configuration.
BACK="$ROOT/backup_release_$(date +%Y%m%d_%H%M%S)"
mkdir -p "$BACK"
DROP=/etc/systemd/system/bima2-next.service.d
mkdir -p "$DROP"
for f in "$ROOT/models/active.json" "$ROOT/data/historical_cycles.csv" "$DROP/20-model.conf"; do
 if [ -f "$f" ];then cp -p "$f" "$BACK/$(basename "$f")";fi
done
cp -a "$SRC" "$DEST"
chmod -R a+rX "$DEST" "$ROOT/envs/$RID"
rollback(){
 for f in "$ROOT/models/active.json" "$ROOT/data/historical_cycles.csv" "$DROP/20-model.conf";do
  if [ -f "$BACK/$(basename "$f")" ];then cp -p "$BACK/$(basename "$f")" "$f";else rm -f "$f";fi
 done
 systemctl daemon-reload;systemctl restart bima2-next.service
}
trap 'rollback; rm -rf "$CHECK"' ERR
install -m 0644 "$SRC/historical_cycles.csv" "$ROOT/data/historical_cycles.csv.new"
mv "$ROOT/data/historical_cycles.csv.new" "$ROOT/data/historical_cycles.csv"
printf '{"release_id":"%s"}\n' "$RID" > "$ROOT/models/active.json.new"
mv "$ROOT/models/active.json.new" "$ROOT/models/active.json"
printf '[Service]\nExecStart=\nExecStart=%s -m uvicorn app:app --host 127.0.0.1 --port 8766 --workers 1\n' "$PY" > "$DROP/20-model.conf"
systemctl daemon-reload
systemctl restart bima2-next.service
for i in $(seq 1 40);do
 if curl -fsS http://127.0.0.1:8766/api/status > "$CHECK/status.json";then break;fi
 sleep 1
done
"$PY" - "$CHECK/status.json" "$RID" <<'PYCODE'
import json,sys
x=json.load(open(sys.argv[1]));assert x['models']['release']==sys.argv[2];assert x['models']['status']=='MODEL_LOADED_UNVALIDATED';assert x['event_engine']['history_seed_count']>0
PYCODE
systemctl is-active --quiet bima2-ais.service
systemctl is-active --quiet bima2-ais-gdrive.timer
trap - ERR
echo "ACTIVATED $RID (staging; component parity passed, live validation pending)"
