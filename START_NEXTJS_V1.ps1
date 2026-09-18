$ErrorActionPreference='Stop'

$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot '.')).Path
$SourceWeb   = Join-Path $ProjectRoot 'web\ferry-dashboard'
$RuntimeRoot = 'C:\LOCAL_RUN_venv\nextjs_runtime'
$RuntimeWeb  = Join-Path $RuntimeRoot 'ferry-dashboard'

if (-not (Get-Command node -ErrorAction SilentlyContinue)) {
    throw 'Node.js belum terpasang atau belum ada di PATH.'
}
if (-not (Get-Command npm -ErrorAction SilentlyContinue)) {
    throw 'npm belum tersedia di PATH.'
}
if (-not (Test-Path (Join-Path $SourceWeb 'package.json'))) {
    throw "package.json tidak ditemukan di $SourceWeb"
}

# Jangan pernah simpan node_modules/.next di Google Drive.
$driveNodeModules = Join-Path $SourceWeb 'node_modules'
$driveNext        = Join-Path $SourceWeb '.next'
if (Test-Path $driveNodeModules) {
    Write-Host 'Menghapus node_modules yang terlanjur dibuat di Google Drive...' -ForegroundColor Yellow
    Remove-Item $driveNodeModules -Recurse -Force -ErrorAction SilentlyContinue
}
if (Test-Path $driveNext) {
    Remove-Item $driveNext -Recurse -Force -ErrorAction SilentlyContinue
}

New-Item -ItemType Directory -Force -Path $RuntimeRoot | Out-Null
New-Item -ItemType Directory -Force -Path $RuntimeWeb  | Out-Null

Write-Host 'Sinkron source Next.js Drive -> runtime lokal C: ...' -ForegroundColor Cyan
$null = & robocopy $SourceWeb $RuntimeWeb /MIR /XD node_modules .next /XF npm-debug.log /R:2 /W:1
$rc=$LASTEXITCODE
if ($rc -gt 7) {
    throw "Robocopy gagal. ExitCode=$rc"
}

Push-Location $RuntimeWeb
try {
    $npmCache='C:\LOCAL_RUN_venv\npm-cache'
    New-Item -ItemType Directory -Force -Path $npmCache | Out-Null
    npm config set cache $npmCache --location=user | Out-Null

    if (-not (Test-Path '.\node_modules\next')) {
        Write-Host 'Menginstal dependency Next.js di C: ...' -ForegroundColor Cyan
        npm install --no-audit --no-fund
    }

    Write-Host ''
    Write-Host 'Next.js runtime lokal:' $RuntimeWeb -ForegroundColor Green
    Write-Host 'Dashboard: http://127.0.0.1:3000/bengkalis' -ForegroundColor Green
    npm run dev
}
finally {
    Pop-Location
}
