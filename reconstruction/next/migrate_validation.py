"""Root-only migration of active MediaMTX JSON; preserve live paths and credentials."""
import json,os,secrets,tempfile,copy
from pathlib import Path
from urllib.request import urlopen
import time
PORTS=("bengkalis","pakning")
def migrate(cfg):
    c=copy.deepcopy(cfg)
    assert c["authMethod"]=="internal"
    live={"live/"+p for p in PORTS};val={"validation/"+p for p in PORTS}
    assert set(c["paths"]) in (live,live|val)
    users=c["authInternalUsers"]
    existing=next((u for u in users if u["user"]=="validation_relay"),None)
    password=existing["pass"] if existing else secrets.token_hex(32)
    # Do not silently change unexpected permissions.
    for u in users:
        if u["user"]=="campus_validation":
            assert all(x["action"]=="read" and x["path"] in live|val for x in u["permissions"])
            for x in u["permissions"]:x["path"]="validation/"+x["path"].split("/")[-1]
        elif u["user"]!="validation_relay":
            assert not any(x.get("action")=="read" and (not x.get("path") or x.get("path","").startswith("~") or x.get("path") in val) for x in u.get("permissions",[])), "Unexpected broad reader permission"
    c["authInternalUsers"]=[u for u in users if u["user"]!="validation_relay"]+[{"user":"validation_relay","pass":password,"ips":["127.0.0.1"],"permissions":[{"action":"read","path":"live/"+p} for p in PORTS]}]
    for p in PORTS:
        c["paths"]["validation/"+p]={"source":"rtsp://validation_relay:"+password+"@127.0.0.1:8554/live/"+p,"sourceOnDemand":True,"sourceOnDemandStartTimeout":"10s","sourceOnDemandCloseAfter":"5s","rtspTransport":"tcp","record":False}
    return c
def replace(path,data):
    st=path.stat();fd,tmp=tempfile.mkstemp(dir=path.parent)
    try:
        with os.fdopen(fd,"w") as f:
            os.fchown(f.fileno(),st.st_uid,st.st_gid);os.fchmod(f.fileno(),0o640);json.dump(data,f,indent=2);f.flush();os.fsync(f.fileno())
        os.replace(tmp,path)
    finally:
        if os.path.exists(tmp):os.unlink(tmp)
def main():
    assert os.geteuid()==0
    path=Path("/var/lib/bima2-cctv/mediamtx.yml")
    old=json.loads(path.read_text());new=migrate(old)
    if new==old:print("Already migrated");return
    backup=Path("/opt/BIMA2_NEXT/mediamtx.pre-validation.json")
    if not backup.exists():
        fd=os.open(backup,os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600)
        with os.fdopen(fd,"w") as f:json.dump(old,f)
    replace(path,new)
    try:
        for _ in range(30):
            time.sleep(.5)
            try:
                with urlopen("http://127.0.0.1:9997/v3/config/paths/list",timeout=2) as f:data=json.load(f)
                items={x["name"]:x for x in data["items"]}
                if all(items.get("validation/"+p,{}).get("sourceOnDemand") is True for p in PORTS):
                    print("Validation paths active");return
            except (OSError,ValueError,KeyError):pass
        raise RuntimeError("Hot reload not verified")
    except Exception:
        replace(path,old)
        raise
if __name__=="__main__":main()
