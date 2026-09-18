"""Build ML2 turnaround-correction training data for BIMA2 Year-2 method alignment."""
from __future__ import annotations
import json, math, os, sys
from pathlib import Path
import numpy as np, pandas as pd, yaml

ROOT=Path(__file__).resolve().parents[2]
PROJ=yaml.safe_load((ROOT/'config/project_config.yaml').read_text(encoding='utf-8')) or {}
CFG=PROJ['ml2']; TZ=PROJ.get('timezone','Asia/Jakarta')
AIS_HISTORY=ROOT/CFG['historical_ais_source']; VEH_HISTORY=ROOT/CFG['historical_vehicle_source']; CCTV_HISTORY=ROOT/CFG['cctv_history_source']
_run=os.getenv('LOCAL_RUN_RUN_ROOT','').strip(); PROCESSED=(Path(_run)/'data_processed' if _run else ROOT/'data/processed')/'ml2'; PROCESSED.mkdir(parents=True,exist_ok=True)
CAPACITY_CSV=ROOT/PROJ['vessels']['capacity_master']; MOTOR_PCE=float(PROJ.get('queue',{}).get('motorcycle_pce',0.25))
RADIUS=float(CFG.get('berth_radius_nm',0.15)); MAX_SOG=float(CFG.get('berth_max_sog_kn',0.8)); MIN_TA=float(CFG.get('min_turnaround_min',3)); MAX_TA=float(CFG.get('max_turnaround_min',180))
WINDOW=PROJ.get('research',{}).get('operational_holdout',{}); WIN_START=str(WINDOW.get('service_window_start','07:00')); WIN_END=str(WINDOW.get('service_window_end','23:55'))
BERTHS={b['id']:(p,float(b['lat']),float(b['lon'])) for p,item in PROJ['ports'].items() for b in item['berths']}
ALIASES={'timestamp':['created_at','timestamp','time','datetime','date_time','basedatetime','base_datetime','dt'],'mmsi':['mmsi','vessel_id','ship_id'],'lat':['lat','latitude','y'],'lon':['lon','lng','longitude','x'],'sog':['sog','speed','speed_over_ground','speed_knots']}

def hav(a,b,c,d):
    R=3440.065;p1,p2=math.radians(a),math.radians(c);dp,dl=math.radians(c-a),math.radians(d-b);x=math.sin(dp/2)**2+math.cos(p1)*math.cos(p2)*math.sin(dl/2)**2;return 2*R*math.asin(math.sqrt(x))
def read_table(p):
    if p.suffix.lower()=='.csv':return pd.read_csv(p)
    if p.suffix.lower() in ('.xlsx','.xls'):return pd.read_excel(p)
    if p.suffix.lower()=='.parquet':return pd.read_parquet(p)
def norm(df):return {str(c).strip().lower().replace(' ','_'):c for c in df.columns}
def resolve(df,names):
    m=norm(df)
    for n in names:
        if n in m:return m[n]
def service_ok(ts):
    local=ts.tz_convert(TZ); sh,sm=map(int,WIN_START.split(':'));eh,em=map(int,WIN_END.split(':'));v=local.hour*60+local.minute;return sh*60+sm<=v<=eh*60+em
def normalize_terminal(v):
    s=str(v).upper(); return 'BENGKALIS' if 'BENG' in s or 'BKS' in s else 'PAKNING' if 'PAK' in s or 'PKG' in s else s
def normalize_ais(df):
    c={k:resolve(df,v) for k,v in ALIASES.items()}; missing=[k for k,v in c.items() if v is None]
    if missing:raise ValueError('AIS columns missing: '+','.join(missing))
    z=pd.DataFrame({k:df[v] for k,v in c.items()}); z.timestamp=pd.to_datetime(z.timestamp,errors='coerce',utc=True); z.mmsi=pd.to_numeric(z.mmsi,errors='coerce').astype('Int64')
    for x in ['lat','lon','sog']:z[x]=pd.to_numeric(z[x],errors='coerce')
    z=z.dropna(subset=['timestamp','mmsi','lat','lon','sog']);z=z[z.lat.between(-90,90)&z.lon.between(-180,180)];z.mmsi=z.mmsi.astype('int64').astype(str);return z.sort_values(['mmsi','timestamp'])
def load_all_ais():
    paths=[]; override=os.getenv('BIMA2_ML2_AIS_INPUT_FILE','').strip()
    if override:paths=[Path(override)]
    else:
        for ext in ('*.csv','*.xlsx','*.xls','*.parquet'):paths+=list(AIS_HISTORY.rglob(ext)) if AIS_HISTORY.exists() else []
    frames=[];src=[];skip=[]
    for p in sorted(set(paths)):
        try:d=read_table(p);z=normalize_ais(d);frames.append(z);src.append({'file':str(p),'rows':len(z)})
        except Exception as e:skip.append({'file':str(p),'reason':str(e)})
    if not frames:raise RuntimeError('No compatible AIS history')
    d=pd.concat(frames,ignore_index=True).drop_duplicates(['timestamp','mmsi','lat','lon','sog']).sort_values(['mmsi','timestamp']);return d,src,skip
def nearest(lat,lon):
    dist,bid=min((hav(lat,lon,xy[1],xy[2]),bid) for bid,xy in BERTHS.items()); return bid,BERTHS[bid][0],dist
def extract_turnarounds(ais):
    rows=[]
    for m,g in ais.groupby('mmsi',sort=False):
        active=None
        for r in g.itertuples(index=False):
            bid,terminal,dist=nearest(float(r.lat),float(r.lon));berthed=dist<=RADIUS and float(r.sog)<=MAX_SOG;ts=r.timestamp
            if active is None:
                if berthed:active={'berth':bid,'terminal':terminal,'arrival':ts}
            elif berthed and bid==active['berth']:
                pass
            else:
                dur=(ts-active['arrival']).total_seconds()/60
                if MIN_TA<=dur<=MAX_TA and service_ok(active['arrival']):rows.append({'trip_id':f"AIS_TA_{m}_{active['arrival'].strftime('%Y%m%d%H%M%S')}",'date':active['arrival'].tz_convert(TZ).date(),'arrival_timestamp':active['arrival'],'departure_timestamp':ts,'mmsi':str(m),'terminal':active['terminal'],'berth':active['berth'],'turnaround_actual_min':dur})
                active={'berth':bid,'terminal':terminal,'arrival':ts} if berthed else None
    out=pd.DataFrame(rows)
    if out.empty:raise RuntimeError('No valid AIS berth turnaround events')
    local=pd.to_datetime(out.arrival_timestamp,utc=True).dt.tz_convert(TZ);out['arrival_hour']=local.dt.hour;out['arrival_dow']=local.dt.dayofweek;out['minute_of_day']=local.dt.hour*60+(local.dt.minute//5)*5;return out.sort_values('arrival_timestamp').reset_index(drop=True)
def load_profiles_and_observed():
    files=[]
    for base in [VEH_HISTORY,CCTV_HISTORY]:
        for ext in ('*.csv','*.xlsx','*.xls','*.parquet'):files+=list(base.rglob(ext)) if base.exists() else []
    profiles=[];observed=[];src=[];skip=[]
    for p in sorted(set(files)):
        try:
            # Project manifest workbook: build a 5-minute historical demand profile from sheet 07_SIM_5MIN.
            if p.suffix.lower() in ('.xlsx','.xls'):
                try:
                    xls=pd.ExcelFile(p)
                    if '07_SIM_5MIN' in xls.sheet_names:
                        q=pd.read_excel(p,sheet_name='07_SIM_5MIN',header=2)
                        if {'Timestamp','Car arrival BKS','Motor arrival BKS','Car arrival PKG','Motor arrival PKG'}.issubset(q.columns):
                            ts=pd.to_datetime(q['Timestamp'],errors='coerce')
                            dow=ts.dt.dayofweek; minute=ts.dt.hour*60+(ts.dt.minute//5)*5
                            for term,cc,mc in [('BENGKALIS','Car arrival BKS','Motor arrival BKS'),('PAKNING','Car arrival PKG','Motor arrival PKG')]:
                                z=pd.DataFrame({'terminal':term,'arrival_dow':dow,'minute_of_day':minute,'predicted_car_5min':pd.to_numeric(q[cc],errors='coerce'),'predicted_motor_5min':pd.to_numeric(q[mc],errors='coerce')}).dropna()
                                z['predicted_pce_5min']=z.predicted_car_5min+MOTOR_PCE*z.predicted_motor_5min
                                profiles.append(z);src.append({'file':str(p),'kind':'PROJECT_MANIFEST_07_SIM_5MIN','rows':len(z),'terminal':term})
                            continue
                except Exception:
                    pass
            d=read_table(p);m=norm(d)
            # profile: terminal + dow + minute + car/motor counts/rates
            tkey=next((x for x in ['terminal','port','origin_port'] if x in m),None); dow=next((x for x in ['arrival_dow','day_of_week','dow'] if x in m),None); minute=next((x for x in ['minute_of_day','time_bin_minute'] if x in m),None)
            car=next((x for x in ['predicted_car_5min','car_rate_5min','car_in','car_count','cars'] if x in m),None); motor=next((x for x in ['predicted_motor_5min','motor_rate_5min','motor_in','motor_count','motorcycles'] if x in m),None)
            if all([tkey,dow,minute,car,motor]):
                z=pd.DataFrame({'terminal':d[m[tkey]].map(normalize_terminal),'arrival_dow':pd.to_numeric(d[m[dow]],errors='coerce'),'minute_of_day':pd.to_numeric(d[m[minute]],errors='coerce'),'predicted_car_5min':pd.to_numeric(d[m[car]],errors='coerce'),'predicted_motor_5min':pd.to_numeric(d[m[motor]],errors='coerce')}).dropna();z['predicted_pce_5min']=z.predicted_car_5min+MOTOR_PCE*z.predicted_motor_5min;profiles.append(z);src.append({'file':str(p),'kind':'HISTORICAL_PROFILE','rows':len(z)});continue
            tskey=next((x for x in ['timestamp_5min','timestamp','time','datetime'] if x in m),None);tkey=next((x for x in ['terminal','port'] if x in m),None);car=next((x for x in ['observed_car_5min','car_rate_5min','car_in','car_arrival_5min'] if x in m),None);motor=next((x for x in ['observed_motor_5min','motor_rate_5min','motor_in','motor_arrival_5min'] if x in m),None)
            if all([tskey,tkey,car,motor]):
                z=pd.DataFrame({'timestamp':pd.to_datetime(d[m[tskey]],errors='coerce'),'terminal':d[m[tkey]].map(normalize_terminal),'observed_car_5min':pd.to_numeric(d[m[car]],errors='coerce'),'observed_motor_5min':pd.to_numeric(d[m[motor]],errors='coerce')}).dropna();z.timestamp=z.timestamp.dt.tz_localize(TZ) if z.timestamp.dt.tz is None else z.timestamp.dt.tz_convert(TZ);z['observed_pce_5min']=z.observed_car_5min+MOTOR_PCE*z.observed_motor_5min;observed.append(z);src.append({'file':str(p),'kind':'OBSERVED_5MIN','rows':len(z)});continue
            raise ValueError('not recognized profile/observation')
        except Exception as e:skip.append({'file':str(p),'reason':str(e)})
    return (pd.concat(profiles,ignore_index=True) if profiles else pd.DataFrame()),(pd.concat(observed,ignore_index=True) if observed else pd.DataFrame()),src,skip
def capacities():
    d=pd.read_csv(CAPACITY_CSV);return {str(int(float(r.mmsi))):float(r.capacity_pce) for _,r in d.iterrows()}
def pair(events,profiles,observed):
    cap=capacities();lookup={}
    if not profiles.empty:
        pg=profiles.groupby(['terminal','arrival_dow','minute_of_day'],as_index=False)[['predicted_car_5min','predicted_motor_5min','predicted_pce_5min']].mean();lookup={(r.terminal,int(r.arrival_dow),int(r.minute_of_day)):(r.predicted_car_5min,r.predicted_motor_5min,r.predicted_pce_5min) for r in pg.itertuples()}
    rows=[]
    for e in events.to_dict('records'):
        pred=lookup.get((e['terminal'],int(e['arrival_dow']),int(e['minute_of_day'])))
        if pred is None:continue
        local=pd.Timestamp(e['arrival_timestamp']).tz_convert(TZ);obs=None
        if not observed.empty:
            c=observed[observed.terminal.eq(e['terminal'])].copy()
            if not c.empty:
                delta=(c.timestamp-local).abs();idx=delta.idxmin()
                if delta.loc[idx]<=pd.Timedelta(minutes=7.5):r=c.loc[idx];obs=(float(r.observed_car_5min),float(r.observed_motor_5min),float(r.observed_pce_5min))
        if obs is None:obs=pred
        capacity=cap.get(str(e['mmsi']),np.nan); ratio=float(pred[2])/capacity if pd.notna(capacity) and capacity>0 else np.nan
        e.update({'capacity_pce':capacity,'predicted_car_5min':pred[0],'predicted_motor_5min':pred[1],'predicted_pce_5min':pred[2],'observed_car_5min':obs[0],'observed_motor_5min':obs[1],'observed_pce_5min':obs[2],'demand_capacity_ratio':ratio,'low_demand_flag':int(pd.notna(ratio) and ratio<float(CFG.get('behavioral_rule',{}).get('low_demand_ratio_threshold',0.35)))})
        rows.append(e)
    out=pd.DataFrame(rows)
    if out.empty:raise RuntimeError('No ML2 events paired with demand profile')
    return out.sort_values('arrival_timestamp').reset_index(drop=True)
def main():
    ais,ais_src,ais_skip=load_all_ais();events=extract_turnarounds(ais);profiles,observed,src,skip=load_profiles_and_observed();dataset=pair(events,profiles,observed);out=PROCESSED/'turnaround_training_dataset.csv';dataset.to_csv(out,index=False)
    # publish historical profile used later by realtime inference
    if not profiles.empty:
        hist=ROOT/PROJ['integration']['historical_demand_profile'];hist.parent.mkdir(parents=True,exist_ok=True);profiles.groupby(['terminal','arrival_dow','minute_of_day'],as_index=False)[['predicted_car_5min','predicted_motor_5min','predicted_pce_5min']].mean().to_csv(hist,index=False)
    prov={'target_source':'AIS_TERMINAL_BERTH_TURNAROUND','arrival_definition':'terminal_berth_arrival','feature_source':'HISTORICAL_DEMAND_PLUS_CCTV_OBSERVATION','ais_sources':ais_src,'ais_skipped':ais_skip,'demand_sources':src,'demand_skipped':skip,'turnaround_events':len(events),'paired_rows':len(dataset)};(PROCESSED/'source_provenance.json').write_text(json.dumps(prov,indent=2,default=str),encoding='utf-8');print(json.dumps(prov,indent=2));print('output=',out)
if __name__=='__main__':main()
