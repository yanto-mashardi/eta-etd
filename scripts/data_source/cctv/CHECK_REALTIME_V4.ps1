$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot '..\..\..')).Path
$items = @(
  'data\01_DATA_SOURCE\AIS\historical',
  'data\01_DATA_SOURCE\AIS\replay',
  'data\01_DATA_SOURCE\AIS\realtime',
  'data\01_DATA_SOURCE\CCTV\video',
  'data\01_DATA_SOURCE\CCTV\output',
  'data\01_DATA_SOURCE\VEHICLE_HISTORICAL',
  'models\YOLO',
  'outputs\operation_state'
)
foreach ($rel in $items) {
  $p = Join-Path $ProjectRoot $rel
  if (Test-Path $p) { Write-Host "[OK] $rel" -ForegroundColor Green }
  else { Write-Host "[MISSING] $rel" -ForegroundColor Red }
}
$toolRoot='C:\LOCAL_RUN_venv'
foreach($exe in @('ffmpeg.exe','mediamtx.exe')){
  $f=Get-ChildItem $toolRoot -Filter $exe -Recurse -ErrorAction SilentlyContinue | Select-Object -First 1
  if($f){Write-Host "[OK] $exe -> $($f.FullName)" -ForegroundColor Green}
  else{Write-Host "[MISSING] $exe under $toolRoot" -ForegroundColor Yellow}
}
