$ErrorActionPreference = "Stop"

$VPS = "root@192.236.226.247"
$Here = Split-Path -Parent $MyInvocation.MyCommand.Path
$Payload = Join-Path $Here "payload"

$files = @(
    @{ Local=(Join-Path $Payload "PublicDashboard_FINAL_V11.tsx"); Remote="/tmp/bima2_v11/PublicDashboard.tsx" },
    @{ Local=(Join-Path $Payload "VesselMap_FINAL_V11.tsx"); Remote="/tmp/bima2_v11/VesselMap.tsx" },
    @{ Local=(Join-Path $Payload "Inspection_FINAL_V11.tsx"); Remote="/tmp/bima2_v11/inspection_page.tsx" },
    @{ Local=(Join-Path $Payload "globals_FINAL_V11.css"); Remote="/tmp/bima2_v11/globals.css" },
    @{ Local=(Join-Path $Payload "main_FINAL_V11.py"); Remote="/tmp/bima2_v11/main.py" },
    @{ Local=(Join-Path $Payload "build_current_operation_state_FINAL_V11.py"); Remote="/tmp/bima2_v11/build_current_operation_state.py" }
)

Write-Host "=== BIMA2 V11 ONE-SHOT DEPLOY ===" -ForegroundColor Cyan
foreach($f in $files){
    if(!(Test-Path $f.Local)){ throw "Payload tidak ditemukan: $($f.Local)" }
}

ssh $VPS "rm -rf /tmp/bima2_v11 && mkdir -p /tmp/bima2_v11"
foreach($f in $files){
    Write-Host "UPLOAD $([IO.Path]::GetFileName($f.Local))"
    scp $f.Local "$VPS`:$($f.Remote)"
    if($LASTEXITCODE -ne 0){ throw "SCP gagal: $($f.Local)" }
}

$remote = @'
set -euo pipefail
ROOT=/opt/JAES_SIMULASI_BIMA2
STAMP=$(date +%Y%m%d_%H%M%S)
BACKUP="$ROOT/backups/${STAMP}_DASHBOARD_V11"
mkdir -p "$BACKUP"
cd "$ROOT"

cp -a web/ferry-dashboard/components/PublicDashboard.tsx "$BACKUP/PublicDashboard.tsx"
cp -a web/ferry-dashboard/components/VesselMap.tsx "$BACKUP/VesselMap.tsx"
cp -a web/ferry-dashboard/app/inspection/page.tsx "$BACKUP/inspection_page.tsx"
cp -a web/ferry-dashboard/app/globals.css "$BACKUP/globals.css"
cp -a scripts/api/main.py "$BACKUP/main.py"
cp -a scripts/operation_state_v4/build_current_operation_state.py "$BACKUP/build_current_operation_state.py"

restore_sources(){
  cp -a "$BACKUP/PublicDashboard.tsx" web/ferry-dashboard/components/PublicDashboard.tsx
  cp -a "$BACKUP/VesselMap.tsx" web/ferry-dashboard/components/VesselMap.tsx
  cp -a "$BACKUP/inspection_page.tsx" web/ferry-dashboard/app/inspection/page.tsx
  cp -a "$BACKUP/globals.css" web/ferry-dashboard/app/globals.css
  cp -a "$BACKUP/main.py" scripts/api/main.py
  cp -a "$BACKUP/build_current_operation_state.py" scripts/operation_state_v4/build_current_operation_state.py
}

cp /tmp/bima2_v11/PublicDashboard.tsx web/ferry-dashboard/components/PublicDashboard.tsx
cp /tmp/bima2_v11/VesselMap.tsx web/ferry-dashboard/components/VesselMap.tsx
cp /tmp/bima2_v11/inspection_page.tsx web/ferry-dashboard/app/inspection/page.tsx
cp /tmp/bima2_v11/globals.css web/ferry-dashboard/app/globals.css
cp /tmp/bima2_v11/main.py scripts/api/main.py
cp /tmp/bima2_v11/build_current_operation_state.py scripts/operation_state_v4/build_current_operation_state.py

echo "=== PYTHON CHECK ==="
if ! .venv/bin/python3 -m py_compile scripts/api/main.py scripts/operation_state_v4/build_current_operation_state.py; then
  echo "PYTHON CHECK GAGAL - ROLLBACK"
  restore_sources
  exit 21
fi

echo "=== SOURCE CHECK ==="
grep -q "Kedatangan ke" web/ferry-dashboard/components/PublicDashboard.tsx
grep -q "Mobil antre" web/ferry-dashboard/components/PublicDashboard.tsx
grep -q "v11ShipLabel" web/ferry-dashboard/components/VesselMap.tsx
grep -q "Edit User & Hak Akses" web/ferry-dashboard/app/inspection/page.tsx
grep -q "processed_departures" scripts/operation_state_v4/build_current_operation_state.py
grep -q "/api/inspection/users/{username}/update" scripts/api/main.py

echo "=== NEXT BUILD ==="
cd web/ferry-dashboard
if ! npm run build; then
  echo "NEXT BUILD GAGAL - ROLLBACK SOURCE"
  cd "$ROOT"
  restore_sources
  cd web/ferry-dashboard
  npm run build || true
  exit 22
fi
cd "$ROOT"

echo "=== RESTART ==="
systemctl restart bima2-state bima2-api bima2-dashboard
sleep 5

echo "=== SERVICES ==="
systemctl is-active bima2-state
systemctl is-active bima2-api
systemctl is-active bima2-dashboard

echo "=== HTTP ==="
printf "bengkalis_http="; curl -s -o /dev/null -w '%{http_code}\n' http://127.0.0.1:3000/bengkalis
printf "pakning_http="; curl -s -o /dev/null -w '%{http_code}\n' http://127.0.0.1:3000/pakning
printf "inspection_http="; curl -s -o /dev/null -w '%{http_code}\n' http://127.0.0.1:3000/inspection
printf "api_health="; curl -s -o /dev/null -w '%{http_code}\n' http://127.0.0.1:8000/api/health

echo "=== V11 API ROUTES ==="
curl -s http://127.0.0.1:8000/openapi.json | grep -oE '"/api/inspection/(roles|users/\{username\}/update)"' | sort -u || true

echo "=== QUEUE STATE ==="
.venv/bin/python3 - <<'PY'
import json
from pathlib import Path
p=Path('outputs/realtime/current_operation_state.json')
try:
 d=json.loads(p.read_text())
 for port,key in [('BENGKALIS','vehicle_bengkalis'),('PAKNING','vehicle_pakning')]:
  q=d.get(key) or {}
  print(port, 'car=',q.get('car_queue_current'),'motor=',q.get('motor_queue_current'),'departures=',q.get('service_departure_count'),'last=',q.get('last_service_departure_at'))
except Exception as e:
 print('queue_state_error=',type(e).__name__,str(e))
PY

echo "BACKUP=$BACKUP"
echo "=== DEPLOY V11 SELESAI ==="
'@

$remote | ssh $VPS "bash -s"
if($LASTEXITCODE -ne 0){ throw "Deploy V11 gagal. Lihat output rollback/check di atas." }

Write-Host "=== V11 DEPLOY SUCCESS ===" -ForegroundColor Green
Write-Host "Buka dashboard dan tekan Ctrl+F5." -ForegroundColor Green
