$ErrorActionPreference = "Stop"

$R = "H:\My Drive\LOCAL_RUN\JAES_SIMULASI_BIMA2"
$V = "root@192.236.226.247"

Write-Host "=== BIMA2 Dashboard V10 one-shot deploy ===" -ForegroundColor Cyan

$files = @(
  @{Local="$R\web\ferry-dashboard\components\PublicDashboard_FINAL_V10.tsx"; Remote="/tmp/PublicDashboard_V10.tsx"},
  @{Local="$R\web\ferry-dashboard\components\VesselMap_FINAL_V10.tsx"; Remote="/tmp/VesselMap_V10.tsx"},
  @{Local="$R\web\ferry-dashboard\app\globals_FINAL_V10.css"; Remote="/tmp/globals_V10.css"},
  @{Local="$R\web\ferry-dashboard\app\inspection\Inspection_FINAL_V10.tsx"; Remote="/tmp/inspection_V10.tsx"},
  @{Local="${R}\scripts\api\main_FINAL_V10.py"; Remote="/tmp/main_V10.py"},
  @{Local="${R}\scripts\database\seed_initial_admin_FINAL_V10.py"; Remote="/tmp/seed_admin_V10.py"}
)

foreach($f in $files){
  if(!(Test-Path $f.Local)){ throw "File tidak ditemukan: $($f.Local)" }
  scp $f.Local "${V}:$($f.Remote)"
}

$remoteScript = @'
set -e
cd /opt/JAES_SIMULASI_BIMA2
STAMP=$(date +%Y%m%d_%H%M%S)
BACKUP="/opt/JAES_SIMULASI_BIMA2/backups/${STAMP}_DASHBOARD_V10"
mkdir -p "$BACKUP"

cp -a web/ferry-dashboard/components/PublicDashboard.tsx "$BACKUP/PublicDashboard.tsx"
cp -a web/ferry-dashboard/components/VesselMap.tsx "$BACKUP/VesselMap.tsx"
cp -a web/ferry-dashboard/app/globals.css "$BACKUP/globals.css"
cp -a web/ferry-dashboard/app/inspection/page.tsx "$BACKUP/inspection_page.tsx"
cp -a scripts/api/main.py "$BACKUP/main.py"
cp -a scripts/database/seed_initial_admin.py "$BACKUP/seed_initial_admin.py"

cp /tmp/PublicDashboard_V10.tsx web/ferry-dashboard/components/PublicDashboard.tsx
cp /tmp/VesselMap_V10.tsx web/ferry-dashboard/components/VesselMap.tsx
cp /tmp/globals_V10.css web/ferry-dashboard/app/globals.css
cp /tmp/inspection_V10.tsx web/ferry-dashboard/app/inspection/page.tsx
cp /tmp/main_V10.py scripts/api/main.py
cp /tmp/seed_admin_V10.py scripts/database/seed_initial_admin.py

/opt/JAES_SIMULASI_BIMA2/.venv/bin/python3 -m py_compile scripts/api/main.py scripts/database/seed_initial_admin.py

cd web/ferry-dashboard
npm run build

systemctl restart bima2-api
systemctl restart bima2-dashboard
sleep 5

echo "=== SERVICES ==="
systemctl is-active bima2-api bima2-dashboard

echo "=== AUTH ROUTE CHECK ==="
curl -s -o /dev/null -w "login_http=%{http_code}\n" -X POST http://127.0.0.1:8000/api/auth/login -H 'Content-Type: application/json' -d '{"username":"__probe__","password":"__probe__"}' || true

echo "=== PUBLIC PAGE CHECK ==="
curl -s -o /dev/null -w "bengkalis_http=%{http_code}\n" http://127.0.0.1:3000/bengkalis
curl -s -o /dev/null -w "pakning_http=%{http_code}\n" http://127.0.0.1:3000/pakning
curl -s -o /dev/null -w "inspection_http=%{http_code}\n" http://127.0.0.1:3000/inspection

echo "BACKUP=$BACKUP"
'@

$remoteScript | ssh $V "bash -s"

Write-Host "=== DEPLOY V10 SELESAI ===" -ForegroundColor Green
Write-Host "Refresh browser dengan Ctrl+F5." -ForegroundColor Yellow
