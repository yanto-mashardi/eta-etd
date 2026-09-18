param(
  [ValidateSet('BENGKALIS','PAKNING')]
  [string]$Port='BENGKALIS'
)
$ErrorActionPreference='Stop'

$ProjectRoot=(Resolve-Path (Join-Path $PSScriptRoot '..\..\..')).Path
$ToolsRoot='C:\LOCAL_RUN_venv'
$VideoRoot=Join-Path $ProjectRoot 'data\01_DATA_SOURCE\CCTV\video'
$PortKey=$Port.ToLower()
$RtspUrl="rtsp://127.0.0.1:8554/cctv_$PortKey"

$ffmpeg=Get-ChildItem $ToolsRoot -Filter ffmpeg.exe -Recurse -ErrorAction SilentlyContinue | Select-Object -First 1
$mediamtx=Get-ChildItem $ToolsRoot -Filter mediamtx.exe -Recurse -ErrorAction SilentlyContinue | Select-Object -First 1
if(-not $ffmpeg){throw "ffmpeg.exe tidak ditemukan di $ToolsRoot"}
if(-not $mediamtx){throw "mediamtx.exe tidak ditemukan di $ToolsRoot"}

$envName="CCTV_${Port}_VIDEO"
$sourceVideo=[Environment]::GetEnvironmentVariable($envName)
$sourceStatus='USER_RECORDING'
if(-not $sourceVideo){
  $portDir=Join-Path $VideoRoot $PortKey
  if(Test-Path $portDir){
    $candidate=Get-ChildItem $portDir -File -Include *.mp4,*.mkv,*.avi,*.mov -ErrorAction SilentlyContinue | Sort-Object LastWriteTime -Descending | Select-Object -First 1
    if($candidate){$sourceVideo=$candidate.FullName}
  }
}
if(-not $sourceVideo){
  $legacy=Join-Path $VideoRoot 'kendaraan.mp4'
  if(Test-Path $legacy){
    $sourceVideo=$legacy
    $sourceStatus=if($Port -eq 'PAKNING'){'SIMULATED_SHARED_RECORDING'}else{'SIMULATED_RECORDING'}
    Write-Warning "$Port belum memiliki rekaman khusus. Menggunakan kendaraan.mp4 sebagai simulasi dengan status $sourceStatus."
  }
}
if(-not $sourceVideo -or -not (Test-Path $sourceVideo)){throw "Video sumber CCTV $Port tidak ditemukan."}

$cacheDir=Join-Path $ToolsRoot 'cache\cctv'
$normalizedVideo=Join-Path $cacheDir "cctv_${PortKey}_rtsp_h264_720p25.mp4"
New-Item -ItemType Directory -Force -Path $cacheDir | Out-Null

$rebuild=-not(Test-Path $normalizedVideo)
if(-not $rebuild){
  if((Get-Item $sourceVideo).LastWriteTimeUtc -gt (Get-Item $normalizedVideo).LastWriteTimeUtc){$rebuild=$true}
}
if($rebuild){
  Write-Host "Menyiapkan cache CCTV $Port..." -ForegroundColor Yellow
  & $ffmpeg.FullName -y -i $sourceVideo -map 0:v:0 -an -vf "scale=1280:720,fps=25" -c:v libx264 -preset veryfast -crf 20 -pix_fmt yuv420p -g 25 -keyint_min 25 -sc_threshold 0 -avoid_negative_ts make_zero -movflags +faststart $normalizedVideo
  if($LASTEXITCODE -ne 0 -or -not(Test-Path $normalizedVideo)){throw "Normalisasi video $Port gagal."}
}
if(-not(Get-Process mediamtx -ErrorAction SilentlyContinue)){
  Start-Process -FilePath $mediamtx.FullName -WorkingDirectory $mediamtx.DirectoryName
  Start-Sleep 2
}
$env:CCTV_SOURCE_STATUS=$sourceStatus
Write-Host ""
Write-Host "CCTV RAW $Port" -ForegroundColor Cyan
Write-Host "Source : $sourceVideo"
Write-Host "Status : $sourceStatus"
Write-Host "RTSP   : $RtspUrl"
Write-Host ""
& $ffmpeg.FullName -re -stream_loop -1 -i $normalizedVideo -map 0:v:0 -c:v copy -an -f rtsp -rtsp_transport tcp $RtspUrl
