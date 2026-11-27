"""Official YOLO CSV sender. Read-only local spool; never modify archive."""
import argparse,csv,json,os,time,urllib.request,urllib.parse
from pathlib import Path
from datetime import datetime,timezone
from zoneinfo import ZoneInfo
WIB=ZoneInfo("Asia/Jakarta")
def req(url,token,body=None):
    headers={"Authorization":"Bearer "+token}
    if body is not None:headers["Content-Type"]="application/json"
    with urllib.request.urlopen(urllib.request.Request(url,headers=headers,data=json.dumps(body).encode() if body is not None else None),timeout=15) as r:return json.load(r)
def main():
    p=argparse.ArgumentParser();p.add_argument("--observed-root",required=True);p.add_argument("--url",required=True);p.add_argument("--preview-url",default="http://127.0.0.1:8765");a=p.parse_args()
    if not a.url.startswith("https://"):raise SystemExit("HTTPS required")
    device=os.environ["BIMA2_YOLO_DEVICE"];root=Path(a.observed_root);base=a.url.rstrip("/")
    while True:
        for port in ("bengkalis","pakning"):
            token=os.environ.get("BIMA2_YOLO_TOKEN_"+port.upper())
            if not token:continue
            try:
                endpoint=base+"/api/vehicles/"+port
                progress=req(endpoint+"/resume?"+urllib.parse.urlencode({"device":device}),token)
                cutoff=datetime.fromisoformat(progress["cutoff"]);last=datetime.fromisoformat(progress["last_ts"]) if progress["last_ts"] else None
                latest=None
                for f in sorted((root/"daily"/port).glob("????-??-??.csv")):
                    if f.stem<cutoff.astimezone(WIB).date().isoformat():continue
                    with f.open(newline="",encoding="utf-8-sig") as fp:
                        for row in csv.DictReader(fp):
                            if any(row.get(k) in (None,"") for k in ("jam","jumlah_mobil","jumlah_motor")):continue
                            ts=datetime.fromisoformat(f.stem+"T"+row["jam"]).replace(tzinfo=WIB)
                            state=dict(tanggal=f.stem,jam=row["jam"],jumlah_mobil=int(row["jumlah_mobil"]),jumlah_motor=int(row["jumlah_motor"]))
                            latest=state
                            if ts>=cutoff and (last is None or ts>last):
                                req(endpoint,token,{"mode":"OBSERVED","device":device,"state":state});last=ts
                # Heartbeat reflects actual local frame processing, not a stale CSV alone.
                with urllib.request.urlopen(a.preview_url.rstrip("/")+"/status?port="+port,timeout=3) as f: health=json.load(f)
                if health.get("status")=="ONLINE" and latest and latest["tanggal"]==datetime.now(WIB).date().isoformat():
                    # current snapshot at time of observation; subsequent genuine crossings follow.
                    # Use last real accepted snapshot only, do not manufacture later event timestamps.
                    ts=datetime.fromisoformat(latest["tanggal"]+"T"+latest["jam"]).replace(tzinfo=WIB)
                    if last is not None and ts==last:
                        req(endpoint,token,{"mode":"OBSERVED","device":device,"state":latest})
                    elif last is None and ts<cutoff:
                        print(port,"Waiting for first observed crossing after handover",flush=True)
            except Exception as e:print(port,"Retry:",type(e).__name__,flush=True)
        time.sleep(10)
if __name__=="__main__":main()
