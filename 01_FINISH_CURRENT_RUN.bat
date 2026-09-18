@echo off
setlocal
cd /d "%~dp0"

set "PY=C:\LOCAL_RUN_venv\.venv\Scripts\python.exe"
if not exist "%PY%" (
  echo ERROR: Python LOCAL_RUN tidak ditemukan: %PY%
  pause
  exit /b 1
)

"%PY%" "%~dp0scripts\run_manager_v3.py" success
if errorlevel 1 (
  echo.
  echo ERROR: proses finalisasi run gagal.
  pause
  exit /b 1
)

echo.
if exist "%~dp0current_run.json" (
  echo ERROR: current_run.json masih tertinggal.
  pause
  exit /b 1
)
if exist "%~dp0.run_lock.json" (
  echo ERROR: .run_lock.json masih tertinggal.
  pause
  exit /b 1
)

echo FINISH COMPLETE
echo current_run.json = CLEAN
echo .run_lock.json   = CLEAN
echo Ringkasan hasil  = outputs\RUN_xxx\00_run\RUN_SUMMARY.md
pause
endlocal
