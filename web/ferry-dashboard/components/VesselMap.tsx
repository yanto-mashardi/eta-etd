"use client";

import {useEffect,useRef} from "react";
import maplibregl,{Map as MLMap,Marker,Popup} from "maplibre-gl";
import type {Vessel} from "@/lib/types";

const BERTHS=[
  {name:"Bengkalis Berth 1",lat:1.449921,lon:102.136747},
  {name:"Bengkalis Berth 2",lat:1.449491,lon:102.138242},
  {name:"Pakning Berth 1",lat:1.380001,lon:102.148561},
  {name:"Pakning Berth 2",lat:1.378790,lon:102.149836},
];
const COLORS=["#00a8e8","#00b894","#ff9f1c","#8e5cff","#ef476f","#16a085","#f45d01"];
function colorFor(v:Vessel){const s=String(v.mmsi||"");let n=0;for(const c of s)n=(n*31+c.charCodeAt(0))>>>0;return COLORS[n%COLORS.length]}
function shortName(v:Vessel){
  const raw=String(v.shipname||`MMSI ${v.mmsi}`).replace(/^KMP[.\s-]*/i,"").trim();
  const first=raw.split(/[\s-]+/).filter(Boolean)[0]||raw;
  return first.length>12?first.slice(0,12):first;
}
function shipSvg(color:string){return `<svg width="44" height="44" viewBox="0 0 64 64" xmlns="http://www.w3.org/2000/svg"><circle cx="32" cy="32" r="28" fill="white" fill-opacity=".94" stroke="${color}" stroke-width="3"/><path d="M20 20h24v15l7 4-3 8c-4 6-9 9-16 9s-12-3-16-9l-3-8 7-4V20z" fill="${color}"/><path d="M26 20V12h12v8M29 12V8h6v4M20 39h24" fill="none" stroke="white" stroke-width="2.8" stroke-linecap="round"/><circle cx="27" cy="29" r="2" fill="white"/><circle cx="37" cy="29" r="2" fill="white"/></svg>`}
function t(v?:string|null){if(!v)return "—";try{return new Date(v).toLocaleTimeString("id-ID",{hour:"2-digit",minute:"2-digit"})}catch{return "—"}}

export default function VesselMap({vessels}:{vessels:Vessel[]}){
  const el=useRef<HTMLDivElement|null>(null);
  const mapRef=useRef<MLMap|null>(null);
  const markers=useRef<Marker[]>([]);

  useEffect(()=>{
    if(!el.current)return;
    const map=new maplibregl.Map({container:el.current,style:"https://basemaps.cartocdn.com/gl/voyager-gl-style/style.json",center:[102.1435,1.4145],zoom:11.55,attributionControl:false});
    map.addControl(new maplibregl.NavigationControl({showCompass:false}),"top-right");
    map.addControl(new maplibregl.AttributionControl({compact:true}),"bottom-right");
    mapRef.current=map;
    return()=>{map.remove();mapRef.current=null};
  },[]);

  useEffect(()=>{
    const map=mapRef.current;if(!map)return;
    markers.current.forEach(m=>m.remove());markers.current=[];

    for(const berth of BERTHS){
      const node=document.createElement("div");node.className="v11BerthMarker";
      const marker=new maplibregl.Marker({element:node}).setLngLat([berth.lon,berth.lat]).setPopup(new Popup({offset:18}).setHTML(`<div class="v11Popup"><b>${berth.name}</b><span>Ro-Ro berth</span></div>`)).addTo(map);
      markers.current.push(marker);
    }

    for(const vessel of vessels){
      if(typeof vessel.latitude!=="number"||typeof vessel.longitude!=="number")continue;
      const color=colorFor(vessel);
      const node=document.createElement("div");
      node.className="v11ShipMarkerWrap";
      node.innerHTML=`<div class="v11ShipLeader"><span class="v11ShipLabel" style="border-color:${color};color:${color}">${shortName(vessel)}</span><svg class="v11LeaderSvg" width="70" height="28" viewBox="0 0 70 28" aria-hidden="true"><path d="M2 3 C24 3, 32 22, 58 22" fill="none" stroke="${color}" stroke-width="2"/><path d="M58 22 l-7 -4 l2 8 z" fill="${color}"/></svg></div><div class="v11ShipIcon">${shipSvg(color)}</div>`;
      const popup=`<div class="v11Popup"><b>${vessel.shipname||vessel.mmsi}</b><span>${vessel.current_port||"—"} → ${vessel.destination_port||"—"}</span><div><strong>ETA</strong><b>${t(vessel.eta_timestamp)}</b></div><div><strong>ETD</strong><b>${t(vessel.etd_timestamp)}</b></div><div><strong>Speed</strong><b>${vessel.sog==null?"—":Number(vessel.sog).toFixed(1)+" kn"}</b></div><div><strong>Distance</strong><b>${vessel.berth_distance_nm==null?"—":Number(vessel.berth_distance_nm).toFixed(2)+" nm"}</b></div></div>`;
      const marker=new maplibregl.Marker({element:node,anchor:"center"}).setLngLat([vessel.longitude,vessel.latitude]).setPopup(new Popup({offset:32,maxWidth:"290px"}).setHTML(popup)).addTo(map);
      markers.current.push(marker);
    }
  },[vessels]);

  return <div ref={el} className="map v11Map"/>;
}
