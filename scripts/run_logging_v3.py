from __future__ import annotations

import json
import platform
import sys
import traceback
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional

from .project_core_v3 import get_logs_dir, load_current_run, find_project_root


def _now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec='seconds')


class PersistentNotebookRunLogger:
    def __init__(self, project_root: Path, notebook_name: str, project_name: Optional[str] = None):
        self.project_root = find_project_root(project_root)
        self.run_context = load_current_run(self.project_root) or {}
        self.logs_dir = get_logs_dir(self.project_root)
        self.logs_dir.mkdir(parents=True, exist_ok=True)
        self.notebook_name = notebook_name
        self.project_name = project_name or self.project_root.name
        self.run_id = self.run_context.get('run_id') or datetime.now().strftime('%Y%m%d_%H%M%S')
        stem = Path(notebook_name).stem.replace(' ','_')
        self.run_log = self.logs_dir / f'{stem}.log'
        self.latest_log = self.logs_dir / 'latest_run.log'
        self.latest_json = self.logs_dir / 'latest_run.json'
        self.latest_error = self.logs_dir / 'latest_error.txt'
        self.started_at = _now_iso(); self.cell_counter=0; self.current_cell=None
        self._ip=None; self._registered=False; self._completed=False
        self.latest_error.write_text('',encoding='utf-8')
        self._append('RUN START',project=self.project_name,notebook=self.notebook_name,run_id=self.run_id,
                     machine=self.run_context.get('machine_id',platform.node()),python=sys.version.split()[0],project_root=str(self.project_root))
        self._write_status('running')

    def _append(self,message:str,**fields:Any):
        line=' | '.join([f'[{_now_iso()}]',message,*[f'{k}={v}' for k,v in fields.items()]])+'\n'
        with self.run_log.open('a',encoding='utf-8') as f:f.write(line)
        with self.latest_log.open('a',encoding='utf-8') as f:f.write(line)

    def _write_status(self,status:str,**extra:Any):
        payload={'run_id':self.run_id,'project':self.project_name,'notebook':self.notebook_name,'status':status,
                 'started_at':self.started_at,'updated_at':_now_iso(),'project_root':str(self.project_root),
                 'logs_dir':str(self.logs_dir),'last_cell':self.current_cell,'cell_counter':self.cell_counter}
        payload.update(extra)
        self.latest_json.write_text(json.dumps(payload,ensure_ascii=False,indent=2,default=str),encoding='utf-8')

    def stage(self,name:str,**fields:Any):
        self._append('STAGE',name=name,**fields)
        if not self._completed:self._write_status('running',stage=name,**fields)

    def _pre_run_cell(self,info):
        if self._completed:self._completed=False
        self.cell_counter+=1
        raw=(getattr(info,'raw_cell','') or '').strip(); first=raw.splitlines()[0][:140] if raw else '<empty>'
        self.current_cell={'sequence':self.cell_counter,'first_line':first}
        self._append('CELL START',sequence=self.cell_counter,first_line=first); self._write_status('running')

    def _post_run_cell(self,result):
        err=getattr(result,'error_before_exec',None) or getattr(result,'error_in_exec',None)
        count=getattr(result,'execution_count',None)
        if err is not None:
            self._completed=False
            tb=''.join(traceback.format_exception(type(err),err,err.__traceback__))
            self.latest_error.write_text(f'RUN_ID: {self.run_id}\nPROJECT: {self.project_name}\nNOTEBOOK: {self.notebook_name}\nTIME: {_now_iso()}\nEXECUTION_COUNT: {count}\n\n'+tb,encoding='utf-8')
            self._append('CELL ERROR',sequence=self.cell_counter,execution_count=count,error_type=type(err).__name__,error=str(err).replace('\n',' ')[:500])
            self._write_status('error',execution_count=count,error_type=type(err).__name__,error=str(err))
        else:
            self._append('CELL OK',sequence=self.cell_counter,execution_count=count)
            if not self._completed:self._write_status('running',execution_count=count)

    def register_ipython(self):
        try: ip=get_ipython()  # type: ignore[name-defined]
        except Exception: ip=None
        if ip is None:self._append('LOGGER NOTICE',message='Not running inside IPython/Jupyter');return
        old=ip.user_ns.get('_PERSISTENT_RUN_LOGGER')
        if old is not None and old is not self:
            try:old.unregister_ipython()
            except Exception:pass
        ip.events.register('pre_run_cell',self._pre_run_cell);ip.events.register('post_run_cell',self._post_run_cell)
        ip.user_ns['_PERSISTENT_RUN_LOGGER']=self;self._ip=ip;self._registered=True
        self._append('LOGGER READY',mode='jupyter_cell_events')

    def unregister_ipython(self):
        if self._ip is not None and self._registered:
            for event,func in [('pre_run_cell',self._pre_run_cell),('post_run_cell',self._post_run_cell)]:
                try:self._ip.events.unregister(event,func)
                except Exception:pass
        self._registered=False

    def mark_complete(self,**fields:Any):
        self._completed=True;self.latest_error.write_text('',encoding='utf-8')
        self._append('RUN COMPLETE',**fields);self._write_status('success',completed_at=_now_iso(),**fields)


def setup_notebook_logging(project_root:Path,notebook_name:str,project_name:Optional[str]=None)->PersistentNotebookRunLogger:
    logger=PersistentNotebookRunLogger(project_root,notebook_name,project_name);logger.register_ipython();return logger
