Urutan:
1. .\CHECK_REALTIME_V4.ps1
2. .\START_CCTV_RTSP_V4.ps1
3. PowerShell kedua: .\START_YOLO_REALTIME_V4.ps1
4. VLC: rtsp://127.0.0.1:8554/cctv_bengkalis_yolo

RAW: rtsp://127.0.0.1:8554/cctv_bengkalis
YOLO: rtsp://127.0.0.1:8554/cctv_bengkalis_yolo

State: data\01_DATA_SOURCE\CCTV\output\vehicle_state.json
Events: data\01_DATA_SOURCE\CCTV\output\vehicle_events.csv
5-min: data\01_DATA_SOURCE\CCTV\output\vehicle_observation_5min.csv

ENTRY menambah antrean.
OUT hanya dicatat sebagai flow keluar.
Antrean berkurang hanya melalui loaded_car_total / loaded_motor_total dari event loading kapal.
Counter tidak reset ketika video loop.
