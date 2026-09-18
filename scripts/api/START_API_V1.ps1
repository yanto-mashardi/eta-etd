$ErrorActionPreference='Stop'

$ProjectRoot=(Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$Python='C:\LOCAL_RUN_venv\.venv\Scripts\python.exe'
if (-not (Test-Path $Python)) { throw "Python venv tidak ditemukan: $Python" }

if (-not $env:BIMA2_DB_PASSWORD) {
    $sec=Read-Host "Masukkan password ROOT MySQL" -AsSecureString
    $env:BIMA2_DB_PASSWORD=[System.Net.NetworkCredential]::new('', $sec).Password
}

# Install hanya bila modul belum tersedia.
& $Python -c "import fastapi,uvicorn,mysql.connector,bcrypt,jwt" 2>$null
if ($LASTEXITCODE -ne 0) {
    Write-Host 'Menginstal dependency API satu kali...' -ForegroundColor Cyan
    & $Python -m pip install -r (Join-Path $PSScriptRoot 'requirements_api_v1.txt')
}

Push-Location $ProjectRoot
try {
    Write-Host 'FastAPI: http://127.0.0.1:8000' -ForegroundColor Green
    & $Python -m uvicorn scripts.api.main:app --host 127.0.0.1 --port 8000
}
finally {
    Pop-Location
}
