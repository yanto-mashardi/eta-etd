param(
  [string]$DbHost='127.0.0.1',
  [int]$DbPort=3306,
  [string]$DbName='jaes_bima2',
  [string]$AdminUsername='Admin',
  [string]$AdminPassword='Admin1234'
)
$ErrorActionPreference='Stop'
$ScriptDir=Split-Path -Parent $MyInvocation.MyCommand.Path
$Python='C:\LOCAL_RUN_venv\.venv\Scripts\python.exe'
if (-not (Test-Path $Python)) { throw "Python venv tidak ditemukan: $Python" }
$mysql=(Get-Command mysql.exe -ErrorAction SilentlyContinue)
if (-not $mysql) { throw 'mysql.exe tidak ditemukan di PATH.' }
$sec=Read-Host 'Masukkan password ROOT MySQL' -AsSecureString
$DbPassword=[System.Net.NetworkCredential]::new('', $sec).Password
$env:BIMA2_DB_HOST=$DbHost
$env:BIMA2_DB_PORT="$DbPort"
$env:BIMA2_DB_NAME=$DbName
$env:BIMA2_DB_USER='root'
$env:BIMA2_DB_PASSWORD=$DbPassword
$env:BIMA2_ADMIN_USERNAME=$AdminUsername
$env:BIMA2_ADMIN_PASSWORD=$AdminPassword
& $Python -m pip install -r (Join-Path $ScriptDir 'requirements_mysql_v5.txt')
$env:MYSQL_PWD=$DbPassword
Get-Content (Join-Path $ScriptDir 'create_tables.sql') | & mysql.exe -h $DbHost -P $DbPort -u root $DbName
Get-Content (Join-Path $ScriptDir 'seed_roles_permissions.sql') | & mysql.exe -h $DbHost -P $DbPort -u root $DbName
& $Python (Join-Path $ScriptDir 'seed_initial_admin.py')
Remove-Item Env:MYSQL_PWD -ErrorAction SilentlyContinue
Write-Host "MySQL jaes_bima2 siap. Koneksi DB=root. Dashboard Master Admin=$AdminUsername" -ForegroundColor Green
