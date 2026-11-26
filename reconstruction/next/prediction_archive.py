"""Daily CSV archive. Root sync reads an atomic state snapshot; live worker prunes only verified closed date groups."""
import csv,json,hashlib,os,tempfile,subprocess,sys
from pathlib import Path
from datetime import datetime,timedelta
from collections import defaultdict
from events import dt
from evaluation import WIB,with_vtt
FIELDS="trip_id mmsi shipname origin_port destination_port status D0_utc arrival_berth departure_berth sog last_fix_utc eta_base eta_corrected eta_correction_min ATA vtt_early_min etd_early etd_arrival etd_real early_error_min arrival_error_min early_abs_error_min arrival_abs_error_min early_published_at arrival_published_at lead_advantage_min lead_to_departure_min release_early release_arrival vtt_conventional_min vtt_real_min vtt_early_base_min vtt_conventional_base_min vtt_early_correction_min vtt_conventional_correction_min eta_error_min event_quality event_qc_flags publication_protocol".split()
def groups(state):
    out=defaultdict(list)
    for r in state.get("trip_monitor",{}).values():
        out[dt(r["D0_utc"]).astimezone(WIB).date().isoformat()].append(r)
    return {k:sorted(v,key=lambda r:r["trip_id"]) for k,v in out.items()}
def fingerprint(rows):
    return hashlib.sha256(json.dumps(rows,sort_keys=True,separators=(",",":"),allow_nan=False).encode()).hexdigest()
def terminal(r):
    return r.get("status") in ("COMPLETED_QC_PASS","COMPLETED_QC_FAIL") or str(r.get("status","")).startswith("INCOMPLETE_")
def prune_verified(state,folder,today):
    cutoff=(today-timedelta(days=6)).isoformat()
    removed=0
    active={str(m)+"|"+dt(v["voyage"]["D0_utc"]).isoformat() for m,v in state.get("vessels",{}).items() if v.get("voyage")}
    for day,rows in groups(state).items():
        if day>=cutoff or any(not terminal(r) or r["trip_id"] in active or dt(r.get("etd_real") or r.get("last_fix_utc") or r["D0_utc"]).astimezone(WIB).date().isoformat()>=cutoff for r in rows):continue
        try: receipt=json.loads((folder/(day+".verified.json")).read_text())
        except (OSError,ValueError):continue
        if receipt.get("fingerprint")!=fingerprint(rows):continue
        for r in rows: del state["trip_monitor"][r["trip_id"]];removed+=1
    return removed
def atomic_file(path,writer):
    fd,tmp=tempfile.mkstemp(dir=path.parent,prefix=".tmp-")
    try:
        with os.fdopen(fd,"w",encoding="utf-8",newline="") as f:writer(f);f.flush();os.fsync(f.fileno())
        os.chmod(tmp,0o640);os.replace(tmp,path)
    finally:
        if os.path.exists(tmp):os.unlink(tmp)
def sync(root):
    folder=root/"data"/"prediction_archive"
    state=json.loads((root/"data"/"events_state.json").read_text())
    today=datetime.now(WIB).date();cutoff=(today-timedelta(days=6)).isoformat()
    grouped=groups(state)
    for day,rows in grouped.items():
        path=folder/("ETA_ETD_"+day+".csv")
        def write(f):
            w=csv.DictWriter(f,fieldnames=FIELDS,extrasaction="raise");w.writeheader();w.writerows(with_vtt(r) for r in rows)
        atomic_file(path,write)
        if day>=today.isoformat():continue
        remote="aisdrive:ETA_ETD_MONITORING/"+path.name
        receipt=folder/(day+".verified.json")
        fp=fingerprint(rows)
        sha=hashlib.sha256(path.read_bytes()).hexdigest()
        try: old=json.loads(receipt.read_text())
        except (OSError,ValueError):old={}
        if old.get("fingerprint")==fp and old.get("csv_sha256")==sha:continue
        cmd=["rclone","--config","/root/.config/rclone/rclone.conf"]
        subprocess.run(cmd+["copyto",str(path),remote,"--ignore-times"],check=True,timeout=180)
        remote_bytes=subprocess.check_output(cmd+["cat",remote],timeout=180)
        if hashlib.sha256(remote_bytes).hexdigest()!=sha:raise RuntimeError("Drive verification failed "+day)
        atomic_file(receipt,lambda f:json.dump({"fingerprint":fp,"csv_sha256":sha,"remote":remote},f))
        print("[VERIFIED]",day,len(rows),flush=True)
    # Prune local CSV only after live journal has already removed the verified group.
    for path in folder.glob("ETA_ETD_????-??-??.csv"):
        day=path.stem.removeprefix("ETA_ETD_")
        if day>=cutoff or day in grouped:continue
        receipt=folder/(day+".verified.json")
        try: info=json.loads(receipt.read_text())
        except (OSError,ValueError):continue
        if info.get("csv_sha256")==hashlib.sha256(path.read_bytes()).hexdigest():
            path.unlink();receipt.unlink()
if __name__=="__main__":sync(Path(sys.argv[1]))
