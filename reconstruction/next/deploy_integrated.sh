#!/usr/bin/env bash
# One complete release from a pinned GitHub commit. No per-file live patch.
set -Eeuo pipefail
umask 027
ROOT=/opt/BIMA2_NEXT
LEGACY=/opt/JAES_SIMULASI_BIMA2
POLL="$LEGACY/scripts/data_source/ais/poll_ais_api_realtime.py"
REF="$1"
MODE="$2"
[[ "$REF" =~ ^[0-9a-f]{40}$ ]] && [[ "$MODE" == --check || "$MODE" == --apply ]] || { echo "Usage: deploy_integrated.sh COMMIT --check|--apply"; exit 2; }
[[ $(id -u) == 0 ]]
test -d "$ROOT/app" && test -f "$POLL"
exec 9>"$ROOT/.integrated-deploy.lock"
flock -n 9
STAGE=$(mktemp -d "$ROOT/.integrated-stage.XXXXXX")
BACK="$ROOT/app.previous"
BASE="https://raw.githubusercontent.com/yanto-mashardi/eta-etd/$REF"
SWAPPED=0
RECEIVER_CHANGED=0
TIMERS_STOPPED=0
ROLLBACK_FAILED=0
cleanup(){ if [[ "$ROLLBACK_FAILED" == 0 ]];then rm -rf -- "$STAGE";else echo "Recovery files retained: $STAGE" >&2;fi; }
trap cleanup EXIT
for u in bima2-next.service bima2-ais.service bima2-ais-gdrive.timer bima2-prediction-archive.timer bima2-trajectory-cache.timer cctv-relay.service; do systemctl is-active --quiet "$u"; done
test "$(awk '/MemAvailable:/{print $2}' /proc/meminfo)" -ge 500000 || { echo "Insufficient memory for model preflight"; exit 1; }
test "$(df -Pk "$ROOT" | awk 'NR==2{print $4}')" -ge 1000000 || { echo "Insufficient disk for safe staging"; exit 1; }
python_of(){
 local pid
 pid=$(systemctl show "$1" -p MainPID --value)
 test "$pid" -gt 0
 python3 - "$pid" <<'PY'
import sys
from pathlib import Path
argv=Path('/proc/'+sys.argv[1]+'/cmdline').read_bytes().split(b'\0')
print(argv[0].decode())
PY
}
PY=$(python_of bima2-next.service)
AIS_PY=$(python_of bima2-ais.service)
test -x "$PY" && test -x "$AIS_PY"
test -s "$ROOT/app/map-assets/maplibre-gl.js" && test -s "$ROOT/app/map-assets/maplibre-gl.css"
export PYTHONDONTWRITEBYTECODE=1 OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1
export STAGE BASE ROOT LEGACY POLL
curl -fsSL --retry 3 "$BASE/reconstruction/next/RELEASE_MANIFEST.json" -o "$STAGE/manifest.json"
echo "===== DOWNLOAD AND GIT BLOB VERIFICATION ====="
python3 - <<'PY'
import hashlib,json,os,urllib.request,pathlib
s=pathlib.Path(os.environ['STAGE']);m=json.loads((s/'manifest.json').read_text())
def digest(b):return hashlib.sha1(b'blob '+str(len(b)).encode()+b'\0'+b).hexdigest()
seen=set()
for f in m['files']:
    rel=pathlib.PurePosixPath(f['path'])
    assert not rel.is_absolute() and '..' not in rel.parts and str(rel) not in seen
    seen.add(str(rel))
    with urllib.request.urlopen(os.environ['BASE']+'/'+str(rel),timeout=45) as stream:b=stream.read()
    assert digest(b)==f['git_blob'],str(rel)
    target=s/'source'/rel;target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(b)
    if f['runtime']:
        dst=s/'runtime'/rel.name;dst.parent.mkdir(parents=True,exist_ok=True);dst.write_bytes(b)
poll=next(f for f in m['files'] if f['path']=='scripts/data_source/ais/poll_ais_api_realtime.py')
actual=digest(pathlib.Path(os.environ['POLL']).read_bytes())
assert actual in (m['previous_poller_blob'],poll['git_blob']), 'VPS AIS receiver differs from the reviewed GitHub versions; stop without overwriting'
print('Verified blobs:',len(seen))
PY
APP="$STAGE/source/reconstruction/next"
CANDIDATE_POLL="$STAGE/source/scripts/data_source/ais/poll_ais_api_realtime.py"
export BIMA2_CANDIDATE_POLLER="$CANDIDATE_POLL"
export PYTHONPATH="$APP:$APP/tests"
echo "===== REGRESSION ====="
cd "$APP"
mapfile -t TESTS < <(find tests -maxdepth 1 -name 'test_*.py' ! -name 'test_receiver_provenance.py' -printf '%f\n' | sed 's/\.py$//' | sort)
"$PY" -m unittest -v "${TESTS[@]}"
"$AIS_PY" -m unittest -v test_receiver_provenance
for f in ./*.sh;do bash -n "$f";done
RID=$(python3 -c 'import json;print(json.load(open("/opt/BIMA2_NEXT/models/active.json"))["release_id"])')
[[ "$RID" =~ ^[A-Za-z0-9_-]+$ ]]
echo "===== EXISTING MODEL COMPONENT PARITY ====="
"$PY" validate_release.py "$ROOT/models" "$ROOT/models/releases/$RID/validation_fixture.json"
echo "===== RAW AIS STRUCTURAL REPLAY (read only) ====="
DAY=$(TZ=Asia/Jakarta date +%F)
"$AIS_PY" tests/replay_raw.py --root "$LEGACY" --poller "$CANDIDATE_POLL" --day "$DAY" > "$STAGE/replay.json"
python3 - "$STAGE/replay.json" <<'PY'
import sys,json
d=json.load(open(sys.argv[1]));print(json.dumps({k:v for k,v in d.items() if k!='cycles'},indent=2))
assert d['complete_cycles']>0 and not d['structural_issues']
PY
echo "===== CURRENT SERVICE DEPENDENCIES ====="
for u in bima2-next.service bima2-ais.service bima2-ais-gdrive.service bima2-prediction-archive.service bima2-trajectory-cache.service cctv-relay.service;do
 systemctl show "$u" -p Id -p ActiveState -p WorkingDirectory -p ExecStart --no-pager
done
echo "===== PRE-FLIGHT PASS ====="
if [[ "$MODE" == --check ]];then echo "No production changes";exit 0;fi
# Do not replace active files while an archive job is running.
test ! -e "$BACK" || { echo "Existing app.previous retained; review rollback directory before release";exit 1; }
for u in bima2-prediction-archive.service bima2-trajectory-cache.service;do
 state=$(systemctl show "$u" -p ActiveState --value)
 [[ "$state" == inactive || "$state" == failed ]] || { echo "Archive job busy: $u";exit 1; }
done
cp -a "$ROOT/app/map-assets" "$STAGE/runtime/map-assets"
cp "$STAGE/manifest.json" "$STAGE/runtime/RELEASE_MANIFEST.json"
printf '%s\n' "$REF" > "$STAGE/runtime/RELEASE_COMMIT"
chown -R root:bima2next "$STAGE/runtime"
find "$STAGE/runtime" -type d -exec chmod 755 {} +
find "$STAGE/runtime" -type f -exec chmod 644 {} +
cp -p "$POLL" "$STAGE/poller.original"
rollback(){
 local rc=$?
 trap - ERR
 set +e
 echo "===== ROLLBACK: preserve journal and SQLite =====" >&2
 if [[ "$SWAPPED" == 1 ]];then
   systemctl stop bima2-next.service
   # Preserve new audit columns before removing them from the compatibility copy.
   # Existing event/prediction values and SQLite ledger are not rolled back.
   PYTHONPATH="$ROOT/app" "$PY" - "$ROOT/data/events_state.json" "$BACK" "$ROOT/data/stockflow.sqlite" <<'PY'
import json,sys,shutil
from pathlib import Path
from events import atomic_json
from stockflow import Ledger
p=Path(sys.argv[1]);back=Path(sys.argv[2]);data=json.loads(p.read_text())
shutil.copy2(p,back/'events_state.candidate.json')
ledger=Ledger(Path(sys.argv[3]))
for key,item in list(data.get('departure_outbox',{}).items()):
    ledger.departure(item['port'],item['mmsi'],item['ts'])
    del data['departure_outbox'][key]
ledger.close()
for row in data.get('trip_monitor',{}).values():
    for k in ('event_evidence_json','features_early_json','features_arrival_json'):row.pop(k,None)
atomic_json(p,data)
PY
   if [[ $? != 0 ]];then ROLLBACK_FAILED=1;echo "Journal reconciliation failed; do not delete candidate files" >&2;exit 1;fi
   chown bima2next:bima2next "$ROOT/data/events_state.json"
   mv "$ROOT/app" "$STAGE/failed-app"
   mv "$BACK" "$ROOT/app"
 fi
 if [[ "$RECEIVER_CHANGED" == 1 ]];then
   cp -p "$STAGE/poller.original" "$POLL.rollback"
   mv "$POLL.rollback" "$POLL"
   systemctl restart bima2-ais.service || ROLLBACK_FAILED=1
 fi
 systemctl start bima2-next.service || ROLLBACK_FAILED=1
 if [[ "$TIMERS_STOPPED" == 1 ]];then systemctl start bima2-prediction-archive.timer bima2-trajectory-cache.timer || ROLLBACK_FAILED=1;fi
 exit "$rc"
}
trap rollback ERR
systemctl stop bima2-prediction-archive.timer bima2-trajectory-cache.timer
TIMERS_STOPPED=1
for u in bima2-prediction-archive.service bima2-trajectory-cache.service;do
 state=$(systemctl show "$u" -p ActiveState --value)
 [[ "$state" == inactive || "$state" == failed ]]
done
if ! cmp -s "$CANDIDATE_POLL" "$POLL";then
 RECEIVER_CHANGED=1
 cp -p "$POLL" "$POLL.new"
 cat "$CANDIDATE_POLL" > "$POLL.new"
 mv "$POLL.new" "$POLL"
 systemctl restart bima2-ais.service
fi
echo "===== VERIFY RECEIVER OUTPUT ====="
AIS_CSV="$LEGACY/data/01_DATA_SOURCE/AIS/realtime/ais_realtime.csv"
for i in $(seq 1 30);do
 if head -n1 "$AIS_CSV" | grep -q provider_observation_basis;then break;fi
 sleep 2
done
head -n1 "$AIS_CSV" | grep -q provider_observation_basis
systemctl is-active --quiet bima2-ais.service
systemctl stop bima2-next.service
mv "$ROOT/app" "$BACK"
if ! mv "$STAGE/runtime" "$ROOT/app";then mv "$BACK" "$ROOT/app";false;fi
SWAPPED=1
systemctl start bima2-next.service
echo "===== SMOKE TEST ====="
for i in $(seq 1 40);do
 if curl -fsS --max-time 10 http://127.0.0.1:8766/api/status > "$STAGE/status.json";then
  if python3 - "$STAGE/status.json" "$RID" <<'PY'
import json,sys
x=json.load(open(sys.argv[1]));e=x.get('event_engine') or {}
assert x['models']['release']==sys.argv[2] and x['models']['status']=='MODEL_LOADED_UNVALIDATED'
assert x['ais_status']=='AVAILABLE' and e.get('history_seed_count',0)>0 and not str(e.get('status','ERROR')).startswith('ERROR')
assert 'arrival_board' in e and 'departure_board' in e and 'prediction_evaluation' in e
PY
  then touch "$STAGE/smoke.ok";break;fi
 fi
 sleep 2
done
test -f "$STAGE/smoke.ok"
for route in bengkalis pakning inspection inspection/manager;do curl -fsS --max-time 15 "http://127.0.0.1:8766/$route" >/dev/null;done
python3 - <<'PY'
import hashlib,json,os,pathlib
root=pathlib.Path(os.environ['ROOT']);app=root/'app'
m=json.loads((app/'RELEASE_MANIFEST.json').read_text())
def digest(b):return hashlib.sha1(b'blob '+str(len(b)).encode()+b'\0'+b).hexdigest()
for f in m['files']:
    if f['runtime']:assert digest((app/pathlib.Path(f['path']).name).read_bytes())==f['git_blob'],f['path']
    if f['path']=='scripts/data_source/ais/poll_ais_api_realtime.py':assert digest(pathlib.Path(os.environ['POLL']).read_bytes())==f['git_blob']
print('GitHub/VPS runtime blobs: MATCH')
PY
cp -p "$STAGE/poller.original" "$BACK/receiver.original.py"
systemctl start bima2-prediction-archive.timer bima2-trajectory-cache.timer
TIMERS_STOPPED=0
for u in bima2-next.service bima2-ais.service bima2-ais-gdrive.timer bima2-prediction-archive.timer bima2-trajectory-cache.timer cctv-relay.service;do systemctl is-active --quiet "$u";done
trap - ERR
echo "===== INTEGRATED RELEASE ACTIVE ====="
echo "$REF"
echo "One previous app retained: $BACK"
echo "Field prediction accuracy and research QC still require actual observed complete cycles."
