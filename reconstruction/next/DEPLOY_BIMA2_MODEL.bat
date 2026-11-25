@echo off
setlocal
if "%~1"=="" exit /b 2
if "%~2"=="" exit /b 2
rem Arguments: local release folder, release ID (letters digits underscore hyphen only)
set "RID=%~2"
powershell -NoProfile -Command "if ($env:RID -cnotmatch '^[A-Za-z0-9_-]+$') {exit 1}"
if errorlevel 1 exit /b 2
ssh root@192.236.226.247 "mkdir -p /opt/BIMA2_NEXT/incoming && test ! -e /opt/BIMA2_NEXT/incoming/%RID%"
if errorlevel 1 exit /b 1
scp -r "%~1" root@192.236.226.247:/opt/BIMA2_NEXT/incoming/%RID%
if errorlevel 1 exit /b 1
ssh root@192.236.226.247 "bash /opt/BIMA2_NEXT/app/activate_release.sh %RID%"
exit /b %errorlevel%
