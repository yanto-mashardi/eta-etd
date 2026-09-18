"use client";

import {useEffect,useMemo,useState} from "react";
import {Activity,Camera,Database,GitCompareArrows,History,LogOut,Settings2,ShieldCheck,Users} from "lucide-react";
import Topbar from "@/components/Topbar";
import {getJSON,postJSON} from "@/lib/api";

type Me={username:string;role:string;full_name?:string};
type Tab="overview"|"cctv"|"reliability"|"correction"|"training"|"mfar"|"logs"|"account"|"users";

function fmt(v:any,d=2){const n=Number(v);return Number.isFinite(n)?n.toFixed(d):"—"}
function time(v:any){if(!v)return "—";try{return new Date(v).toLocaleString("id-ID")}catch{return String(v)}}
function pick(row:any,keys:string[]){for(const k of keys){if(row?.[k]!==undefined&&row?.[k]!==null&&row?.[k]!=="")return row[k]}return "—"}
function badge(v:any){const x=String(v||"UNKNOWN").toUpperCase();return x.includes("OK")||x.includes("ACTIVE")||x.includes("LIVE")||x.includes("FRESH")?"good":x.includes("MISSING")||x.includes("STALE")||x.includes("ERROR")?"bad":"warn"}

function numMetric(row:any,keys:string[]){
  for(const k of keys){
    const v=Number(row?.[k]);
    if(Number.isFinite(v)) return v;
  }
  return null;
}
function modelValue(row:any){
  const raw=String(pick(row,["algorithm","model","model_name","name"])).toLowerCase();
  if(raw.includes("xg")) return "xgboost";
  if(raw.includes("random")||raw.includes("forest")||raw==="rf") return "random_forest";
  return raw.replace(/\s+/g,"_");
}
function modelLabel(row:any){
  const raw=String(pick(row,["algorithm","model","model_name","name"]));
  if(raw==="—") return "Model";
  return raw;
}
function modelOptions(rows:any[]){
  const byValue=new Map<string,{value:string;label:string;mae:number|null;rmse:number|null;r2:number|null}>();
  for(const r of rows||[]){
    const value=modelValue(r);
    if(!value||value==="—") continue;
    const mae=numMetric(r,["mae","MAE","MAE_min","test_mae","mae_min"]);
    const rmse=numMetric(r,["rmse","RMSE","RMSE_min","test_rmse"]);
    const r2=numMetric(r,["r2","R2","r_squared"]);
    const prev=byValue.get(value);
    if(!prev || (mae!==null && (prev.mae===null || mae<prev.mae))){
      byValue.set(value,{value,label:modelLabel(r),mae,rmse,r2});
    }
  }
  return Array.from(byValue.values()).sort((a,b)=>{
    if(a.mae!==null&&b.mae!==null)return a.mae-b.mae;
    if(a.mae!==null)return -1;
    if(b.mae!==null)return 1;
    return a.label.localeCompare(b.label);
  });
}

function VideoFrame({url,label}:{url?:string|null;label:string}){
  return <div className="auditVideo"><div className="auditVideoLabel">{label}</div>{url?<iframe src={url} title={label} allow="autoplay; fullscreen"/>:<div className="auditVideoEmpty">Stream belum tersedia</div>}</div>
}

export default function Inspection(){
  const[token,setToken]=useState("");
  const[user,setUser]=useState<Me|null>(null);
  const[username,setUsername]=useState("Admin");
  const[password,setPassword]=useState("");
  const[error,setError]=useState("");
  const[tab,setTab]=useState<Tab>("overview");
  const[overview,setOverview]=useState<any>(null);
  const[reliability,setReliability]=useState<any>(null);
  const[correction,setCorrection]=useState<any>(null);
  const[cctv,setCctv]=useState<any>(null);
  const[logs,setLogs]=useState<any[]>([]);
  const[users,setUsers]=useState<any[]>([]);
  const[roles,setRoles]=useState<any[]>([]);
  const[userDrafts,setUserDrafts]=useState<Record<string,any>>({});
  const[models,setModels]=useState({ml1:"",ml2:""});
  const[saving,setSaving]=useState(false);
  const[nu,setNu]=useState({username:"",full_name:"",password:"",role:"Viewer"});
  const[resetUser,setResetUser]=useState("");
  const[resetPass,setResetPass]=useState("");
  const[currentPass,setCurrentPass]=useState("");
  const[newPass,setNewPass]=useState("");
  const[passwordMsg,setPasswordMsg]=useState("");
  const[training,setTraining]=useState<any>({status:{status:"IDLE"},candidates:[]});
  const[retraining,setRetraining]=useState(false);
  const[selectedCandidates,setSelectedCandidates]=useState({ml1:"",ml2:""});

  useEffect(()=>{const t=localStorage.getItem("bima2_token")||"";if(t){setToken(t);load(t)}},[]);

  useEffect(()=>{
    const prevBodyOverflow=document.body.style.overflow;
    const prevBodyHeight=document.body.style.height;
    const prevHtmlOverflow=document.documentElement.style.overflow;
    document.documentElement.style.overflow="auto";
    document.body.style.overflow="auto";
    document.body.style.height="auto";
    return()=>{
      document.documentElement.style.overflow=prevHtmlOverflow;
      document.body.style.overflow=prevBodyOverflow;
      document.body.style.height=prevBodyHeight;
    };
  },[]);


  async function load(t:string){
    try{
      const me=await getJSON<Me>("/api/auth/me",t);setUser(me);
      const [o,r,c,ca,l,tr]=await Promise.all([
        getJSON<any>("/api/inspection/overview",t),
        getJSON<any>("/api/inspection/reliability/details",t),
        getJSON<any>("/api/inspection/model-corrections",t),
        getJSON<any>("/api/inspection/cctv-audit",t),
        getJSON<any[]>("/api/inspection/logs",t),
        getJSON<any>("/api/inspection/training/status",t),
      ]);
      setOverview(o);setReliability(r);setCorrection(c);setCctv(ca);setLogs(l||[]);setTraining(tr||{status:{status:"IDLE"},candidates:[]});
      setModels({ml1:o?.models?.active?.ml1_eta?.active||"",ml2:o?.models?.active?.ml2_turnaround?.active||""});
      if(me.role==="MasterAdmin"){
        const [uu,rr]=await Promise.all([getJSON<any[]>("/api/inspection/users",t),getJSON<any[]>("/api/inspection/roles",t)]);
        setUsers(uu||[]);setRoles(rr||[]);
        setUserDrafts(Object.fromEntries((uu||[]).map((x:any)=>[x.username,{full_name:x.full_name||"",role:x.role,is_active:!!x.is_active}])));
      }
      setError("");
    }catch(e:any){localStorage.removeItem("bima2_token");setToken("");setUser(null);setError(e?.message||"Gagal memuat Inspection")}
  }

  async function login(e:React.FormEvent){
    e.preventDefault();setError("");
    try{const r=await postJSON<{access_token:string}>("/api/auth/login",{username,password});localStorage.setItem("bima2_token",r.access_token);setToken(r.access_token);await load(r.access_token)}
    catch{setError("Login gagal. Periksa username/password.")}
  }

  async function saveModels(){
    setSaving(true);setError("");
    try{await postJSON("/api/inspection/models/active",{ml1:models.ml1||null,ml2:models.ml2||null},token);await load(token)}
    catch(e:any){setError(e?.message||"Gagal mengubah model aktif")}
    finally{setSaving(false)}
  }

  async function runRetraining(){
    if(!confirm("Jalankan training ulang ML1 dan ML2 dari seluruh data histori yang tersedia? Model aktif tidak akan berubah otomatis."))return;
    setRetraining(true);setError("");
    try{
      await postJSON("/api/inspection/training/run",{},token);
      const poll=async()=>{
        const tr=await getJSON<any>("/api/inspection/training/status",token);
        setTraining(tr);
        const st=String(tr?.status?.status||"").toUpperCase();
        if(st==="RUNNING"||st==="STARTING"){setTimeout(poll,3000)}
        else{setRetraining(false);await load(token)}
      };
      setTimeout(poll,1500);
    }catch(e:any){setRetraining(false);setError(e?.message||"Gagal memulai retraining")}
  }

  async function activateCandidates(){
    if(!selectedCandidates.ml1&&!selectedCandidates.ml2){setError("Pilih candidate ML1 atau ML2.");return}
    setSaving(true);setError("");
    try{
      await postJSON("/api/inspection/training/activate",{ml1_candidate_id:selectedCandidates.ml1||null,ml2_candidate_id:selectedCandidates.ml2||null},token);
      await load(token);
    }catch(e:any){setError(e?.message||"Gagal mengaktifkan candidate model")}
    finally{setSaving(false)}
  }

  async function refreshUsers(){
    const uu=await getJSON<any[]>("/api/inspection/users",token);
    setUsers(uu||[]);
    setUserDrafts(Object.fromEntries((uu||[]).map((x:any)=>[x.username,{full_name:x.full_name||"",role:x.role,is_active:!!x.is_active}])));
  }

  async function addUser(e:React.FormEvent){
    e.preventDefault();
    try{await postJSON("/api/inspection/users",nu,token);setNu({username:"",full_name:"",password:"",role:"Viewer"});await refreshUsers()}
    catch(e:any){setError(e?.message||"Gagal menambah user")}
  }

  function draftUser(username:string,patch:any){setUserDrafts(d=>({...d,[username]:{...(d[username]||{}),...patch}}))}

  async function saveUser(username:string){
    setError("");setPasswordMsg("");
    try{await postJSON(`/api/inspection/users/${encodeURIComponent(username)}/update`,userDrafts[username]||{},token);await refreshUsers();setPasswordMsg(`User ${username} berhasil diperbarui.`)}
    catch(e:any){setError(e?.message||"Gagal memperbarui user")}
  }

  async function changeOwnPassword(e:React.FormEvent){
    e.preventDefault();setPasswordMsg("");setError("");
    if(newPass.length<8){setError("Password baru minimal 8 karakter.");return}
    try{
      await postJSON("/api/auth/change-password",{current_password:currentPass,new_password:newPass},token);
      setCurrentPass("");setNewPass("");setPasswordMsg("Password Anda berhasil diubah.");
    }catch(e:any){setError(e?.message||"Gagal mengubah password")}
  }

  async function resetUserPassword(e:React.FormEvent){
    e.preventDefault();setPasswordMsg("");setError("");
    if(!resetUser){setError("Pilih user yang akan direset.");return}
    if(resetPass.length<8){setError("Password baru minimal 8 karakter.");return}
    try{
      await postJSON(`/api/inspection/users/${encodeURIComponent(resetUser)}/reset-password`,{new_password:resetPass},token);
      setResetPass("");setPasswordMsg(`Password ${resetUser} berhasil direset.`);
    }catch(e:any){setError(e?.message||"Gagal mereset password user")}
  }

  const nav=[
    ["overview","Overview",Activity],
    ["cctv","CCTV & YOLO Audit",Camera],
    ["reliability","ETA & ETD Reliability",Activity],
    ["correction","Model Correction",GitCompareArrows],
    ["training","Model Training",History],
    ["mfar","MFAR",Settings2],
    ["logs","Logs",Database],
    ["account","Akun Saya",ShieldCheck],
    ...(user?.role==="MasterAdmin"?[["users","User Management",Users] as any]:[]),
  ] as [Tab,string,any][];

  if(!user)return <div className="loginWrap"><form className="card loginCard" onSubmit={login}>
    <div className="eyebrow">System Inspection & Reliability</div><h1 style={{fontSize:30}}>Masuk</h1><div className="subtle">Akses analisis ETA/ETD, model, CCTV/YOLO, MFAR, dan administrasi.</div>
    {error&&<div className="error" style={{marginTop:14}}>{error}</div>}
    <div className="field"><label>Username</label><input value={username} onChange={e=>setUsername(e.target.value)}/></div>
    <div className="field"><label>Password</label><input type="password" value={password} onChange={e=>setPassword(e.target.value)}/></div>
    <button className="primary">Login</button>
  </form></div>;

  const health=overview?.system_health||{};
  const relSum=reliability?.summary||{};
  const hist=correction?.historical||{};
  const ml1Rows=overview?.models?.ml1_registry||[];
  const ml2Rows=overview?.models?.ml2_registry||[];
  const ml1Options=modelOptions(ml1Rows);
  const ml2Options=modelOptions(ml2Rows);
  const ml1Best=ml1Options.find(x=>x.mae!==null)||null;
  const ml2Best=ml2Options.find(x=>x.mae!==null)||null;
  const trainingStatus=training?.status||{};
  const candidateRows=training?.candidates||[];
  const ml1Candidates=candidateRows.filter((r:any)=>String(r.scope).toUpperCase()==="ML1");
  const ml2Candidates=candidateRows.filter((r:any)=>String(r.scope).toUpperCase()==="ML2");

  return <div className="shell" style={{minHeight:"100vh",height:"auto",overflow:"visible"}}><Topbar active="inspection"/><main className="inspectionPage" style={{minHeight:"calc(100vh - 72px)",height:"auto",overflow:"visible",paddingBottom:48}}>
    <div className="inspectionHero"><div><div className="eyebrow">Inspection & Reliability</div><h1>System Inspection</h1><div className="subtle">{user.full_name||user.username} · {user.role}</div></div><button className="secondary" onClick={()=>{localStorage.removeItem("bima2_token");setToken("");setUser(null)}}><LogOut size={15}/> Logout</button></div>
    {error&&<div className="error">{error}</div>}

    <div className="inspectionTabs">{nav.map(([key,label,Icon])=><button key={key} className={tab===key?"active":""} onClick={()=>setTab(key)}><Icon size={15}/>{label}</button>)}</div>

    {tab==="overview"&&<section className="inspectSection">
      <div className="inspectTitle"><div><h2>System Overview</h2><p>Hanya kesehatan pipeline realtime; analisis model dan MFAR dipisahkan agar tidak overlap.</p></div></div>
      <div className="inspectKpis">
        {[['AIS',health.ais],['CCTV',health.cctv],['ML1',health.ml1],['ML2',health.ml2]].map(([k,v])=><div className="inspectKpi" key={String(k)}><span>{k}</span><b className={badge(v)}>{String(v||'—')}</b></div>)}
        <div className="inspectKpi"><span>Kapal</span><b>{health.vessel_count??0}</b></div>
        <div className="inspectKpi"><span>Dermaga terisi</span><b>{health.berth_occupied??0}/{health.berth_total??4}</b></div>
      </div>
      <div className="inspectGrid2"><div className="card inspectCard"><h3>Freshness</h3><div className="kv"><span>AIS update</span><b>{time(health.ais_updated_at)}</b></div><div className="kv"><span>CCTV update</span><b>{time(health.cctv_updated_at)}</b></div></div><div className="card inspectCard"><h3>Active model configuration</h3><div className="kv"><span>ML1 ETA</span><b>{overview?.models?.active?.ml1_eta?.active||'—'}</b></div><div className="kv"><span>ML2 Turnaround</span><b>{overview?.models?.active?.ml2_turnaround?.active||'—'}</b></div></div></div>
    </section>}

    {tab==="cctv"&&<section className="inspectSection">
      <div className="inspectTitle"><div><h2>CCTV & YOLO Audit</h2><p>RAW dan YOLO ditampilkan berdampingan khusus Inspection untuk memeriksa kendaraan yang terlewat, salah klasifikasi, atau tidak terhitung.</p></div><span className="inspectNote">Tidak ditampilkan di dashboard publik</span></div>
      <div className="auditVideoGrid"><VideoFrame label="CCTV RAW" url={cctv?.raw_hls_url||cctv?.raw_webrtc_url}/><VideoFrame label="YOLO + ByteTrack" url={cctv?.yolo_hls_url||cctv?.yolo_webrtc_url}/></div>
      <div className="inspectKpis six">{[['Mobil antre',cctv?.state?.car_queue_current],['Motor antre',cctv?.state?.motor_queue_current],['Mobil masuk',cctv?.state?.car_in_total],['Motor masuk',cctv?.state?.motor_in_total],['Mobil keluar',cctv?.state?.car_out_total],['Motor keluar',cctv?.state?.motor_out_total]].map(([k,v])=><div className="inspectKpi" key={String(k)}><span>{k}</span><b>{v??0}</b></div>)}</div>
      <div className="card inspectCard"><h3>Pedoman pemeriksaan</h3><p className="subtle">Bandingkan objek pada RAW dengan bounding box/track pada YOLO pada waktu yang sama. Jika kendaraan terlihat pada RAW tetapi tidak memiliki deteksi/track, catat waktu, kelas kendaraan, arah gerak, dan kondisi visual untuk evaluasi confidence, ROI, tracking, atau occlusion.</p></div>
    </section>}

    {tab==="reliability"&&<section className="inspectSection">
      <div className="inspectTitle"><div><h2>ETA & ETD Reliability</h2><p>Prediksi dibandingkan dengan event aktual. Arrival dianalisis sebagai ETA; Departure dianalisis sebagai ETD.</p></div></div>
      <div className="inspectKpis"><div className="inspectKpi"><span>ETA events</span><b>{relSum.eta_events??0}</b><small>MAE {fmt(relSum.eta_mae_min)} min</small></div><div className="inspectKpi"><span>ETD events</span><b>{relSum.etd_events??0}</b><small>MAE {fmt(relSum.etd_mae_min)} min</small></div><div className="inspectKpi"><span>Total events</span><b>{relSum.overall_events??0}</b><small>MAE {fmt(relSum.overall_mae_min)} min</small></div></div>
      <div className="card inspectCard tableWrap"><table className="table"><thead><tr><th>Event</th><th>MMSI</th><th>Terminal/Berth</th><th>Predicted</th><th>Actual</th><th>Error</th><th>|Error|</th><th>Data</th><th>Model</th><th>Status</th></tr></thead><tbody>{(reliability?.rows||[]).map((r:any)=><tr key={r.id}><td>{r.event_type}</td><td>{r.mmsi}</td><td>{r.terminal||'—'} / {r.berth||'—'}</td><td>{time(r.predicted_at)}</td><td>{time(r.actual_at)}</td><td>{fmt(r.error_minutes)} m</td><td>{fmt(r.absolute_error_minutes)} m</td><td>{r.data_quality||'—'}</td><td>{r.event_type==='ARRIVAL'?(r.ml1_model_id||'—'):(r.ml2_model_id||'—')}</td><td>{r.analysis_status||'—'}</td></tr>)}</tbody></table>{!(reliability?.rows||[]).length&&<div className="empty">Belum ada pasangan predicted–actual yang dapat dianalisis.</div>}</div>
    </section>}

    {tab==="correction"&&<section className="inspectSection">
      <div className="inspectTitle"><div><h2>Model Correction</h2><p>Menunjukkan berapa menit ML1 mengoreksi ETA baseline dan berapa menit ML2 mengoreksi turnaround/ETD. Nilai hanya ditampilkan bila keluaran model tersedia.</p></div></div>
      {user.role==="MasterAdmin"&&<div className="card inspectCard">
        <h3>Retraining dari data histori</h3>
        <p className="subtle">Membaca seluruh file AIS pada folder histori dan seluruh workbook kendaraan/penumpang yang kompatibel. Random Forest dan XGBoost dilatih ulang dengan split chronological 80/20. Hasil disimpan sebagai candidate baru dan tidak otomatis mengganti model operasi.</p>
        <div className="policyGrid"><div><span>Status</span><b className={badge(trainingStatus.status)}>{trainingStatus.status||"IDLE"}</b></div><div><span>Run ID</span><b>{trainingStatus.run_id||"—"}</b></div><div><span>Stage</span><b>{trainingStatus.stage||"—"}</b></div><div><span>Update</span><b>{time(trainingStatus.updated_at)}</b></div></div>
        <div style={{display:"flex",gap:12,alignItems:"center",marginTop:14,flexWrap:"wrap"}}><button className="primary" onClick={runRetraining} disabled={retraining||["RUNNING","STARTING"].includes(String(trainingStatus.status||"").toUpperCase())}>{retraining?"Training berjalan...":"Run Training dari Seluruh Histori"}</button><span className="subtle">{trainingStatus.message||"Belum ada retraining baru."}</span></div>
      </div>}
      <div className="inspectKpis"><div className="inspectKpi"><span>Avg ML1 correction</span><b>{fmt(hist.avg_ml1_correction_min)} m</b><small>|avg| {fmt(hist.avg_abs_ml1_correction_min)} m</small></div><div className="inspectKpi"><span>Avg ML2 correction</span><b>{fmt(hist.avg_ml2_correction_min)} m</b><small>|avg| {fmt(hist.avg_abs_ml2_correction_min)} m</small></div><div className="inspectKpi"><span>Historical samples</span><b>{hist.samples??0}</b></div></div>
      <div className="card inspectCard tableWrap"><table className="table"><thead><tr><th>Kapal</th><th>State</th><th>ETA base</th><th>ETA corrected</th><th>ML1 correction</th><th>Turnaround base</th><th>Turnaround corrected</th><th>ML2 correction</th><th>ETA</th><th>ETD</th></tr></thead><tbody>{(correction?.current||[]).map((r:any)=><tr key={r.mmsi}><td>{r.shipname||r.mmsi}</td><td>{r.state||'—'}</td><td>{fmt(r.eta_base_min)} m</td><td>{fmt(r.eta_corrected_min)} m</td><td>{fmt(r.ml1_correction_min)} m</td><td>{fmt(r.turnaround_base_min)} m</td><td>{fmt(r.turnaround_corrected_min)} m</td><td>{fmt(r.ml2_correction_min)} m</td><td>{time(r.eta_timestamp)}</td><td>{time(r.etd_timestamp)}</td></tr>)}</tbody></table></div><div className="inspectNoteBlock">{correction?.note}</div>
    </section>}

    {tab==="training"&&<section className="inspectSection">
      <div className="inspectTitle"><div><h2>Model Training & Historical Validation</h2><p>Hasil training dari data histori disimpan di registry. Split validasi tetap chronological 80/20; realtime tidak dipakai untuk melatih model secara otomatis.</p></div></div>
      <div className="card inspectCard"><h3>Historical policy</h3><div className="policyGrid"><div><span>Split</span><b>{overview?.historical_policy?.split_method||'—'} · test {Number((overview?.historical_policy?.test_ratio||0)*100).toFixed(0)}%</b></div><div><span>AIS history</span><b>{overview?.historical_policy?.ais_folder||'—'}</b></div><div><span>Vehicle history</span><b>{overview?.historical_policy?.vehicle_folder||'—'}</b></div><div><span>Realtime for training</span><b>{overview?.historical_policy?.realtime_data_used_for_training?'YES':'NO'}</b></div></div></div>
      <div className="inspectGrid2 modelLabs"><div className="card inspectCard"><h3>ML1 · ETA Correction</h3><ModelRegistry rows={ml1Rows}/></div><div className="card inspectCard"><h3>ML2 · Turnaround / ETD</h3><ModelRegistry rows={ml2Rows}/></div></div>
      {user.role==="MasterAdmin"&&<div className="card inspectCard modelSelector">
        <h3>Candidate model & aktivasi</h3>
        <p className="subtle">Setiap retraining menghasilkan versi candidate baru. Bandingkan MAE/RMSE dan jumlah data uji sebelum aktivasi. Model lama tetap tersimpan untuk audit dan evaluasi.</p>
        <div className="modelSelectGrid">
          <label>ML1 · ETA candidate<select value={selectedCandidates.ml1} onChange={e=>setSelectedCandidates({...selectedCandidates,ml1:e.target.value})}><option value="">— jangan ubah ML1 —</option>{ml1Candidates.map((r:any)=><option key={r.candidate_id} value={r.candidate_id}>{r.run_id} · {r.algorithm} · MAE {fmt(r.mae_min)} · RMSE {fmt(r.rmse_min)} · n={r.n_test||"—"} {String(r.status)==="ACTIVE"?"· ACTIVE":""}</option>)}</select></label>
          <label>ML2 · Turnaround/ETD candidate<select value={selectedCandidates.ml2} onChange={e=>setSelectedCandidates({...selectedCandidates,ml2:e.target.value})}><option value="">— jangan ubah ML2 —</option>{ml2Candidates.map((r:any)=><option key={r.candidate_id} value={r.candidate_id}>{r.run_id} · {r.algorithm} · MAE {fmt(r.mae_min)} · RMSE {fmt(r.rmse_min)} · n={r.n_test||"—"} {String(r.status)==="ACTIVE"?"· ACTIVE":""}</option>)}</select></label>
          <button className="primary" onClick={activateCandidates} disabled={saving||(!selectedCandidates.ml1&&!selectedCandidates.ml2)}>{saving?"Menyimpan...":"Aktifkan Candidate Terpilih"}</button>
        </div>
        <p className="subtle">Model aktif saat ini: ML1 {overview?.models?.active?.ml1_eta?.active||"—"} · ML2 {overview?.models?.active?.ml2_turnaround?.active||"—"}.</p>
      </div>}
    </section>}

    {tab==="mfar"&&<section className="inspectSection">
      <div className="inspectTitle"><div><h2>MFAR · Supporting Analysis</h2><p>MFAR dipisahkan karena berada di luar analisis inti ETA/ETD. Menu ini hanya untuk parameter operasional/fuzzy dan rule inspection.</p></div><span className="inspectNote">Supporting analysis</span></div>
      <div className="card inspectCard tableWrap"><h3>Operational parameters</h3><table className="table"><thead><tr><th>Parameter</th><th>Value</th><th>Unit</th><th>Availability</th><th>Note</th></tr></thead><tbody>{(overview?.parameters||[]).map((r:any)=><tr key={r.key}><td>{r.label}</td><td>{r.value??'—'}</td><td>{r.unit||'—'}</td><td><span className={`statusText ${badge(r.availability)}`}>{r.availability}</span></td><td>{r.note||'—'}</td></tr>)}</tbody></table></div>
      <div className="card inspectCard tableWrap"><h3>Fuzzy rules</h3><table className="table"><thead><tr><th>Rule</th><th>IF</th><th>THEN</th></tr></thead><tbody>{(overview?.fuzzy_rules||[]).map((r:any)=><tr key={r.rule}><td>{r.rule}</td><td>{r.if}</td><td>{r.then}</td></tr>)}</tbody></table></div>
    </section>}

    {tab==="logs"&&<section className="inspectSection"><div className="inspectTitle"><div><h2>System Logs</h2><p>Log teknis pipeline untuk diagnosis kegagalan proses.</p></div></div><div className="card inspectCard"><pre className="logBox">{(logs||[]).map((x:any)=>typeof x==='string'?x:JSON.stringify(x,null,2)).join('\n\n')||'Belum ada log.'}</pre></div></section>}

    {tab==="account"&&<section className="inspectSection">
      <div className="inspectTitle"><div><h2>Akun Saya</h2><p>Semua user yang sudah login dapat mengganti password miliknya sendiri. Fitur ini tidak memberi hak untuk mereset password user lain.</p></div></div>
      {passwordMsg&&<div className="card inspectCard"><strong>{passwordMsg}</strong></div>}
      <div className="card inspectCard"><h3>Ganti Password Saya</h3><form onSubmit={changeOwnPassword} className="userForm"><input placeholder="Password saat ini" type="password" value={currentPass} onChange={e=>setCurrentPass(e.target.value)} required/><input placeholder="Password baru (min. 8 karakter)" type="password" value={newPass} onChange={e=>setNewPass(e.target.value)} required/><button className="primary">Ganti Password</button></form></div>
    </section>}

    {tab==="users"&&user.role==="MasterAdmin"&&<section className="inspectSection">
      <div className="inspectTitle"><div><h2>User Management</h2><p>Khusus MasterAdmin: tambah user, edit nama/role/status aktif, dan reset password user lain.</p></div></div>
      {passwordMsg&&<div className="card inspectCard"><strong>{passwordMsg}</strong></div>}
      <div className="card inspectCard"><h3>Reset Password User</h3><form onSubmit={resetUserPassword} className="userForm"><select value={resetUser} onChange={e=>setResetUser(e.target.value)} required><option value="">Pilih user</option>{users.filter(u=>u.username!==user.username).map(u=><option key={u.id} value={u.username}>{u.username} · {u.role}</option>)}</select><input placeholder="Password baru (min. 8 karakter)" type="password" value={resetPass} onChange={e=>setResetPass(e.target.value)} required/><button className="primary">Reset Password</button></form></div>
      <div className="card inspectCard"><h3>Tambah User</h3><form onSubmit={addUser} className="userForm"><input placeholder="Username" value={nu.username} onChange={e=>setNu({...nu,username:e.target.value})} required/><input placeholder="Nama" value={nu.full_name} onChange={e=>setNu({...nu,full_name:e.target.value})}/><input placeholder="Password" type="password" value={nu.password} onChange={e=>setNu({...nu,password:e.target.value})} required/><select value={nu.role} onChange={e=>setNu({...nu,role:e.target.value})}>{(roles.length?roles:[{name:"Researcher"},{name:"Operator"},{name:"Viewer"},{name:"MasterAdmin"}]).map((r:any)=><option key={r.name} value={r.name}>{r.name}</option>)}</select><button className="primary">Tambah User</button></form></div>
      <div className="card inspectCard tableWrap"><h3>Edit User & Hak Akses</h3><table className="table userAdminTable"><thead><tr><th>Username</th><th>Nama</th><th>Role</th><th>Aktif</th><th>Last login</th><th>Aksi</th></tr></thead><tbody>{users.map(u=>{const d=userDrafts[u.username]||{full_name:u.full_name||"",role:u.role,is_active:!!u.is_active};const self=u.username===user.username;return <tr key={u.id}><td><b>{u.username}</b>{self&&<small className="selfTag">ANDA</small>}</td><td><input value={d.full_name} onChange={e=>draftUser(u.username,{full_name:e.target.value})}/></td><td><select value={d.role} disabled={self} onChange={e=>draftUser(u.username,{role:e.target.value})}>{(roles.length?roles:[{name:"Researcher"},{name:"Operator"},{name:"Viewer"},{name:"MasterAdmin"}]).map((r:any)=><option key={r.name} value={r.name}>{r.name}</option>)}</select></td><td><label className="activeToggle"><input type="checkbox" checked={!!d.is_active} disabled={self} onChange={e=>draftUser(u.username,{is_active:e.target.checked})}/><span>{d.is_active?"Aktif":"Nonaktif"}</span></label></td><td>{time(u.last_login)}</td><td><button className="primary smallButton" type="button" onClick={()=>saveUser(u.username)}>Simpan</button></td></tr>})}</tbody></table><p className="subtle">Proteksi: MasterAdmin tidak dapat menonaktifkan atau menurunkan role akunnya sendiri. Reset password user lain tetap hanya tersedia untuk MasterAdmin.</p></div>
    </section>}
  </main></div>
}

function ModelRegistry({rows}:{rows:any[]}){
  if(!rows?.length)return <div className="empty">Registry belum berisi hasil training.</div>;
  return <div className="modelRegistryList">{rows.map((r:any,i:number)=><div className="modelRegistryRow" key={i}><div><b>{pick(r,['algorithm','model','model_name','name'])}</b><span>{pick(r,['run_id','training_run','version','created_at'])}</span></div><div><span>MAE</span><b>{fmt(pick(r,['mae','MAE','MAE_min','test_mae','mae_min']))}</b></div><div><span>RMSE</span><b>{fmt(pick(r,['rmse','RMSE','RMSE_min','test_rmse']))}</b></div><div><span>R²</span><b>{fmt(pick(r,['r2','R2','r_squared']))}</b></div><div><span>Status</span><b>{pick(r,['status','state','active'])}</b></div></div>)}</div>
}
