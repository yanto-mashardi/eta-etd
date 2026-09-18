# JAES_SIMULASI_BIMA2 — Realtime Dashboard Architecture V5

Struktur folder utama dipertahankan.

## Dashboard
1. Public Bengkalis: CCTV, kendaraan saat ini, 2 dermaga, kapal, ETA, ETD.
2. Public Pakning: struktur sama; CCTV/vehicle state aktif saat sumber Pakning tersedia.
3. Inspection (login): realtime health, historical analysis, ML1 Lab, ML2 Lab, error analysis, model comparison, registry/activation, system logs.

## Realtime
AIS API -> `data/01_DATA_SOURCE/AIS/realtime/ais_current_state.json` (fallback sementara `ais_realtime.csv`).
CCTV -> `data/01_DATA_SOURCE/CCTV/output/vehicle_state.json`.
`vehicle_observation_5min.csv` tidak digunakan oleh dashboard atau ML2 realtime.
Jam operasional mengikuti laptop/Asia-Jakarta.

## Historical model research
ML1: `data/01_DATA_SOURCE/AIS/historical/`.
ML2: `data/01_DATA_SOURCE/VEHICLE_HISTORICAL/` + turnaround AIS + vessel capacity.
Validation: chronological 80/20.
Realtime AIS/CCTV tidak otomatis menjadi training data.

## Lifecycle
TRAIN -> VALIDATE -> ANALYSE -> COMPARE -> REGISTER CANDIDATE -> ACTIVATE.
Training dari Inspection tidak otomatis mengganti model aktif.

## Current state
`outputs/realtime/current_operation_state.json` dengan turunan `current_bengkalis_state.json` dan `current_pakning_state.json` menjadi kontrak realtime dashboard.
