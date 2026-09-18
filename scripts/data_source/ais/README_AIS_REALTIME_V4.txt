AIS REALTIME V4 - JAES_SIMULASI_BIMA2

Tujuan
- Menjadikan AIS API sebagai sumber posisi realtime untuk inferensi ML1.
- Data historis tetap menjadi satu-satunya sumber train/validation (chronological 80:20).
- Data API tidak pernah ditambahkan ke train/test secara otomatis.

Filter kapal
525002060
525002121
525003298
525015047
525100240

Aturan penerimaan
1. MMSI harus berada dalam whitelist di atas.
2. Posisi harus berada di koridor Bengkalis-Pakning (buffer di config/ais_source_config_v4.yaml).
3. Field destination AIS disimpan sebagai metadata, bukan syarat penerimaan.
4. heading=511 dan turn=-128 dinormalisasi menjadi missing value.
5. Raw response API disimpan di data/01_DATA_SOURCE/AIS/realtime/raw/*.jsonl.
6. Kontrak realtime bersih: data/01_DATA_SOURCE/AIS/realtime/ais_realtime.csv.

Environment PowerShell
$env:AIS_API_URL="<endpoint AIS yang sudah digunakan>"
# hanya bila API memakai bearer/token:
$env:AIS_API_KEY="<token>"

Jalankan
powershell -ExecutionPolicy Bypass -File .\scripts\data_source\ais\START_AIS_API_REALTIME_V4.ps1

Uji satu kali
C:\LOCAL_RUN_venv\.venv\Scripts\python.exe .\scripts\data_source\ais\poll_ais_api_realtime.py --once
