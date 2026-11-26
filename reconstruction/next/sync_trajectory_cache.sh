#!/usr/bin/env bash
# Root-only mirror of seven completed WIB days. Never expose rclone credentials to web service.
set -euo pipefail
umask 077
ROOT=/opt/BIMA2_NEXT
CACHE="$ROOT/data/trajectory_cache"
install -d -o root -g bima2next -m 0750 "$CACHE"
exec 9>"$ROOT/.trajectory-sync.lock"
flock -n 9 || exit 0
# Remove abandoned downloads only while holding the exclusive sync lock.
find "$CACHE" -maxdepth 1 -type f -name '.download.*' -delete
tmp=''
trap 'if [[ -n "$tmp" ]]; then rm -f -- "$tmp"; fi' EXIT
for i in $(seq 1 7); do
 day=$(TZ=Asia/Jakarta date -d "$i days ago" +%F)
 name="AIS_RAW_$day.csv"
 if [[ -s "$CACHE/$name" ]]; then continue; fi
 tmp=$(mktemp "$CACHE/.download.XXXXXX")
 if rclone copyto "aisdrive:$name" "$tmp" --config /root/.config/rclone/rclone.conf --retries 2 --contimeout 15s --timeout 60s; then
  if python3 - "$tmp" <<'PY'
import csv,sys
with open(sys.argv[1],encoding="utf-8-sig",newline="") as f:
 r=csv.DictReader(f)
 assert {"mmsi","received_at_original","lat","lon","sog","update_at","timestamp"}<=set(r.fieldnames or [])
 assert next(r,None) is not None
PY
  then
   chown root:bima2next "$tmp"
   chmod 0640 "$tmp"
   mv "$tmp" "$CACHE/$name"
   echo "[OK] $name"
  else rm -f "$tmp"; echo "[INVALID] $name" >&2; exit 1; fi
 else rm -f "$tmp"; echo "[UNAVAILABLE] $name" >&2; fi
done
cutoff=$(TZ=Asia/Jakarta date -d '7 days ago' +%F)
for f in "$CACHE"/AIS_RAW_????-??-??.csv; do
 [[ -f "$f" ]] || continue
 name=${f##*/}; day=${name#AIS_RAW_}; day=${day%.csv}
 if [[ "$day" < "$cutoff" ]]; then rm -- "$f"; fi
done
