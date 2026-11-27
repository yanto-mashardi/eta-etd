#!/usr/bin/env bash
# Root-only rotation; no token printed or passed in command arguments.
set -euo pipefail
[[ $(id -u) == 0 ]]
ROOT=/opt/BIMA2_NEXT
test -s "$ROOT/cctv-admin.env"
exec 9>"$ROOT/.cctv-token-rotation.lock"
flock -x 9
umask 077
tmp=$(mktemp "$ROOT/.cctv-admin.XXXXXX")
trap 'rm -f "$tmp"' EXIT
printf 'BIMA2_CCTV_ADMIN_TOKEN=%s\n' "$(openssl rand -hex 32)" > "$tmp"
mv -f "$tmp" "$ROOT/cctv-admin.env"
systemctl restart bima2-next.service
curl -fsS --retry 30 --retry-connrefused --retry-delay 2 http://127.0.0.1:8766/api/status >/dev/null
python3 - "$ROOT/cctv-admin.env" <<'PY'
import sys,urllib.request,urllib.error
token=open(sys.argv[1]).read().strip().split('=',1)[1]
url='http://127.0.0.1:8766/api/inspection/cctv/readers/accounts'
with urllib.request.urlopen(urllib.request.Request(url,headers={'Authorization':'Bearer '+token}),timeout=10) as r:
 assert r.status==200
try:urllib.request.urlopen(url,timeout=10)
except urllib.error.HTTPError as e:assert e.code==401
else:raise RuntimeError('Unauthenticated request accepted')
PY
echo 'Token rotated. Retrieve privately: cat /opt/BIMA2_NEXT/cctv-admin.env'
