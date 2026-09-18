"use client";

import {useEffect,useMemo,useState} from "react";
import {Anchor,Clock3,MapPinned,Ship,Signal} from "lucide-react";
import Topbar from "./Topbar";
import VesselMap from "./VesselMap";
import {getJSON} from "@/lib/api";
import type {CurrentState,Vessel} from "@/lib/types";

function fmtTime(v?:string|null){
  if(!v)return "—";
  try{return new Date(v).toLocaleTimeString("id-ID",{hour:"2-digit",minute:"2-digit"})}
  catch{return "—"}
}
function fmtSpeed(v?:number|null){return v==null||!Number.isFinite(Number(v))?"—":`${Number(v).toFixed(1)} kn`}
function fmtDistance(v?:number|null){return v==null||!Number.isFinite(Number(v))?"—":`${Number(v).toFixed(2)} nm`}

function otherPort(port:"BENGKALIS"|"PAKNING"){
  return port==="BENGKALIS"?"PAKNING":"BENGKALIS";
}
function routeOf(v:Vessel,port:"BENGKALIS"|"PAKNING"){
  const anyV=v as any;
  const origin=anyV.origin_port||anyV.departure_port||anyV.from_port;
  const destination=v.destination_port||anyV.to_port;
  if(origin&&destination)return `${origin} → ${destination}`;
  if(destination)return `${destination===port?otherPort(port):(v.current_port||otherPort(port))} → ${destination}`;
  if(v.operational_state==="BERTHED"&&v.current_port)return `${v.current_port} → ${otherPort(v.current_port as any)}`;
  return `${otherPort(port)} ↔ ${port}`;
}
function publicStatus(v:Vessel){
  const anyV=v as any;
  const explicit=String(anyV.schedule_status||anyV.public_status||anyV.delay_status||"").trim();
  if(explicit)return explicit.toUpperCase().replaceAll("_"," ");
  const quality=String(v.data_quality||"").toUpperCase();
  const op=String(v.operational_state||"").toUpperCase();
  if(quality==="STALE"||quality==="DELAYED")return "DATA DELAY";
  if(op==="BERTHED")return "BERTHED";
  if(op==="SAILING")return "EN ROUTE";
  if(op.includes("MANEUVER"))return "ARRIVING";
  if(op)return op.replaceAll("_"," ");
  return "LIVE";
}
function statusClass(status:string){
  const s=status.toUpperCase();
  if(s.includes("DELAY")||s.includes("STALE")||s.includes("ERROR"))return "delay";
  if(s.includes("BERTH")||s.includes("ARRIV"))return "berth";
  if(s.includes("DEPART")||s.includes("EN ROUTE")||s.includes("SAIL"))return "route";
  if(s.includes("ON TIME")||s.includes("LIVE"))return "ontime";
  return "neutral";
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

  const vessels=state.vessels||[];
  const berthEntries=Object.entries(state.berths||{}).filter(([k])=>k.includes(port));
  const occupied=berthEntries.filter(([,v])=>v.status==="OCCUPIED").length;

  const board=useMemo(()=>[...vessels].sort((a,b)=>{
    const ta=a.eta_timestamp?new Date(a.eta_timestamp).getTime():Number.MAX_SAFE_INTEGER;
    const tb=b.eta_timestamp?new Date(b.eta_timestamp).getTime():Number.MAX_SAFE_INTEGER;
    const sa=String(a.operational_state||"").toUpperCase()==="BERTHED"?0:1;
    const sb=String(b.operational_state||"").toUpperCase()==="BERTHED"?0:1;
    return sa-sb||ta-tb;
  }),[vessels]);

  return <div className="shell publicV10Shell">
    <Topbar active={port.toLowerCase()}/>
    <main className="publicV10Page">
      <header className="publicV10Hero">
        <div>
          <div className="eyebrow">Ferry Information Board</div>
          <h1>{port==="BENGKALIS"?"Bengkalis":"Pakning"} Ferry Terminal</h1>
          <p>Informasi kedatangan dan keberangkatan kapal secara realtime.</p>
        </div>
        <div className="publicV10Live">
          <span className="liveBadge"><span className="liveDot"/> LIVE</span>
          <small>Update {fmtTime(state.generated_at)}</small>
        </div>
      </header>

      {err&&<div className="error">{err}</div>}

      <section className="publicV10Quick">
        <div><Ship/><span>Kapal aktif</span><b>{vessels.length}</b></div>
        <div><Anchor/><span>Dermaga terpakai</span><b>{occupied}/{berthEntries.length||2}</b></div>
        <div><Signal/><span>AIS terakhir</span><b>{fmtTime(state.ais_updated_at)}</b></div>
        <div><MapPinned/><span>Rute</span><b>Bengkalis ↔ Pakning</b></div>
      </section>

      <section className="publicV10Main">
        <div className="card publicV10MapCard">
          <div className="publicV10SectionHead">
            <div><b>Peta Kapal Realtime</b><span>Posisi, arah, dan status kapal</span></div>
            <MapPinned size={18}/>
          </div>
          <VesselMap vessels={vessels}/>
          <div className="publicV10Berths">
            {berthEntries.length?berthEntries.map(([name,b])=>
              <div className={`publicV10Berth ${b.status==="OCCUPIED"?"occupied":"ready"}`} key={name}>
                <span>{name.replace(`${port}_BERTH_`,"Dermaga ")}</span>
                <b>{b.shipname||"AVAILABLE"}</b>
              </div>
            ):<div className="publicV10Berth ready"><span>Dermaga</span><b>Menunggu data</b></div>}
          </div>
        </div>

        <div className="card publicV10BoardCard">
          <div className="publicV10SectionHead boardHead">
            <div><b>Arrival / Departure</b><span>{port} · urut berdasarkan kedatangan</span></div>
            <Clock3 size={18}/>
          </div>
          <div className="publicV10Board">
            <div className="publicV10BoardHeader">
              <span>Kapal</span><span>Rute</span><span>ETA</span><span>ETD</span><span>Kecepatan</span><span>Jarak</span><span>Status</span>
            </div>
            {board.length===0?<div className="publicV10Empty">Belum ada kapal AIS aktif.</div>:board.map(v=>{
              const status=publicStatus(v);
              return <div className="publicV10BoardRow" key={v.mmsi}>
                <div className="publicV10Vessel"><span className="publicV10ShipDot"/><div><b>{v.shipname||`MMSI ${v.mmsi}`}</b><small>{v.mmsi}</small></div></div>
                <span className="publicV10Route">{routeOf(v,port)}</span>
                <b className="publicV10Time">{fmtTime(v.eta_timestamp)}</b>
                <b className="publicV10Time">{fmtTime(v.etd_timestamp)}</b>
                <span>{fmtSpeed(v.sog)}</span>
                <span>{fmtDistance(v.berth_distance_nm)}</span>
                <span><em className={`publicV10Status ${statusClass(status)}`}>{status}</em></span>
              </div>
            })}
          </div>
          <div className="publicV10Footnote">ETA dan ETD yang ditampilkan adalah estimasi operasional terbaru. Detail koreksi model, CCTV, dan audit tersedia pada Inspection.</div>
        </div>
      </section>
    </main>
  </div>
}
