$ErrorActionPreference = 'SilentlyContinue'
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$ProjectRoot = Resolve-Path (Join-Path $ScriptDir '..\..\..')
$Legacy = Join-Path $ProjectRoot 'data\01_DATA_SOURCE\CCTV\output\vehicle_observation_5min.csv'
Write-Host "Legacy 5-minute vehicle file cleanup active: $Legacy"
while ($true) {
    if (Test-Path $Legacy) {
        Remove-Item -Force $Legacy -ErrorAction SilentlyContinue
        if (-not (Test-Path $Legacy)) { Write-Host "Removed legacy vehicle_observation_5min.csv" }
    }
    Start-Sleep -Seconds 30
}
