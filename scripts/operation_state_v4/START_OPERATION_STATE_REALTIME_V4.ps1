$ErrorActionPreference = 'Stop'
$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$Python = 'C:\LOCAL_RUN_venv\.venv\Scripts\python.exe'
if (-not (Test-Path $Python)) { $Python = 'python' }
Write-Host "Building realtime ETA-ETD operation state from AIS API + CCTV..."
& $Python (Join-Path $PSScriptRoot 'build_operation_state_realtime_v4.py')
