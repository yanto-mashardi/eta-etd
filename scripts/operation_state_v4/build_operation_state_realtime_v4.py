"""Build rolling realtime operation_state_5min.csv from AIS API + CCTV.

ML1/ML2 artifacts remain those trained/validated from historical data. Realtime data are
used only for inference. Destination text reported by AIS is never used to accept/reject a vessel.
"""
from __future__ import annotations

import argparse
import math
import os
import time
from datetime import datetime
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
import yaml

MOTOR_PCE_FACTOR = 0.25
ML1_NUM = ["distance_to_destination_nm", "sog_kn", "cog_deg", "heading_error_deg", "eta_baseline_min", "hour", "day_of_week"]
ML1_CAT = ["mmsi", "origin_port", "destination_port"]


def find_root() -> Path:
    here = Path(__file__).resolve()
    for p in [here.parent, *here.parents]:
        if (p / "config" / "project_config_realtime_v4.yaml").exists():
            return p
    raise RuntimeError("Project root JAES_SIMULASI_BIMA2 tidak ditemukan")


def yload(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def haversine_nm(lat1, lon1, lat2, lon2):
    r_km = 6371.0088
    p1, p2 = math.radians(float(lat1)), math.radians(float(lat2))
    dp, dl = math.radians(float(lat2) - float(lat1)), math.radians(float(lon2) - float(lon1))
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return (2 * r_km * math.asin(min(1.0, math.sqrt(a)))) / 1.852


def bearing_deg(lat1, lon1, lat2, lon2):
    p1, p2, dl = math.radians(lat1), math.radians(lat2), math.radians(lon2 - lon1)
    y = math.sin(dl) * math.cos(p2)
    x = math.cos(p1) * math.sin(p2) - math.sin(p1) * math.cos(p2) * math.cos(dl)
    return (math.degrees(math.atan2(y, x)) + 360.0) % 360.0


def angle_diff(a, b):
    if pd.isna(a) or pd.isna(b):
        return np.nan
    return abs((float(a) - float(b) + 180.0) % 360.0 - 180.0)


def normalize_model_key(name: str) -> str:
    return str(name).strip().lower().replace(" ", "_")


def load_ports(root: Path):
    ports = yload(root / "config" / "ports_berths.yaml")["ports"]
    out = {}
    for p, item in ports.items():
        out[p] = {
            "berths": item["berths"],
            "center": (
                sum(float(b["lat"]) for b in item["berths"]) / len(item["berths"]),
                sum(float(b["lon"]) for b in item["berths"]) / len(item["berths"]),
            ),
        }
    return out


def nearest_berth(lat, lon, ports):
    rows = []
    for terminal, item in ports.items():
        for b in item["berths"]:
            rows.append((haversine_nm(lat, lon, b["lat"], b["lon"]), terminal, b["id"]))
    return min(rows, key=lambda x: x[0])


def infer_direction(row, ports, berth_radius_nm=0.15):
    lat, lon = float(row.latitude), float(row.longitude)
    sog = float(row.sog) if pd.notna(row.sog) else 0.0
    cog = float(row.cog) if pd.notna(row.cog) else np.nan
    berth_d, nearest_port, berth_id = nearest_berth(lat, lon, ports)
    names = list(ports)
    other = names[1] if nearest_port == names[0] else names[0]

    if berth_d <= berth_radius_nm and sog <= 1.0:
        return other, nearest_port, f"BERTHED_{nearest_port.upper()}", berth_id, berth_d

    candidates = []
    for p, item in ports.items():
        d = haversine_nm(lat, lon, item["center"][0], item["center"][1])
        b = bearing_deg(lat, lon, item["center"][0], item["center"][1])
        e = angle_diff(cog, b) if pd.notna(cog) else d * 20.0
        candidates.append((e, d, p))
    destination = min(candidates, key=lambda x: (x[0], x[1]))[2]
    origin = names[1] if destination == names[0] else names[0]
    state = "SAILING" if sog >= 3.0 else "MANEUVERING"
    return origin, destination, state, berth_id if berth_d <= berth_radius_nm else None, berth_d


def load_ml1_models(root: Path):
    model_dir = root / "models" / "ML1_ETA_CORRECTION" / "06_model_saved"
    models = {}
    for key, name in [("random_forest", "ml1_random_forest.joblib"), ("xgboost", "ml1_xgboost.joblib")]:
        p = model_dir / name
        if p.exists():
            models[key] = joblib.load(p)
    return models


def load_ml2_models(root: Path):
    model_dir = root / "models" / "ML2_TURNAROUND_CORRECTION" / "06_model_saved"
    all_path = model_dir / "ml2_turnaround_models.joblib"
    if all_path.exists():
        art = joblib.load(all_path)
        return {normalize_model_key(k): v for k, v in art["models"].items()}, art.get("features", []), art.get("base_by_vessel_terminal", {})
    selected = model_dir / "ml2_turnaround_selected.joblib"
    if selected.exists():
        art = joblib.load(selected)
        key = normalize_model_key(art.get("winner", "selected"))
        return {key: art["model"]}, art.get("features", []), art.get("base_by_vessel_terminal", {})
    return {}, [], {}


def capacity_table(root: Path):
    p = root / "config" / "vessel_capacity_realtime_v4.csv"
    if not p.exists():
        return {}
    d = pd.read_csv(p)
    return {str(int(r.mmsi)): float(r.capacity_pce) for _, r in d.iterrows()}


def latest_cctv(root: Path, cfg: dict):
    p = root / cfg["integration"]["cctv_state"]
    result = {}
    if not p.exists() or p.stat().st_size == 0:
        return result
    try:
        d = pd.read_csv(p)
        if d.empty:
            return result
        tcol = "timestamp_5min" if "timestamp_5min" in d.columns else "timestamp"
        d[tcol] = pd.to_datetime(d[tcol], errors="coerce")
        d = d.sort_values(tcol)
        for port, g in d.groupby(d.get("port", pd.Series(["BENGKALIS"] * len(d))).astype(str).str.upper()):
            r = g.iloc[-1]
            canonical = "Bengkalis" if port.startswith("BENG") else "Pakning" if port.startswith("PAK") else port.title()
            car_in = float(r.get("car_in", 0) or 0)
            motor_in = float(r.get("motor_in", 0) or 0)
            car_q = float(r.get("car_queue_current", 0) or 0)
            motor_q = float(r.get("motor_queue_current", 0) or 0)
            result[canonical] = {
                "car_rate_5min": car_in,
                "motor_rate_5min": motor_in,
                "pce_rate_5min": car_in + MOTOR_PCE_FACTOR * motor_in,
                "queue_pce": car_q + MOTOR_PCE_FACTOR * motor_q,
                "source": "CCTV_REALTIME",
                "timestamp": r.get(tcol),
            }
    except Exception:
        return {}
    return result


def historical_rate(root: Path, terminal: str, when: pd.Timestamp):
    try:
        if str(root) not in os.sys.path:
            os.sys.path.insert(0, str(root))
        from scripts.v3_paths import processed_root
        p = processed_root(root) / "ml2" / "vehicle_rate_5min.csv"
        if not p.exists():
            return None
        d = pd.read_csv(p)
        local = when.tz_convert("Asia/Jakarta") if when.tzinfo else when
        minute = local.hour * 60 + (local.minute // 5) * 5
        q = d[(d.terminal.astype(str).str.lower() == terminal.lower()) &
              (pd.to_numeric(d.arrival_dow, errors="coerce") == local.dayofweek) &
              (pd.to_numeric(d.minute_of_day, errors="coerce") == minute)]
        if q.empty:
            return None
        r = q.iloc[0]
        return {"car_rate_5min": float(r.car_rate_5min), "motor_rate_5min": float(r.motor_rate_5min),
                "pce_rate_5min": float(r.pce_rate_5min), "queue_pce": np.nan, "source": "HISTORICAL_PROFILE_FALLBACK"}
    except Exception:
        return None


def base_turnaround(base_map: dict, mmsi: str, destination: str):
    for key in [(mmsi, destination), (int(mmsi) if mmsi.isdigit() else mmsi, destination)]:
        if key in base_map:
            return float(base_map[key])
    vals = [float(v) for v in base_map.values() if pd.notna(v)]
    return float(np.median(vals)) if vals else np.nan


def predict_ml2(models, features, base_map, row, rate, capacity, arrival_time):
    out = {}
    if not models or not features or pd.isna(arrival_time):
        return out
    local_arrival = arrival_time.tz_convert("Asia/Jakarta") if arrival_time.tzinfo else arrival_time
    base = base_turnaround(base_map, str(row.mmsi), row.destination_port)
    x = pd.DataFrame([{
        "mmsi": str(row.mmsi),
        "destination_port": row.destination_port,
        "arrival_hour": int(local_arrival.hour),
        "arrival_dow": int(local_arrival.dayofweek),
        "capacity_pce": float(capacity) if pd.notna(capacity) else np.nan,
        "car_rate_5min": float(rate.get("car_rate_5min", 0)),
        "motor_rate_5min": float(rate.get("motor_rate_5min", 0)),
        "pce_rate_5min": float(rate.get("pce_rate_5min", 0)),
    }])
    for key, model in models.items():
        correction = float(model.predict(x[features])[0])
        corrected = max(0.0, base + correction) if pd.notna(base) else np.nan
        out[key] = (base, correction, corrected)
    return out


def build_once(root: Path, cfg: dict):
    ais_path = root / cfg["data_source"]["ais"]["normalized_contract"]
    if not ais_path.exists():
        raise FileNotFoundError(f"AIS realtime belum tersedia: {ais_path}")
    ais = pd.read_csv(ais_path)
    if ais.empty:
        return 0
    ais["timestamp"] = pd.to_datetime(ais["timestamp"], errors="coerce", utc=True)
    ais = ais.dropna(subset=["timestamp", "mmsi", "latitude", "longitude"]).copy()
    ais["mmsi"] = ais.mmsi.astype("Int64").astype(str)
    for c in ["latitude", "longitude", "sog", "cog"]:
        ais[c] = pd.to_numeric(ais.get(c), errors="coerce")

    ports = load_ports(root)
    ml1 = load_ml1_models(root)
    ml2, ml2_features, base_map = load_ml2_models(root)
    capacities = capacity_table(root)
    cctv = latest_cctv(root, cfg)
    berth_radius = float(yload(root / "config" / "ais_source_config_v4.yaml")["ais"]["corridor_filter"].get("berth_radius_nm", 0.15))

    rows = []
    tick_minutes = int(cfg["integration"].get("tick_minutes", 5))
    for _, a in ais.iterrows():
        origin, dest, visual_state, berth_id, berth_distance = infer_direction(a, ports, berth_radius)
        d_dest = haversine_nm(a.latitude, a.longitude, ports[dest]["center"][0], ports[dest]["center"][1])
        target_bearing = bearing_deg(a.latitude, a.longitude, ports[dest]["center"][0], ports[dest]["center"][1])
        h_err = angle_diff(a.cog, target_bearing)
        sog = float(a.sog) if pd.notna(a.sog) else np.nan
        baseline = 0.0 if visual_state.startswith("BERTHED") else (d_dest / sog * 60.0 if pd.notna(sog) and sog > 0.3 else np.nan)
        tick = a.timestamp.floor(f"{tick_minutes}min")
        feat = pd.DataFrame([{
            "distance_to_destination_nm": d_dest,
            "sog_kn": sog,
            "cog_deg": a.cog,
            "heading_error_deg": h_err,
            "eta_baseline_min": baseline,
            "hour": int(a.timestamp.hour),
            "day_of_week": int(a.timestamp.dayofweek),
            "mmsi": str(a.mmsi),
            "origin_port": origin,
            "destination_port": dest,
        }])
        rec = {
            "record_type": "VESSEL_STATE", "simulation_tick": tick, "prediction_time": a.timestamp,
            "mmsi": str(a.mmsi), "shipname": a.get("shipname"), "latitude": a.latitude, "longitude": a.longitude,
            "sog_kn": sog, "cog_deg": a.cog, "heading": a.get("heading"), "visual_state": visual_state,
            "berth_id": berth_id, "origin_port": origin, "destination_port": dest,
            "distance_to_destination_nm": d_dest, "eta_baseline_min": baseline, "heading_error_deg": h_err,
            "capacity_pce": capacities.get(str(a.mmsi), np.nan),
            "data_age_seconds": a.get("data_age_seconds"), "ais_data_quality": a.get("data_quality"),
            "ais_destination_reported": a.get("destination_reported"), "data_source_position": "AIS_API_REALTIME",
            "run_id": f"realtime_{tick.strftime('%Y%m%d')}", "bima2_snapshot_status": "REALTIME_INPUT_MODEL_INFERENCE",
            "operational_claim_allowed": False,
            "leg_id": f"RT-{a.mmsi}-{tick.strftime('%Y%m%d')}-{origin[:3]}-{dest[:3]}",
            "journey_id": f"RT-{a.mmsi}-{tick.strftime('%Y%m%d')}-{origin[:3]}-{dest[:3]}",
        }
        eta_times = {}
        for key, model in ml1.items():
            if visual_state.startswith("BERTHED"):
                residual, corrected = 0.0, 0.0
            elif pd.notna(baseline):
                residual = float(model.predict(feat[ML1_NUM + ML1_CAT])[0])
                corrected = max(0.0, float(baseline) + residual)
            else:
                residual, corrected = np.nan, np.nan
            rec[f"eta_correction_{key}_min"] = residual
            rec[f"eta_corrected_{key}_min"] = corrected
            eta_t = a.timestamp + pd.to_timedelta(corrected, unit="m") if pd.notna(corrected) else pd.NaT
            rec[f"estimated_arrival_{key}"] = eta_t
            eta_times[key] = eta_t

        # Current CCTV is authoritative for observed terminal; historical profile is inference fallback for the other terminal.
        reference_arrival = next((x for x in eta_times.values() if pd.notna(x)), a.timestamp)
        rate = cctv.get(dest) or historical_rate(root, dest, reference_arrival) or {
            "car_rate_5min": 0.0, "motor_rate_5min": 0.0, "pce_rate_5min": 0.0, "queue_pce": np.nan, "source": "RATE_UNAVAILABLE"
        }
        rec["vehicle_rate_source"] = rate.get("source")
        rec["car_rate_5min"] = rate.get("car_rate_5min")
        rec["motor_rate_5min"] = rate.get("motor_rate_5min")
        rec["pce_rate_5min"] = rate.get("pce_rate_5min")

        ml2_pred = predict_ml2(ml2, ml2_features, base_map, pd.Series({"mmsi": a.mmsi, "destination_port": dest}), rate,
                               capacities.get(str(a.mmsi), np.nan), reference_arrival)
        for turn_key, (base, corr, corrected) in ml2_pred.items():
            rec["turnaround_base_min"] = base
            for eta_key, eta_t in eta_times.items():
                combo = f"{eta_key}_{turn_key}"
                rec[f"turnaround_correction_{combo}_min"] = corr
                rec[f"turnaround_corrected_{combo}_min"] = corrected
                etd = eta_t + pd.to_timedelta(corrected, unit="m") if pd.notna(eta_t) and pd.notna(corrected) else pd.NaT
                rec[f"estimated_departure_{eta_key}_{turn_key}"] = etd
                rec[f"etd_{eta_key}_{turn_key}"] = etd
        rows.append(rec)

    # Terminal states are written for every vessel tick so dashboard synchronization is exact.
    vessel_ticks = sorted({pd.Timestamp(r["simulation_tick"]) for r in rows if r.get("record_type") == "VESSEL_STATE"})
    if not vessel_ticks:
        vessel_ticks = [pd.Timestamp.now(tz="UTC").floor(f"{tick_minutes}min")]
    for ref_tick in vessel_ticks:
        for terminal in ports:
            rate = cctv.get(terminal) or historical_rate(root, terminal, ref_tick) or {
                "car_rate_5min": 0.0, "motor_rate_5min": 0.0, "pce_rate_5min": 0.0, "queue_pce": np.nan, "source": "RATE_UNAVAILABLE"
            }
            rows.append({
                "record_type": "TERMINAL_STATE", "simulation_tick": ref_tick, "terminal": terminal,
                "queue_estimated_pce": rate.get("queue_pce"), "car_arrival_5min": rate.get("car_rate_5min", 0),
                "motor_arrival_5min": rate.get("motor_rate_5min", 0), "pce_arrival_5min": rate.get("pce_rate_5min", 0),
                "service_capacity_pce": 0.0, "data_source_vehicle": rate.get("source"),
                "run_id": f"realtime_{ref_tick.strftime('%Y%m%d')}", "bima2_snapshot_status": "REALTIME_INPUT_MODEL_INFERENCE",
                "operational_claim_allowed": False,
            })

    new = pd.DataFrame(rows)
    out_path = root / cfg["integration"]["operation_state_output"]
    out_path.parent.mkdir(parents=True, exist_ok=True)
    if out_path.exists() and out_path.stat().st_size > 0:
        try:
            old = pd.read_csv(out_path, dtype={"mmsi": "string"})
            old["simulation_tick"] = pd.to_datetime(old["simulation_tick"], errors="coerce", utc=True)
            new["simulation_tick"] = pd.to_datetime(new["simulation_tick"], errors="coerce", utc=True)
            # Replace current tick/entity rows, keep rolling history.
            entity_cols = ["record_type", "simulation_tick"]
            old_key = old["mmsi"].astype(str) if "mmsi" in old.columns else pd.Series("", index=old.index)
            old_term = old["terminal"].astype(str) if "terminal" in old.columns else pd.Series("", index=old.index)
            new_key = new["mmsi"].astype(str) if "mmsi" in new.columns else pd.Series("", index=new.index)
            new_term = new["terminal"].astype(str) if "terminal" in new.columns else pd.Series("", index=new.index)
            old["__entity"] = np.where(old.record_type.eq("VESSEL_STATE"), old_key, old_term)
            new["__entity"] = np.where(new.record_type.eq("VESSEL_STATE"), new_key, new_term)
            replacement = set(zip(new.record_type.astype(str), new.simulation_tick.astype(str), new.__entity.astype(str)))
            keep = ~pd.Series(list(zip(old.record_type.astype(str), old.simulation_tick.astype(str), old.__entity.astype(str))), index=old.index).isin(replacement)
            combined = pd.concat([old.loc[keep].drop(columns="__entity"), new.drop(columns="__entity")], ignore_index=True, sort=False)
        except Exception:
            combined = new
    else:
        combined = new

    combined["simulation_tick"] = pd.to_datetime(combined["simulation_tick"], errors="coerce", utc=True)
    cutoff = pd.Timestamp.now(tz="UTC") - pd.Timedelta(days=int(cfg["integration"].get("realtime_history_days", 14)))
    combined = combined[combined.simulation_tick.ge(cutoff)].sort_values(["simulation_tick", "record_type", "mmsi"], na_position="last")
    tmp = out_path.with_suffix(".csv.tmp")
    combined.to_csv(tmp, index=False)
    os.replace(tmp, out_path)
    return len([r for r in rows if r.get("record_type") == "VESSEL_STATE"])


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--once", action="store_true")
    p.add_argument("--poll-seconds", type=float, default=5.0)
    args = p.parse_args()
    root = find_root()
    cfg = yload(root / "config" / "project_config_realtime_v4.yaml")
    while True:
        try:
            n = build_once(root, cfg)
            print(f"[{datetime.now().astimezone().isoformat(timespec='seconds')}] operation_state realtime vessels={n}", flush=True)
        except KeyboardInterrupt:
            break
        except Exception as exc:
            print(f"OPERATION STATE ERROR: {exc}", flush=True)
            if args.once:
                raise
        if args.once:
            break
        time.sleep(max(1.0, args.poll_seconds))


if __name__ == "__main__":
    main()
