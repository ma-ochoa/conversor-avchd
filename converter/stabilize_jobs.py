"""Orquesta un trabajo de estabilización en segundo plano, independiente del remuxeo.

El vídeo estabilizado se guarda junto al original como "<nombre>_stabilized.mp4" (o
en la misma ruta relativa dentro de la carpeta de trabajo, si hay una configurada —
ver stabilize.py::stabilized_output_path). Cada clip decide su propio destino, así que
ya no hace falta un manifiesto ni una carpeta de salida única para todo el trabajo."""

import os
import threading
import uuid
from datetime import datetime
from pathlib import Path

from .metadata import get_capture_datetime
from .stabilize import DEFAULT_PARAMS, load_stabilize_draft, stabilize_clip, stabilized_output_path

_jobs: dict[str, dict] = {}
_jobs_lock = threading.Lock()


def start_job(root: str, avchd_paths: list[str], force: bool, fast_hw: bool = False,
              params: dict | None = None) -> str:
    root_path = Path(root).expanduser().resolve()
    job_id = uuid.uuid4().hex
    stab_params = {**DEFAULT_PARAMS, **(params or {})}

    items = [
        {
            "path": str(Path(p)),
            "relative": str(Path(p).relative_to(root_path)),
            "type": "avchd",
            "status": "pendiente",
            "percent": 0.0,
            "output_name": None,
            "stats": None,
            "error": None,
        }
        for p in avchd_paths
    ]

    job = {
        "id": job_id,
        "root": str(root_path),
        "items": items,
        "state": "en_curso",
        "started_at": datetime.now().isoformat(timespec="seconds"),
    }
    with _jobs_lock:
        _jobs[job_id] = job

    thread = threading.Thread(
        target=_run_job, args=(job_id, root_path, force, fast_hw, stab_params), daemon=True
    )
    thread.start()
    return job_id


def get_job(job_id: str) -> dict | None:
    with _jobs_lock:
        job = _jobs.get(job_id)
        return dict(job) if job else None


def _run_job(job_id: str, root_path: Path, force: bool, fast_hw: bool, stab_params: dict) -> None:
    job = _jobs[job_id]
    for item in job["items"]:
        source = Path(item["path"])
        try:
            source.stat()
        except OSError as exc:
            item["status"] = "error"
            item["error"] = str(exc)
            continue

        dest = stabilized_output_path(root_path, source)
        if not force and dest.exists():
            item["status"] = "omitido (ya estabilizado)"
            item["output_name"] = dest.name
            item["percent"] = 1.0
            continue

        item["status"] = "procesando"
        capture_dt, _ = get_capture_datetime(source, is_video=True)

        try:
            def progress_cb(fraction, item=item):
                item["percent"] = fraction

            draft = load_stabilize_draft(root_path, source)
            effective_params = {**stab_params, **draft} if draft else stab_params
            stats = stabilize_clip(
                source, dest, root_path, progress_cb=progress_cb, fast_hw=fast_hw, **effective_params
            )

            timestamp = capture_dt.timestamp()
            os.utime(dest, (timestamp, timestamp))

            item["status"] = "completado"
            item["output_name"] = dest.name
            item["stats"] = stats
        except Exception as exc:
            item["status"] = "error"
            item["error"] = str(exc)

    job["state"] = "finalizado"
