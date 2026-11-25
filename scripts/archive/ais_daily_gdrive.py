#!/usr/bin/env python3
"""Archive original AIS API messages to one CSV per Asia/Jakarta calendar day.

Input: poll_ais_api_realtime.py raw JSONL (each line has received_at, payload).
Every raw AIS record is retained, including records rejected by realtime filters.
Requires Python >=3.9 (zoneinfo), rclone configured separately for Google Drive.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import subprocess
import sys
import tempfile
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[2]
RAW_DIR = ROOT / "data/01_DATA_SOURCE/AIS/realtime/raw"
ARCHIVE_DIR = ROOT / "data/01_DATA_SOURCE/AIS/archive_daily"
TZ = ZoneInfo("Asia/Jakarta")
DRIVE_FOLDER_ID = "1S3QALsal7ztEwu13vhpRMz-H-VmtagUc"
FIELDS = [
    "received_at_wib", "received_at_original", "source_file", "record_index",
    "mmsi", "timestamp", "created_at", "update_at", "lat", "lon",
    "sog", "cog", "heading", "navstatus", "shipname", "raw_json",
]


def parse_received_at(value: object) -> datetime:
    if not value:
        raise ValueError("received_at is missing")
    dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if dt.tzinfo is None:
        raise ValueError("received_at must contain a UTC offset")
    return dt.astimezone(TZ)


def extract_messages(payload: object) -> list:
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict):
        for key in ("data", "results", "ships", "vessels", "items"):
            if isinstance(payload.get(key), list):
                return payload[key]
        return [payload]
    return [payload]


def source_files(day: date) -> list[Path]:
    # Source file names use the VPS local date, which can differ from WIB.
    # Search adjacent dates; final filtering always uses received_at converted to WIB.
    paths = []
    for offset in (-2, -1, 0, 1, 2):
        stamp = (day + timedelta(days=offset)).strftime("%Y%m%d")
        candidate = RAW_DIR / f"ais_api_raw_{stamp}.jsonl"
        if candidate.is_file():
            paths.append(candidate)
    return sorted(set(paths))


def export_day(day: date) -> tuple[Path | None, int]:
    sources = source_files(day)
    if not sources:
        raise RuntimeError(f"No raw JSONL files found near {day}. Enable store_raw_payload and check receiver.")
    ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)
    target = ARCHIVE_DIR / f"AIS_RAW_{day.isoformat()}.csv"
    fd, temporary = tempfile.mkstemp(prefix=".ais_", suffix=".csv.tmp", dir=ARCHIVE_DIR)
    count = 0
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as out:
            writer = csv.DictWriter(out, fieldnames=FIELDS)
            writer.writeheader()
            for path in sources:
                with path.open("r", encoding="utf-8") as source:
                    for line_no, line in enumerate(source, 1):
                        if not line.strip():
                            continue
                        try:
                            envelope = json.loads(line)
                            received = parse_received_at(envelope["received_at"])
                        except (ValueError, TypeError, KeyError, json.JSONDecodeError) as exc:
                            raise RuntimeError(f"Invalid raw data {path}:{line_no}: {exc}") from exc
                        if received.date() != day:
                            continue
                        for index, item in enumerate(extract_messages(envelope.get("payload")), 1):
                            obj = item if isinstance(item, dict) else {}
                            writer.writerow({
                                "received_at_wib": received.isoformat(),
                                "received_at_original": envelope["received_at"],
                                "source_file": path.name,
                                "record_index": index,
                                "mmsi": obj.get("mmsi", obj.get("immsi", "")),
                                "timestamp": obj.get("timestamp", ""),
                                "created_at": obj.get("created_at", ""),
                                "update_at": obj.get("update_at", ""),
                                "lat": obj.get("lat", obj.get("latitude", "")),
                                "lon": obj.get("lon", obj.get("longitude", "")),
                                "sog": obj.get("sog", ""),
                                "cog": obj.get("cog", ""),
                                "heading": obj.get("heading", ""),
                                "navstatus": obj.get("navstatus", obj.get("nav_status", "")),
                                "shipname": obj.get("shipname", ""),
                                "raw_json": json.dumps(item, ensure_ascii=False, separators=(",", ":"), default=str),
                            })
                            count += 1
        if count == 0:
            os.unlink(temporary)
            return None, 0
        os.replace(temporary, target)
        return target, count
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def upload(path: Path, remote: str) -> None:
    # Configure 'aisdrive' with root_folder_id before running this module.
    destination = f"{remote.rstrip(':')}:{path.name}"
    subprocess.run(["rclone", "copyto", str(path), destination, "--retries", "3"], check=True)
    check = subprocess.run(["rclone", "lsjson", destination, "--stat", "--files-only"],
                           check=True, capture_output=True, text=True)
    details = json.loads(check.stdout)
    if details.get("Size") != path.stat().st_size:
        raise RuntimeError(f"Upload size verification failed for {destination}")
    digest = hashlib.md5()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    remote_hash = subprocess.run(
        ["rclone", "md5sum", destination], check=True, text=True, capture_output=True
    ).stdout.strip().split()
    if not remote_hash or remote_hash[0].lower() != digest.hexdigest():
        raise RuntimeError(f"Upload MD5 verification failed for {destination}")


def remote_verified(remote: str, path: Path) -> bool:
    """Verify exact local CSV against remote size and MD5, without uploading."""
    destination = f"{remote.rstrip(':')}:{path.name}"
    info = json.loads(subprocess.run(["rclone","lsjson",destination,"--stat","--files-only"],
                          check=True,capture_output=True,text=True,timeout=120).stdout)
    if info.get("Size") != path.stat().st_size or path.stat().st_size == 0:
        return False
    with path.open("rb") as f:
        digest = hashlib.file_digest(f, "md5").hexdigest()
    remote_hash = subprocess.run(["rclone","md5sum",destination],check=True,
                                 capture_output=True,text=True,timeout=120).stdout.split()
    return bool(remote_hash and remote_hash[0].lower()==digest)


def cleanup_local_archives(remote: str, current_wib: date) -> None:
    # Keep local CSVs for seven completed days. Never delete on a partial match.
    for path in sorted(ARCHIVE_DIR.glob("AIS_RAW_????-??-??.csv")):
        try:
            day = date.fromisoformat(path.stem.removeprefix("AIS_RAW_"))
            if day <= current_wib-timedelta(days=8) and remote_verified(remote,path):
                path.unlink()
                print(f"[CLEAN CSV] {path.name}",flush=True)
        except (ValueError,OSError,subprocess.SubprocessError) as exc:
            print(f"[KEEP CSV] {path.name}: {exc}",flush=True)


def cleanup_raw_sources(remote: str, current_wib: date) -> None:
    """Verify every raw record against the downloaded, verified daily archives.

    Deliberately opt-in: automatic daily upload must not depend on raw deletion.
    """
    from collections import Counter
    now=datetime.now().astimezone()
    for path in sorted(RAW_DIR.glob("ais_api_raw_????????.jsonl")):
        try:
            original=path.stat()
            source_day=datetime.strptime(path.stem.removeprefix("ais_api_raw_"),"%Y%m%d").date()
            if source_day>=now.date() or now.timestamp()-original.st_mtime<86400:
                continue
            expected={}
            with path.open(encoding="utf-8") as f:
                for line in f:
                    if not line.strip():continue
                    env=json.loads(line);day=parse_received_at(env["received_at"]).date()
                    if day>current_wib-timedelta(days=8):raise ValueError("retention window")
                    bucket=expected.setdefault(day,Counter())
                    for index,item in enumerate(extract_messages(env.get("payload")),1):
                        raw=json.dumps(item,ensure_ascii=False,separators=(",",":"),default=str)
                        bucket[(str(env["received_at"]),str(index),raw)]+=1
            if not expected or not all(expected.values()):continue
            with tempfile.TemporaryDirectory(prefix="ais-clean-") as tmp:
                for day,wanted in expected.items():
                    local=Path(tmp)/f"AIS_RAW_{day.isoformat()}.csv"
                    subprocess.run(["rclone","copyto",f"{remote.rstrip(':')}:{local.name}",str(local)],
                                   check=True,timeout=300)
                    if not remote_verified(remote,local):raise ValueError("remote hash mismatch")
                    observed=Counter()
                    with local.open(encoding="utf-8",newline="") as f:
                        for row in csv.DictReader(f):
                            if row["source_file"]==path.name:
                                observed[(row["received_at_original"],row["record_index"],row["raw_json"])]+=1
                    if observed!=wanted:raise ValueError("raw record multiset mismatch")
                    local.unlink()
            latest=path.stat()
            if (latest.st_ino,latest.st_size,latest.st_mtime_ns)!=(original.st_ino,original.st_size,original.st_mtime_ns):
                raise ValueError("source changed during verification")
            path.unlink()
            print(f"[CLEAN RAW] {path.name}; exact record match verified",flush=True)
        except (OSError,ValueError,KeyError,TypeError,subprocess.SubprocessError) as exc:
            print(f"[KEEP RAW] {path.name}: {exc}",flush=True)


def main() -> int:
    parser = argparse.ArgumentParser(description="Archive raw AIS to Google Drive daily")
    parser.add_argument("--date", help="WIB date YYYY-MM-DD (default: yesterday)")
    parser.add_argument("--days-back", type=int, default=1,
                        help="Export N preceding WIB days, default 1; reruns replace the same Drive filename")
    parser.add_argument("--remote", default="aisdrive",
                        help="rclone remote configured with the target folder as its root")
    parser.add_argument("--local-only", action="store_true", help="Create CSV without uploading")
    parser.add_argument("--cleanup-uploaded", action="store_true",
                        help="After verified upload, remove closed source JSONL and uploaded CSV only")
    parser.add_argument("--cleanup-raw-verified", action="store_true", help="Opt-in exact raw record verification before deletion")
    args = parser.parse_args()
    today_wib = datetime.now(TZ).date()
    if args.days_back < 1:
        parser.error("--days-back must be >= 1")
    if not args.remote or any(ch in args.remote for ch in ":/\\"):
        parser.error("--remote must be a simple rclone remote name")
    end = date.fromisoformat(args.date) if args.date else today_wib - timedelta(days=1)
    failed = False
    print(f"Destination Google Drive folder ID: {DRIVE_FOLDER_ID}", flush=True)
    for offset in reversed(range(args.days_back)):
        day = end - timedelta(days=offset)
        try:
            path, count = export_day(day)
            if path is None:
                print(f"[SKIP] {day}: no messages in source files", flush=True)
                continue
            if not args.local_only:
                upload(path, args.remote)
            print(f"[OK] {day}: {count} raw records -> {path.name}"
                  + (" (local only)" if args.local_only else " (Drive verified)"), flush=True)
        except (OSError, RuntimeError, subprocess.CalledProcessError, json.JSONDecodeError) as exc:
            print(f"[ERROR] {day}: {exc}", file=sys.stderr, flush=True)
            failed = True
    if args.cleanup_uploaded and not args.local_only and not failed:
        try:
            cleanup_local_archives(args.remote, today_wib)
            if args.cleanup_raw_verified:
                cleanup_raw_sources(args.remote, today_wib)
            else:
                print("[KEEP RAW] Exact raw cleanup is opt-in", flush=True)
        except (OSError, RuntimeError, subprocess.CalledProcessError) as exc:
            print(f"[ERROR] cleanup: {exc}", file=sys.stderr)
            failed = True
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
