$ErrorActionPreference = 'Stop'
$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot '..\..\..')).Path
$Python = 'C:\LOCAL_RUN_venv\.venv\Scripts\python.exe'
if (-not (Test-Path $Python)) { $Python = 'python' }

if (-not $env:AIS_API_URL) {
    Write-Host 'AIS_API_URL belum diset pada environment PowerShell.' -ForegroundColor Yellow
    Write-Host 'Contoh untuk sesi ini: $env:AIS_API_URL="https://alamat-api-anda"'
    Write-Host 'Jika API memakai token: $env:AIS_API_KEY="..."'
    exit 1
}

Write-Host "Project : $ProjectRoot"
Write-Host "AIS API  : configured via AIS_API_URL"
Write-Host 'Filter   : 5 MMSI Ro-Ro + koridor Bengkalis-Pakning; destination AIS diabaikan sebagai filter'
& $Python (Join-Path $PSScriptRoot 'poll_ais_api_realtime.py')
