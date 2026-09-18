import cv2
import csv
import json
import math
import os
import subprocess
import threading
import time
from collections import defaultdict
from datetime import datetime
from pathlib import Path

import numpy as np
import torch
from ultralytics import YOLO

# =========================================================
# JAES_SIMULASI_BIMA2 - CCTV REALTIME V4.2
# STABLE STREAM + ROI INFERENCE + ROBUST COUNTING
# =========================================================
# Alur tunggal:
# RAW RTSP (sama dengan VLC 1)
#   -> FFmpeg latest-frame reader 10 fps
#   -> YOLO + ByteTrack hanya pada expanded ROI
#   -> robust line-crossing (hysteresis + min hits + class voting)
#   -> annotated RTSP (VLC 2)
#
# Counter tetap persistent. Reset hanya dilakukan manual lewat
# RESET_CCTV_VALIDATION_V4.ps1 saat memulai uji validasi baru.
# =========================================================

SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parents[2]

PORT = os.getenv("CCTV_PORT", "BENGKALIS").strip().upper()
if PORT not in {"BENGKALIS", "PAKNING"}:
    raise ValueError(f"CCTV_PORT tidak valid: {PORT}")
PORT_KEY = PORT.lower()
CAMERA_ID = f"cctv_{PORT_KEY}"
STREAM_KEY = os.getenv("CCTV_STREAM_KEY", CAMERA_ID).strip()
RAW_RTSP = os.getenv("CCTV_RAW_RTSP", f"rtsp://127.0.0.1:8554/{STREAM_KEY}")
ANNOTATED_RTSP = os.getenv("CCTV_ANNOTATED_RTSP", f"rtsp://127.0.0.1:8554/{STREAM_KEY}_yolo")
SOURCE_STATUS = os.getenv("CCTV_SOURCE_STATUS", "OBSERVED_OR_USER_RECORDING")

MODEL = PROJECT_ROOT / "models" / "YOLO" / "yolo26s.pt"
TRACKER = SCRIPT_DIR / "bytetrack_vehicle_10fps.yaml"
_port_roi = SCRIPT_DIR / f"roi_config_{PORT_KEY}.json"
ROI_CONFIG = Path(os.getenv("CCTV_ROI_CONFIG", str(_port_roi if _port_roi.exists() else SCRIPT_DIR / "roi_config.json")))

# Realtime CCTV state/history must be written to local runtime storage, not Google Drive.
# This avoids Google Drive file-lock/sync conflicts (for example vehicle_state.tmp PermissionError).
RUNTIME_ROOT = Path(os.getenv("CCTV_RUNTIME_ROOT", r"C:\LOCAL_RUN_venv\cache\cctv"))
OUTPUT_DIR = Path(os.getenv("CCTV_OUTPUT_DIR", str(RUNTIME_ROOT / "output" / PORT_KEY)))
HISTORY_DIR = Path(os.getenv("CCTV_HISTORY_DIR", str(RUNTIME_ROOT / "historical" / PORT_KEY)))
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
HISTORY_DIR.mkdir(parents=True, exist_ok=True)
EVENT_CSV = OUTPUT_DIR / f"vehicle_events_{PORT_KEY}.csv"
STATE_JSON = OUTPUT_DIR / ("vehicle_state.json" if PORT == "BENGKALIS" else f"vehicle_state_{PORT_KEY}.json")

FFMPEG = Path(r"C:\LOCAL_RUN_venv\tools\ffmpeg\bin\ffmpeg.exe")

# ---------------- PERFORMANCE ----------------
DEVICE = "cpu"
IMAGE_SIZE = 640
TARGET_INFERENCE_FPS = 10.0
TARGET_OUTPUT_FPS = 10.0
READER_MAX_WIDTH = 1280
OUTPUT_MAX_WIDTH = 1280

# Keep low threshold for small motorcycles. False events are controlled by
# track stability + hysteresis, not by raising detector threshold aggressively.
CONFIDENCE = 0.10

# Expanded ROI gives small vehicles more effective pixels at imgsz=640.
ROI_CROP_MARGIN_PX = 90
COUNTING_ROI_TOLERANCE_PX = 35.0

# ---------------- COUNTING STABILITY ----------------
MIN_ROI_HITS_BEFORE_COUNT = 2
LINE_HYSTERESIS_PX = 8.0
MAX_CROSSING_GAP_SECONDS = 2.5
TRACK_STALE_SECONDS = 7.0

# COCO classes: 2 car, 3 motorcycle, 5 bus, 7 truck.
# Four-wheel/heavy road vehicles are grouped into CAR for ferry queue purposes.
CAR_LIKE_CLASSES = {2, 5, 7}
MOTOR_CLASS = 3
VEHICLE_CLASSES = sorted(CAR_LIKE_CLASSES | {MOTOR_CLASS})
ENTRY_DIRECTION = "A_TO_B"

CPU_COUNT = os.cpu_count() or 4
TORCH_THREADS = max(2, min(8, CPU_COUNT // 2))
try:
    torch.set_num_threads(TORCH_THREADS)
    torch.set_num_interop_threads(1)
except RuntimeError:
    pass

os.environ["OPENCV_FFMPEG_CAPTURE_OPTIONS"] = "rtsp_transport;tcp"


class LatestFrameReader:
    """RTSP/TCP reader that keeps only the newest decoded frame."""

    def __init__(self, source, source_width, source_height, ingest_fps=10.0, max_width=1280):
        self.source = str(source)
        self.source_width = int(source_width)
        self.source_height = int(source_height)
        self.ingest_fps = float(ingest_fps)

        if self.source_width > max_width:
            scale = max_width / float(self.source_width)
            self.width = int(round(self.source_width * scale))
            self.height = int(round(self.source_height * scale))
        else:
            self.width = self.source_width
            self.height = self.source_height

        self.width -= self.width % 2
        self.height -= self.height % 2
        self.frame_bytes = self.width * self.height * 3

        self.lock = threading.Lock()
        self.condition = threading.Condition(self.lock)
        self.frame = None
        self.seq = 0
        self.frame_time = 0.0
        self.running = False
        self.thread = None
        self.proc = None
        self.generation = 0
        self.source_fps = self.ingest_fps

    def _build_cmd(self):
        vf = f"fps={self.ingest_fps:.3f},scale={self.width}:{self.height}"
        return [
            str(FFMPEG),
            "-hide_banner", "-loglevel", "error", "-nostdin",
            "-rtsp_transport", "tcp",
            "-i", self.source,
            "-map", "0:v:0", "-an",
            "-vf", vf,
            "-pix_fmt", "bgr24",
            "-f", "rawvideo",
            "pipe:1",
        ]

    def _start_ffmpeg(self):
        print(
            f"[READER] RAW RTSP/TCP -> BGR {self.width}x{self.height} "
            f"@ {self.ingest_fps:.1f} fps"
        )
        self.proc = subprocess.Popen(
            self._build_cmd(),
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            bufsize=0,
        )
        with self.lock:
            self.generation += 1

    @staticmethod
    def _read_exact(stream, nbytes):
        chunks = bytearray()
        while len(chunks) < nbytes:
            chunk = stream.read(nbytes - len(chunks))
            if not chunk:
                return None
            chunks.extend(chunk)
        return bytes(chunks)

    def _stop_ffmpeg(self):
        if self.proc is None:
            return
        try:
            self.proc.kill()
        except Exception:
            pass
        try:
            self.proc.wait(timeout=2)
        except Exception:
            pass
        self.proc = None

    def _run(self):
        reconnect_delay = 1.0
        while self.running:
            if self.proc is None or self.proc.poll() is not None:
                self._stop_ffmpeg()
                try:
                    self._start_ffmpeg()
                except Exception as exc:
                    print(f"[READER] gagal start FFmpeg: {exc}")
                    time.sleep(reconnect_delay)
                    continue

            raw = self._read_exact(self.proc.stdout, self.frame_bytes)
            if raw is None:
                code = None if self.proc is None else self.proc.poll()
                print(f"[READER] pipe berhenti (exit={code}); reconnect...")
                self._stop_ffmpeg()
                time.sleep(reconnect_delay)
                continue

            frame = np.frombuffer(raw, dtype=np.uint8).reshape((self.height, self.width, 3))
            now = time.perf_counter()
            with self.condition:
                self.frame = frame.copy()
                self.seq += 1
                self.frame_time = now
                self.condition.notify_all()

        self._stop_ffmpeg()

    def start(self):
        self.running = True
        self.thread = threading.Thread(target=self._run, name="CCTV-RTSP-Reader", daemon=True)
        self.thread.start()
        return self

    def read_latest(self, after_seq=-1, timeout=5.0):
        end = time.perf_counter() + timeout
        with self.condition:
            while self.running and (self.frame is None or self.seq <= after_seq):
                remain = end - time.perf_counter()
                if remain <= 0:
                    return False, None, after_seq, 0.0, self.generation
                self.condition.wait(timeout=min(remain, 0.25))

            if self.frame is None or self.seq <= after_seq:
                return False, None, after_seq, 0.0, self.generation

            return True, self.frame.copy(), self.seq, self.frame_time, self.generation

    def stop(self):
        self.running = False
        with self.condition:
            self.condition.notify_all()
        self._stop_ffmpeg()
        if self.thread is not None:
            self.thread.join(timeout=2.0)


def start_writer(width, height):
    # Constant low-latency H.264 stream. CRF 18 avoids the blocky output that
    # was visible with default ultrafast settings.
    cmd = [
        str(FFMPEG),
        "-hide_banner", "-loglevel", "warning", "-nostdin",
        "-f", "rawvideo",
        "-pix_fmt", "bgr24",
        "-s", f"{width}x{height}",
        "-r", f"{TARGET_OUTPUT_FPS:.03f}",
        "-i", "-",
        "-an",
        "-c:v", "libx264",
        "-preset", "ultrafast",
        "-tune", "zerolatency",
        "-crf", "18",
        "-threads", "2",
        "-bf", "0",
        "-g", "10",
        "-keyint_min", "10",
        "-sc_threshold", "0",
        "-pix_fmt", "yuv420p",
        "-f", "rtsp",
        "-rtsp_transport", "tcp",
        ANNOTATED_RTSP,
    ]
    return subprocess.Popen(cmd, stdin=subprocess.PIPE, bufsize=0)


class AnnotatedPublisher:
    """Publishes the latest annotated frame at a constant 10 fps."""

    def __init__(self, width, height, fps):
        self.width = int(width)
        self.height = int(height)
        self.fps = float(fps)
        self.period = 1.0 / self.fps
        self.lock = threading.Lock()
        self.frame = None
        self.running = False
        self.thread = None
        self.writer = None

    def update(self, frame):
        if frame is None:
            return
        with self.lock:
            self.frame = frame.copy()

    def _restart_writer(self):
        if self.writer is not None:
            try:
                if self.writer.stdin:
                    self.writer.stdin.close()
            except Exception:
                pass
            try:
                self.writer.kill()
            except Exception:
                pass
        self.writer = start_writer(self.width, self.height)

    def _run(self):
        next_tick = time.perf_counter()
        self._restart_writer()
        while self.running:
            now = time.perf_counter()
            if now < next_tick:
                time.sleep(min(next_tick - now, 0.01))
                continue
            if now - next_tick > 0.5:
                next_tick = now
            next_tick += self.period

            with self.lock:
                frame = None if self.frame is None else self.frame.copy()
            if frame is None:
                continue

            try:
                if self.writer is None or self.writer.poll() is not None:
                    self._restart_writer()
                self.writer.stdin.write(frame.tobytes())
            except (BrokenPipeError, OSError, AttributeError):
                print("[PUBLISHER] RTSP YOLO reconnect...")
                time.sleep(0.25)
                try:
                    self._restart_writer()
                except Exception as exc:
                    print(f"[PUBLISHER] restart gagal: {exc}")

        if self.writer is not None:
            try:
                if self.writer.stdin:
                    self.writer.stdin.close()
            except Exception:
                pass
            try:
                self.writer.terminate()
            except Exception:
                pass

    def start(self):
        self.running = True
        self.thread = threading.Thread(target=self._run, name="CCTV-YOLO-Publisher", daemon=True)
        self.thread.start()
        return self

    def stop(self):
        self.running = False
        if self.thread is not None:
            self.thread.join(timeout=3.0)


def line_side(point, a, b):
    return (b[0] - a[0]) * (point[1] - a[1]) - (b[1] - a[1]) * (point[0] - a[0])


def signed_line_distance(point, a, b):
    denom = math.hypot(b[0] - a[0], b[1] - a[1])
    if denom < 1e-9:
        return 0.0
    return line_side(point, a, b) / denom


def stable_side_from_distance(distance_px):
    if distance_px <= -LINE_HYSTERESIS_PX:
        return -1
    if distance_px >= LINE_HYSTERESIS_PX:
        return 1
    return 0


def segments_intersect(p1, p2, q1, q2):
    def orientation(a, b, c):
        value = ((b[1] - a[1]) * (c[0] - b[0])) - ((b[0] - a[0]) * (c[1] - b[1]))
        if abs(value) < 1e-9:
            return 0
        return 1 if value > 0 else 2

    def on_segment(a, b, c):
        return (
            min(a[0], c[0]) <= b[0] <= max(a[0], c[0])
            and min(a[1], c[1]) <= b[1] <= max(a[1], c[1])
        )

    o1 = orientation(p1, p2, q1)
    o2 = orientation(p1, p2, q2)
    o3 = orientation(q1, q2, p1)
    o4 = orientation(q1, q2, p2)
    if o1 != o2 and o3 != o4:
        return True
    return (
        (o1 == 0 and on_segment(p1, q1, p2))
        or (o2 == 0 and on_segment(p1, q2, p2))
        or (o3 == 0 and on_segment(q1, p1, q2))
        or (o4 == 0 and on_segment(q1, p2, q2))
    )


def class_family(class_id):
    if int(class_id) == MOTOR_CLASS:
        return "MOTOR"
    if int(class_id) in CAR_LIKE_CLASSES:
        return "CAR"
    return None


def dominant_family(votes):
    if not votes:
        return None
    return max(votes.items(), key=lambda item: item[1])[0]


def floor_5min(dt):
    return dt.replace(minute=(dt.minute // 5) * 5, second=0, microsecond=0)


def load_state():
    state = {
        "car_queue_current": 0,
        "motor_queue_current": 0,
        "car_in_total": 0,
        "car_out_total": 0,
        "motor_in_total": 0,
        "motor_out_total": 0,
        "loaded_car_total": 0,
        "loaded_motor_total": 0,
        "car_rate_5min": 0,
        "motor_rate_5min": 0,
        "pce_rate_5min": 0.0,
        "rate_window_start": None,
        "port": PORT,
        "camera_id": CAMERA_ID,
        "source_status": SOURCE_STATUS,
        "updated_at": None,
        "counting_algorithm": "v4.4_dual_port_5min_rate",
    }
    if STATE_JSON.exists():
        try:
            state.update(json.loads(STATE_JSON.read_text(encoding="utf-8")))
        except Exception:
            pass
    state["counting_algorithm"] = "v4.4_dual_port_5min_rate"
    return state


def apply_loading(state):
    state["car_queue_current"] = max(
        0, int(state.get("car_in_total", 0)) - int(state.get("loaded_car_total", 0))
    )
    state["motor_queue_current"] = max(
        0, int(state.get("motor_in_total", 0)) - int(state.get("loaded_motor_total", 0))
    )
    return state


def save_state(state):
    state["updated_at"] = datetime.now().isoformat(timespec="seconds")
    state["port"] = PORT
    state["camera_id"] = CAMERA_ID
    state["source_status"] = SOURCE_STATUS
    state["counting_algorithm"] = "v4.4_dual_port_5min_rate"
    tmp = STATE_JSON.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, indent=2), encoding="utf-8")
    os.replace(tmp, STATE_JSON)


def set_rate_state(state, delta, bucket):
    state["car_rate_5min"] = int(delta.get("car_in", 0))
    state["motor_rate_5min"] = int(delta.get("motor_in", 0))
    state["pce_rate_5min"] = float(state["car_rate_5min"] + 0.25 * state["motor_rate_5min"])
    state["rate_window_start"] = bucket.isoformat(timespec="minutes")
    return state


def ensure_event_header():
    if EVENT_CSV.exists() and EVENT_CSV.stat().st_size > 0:
        return
    with EVENT_CSV.open("w", newline="", encoding="utf-8") as f:
        csv.writer(f).writerow([
            "timestamp", "camera_id", "port", "track_id", "class", "confidence",
            "direction", "event", "car_in_total", "car_out_total",
            "motor_in_total", "motor_out_total", "car_queue_current",
            "motor_queue_current", "algorithm",
        ])


def append_event(row):
    with EVENT_CSV.open("a", newline="", encoding="utf-8") as f:
        csv.writer(f).writerow(row)


def write_5min(bucket, state, delta):
    obs_file = HISTORY_DIR / f"cctv_5min_{PORT_KEY}_{bucket:%Y%m}.csv"
    new_file = not obs_file.exists() or obs_file.stat().st_size == 0
    with obs_file.open("a", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        if new_file:
            writer.writerow([
                "timestamp_5min", "camera_id", "port",
                "car_rate_5min", "motor_rate_5min", "pce_rate_5min",
                "car_out", "motor_out",
                "car_in_total", "car_out_total", "motor_in_total", "motor_out_total",
                "car_queue_current", "motor_queue_current", "total_queue_current",
                "algorithm", "source_status",
            ])
        car_rate=int(delta.get("car_in",0))
        motor_rate=int(delta.get("motor_in",0))
        pce_rate=car_rate+0.25*motor_rate
        writer.writerow([
            bucket.isoformat(timespec="minutes"), CAMERA_ID, PORT,
            car_rate, motor_rate, pce_rate,
            int(delta.get("car_out",0)), int(delta.get("motor_out",0)),
            state["car_in_total"], state["car_out_total"],
            state["motor_in_total"], state["motor_out_total"],
            state["car_queue_current"], state["motor_queue_current"],
            state["car_queue_current"] + state["motor_queue_current"],
            "v4.4_dual_port_5min_rate", SOURCE_STATUS,
        ])


def output_size(width, height):
    if width <= OUTPUT_MAX_WIDTH:
        out_w, out_h = width, height
    else:
        scale = OUTPUT_MAX_WIDTH / float(width)
        out_w = OUTPUT_MAX_WIDTH
        out_h = int(round(height * scale))
    return out_w - out_w % 2, out_h - out_h % 2


def expanded_roi_bounds(roi, width, height, margin):
    x1 = max(0, int(np.min(roi[:, 0])) - margin)
    y1 = max(0, int(np.min(roi[:, 1])) - margin)
    x2 = min(width, int(np.max(roi[:, 0])) + margin)
    y2 = min(height, int(np.max(roi[:, 1])) + margin)
    return x1, y1, x2, y2


def reset_ultralytics_tracker(model):
    try:
        trackers = getattr(getattr(model, "predictor", None), "trackers", None)
        if trackers:
            for tracker in trackers:
                if hasattr(tracker, "reset"):
                    tracker.reset()
            print("[TRACKER] reset setelah reconnect.")
    except Exception as exc:
        print(f"[TRACKER] reset warning: {exc}")


def main():
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    for path in [MODEL, TRACKER, ROI_CONFIG, FFMPEG]:
        if not path.exists():
            raise FileNotFoundError(str(path))

    cfg = json.loads(ROI_CONFIG.read_text(encoding="utf-8"))
    config_w = int(cfg["video_width"])
    config_h = int(cfg["video_height"])
    roi_original = np.array(cfg["roi"], dtype=np.int32)
    line_original = cfg["counting_line"]

    print("Input YOLO : SAME RAW RTSP as VLC 1")
    print("RTSP       :", RAW_RTSP)
    print("Membuka RAW RTSP dengan latest-frame reader...")

    reader = LatestFrameReader(
        RAW_RTSP,
        source_width=config_w,
        source_height=config_h,
        ingest_fps=TARGET_INFERENCE_FPS,
        max_width=READER_MAX_WIDTH,
    ).start()

    print("[SELFTEST] Menunggu frame pertama...")
    ok, frame, seq, frame_ts, generation = reader.read_latest(timeout=30.0)
    if not ok:
        reader.stop()
        raise RuntimeError("RAW RTSP belum menghasilkan frame ke reader dalam 30 detik.")

    height, width = frame.shape[:2]
    scale_x = width / float(config_w)
    scale_y = height / float(config_h)
    roi = np.array(
        [[int(x * scale_x), int(y * scale_y)] for x, y in roi_original],
        dtype=np.int32,
    )
    line = [
        (int(line_original[0][0] * scale_x), int(line_original[0][1] * scale_y)),
        (int(line_original[1][0] * scale_x), int(line_original[1][1] * scale_y)),
    ]
    crop_x1, crop_y1, crop_x2, crop_y2 = expanded_roi_bounds(
        roi, width, height, ROI_CROP_MARGIN_PX
    )

    out_w, out_h = output_size(width, height)
    first_overlay = frame.copy()
    cv2.polylines(first_overlay, [roi], True, (0, 255, 0), 2)
    cv2.line(first_overlay, line[0], line[1], (0, 0, 255), 3)
    if (out_w, out_h) != (width, height):
        first_overlay = cv2.resize(first_overlay, (out_w, out_h), interpolation=cv2.INTER_AREA)

    publisher = AnnotatedPublisher(out_w, out_h, TARGET_OUTPUT_FPS).start()
    publisher.update(first_overlay)

    print("Memuat YOLO:", MODEL)
    model = YOLO(str(MODEL))

    state = apply_loading(load_state())
    save_state(state)
    ensure_event_header()

    tracks = {}
    bucket = floor_5min(datetime.now())
    delta = {"car_in": 0, "car_out": 0, "motor_in": 0, "motor_out": 0}

    last_seq = seq
    last_generation = generation
    stats_started = time.perf_counter()
    stats_last_print = stats_started
    processed_frames = 0
    source_frames_seen = 0
    last_source_seq = seq

    print("")
    print("============================================")
    print(f" CCTV YOLO V4.4 - {PORT} / 5-MIN RATE")
    print("============================================")
    print("Port                 :", PORT)
    print("RAW source           :", RAW_RTSP)
    print("Frame reader         :", f"{width}x{height} @ {TARGET_INFERENCE_FPS:.1f} fps")
    print("Inference crop       :", f"x={crop_x1}:{crop_x2}, y={crop_y1}:{crop_y2}")
    print("YOLO imgsz           :", IMAGE_SIZE)
    print("Classes              : CAR(2/5/7), MOTOR(3)")
    print("Counting             : robust crossing + 2 ROI hits + class voting")
    print("Output               :", f"{out_w}x{out_h} @ {TARGET_OUTPUT_FPS:.1f} fps, H264 CRF18")
    print("Counter persistent   : ON")
    print("5-min history        :", HISTORY_DIR)
    print("")

    try:
        while True:
            ok, frame, new_seq, frame_ts, generation = reader.read_latest(
                after_seq=last_seq, timeout=5.0
            )
            if not ok:
                print("[WARN] Belum ada frame baru; menunggu reader/reconnect...")
                continue

            if generation != last_generation:
                tracks.clear()
                reset_ultralytics_tracker(model)
                last_generation = generation

            source_frames_seen += max(0, new_seq - last_source_seq)
            last_source_seq = new_seq
            last_seq = new_seq

            now_dt = datetime.now()
            mono_now = time.monotonic()
            new_bucket = floor_5min(now_dt)
            if new_bucket != bucket:
                state = apply_loading(load_state())
                state = set_rate_state(state, delta, bucket)
                save_state(state)
                write_5min(bucket, state, delta)
                bucket = new_bucket
                delta = {"car_in": 0, "car_out": 0, "motor_in": 0, "motor_out": 0}
                state = set_rate_state(apply_loading(load_state()), delta, bucket)
                save_state(state)

            overlay = frame.copy()
            crop = frame[crop_y1:crop_y2, crop_x1:crop_x2]
            infer_t0 = time.perf_counter()

            results = model.track(
                source=crop,
                persist=True,
                tracker=str(TRACKER),
                classes=VEHICLE_CLASSES,
                conf=CONFIDENCE,
                imgsz=IMAGE_SIZE,
                device=DEVICE,
                verbose=False,
            )
            inference_ms = (time.perf_counter() - infer_t0) * 1000.0

            cv2.polylines(overlay, [roi], True, (0, 255, 0), 2)
            cv2.line(overlay, line[0], line[1], (0, 0, 255), 3)
            cv2.rectangle(
                overlay, (crop_x1, crop_y1), (crop_x2, crop_y2), (120, 120, 120), 1
            )

            result = results[0]
            detections_in_roi = 0
            current_ids = set()

            if result.boxes is not None and result.boxes.id is not None:
                boxes = result.boxes.xyxy.cpu().numpy()
                ids = result.boxes.id.int().cpu().tolist()
                classes = result.boxes.cls.int().cpu().tolist()
                confidences = result.boxes.conf.cpu().tolist()

                for box, track_id, class_id, confidence in zip(boxes, ids, classes, confidences):
                    family = class_family(class_id)
                    if family is None:
                        continue

                    current_ids.add(track_id)
                    x1, y1, x2, y2 = map(int, box)
                    x1 += crop_x1
                    x2 += crop_x1
                    y1 += crop_y1
                    y2 += crop_y1
                    center = (int((x1 + x2) / 2), int((y1 + y2) / 2))
                    roi_distance = cv2.pointPolygonTest(roi, center, True)
                    inside_roi = roi_distance >= 0
                    near_roi = roi_distance >= -COUNTING_ROI_TOLERANCE_PX

                    meta = tracks.get(track_id)
                    if meta is None:
                        meta = {
                            "last_center": None,
                            "last_seen": mono_now,
                            "stable_side": 0,
                            "stable_center": None,
                            "roi_hits": 0,
                            "votes": defaultdict(float),
                            "counted_dirs": set(),
                        }
                        tracks[track_id] = meta

                    prev_center = meta["last_center"]
                    prev_seen = meta["last_seen"]
                    prev_stable_side = meta["stable_side"]
                    prev_stable_center = meta.get("stable_center")
                    meta["last_seen"] = mono_now
                    meta["votes"][family] += max(0.05, float(confidence))
                    stable_family = dominant_family(meta["votes"]) or family

                    if inside_roi:
                        detections_in_roi += 1
                        meta["roi_hits"] += 1

                    distance_px = signed_line_distance(center, line[0], line[1])
                    current_stable_side = stable_side_from_distance(distance_px)

                    counted_now = False
                    if (
                        near_roi
                        and prev_stable_center is not None
                        and prev_stable_side in (-1, 1)
                        and current_stable_side in (-1, 1)
                        and current_stable_side != prev_stable_side
                        and meta["roi_hits"] >= MIN_ROI_HITS_BEFORE_COUNT
                        and (mono_now - prev_seen) <= MAX_CROSSING_GAP_SECONDS
                        and segments_intersect(prev_stable_center, center, line[0], line[1])
                    ):
                        direction = "A_TO_B" if prev_stable_side < current_stable_side else "B_TO_A"
                        if direction not in meta["counted_dirs"]:
                            meta["counted_dirs"].add(direction)
                            counted_now = True
                            is_entry = direction == ENTRY_DIRECTION

                            state = apply_loading(load_state())
                            if stable_family == "CAR":
                                if is_entry:
                                    state["car_in_total"] += 1
                                    delta["car_in"] += 1
                                    event = "IN"
                                else:
                                    state["car_out_total"] += 1
                                    delta["car_out"] += 1
                                    event = "OUT"
                            else:
                                if is_entry:
                                    state["motor_in_total"] += 1
                                    delta["motor_in"] += 1
                                    event = "IN"
                                else:
                                    state["motor_out_total"] += 1
                                    delta["motor_out"] += 1
                                    event = "OUT"

                            state = apply_loading(state)
                            state = set_rate_state(state, delta, bucket)
                            save_state(state)
                            append_event([
                                now_dt.isoformat(timespec="seconds"),
                                CAMERA_ID, PORT, track_id,
                                stable_family, round(float(confidence), 3),
                                direction, event,
                                state["car_in_total"], state["car_out_total"],
                                state["motor_in_total"], state["motor_out_total"],
                                state["car_queue_current"], state["motor_queue_current"],
                                "v4.4_dual_port_5min_rate",
                            ])
                            print(
                                f"[COUNT {event}] {now_dt:%H:%M:%S} ID={track_id} "
                                f"{stable_family} dir={direction} conf={confidence:.2f} "
                                f"queue car={state['car_queue_current']} "
                                f"motor={state['motor_queue_current']}"
                            )

                    if current_stable_side in (-1, 1):
                        meta["stable_side"] = current_stable_side
                        meta["stable_center"] = center
                    meta["last_center"] = center

                    # Show every tracked road vehicle in the crop. Counting still
                    # requires center inside ROI.
                    box_color = (255, 255, 255) if inside_roi else (150, 150, 150)
                    cv2.rectangle(overlay, (x1, y1), (x2, y2), box_color, 2)
                    cv2.circle(overlay, center, 3, box_color, -1)
                    counted_tag = " COUNTED" if meta["counted_dirs"] else ""
                    label = f"ID {track_id} {stable_family}{counted_tag} {confidence:.2f}"
                    cv2.putText(
                        overlay, label, (x1, max(18, y1 - 7)),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.48, box_color, 1, cv2.LINE_AA
                    )

            # Remove only genuinely stale track state. Counter totals remain persistent.
            stale_ids = [
                tid for tid, meta in tracks.items()
                if mono_now - meta["last_seen"] > TRACK_STALE_SECONDS
            ]
            for tid in stale_ids:
                tracks.pop(tid, None)

            state = apply_loading(load_state())
            panel_x1 = 14
            panel_y1 = max(10, height - 205)
            panel_x2 = min(width - 14, 730)
            panel_y2 = height - 14
            cv2.rectangle(overlay, (panel_x1, panel_y1), (panel_x2, panel_y2), (0, 0, 0), -1)
            cv2.rectangle(overlay, (panel_x1, panel_y1), (panel_x2, panel_y2), (255, 255, 255), 1)

            texts = [
                "CCTV VEHICLE COUNT - V4.2",
                f"Mobil antre={state['car_queue_current']} | masuk={state['car_in_total']} | flow keluar={state['car_out_total']}",
                f"Motor antre={state['motor_queue_current']} | masuk={state['motor_in_total']} | flow keluar={state['motor_out_total']}",
                f"Deteksi dalam ROI={detections_in_roi} | track aktif={len(tracks)}",
                f"Inference={inference_ms:.0f} ms | target={TARGET_INFERENCE_FPS:.0f} fps | imgsz={IMAGE_SIZE}",
                f"Waktu={now_dt:%Y-%m-%d %H:%M:%S}",
            ]
            y = panel_y1 + 27
            for idx, text in enumerate(texts):
                fs = 0.60 if idx == 0 else 0.46
                cv2.putText(
                    overlay, text, (panel_x1 + 12, y),
                    cv2.FONT_HERSHEY_SIMPLEX, fs, (255, 255, 255), 1, cv2.LINE_AA
                )
                y += 29

            if (out_w, out_h) != (width, height):
                annotated = cv2.resize(overlay, (out_w, out_h), interpolation=cv2.INTER_AREA)
            else:
                annotated = overlay
            publisher.update(annotated)

            processed_frames += 1
            stats_now = time.perf_counter()
            if stats_now - stats_last_print >= 5.0:
                elapsed = stats_now - stats_started
                effective_fps = processed_frames / max(elapsed, 1e-6)
                frame_age_ms = max(0.0, (stats_now - frame_ts) * 1000.0)
                skipped = max(0, source_frames_seen - processed_frames)
                print(
                    "[PERF] "
                    f"infer_fps={effective_fps:.2f} "
                    f"last={inference_ms:.0f}ms "
                    f"frame_age={frame_age_ms:.0f}ms "
                    f"det_roi={detections_in_roi} "
                    f"tracks={len(tracks)} "
                    f"skipped_latest={skipped}"
                )
                if effective_fps < 7.0:
                    print(
                        "[PERF-WARN] inference < 7 fps. Jangan menilai akurasi counting "
                        "sebelum beban RAW publisher dinormalkan/stream-copy."
                    )
                stats_last_print = stats_now

    except KeyboardInterrupt:
        print("\nStop requested.")
    finally:
        reader.stop()
        try:
            publisher.stop()
        except Exception:
            pass


if __name__ == "__main__":
    main()
