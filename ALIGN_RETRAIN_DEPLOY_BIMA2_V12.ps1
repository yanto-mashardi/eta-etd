$ErrorActionPreference = 'Stop'
$R = $PSScriptRoot
$V = 'root@192.236.226.247'
$Py = 'C:\LOCAL_RUN_venv\.venv\Scripts\python.exe'
if (!(Test-Path $Py)) { $Py = 'python' }

Write-Host '=== BIMA2 YEAR-2 METHOD ALIGNMENT V12 ===' -ForegroundColor Cyan

$required = @(
  "$R\config\project_config.yaml",
  "$R\config\vessel_capacity_realtime_v4.csv",
  "$R\scripts\ml1\build_ml1_dataset.py",
  "$R\scripts\ml1\train_ml1.py",
  "$R\scripts\ml2\build_ml2_history_dataset.py",
  "$R\scripts\ml2\train_ml2_manifest.py",
  "$R\scripts\ml2\run_ml2_pipeline.py",
  "$R\scripts\data_source\ais\poll_ais_api_realtime.py",
  "$R\scripts\operation_state_v4\build_current_operation_state.py"
)
foreach ($f in $required) { if (!(Test-Path $f)) { throw "File tidak ditemukan: $f" } }

Write-Host '=== PYTHON CHECK ===' -ForegroundColor Cyan
& $Py -m py_compile `
  "$R\scripts\ml1\build_ml1_dataset.py" `
  "$R\scripts\ml1\train_ml1.py" `
  "$R\scripts\ml2\build_ml2_history_dataset.py" `
  "$R\scripts\ml2\train_ml2_manifest.py" `
  "$R\scripts\data_source\ais\poll_ais_api_realtime.py" `
  "$R\scripts\operation_state_v4\build_current_operation_state.py"

Write-Host '=== RETRAIN ML1: TERMINAL BERTH ARRIVAL ===' -ForegroundColor Cyan
Push-Location $R
& $Py "$R\scripts\ml1\run_ml1.py"
if ($LASTEXITCODE -ne 0) { throw 'ML1 retraining gagal.' }

Write-Host '=== RETRAIN ML2: TURNAROUND CORRECTION ===' -ForegroundColor Cyan
& $Py "$R\scripts\ml2\run_ml2_pipeline.py"
if ($LASTEXITCODE -ne 0) { throw 'ML2 retraining gagal.' }

Write-Host '=== UPDATE ACTIVE REGISTRY ===' -ForegroundColor Cyan
@'
from pathlib import Path
import pandas as pd, yaml, datetime
r=Path.cwd()
ml1m=r/'outputs/01_ml1_eta/tables/metrics_comparison.csv'
ml2m=r/'outputs/02_ml2_turnaround/tables/ml2_model_metrics.csv'
if not ml1m.exists(): raise FileNotFoundError(ml1m)
if not ml2m.exists(): raise FileNotFoundError(ml2m)
a=pd.read_csv(ml1m); b=pd.read_csv(ml2m)
a2=a[~a['model'].str.contains('Baseline',case=False,na=False)].sort_values('MAE_min')
ml1='random_forest' if 'Random Forest' in str(a2.iloc[0]['model']) else 'xgboost'
ml2='random_forest' if 'Random Forest' in str(b.sort_values('MAE_min').iloc[0]['model']) else 'xgboost'
reg=r/'config/registry'; reg.mkdir(parents=True,exist_ok=True)
a.to_csv(reg/'ml1_model_registry.csv',index=False)
b.to_csv(reg/'ml2_model_registry.csv',index=False)
cfg={'run_id':'BIMA2_YEAR2_METHOD_ALIGNED_V12_'+datetime.datetime.now().strftime('%Y%m%d_%H%M%S'),'ml1_eta':{'active':ml1,'alternatives':['random_forest','xgboost'],'selection_metric':'chronological_test_mae_min','arrival_definition':'terminal_berth_arrival'},'ml2_turnaround':{'active':ml2,'alternatives':['random_forest','xgboost'],'selection_metric':'chronological_test_mae_min'}}
(reg/'active_model_config.yaml').write_text(yaml.safe_dump(cfg,sort_keys=False),encoding='utf-8')
print('ML1 active =',ml1)
print('ML2 active =',ml2)
'@ | & $Py -

$ml1rf = "$R\models\ML1_ETA_CORRECTION\06_model_saved\ml1_random_forest.joblib"
$ml1xg = "$R\models\ML1_ETA_CORRECTION\06_model_saved\ml1_xgboost.joblib"
$ml2sel = "$R\models\ML2_TURNAROUND_CORRECTION\06_model_saved\ml2_turnaround_selected.joblib"
$ml2rf = "$R\models\ML2_TURNAROUND_CORRECTION\06_model_saved\ml2_random_forest.joblib"
$ml2xg = "$R\models\ML2_TURNAROUND_CORRECTION\06_model_saved\ml2_xgboost.joblib"
foreach ($f in @($ml1rf,$ml1xg,$ml2sel,$ml2rf,$ml2xg)) { if (!(Test-Path $f)) { throw "Model belum terbentuk: $f" } }

Write-Host '=== UPLOAD V12 TO VPS ===' -ForegroundColor Cyan
$uploads = @(
  @{L="$R\config\project_config.yaml"; D='/tmp/bima2_v12_project_config.yaml'},
  @{L="$R\config\vessel_capacity_realtime_v4.csv"; D='/tmp/bima2_v12_capacity.csv'},
  @{L="$R\config\registry\active_model_config.yaml"; D='/tmp/bima2_v12_active_model.yaml'},
  @{L="$R\config\registry\ml1_model_registry.csv"; D='/tmp/bima2_v12_ml1_registry.csv'},
  @{L="$R\config\registry\ml2_model_registry.csv"; D='/tmp/bima2_v12_ml2_registry.csv'},
  @{L="$R\scripts\data_source\ais\poll_ais_api_realtime.py"; D='/tmp/bima2_v12_ais.py'},
  @{L="$R\scripts\operation_state_v4\build_current_operation_state.py"; D='/tmp/bima2_v12_state.py'},
  @{L=$ml1rf; D='/tmp/bima2_v12_ml1_rf.joblib'}, @{L=$ml1xg; D='/tmp/bima2_v12_ml1_xgb.joblib'},
  @{L=$ml2sel; D='/tmp/bima2_v12_ml2_selected.joblib'}, @{L=$ml2rf; D='/tmp/bima2_v12_ml2_rf.joblib'}, @{L=$ml2xg; D='/tmp/bima2_v12_ml2_xgb.joblib'}
)
$hist = "$R\outputs\history\historical_demand_profile_5min.csv"
if (Test-Path $hist) { $uploads += @{L=$hist; D='/tmp/bima2_v12_demand_profile.csv'} }
foreach ($u in $uploads) { scp $u.L "${V}:$($u.D)"; if ($LASTEXITCODE -ne 0) { throw "SCP gagal: $($u.L)" } }

Write-Host '=== APPLY + BACKUP VPS ===' -ForegroundColor Cyan
$remote = @'
set -e
R=/opt/JAES_SIMULASI_BIMA2
cd "$R"
STAMP=$(date +%Y%m%d_%H%M%S)
B="$R/backups/${STAMP}_METHOD_ALIGNMENT_V12"
mkdir -p "$B/config" "$B/scripts" "$B/models"
cp -a config/project_config.yaml "$B/config/" 2>/dev/null || true
cp -a config/registry "$B/config/registry" 2>/dev/null || true
cp -a scripts/data_source/ais/poll_ais_api_realtime.py "$B/scripts/" 2>/dev/null || true
cp -a scripts/operation_state_v4/build_current_operation_state.py "$B/scripts/" 2>/dev/null || true
cp -a models/ML1_ETA_CORRECTION/06_model_saved "$B/models/ml1" 2>/dev/null || true
cp -a models/ML2_TURNAROUND_CORRECTION/06_model_saved "$B/models/ml2" 2>/dev/null || true

mkdir -p config/archive config/registry outputs/history models/ML1_ETA_CORRECTION/06_model_saved models/ML2_TURNAROUND_CORRECTION/06_model_saved
cp /tmp/bima2_v12_project_config.yaml config/project_config.yaml
cp /tmp/bima2_v12_capacity.csv config/vessel_capacity_realtime_v4.csv
cp /tmp/bima2_v12_active_model.yaml config/registry/active_model_config.yaml
cp /tmp/bima2_v12_ml1_registry.csv config/registry/ml1_model_registry.csv
cp /tmp/bima2_v12_ml2_registry.csv config/registry/ml2_model_registry.csv
cp /tmp/bima2_v12_ais.py scripts/data_source/ais/poll_ais_api_realtime.py
cp /tmp/bima2_v12_state.py scripts/operation_state_v4/build_current_operation_state.py
cp /tmp/bima2_v12_ml1_rf.joblib models/ML1_ETA_CORRECTION/06_model_saved/ml1_random_forest.joblib
cp /tmp/bima2_v12_ml1_xgb.joblib models/ML1_ETA_CORRECTION/06_model_saved/ml1_xgboost.joblib
cp /tmp/bima2_v12_ml2_selected.joblib models/ML2_TURNAROUND_CORRECTION/06_model_saved/ml2_turnaround_selected.joblib
cp /tmp/bima2_v12_ml2_rf.joblib models/ML2_TURNAROUND_CORRECTION/06_model_saved/ml2_random_forest.joblib
cp /tmp/bima2_v12_ml2_xgb.joblib models/ML2_TURNAROUND_CORRECTION/06_model_saved/ml2_xgboost.joblib
[ -f /tmp/bima2_v12_demand_profile.csv ] && cp /tmp/bima2_v12_demand_profile.csv outputs/history/historical_demand_profile_5min.csv || true

for f in project_config_realtime_v4.yaml ais_source_config_v4.yaml cctv_source_config_v4.yaml simulation_config.yaml model_policy.yaml ml1_config.yaml ports_berths.yaml project_config.json active_pipeline.json; do
  [ -f "config/$f" ] && mv "config/$f" "config/archive/ARCHIVED_$f" || true
done

.venv/bin/python3 -m py_compile scripts/data_source/ais/poll_ais_api_realtime.py scripts/operation_state_v4/build_current_operation_state.py
systemctl restart bima2-ais bima2-state bima2-api
sleep 8

echo '=== SERVICES ==='
systemctl is-active bima2-ais bima2-state bima2-api

echo '=== SINGLE CONFIG CHECK ==='
ls -1 config | sed -n '1,80p'

echo '=== ACTIVE MODELS ==='
cat config/registry/active_model_config.yaml

echo '=== RESEARCH HISTORY ==='
ls -lh outputs/history/operation_state_5min.csv 2>/dev/null || echo 'operation_state_5min.csv belum tercipta; tunggu tick state berikutnya.'

echo '=== STALE POLICY SOURCE ==='
grep -n 'STALE_NO_INFERENCE' scripts/operation_state_v4/build_current_operation_state.py | head

echo "BACKUP=$B"
'@
ssh $V $remote
Pop-Location
Write-Host '=== METHOD ALIGNMENT V12 COMPLETE ===' -ForegroundColor Green
