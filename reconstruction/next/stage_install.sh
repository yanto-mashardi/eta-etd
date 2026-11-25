#!/usr/bin/env bash
# Run as root on the existing VPS. Install only isolated staging files; no legacy writes.
set -euo pipefail
ROOT=/opt/BIMA2_NEXT
REF="${1:?Supply reviewed full Git commit SHA}"
[[ "$REF" =~ ^[0-9a-f]{40}$ ]] || exit 2
test -s /opt/JAES_SIMULASI_BIMA2/data/01_DATA_SOURCE/AIS/realtime/ais_realtime.csv
systemctl is-active --quiet bima2-ais.service
systemctl is-active --quiet bima2-ais-gdrive.timer
if ss -lntH | awk '{print $4}' | grep -qE ':8766$'; then echo 'Port 8766 occupied'; exit 3; fi
test ! -e "$ROOT" || { echo 'Existing staging directory; do not overwrite'; exit 4; }
test ! -e /etc/systemd/system/bima2-next.service
mkdir -m 0750 "$ROOT"
mkdir -p "$ROOT/app" "$ROOT/data" "$ROOT/models/releases"
for f in app.py engine.py events.py live.py stockflow.py capacity.py stock_admin.py vehicle_sender.py dashboard.html test_events.py test_stockflow.py test_capacity.py validate_release.py; do
 curl -fsSL --retry 3 "https://raw.githubusercontent.com/yanto-mashardi/eta-etd/$REF/reconstruction/next/$f" -o "$ROOT/app/$f"
done
# Reuse installed packages read-only for initial diagnostics, not model release parity.
# Separate venv with exact Local Run dependencies is required before model activation.
python3 -m compileall -q "$ROOT/app"
cd "$ROOT/app"
python3 -m unittest -v test_events test_stockflow test_capacity
LEGACY_PY=/opt/JAES_SIMULASI_BIMA2/.venv/bin/python
"$LEGACY_PY" -c 'import fastapi,uvicorn,joblib,pandas,numpy'
id bima2next >/dev/null 2>&1 || useradd --system --no-create-home --shell /usr/sbin/nologin bima2next
chgrp bima2next "$ROOT"
chown -R bima2next:bima2next "$ROOT/data"
chmod 0750 "$ROOT/data"
runuser -u bima2next -- test -r /opt/JAES_SIMULASI_BIMA2/data/01_DATA_SOURCE/AIS/realtime/ais_realtime.csv || { echo 'AIS read access blocked; stop without changing legacy permissions'; exit 5; }
runuser -u bima2next -- "$LEGACY_PY" -c 'import uvicorn,fastapi,joblib,pandas,numpy'
umask 077
printf 'BIMA2_VEHICLE_TOKEN=%s\n' "$(openssl rand -hex 32)" > "$ROOT/staging.env"
cat > /etc/systemd/system/bima2-next.service <<EOF
[Unit]
Description=BIMA2 isolated staging
After=network.target
[Service]
User=bima2next
Group=bima2next
WorkingDirectory=$ROOT/app
Environment=BIMA2_NEXT_ROOT=$ROOT
Environment=PYTHONDONTWRITEBYTECODE=1
Environment=OMP_NUM_THREADS=1
Environment=OPENBLAS_NUM_THREADS=1
EnvironmentFile=$ROOT/staging.env
ExecStart=$LEGACY_PY -m uvicorn app:app --host 127.0.0.1 --port 8766 --workers 1
Restart=on-failure
MemoryMax=400M
CPUQuota=35%
NoNewPrivileges=true
ProtectSystem=strict
ProtectHome=true
ReadWritePaths=$ROOT/data
PrivateTmp=true
[Install]
WantedBy=multi-user.target
EOF
systemctl daemon-reload
systemctl start bima2-next.service
for i in $(seq 1 20); do
 if curl -fsS http://127.0.0.1:8766/api/status >/dev/null; then break; fi
 sleep 1
done
curl -fsS http://127.0.0.1:8766/api/status
systemctl is-active bima2-ais.service bima2-ais-gdrive.timer bima2-next.service
echo 'Staging only. Existing archive and production services unchanged. No public route or auto-enable.'
