from __future__ import annotations

import argparse
import csv
import json
import os
import platform
import re
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path

from project_core_v3 import find_project_root, machine_id

ARCH = 'LOCAL_RUN_STANDARD_V3'


def now_iso():
    return datetime.now().astimezone().isoformat(timespec='seconds')


def read_json(path: Path, default=None):
    try:
        return json.loads(path.read_text(encoding='utf-8-sig'))
    except FileNotFoundError:
        return default


def write_json(path: Path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding='utf-8')


def _read_csv_rows(path: Path):
    if not path.exists():
        return []
    with path.open('r', encoding='utf-8-sig', newline='') as f:
        return list(csv.DictReader(f))


def build_run_summary(root: Path, run_root: Path, manifest: dict):
    """Create human-readable and machine-readable summaries for a completed JAES run."""
    summary_json = {
        'architecture_version': ARCH,
        'project': manifest.get('project'),
        'run_id': manifest.get('run_id'),
        'machine_id': manifest.get('machine_id'),
        'status': manifest.get('status'),
        'created_at': manifest.get('created_at'),
        'closed_at': manifest.get('closed_at'),
    }

    ml1_report = run_root / '01_ml1_eta' / 'analysis_interpretation' / 'reports' / 'interpretasi_ml1.md'
    ml1_text = ml1_report.read_text(encoding='utf-8-sig') if ml1_report.exists() else ''
    summary_json['ml1_report_present'] = bool(ml1_text)

    ml2_metrics_path = run_root / '02_ml2_turnaround' / 'tables' / 'ml2_model_metrics.csv'
    ml2_metrics = _read_csv_rows(ml2_metrics_path)
    summary_json['ml2_metrics'] = ml2_metrics

    contract_path = run_root / 'logs' / 'latest_contract_audit.json'
    contract = read_json(contract_path, {}) or {}
    summary_json['contract_audit'] = contract

    migration_path = run_root / 'logs' / 'latest_integration_migration.json'
    migration = read_json(migration_path, {}) or {}
    summary_json['integration_migration'] = migration

    operation_state = run_root / 'published' / 'operation_state_5min.csv'
    summary_json['operation_state_5min'] = {
        'present': operation_state.exists(),
        'size_bytes': operation_state.stat().st_size if operation_state.exists() else None,
        'relative_path': str(operation_state.relative_to(root)) if operation_state.exists() else None,
    }

    dash_root = run_root / '04_replay_dashboard'
    dashboard_files = {}
    for name in ['visual_track_5min.csv', 'daily_operation_schedule.csv', 'legacy_simulation_input_5min.csv']:
        q = dash_root / name
        dashboard_files[name] = {
            'present': q.exists(),
            'size_bytes': q.stat().st_size if q.exists() else None,
        }
    summary_json['dashboard_outputs'] = dashboard_files

    write_json(run_root / '00_run' / 'RUN_SUMMARY.json', summary_json)

    lines = [
        f"# Ringkasan Hasil {manifest.get('run_id', '')}",
        "",
        f"- Project: `{manifest.get('project', '')}`",
        f"- Machine: `{manifest.get('machine_id', '')}`",
        f"- Status: **{manifest.get('status', '')}**",
        f"- Dibuat: `{manifest.get('created_at', '')}`",
        f"- Ditutup: `{manifest.get('closed_at', '')}`",
        "",
        "## ML1 — Koreksi ETA",
        "",
    ]
    if ml1_text:
        ml1_lines = ml1_text.splitlines()
        if ml1_lines and ml1_lines[0].startswith('# '):
            ml1_lines = ml1_lines[1:]
        lines.extend(ml1_lines)
    else:
        lines.append("Laporan interpretasi ML1 tidak ditemukan pada run ini.")

    lines += ["", "## ML2 — Koreksi Turnaround", ""]
    if ml2_metrics:
        lines += [
            "| Model | MAE (menit) | RMSE (menit) | n test |",
            "|---|---:|---:|---:|",
        ]
        for row in ml2_metrics:
            try:
                mae = f"{float(row.get('MAE_min', 'nan')):.2f}"
                rmse = f"{float(row.get('RMSE_min', 'nan')):.2f}"
            except Exception:
                mae = row.get('MAE_min', '')
                rmse = row.get('RMSE_min', '')
            lines.append(f"| {row.get('model','')} | {mae} | {rmse} | {row.get('n_test','')} |")
        try:
            best = min(ml2_metrics, key=lambda r: float(r.get('MAE_min', 'inf')))
            lines += [
                "",
                f"Model ML2 dengan MAE terkecil pada data uji adalah **{best.get('model','')}** "
                f"dengan MAE **{float(best.get('MAE_min')):.2f} menit**.",
            ]
        except Exception:
            pass
    else:
        lines.append("Metrik ML2 tidak ditemukan pada run ini.")

    lines += ["", "## Integrasi ETA–ETD dan kontrak data", ""]
    if contract:
        lines.append(f"- Status contract audit: **{contract.get('status', 'UNKNOWN')}**")
        lines.append(f"- Mode integrasi: `{contract.get('integration_mode', '')}`")
        lines.append(f"- Provenance kendaraan: `{contract.get('vehicle_provenance', '')}`")
        lines.append(f"- Operational claim allowed: `{contract.get('operational_claim_allowed', '')}`")
        lines.append(f"- Missing required files: `{contract.get('missing_required_files', {})}`")
    else:
        lines.append("Contract audit tidak ditemukan.")

    if migration:
        lines.append(f"- Baris integrasi: `{migration.get('rows', '')}`")
        lines.append(f"- Output integrasi: `{migration.get('output', '')}`")

    lines += ["", "## Output simulasi/dashboard", ""]
    if operation_state.exists():
        lines.append(f"- `published/operation_state_5min.csv` tersedia ({operation_state.stat().st_size:,} bytes).")
    else:
        lines.append("- `published/operation_state_5min.csv` tidak ditemukan.")
    for name, info in dashboard_files.items():
        lines.append(f"- `{name}`: {'tersedia' if info['present'] else 'tidak ditemukan'}")

    lines += [
        "",
        "## Catatan penggunaan hasil",
        "",
        "Hasil pada run ini harus ditafsirkan sesuai provenance data pada contract audit. "
        "Jika provenance kendaraan adalah `SIMULATED_LEGACY` dan `operational_claim_allowed=false`, "
        "maka hasil ML2/ETD valid untuk reproduksi/simulasi metodologis, bukan klaim kinerja operasional aktual.",
        "",
    ]
    (run_root / '00_run' / 'RUN_SUMMARY.md').write_text('\n'.join(lines), encoding='utf-8')
    return summary_json


def next_run_number(root: Path) -> int:
    nums = []
    for p in (root / 'outputs').glob('RUN_*'):
        m = re.match(r'RUN_(\d{3,})_', p.name)
        if m:
            nums.append(int(m.group(1)))
    registry = root / 'logs' / 'run_registry.csv'
    if registry.exists():
        try:
            with registry.open(newline='', encoding='utf-8-sig') as f:
                for row in csv.DictReader(f):
                    n = row.get('run_number','').strip()
                    if n.isdigit(): nums.append(int(n))
        except Exception:
            pass
    return max(nums, default=0) + 1



def reusable_orphan_run(root: Path, mid: str, date_tag: str):
    # Reuse only an initialization scaffold that never reached manifest creation.
    # Completed or active runs are never reused.
    candidates = []
    pattern = f'RUN_*_{date_tag}_{mid}'
    for p in (root / 'outputs').glob(pattern):
        m = re.match(r'RUN_(\d{3,})_', p.name)
        if not m or not p.is_dir():
            continue
        if not (p / '00_run' / 'run_manifest.json').exists():
            candidates.append((int(m.group(1)), p))
    if not candidates:
        return None
    candidates.sort(key=lambda x: x[0])
    return candidates[0]

def acquire_lock(root: Path, force=False):
    lock = root / '.run_lock.json'
    if lock.exists() and not force:
        info = read_json(lock,{}) or {}
        raise RuntimeError(f"Project sedang memiliki run aktif: {info.get('run_id','UNKNOWN')} pada {info.get('machine_id','UNKNOWN')}. Gunakan --force hanya setelah memastikan run lama sudah berhenti.")
    return lock


def append_registry(root: Path, row: dict):
    path = root / 'logs' / 'run_registry.csv'
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = ['project','run_number','run_id','machine_id','computer_name','created_at','closed_at','status','run_folder']
    exists = path.exists()
    with path.open('a', newline='', encoding='utf-8-sig') as f:
        w = csv.DictWriter(f, fieldnames=fields)
        if not exists: w.writeheader()
        w.writerow({k: row.get(k,'') for k in fields})


def start_run(root: Path, open_jupyter=False, force=False, dry_run=False):
    root = root.resolve()
    lock = acquire_lock(root, force=force)
    project = root.name
    mid = machine_id()
    computer_name = os.environ.get('COMPUTERNAME') or platform.node() or mid
    date_tag = datetime.now().strftime('%Y%m%d')

    orphan = reusable_orphan_run(root, mid, date_tag)
    if orphan:
        run_number, run_root = orphan
        run_id = run_root.name
        run_rel = Path('outputs') / run_id
    else:
        run_number = next_run_number(root)
        run_id = f'RUN_{run_number:03d}_{date_tag}_{mid}'
        run_rel = Path('outputs') / run_id
        run_root = root / run_rel

    if dry_run:
        return {'project':project,'run_number':run_number,'run_id':run_id,'machine_id':mid,'run_folder':str(run_rel).replace('\\','/')}

    # Validate/read configuration before creating or reusing the run folder.
    pipeline = read_json(root / 'config' / 'active_pipeline.json', {'notebooks':[]}) or {'notebooks':[]}
    project_cfg = read_json(root / 'config' / 'project_config.json', {}) or {}

    (run_root / '00_run').mkdir(parents=True, exist_ok=True if orphan else False)
    (run_root / 'logs').mkdir(parents=True, exist_ok=True)
    ctx = {
        'architecture_version': ARCH,
        'project': project,
        'run_number': run_number,
        'run_id': run_id,
        'machine_id': mid,
        'computer_name': computer_name,
        'created_at': now_iso(),
        'status': 'ACTIVE',
        'run_folder': str(run_rel).replace('\\','/'),
        'pipeline_file': 'config/active_pipeline.json',
    }
    write_json(root / 'current_run.json', ctx)
    write_json(lock, ctx)
    manifest = dict(ctx)
    manifest.update({'completed_notebooks':[], 'python_executable':sys.executable, 'python_version':sys.version.split()[0]})
    write_json(run_root / '00_run' / 'run_manifest.json', manifest)
    write_json(run_root / '00_run' / 'pipeline_snapshot.json', pipeline)
    write_json(run_root / '00_run' / 'project_config_snapshot.json', project_cfg)
    append_registry(root, manifest)

    print('='*64)
    print('LOCAL_RUN STANDARD V3')
    print('Project :', project)
    print('Machine :', mid)
    print('Run ID  :', run_id)
    print('Folder  :', run_root)
    print('='*64)

    if open_jupyter:
        env = os.environ.copy()
        env['LOCAL_RUN_RUN_ID'] = run_id
        env['LOCAL_RUN_RUN_ROOT'] = str(run_root)
        env['LOCAL_RUN_PROJECT_ROOT'] = str(root)
        try:
            return_code = subprocess.call([sys.executable, '-m', 'jupyterlab', '--notebook-dir', str(root)], cwd=str(root), env=env)
        finally:
            close_run(root, status='CLOSED', note=f'Jupyter exited with code {locals().get("return_code", "unknown")}')
    return ctx


def close_run(root: Path, status='CLOSED', note=''):
    root = root.resolve()
    current = root / 'current_run.json'
    ctx = read_json(current, None)
    if not ctx:
        print('Tidak ada current_run.json. Tidak ada run yang ditutup.')
        return None

    run_root = root / ctx['run_folder']
    manifest_path = run_root / '00_run' / 'run_manifest.json'
    manifest = read_json(manifest_path, ctx) or dict(ctx)

    already_final = (
        manifest.get('status') == status
        and bool(manifest.get('closed_at'))
        and status in {'SUCCESS', 'CLOSED', 'FAILED'}
    )

    if not already_final:
        manifest['status'] = status
        manifest['closed_at'] = now_iso()
        if note:
            manifest['close_note'] = note
        write_json(manifest_path, manifest)
        if status == 'SUCCESS':
            write_json(root / 'latest_successful_run.json', manifest)
        append_registry(root, manifest)
    elif status == 'SUCCESS':
        write_json(root / 'latest_successful_run.json', manifest)

    try:
        build_run_summary(root, run_root, manifest)
    except Exception as exc:
        print(f'WARNING: RUN_SUMMARY gagal dibuat: {exc}')

    lock = root / '.run_lock.json'
    if lock.exists():
        lock.unlink()
    if current.exists():
        current.unlink()

    print(f"RUN FINALIZED: {manifest.get('run_id')} status={manifest.get('status')}")
    print(f"SUMMARY: {run_root / '00_run' / 'RUN_SUMMARY.md'}")
    return manifest


def status(root: Path):
    root = root.resolve()
    print(json.dumps(read_json(root/'current_run.json',{}), indent=2, ensure_ascii=False))


def smoke_test(root: Path):
    root = root.resolve()
    required = [root/'.local_run_project', root/'config', root/'notebooks', root/'outputs', root/'scripts']
    missing = [str(p) for p in required if not p.exists()]
    if missing: raise RuntimeError('V3 smoke test gagal. Missing: ' + ', '.join(missing))
    dry = start_run(root, dry_run=True)
    assert dry['run_id'].startswith('RUN_')
    print('SMOKE PASS:', dry['run_id'])
    return dry


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('command', choices=['start','close','success','status','smoke'])
    parser.add_argument('--project-root', default=None)
    parser.add_argument('--open-jupyter', action='store_true')
    parser.add_argument('--force', action='store_true')
    args = parser.parse_args()
    root = find_project_root(Path(args.project_root) if args.project_root else Path.cwd())
    if args.command == 'start': start_run(root, open_jupyter=args.open_jupyter, force=args.force)
    elif args.command == 'close': close_run(root, 'CLOSED')
    elif args.command == 'success': close_run(root, 'SUCCESS')
    elif args.command == 'status': status(root)
    elif args.command == 'smoke': smoke_test(root)

if __name__ == '__main__': main()
