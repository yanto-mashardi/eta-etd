$ErrorActionPreference = 'Stop'

$Root = (Resolve-Path $PSScriptRoot).Path
$Python = 'C:\LOCAL_RUN_venv\.venv\Scripts\python.exe'
$LocalConfig = 'C:\LOCAL_RUN_venv\bima2_local_config.ps1'

if (-not (Test-Path $Python)) { throw "Python venv tidak ditemukan: $Python" }
if (-not (Test-Path $LocalConfig)) { throw "Konfigurasi lokal tidak ditemukan: $LocalConfig" }

. $LocalConfig

if (-not $env:AIS_API_URL) { throw 'AIS_API_URL belum ada di bima2_local_config.ps1' }
if (-not $env:BIMA2_DB_PASSWORD) { throw 'BIMA2_DB_PASSWORD belum ada di bima2_local_config.ps1' }

if (-not $env:BIMA2_DB_HOST) { $env:BIMA2_DB_HOST = '127.0.0.1' }
if (-not $env:BIMA2_DB_PORT) { $env:BIMA2_DB_PORT = '3306' }
if (-not $env:BIMA2_DB_NAME) { $env:BIMA2_DB_NAME = 'jaes_bima2' }
$env:BIMA2_DB_USER = 'root'

if (-not $env:BIMA2_CCTV_ENABLED) { $env:BIMA2_CCTV_ENABLED = '1' }

$AisScript = Join-Path $Root 'scripts\data_source\ais\poll_ais_api_realtime.py'
$StateScript = Join-Path $Root 'scripts\operation_state_v4\build_current_operation_state.py'
$ApiLauncher = Join-Path $Root 'scripts\api\START_API_V1.ps1'
$NextLauncher = Join-Path $Root 'START_NEXTJS_V1.ps1'
$HistoryLauncher = Join-Path $Root 'scripts\database\START_HISTORY_RECORDER_MYSQL_V5.ps1'

$CctvDir = Join-Path $Root 'scripts\data_source\cctv'
$CctvRtspLauncher = Join-Path $CctvDir 'START_CCTV_RTSP_V4.ps1'
$YoloLauncher = Join-Path $CctvDir 'START_YOLO_REALTIME_V4.ps1'

foreach ($required in @($AisScript,$StateScript,$ApiLauncher,$NextLauncher,$HistoryLauncher)) {
    if (-not (Test-Path $required)) { throw "File wajib tidak ditemukan: $required" }
}

function Start-BimaWindow {
    param([string]$Title,[string]$Command)
    $wrapped = "`$Host.UI.RawUI.WindowTitle='$Title'; " + $Command
    Start-Process powershell -ArgumentList '-NoExit','-ExecutionPolicy','Bypass','-Command',$wrapped
}

Write-Host ''
Write-Host '====================================================' -ForegroundColor Cyan
Write-Host ' BIMA2 REALTIME - AIS + CCTV + API + NEXT.JS' -ForegroundColor Cyan
Write-Host '====================================================' -ForegroundColor Cyan
Write-Host "Local config : $LocalConfig"
Write-Host "AIS API      : $($env:AIS_API_URL)"
Write-Host "Database     : root@$($env:BIMA2_DB_HOST):$($env:BIMA2_DB_PORT)/$($env:BIMA2_DB_NAME)"
Write-Host "CCTV enabled : $($env:BIMA2_CCTV_ENABLED)"
Write-Host ''

$aisCmd = @"
. '$LocalConfig'
Set-Location '$Root'
& '$Python' '$AisScript'
"@
Start-BimaWindow 'BIMA2 - AIS REALTIME' $aisCmd
Start-Sleep 1

if ($env:BIMA2_CCTV_ENABLED -ne '0') {
    if ((Test-Path $CctvRtspLauncher) -and (Test-Path $YoloLauncher)) {
        foreach($port in @('BENGKALIS','PAKNING')){
            $cctvCmd = @"
. '$LocalConfig'
Set-Location '$CctvDir'
& '$CctvRtspLauncher' -Port '$port'
"@
            Start-BimaWindow "BIMA2 - CCTV RAW $port" $cctvCmd
        }
        Start-Sleep 5

        foreach($port in @('BENGKALIS','PAKNING')){
            $yoloCmd = @"
. '$LocalConfig'
Set-Location '$CctvDir'
& '$YoloLauncher' -Port '$port'
"@
            Start-BimaWindow "BIMA2 - YOLO $port" $yoloCmd
        }
        Start-Sleep 3
    } else {
        Write-Warning 'Launcher CCTV/YOLO tidak lengkap. Sistem tetap lanjut tanpa CCTV.'
    }
}

$stateCmd = @"
. '$LocalConfig'
Set-Location '$Root'
& '$Python' '$StateScript' --loop --seconds 5
"@
Start-BimaWindow 'BIMA2 - OPERATION STATE' $stateCmd
Start-Sleep 1

$historyCmd = @"
. '$LocalConfig'
Set-Location '$Root'
& '$HistoryLauncher'
"@
Start-BimaWindow 'BIMA2 - MYSQL HISTORY + DAILY RECAP' $historyCmd
Start-Sleep 1

$apiCmd = @"
. '$LocalConfig'
Set-Location '$Root'
& '$ApiLauncher'
"@
Start-BimaWindow 'BIMA2 - FASTAPI' $apiCmd

Write-Host 'Menunggu FastAPI port 8000...' -ForegroundColor Yellow
$apiReady = $false
for ($i=0; $i -lt 40; $i++) {
    try {
        $r = Invoke-RestMethod -Uri 'http://127.0.0.1:8000/api/health' -TimeoutSec 1
        if ($r.status -eq 'ok') { $apiReady = $true; break }
    } catch {}
    Start-Sleep 1
}
if (-not $apiReady) { throw 'FastAPI tidak hidup di port 8000. Periksa window BIMA2 - FASTAPI.' }

$nextCmd = @"
. '$LocalConfig'
Set-Location '$Root'
& '$NextLauncher'
"@
Start-BimaWindow 'BIMA2 - NEXT.JS' $nextCmd

Write-Host ''
Write-Host 'BIMA2 STACK STARTED' -ForegroundColor Green
Write-Host 'Bengkalis  : http://127.0.0.1:3000/bengkalis'
Write-Host 'Pakning    : http://127.0.0.1:3000/pakning'
Write-Host 'Inspection : http://127.0.0.1:3000/inspection'
Write-Host 'API Health : http://127.0.0.1:8000/api/health'
Write-Host ''
Write-Host 'Jangan tutup window AIS / CCTV Bengkalis-Pakning / YOLO Bengkalis-Pakning / STATE / MYSQL HISTORY / API / NEXT selama sistem berjalan.'
