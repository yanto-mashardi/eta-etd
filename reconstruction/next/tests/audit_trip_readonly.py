"""One-off, read-only diagnosis of short turnaround or fragmented trips.
Run with PYTHONPATH pointing to deployed app. Never modifies service, journal,
archives or cache. Reads only the selected AIS dates, streams observations.
"""
import argparse,json
from datetime import datetime,timedelta
from pathlib import Path
from trajectories import records,normalize,WIB
from events import dt,canonical_mmsi
from evaluation import row_start

def main():
    p=argparse.ArgumentParser()
    p.add_argument("--root",default="/opt/BIMA2_NEXT")
    p.add_argument("--ais",default="/opt/JAES_SIMULASI_BIMA2/data/01_DATA_SOURCE/AIS/realtime/ais_realtime.csv")
    p.add_argument("--mmsi",required=True)
    p.add_argument("--start",required=True,help="ISO date/time with offset")
    p.add_argument("--end",required=True,help="ISO date/time with offset")
    a=p.parse_args();start,end=dt(a.start),dt(a.end)
    if not start<end or end-start>timedelta(hours=3):p.error("Select at most three hours")
    state=json.loads((Path(a.root)/"data/events_state.json").read_text())
    print("=== JOURNAL (UTC timestamps; intersecting interval) ===")
    fields="trip_id origin_port destination_port status record_type D0_utc ATA etd_real eta_corrected etd_early etd_arrival early_published_at arrival_published_at arrival_berth event_qc_flags prediction_status_early prediction_status_arrival prediction_error_early prediction_error_arrival last_fix_utc".split()
    for r in sorted(state.get("trip_monitor",{}).values(),key=lambda r:dt(row_start(r))):
        if str(r["mmsi"])!=a.mmsi:continue
        lo=dt(row_start(r));hi=dt(r.get("etd_real") or r.get("last_fix_utc") or row_start(r))
        if lo<=end and hi>=start:print(json.dumps({k:r.get(k) for k in fields},ensure_ascii=False))
    print("=== LAST TRACKER STATE ===")
    v=state.get("vessels",{}).get(a.mmsi,{})
    print(json.dumps({k:v.get(k) for k in ("status","last","voyage","stop")},ensure_ascii=False))
    print("=== AIS OBSERVATIONS (WIB; distance to nearest berth in NM) ===")
    groups={};conflicts=set()
    day=start.astimezone(WIB).date()
    while day<=end.astimezone(WIB).date():
        for r,rx in records(Path(a.ais),day):
            if canonical_mmsi(r.get("mmsi",r.get("immsi","")))!=a.mmsi:continue
            x=normalize(r,rx,day)
            if not x or not start<=dt(x["ts"])<=end:continue
            key=x["ts"]; signature=(x["lat"],x["lon"],x["sog"])
            if key in groups and groups[key][0]!=signature:conflicts.add(key)
            elif key not in groups:groups[key]=(signature,x,r.get("ais_update_at") or r.get("updated_at") or r.get("update_at"))
        day+=timedelta(days=1)
    print("WIB | lat | lon | SOG | port | berth | dist_NM | phase | source_update (if present)")
    for key,(_,x,source) in sorted(groups.items(),key=lambda k:dt(k[0])):
        phase="CONFLICT" if key in conflicts else "SANDAR" if x["candidate"] else "MANUVER" if x["distance"]<=.15 else "OUTSIDE"
        print(f'{dt(key).astimezone(WIB):%H:%M:%S.%f} | {x["lat"]:.6f} | {x["lon"]:.6f} | {x["sog"]:.2f} | {x["port"]} | {x["berth"]} | {x["distance"]:.4f} | {phase} | {source or "-"}')
    print("Observations:",len(groups),"conflicting timestamps:",len(conflicts))
if __name__=="__main__":main()
