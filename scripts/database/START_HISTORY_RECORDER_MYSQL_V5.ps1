$ErrorActionPreference='Stop'
$ScriptDir=Split-Path -Parent $MyInvocation.MyCommand.Path
$Python='C:\LOCAL_RUN_venv\.venv\Scripts\python.exe'
$Script=Join-Path $ScriptDir 'history_recorder_mysql.py'
if (-not (Test-Path $Python)) { throw "Python venv tidak ditemukan: $Python" }
$env:BIMA2_DB_USER='root'
if (-not $env:BIMA2_DB_PASSWORD) {
  $sec=Read-Host 'Masukkan password ROOT MySQL' -AsSecureString
  $env:BIMA2_DB_PASSWORD=[System.Net.NetworkCredential]::new('', $sec).Password
}
& $Python $Script
