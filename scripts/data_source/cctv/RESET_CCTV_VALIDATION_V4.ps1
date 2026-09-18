$ErrorActionPreference = "Stop"

$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot '..\..\..')).Path
$OutputDir = Join-Path $ProjectRoot 'data\01_DATA_SOURCE\CCTV\output'
$Stamp = Get-Date -Format 'yyyyMMdd_HHmmss'
$ArchiveDir = Join-Path $OutputDir ("archive\validation_" + $Stamp)

New-Item -ItemType Directory -Force -Path $ArchiveDir | Out-Null

$files = @(
    'vehicle_state.json',
    'vehicle_events.csv',
    'vehicle_observation_5min.csv'
)

foreach ($name in $files) {
    $src = Join-Path $OutputDir $name
    if (Test-Path $src) {
        Move-Item -Path $src -Destination (Join-Path $ArchiveDir $name) -Force
        Write-Host "Archived: $name"
    }
}

Write-Host ""
Write-Host "State validasi CCTV di-reset ke nol." -ForegroundColor Green
Write-Host "Data lama tidak dihapus; dipindahkan ke:" -ForegroundColor Green
Write-Host $ArchiveDir
Write-Host ""
Write-Host "Gunakan script ini hanya saat memulai uji validasi baru, bukan saat sistem operasional berjalan." -ForegroundColor Yellow
