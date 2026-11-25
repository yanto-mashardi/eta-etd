"""Campus sender: replay durable local daily CSV, including closed-day final counts.
No changes to CCTV archive. Requires HTTPS and explicit observed source.
"""
import argparse,csv,json,os,time,urllib.request
from pathlib import Path
from datetime import date,timedelta
from zoneinfo import ZoneInfo
from datetime import datetime
def send(url,token,port,state):
    req=urllib.request.Request(url.rstrip("/")+"/api/vehicles/"+port,data=json.dumps({"mode":"OBSERVED","state":state}).encode(),headers={"Content-Type":"application/json","Authorization":"Bearer "+token},method="POST")
    with urllib.request.urlopen(req,timeout=15) as r:
        if not json.load(r).get("accepted"):raise RuntimeError("Not accepted")
def main():
    p=argparse.ArgumentParser();p.add_argument("--observed-root",required=True);p.add_argument("--url",required=True);p.add_argument("--since",required=True);a=p.parse_args()
    if not a.url.startswith("https://"):raise SystemExit("HTTPS required")
    token=os.environ["BIMA2_VEHICLE_TOKEN"];root=Path(a.observed_root);since=date.fromisoformat(a.since)
    # Replay all daily snapshots on startup, then only changed rows plus heartbeat.
    sent={};last={}
    while True:
        try:
            for port in ("bengkalis","pakning"):
                for f in sorted((root/"daily"/port).glob("????-??-??.csv")):
                    if date.fromisoformat(f.stem)<since:continue
                    with f.open(newline="",encoding="utf-8-sig") as fp:rows=list(csv.DictReader(fp))
                    key=(port,f.stem);n=sent.get(key,0)
                    for row in rows[n:]:
                        state=dict(tanggal=f.stem,jam=row["jam"],jumlah_mobil=int(row["jumlah_mobil"]),jumlah_motor=int(row["jumlah_motor"]))
                        send(a.url,token,port,state);n+=1;sent[key]=n;last[port]=state
                if port in last:send(a.url,token,port,last[port])
        except Exception as e:print("Retry:",type(e).__name__,flush=True)
        time.sleep(10)
if __name__=="__main__":main()
