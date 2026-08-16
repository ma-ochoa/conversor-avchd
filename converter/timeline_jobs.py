"""Orquesta la exportación final de un montaje en segundo plano, con progreso."""

import threading
import uuid
from datetime import datetime
from pathlib import Path

from .project import exports_dir, sanitize_project_name
from .timeline_export import export_timeline

_jobs: dict[str, dict] = {}
_jobs_lock = threading.Lock()


def start_export(root: str, project_name: str, clips: list, transition_seconds: float) -> str:
    root_path = Path(root).expanduser().resolve()
    job_id = uuid.uuid4().hex

    dest = exports_dir(root_path) / f"{sanitize_project_name(project_name)}_final.mp4"

    job = {
        "id": job_id,
        "dest": str(dest),
        "percent": 0.0,
        "status": "procesando",
        "error": None,
        "started_at": datetime.now().isoformat(timespec="seconds"),
    }
    with _jobs_lock:
        _jobs[job_id] = job

    thread = threading.Thread(
        target=_run_export, args=(job_id, clips, transition_seconds, dest, root_path), daemon=True
    )
    thread.start()
    return job_id


def get_export_job(job_id: str) -> dict | None:
    with _jobs_lock:
        job = _jobs.get(job_id)
        return dict(job) if job else None


def _run_export(job_id: str, clips: list, transition_seconds: float, dest: Path, root_path: Path) -> None:
    job = _jobs[job_id]

    def progress_cb(fraction):
        job["percent"] = fraction

    try:
        export_timeline(clips, transition_seconds, dest, root=root_path, progress_cb=progress_cb)
        job["status"] = "completado"
        job["percent"] = 1.0
    except Exception as exc:
        job["status"] = "error"
        job["error"] = str(exc)
