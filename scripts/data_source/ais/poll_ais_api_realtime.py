"""Poll AIS API, keep only target Ro-Ro MMSIs inside Bengkalis-Pakning corridor.

Realtime input is inference-only. Historical training/validation files are never modified.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import time
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd
import requests
import yaml


def find_project_root() -> Path:
    here = Path(__file__).resolve()
    for p in [here.parent, *here.parents]:
        if (p / "config" / "project_config.yaml").exists():
            return p
    raise RuntimeError("Project root JAES_SIMULASI_BIMA2 tidak ditemukan.")


def load_yaml(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def haversine_nm(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r_km = 6371.0088
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = math.radians(lat2 - lat1), math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return (2 * r_km * math.asin(min(1.0, math.sqrt(a)))) / 1.852


def local_xy_nm(lat: float, lon: float, lat0: float, lon0: float) -> tuple[float, float]:
    # Equirectangular projection is sufficient for this short corridor.
    y = (lat - lat0) * 60.0
    x = (lon - lon0) * 60.0 * math.cos(math.radians(lat0))
    return x, y


def point_segment_distance_nm(lat: float, lon: float, a: tuple[float, float], b: tuple[float, float]) -> float:
    lat0 = (a[0] + b[0]) / 2.0
    lon0 = (a[1] + b[1]) / 2.0
    px, py = local_xy_nm(lat, lon, lat0, lon0)
    ax, ay = local_xy_nm(a[0], a[1], lat0, lon0)
    bx, by = local_xy_nm(b[0], b[1], lat0, lon0)
    vx, vy = bx - ax, by - ay
    wx, wy = px - ax, py - ay
    denom = vx * vx + vy * vy
    t = 0.0 if denom == 0 else max(0.0, min(1.0, (wx * vx + wy * vy) / denom))
    qx, qy = ax + t * vx, ay + t * vy
    return math.hypot(px - qx, py - qy)


def terminal_centers(root: Path, cfg: dict) -> dict[str, tuple[float, float]]:
    ports = cfg["ports"]
    centers = {}
    for name, item in ports.items():
        berths = item["berths"]
        centers[name] = (
            sum(float(b["lat"]) for b in berths) / len(berths),
            sum(float(b["lon"]) for b in berths) / len(berths),
        )
    return centers


def unwrap_payload(payload: Any) -> list[dict]:
    if isinstance(payload, list):
        return [x for x in payload if isinstance(x, dict)]
    if isinstance(payload, dict):
        for key in ("data", "results", "ships", "vessels", "items"):
            if isinstance(payload.get(key), list):
                return [x for x in payload[key] if isinstance(x, dict)]
        return [payload]
    return []


def safe_float(v: Any) -> float | None:
    try:
        if v is None or v == "":
            return None
        x = float(v)
        return x if math.isfinite(x) else None
    except Exception:
        return None


def parse_ts(v: Any, naive_timezone: str | None = None) -> pd.Timestamp | None:
    if v is None or v == "":
        return None
    try:
        ts = pd.Timestamp(v)
        if ts.tzinfo is None:
            ts = ts.tz_localize(naive_timezone or "UTC")
        return ts.tz_convert("UTC")
    except Exception:
        return None


def normalize_one(raw: dict, fmap: dict, qc: dict, centers: dict, buffer_nm: float, whitelist: set[int]) -> dict | None:
    try:
        mmsi = int(raw.get(fmap["mmsi"]))
    except Exception:
        return None
    if mmsi not in whitelist:
        return None

    lat = safe_float(raw.get(fmap["latitude"]))
    lon = safe_float(raw.get(fmap["longitude"]))
    if lat is None or lon is None or not (-90 <= lat <= 90 and -180 <= lon <= 180):
        return None

    port_names = list(centers)
    if len(port_names) != 2:
        raise ValueError("Corridor filter requires exactly two terminals in project_config.yaml.")
    corridor_distance = point_segment_distance_nm(lat, lon, centers[port_names[0]], centers[port_names[1]])
    if corridor_distance > buffer_nm:
        return None

    naive_tz = str(qc.get("naive_timestamp_timezone", "Asia/Jakarta"))
    provider_observation = parse_ts(raw.get(fmap["timestamp"]), naive_tz)
    timestamp = provider_observation if provider_observation is not None else pd.Timestamp.now(tz="UTC")
    if provider_observation is None:
        observation_basis = "SERVER_FALLBACK"
    else:
        observation_basis = "PROVIDER_ASSUMED_TZ" if pd.Timestamp(raw.get(fmap["timestamp"])).tzinfo is None else "PROVIDER_EXPLICIT_OFFSET"
    update_ts = parse_ts(raw.get(fmap.get("ais_update_at", "update_at")), naive_tz)
    data_age = (timestamp - update_ts).total_seconds() if update_ts is not None else None
    if data_age is not None:
        data_age = max(0.0, float(data_age))

    heading = safe_float(raw.get(fmap.get("heading", "heading")))
    turn = safe_float(raw.get(fmap.get("turn", "turn")))
    if heading == float(qc.get("heading_not_available", 511)):
        heading = None
    if turn == float(qc.get("turn_not_available", -128)):
        turn = None

    sog = safe_float(raw.get(fmap["sog"]))
    cog = safe_float(raw.get(fmap["cog"]))
    nearest_port = min(centers, key=lambda p: haversine_nm(lat, lon, centers[p][0], centers[p][1]))
    nearest_port_distance = haversine_nm(lat, lon, centers[nearest_port][0], centers[nearest_port][1])
    stale_limit = float(qc.get("max_data_age_seconds", 300))
    quality = "UNKNOWN_AGE" if data_age is None else ("FRESH" if data_age <= 60 else "DELAYED" if data_age <= stale_limit else "STALE")

    return {
        "timestamp": timestamp.isoformat(),
        "provider_observation_basis": observation_basis,
        "mmsi": mmsi,
        "latitude": lat,
        "longitude": lon,
        "sog": sog,
        "cog": cog,
        "heading": heading,
        "turn": turn,
        "nav_status": raw.get(fmap.get("nav_status", "status")),
        "accuracy": raw.get(fmap.get("accuracy", "accuracy")),
        "imo": raw.get(fmap.get("imo", "imo")),
        "callsign": raw.get(fmap.get("callsign", "callsign")),
        "shipname": raw.get(fmap.get("shipname", "shipname")),
        "ship_type": raw.get(fmap.get("ship_type", "ship_type")),
        "draught": raw.get(fmap.get("draught", "draught")),
        "destination_reported": raw.get(fmap.get("destination_reported", "destination")),
        "ais_update_at": update_ts.isoformat() if update_ts is not None else None,
        "data_age_seconds": data_age,
        "data_quality": quality,
        "inference_allowed": bool(quality != "STALE" or qc.get("allow_stale_for_inference", False)),
        "corridor_distance_nm": corridor_distance,
        "nearest_terminal": nearest_port,
        "nearest_terminal_distance_nm": nearest_port_distance,
        "accepted_by": "MMSI_WHITELIST_AND_CORRIDOR",
    }


def atomic_csv(df: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    df.to_csv(tmp, index=False)
    os.replace(tmp, path)



def atomic_json(payload: dict, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    os.replace(tmp, path)

def append_csv(df: pd.DataFrame, path: Path) -> None:
    if df.empty:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(path, mode="a", index=False, header=not path.exists())


def append_raw(payload: Any, raw_dir: Path) -> None:
    raw_dir.mkdir(parents=True, exist_ok=True)
    target = raw_dir / f"ais_api_raw_{datetime.now().strftime('%Y%m%d')}.jsonl"
    with target.open("a", encoding="utf-8") as f:
        f.write(json.dumps({"received_at": datetime.now().astimezone().isoformat(), "payload": payload}, ensure_ascii=False, default=str) + "\n")


def rejection_reason(raw: dict, fmap: dict, centers: dict, buffer_nm: float, whitelist: set[int]) -> tuple[str | None, int | None]:
    """Return why an API row is rejected. MMSI is never rewritten/aliased."""
    try:
        mmsi=int(raw.get(fmap["mmsi"]))
    except Exception:
        return "INVALID_MMSI", None
    if mmsi not in whitelist:
        return "MMSI_NOT_IN_WHITELIST", mmsi
    lat=safe_float(raw.get(fmap["latitude"]))
    lon=safe_float(raw.get(fmap["longitude"]))
    if lat is None or lon is None or not (-90 <= lat <= 90 and -180 <= lon <= 180):
        return "INVALID_POSITION", mmsi
    names=list(centers)
    if len(names)==2:
        d=point_segment_distance_nm(lat, lon, centers[names[0]], centers[names[1]])
        if d > buffer_nm:
            return "OUTSIDE_CORRIDOR", mmsi
    return None, mmsi


def poll_once(root: Path, cfg: dict) -> tuple[int, int]:
    ais = cfg["ais"]
    api = ais["api"]
    endpoint = str(api.get("endpoint") or os.environ.get(api.get("endpoint_env", "AIS_API_URL"), "")).strip()
    if not endpoint:
        raise RuntimeError("AIS API endpoint belum tersedia. Set environment variable AIS_API_URL atau isi config/project_config.yaml > ais.api.endpoint.")

    headers = {"Accept": "application/json"}
    key = os.environ.get(str(api.get("api_key_env", "AIS_API_KEY")), "").strip()
    if key:
        scheme = str(api.get("auth_scheme", "Bearer")).strip()
        headers[str(api.get("auth_header", "Authorization"))] = f"{scheme} {key}".strip()

    r = requests.get(endpoint, headers=headers, timeout=float(api.get("timeout_seconds", 15)))
    r.raise_for_status()
    payload = r.json()
    if bool(api.get("store_raw_payload", False)):
        append_raw(payload, root / api["raw_dir"])

    rows = unwrap_payload(payload)
    whitelist = {int(x) for x in ais["vessel_filter"]["mmsi_whitelist"]}
    centers = terminal_centers(root, cfg)
    fmap = ais["field_map"]
    qc = ais.get("quality_control", {})
    buffer_nm = float(ais["corridor_filter"].get("buffer_nm", 2.0))
    normalized = [normalize_one(x, fmap, qc, centers, buffer_nm, whitelist) for x in rows]
    normalized = [x for x in normalized if x is not None]

    rejected=[]
    for raw in rows:
        reason, reported_mmsi = rejection_reason(raw, fmap, centers, buffer_nm, whitelist)
        if reason:
            rejected.append({"mmsi": reported_mmsi, "reason": reason})

    rejected=[]
    for raw in rows:
        reason, reported_mmsi = rejection_reason(raw, fmap, centers, buffer_nm, whitelist)
        if reason:
            rejected.append({"mmsi": reported_mmsi, "reason": reason})
    out = pd.DataFrame(normalized)
    if not out.empty:
        out["timestamp"] = pd.to_datetime(out["timestamp"], utc=True)
        out = out.sort_values("timestamp").drop_duplicates("mmsi", keep="last").sort_values("mmsi")
        out["timestamp"] = out["timestamp"].astype(str)
    output_csv = root / api["output_file"]
    atomic_csv(out, output_csv)

    # Canonical realtime state for ETA/dashboard: one latest row per target MMSI.
    # This is current state only, not a historical archive.
    vessels = json.loads(out.to_json(orient="records")) if not out.empty else []
    state_payload = {
        "updated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "source": "AIS_API",
        "received_count": len(rows),
        "accepted_count": len(vessels),
        "whitelist_mmsi": sorted(whitelist),
        "rejected": rejected,
        "vessels": vessels,
    }
    atomic_json(state_payload, output_csv.parent / "ais_current_state.json")

    if bool(api.get("append_history", False)):
        # Keep the existing historical CSV schema and column order unchanged.
        append_csv(pd.DataFrame(normalized).drop(columns=["provider_observation_basis"],errors="ignore"), root / api["history_file"])
    return len(rows), len(vessels)


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--once", action="store_true", help="Poll once then exit")
    p.add_argument("--config", default="config/project_config.yaml")
    args = p.parse_args()
    root = find_project_root()
    cfg = load_yaml(root / args.config)
    interval = float(cfg["ais"]["api"].get("poll_seconds", 10))
    while True:
        try:
            received, accepted = poll_once(root, cfg)
            print(f"[{datetime.now().astimezone().isoformat(timespec='seconds')}] AIS received={received}; accepted={accepted}", flush=True)
        except KeyboardInterrupt:
            break
        except Exception as exc:
            print(f"AIS API ERROR: {exc}", flush=True)
            if args.once:
                raise
        if args.once:
            break
        time.sleep(max(1.0, interval))


if __name__ == "__main__":
    main()
