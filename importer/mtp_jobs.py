"""Job de descarga desde el móvil.

Descarga lo seleccionado a una carpeta de trabajo en disco; a partir de ahí el flujo es
exactamente el mismo que con una tarjeta (escanear → planificar → importar), así que el
móvil hereda sin cambios el renombrado por fecha, la separación JPG/RAW, la agrupación por
cámara y día, el nombre de evento y el envío al NAS.

Se descarga a una carpeta intermedia en vez de directamente al destino final para poder
enseñar el plan antes de tocar la biblioteca, igual que con las tarjetas.
"""

import shutil
import threading
import uuid
from datetime import datetime
from pathlib import Path

from . import mtp
from .config import CONFIG_DIR
from .history import imported_keys
from .media import import_key

DOWNLOAD_DIR = CONFIG_DIR / "descargas-movil"

_jobs: dict[str, dict] = {}
_jobs_lock = threading.Lock()


def download_key(entry: dict) -> str:
    """Misma identidad que usa el importador para las tarjetas, para que un fichero ya
    importado desde el móvil no se vuelva a descargar."""
    return import_key(entry["name"], entry.get("size") or 0, entry.get("captured") or "")


def start_download(folder: str, entries: list[dict], skip_duplicates: bool = True) -> str:
    job_id = uuid.uuid4().hex
    known = imported_keys() if skip_duplicates else set()

    pending = [e for e in entries if not (skip_duplicates and download_key(e) in known)]

    job = {
        "id": job_id,
        "folder": folder,
        "state": "en_curso",
        "done": 0,
        "total": len(pending),
        "skipped": len(entries) - len(pending),
        "bytes_total": sum(e.get("size") or 0 for e in pending),
        "saved": 0,
        "current": None,
        "destination": None,
        "error": None,
        "started_at": datetime.now().isoformat(timespec="seconds"),
    }
    with _jobs_lock:
        _jobs[job_id] = job

    threading.Thread(target=_run, args=(job_id, folder, pending), daemon=True).start()
    return job_id


def get_job(job_id: str) -> dict | None:
    with _jobs_lock:
        job = _jobs.get(job_id)
        return dict(job) if job else None


def _run(job_id: str, folder: str, entries: list[dict]) -> None:
    job = _jobs[job_id]
    # Una carpeta por descarga, con el nombre de la del móvil, para que se distinga de
    # qué venía cada tanda si quedan varias sin importar.
    label = folder.rstrip("/").rsplit("/", 1)[-1] or "movil"
    destination = DOWNLOAD_DIR / f"{label} {datetime.now():%Y-%m-%d %H%M%S}"

    try:
        if not entries:
            job["destination"] = str(destination)
            job["state"] = "finalizado"
            return

        def progress_cb(done, total, name):
            job["done"] = done
            job["current"] = name

        saved = mtp.download(folder, [e["name"] for e in entries], destination,
                             progress_cb=progress_cb)
        job["saved"] = len(saved)
        job["destination"] = str(destination)
        job["state"] = "finalizado"
    except Exception as exc:
        job["state"] = "error"
        job["error"] = str(exc)
    finally:
        # La sesión con el móvil se cierra al terminar: mantenerla abierta impide que
        # Fotos o Captura de Imagen vuelvan a hablar con el dispositivo.
        mtp.close()


def cleanup(path: str) -> bool:
    """Borra una carpeta de descarga ya importada. Solo dentro de DOWNLOAD_DIR."""
    target = Path(path).expanduser().resolve()
    try:
        # Nunca borrar fuera de la carpeta de descargas, pase lo que pase por parámetro.
        target.relative_to(DOWNLOAD_DIR.resolve())
    except ValueError:
        return False
    if not target.is_dir():
        return False
    shutil.rmtree(target)
    return True


def pending_downloads() -> list[dict]:
    """Descargas que quedaron en disco sin importar (por ejemplo, tras cerrar la app)."""
    if not DOWNLOAD_DIR.is_dir():
        return []
    found = []
    for path in sorted(DOWNLOAD_DIR.iterdir(), reverse=True):
        if not path.is_dir():
            continue
        files = [f for f in path.rglob("*") if f.is_file()]
        if files:
            found.append({
                "path": str(path),
                "name": path.name,
                "files": len(files),
                "bytes": sum(f.stat().st_size for f in files),
            })
    return found
