@echo off
setlocal
if "%~7"=="" (
 echo Usage: EXPORT_BIMA2_MODEL.bat results history eta_csv early_csv conventional_csv output release_id
 exit /b 2
)
python "%~dp0export_release.py" --results "%~1" --history "%~2" --eta-data "%~3" --early-data "%~4" --conventional-data "%~5" --output "%~6" --release "%~7"
exit /b %errorlevel%
