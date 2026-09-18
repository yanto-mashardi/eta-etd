# JAES_SIMULASI_BIMA2

Project ini dibuat otomatis dengan **LOCAL_RUN_STANDARD_V2**.

Struktur wajib:
- data/input, data/reference, data/processed
- notebooks
- models
- outputs/model_runs
- config
- scripts
- docs
- logs

Persistent logging tersedia melalui scripts/run_logging.py.

Contoh inisialisasi di awal notebook:

    from scripts.project_core import find_project_root
    PROJECT_ROOT = find_project_root()

    from scripts.run_logging import setup_notebook_logging
    RUN_LOGGER = setup_notebook_logging(
        PROJECT_ROOT,
        notebook_name="nama_notebook.ipynb",
        project_name="JAES_SIMULASI_BIMA2",
    )

Output logger:
- logs/latest_run.log
- logs/latest_run.json
- logs/latest_error.txt
- logs/run_<timestamp>.log
