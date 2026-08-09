"""Orquesta en segundo plano el cálculo de la trayectoria de estabilización para la
vista previa del Montaje (análisis + volcado de movimiento, sin generar vídeo)."""

import threading
import uuid
from pathlib import Path

from .proxy import get_or_create_proxy
from .stabilize import get_preview_analysis

_jobs: dict[str, dict] = {}
_jobs_lock = threading.Lock()


def start_analysis(root: str, path: str, shakiness: int, accuracy: int) -> str:
    root_path = Path(root).expanduser().resolve()
    source = Path(path)
    job_id = uuid.uuid4().hex

    job = {"id": job_id, "status": "procesando", "percent": 0.0, "data": None, "error": None}
    with _jobs_lock:
        _jobs[job_id] = job

    thread = threading.Thread(
        target=_run_analysis, args=(job_id, root_path, source, shakiness, accuracy), daemon=True
    )
    thread.start()
    return job_id


def get_analysis_job(job_id: str) -> dict | None:
    with _jobs_lock:
        job = _jobs.get(job_id)
        return dict(job) if job else None


def _run_analysis(job_id: str, root_path: Path, source: Path, shakiness: int, accuracy: int) -> None:
    job = _jobs[job_id]

    def progress_cb(fraction):
        job["percent"] = fraction * 0.9

    try:
        proxy_path = get_or_create_proxy(root_path, source)
        data = get_preview_analysis(root_path, source, shakiness, accuracy, progress_cb=progress_cb)
        data["proxy_path"] = str(proxy_path)
        job["data"] = data
        job["status"] = "completado"
        job["percent"] = 1.0
    except Exception as exc:
        job["status"] = "error"
        job["error"] = str(exc)
