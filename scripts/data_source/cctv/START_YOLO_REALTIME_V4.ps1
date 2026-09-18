param(
  [ValidateSet('BENGKALIS','PAKNING')]
  [string]$Port='BENGKALIS'
)
$ErrorActionPreference='Stop'
$ScriptDir=Split-Path -Parent $MyInvocation.MyCommand.Path
$Python='C:\LOCAL_RUN_venv\.venv\Scripts\python.exe'
$Script=Join-Path $ScriptDir 'count_vehicle_realtime.py'
if(-not(Test-Path $Python)){throw "Python venv tidak ditemukan: $Python"}
if(-not(Test-Path $Script)){throw "Script realtime tidak ditemukan: $Script"}

$PortKey=$Port.ToLower()
$env:OPENCV_FFMPEG_CAPTURE_OPTIONS='rtsp_transport;tcp'
$env:CCTV_INPUT_MODE='rtsp'
$env:CCTV_PORT=$Port
$env:CCTV_STREAM_KEY="cctv_$PortKey"
$env:CCTV_RAW_RTSP="rtsp://127.0.0.1:8554/cctv_$PortKey"
$env:CCTV_ANNOTATED_RTSP="rtsp://127.0.0.1:8554/cctv_${PortKey}_yolo"
if(-not $env:CCTV_SOURCE_STATUS){$env:CCTV_SOURCE_STATUS='OBSERVED_OR_USER_RECORDING'}

Write-Host ""
Write-Host "JAES CCTV YOLO REALTIME V4.4 - $Port" -ForegroundColor Cyan
Write-Host "RAW  : $env:CCTV_RAW_RTSP"
Write-Host "YOLO : $env:CCTV_ANNOTATED_RTSP"
Write-Host "Output state + histori 5-menit dipisahkan per pelabuhan."
Write-Host ""
& $Python $Script
