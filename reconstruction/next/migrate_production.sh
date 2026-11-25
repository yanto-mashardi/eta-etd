#!/usr/bin/env bash
# Approved staged production cutover. Retain AIS, raw data, database and legacy source.
set -Eeuo pipefail
ROOT=/opt/BIMA2_NEXT
DOMAIN=eta-etd.gudang-apps.my.id
CONF=$(readlink -f /etc/nginx/sites-enabled/bima2)
test -f "$CONF"
exec 9>"$ROOT/.migration.lock"
flock -n 9
OLD=(bima2-dashboard.service bima2-api.service bima2-state.service bima2-history.service bima2-cctv-watch.service bima2-yolo-hls.service)
KEEP=(bima2-next.service bima2-ais.service bima2-ais-gdrive.timer)
for u in "${KEEP[@]}"; do systemctl is-active --quiet "$u"; done
curl -fsS --max-time 20 http://127.0.0.1:8766/api/status | python3 -c 'import json,sys;x=json.load(sys.stdin);assert x["models"]["status"]=="MODEL_LOADED_UNVALIDATED" and x["models"]["release"] and x["event_engine"]["history_seed_count"]>0'
# Refuse to stop a required/wanted dependency of the preserved services.
for u in "${KEEP[@]}" bima2-ais-gdrive.service; do
 deps=$(systemctl show "$u" -p Requires -p Wants -p BindsTo -p Requisite -p PartOf --value)
 for old in "${OLD[@]}"; do
  if grep -qwF "$old" <<<"$deps"; then echo "Protected dependency: $u -> $old"; exit 1; fi
 done
done
BACK=$(mktemp -d "$ROOT/migration_backup_XXXXXXXX")
chmod 700 "$BACK"
cp -p "$CONF" "$BACK/nginx.conf"
for u in "${OLD[@]}"; do
 systemctl is-enabled "$u" > "$BACK/$u.enabled" 2>/dev/null || true
 systemctl is-active "$u" > "$BACK/$u.active" 2>/dev/null || true
 fragment=$(systemctl show "$u" -p FragmentPath --value)
 if [[ -n "$fragment" && "$fragment" != "/etc/systemd/system/$u" ]]; then
  echo "Unexpected unit location $fragment; aborting"; exit 1
 fi
 if [[ -f "/etc/systemd/system/$u" ]]; then cp -a "/etc/systemd/system/$u" "$BACK/$u"; fi
 if [[ -d "/etc/systemd/system/$u.d" ]]; then cp -a "/etc/systemd/system/$u.d" "$BACK/$u.d"; fi
done
rollback(){
 trap - ERR
 set +e
 echo "Migration failed: restoring previous routing and services"
 cp -p "$BACK/nginx.conf" "$CONF"
 for u in "${OLD[@]}"; do
  if [[ -e "$BACK/$u" ]]; then cp -a "$BACK/$u" "/etc/systemd/system/$u"; fi
  if [[ -d "$BACK/$u.d" ]]; then cp -a "$BACK/$u.d" /etc/systemd/system/; fi
 done
 systemctl daemon-reload
 for u in "${OLD[@]}"; do
  if grep -qx enabled "$BACK/$u.enabled"; then systemctl enable "$u"; fi
  if grep -Eq '^(active|activating)$' "$BACK/$u.active"; then systemctl start "$u"; fi
 done
 nginx -t && systemctl reload nginx
 echo "Rollback files: $BACK"
 exit 1
}
trap rollback ERR
# Patch only known upstreams in the dedicated BIMA2 site; preserve TLS and all other directives.
python3 - "$CONF" "$DOMAIN" <<'PYCODE'
import pathlib,re,sys
p=pathlib.Path(sys.argv[1]);s=p.read_text()
if set(re.findall(r'(?m)^\s*server_name\s+([^;]+);',s))!={sys.argv[2]}:
 raise SystemExit("Unexpected server names; no changes")
for port in (8000,3000):
 pat=rf'(?m)^(\s*proxy_pass\s+)http://127\.0\.0\.1:{port};'
 s,n=re.subn(pat,r'\g<1>http://127.0.0.1:8766;',s)
 if n!=1:raise SystemExit(f"Unexpected upstream count for {port}: {n}")
# Legacy HLS endpoints intentionally unavailable until the new CCTV subsystem is installed.
s,n=re.subn(r'(?m)^([ \t]*)proxy_pass\s+http://127\.0\.0\.1:18888[^;]*;',r'\g<1>return 503;',s)
if n!=3:raise SystemExit(f"Unexpected CCTV upstream count: {n}")
p.write_text(s)
PYCODE
nginx -t
systemctl reload nginx
probe(){
 local base="https://$DOMAIN"
 for path in / /bengkalis /pakning /inspection; do
  curl -fsS --max-time 20 --resolve "$DOMAIN:443:127.0.0.1" "$base$path" >/dev/null || return 1
 done
 curl -fsS --max-time 20 --resolve "$DOMAIN:443:127.0.0.1" "$base/api/status" | python3 -c 'import json,sys;x=json.load(sys.stdin);assert x["models"]["release"] and x["event_engine"]["history_seed_count"]>0 and x["models"]["status"]=="MODEL_LOADED_UNVALIDATED"'
}
probe
systemctl enable bima2-next.service
# Stop and unregister only exact obsolete units. Keep their source and historical data
# because AIS still uses the old tree; physical source pruning needs dependency inventory.
for u in "${OLD[@]}"; do systemctl stop "$u"; done
for u in "${OLD[@]}"; do
 systemctl disable "$u"
 if [[ -f "/etc/systemd/system/$u" ]]; then rm -- "/etc/systemd/system/$u"; fi
 if [[ -d "/etc/systemd/system/$u.d" ]]; then rm -rf -- "/etc/systemd/system/$u.d"; fi
done
systemctl daemon-reload
for u in "${KEEP[@]}"; do systemctl is-active --quiet "$u"; done
for u in "${OLD[@]}"; do
 if systemctl is-active --quiet "$u"; then echo "Obsolete service still running: $u"; false; fi
done
probe
trap - ERR
echo "MIGRATION SUCCESS: https://$DOMAIN"
echo "Old app services removed; AIS/data retained. Rollback files: $BACK"
systemctl show bima2-next.service -p ActiveState -p MemoryCurrent -p MemoryMax
systemctl show bima2-ais-gdrive.service -p Result -p ExecMainStatus
