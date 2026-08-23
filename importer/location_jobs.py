"""Job de asignación de ubicación en segundo plano.

Escribir el EXIF de varios cientos de ficheros tarda, así que sigue el mismo patrón de
hilo + polling que el resto de módulos.
"""

import threading
import uuid
from datetime import datetime
from pathlib import Path

from . import geoindex
from .geowrite import GeoWriteError, verify_gps, write_gps

_jobs: dict[str, dict] = {}
_jobs_lock = threading.Lock()


def start_assign(root: str, relatives: list[str], gps: list[float], source: str,
                 place: str = "", make_backup: bool = True) -> str:
    job_id = uuid.uuid4().hex
    job = {
        "id": job_id,
        "root": root,
        "gps": gps,
        "place": place,
        "source": source,
        "state": "en_curso",
        "done": 0,
        "total": len(relatives),
        "written": 0,
        "errors": [],
        "current": None,
        "started_at": datetime.now().isoformat(timespec="seconds"),
    }
    with _jobs_lock:
        _jobs[job_id] = job

    threading.Thread(
        target=_run, args=(job_id, Path(root), relatives, gps, source, place, make_backup),
        daemon=True,
    ).start()
    return job_id


def get_assign_job(job_id: str) -> dict | None:
    with _jobs_lock:
        job = _jobs.get(job_id)
        return dict(job) if job else None


def start_reindex(root: str, full: bool = False) -> str:
    job_id = uuid.uuid4().hex
    job = {
        "id": job_id, "root": root, "kind": "reindex", "state": "en_curso",
        "done": 0, "total": 0, "added": 0, "errors": [], "current": None,
        "started_at": datetime.now().isoformat(timespec="seconds"),
    }
    with _jobs_lock:
        _jobs[job_id] = job

    threading.Thread(target=_run_reindex, args=(job_id, Path(root), full), daemon=True).start()
    return job_id


def _run_reindex(job_id: str, root: Path, full: bool) -> None:
    job = _jobs[job_id]
    try:
        def progress_cb(done, total):
            job["done"], job["total"] = done, total

        result = geoindex.rebuild(root, only_missing=not full, progress_cb=progress_cb)
        job["added"] = result["added"]
        job["state"] = "finalizado"
    except Exception as exc:
        job["errors"].append(str(exc))
        job["state"] = "error"


def _run(job_id: str, root: Path, relatives: list[str], gps: list[float],
         source: str, place: str, make_backup: bool) -> None:
    job = _jobs[job_id]
    lat, lon = gps
    written: list[str] = []

    for relative in relatives:
        job["current"] = relative
        target = root / relative
        try:
            write_gps(target, lat, lon, make_backup=make_backup)
            # Se comprueba releyendo el archivo: si exiftool devolvió 0 pero el formato
            # no admitía el campo, la posición no estaría dentro y el índice mentiría.
            if verify_gps(target) is None:
                raise GeoWriteError("La posición no se pudo leer de vuelta tras escribirla.")
            written.append(relative)
            job["written"] += 1
        except Exception as exc:
            job["errors"].append(f"{relative}: {exc}")
        job["done"] += 1

    # El índice solo registra lo que de verdad quedó escrito en el archivo.
    if written:
        geoindex.set_location(root, written, gps, source, place)

    job["current"] = None
    job["state"] = "finalizado"
