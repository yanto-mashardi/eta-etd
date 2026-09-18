import cv2
import json
import csv
import time
import numpy as np
from pathlib import Path
from ultralytics import YOLO

# =========================================================
# PENGATURAN UTAMA
# =========================================================

VIDEO = "input/kendaraan.mp4"
CONFIG_FILE = "roi_config.json"

# Atur rentang waktu analisis di sini
# Boleh bilangan bulat atau desimal
# Contoh:
# 0 sampai 5   = menit 00:00 s.d. 05:00
# 2.5 sampai 7 = menit 02:30 s.d. 07:00
START_MINUTE = 0
END_MINUTE = 5

OUTPUT_VIDEO = f"output/hasil_count_{START_MINUTE}_{END_MINUTE}menit.mp4"
OUTPUT_CSV = f"output/count_events_{START_MINUTE}_{END_MINUTE}menit.csv"

# =========================================================
# PENGATURAN YOLO
# =========================================================

MODEL = "yolo26s.pt"
CONFIDENCE = 0.10
IMAGE_SIZE = 960
DEVICE = "cpu"   # tetap CPU dahulu agar stabil untuk laptop Anda

# =========================================================
# PENGATURAN ARAH / LOGIKA COUNTING
# =========================================================
# NET:
#   kendaraan masuk  = +1
#   kendaraan keluar = -1
#
# Jika arah fisik masuk ternyata terbalik pada video,
# cukup ubah ENTRY_DIRECTION menjadi "B_TO_A".
COUNT_MODE = "NET"
ENTRY_DIRECTION = "A_TO_B"

# Jumlah kendaraan yang sudah berada di area pada awal
# rentang video yang dianalisis.
INITIAL_CAR_COUNT = 0
INITIAL_MOTOR_COUNT = 0

# COCO class ID
CAR_CLASS = 2
MOTOR_CLASS = 3
VEHICLE_CLASSES = [CAR_CLASS, MOTOR_CLASS]

# =========================================================
# WARNA TAMPILAN
# =========================================================

COLOR_ROI = (0, 255, 0)        # hijau
COLOR_LINE = (0, 0, 255)       # merah
COLOR_BOX = (255, 255, 255)    # putih
COLOR_TEXT = (255, 255, 255)   # putih
COLOR_PANEL_BG = (0, 0, 0)     # hitam
COLOR_PANEL_BORDER = (255, 255, 255)

# =========================================================
# FUNGSI BANTU
# =========================================================

def format_time(seconds):
    minutes = int(seconds // 60)
    secs = seconds % 60
    return f"{minutes:02d}:{secs:05.2f}"


def line_side(point, a, b):
    return (
        (b[0] - a[0]) * (point[1] - a[1])
        - (b[1] - a[1]) * (point[0] - a[0])
    )


def segments_intersect(p1, p2, q1, q2):
    def orientation(a, b, c):
        value = ((b[1] - a[1]) * (c[0] - b[0])) - ((b[0] - a[0]) * (c[1] - b[1]))
        if abs(value) < 1e-9:
            return 0
        return 1 if value > 0 else 2

    def on_segment(a, b, c):
        return (
            min(a[0], c[0]) <= b[0] <= max(a[0], c[0]) and
            min(a[1], c[1]) <= b[1] <= max(a[1], c[1])
        )

    o1 = orientation(p1, p2, q1)
    o2 = orientation(p1, p2, q2)
    o3 = orientation(q1, q2, p1)
    o4 = orientation(q1, q2, p2)

    if o1 != o2 and o3 != o4:
        return True

    if o1 == 0 and on_segment(p1, q1, p2):
        return True
    if o2 == 0 and on_segment(p1, q2, p2):
        return True
    if o3 == 0 and on_segment(q1, p1, q2):
        return True
    if o4 == 0 and on_segment(q1, p2, q2):
        return True

    return False


# =========================================================
# CEK FILE
# =========================================================

if not Path(VIDEO).exists():
    raise FileNotFoundError(f"Video tidak ditemukan: {VIDEO}")

if not Path(CONFIG_FILE).exists():
    raise FileNotFoundError(
        "File roi_config.json tidak ditemukan. Jalankan setup_roi.py dahulu."
    )

Path("output").mkdir(exist_ok=True)

# =========================================================
# LOAD ROI CONFIG
# =========================================================

with open(CONFIG_FILE, "r", encoding="utf-8") as f:
    config = json.load(f)

config_w = config["video_width"]
config_h = config["video_height"]

roi_original = np.array(config["roi"], dtype=np.int32)
line_original = config["counting_line"]

# =========================================================
# BUKA VIDEO
# =========================================================

cap = cv2.VideoCapture(VIDEO)

if not cap.isOpened():
    raise RuntimeError("Video gagal dibuka.")

fps = cap.get(cv2.CAP_PROP_FPS)
width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
duration_sec = total_frames / fps

# =========================================================
# SESUAIKAN SKALA ROI KE VIDEO AKTUAL
# =========================================================

scale_x = width / config_w
scale_y = height / config_h

roi = np.array(
    [[int(x * scale_x), int(y * scale_y)] for x, y in roi_original],
    dtype=np.int32
)

line = [
    (int(line_original[0][0] * scale_x), int(line_original[0][1] * scale_y)),
    (int(line_original[1][0] * scale_x), int(line_original[1][1] * scale_y)),
]

# =========================================================
# VALIDASI RENTANG WAKTU
# =========================================================

start_sec = START_MINUTE * 60
end_sec = END_MINUTE * 60

if start_sec >= duration_sec:
    raise ValueError("START_MINUTE berada di luar durasi video.")

end_sec = min(end_sec, duration_sec)

if end_sec <= start_sec:
    raise ValueError("END_MINUTE harus lebih besar dari START_MINUTE.")

print()
print("========================================")
print("INFORMASI VIDEO")
print("========================================")
print(f"Resolusi video   : {width} x {height}")
print(f"FPS              : {fps:.2f}")
print(f"Durasi video     : {duration_sec/60:.2f} menit")
print(f"Rentang analisis : {START_MINUTE:.2f} s.d. {end_sec/60:.2f} menit")
print(f"ROI points       : {roi.tolist()}")
print(f"Counting line    : {line}")
print("========================================")
print()

# =========================================================
# POSISIKAN KE MENIT AWAL
# =========================================================

cap.set(cv2.CAP_PROP_POS_MSEC, start_sec * 1000)

# =========================================================
# OUTPUT VIDEO
# =========================================================

fourcc = cv2.VideoWriter_fourcc(*"mp4v")
writer = cv2.VideoWriter(OUTPUT_VIDEO, fourcc, fps, (width, height))

if not writer.isOpened():
    raise RuntimeError("Video output gagal dibuat.")

# =========================================================
# LOAD MODEL
# =========================================================

print("Memuat model YOLO...")
model = YOLO(MODEL)
print("Model siap.")
print()

# =========================================================
# VARIABEL COUNTING
# =========================================================

car_count = INITIAL_CAR_COUNT
motor_count = INITIAL_MOTOR_COUNT

car_in = 0
car_out = 0
motor_in = 0
motor_out = 0

# Satu ID dapat melintas satu kali pada masing-masing arah.
counted_crossings = set()

previous_centers = {}
event_rows = []

frame_counter = 0
process_start_time = time.time()

# =========================================================
# LOOP PEMROSESAN VIDEO
# =========================================================

while cap.isOpened():
    current_time_sec = cap.get(cv2.CAP_PROP_POS_MSEC) / 1000

    if current_time_sec >= end_sec:
        break

    success, frame = cap.read()
    if not success:
        break

    overlay = frame.copy()

    # -----------------------------------------------------
    # TRACKING
    # -----------------------------------------------------
    results = model.track(
        source=frame,
    	persist=True,
    	tracker="bytetrack_vehicle.yaml",
    	classes=VEHICLE_CLASSES,
    	conf=CONFIDENCE,
    	imgsz=IMAGE_SIZE,
    	device="cpu",
    	verbose=False
	)

    # -----------------------------------------------------
    # TAMPILKAN ROI DAN COUNTING LINE PADA OUTPUT VIDEO
    # -----------------------------------------------------
    cv2.polylines(overlay, [roi], True, COLOR_ROI, 3)
    cv2.line(overlay, line[0], line[1], COLOR_LINE, 4)

    # Label ROI dan line
    roi_label_point = tuple(roi[0])
    cv2.putText(
        overlay,
        "ROI",
        (roi_label_point[0] + 5, roi_label_point[1] - 10),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.7,
        COLOR_ROI,
        2
    )

    mid_x = int((line[0][0] + line[1][0]) / 2)
    mid_y = int((line[0][1] + line[1][1]) / 2)
    cv2.putText(
        overlay,
        "COUNT LINE",
        (mid_x - 70, mid_y - 10),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.6,
        COLOR_LINE,
        2
    )

    result = results[0]

    if result.boxes is not None and result.boxes.id is not None:
        boxes = result.boxes.xyxy.cpu().numpy()
        ids = result.boxes.id.int().cpu().tolist()
        classes = result.boxes.cls.int().cpu().tolist()
        confidences = result.boxes.conf.cpu().tolist()

        for box, track_id, cls_id, conf in zip(boxes, ids, classes, confidences):
            x1, y1, x2, y2 = map(int, box)
            cx = int((x1 + x2) / 2)
            cy = int((y1 + y2) / 2)
            center = (cx, cy)

            previous = previous_centers.get(track_id)

            # cek apakah center objek berada dalam ROI
            inside_roi = cv2.pointPolygonTest(roi, center, False) >= 0

            # tentukan nama kelas
            if cls_id == CAR_CLASS:
                class_name = "CAR"
            elif cls_id == MOTOR_CLASS:
                class_name = "MOTOR"
            else:
                class_name = "OTHER"

            # hanya tampilkan box jika center berada di ROI
            if inside_roi:
                # bounding box
                cv2.rectangle(overlay, (x1, y1), (x2, y2), COLOR_BOX, 2)

                # titik tengah
                cv2.circle(overlay, center, 5, COLOR_BOX, -1)

                # cek apakah ID pernah tercatat pada salah satu arah
                has_crossed = any(key[0] == track_id for key in counted_crossings)

                if has_crossed:
                    label = f"ID {track_id} {class_name} COUNTED {conf:.2f}"
                else:
                    label = f"ID {track_id} {class_name} {conf:.2f}"

                cv2.putText(
                    overlay,
                    label,
                    (x1, max(y1 - 10, 20)),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.55,
                    COLOR_TEXT,
                    2
                )

                # proses arah dan counting ketika trajectory melintasi line
                if previous is not None:
                    crossed = segments_intersect(previous, center, line[0], line[1])

                    if crossed:
                        side_prev = line_side(previous, line[0], line[1])
                        side_now = line_side(center, line[0], line[1])

                        if side_prev < 0 and side_now >= 0:
                            direction = "A_TO_B"
                        else:
                            direction = "B_TO_A"

                        crossing_key = (track_id, direction)

                        # Cegah kendaraan yang sama dihitung berulang
                        # ketika berada di sekitar counting line.
                        if crossing_key not in counted_crossings:
                            counted_crossings.add(crossing_key)

                            is_entry = direction == ENTRY_DIRECTION

                            if cls_id == CAR_CLASS:
                                if is_entry:
                                    car_in += 1
                                    car_count += 1
                                    event_type = "IN"
                                else:
                                    car_out += 1
                                    event_type = "OUT"
                                    if COUNT_MODE == "NET":
                                        car_count = max(0, car_count - 1)

                            elif cls_id == MOTOR_CLASS:
                                if is_entry:
                                    motor_in += 1
                                    motor_count += 1
                                    event_type = "IN"
                                else:
                                    motor_out += 1
                                    event_type = "OUT"
                                    if COUNT_MODE == "NET":
                                        motor_count = max(0, motor_count - 1)
                            else:
                                event_type = "UNKNOWN"

                            event_rows.append({
                                "video_time": format_time(current_time_sec),
                                "video_seconds": round(current_time_sec, 3),
                                "track_id": track_id,
                                "class": class_name,
                                "confidence": round(conf, 3),
                                "direction": direction,
                                "event": event_type,
                                "car_current": car_count,
                                "motor_current": motor_count
                            })

                            print(
                                f"[{event_type}] {format_time(current_time_sec)} | "
                                f"ID={track_id} | {class_name} | "
                                f"DIR={direction} | "
                                f"Mobil={car_count} | Motor={motor_count}"
                            )

            previous_centers[track_id] = center

    # -----------------------------------------------------
    # PANEL INFORMASI DI POJOK KIRI BAWAH
    # -----------------------------------------------------
    panel_x1 = 20
    panel_x2 = 700
    panel_y2 = height - 20
    panel_y1 = panel_y2 - 245

    cv2.rectangle(
        overlay,
        (panel_x1, panel_y1),
        (panel_x2, panel_y2),
        COLOR_PANEL_BG,
        -1
    )

    cv2.rectangle(
        overlay,
        (panel_x1, panel_y1),
        (panel_x2, panel_y2),
        COLOR_PANEL_BORDER,
        2
    )

    cv2.putText(
        overlay,
        "INFORMASI JUMLAH KENDARAAN",
        (panel_x1 + 20, panel_y1 + 35),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.8,
        COLOR_TEXT,
        2
    )

    cv2.putText(
        overlay,
        f"Jumlah Mobil Saat Ini = {car_count}",
        (panel_x1 + 20, panel_y1 + 80),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.82,
        COLOR_TEXT,
        2
    )

    cv2.putText(
        overlay,
        f"Mobil Masuk = {car_in}   |   Mobil Keluar = {car_out}",
        (panel_x1 + 20, panel_y1 + 115),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.62,
        COLOR_TEXT,
        2
    )

    cv2.putText(
        overlay,
        f"Jumlah Motor Saat Ini = {motor_count}",
        (panel_x1 + 20, panel_y1 + 155),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.82,
        COLOR_TEXT,
        2
    )

    cv2.putText(
        overlay,
        f"Motor Masuk = {motor_in}   |   Motor Keluar = {motor_out}",
        (panel_x1 + 20, panel_y1 + 190),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.62,
        COLOR_TEXT,
        2
    )

    cv2.putText(
        overlay,
        f"Total Kendaraan Saat Ini = {car_count + motor_count}",
        (panel_x1 + 20, panel_y1 + 230),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.72,
        COLOR_TEXT,
        2
    )

    # waktu video di kanan atas panel
    cv2.putText(
        overlay,
        f"Waktu Video = {format_time(current_time_sec)}",
        (panel_x1 + 360, panel_y1 + 35),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.55,
        (200, 200, 200),
        1
    )

    # -----------------------------------------------------
    # SIMPAN FRAME
    # -----------------------------------------------------
    writer.write(overlay)

    frame_counter += 1

    if frame_counter % 100 == 0:
        elapsed = time.time() - process_start_time
        processed_duration = current_time_sec - start_sec
        total_selected = end_sec - start_sec
        percent = (processed_duration / total_selected) * 100 if total_selected > 0 else 0

        print(
            f"Progress {percent:6.2f}% | "
            f"Waktu video {format_time(current_time_sec)} | "
            f"Waktu proses {elapsed/60:.2f} menit"
        )

# =========================================================
# RELEASE
# =========================================================

cap.release()
writer.release()
cv2.destroyAllWindows()

# =========================================================
# SIMPAN CSV
# =========================================================

with open(OUTPUT_CSV, "w", newline="", encoding="utf-8") as f:
    fieldnames = [
        "video_time",
        "video_seconds",
        "track_id",
        "class",
        "confidence",
        "direction",
        "event",
        "car_current",
        "motor_current"
    ]

    csv_writer = csv.DictWriter(f, fieldnames=fieldnames)
    csv_writer.writeheader()
    csv_writer.writerows(event_rows)

# =========================================================
# RINGKASAN HASIL
# =========================================================

elapsed_total = time.time() - process_start_time

print()
print("========================================")
print("SELESAI")
print("========================================")
print(f"Jumlah Mobil Saat Ini  : {car_count}")
print(f"Mobil Masuk             : {car_in}")
print(f"Mobil Keluar            : {car_out}")
print(f"Jumlah Motor Saat Ini   : {motor_count}")
print(f"Motor Masuk             : {motor_in}")
print(f"Motor Keluar            : {motor_out}")
print(f"Jumlah Total Saat Ini   : {car_count + motor_count}")
print(f"Crossing unik tercatat  : {len(counted_crossings)}")
print("----------------------------------------")
print(f"Video output        : {OUTPUT_VIDEO}")
print(f"CSV output          : {OUTPUT_CSV}")
print(f"Waktu proses        : {elapsed_total/60:.2f} menit")
print("========================================")