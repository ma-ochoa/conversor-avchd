"""Job de subida al NAS independiente de la importación.

Existe para reintentar lo que quedó pendiente cuando la red se cortó a mitad de una
subida, sin tener que volver a importar la tarjeta.
"""

import threading
import uuid
from datetime import datetime
from pathlib import Path

from . import history
from .config import load_config
from .nas import NasOtpRequired, upload_files

_jobs: dict[str, dict] = {}
_jobs_lock = threading.Lock()


def start_upload(entries: list[dict]) -> str:
    job_id = uuid.uuid4().hex
    job = {
        "id": job_id,
        "state": "en_curso",
        "done": 0,
        "total": len(entries),
        "current": None,
        "error": None,
        "started_at": datetime.now().isoformat(timespec="seconds"),
    }
    with _jobs_lock:
        _jobs[job_id] = job

    threading.Thread(target=_run, args=(job_id, entries), daemon=True).start()
    return job_id


def get_upload_job(job_id: str) -> dict | None:
    with _jobs_lock:
        job = _jobs.get(job_id)
        return dict(job) if job else None


def _run(job_id: str, entries: list[dict]) -> None:
    job = _jobs[job_id]
    try:
        def progress_cb(done, current):
            job["done"] = done
            job["current"] = current

        upload_files(
            [(Path(e["dest"]), e["dest_relative"]) for e in entries],
            load_config()["nas"],
            progress_cb=progress_cb,
        )
        history.mark_uploaded([e["dest"] for e in entries])
        job["state"] = "finalizado"
    except NasOtpRequired:
        # Una subida corre en segundo plano, sin nadie mirando: no se puede pedir aquí un
        # código que caduca en 30 s. Se explica qué hacer y los ficheros quedan pendientes.
        job["state"] = "error"
        job["error"] = (
            "El NAS pide el código de verificación en dos pasos. Ve a «Configurar conexión» "
            "y pulsa «Probar conexión» introduciendo el código: este equipo quedará "
            "autorizado y no volverá a pedírtelo. Después reintenta la subida."
        )
    except Exception as exc:
        job["state"] = "error"
        job["error"] = str(exc)
