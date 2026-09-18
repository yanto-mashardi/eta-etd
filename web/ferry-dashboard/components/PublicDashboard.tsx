"use client";

import {useEffect,useMemo,useState} from "react";
import {Anchor,Car,Clock3,MapPinned,Ship,Signal} from "lucide-react";
import Topbar from "./Topbar";
import VesselMap from "./VesselMap";
import {getJSON} from "@/lib/api";
import type {CurrentState,Vessel,VehicleState} from "@/lib/types";

function fmtTime(v?:string|null){
  if(!v)return "—";
  try{return new Date(v).toLocaleTimeString("id-ID",{hour:"2-digit",minute:"2-digit"})}
  catch{return "—"}
}
function fmtSpeed(v?:number|null){return v==null||!Number.isFinite(Number(v))?"—":`${Number(v).toFixed(1)} kn`}
function fmtDistance(v?:number|null){return v==null||!Number.isFinite(Number(v))?"—":`${Number(v).toFixed(2)} nm`}
function queueValue(v:unknown){const x=Number(v);return Number.isFinite(x)?String(Math.max(0,Math.round(x))):"—"}
function otherPort(port:"BENGKALIS"|"PAKNING"){return port==="BENGKALIS"?"PAKNING":"BENGKALIS"}
function upper(v:any){return String(v||"").trim().toUpperCase()}

function isBerthAt(v:Vessel,port:"BENGKALIS"|"PAKNING"){
  return upper(v.operational_state)==="BERTHED" && upper(v.current_port)===port;
}
function isArrivalTo(v:Vessel,port:"BENGKALIS"|"PAKNING"){
  return upper(v.destination_port)===port && !isBerthAt(v,port);
}
function scheduledArrival(v:Vessel){
  const a=v as any;
  return a.scheduled_arrival_timestamp||a.planned_arrival_timestamp||a.schedule_arrival_timestamp||null;
}
function explicitArrivalStatus(v:Vessel){
  const a=v as any;
  const raw=a.arrival_status||a.schedule_status||a.punctuality_status;
  return raw?upper(raw).replaceAll("_"," "):"";
}
function arrivalStatus(v:Vessel){
  const explicit=explicitArrivalStatus(v);
  if(explicit)return explicit;
  const sched=scheduledArrival(v);
  if(!sched||!v.eta_timestamp)return "BELUM ADA JADWAL";
  const eta=new Date(v.eta_timestamp).getTime();
  const ref=new Date(sched).getTime();
  if(!Number.isFinite(eta)||!Number.isFinite(ref))return "BELUM ADA JADWAL";
  const delta=(eta-ref)/60000;
  if(delta>5)return `DELAY ${Math.round(delta)} MNT`;
  if(delta<-5)return `EARLY ${Math.abs(Math.round(delta))} MNT`;
  return "ON TIME";
}
function arrivalStatusClass(s:string){
  const x=upper(s);
  if(x.startsWith("DELAY"))return "delay";
  if(x.startsWith("EARLY"))return "early";
  if(x==="ON TIME")return "ontime";
  return "neutral";
}
function departureStatus(v:Vessel){
  const a=v as any;
  const explicit=a.departure_status||a.boarding_status;
  if(explicit)return upper(explicit).replaceAll("_"," ");
  if(isBerthAt(v,upper(v.current_port) as any))return "ESTIMASI BERANGKAT";
  return "—";
}

export default function PublicDashboard({port}:{port:"BENGKALIS"|"PAKNING"}){
  const [state,setState]=useState<CurrentState>({});
  const [err,setErr]=useState("");

  useEffect(()=>{
    let active=true;
    const load=async()=>{
      try{
        const s=await getJSON<CurrentState>(`/api/realtime/${port.toLowerCase()}`);
        if(active){setState(s);setErr("")}
      }catch(e:any){if(active)setErr(e?.message||"Data realtime tidak tersedia")}
    };
    load();
    const id=setInterval(load,5000);
    return()=>{active=false;clearInterval(id)};
  },[port]);

  const stateAny=state as any;
  const portVessels=state.vessels||[];
  const mapVessels:Vessel[]=stateAny.all_vessels||portVessels;
  const berthEntries=Object.entries(state.berths||{}).filter(([k])=>k.includes(port));
  const occupied=berthEntries.filter(([,v])=>v.status==="OCCUPIED").length;
  const vehicle:VehicleState=port==="BENGKALIS"?(state.vehicle_bengkalis||{}):(state.vehicle_pakning||{});
  const qCar=queueValue(vehicle.car_queue_current);
  const qMotor=queueValue(vehicle.motor_queue_current);
  const queueNote=vehicle.updated_at?`Update ${fmtTime(vehicle.updated_at)}`:(port==="PAKNING"?"CCTV Pakning belum aktif":"Menunggu CCTV");

  const arrivals=useMemo(()=>portVessels.filter(v=>isArrivalTo(v,port)).sort((a,b)=>{
    const ta=a.eta_timestamp?new Date(a.eta_timestamp).getTime():Number.MAX_SAFE_INTEGER;
    const tb=b.eta_timestamp?new Date(b.eta_timestamp).getTime():Number.MAX_SAFE_INTEGER;
    return ta-tb;
  }),[portVessels,port]);

  const departures=useMemo(()=>portVessels.filter(v=>isBerthAt(v,port)).sort((a,b)=>{
    const ta=a.etd_timestamp?new Date(a.etd_timestamp).getTime():Number.MAX_SAFE_INTEGER;
    const tb=b.etd_timestamp?new Date(b.etd_timestamp).getTime():Number.MAX_SAFE_INTEGER;
    return ta-tb;
  }),[portVessels,port]);

  return <div className="shell publicV11Shell">
    <Topbar active={port.toLowerCase()}/>
    <main className="publicV11Page">
      <header className="publicV11Hero">
        <div>
          <div className="eyebrow">Ferry Information Board</div>
          <h1>{port==="BENGKALIS"?"Bengkalis":"Pakning"} Ferry Terminal</h1>
          <p>Informasi terminal ini: kedatangan ke {port==="BENGKALIS"?"Bengkalis":"Pakning"}, keberangkatan dari terminal, posisi kapal, dan antrean kendaraan.</p>
        </div>
        <div className="publicV11Live"><span className="liveBadge"><span className="liveDot"/> LIVE</span><small>Update {fmtTime(state.generated_at)}</small></div>
      </header>

      {err&&<div className="error">{err}</div>}

      <section className="publicV11Quick">
        <div><Ship/><span>Kapal koridor</span><b>{mapVessels.length}</b><small>{arrivals.length} menuju terminal</small></div>
        <div><Anchor/><span>Dermaga terpakai</span><b>{occupied}/{berthEntries.length||2}</b><small>{departures.length} kapal sandar</small></div>
        <div className="queueKpi"><Car/><span>Mobil antre</span><b>{qCar}</b><small>{queueNote}</small></div>
        <div className="queueKpi"><Car/><span>Motor antre</span><b>{qMotor}</b><small>{queueNote}</small></div>
        <div><Signal/><span>AIS terakhir</span><b>{fmtTime(state.ais_updated_at)}</b><small>Bengkalis ↔ Pakning</small></div>
      </section>

      <section className="publicV11Main">
        <div className="card publicV11MapCard">
          <div className="publicV11SectionHead"><div><b>Peta Kapal Realtime</b><span>Nama kapal mengikuti ikon saat kapal bergerak</span></div><MapPinned size={18}/></div>
          <VesselMap vessels={mapVessels}/>
          <div className="publicV11Berths">
            {berthEntries.length?berthEntries.map(([name,b])=><div className={`publicV11Berth ${b.status==="OCCUPIED"?"occupied":"ready"}`} key={name}><span>{name.replace(`${port}_BERTH_`,"Dermaga ")}</span><b>{b.shipname||"AVAILABLE"}</b></div>):<div className="publicV11Berth ready"><span>Dermaga</span><b>Menunggu data</b></div>}
          </div>
        </div>

        <div className="publicV11Boards">
          <div className="card publicV11BoardCard">
            <div className="publicV11SectionHead boardHead"><div><b>Kedatangan ke {port==="BENGKALIS"?"Bengkalis":"Pakning"}</b><span>Kapal yang sedang menuju terminal ini</span></div><Clock3 size={18}/></div>
            <div className="publicV11ArrivalHeader"><span>Kapal</span><span>Dari</span><span>ETA</span><span>Kecepatan</span><span>Jarak</span><span>Status Kedatangan</span></div>
            {arrivals.length===0?<div className="publicV11Empty">Belum ada kapal yang sedang menuju terminal ini.</div>:arrivals.map(v=>{const st=arrivalStatus(v);return <div className="publicV11ArrivalRow" key={v.mmsi}><div className="publicV11Vessel"><span className="publicV11ShipDot"/><div><b>{v.shipname||`MMSI ${v.mmsi}`}</b><small>{v.mmsi}</small></div></div><span>{otherPort(port)}</span><b className="publicV11Time">{fmtTime(v.eta_timestamp)}</b><span>{fmtSpeed(v.sog)}</span><span>{fmtDistance(v.berth_distance_nm)}</span><span><em className={`publicV11Status ${arrivalStatusClass(st)}`}>{st}</em></span></div>})}
          </div>

          <div className="card publicV11BoardCard departureBoard">
            <div className="publicV11SectionHead boardHead"><div><b>Keberangkatan dari {port==="BENGKALIS"?"Bengkalis":"Pakning"}</b><span>Hanya kapal yang sedang berada di dermaga terminal ini</span></div><Ship size={18}/></div>
            <div className="publicV11DepartureHeader"><span>Kapal</span><span>Tujuan</span><span>ETD</span><span>Dermaga</span><span>Status</span></div>
            {departures.length===0?<div className="publicV11Empty">Tidak ada kapal yang sedang sandar untuk keberangkatan.</div>:departures.map(v=><div className="publicV11DepartureRow" key={v.mmsi}><div className="publicV11Vessel"><span className="publicV11ShipDot"/><div><b>{v.shipname||`MMSI ${v.mmsi}`}</b><small>{v.mmsi}</small></div></div><span>{otherPort(port)}</span><b className="publicV11Time">{fmtTime(v.etd_timestamp)}</b><span>{v.nearest_berth?.replace(`${port}_BERTH_`,"Dermaga ")||"—"}</span><span><em className="publicV11Status berth">{departureStatus(v)}</em></span></div>)}
          </div>
          <div className="publicV11Footnote">Status kedatangan ON TIME / DELAY / EARLY hanya dihitung bila tersedia jadwal referensi. Jika jadwal belum tersedia, sistem menampilkan “BELUM ADA JADWAL”, bukan status kualitas data. Detail CCTV, koreksi ML1/ML2, reliability, dan audit tersedia di Inspection.</div>
        </div>
      </section>
    </main>
  </div>
}
