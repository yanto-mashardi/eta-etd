"use client";

import {useEffect,useMemo,useState} from "react";
import {Camera,Radio} from "lucide-react";
import {getJSON} from "@/lib/api";
import type {CctvPayload,VehicleState} from "@/lib/types";

function n(v:unknown){const x=Number(v);return Number.isFinite(x)?x:0}
function time(v?:string|null){
  if(!v)return "—";
  try{return new Date(v).toLocaleTimeString("id-ID",{hour:"2-digit",minute:"2-digit",second:"2-digit"})}
  catch{return "—"}
}

export default function CctvMonitor({
  port,
  onVehicle,
  showYolo=false
}:{
  port:"BENGKALIS"|"PAKNING";
  onVehicle?:(v:VehicleState)=>void;
  showYolo?:boolean;
}){
  const [payload,setPayload]=useState<CctvPayload|null>(null);
  const [error,setError]=useState("");

  useEffect(()=>{
    let alive=true;
    const load=async()=>{
      try{
        const r=await getJSON<CctvPayload>(`/api/realtime/cctv/${port.toLowerCase()}`);
        if(!alive)return;
        setPayload(r);
        setError("");
        if(r.state&&onVehicle)onVehicle(r.state);
      }catch(e:any){
        if(alive)setError(e?.message||"CCTV API tidak tersedia")
      }
    };
    load();
    const id=setInterval(load,2000);
    return()=>{alive=false;clearInterval(id)};
  },[port,onVehicle]);

  const s=payload?.state||{};

  // MediaMTX WebRTC page is the primary browser playback endpoint.
  // HLS page remains as fallback.
  const rawUrl=payload?.raw_webrtc_url||payload?.raw_hls_url||null;
  const yoloUrl=payload?.yolo_webrtc_url||payload?.yolo_hls_url||null;

  const counters=useMemo(()=>[
    ["Mobil antre",n(s.car_queue_current)],
    ["Motor antre",n(s.motor_queue_current)],
    ["Mobil masuk",n(s.car_in_total)],
    ["Motor masuk",n(s.motor_in_total)],
    ["Mobil termuat",n(s.loaded_car_total)],
    ["Motor termuat",n(s.loaded_motor_total)],
  ],[s]);

  return <div className="cameraPanel publicCameraPanel">
    <div className="compactHeader">
      <div>
        <b>CCTV Realtime</b>
        <span>{port} · update {time(payload?.updated_at||s.updated_at)}</span>
      </div>
      <div className={`streamState ${error?"bad":"good"}`}>
        <Radio size={13}/>{error?"API ERROR":"LIVE"}
      </div>
    </div>

    <div className={`cameraGrid ${showYolo?"withYolo":"rawOnly"}`}>
      <div className="videoTile rawVideoTile">
        <div className="videoLabel"><Camera size={13}/> CCTV RAW</div>
        {rawUrl
          ? <iframe
              src={rawUrl}
              title={`CCTV RAW ${port}`}
              allow="autoplay; fullscreen; picture-in-picture"
              referrerPolicy="no-referrer"
            />
          : <div className="videoEmpty">Stream RAW belum tersedia</div>}
      </div>

      {showYolo&&
        <div className="videoTile yoloTile">
          <div className="videoLabel"><Camera size={13}/> YOLO + ByteTrack</div>
          {yoloUrl
            ? <iframe
                src={yoloUrl}
                title={`CCTV YOLO ${port}`}
                allow="autoplay; fullscreen; picture-in-picture"
                referrerPolicy="no-referrer"
              />
            : <div className="videoEmpty">Stream YOLO belum tersedia</div>}
        </div>}
    </div>

    <div className="counterStrip">
      {counters.map(([label,value])=>
        <div className="counterCell" key={String(label)}>
          <b>{value}</b><span>{label}</span>
        </div>)}
    </div>

    <div className="algoLine">
      <span>Algoritma</span>
      <b>{s.counting_algorithm||"—"}</b>
      <span>Keluar: mobil {n(s.car_out_total)} · motor {n(s.motor_out_total)}</span>
    </div>

    {error&&<div className="miniError">{error}</div>}
  </div>
}
