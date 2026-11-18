#!/usr/bin/env bash
# One-shot DediRock setup for daily raw AIS -> Google Drive.
# Does not delete or alter MySQL data, trained models, dashboard, or CCTV.
set -Eeuo pipefail

ROOT=/opt/JAES_SIMULASI_BIMA2
REMOTE=aisdrive:
URL=https://raw.githubusercontent.com/yanto-mashardi/eta-etd/main/scripts/archive/ais_daily_gdrive.py
HISTORY="$ROOT/data/01_DATA_SOURCE/AIS/realtime/ais_realtime_history.csv"
cd "$ROOT"
test "$(id -u)" -eq 0 || { echo "Must run as root"; exit 1; }
test -x .venv/bin/python || { echo "Python venv missing"; exit 1; }
test -f config/project_config.yaml || { echo "Project config missing"; exit 1; }
command -v rclone >/dev/null || { echo "rclone not installed"; exit 1; }
command -v curl >/dev/null || { echo "curl not installed"; exit 1; }
echo "[1/6] Verify Google Drive access"
rclone lsf "$REMOTE" >/dev/null
# Confirm write permission using a small unique test file, remove only that file.
TEST_NAME=".ais_permission_test_$(date +%s)_$$.txt"
printf 'AIS_ARCHIVE_TEST\n' | rclone rcat "$REMOTE$TEST_NAME"
rclone deletefile "$REMOTE$TEST_NAME"
echo "[2/6] Fetch & validate latest archive module"
mkdir -p scripts/archive
TEMP=$(mktemp scripts/archive/.ais_daily_gdrive.XXXXXXXX.py)
trap 'rm -f "$TEMP"' EXIT
curl -fsSL --retry 3 "$URL" -o "$TEMP"
.venv/bin/python -m py_compile "$TEMP"
mv -f "$TEMP" scripts/archive/ais_daily_gdrive.py
chmod 0644 scripts/archive/ais_daily_gdrive.py
echo "[3/6] Install safe scheduled service, 00:10 WIB / 17:10 UTC"
cat >/etc/systemd/system/bima2-ais-gdrive.service <<'EOF'
[Unit]
Description=BIMA2 daily raw AIS CSV upload and verified local cleanup
Wants=network-online.target
After=network-online.target
[Service]
Type=oneshot
User=root
WorkingDirectory=/opt/JAES_SIMULASI_BIMA2
ExecStart=/usr/bin/flock -n /run/lock/bima2-ais-gdrive.lock /opt/JAES_SIMULASI_BIMA2/.venv/bin/python /opt/JAES_SIMULASI_BIMA2/scripts/archive/ais_daily_gdrive.py --cleanup-uploaded
EOF
cat >/etc/systemd/system/bima2-ais-gdrive.timer <<'EOF'
[Unit]
Description=Daily raw AIS archive at 00:10 WIB
[Timer]
OnCalendar=*-*-* 17:10:00 UTC
Persistent=true
Unit=bima2-ais-gdrive.service
[Install]
WantedBy=timers.target
EOF
systemd-analyze calendar '*-*-* 17:10:00 UTC' >/dev/null
systemctl daemon-reload
systemctl enable --now bima2-ais-gdrive.timer
echo "[4/6] Install one-time normalized historical CSV migration"
cat >/usr/local/sbin/bima2-ais-legacy-history-migrate <<'EOF'
#!/usr/bin/env bash
set -Eeuo pipefail
P=/opt/JAES_SIMULASI_BIMA2/data/01_DATA_SOURCE/AIS/realtime/ais_realtime_history.csv
if [[ ! -s "$P" ]]; then echo "No legacy history to upload"; exit 0; fi
DEST="aisdrive:AIS_NORMALIZED_HISTORY_PRE_ARCHIVE_$(TZ=Asia/Jakarta date +%Y%m%d).csv"
echo "Copy legacy $(du -h "$P") to $DEST"
rclone copyto "$P" "$DEST" --retries 4
LOCAL_MD5=$(md5sum "$P" | awk '{print $1}')
REMOTE_MD5=$(rclone md5sum "$DEST" | awk 'NR==1{print $1}')
if [[ -z "$REMOTE_MD5" || "$LOCAL_MD5" != "$REMOTE_MD5" ]]; then
  echo "MD5 mismatch; local legacy file preserved" >&2
  exit 1
fi
# Check no process holds this file, to avoid deleting a still-active writer.
if command -v fuser >/dev/null && fuser -s "$P" 2>/dev/null; then
  echo "Legacy CSV still in use; preserved" >&2
  exit 1
fi
rm -- "$P"
echo "Legacy history verified on Drive by MD5 and deleted locally."
EOF
chmod 0700 /usr/local/sbin/bima2-ais-legacy-history-migrate
cat >/etc/systemd/system/bima2-ais-legacy-migrate.service <<'EOF'
[Unit]
Description=One-time archival of old AIS normalized CSV history
Wants=network-online.target
After=network-online.target
[Service]
Type=oneshot
User=root
WorkingDirectory=/opt/JAES_SIMULASI_BIMA2
ExecStart=/usr/local/sbin/bima2-ais-legacy-history-migrate
EOF
systemctl daemon-reload
echo "[5/6] Disable new unlimited normalized CSV append; leave raw JSONL active"
.venv/bin/python - <<'PY'
from pathlib import Path
p = Path('config/project_config.yaml')
s = p.read_text()
assert '    store_raw_payload: true' in s, 'Raw AIS capture must remain enabled'
assert '    append_history:' in s
s = s.replace('    append_history: true', '    append_history: false')
p.write_text(s)
PY
systemctl restart bima2-ais.service
systemctl is-active --quiet bima2-ais.service || {
  echo "AIS receiver failed after restart; check journalctl -u bima2-ais.service"
  exit 1
}
echo "[6/6] Start legacy upload in independent systemd service"
systemctl start --no-block bima2-ais-legacy-migrate.service
echo "READY: daily automatic archive installed; legacy 316MB migration is started."
echo "Timer: systemctl list-timers bima2-ais-gdrive.timer --no-pager"
echo "Logs: journalctl -u bima2-ais-gdrive.service -n 30 --no-pager"
echo "Legacy progress: journalctl -u bima2-ais-legacy-migrate.service -n 30 --no-pager"
echo "MySQL was not modified."
