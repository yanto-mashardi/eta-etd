"""Local operator CLI. No public stock/load modification endpoint."""
import argparse,json,os
from pathlib import Path
from stockflow import Ledger
p=argparse.ArgumentParser();p.add_argument("--root",default=os.getenv("BIMA2_NEXT_ROOT","/opt/BIMA2_NEXT"))
s=p.add_subparsers(dest="cmd",required=True)
a=s.add_parser("opening");a.add_argument("port");a.add_argument("timestamp");a.add_argument("car",type=int);a.add_argument("motor",type=int);a.add_argument("counter_car",type=int);a.add_argument("counter_motor",type=int)
b=s.add_parser("load");b.add_argument("event_id");b.add_argument("car",type=int);b.add_argument("motor",type=int);b.add_argument("source",choices=["ACTUAL","ESTIMATED"])
c=s.add_parser("status");c.add_argument("port")
x=p.parse_args();l=Ledger(Path(x.root)/"data"/"stockflow.sqlite")
if x.cmd=="opening":l.set_opening(x.port,x.timestamp,x.car,x.motor,x.counter_car,x.counter_motor)
elif x.cmd=="load":l.set_load(x.event_id,x.car,x.motor,x.source)
else:print(json.dumps(l.snapshot(x.port),indent=2))
