$ErrorActionPreference = 'Stop'
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$Python = 'C:\LOCAL_RUN_venv\.venv\Scripts\python.exe'
$Script = Join-Path $ScriptDir 'build_current_operation_state.py'
if (-not (Test-Path $Python)) { throw "Python tidak ditemukan: $Python" }
if (-not (Test-Path $Script)) { throw "Script tidak ditemukan: $Script" }
& $Python $Script --loop --seconds 5
