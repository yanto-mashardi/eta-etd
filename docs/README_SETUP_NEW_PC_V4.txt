JAES_SIMULASI_BIMA2 - SETUP PC BARU V4
======================================

Tujuan:
Menyiapkan environment lokal di C:\LOCAL_RUN_venv untuk menjalankan dashboard, CCTV realtime, YOLO/ByteTrack, ML1 dan ML2 tanpa memasang virtual environment di Google Drive.

STRUKTUR LOKAL
--------------
C:\LOCAL_RUN_venv\
├── .venv\
└── tools\
    ├── ffmpeg\
    │   └── bin\
    │       ├── ffmpeg.exe
    │       ├── ffplay.exe
    │       └── ffprobe.exe
    └── mediamtx\
        └── mediamtx.exe

LANGKAH SETUP
-------------
1. Pastikan Python 64-bit terpasang.
2. Buat virtual environment:
   python -m venv C:\LOCAL_RUN_venv\.venv

3. Upgrade pip:
   & "C:\LOCAL_RUN_venv\.venv\Scripts\python.exe" -m pip install --upgrade pip

4. Install dependency inti:
   & "C:\LOCAL_RUN_venv\.venv\Scripts\python.exe" -m pip install numpy pandas pyyaml requests scikit-learn xgboost joblib streamlit opencv-python ultralytics

5. Verifikasi OpenCV:
   & "C:\LOCAL_RUN_venv\.venv\Scripts\python.exe" -c "import cv2; print('OpenCV OK', cv2.__version__)"

6. Verifikasi Torch:
   & "C:\LOCAL_RUN_venv\.venv\Scripts\python.exe" -c "import torch; print('Torch OK', torch.__version__)"

7. Verifikasi Ultralytics:
   & "C:\LOCAL_RUN_venv\.venv\Scripts\python.exe" -c "import ultralytics; print('Ultralytics OK')"

8. Verifikasi FFmpeg:
   & "C:\LOCAL_RUN_venv\tools\ffmpeg\bin\ffmpeg.exe" -version

9. Verifikasi MediaMTX:
   & "C:\LOCAL_RUN_venv\tools\mediamtx\mediamtx.exe" --version

CATATAN WINDOWS APPLICATION CONTROL
-----------------------------------
Jika muncul:
OSError: [WinError 4551] An Application Control policy has blocked this file
saat import torch, jangan menganggap package belum terpasang.

Langkah aman pertama:
A. Tutup semua proses Python yang memakai environment tersebut.
B. Jalankan PowerShell as Administrator:
   Get-ChildItem "C:\LOCAL_RUN_venv" -Recurse -File | Unblock-File

C. Uji ulang:
   & "C:\LOCAL_RUN_venv\.venv\Scripts\python.exe" -c "import torch; print(torch.__version__)"

Jika masih diblokir:
- Periksa Windows Security > App & browser control.
- Jika PC dikelola institusi/organisasi, kebijakan WDAC/AppLocker dapat memblokir torch_python.dll dan harus diizinkan oleh administrator kebijakan.
- Jangan mematikan kebijakan keamanan organisasi secara paksa.
- Catat event pada Event Viewer:
  Applications and Services Logs > Microsoft > Windows > CodeIntegrity > Operational
  dan/atau
  Microsoft > Windows > AppLocker.

VERIFIKASI CCTV
---------------
Dari:
H:\My Drive\LOCAL_RUN\JAES_SIMULASI_BIMA2\scripts\data_source\cctv

Jalankan:
.\CHECK_REALTIME_V4.ps1
.\START_CCTV_RTSP_V4.ps1

PowerShell kedua:
.\START_YOLO_REALTIME_V4.ps1

RAW RTSP:
rtsp://127.0.0.1:8554/cctv_bengkalis

YOLO annotated RTSP:
rtsp://127.0.0.1:8554/cctv_bengkalis_yolo
