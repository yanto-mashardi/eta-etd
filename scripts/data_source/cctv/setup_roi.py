import cv2
import json
from pathlib import Path

# ==============================
# PENGATURAN
# ==============================

VIDEO = "input/kendaraan.mp4"

# Frame yang digunakan untuk memilih ROI
# Misalnya menit ke-5
FRAME_MINUTE = 5

CONFIG_FILE = "roi_config.json"

# Ukuran maksimum jendela tampilan
MAX_W = 1280
MAX_H = 720


# ==============================
# BUKA VIDEO
# ==============================

if not Path(VIDEO).exists():
    raise FileNotFoundError(f"Video tidak ditemukan: {VIDEO}")

cap = cv2.VideoCapture(VIDEO)

if not cap.isOpened():
    raise RuntimeError("Video tidak dapat dibuka.")

cap.set(
    cv2.CAP_PROP_POS_MSEC,
    FRAME_MINUTE * 60 * 1000
)

success, frame_original = cap.read()

if not success:
    raise RuntimeError("Frame video tidak dapat dibaca.")

cap.release()

H, W = frame_original.shape[:2]

scale = min(
    MAX_W / W,
    MAX_H / H,
    1.0
)

display_w = int(W * scale)
display_h = int(H * scale)

base_frame = cv2.resize(
    frame_original,
    (display_w, display_h)
)

roi_points = []
line_points = []

phase = "ROI"


# ==============================
# MOUSE
# ==============================

def mouse_callback(event, x, y, flags, param):
    global phase

    if event != cv2.EVENT_LBUTTONDOWN:
        return

    if phase == "ROI":
        roi_points.append((x, y))

    elif phase == "LINE":

        if len(line_points) < 2:
            line_points.append((x, y))


# ==============================
# WINDOW
# ==============================

window_name = "SETUP ROI DAN COUNTING LINE"

cv2.namedWindow(window_name)

cv2.setMouseCallback(
    window_name,
    mouse_callback
)


while True:

    canvas = base_frame.copy()

    # --------------------------
    # GAMBAR ROI
    # --------------------------

    for p in roi_points:
        cv2.circle(canvas, p, 5, (0, 255, 0), -1)

    if len(roi_points) >= 2:

        for i in range(len(roi_points) - 1):

            cv2.line(
                canvas,
                roi_points[i],
                roi_points[i + 1],
                (0, 255, 0),
                2
            )

    if phase == "LINE" and len(roi_points) >= 3:

        cv2.polylines(
            canvas,
            [__import__("numpy").array(roi_points)],
            True,
            (0, 255, 0),
            2
        )


    # --------------------------
    # GAMBAR COUNTING LINE
    # --------------------------

    for p in line_points:
        cv2.circle(canvas, p, 7, (0, 0, 255), -1)

    if len(line_points) == 2:

        cv2.line(
            canvas,
            line_points[0],
            line_points[1],
            (0, 0, 255),
            3
        )


    # --------------------------
    # PETUNJUK
    # --------------------------

    if phase == "ROI":

        text1 = "TAHAP 1: Klik titik-titik mengelilingi AREA JALAN"
        text2 = "ENTER = selesai ROI | R = reset | Q = keluar"

    else:

        text1 = "TAHAP 2: Klik 2 titik untuk COUNTING LINE"
        text2 = "ENTER = simpan | R = reset line | Q = keluar"

    cv2.putText(
        canvas,
        text1,
        (20, 35),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.7,
        (255, 255, 255),
        2
    )

    cv2.putText(
        canvas,
        text2,
        (20, 65),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.6,
        (255, 255, 255),
        2
    )

    cv2.imshow(window_name, canvas)

    key = cv2.waitKey(20) & 0xFF


    # ENTER
    if key == 13:

        if phase == "ROI":

            if len(roi_points) < 3:

                print("ROI minimal membutuhkan 3 titik.")
                continue

            phase = "LINE"

            print("ROI selesai.")
            print("Sekarang pilih 2 titik counting line.")

        else:

            if len(line_points) != 2:

                print("Counting line harus mempunyai 2 titik.")
                continue

            break


    # R
    elif key == ord("r"):

        if phase == "ROI":
            roi_points.clear()

        else:
            line_points.clear()


    # Q
    elif key == ord("q"):

        cv2.destroyAllWindows()
        raise SystemExit


cv2.destroyAllWindows()


# ==============================
# KONVERSI KE RESOLUSI ASLI
# ==============================

roi_original = [
    [int(x / scale), int(y / scale)]
    for x, y in roi_points
]

line_original = [
    [int(x / scale), int(y / scale)]
    for x, y in line_points
]


config = {
    "video_width": W,
    "video_height": H,
    "roi": roi_original,
    "counting_line": line_original
}


with open(CONFIG_FILE, "w") as f:

    json.dump(
        config,
        f,
        indent=4
    )


print()
print("==============================")
print("ROI BERHASIL DISIMPAN")
print("==============================")
print(f"File : {CONFIG_FILE}")
print(f"ROI  : {roi_original}")
print(f"Line : {line_original}")