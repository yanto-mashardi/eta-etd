#!/usr/bin/env bash
# Read-only operational audit. Do not print secrets or environment contents.
ROOT=/opt/JAES_SIMULASI_BIMA2
cd "$ROOT" || exit 1
echo '=== TIME ==='; date -Is; TZ=Asia/Jakarta date -Is
echo '=== SERVICES ==='
for s in bima2-ais bima2-ais-gdrive bima2-ais-gdrive.timer bima2-state bima2-api bima2-history bima2-dashboard bima2-cctv-watch; do
 echo "$s"; systemctl show "$s" -p LoadState -p ActiveState -p Result -p ExecMainStatus -p MainPID -p WorkingDirectory -p FragmentPath
done
systemctl list-timers --all --no-pager | grep -Ei 'ais|archive|gdrive' || true
echo '=== ARCHIVE ==='
command -v rclone; rclone listremotes
timeout 45 rclone lsf aisdrive: --files-only | grep '^AIS_RAW_' | sort | tail -10
grep -nE '^[[:space:]]*(store_raw_payload|append_history):' config/project_config.yaml
echo '=== AIS FILES ==='
find data/01_DATA_SOURCE/AIS/realtime -maxdepth 2 -type f -printf '%p %s bytes %TY-%Tm-%Td %TH:%TM\n' | sort | tail -30
echo '=== SOURCE HASH ==='
for f in scripts/data_source/ais/poll_ais_api_realtime.py scripts/archive/ais_daily_gdrive.py scripts/api/main.py scripts/operation_state_v4/build_current_operation_state.py scripts/database/history_recorder_mysql.py; do
 if [ -f "$f" ]; then git hash-object "$f"; echo "$f"; fi
done
echo '=== MODELS ==='
find models -type f -name '*.joblib' -printf '%p %s bytes\n' | sort
.venv/bin/python --version
.venv/bin/python -m pip list | grep -Ei 'scikit|catboost|xgboost|pandas|numpy|joblib'
echo '=== AIS SCHEMA (HEADER ONLY) ==='
head -n 1 data/01_DATA_SOURCE/AIS/realtime/ais_realtime.csv
echo '=== END ==='
