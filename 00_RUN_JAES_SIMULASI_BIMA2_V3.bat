@echo off
cd /d "%~dp0"
set "PY=C:\LOCAL_RUN_venv\.venv\Scripts\python.exe"
if not exist "%PY%" (
  echo Environment lokal belum tersedia: %PY%
  echo Jalankan setup LOCAL_RUN pada komputer ini satu kali.
  pause
  exit /b 1
)
"%PY%" "%~dp0scripts\run_manager_v3.py" smoke
if errorlevel 1 (
  echo V3 smoke test gagal.
  pause
  exit /b 1
)
"%PY%" "%~dp0scripts\run_manager_v3.py" start --open-jupyter
pause
