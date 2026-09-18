from __future__ import annotations

import json
import platform
import sys
import traceback
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional


def _now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


class PersistentNotebookRunLogger:
    """
    Persistent cell-level logger for Jupyter notebooks.

    Creates in <PROJECT_ROOT>/logs:
      - run_<RUN_ID>.log       : immutable log for this run
      - latest_run.log         : mirror of the current/latest run
      - latest_run.json        : machine-readable current status
      - latest_error.txt       : traceback of the latest cell error
    """

    def __init__(self, project_root: Path, notebook_name: str, project_name: Optional[str] = None):
        self.project_root = Path(project_root).resolve()
        self.logs_dir = self.project_root / "logs"
        self.logs_dir.mkdir(parents=True, exist_ok=True)

        self.notebook_name = notebook_name
        self.project_name = project_name or self.project_root.name
        self.run_id = datetime.now().strftime("%Y%m%d_%H%M%S")

        self.run_log = self.logs_dir / f"run_{self.run_id}.log"
        self.latest_log = self.logs_dir / "latest_run.log"
        self.latest_json = self.logs_dir / "latest_run.json"
        self.latest_error = self.logs_dir / "latest_error.txt"

        self.started_at = _now_iso()
        self.cell_counter = 0
        self.current_cell = None
        self._ip = None
        self._registered = False
        self._completed = False

        self.latest_log.write_text("", encoding="utf-8")
        self.latest_error.write_text("", encoding="utf-8")

        self._append(
            "RUN START",
            project=self.project_name,
            notebook=self.notebook_name,
            python=sys.version.split()[0],
            platform=platform.platform(),
            project_root=str(self.project_root),
        )
        self._write_status("running")

    def _append(self, message: str, **fields: Any) -> None:
        parts = [f"[{_now_iso()}]", message]
        if fields:
            parts.extend(f"{k}={v}" for k, v in fields.items())
        line = " | ".join(parts) + "\n"
        with self.run_log.open("a", encoding="utf-8") as f:
            f.write(line)
        with self.latest_log.open("a", encoding="utf-8") as f:
            f.write(line)

    def _write_status(self, status: str, **extra: Any) -> None:
        payload: Dict[str, Any] = {
            "run_id": self.run_id,
            "project": self.project_name,
            "notebook": self.notebook_name,
            "status": status,
            "started_at": self.started_at,
            "updated_at": _now_iso(),
            "project_root": str(self.project_root),
            "run_log": str(self.run_log),
            "latest_error": str(self.latest_error),
            "last_cell": self.current_cell,
            "cell_counter": self.cell_counter,
        }
        payload.update(extra)
        self.latest_json.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2, default=str),
            encoding="utf-8",
        )

    def stage(self, name: str, **fields: Any) -> None:
        self._append("STAGE", name=name, **fields)
        if not self._completed:
            self._write_status("running", stage=name, **fields)

    def _pre_run_cell(self, info) -> None:
        # A manually executed cell after a completed run starts a new active state.
        if self._completed:
            self._completed = False
        self.cell_counter += 1
        raw = (getattr(info, "raw_cell", "") or "").strip()
        first_line = raw.splitlines()[0][:140] if raw else "<empty>"
        self.current_cell = {
            "sequence": self.cell_counter,
            "first_line": first_line,
        }
        self._append("CELL START", sequence=self.cell_counter, first_line=first_line)
        self._write_status("running")

    def _post_run_cell(self, result) -> None:
        err = getattr(result, "error_before_exec", None) or getattr(result, "error_in_exec", None)
        execution_count = getattr(result, "execution_count", None)

        if err is not None:
            self._completed = False
            tb = "".join(traceback.format_exception(type(err), err, err.__traceback__))
            header = (
                f"RUN_ID: {self.run_id}\n"
                f"PROJECT: {self.project_name}\n"
                f"NOTEBOOK: {self.notebook_name}\n"
                f"TIME: {_now_iso()}\n"
                f"EXECUTION_COUNT: {execution_count}\n\n"
            )
            self.latest_error.write_text(header + tb, encoding="utf-8")
            self._append(
                "CELL ERROR",
                sequence=self.cell_counter,
                execution_count=execution_count,
                error_type=type(err).__name__,
                error=str(err).replace("\n", " ")[:500],
            )
            self._write_status(
                "error",
                execution_count=execution_count,
                error_type=type(err).__name__,
                error=str(err),
            )
        else:
            self._append(
                "CELL OK",
                sequence=self.cell_counter,
                execution_count=execution_count,
            )
            if not self._completed:
                self._write_status("running", execution_count=execution_count)

    def register_ipython(self) -> None:
        try:
            ip = get_ipython()  # type: ignore[name-defined]
        except Exception:
            ip = None
        if ip is None:
            self._append("LOGGER NOTICE", message="Not running inside IPython/Jupyter")
            return

        old = ip.user_ns.get("_PERSISTENT_RUN_LOGGER")
        if old is not None and old is not self:
            try:
                old.unregister_ipython()
            except Exception:
                pass

        ip.events.register("pre_run_cell", self._pre_run_cell)
        ip.events.register("post_run_cell", self._post_run_cell)
        ip.user_ns["_PERSISTENT_RUN_LOGGER"] = self
        self._ip = ip
        self._registered = True
        self._append("LOGGER READY", mode="jupyter_cell_events")

    def unregister_ipython(self) -> None:
        if self._ip is not None and self._registered:
            for event, func in [
                ("pre_run_cell", self._pre_run_cell),
                ("post_run_cell", self._post_run_cell),
            ]:
                try:
                    self._ip.events.unregister(event, func)
                except Exception:
                    pass
        self._registered = False

    def mark_complete(self, **fields: Any) -> None:
        self._completed = True
        self.latest_error.write_text("", encoding="utf-8")
        self._append("RUN COMPLETE", **fields)
        self._write_status("success", completed_at=_now_iso(), **fields)


def setup_notebook_logging(
    project_root: Path,
    notebook_name: str,
    project_name: Optional[str] = None,
) -> PersistentNotebookRunLogger:
    logger = PersistentNotebookRunLogger(
        project_root=project_root,
        notebook_name=notebook_name,
        project_name=project_name,
    )
    logger.register_ipython()
    return logger
