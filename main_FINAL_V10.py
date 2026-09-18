from __future__ import annotations

import csv
import json
import os
import re
import subprocess
import shutil
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import bcrypt
import jwt
import mysql.connector
from fastapi import FastAPI, HTTPException, Depends, Header
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "outputs" / "realtime"
CCTV_OUT = ROOT / "data" / "01_DATA_SOURCE" / "CCTV" / "output"
QUEUE_LEDGER_PATH = OUT / "queue_service_state.json"
REGISTRY_DIR = ROOT / "config" / "registry"
LOG_DIRS = [ROOT / "logs", ROOT / "outputs" / "logs", ROOT / "outputs" / "training_runs"]

TRAINING_STATUS = ROOT / "outputs" / "inspection" / "training_status.json"
TRAINING_REGISTRY = REGISTRY_DIR / "training_run_registry.csv"
RETRAIN_SCRIPT = ROOT / "scripts" / "integration" / "retrain_from_history.py"
ACTIVATION_LOG = ROOT / "outputs" / "inspection" / "model_activation_log.jsonl"

JWT_SECRET = os.getenv("BIMA2_JWT_SECRET", "BIMA2_LOCAL_DEV_CHANGE_ME")
JWT_ALG = "HS256"

app = FastAPI(title="BIMA2 Realtime API", version="1.2")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://127.0.0.1:3000",
        "http://localhost:3000",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def read_json(name: str) -> dict[str, Any]:
    path = OUT / name
    return read_json_path(path)


def read_json_path(path: Path) -> dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def read_csv_rows(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    try:
        with path.open("r", encoding="utf-8-sig", newline="") as f:
            rows=list(csv.DictReader(f))
        # Normalize historical metric column names so frontend/API consumers
        # do not depend on one CSV naming convention.
        for row in rows:
            if row.get("mae") in (None,""):
                row["mae"]=row.get("MAE_min") or row.get("test_mae") or row.get("mae_min")
            if row.get("rmse") in (None,""):
                row["rmse"]=row.get("RMSE_min") or row.get("test_rmse")
            if row.get("r2") in (None,""):
                row["r2"]=row.get("R2") or row.get("r_squared")
            if row.get("algorithm") in (None,""):
                row["algorithm"]=row.get("model") or row.get("model_name") or row.get("name")
        return rows
    except Exception:
        return []


def cctv_state_path(port: str) -> Path | None:
    p = port.upper()
    if p == "BENGKALIS":
        return CCTV_OUT / "vehicle_state.json"
    if p == "PAKNING":
        env_path = os.getenv("CCTV_PAKNING_STATE_PATH", "").strip()
        return Path(env_path) if env_path else CCTV_OUT / "vehicle_state_pakning.json"
    return None


def read_cctv_state(port: str) -> dict[str, Any]:
    path = cctv_state_path(port)
    if not path:
        return {}
    raw = read_json_path(path)
    if not raw:
        return {}
    # Queue service is owned by the operation-state departure ledger, not by YOLO.
    # YOLO remains the source for vehicle arrivals; ferry departure subtracts loaded vehicles.
    ledger = read_json_path(QUEUE_LEDGER_PATH)
    lp = ((ledger.get("ports") or {}).get(port.upper()) or {}) if isinstance(ledger, dict) else {}
    try:
        loaded_car = int(float(lp.get("loaded_car_total", raw.get("loaded_car_total", 0)) or 0))
    except Exception:
        loaded_car = 0
    try:
        loaded_motor = int(float(lp.get("loaded_motor_total", raw.get("loaded_motor_total", 0)) or 0))
    except Exception:
        loaded_motor = 0
    try:
        car_in = int(float(raw.get("car_in_total", 0) or 0))
    except Exception:
        car_in = 0
    try:
        motor_in = int(float(raw.get("motor_in_total", 0) or 0))
    except Exception:
        motor_in = 0
    state = dict(raw)
    state["loaded_car_total"] = loaded_car
    state["loaded_motor_total"] = loaded_motor
    state["car_queue_current"] = max(0, car_in - loaded_car)
    state["motor_queue_current"] = max(0, motor_in - loaded_motor)
    state["total_queue_current"] = state["car_queue_current"] + state["motor_queue_current"]
    state["service_departure_count"] = int(lp.get("departure_count", 0) or 0)
    state["last_service_departure_at"] = lp.get("last_departure_at")
    state["last_service_departure_mmsi"] = lp.get("last_departure_mmsi")
    return state


def stream_urls(port: str) -> dict[str, str | None]:
    p = port.upper()

    # Browser publik tidak boleh diarahkan ke 127.0.0.1 milik server/laptop.
    # HLS diproxy melalui domain yang sama (/cctv-hls/) sehingga aman pada HTTPS.
    # WebRTC hanya dipakai bila BIMA2_WEBRTC_BASE memang dikonfigurasi publik.
    webrtc_base = os.getenv("BIMA2_WEBRTC_BASE", "").rstrip("/")
    hls_base = os.getenv("BIMA2_HLS_BASE", "/cctv-hls").rstrip("/")

    if p == "BENGKALIS":
        key="cctv_bengkalis"
        prefix="CCTV_BENGKALIS"
    elif p == "PAKNING":
        key="cctv_pakning"
        prefix="CCTV_PAKNING"
    else:
        return {
            "raw_rtsp_url":None,"yolo_rtsp_url":None,
            "raw_webrtc_url":None,"yolo_webrtc_url":None,
            "raw_hls_url":None,"yolo_hls_url":None,
        }

    default_raw_webrtc = f"{webrtc_base}/{key}/" if webrtc_base else ""
    default_yolo_webrtc = f"{webrtc_base}/{key}_yolo/" if webrtc_base else ""

    return {
        # RTSP ini untuk proses backend/relay, bukan untuk iframe browser.
        "raw_rtsp_url": os.getenv(f"{prefix}_RTSP_URL", f"rtsp://127.0.0.1:8554/{key}"),
        "yolo_rtsp_url": os.getenv(f"{prefix}_YOLO_RTSP_URL", f"rtsp://127.0.0.1:8554/{key}_yolo"),
        "raw_webrtc_url": os.getenv(f"{prefix}_WEBRTC_RAW_URL", default_raw_webrtc) or None,
        "yolo_webrtc_url": os.getenv(f"{prefix}_WEBRTC_YOLO_URL", default_yolo_webrtc) or None,
        "raw_hls_url": os.getenv(f"{prefix}_HLS_RAW_URL", f"{hls_base}/{key}/"),
        "yolo_hls_url": os.getenv(
            f"{prefix}_HLS_YOLO_URL",
            os.getenv(f"{prefix}_HLS_URL", f"{hls_base}/{key}_yolo/")
        ),
    }


def parse_active_model_config() -> dict[str, Any]:
    path = REGISTRY_DIR / "active_model_config.yaml"
    result: dict[str, Any] = {
        "run_id": None,
        "ml1_eta": {"active": None, "alternatives": [], "selection_metric": None},
        "ml2_turnaround": {"active": None, "alternatives": [], "selection_metric": None},
    }
    if not path.exists():
        return result
    section: str | None = None
    try:
        for raw in path.read_text(encoding="utf-8").splitlines():
            stripped = raw.strip()
            if not stripped or stripped.startswith("#"):
                continue
            if not raw.startswith((" ", "\t")) and stripped.endswith(":"):
                section = stripped[:-1]
                continue
            if not raw.startswith((" ", "\t")) and stripped.startswith("run_id:"):
                result["run_id"] = stripped.split(":", 1)[1].strip()
                continue
            if section not in ("ml1_eta", "ml2_turnaround") or ":" not in stripped:
                continue
            key, value = [x.strip() for x in stripped.split(":", 1)]
            if key == "alternatives":
                value = value.strip("[]")
                result[section][key] = [v.strip() for v in value.split(",") if v.strip()]
            elif key in ("active", "selection_metric"):
                result[section][key] = value
    except Exception:
        pass
    return result


def update_active_model_config(ml1: str | None, ml2: str | None) -> dict[str, Any]:
    path = REGISTRY_DIR / "active_model_config.yaml"
    if not path.exists():
        raise HTTPException(404, "active_model_config.yaml tidak ditemukan")
    allowed = {"random_forest", "xgboost"}
    if ml1 is not None and ml1 not in allowed:
        raise HTTPException(400, "Model ML1 tidak valid")
    if ml2 is not None and ml2 not in allowed:
        raise HTTPException(400, "Model ML2 tidak valid")

    lines = path.read_text(encoding="utf-8").splitlines()
    section: str | None = None
    out: list[str] = []
    for line in lines:
        stripped = line.strip()
        if not line.startswith((" ", "\t")) and stripped.endswith(":"):
            section = stripped[:-1]
            out.append(line)
            continue
        if stripped.startswith("active:"):
            if section == "ml1_eta" and ml1 is not None:
                out.append(f"  active: {ml1}")
                continue
            if section == "ml2_turnaround" and ml2 is not None:
                out.append(f"  active: {ml2}")
                continue
        out.append(line)
    tmp = path.with_suffix(".tmp")
    tmp.write_text("\n".join(out) + "\n", encoding="utf-8")
    os.replace(tmp, path)
    return parse_active_model_config()


def db():
    password = os.getenv("BIMA2_DB_PASSWORD")
    if not password:
        raise HTTPException(status_code=503, detail="BIMA2_DB_PASSWORD belum diset pada API.")
    return mysql.connector.connect(
        host=os.getenv("BIMA2_DB_HOST", "127.0.0.1"),
        port=int(os.getenv("BIMA2_DB_PORT", "3306")),
        user=os.getenv("BIMA2_DB_USER", "root"),
        password=password,
        database=os.getenv("BIMA2_DB_NAME", "jaes_bima2"),
    )


class LoginIn(BaseModel):
    username: str
    password: str


class UserIn(BaseModel):
    username: str
    password: str
    full_name: str = ""
    role: str = "Viewer"


class PasswordChangeIn(BaseModel):
    current_password: str
    new_password: str


class AdminResetPasswordIn(BaseModel):
    new_password: str


class ActiveModelsIn(BaseModel):
    ml1: str | None = None
    ml2: str | None = None

class CandidateActivationIn(BaseModel):
    ml1_candidate_id: str | None = None
    ml2_candidate_id: str | None = None


def token_for(row: dict[str, Any]) -> str:
    payload = {
        "sub": row["username"],
        "uid": row["id"],
        "role": row["role"],
        "full_name": row.get("full_name"),
        "exp": datetime.now(timezone.utc) + timedelta(hours=12),
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALG)


def current_user(authorization: str | None = Header(default=None)):
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(401, "Unauthorized")
    try:
        return jwt.decode(authorization[7:], JWT_SECRET, algorithms=[JWT_ALG])
    except Exception:
        raise HTTPException(401, "Token invalid")


def require_master(user=Depends(current_user)):
    if user.get("role") != "MasterAdmin":
        raise HTTPException(403, "MasterAdmin required")
    return user


@app.get("/api/health")
def health():
    state = read_json("current_operation_state.json")
    cctv = read_cctv_state("BENGKALIS")
    return {
        "status": "ok",
        "time": datetime.now().isoformat(),
        "operation_state_available": bool(state),
        "cctv_state_available": bool(cctv),
        "vessel_count": len(state.get("vessels", [])) if state else 0,
    }


@app.get("/api/realtime/system")
def realtime_system():
    state = read_json("current_operation_state.json")
    if state:
        cctv = read_cctv_state("BENGKALIS")
        if cctv:
            state = dict(state)
            state["vehicle_bengkalis"] = cctv
            state["cctv_updated_at"] = cctv.get("updated_at")
    return state


def port_state(port: str):
    state = read_json("current_operation_state.json")
    if not state:
        return {}
    p = port.upper()
    vessels = [
        v for v in state.get("vessels", [])
        if v.get("current_port") == p or v.get("destination_port") == p
    ]
    berths = {
        k: v for k, v in (state.get("berths") or {}).items()
        if k.startswith(p + "_")
    }
    result = dict(state)
    result["vessels"] = vessels
    result["berths"] = berths
    cctv = read_cctv_state(p)
    if p == "BENGKALIS":
        result["vehicle_bengkalis"] = cctv
    else:
        result["vehicle_pakning"] = cctv
    if cctv:
        result["cctv_updated_at"] = cctv.get("updated_at")
    return result


@app.get("/api/realtime/bengkalis")
def realtime_bengkalis():
    return port_state("BENGKALIS")


@app.get("/api/realtime/pakning")
def realtime_pakning():
    return port_state("PAKNING")


@app.get("/api/realtime/cctv/{port}")
def realtime_cctv(port: str):
    p = port.upper()
    if p not in ("BENGKALIS", "PAKNING"):
        raise HTTPException(404, "Port tidak valid")
    state = read_cctv_state(p)
    urls = stream_urls(p)
    return {
        "port": p,
        "camera_id": "cctv_bengkalis" if p == "BENGKALIS" else "cctv_pakning",
        "available": bool(state) or any(urls.values()),
        "updated_at": state.get("updated_at") if state else None,
        "state": state,
        **urls,
    }


@app.post("/api/auth/login")
def login(body: LoginIn):
    cn = db()
    cur = cn.cursor(dictionary=True)
    cur.execute(
        """SELECT u.id,u.username,u.password_hash,u.full_name,u.is_active,r.name role
           FROM users u JOIN roles r ON r.id=u.role_id
           WHERE u.username=%s""",
        (body.username,),
    )
    row = cur.fetchone()
    if not row or not row["is_active"] or not bcrypt.checkpw(
        body.password.encode(), row["password_hash"].encode()
    ):
        cur.close()
        cn.close()
        raise HTTPException(401, "Login gagal")

    cur.execute("UPDATE users SET last_login=NOW() WHERE id=%s", (row["id"],))
    cn.commit()
    cur.close()
    cn.close()
    return {
        "access_token": token_for(row),
        "token_type": "bearer",
        "role": row["role"],
    }


@app.get("/api/auth/me")
def me(user=Depends(current_user)):
    return {
        "username": user["sub"],
        "role": user["role"],
        "full_name": user.get("full_name"),
    }


@app.post("/api/auth/change-password")
def change_password(body: PasswordChangeIn, user=Depends(current_user)):
    if len(body.new_password) < 8:
        raise HTTPException(400, "Password baru minimal 8 karakter")
    cn = db()
    cur = cn.cursor(dictionary=True)
    cur.execute(
        "SELECT id,password_hash FROM users WHERE username=%s AND is_active=1",
        (user["sub"],),
    )
    row = cur.fetchone()
    if not row or not bcrypt.checkpw(body.current_password.encode(), row["password_hash"].encode()):
        cur.close(); cn.close()
        raise HTTPException(401, "Password saat ini salah")
    new_hash = bcrypt.hashpw(body.new_password.encode(), bcrypt.gensalt()).decode()
    cur.execute("UPDATE users SET password_hash=%s WHERE id=%s", (new_hash, row["id"]))
    cn.commit(); cur.close(); cn.close()
    return {"ok": True, "message": "Password berhasil diubah"}


@app.post("/api/inspection/users/{username}/reset-password")
def reset_user_password(username: str, body: AdminResetPasswordIn, user=Depends(require_master)):
    if len(body.new_password) < 8:
        raise HTTPException(400, "Password baru minimal 8 karakter")
    cn = db()
    cur = cn.cursor(dictionary=True)
    cur.execute("SELECT id FROM users WHERE username=%s", (username,))
    row = cur.fetchone()
    if not row:
        cur.close(); cn.close()
        raise HTTPException(404, "User tidak ditemukan")
    new_hash = bcrypt.hashpw(body.new_password.encode(), bcrypt.gensalt()).decode()
    cur.execute("UPDATE users SET password_hash=%s,is_active=1 WHERE id=%s", (new_hash, row["id"]))
    cn.commit(); cur.close(); cn.close()
    return {"ok": True, "username": username, "message": "Password berhasil direset"}


@app.get("/api/inspection/reliability/summary")
def reliability_summary(user=Depends(current_user)):
    cn = db()
    cur = cn.cursor(dictionary=True)
    try:
        cur.execute(
            """SELECT COUNT(*) event_count,
                      AVG(absolute_error_minutes) mae_minutes,
                      SUM(CASE WHEN analysis_status IN ('NEW','NEEDS_REVIEW')
                               THEN 1 ELSE 0 END) needs_review
               FROM reliability_result"""
        )
        row = cur.fetchone() or {}
    except mysql.connector.Error:
        row = {"event_count": 0, "mae_minutes": None, "needs_review": 0}
    cur.close()
    cn.close()
    return row


def avg(values: list[float]) -> float | None:
    return round(sum(values) / len(values), 3) if values else None


def build_inspection_overview() -> dict[str, Any]:
    state = read_json("current_operation_state.json")
    cctv = read_cctv_state("BENGKALIS")
    vessels = state.get("vessels", []) if state else []
    berths = state.get("berths", {}) if state else {}
    occupied = sum(1 for b in berths.values() if b.get("status") == "OCCUPIED")
    berth_total = len(berths)
    turnarounds = [float(v["turnaround_corrected_min"]) for v in vessels if v.get("turnaround_corrected_min") is not None]
    speeds = [float(v["sog"]) for v in vessels if v.get("sog") is not None]
    distances = [float(v["berth_distance_nm"]) for v in vessels if v.get("berth_distance_nm") is not None]
    queue_car = int(cctv.get("car_queue_current", 0) or 0)
    queue_motor = int(cctv.get("motor_queue_current", 0) or 0)

    vessel_rows = []
    for v in vessels:
        eta_base = v.get("eta_baseline_min")
        eta_corr = v.get("eta_corrected_min")
        eta_correction = None
        if eta_base is not None and eta_corr is not None:
            eta_correction = round(float(eta_corr) - float(eta_base), 3)
        vessel_rows.append({
            "mmsi": v.get("mmsi"),
            "shipname": v.get("shipname"),
            "state": v.get("operational_state"),
            "current_port": v.get("current_port"),
            "destination_port": v.get("destination_port"),
            "eta_baseline_min": eta_base,
            "eta_corrected_min": eta_corr,
            "eta_correction_min": eta_correction,
            "eta_timestamp": v.get("eta_timestamp"),
            "turnaround_min": v.get("turnaround_corrected_min"),
            "etd_timestamp": v.get("etd_timestamp"),
            "speed_kn": v.get("sog"),
            "distance_to_berth_nm": v.get("berth_distance_nm"),
            "nearest_berth": v.get("nearest_berth"),
            "data_quality": v.get("data_quality"),
        })

    parameters = [
        {
            "key": "eta_deviation",
            "label": "ETA deviation",
            "value": None,
            "unit": "min",
            "categories": ["Small", "Moderate", "Large"],
            "availability": "AWAITING_REFERENCE_ARRIVAL",
            "note": "Memerlukan reference/actual arrival untuk menghitung deviasi ETA sesuai metodologi.",
        },
        {
            "key": "headway_gap",
            "label": "Headway gap",
            "value": None,
            "unit": "min",
            "categories": ["Short", "Normal", "Long"],
            "availability": "AWAITING_SERVICE_EVENTS",
            "note": "Memerlukan event keberangkatan berurutan pada koridor.",
        },
        {
            "key": "berth_occupancy",
            "label": "Berth occupancy",
            "value": occupied,
            "unit": f"/{berth_total or 4} berth",
            "ratio": round(occupied / berth_total, 3) if berth_total else None,
            "categories": ["Free", "Soon Available", "Occupied"],
            "availability": "LIVE" if berth_total else "NO_DATA",
        },
        {
            "key": "queue_pressure",
            "label": "Queue pressure",
            "value": queue_car + queue_motor,
            "unit": "kendaraan",
            "ratio": None,
            "categories": ["Low", "Medium", "High"],
            "availability": "LIVE_COUNT" if cctv else "NO_CCTV_STATE",
            "note": "Rasio pressure menunggu kapasitas layanan aktif; dashboard tetap menampilkan antrean aktual CCTV.",
        },
        {
            "key": "turnaround_time",
            "label": "Turnaround time",
            "value": avg(turnarounds),
            "unit": "min",
            "categories": ["Short", "Normal", "Long"],
            "availability": "LIVE" if turnarounds else "NO_DATA",
        },
        {
            "key": "vessel_speed",
            "label": "Vessel speed",
            "value": avg(speeds),
            "unit": "kn",
            "categories": ["Low", "Normal", "High"],
            "availability": "LIVE" if speeds else "NO_DATA",
        },
        {
            "key": "distance_to_berth",
            "label": "Distance to berth",
            "value": round(min(distances), 3) if distances else None,
            "unit": "nm",
            "categories": ["Near", "Medium", "Far"],
            "availability": "LIVE" if distances else "NO_DATA",
        },
    ]

    rules = [
        {"rule": "R1", "if": "Berth Free AND Queue Pressure High", "then": "Depart Now"},
        {"rule": "R2", "if": "Berth Occupied AND Distance to Berth Near", "then": "Reduce Speed"},
        {"rule": "R3", "if": "Berth Occupied AND ETA Deviation Small", "then": "Hold Departure"},
        {"rule": "R4", "if": "Headway Short AND Berth Occupied", "then": "Hold Departure"},
        {"rule": "R5", "if": "Headway Long AND Queue Pressure High", "then": "Increase Service Priority"},
        {"rule": "R6", "if": "Turnaround Time Long AND Queue Pressure High", "then": "Alert Operator"},
        {"rule": "R7", "if": "ETA Deviation Large AND Headway Long", "then": "Reschedule Headway"},
        {"rule": "R8", "if": "Berth Soon Available AND Vessel Speed Normal", "then": "Maintain Speed"},
        {"rule": "R9", "if": "Queue Pressure High AND Headway Long AND Berth Free", "then": "Depart Now"},
        {"rule": "R10", "if": "Berth Occupied AND Queue Pressure High AND Turnaround Time Long", "then": "Alert Operator"},
    ]

    active = parse_active_model_config()
    ml1_registry = read_csv_rows(REGISTRY_DIR / "ml1_model_registry.csv")
    ml2_registry = read_csv_rows(REGISTRY_DIR / "ml2_model_registry.csv")

    def _norm_model_name(value: Any) -> str:
        s=str(value or "").strip().lower()
        if "xg" in s:
            return "xgboost"
        if "random" in s or "forest" in s or s=="rf":
            return "random_forest"
        return s.replace(" ","_")

    ml1_active=(active.get("ml1_eta") or {}).get("active")
    ml2_active=(active.get("ml2_turnaround") or {}).get("active")
    for row in ml1_registry:
        key=_norm_model_name(row.get("algorithm") or row.get("model"))
        row["model_key"]=key
        row["status"]="active" if key==ml1_active else ("baseline" if "baseline" in key else "candidate")
        row["artifact_exists"]=(ROOT/"models"/"ML1_ETA_CORRECTION"/"06_model_saved"/f"ml1_{key}.joblib").exists() if key and "baseline" not in key else False
    for row in ml2_registry:
        key=_norm_model_name(row.get("algorithm") or row.get("model"))
        row["model_key"]=key
        row["status"]="active" if key==ml2_active else "candidate"
        row["artifact_exists"]=(ROOT/"models"/"ML2_TURNAROUND_CORRECTION"/"06_model_saved"/f"ml2_{key}.joblib").exists()

    return {
        "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "system_health": {
            "operation_state": "OK" if state else "MISSING",
            "ais": "OK" if state.get("ais_updated_at") else "NO_DATA",
            "cctv": "OK" if cctv else "NO_STATE",
            "ml1": state.get("ml1_status", "UNKNOWN") if state else "UNKNOWN",
            "ml2": state.get("ml2_status", "UNKNOWN") if state else "UNKNOWN",
            "vessel_count": len(vessels),
            "berth_occupied": occupied,
            "berth_total": berth_total,
            "ais_updated_at": state.get("ais_updated_at") if state else None,
            "cctv_updated_at": cctv.get("updated_at") if cctv else None,
        },
        "parameters": parameters,
        "operational_condition": {
            "index": None,
            "level": "NOT_EVALUATED",
            "warning_levels": ["Normal", "Watch", "Warning", "Critical"],
            "responses": ["Maintain Operation", "Monitor Closely", "Adjust Operation", "Operator Intervention"],
            "note": "OCI/warning hanya diisi setelah membership function dan threshold kalibrasi aktif; tidak dibuat dari asumsi dashboard.",
        },
        "forecast_risks": [
            {"key": "arrival", "label": "Arrival risk", "status": "NOT_EVALUATED"},
            {"key": "berth_conflict", "label": "Berth conflict", "status": "NOT_EVALUATED"},
            {"key": "headway_instability", "label": "Headway instability", "status": "NOT_EVALUATED"},
            {"key": "queue_escalation", "label": "Queue escalation", "status": "NOT_EVALUATED"},
            {"key": "delay_propagation", "label": "Delay propagation", "status": "NOT_EVALUATED"},
        ],
        "fuzzy_rules": rules,
        "historical_policy": {
            "ais_folder": "data/01_DATA_SOURCE/AIS/historical",
            "vehicle_folder": "data/01_DATA_SOURCE/VEHICLE_HISTORICAL",
            "split_method": "chronological",
            "test_ratio": 0.20,
            "realtime_data_used_for_training": False,
            "train_does_not_auto_activate": True,
            "vehicle_observation_5min_enabled": False,
        },
        "models": {
            "active": active,
            "ml1_registry": ml1_registry,
            "ml2_registry": ml2_registry,
        },
        "cctv": {
            "state": cctv,
            **stream_urls("BENGKALIS"),
        },
        "vessels": vessel_rows,
        "diagnostics": state.get("diagnostics", {}) if state else {},
        "sections": [
            "realtime_system_health",
            "historical_analysis",
            "ml1_model_lab",
            "ml2_model_lab",
            "error_analysis",
            "model_comparison",
            "model_registry",
            "system_logs",
        ],
    }


@app.get("/api/inspection/overview")
def inspection_overview(user=Depends(current_user)):
    return build_inspection_overview()


@app.get("/api/inspection/cctv-audit")
def inspection_cctv_audit(user=Depends(current_user)):
    state = read_cctv_state("BENGKALIS")
    return {
        "port": "BENGKALIS",
        "updated_at": state.get("updated_at") if state else None,
        "state": state,
        **stream_urls("BENGKALIS"),
        "audit_note": "Bandingkan CCTV RAW dengan YOLO untuk menemukan kendaraan yang tidak terdeteksi/terhitung. Video YOLO hanya untuk Inspection; dashboard publik tetap RAW-only.",
    }


@app.get("/api/inspection/reliability/details")
def inspection_reliability_details(limit: int = 200, user=Depends(current_user)):
    limit = max(1, min(int(limit), 1000))
    cn = db()
    cur = cn.cursor(dictionary=True)
    summary = {
        "eta_events": 0, "eta_mae_min": None,
        "etd_events": 0, "etd_mae_min": None,
        "overall_events": 0, "overall_mae_min": None,
    }
    rows = []
    try:
        cur.execute("""SELECT
            SUM(CASE WHEN event_type='ARRIVAL' THEN 1 ELSE 0 END) eta_events,
            AVG(CASE WHEN event_type='ARRIVAL' THEN absolute_error_minutes END) eta_mae_min,
            SUM(CASE WHEN event_type='DEPARTURE' THEN 1 ELSE 0 END) etd_events,
            AVG(CASE WHEN event_type='DEPARTURE' THEN absolute_error_minutes END) etd_mae_min,
            COUNT(*) overall_events,
            AVG(absolute_error_minutes) overall_mae_min
          FROM reliability_result""")
        summary = cur.fetchone() or summary
        cur.execute("""SELECT id,mmsi,event_type,terminal,berth,predicted_at,actual_at,
                          error_minutes,absolute_error_minutes,data_quality,
                          ml1_model_id,ml2_model_id,analysis_status,analyst_note,created_at
                   FROM reliability_result
                   ORDER BY actual_at DESC LIMIT %s""", (limit,))
        rows = cur.fetchall()
    except mysql.connector.Error:
        rows = []
    cur.close(); cn.close()
    return {"summary": summary, "rows": rows}


@app.get("/api/inspection/model-corrections")
def inspection_model_corrections(user=Depends(current_user)):
    state = read_json("current_operation_state.json")
    active = parse_active_model_config()
    current = []
    for v in state.get("vessels", []) if state else []:
        eta_base = v.get("eta_baseline_min")
        eta_corr = v.get("eta_corrected_min")
        eta_delta = None
        if eta_base is not None and eta_corr is not None:
            eta_delta = round(float(eta_corr) - float(eta_base), 3)
        ta_base = v.get("turnaround_base_min")
        ta_corr = v.get("turnaround_corrected_min")
        ta_delta = v.get("turnaround_correction_min")
        if ta_delta is None and ta_base is not None and ta_corr is not None:
            ta_delta = round(float(ta_corr) - float(ta_base), 3)
        current.append({
            "mmsi": v.get("mmsi"),
            "shipname": v.get("shipname"),
            "state": v.get("operational_state"),
            "eta_base_min": eta_base,
            "eta_corrected_min": eta_corr,
            "ml1_correction_min": eta_delta,
            "turnaround_base_min": ta_base,
            "turnaround_corrected_min": ta_corr,
            "ml2_correction_min": ta_delta,
            "eta_timestamp": v.get("eta_timestamp"),
            "etd_timestamp": v.get("etd_timestamp"),
            "data_quality": v.get("data_quality"),
        })

    historical = {
        "samples": 0,
        "avg_ml1_correction_min": None,
        "avg_abs_ml1_correction_min": None,
        "avg_ml2_correction_min": None,
        "avg_abs_ml2_correction_min": None,
    }
    cn = None
    try:
        cn = db(); cur = cn.cursor(dictionary=True)
        cur.execute("""SELECT COUNT(*) samples,
                    AVG(eta_corrected_min-eta_base_min) avg_ml1_correction_min,
                    AVG(ABS(eta_corrected_min-eta_base_min)) avg_abs_ml1_correction_min,
                    AVG(turnaround_correction_min) avg_ml2_correction_min,
                    AVG(ABS(turnaround_correction_min)) avg_abs_ml2_correction_min
             FROM prediction_history
             WHERE eta_base_min IS NOT NULL OR turnaround_correction_min IS NOT NULL""")
        historical = cur.fetchone() or historical
        cur.close(); cn.close()
    except Exception:
        try:
            if cn: cn.close()
        except Exception:
            pass

    return {
        "active_models": active,
        "ml1_status": state.get("ml1_status") if state else None,
        "ml2_status": state.get("ml2_status") if state else None,
        "current": current,
        "historical": historical,
        "note": "Koreksi ditampilkan hanya jika tersedia dari keluaran model. Nilai fallback tidak diberi label sebagai koreksi ML.",
    }



def training_status_payload() -> dict[str, Any]:
    if not TRAINING_STATUS.exists():
        return {"status":"IDLE","message":"Belum ada retraining baru."}
    try:
        return json.loads(TRAINING_STATUS.read_text(encoding="utf-8"))
    except Exception:
        return {"status":"UNKNOWN","message":"training_status.json tidak dapat dibaca."}


def training_candidates() -> list[dict[str, Any]]:
    rows=read_csv_rows(TRAINING_REGISTRY)
    rows.sort(key=lambda r: str(r.get("created_at") or ""), reverse=True)
    return rows


def _candidate_by_id(candidate_id: str) -> dict[str, Any] | None:
    for row in training_candidates():
        if row.get("candidate_id")==candidate_id:
            return row
    return None


def _rewrite_candidate_status(active_ids: set[str]) -> None:
    if not TRAINING_REGISTRY.exists():
        return
    rows=read_csv_rows(TRAINING_REGISTRY)
    if not rows:
        return
    # Do not persist API-normalized convenience columns.
    fields=["candidate_id","run_id","scope","algorithm","created_at","mae_min","rmse_min","r2","n_test","artifact_path","source_files","source_rows","status"]
    for row in rows:
        if row.get("candidate_id") in active_ids:
            row["status"]="ACTIVE"
        elif row.get("status")=="ACTIVE" and row.get("scope") in {(_candidate_by_id(x) or {}).get("scope") for x in active_ids}:
            row["status"]="CANDIDATE"
    tmp=TRAINING_REGISTRY.with_suffix(".tmp")
    with tmp.open("w",encoding="utf-8",newline="") as f:
        w=csv.DictWriter(f,fieldnames=fields)
        w.writeheader()
        for row in rows:
            w.writerow({k:row.get(k) for k in fields})
    os.replace(tmp,TRAINING_REGISTRY)


@app.get("/api/inspection/training/status")
def inspection_training_status(user=Depends(current_user)):
    return {"status":training_status_payload(),"candidates":training_candidates()}


@app.post("/api/inspection/training/run")
def inspection_training_run(user=Depends(require_master)):
    current=training_status_payload()
    if str(current.get("status","")).upper() in {"RUNNING","STARTING"}:
        raise HTTPException(409,"Training masih berjalan.")
    if not RETRAIN_SCRIPT.exists():
        raise HTTPException(500,f"Script retraining tidak ditemukan: {RETRAIN_SCRIPT}")
    TRAINING_STATUS.parent.mkdir(parents=True,exist_ok=True)
    initial={"status":"STARTING","requested_at":datetime.now().astimezone().isoformat(timespec="seconds"),"requested_by":user.get("sub"),"message":"Menyiapkan retraining dari seluruh data histori."}
    TRAINING_STATUS.write_text(json.dumps(initial,indent=2,ensure_ascii=False),encoding="utf-8")
    subprocess.Popen([sys.executable,str(RETRAIN_SCRIPT)],cwd=str(ROOT),env=os.environ.copy(),creationflags=getattr(subprocess,"CREATE_NO_WINDOW",0))
    return {"ok":True,"status":initial}


@app.post("/api/inspection/training/activate")
def inspection_training_activate(body: CandidateActivationIn, user=Depends(require_master)):
    if not body.ml1_candidate_id and not body.ml2_candidate_id:
        raise HTTPException(400,"Pilih minimal satu candidate model.")
    selected=[]; ml1_alg=None; ml2_alg=None
    for scope,cid in (("ML1",body.ml1_candidate_id),("ML2",body.ml2_candidate_id)):
        if not cid:
            continue
        row=_candidate_by_id(cid)
        if not row:
            raise HTTPException(404,f"Candidate tidak ditemukan: {cid}")
        if str(row.get("scope")).upper()!=scope:
            raise HTTPException(400,f"Candidate {cid} bukan {scope}.")
        artifact=ROOT / str(row.get("artifact_path"))
        if not artifact.exists():
            raise HTTPException(404,f"Artifact candidate tidak ditemukan: {artifact}")
        alg=str(row.get("algorithm"))
        if alg not in {"random_forest","xgboost"}:
            raise HTTPException(400,f"Algorithm candidate tidak valid: {alg}")
        if scope=="ML1":
            target=ROOT/"models"/"ML1_ETA_CORRECTION"/"06_model_saved"/f"ml1_{alg}.joblib"; ml1_alg=alg
        else:
            target=ROOT/"models"/"ML2_TURNAROUND_CORRECTION"/"06_model_saved"/f"ml2_{alg}.joblib"; ml2_alg=alg
        target.parent.mkdir(parents=True,exist_ok=True)
        shutil.copy2(artifact,target)
        selected.append({"scope":scope,"candidate_id":cid,"algorithm":alg,"artifact":str(artifact.relative_to(ROOT))})
    active=update_active_model_config(ml1_alg,ml2_alg)
    _rewrite_candidate_status({x["candidate_id"] for x in selected})
    ACTIVATION_LOG.parent.mkdir(parents=True,exist_ok=True)
    with ACTIVATION_LOG.open("a",encoding="utf-8") as f:
        f.write(json.dumps({"timestamp":datetime.now().astimezone().isoformat(timespec="seconds"),"user":user.get("sub"),"selected":selected,"active":active},ensure_ascii=False)+"\\n")
    return {"ok":True,"active":active,"selected":selected}


@app.post("/api/inspection/models/active")
def inspection_set_active_models(body: ActiveModelsIn, user=Depends(require_master)):
    if body.ml1 is None and body.ml2 is None:
        raise HTTPException(400, "Tidak ada model yang dipilih")
    active = update_active_model_config(body.ml1, body.ml2)
    return {
        "ok": True,
        "active": active,
        "note": "Konfigurasi aktif diperbarui. Pipeline/operation-state perlu membaca ulang konfigurasi sebelum perubahan terlihat pada prediksi realtime.",
    }


def tail_text(path: Path, max_lines: int = 80, max_chars: int = 9000) -> str:
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
        lines = text.splitlines()[-max_lines:]
        return "\n".join(lines)[-max_chars:]
    except Exception:
        return ""


@app.get("/api/inspection/logs")
def inspection_logs(user=Depends(current_user)):
    files: list[Path] = []
    for root in LOG_DIRS:
        if not root.exists():
            continue
        try:
            files.extend(
                p for p in root.rglob("*")
                if p.is_file() and p.suffix.lower() in {".log", ".txt", ".json"}
            )
        except Exception:
            pass
    files.sort(key=lambda p: p.stat().st_mtime if p.exists() else 0, reverse=True)
    return [
        {
            "name": str(p.relative_to(ROOT)),
            "modified_at": datetime.fromtimestamp(p.stat().st_mtime).astimezone().isoformat(timespec="seconds"),
            "tail": tail_text(p),
        }
        for p in files[:8]
    ]


@app.get("/api/inspection/users")
def list_users(user=Depends(require_master)):
    cn = db()
    cur = cn.cursor(dictionary=True)
    cur.execute(
        """SELECT u.id,u.username,u.full_name,r.name role,u.is_active,u.last_login
           FROM users u JOIN roles r ON r.id=u.role_id
           ORDER BY u.id"""
    )
    rows = cur.fetchall()
    cur.close()
    cn.close()
    return rows


@app.post("/api/inspection/users")
def add_user(body: UserIn, user=Depends(require_master)):
    cn = db()
    cur = cn.cursor(dictionary=True)
    cur.execute("SELECT id FROM roles WHERE name=%s", (body.role,))
    role = cur.fetchone()
    if not role:
        cur.close()
        cn.close()
        raise HTTPException(400, "Role tidak valid")

    password_hash = bcrypt.hashpw(body.password.encode(), bcrypt.gensalt()).decode()
    try:
        cur.execute(
            """INSERT INTO users(username,password_hash,full_name,role_id,is_active)
               VALUES(%s,%s,%s,%s,1)""",
            (body.username, password_hash, body.full_name, role["id"]),
        )
        cn.commit()
    except mysql.connector.IntegrityError:
        cur.close()
        cn.close()
        raise HTTPException(409, "Username sudah ada")

    cur.close()
    cn.close()
    return {"ok": True}
