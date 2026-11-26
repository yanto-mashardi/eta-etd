#!/usr/bin/env bash
set -euo pipefail
[[ $(id -u) == 0 ]]
ROOT=/opt/BIMA2_NEXT
BASE=/var/lib/bima2-cctv
systemctl is-active --quiet cctv-relay.service
systemctl is-active --quiet bima2-next.service
# Ubuntu system Python uses PyYAML for converting the existing configuration once.
python3 -c 'import yaml' || { echo 'Install python3-yaml first'; exit 1; }
install -d -o bima2next -g cctvrelay -m 2750 "$BASE"
if [[ ! -f "$BASE/mediamtx.yml" ]]; then
 python3 - "$BASE" <<'PY'
import json,sys,yaml,os
from pathlib import Path
b=Path(sys.argv[1]);c=yaml.safe_load(Path('/opt/CCTV_RELAY/mediamtx.yml').read_text())
assert c['authMethod']=='internal' and set(c['paths']) in ({'bengkalis','pakning'},{'live/bengkalis','live/pakning'})
assert all(p.get('source')=='publisher' and p.get('record') is False for p in c['paths'].values())
c['api']=True;c['apiAddress']='127.0.0.1:9997'
c['authInternalUsers'].append({'user':'any','pass':'','ips':['127.0.0.1','::1'],'permissions':[{'action':'api'}]})
for name,obj in [('mediamtx.yml',c),('devices.json',{})]:
 p=b/name
 with p.open('x') as f:json.dump(obj,f,indent=2)
 os.chmod(p,0o640 if name=='mediamtx.yml' else 0o600)
PY
 chown bima2next:cctvrelay "$BASE/mediamtx.yml" "$BASE/devices.json"
fi
# Migrate existing manager configuration as well as first-time installation.
python3 - "$BASE" <<'PY'
import json,sys,os,tempfile
from pathlib import Path
p=Path(sys.argv[1])/'mediamtx.yml'
c=json.loads(p.read_text())
old={'bengkalis','pakning'}
new={'live/bengkalis','live/pakning'}
assert set(c['paths']) in (old,new), 'Unexpected relay paths'
if set(c['paths'])==old:
    c['paths']={'live/'+k:v for k,v in c['paths'].items()}
    for u in c['authInternalUsers']:
        for perm in u.get('permissions',[]):
            if perm.get('path') in old:perm['path']='live/'+perm['path']
    st=p.stat()
    backup=p.with_name('mediamtx.pre-live.json')
    if not backup.exists():
        fd=os.open(backup,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
        with os.fdopen(fd,'w') as f:f.write(p.read_text())
    fd,tmp=tempfile.mkstemp(dir=p.parent)
    with os.fdopen(fd,'w') as f:
        os.fchown(f.fileno(),st.st_uid,st.st_gid)
        os.fchmod(f.fileno(),0o640)
        json.dump(c,f,indent=2)
    os.replace(tmp,p)
assert set(c['paths'])==new
PY
install -d -m 0755 /etc/systemd/system/cctv-relay.service.d /etc/systemd/system/bima2-next.service.d
if [[ ! -s "$ROOT/cctv-admin.env" ]]; then
 (umask 077; printf 'BIMA2_CCTV_ADMIN_TOKEN=%s\n' "$(openssl rand -hex 32)" > "$ROOT/cctv-admin.env")
fi
cat > /etc/systemd/system/cctv-relay.service.d/manager.conf <<'EOF'
[Service]
ExecStart=
ExecStart=/opt/CCTV_RELAY/mediamtx /var/lib/bima2-cctv/mediamtx.yml
EOF
cat > /etc/systemd/system/bima2-next.service.d/cctv-manager.conf <<'EOF'
[Service]
EnvironmentFile=/opt/BIMA2_NEXT/cctv-admin.env
ReadWritePaths=/var/lib/bima2-cctv
EOF
systemctl daemon-reload
systemctl restart cctv-relay.service
if ! curl -fsS --retry 5 --retry-connrefused --retry-delay 1 http://127.0.0.1:9997/v3/paths/list >/dev/null; then
 rm /etc/systemd/system/cctv-relay.service.d/manager.conf
 systemctl daemon-reload
 systemctl restart cctv-relay.service
 exit 1
fi
systemctl restart bima2-next.service
curl -fsS --retry 30 --retry-connrefused --retry-delay 2 http://127.0.0.1:8766/api/status >/dev/null
# Check protected endpoint without printing credentials.
code=$(curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:8766/api/inspection/cctv)
test "$code" = 401
echo 'CCTV manager enabled; admin token in /opt/BIMA2_NEXT/cctv-admin.env'
systemctl is-active cctv-relay.service bima2-next.service bima2-ais.service bima2-ais-gdrive.timer
