from __future__ import annotations
import json, os, time
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo
import mysql.connector
import yaml

TZ = ZoneInfo('Asia/Jakarta')
ROOT = Path(__file__).resolve().parents[2]
CFG_PATH = ROOT / 'config' / 'database' / 'mysql_config.yaml'
VEHICLE_PATH = ROOT / 'data' / '01_DATA_SOURCE' / 'CCTV' / 'output' / 'vehicle_state.json'
STATE_PATH = ROOT / 'outputs' / 'realtime' / 'current_operation_state.json'
QUEUE_LEDGER_PATH = ROOT / 'outputs' / 'realtime' / 'queue_service_state.json'
QUEUE_EVENTS_PATH = ROOT / 'outputs' / 'realtime' / 'queue_service_events.jsonl'

def cfg():
    with CFG_PATH.open('r', encoding='utf-8') as f:
        return yaml.safe_load(f)

def db_connect(c):
    d = c['database']
    return mysql.connector.connect(
        host=os.getenv(d['host_env'], d.get('default_host','127.0.0.1')),
        port=int(os.getenv(d['port_env'], d.get('default_port',3306))),
        database=os.getenv(d['name_env'], d.get('default_name','jaes_bima2')),
        user=d.get('default_user','root'), password=os.environ[d['password_env']], autocommit=True)

def now_local(): return datetime.now(TZ).replace(tzinfo=None)
def read_json(path):
    try: return json.loads(path.read_text(encoding='utf-8'))
    except Exception: return None

def parse_dt(v):
    if not v: return None
    try:
        return datetime.fromisoformat(str(v).replace('Z','+00:00')).astimezone(TZ).replace(tzinfo=None)
    except Exception: return None

def _int(v):
    try: return int(float(v or 0))
    except Exception: return 0

def effective_port_state(state, port):
    key='vehicle_bengkalis' if port=='BENGKALIS' else 'vehicle_pakning'
    s=(state or {}).get(key) or {}
    if port=='BENGKALIS' and not s:
        s=read_json(VEHICLE_PATH) or {}
    return s

def ensure_daily_tables(cur):
    cur.execute('''CREATE TABLE IF NOT EXISTS queue_service_event (
      id BIGINT AUTO_INCREMENT PRIMARY KEY,
      event_id VARCHAR(255) NOT NULL UNIQUE,
      occurred_at DATETIME(3) NOT NULL,
      port VARCHAR(50) NOT NULL,
      mmsi BIGINT NOT NULL, vessel_name VARCHAR(150),
      capacity_pce DOUBLE DEFAULT 0,
      queue_car_before INT DEFAULT 0, queue_motor_before INT DEFAULT 0,
      loaded_car INT DEFAULT 0, loaded_motor INT DEFAULT 0, loaded_pce DOUBLE DEFAULT 0,
      queue_car_after INT DEFAULT 0, queue_motor_after INT DEFAULT 0,
      created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
      KEY idx_qse_day_port (occurred_at,port)
    )''')
    cur.execute('''CREATE TABLE IF NOT EXISTS daily_port_summary (
      service_date DATE NOT NULL, port VARCHAR(50) NOT NULL,
      first_observed_at DATETIME(3) NOT NULL, last_observed_at DATETIME(3) NOT NULL,
      car_in_start BIGINT DEFAULT 0, motor_in_start BIGINT DEFAULT 0,
      car_out_start BIGINT DEFAULT 0, motor_out_start BIGINT DEFAULT 0,
      loaded_car_start BIGINT DEFAULT 0, loaded_motor_start BIGINT DEFAULT 0,
      departure_count_start BIGINT DEFAULT 0,
      car_in_last BIGINT DEFAULT 0, motor_in_last BIGINT DEFAULT 0,
      car_out_last BIGINT DEFAULT 0, motor_out_last BIGINT DEFAULT 0,
      loaded_car_last BIGINT DEFAULT 0, loaded_motor_last BIGINT DEFAULT 0,
      departure_count_last BIGINT DEFAULT 0,
      car_in_day BIGINT DEFAULT 0, motor_in_day BIGINT DEFAULT 0,
      car_out_day BIGINT DEFAULT 0, motor_out_day BIGINT DEFAULT 0,
      loaded_car_day BIGINT DEFAULT 0, loaded_motor_day BIGINT DEFAULT 0,
      departures_day BIGINT DEFAULT 0,
      queue_car_end INT DEFAULT 0, queue_motor_end INT DEFAULT 0,
      updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
      PRIMARY KEY(service_date,port)
    )''')

def record_cctv(cur, state):
    ts = now_local()
    for port in ('BENGKALIS','PAKNING'):
        s=effective_port_state(state,port)
        if not s: continue
        qcar=_int(s.get('car_queue_current',s.get('car_queue',0)))
        qmotor=_int(s.get('motor_queue_current',s.get('motor_queue',0)))
        camera=s.get('camera_id',f'cctv_{port.lower()}')
        cur.execute('''INSERT IGNORE INTO cctv_observation
          (observed_at,camera_id,port,car_queue,motor_queue,car_in_total,car_out_total,motor_in_total,motor_out_total,total_queue)
          VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)''',
          (ts,camera,s.get('port',port),qcar,qmotor,_int(s.get('car_in_total')),_int(s.get('car_out_total')),
           _int(s.get('motor_in_total')),_int(s.get('motor_out_total')),qcar+qmotor))

def record_service_events(cur):
    if not QUEUE_EVENTS_PATH.exists(): return
    try:
        lines=QUEUE_EVENTS_PATH.read_text(encoding='utf-8').splitlines()
    except Exception:
        return
    for line in lines[-5000:]:
        if not line.strip(): continue
        try: e=json.loads(line)
        except Exception: continue
        cur.execute('''INSERT IGNORE INTO queue_service_event
          (event_id,occurred_at,port,mmsi,vessel_name,capacity_pce,queue_car_before,queue_motor_before,loaded_car,loaded_motor,loaded_pce,queue_car_after,queue_motor_after)
          VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)''',
          (e.get('event_id'),parse_dt(e.get('occurred_at')) or now_local(),e.get('port'),_int(e.get('mmsi')),e.get('shipname'),
           float(e.get('capacity_pce') or 0),_int(e.get('queue_car_before')),_int(e.get('queue_motor_before')),
           _int(e.get('loaded_car')),_int(e.get('loaded_motor')),float(e.get('loaded_pce') or 0),
           _int(e.get('queue_car_after')),_int(e.get('queue_motor_after'))))

def upsert_daily_summary(cur,state):
    ts=now_local(); service_date=ts.date()
    for port in ('BENGKALIS','PAKNING'):
        s=effective_port_state(state,port)
        if not s: continue
        vals={
          'car_in':_int(s.get('car_in_total')),'motor_in':_int(s.get('motor_in_total')),
          'car_out':_int(s.get('car_out_total')),'motor_out':_int(s.get('motor_out_total')),
          'loaded_car':_int(s.get('loaded_car_total')),'loaded_motor':_int(s.get('loaded_motor_total')),
          'dep':_int(s.get('service_departure_count')),'qcar':_int(s.get('car_queue_current')),'qmotor':_int(s.get('motor_queue_current')),
        }
        cur.execute('''INSERT INTO daily_port_summary
          (service_date,port,first_observed_at,last_observed_at,
           car_in_start,motor_in_start,car_out_start,motor_out_start,loaded_car_start,loaded_motor_start,departure_count_start,
           car_in_last,motor_in_last,car_out_last,motor_out_last,loaded_car_last,loaded_motor_last,departure_count_last,
           car_in_day,motor_in_day,car_out_day,motor_out_day,loaded_car_day,loaded_motor_day,departures_day,queue_car_end,queue_motor_end)
          VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,0,0,0,0,0,0,0,%s,%s)
          ON DUPLICATE KEY UPDATE
            last_observed_at=VALUES(last_observed_at),
            car_in_last=VALUES(car_in_last),motor_in_last=VALUES(motor_in_last),
            car_out_last=VALUES(car_out_last),motor_out_last=VALUES(motor_out_last),
            loaded_car_last=VALUES(loaded_car_last),loaded_motor_last=VALUES(loaded_motor_last),
            departure_count_last=VALUES(departure_count_last),
            car_in_day=GREATEST(0,VALUES(car_in_last)-car_in_start),
            motor_in_day=GREATEST(0,VALUES(motor_in_last)-motor_in_start),
            car_out_day=GREATEST(0,VALUES(car_out_last)-car_out_start),
            motor_out_day=GREATEST(0,VALUES(motor_out_last)-motor_out_start),
            loaded_car_day=GREATEST(0,VALUES(loaded_car_last)-loaded_car_start),
            loaded_motor_day=GREATEST(0,VALUES(loaded_motor_last)-loaded_motor_start),
            departures_day=GREATEST(0,VALUES(departure_count_last)-departure_count_start),
            queue_car_end=VALUES(queue_car_end),queue_motor_end=VALUES(queue_motor_end)''',
          (service_date,port,ts,ts,vals['car_in'],vals['motor_in'],vals['car_out'],vals['motor_out'],vals['loaded_car'],vals['loaded_motor'],vals['dep'],
           vals['car_in'],vals['motor_in'],vals['car_out'],vals['motor_out'],vals['loaded_car'],vals['loaded_motor'],vals['dep'],vals['qcar'],vals['qmotor']))


def record_vessels(cur, state):
    if not state: return
    ts = now_local()
    for v in state.get('vessels', []):
        mmsi=v.get('mmsi')
        if not mmsi: continue
        current=v.get('current_port'); dest=v.get('destination_port')
        cur.execute('''INSERT IGNORE INTO ais_observation
          (observed_at,mmsi,vessel_name,lat,lon,sog,cog,heading,operational_state,nearest_port,nearest_berth,distance_to_berth_nm,freshness_status,source_updated_at)
          VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)''',
          (ts,int(mmsi),v.get('shipname'),v.get('latitude'),v.get('longitude'),v.get('sog'),v.get('cog'),v.get('heading'),
           v.get('operational_state'),current,v.get('nearest_berth'),v.get('berth_distance_nm'),v.get('freshness_status'),parse_dt(v.get('source_timestamp'))))
        cur.execute('''INSERT INTO prediction_history
          (predicted_at,mmsi,origin_port,destination_port,eta_base_min,eta_corrected_min,estimated_arrival_at,turnaround_base_min,turnaround_correction_min,estimated_departure_at,ml1_model_id,ml2_model_id)
          VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)''',
          (ts,int(mmsi),current,dest,v.get('eta_baseline_min'),v.get('eta_corrected_min'),parse_dt(v.get('eta_timestamp')),
           v.get('turnaround_base_min'),v.get('turnaround_correction_min'),parse_dt(v.get('etd_timestamp')),
           state.get('ml1_model_id'),state.get('ml2_model_id')))

def main():
    c=cfg(); interval=max(10,int(c['history_recorder'].get('interval_seconds',60)))
    print(f'MySQL history recorder active: every {interval}s')
    while True:
        try:
            state=read_json(STATE_PATH)
            cn=db_connect(c); cur=cn.cursor()
            ensure_daily_tables(cur)
            if c['history_recorder'].get('cctv_enabled',True): record_cctv(cur,state)
            if c['history_recorder'].get('ais_enabled',True) or c['history_recorder'].get('prediction_enabled',True): record_vessels(cur,state)
            record_service_events(cur)
            upsert_daily_summary(cur,state)
            cur.close(); cn.close()
        except Exception as e:
            print(f'[history-recorder] {type(e).__name__}: {e}')
        time.sleep(interval)

if __name__=='__main__': main()
