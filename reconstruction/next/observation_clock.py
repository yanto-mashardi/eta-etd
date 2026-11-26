"""Resolve provider observation changes without inventing fix timestamps."""
from events import dt

def resolve(p,raw,previous,now):
    p=dict(p)
    source=dt(p["ts"])
    p["source_fix_utc"]=source.isoformat()
    p["clock_basis"]="AIS_UPDATE"
    if not previous:return p
    last=dt(previous["ts"])
    last_source=dt(previous.get("source_fix_utc",previous["ts"]))
    if source<last_source:return None
    changed=any(p.get(k)!=previous.get(k) for k in ("latitude","longitude","sog","cog"))
    if source==last_source and not changed:return None
    if source>last and source>last_source:return p
    # A new payload may share an AIS update timestamp. Use the existing
    # provider observation timestamp, never server poll time or +epsilon.
    try: observation=dt(raw["timestamp"])
    except (ValueError,TypeError,KeyError):return None
    if not (observation>last and source<=observation<=now and (now-observation).total_seconds()<=300):return None
    p["ts"]=observation.isoformat()
    p["clock_basis"]="PROVIDER_OBSERVATION"
    return p
