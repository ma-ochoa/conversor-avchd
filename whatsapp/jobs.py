"""Trabajos en segundo plano: copiar los medios y traerse la base de datos.

Mismo patrón que el resto de la app (hilo + diccionario en memoria + sondeo desde el
navegador), pero sin depender de nada de fuera del paquete.
"""

import threading
import uuid
from datetime import datetime
from pathlib import Path

from . import backup, dispositivo, history
from .config import load_config
from .media import import_key

_jobs: dict[str, dict] = {}
_lock = threading.Lock()


def get_job(job_id: str) -> dict | None:
    with _lock:
        job = _jobs.get(job_id)
        return dict(job) if job else None


def _nuevo(tipo: str, **campos) -> tuple[str, dict]:
    job_id = uuid.uuid4().hex
    job = {"id": job_id, "kind": tipo, "state": "en_curso", "error": None,
           "started_at": history.marca_tiempo(), **campos}
    with _lock:
        _jobs[job_id] = job
    return job_id, job


# ------------------------------------------------------------------ copia de los medios

def start_media(items: list[dict], source: str) -> str:
    job_id, job = _nuevo(
        "media", source=source, done=0, total=len(items), bytes_done=0,
        bytes_total=sum(i.get("size") or 0 for i in items), current=None, errors=[],
    )
    threading.Thread(target=_run_media, args=(job, items), daemon=True).start()
    return job_id


def _trae(item: dict, dest: Path) -> None:
    """Un archivo a su destino final, venga del móvil o de una carpeta en disco."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    if item.get("mtp_folder"):
        dispositivo.descarga(item["mtp_folder"], item["name"], dest, item.get("size"))
    else:
        import shutil
        shutil.copy2(item["path"], dest)

    # WhatsApp borra el EXIF, así que la fecha del fichero es el único dato de tiempo que
    # sobrevive. Se pone la del mensaje, no la de ahora.
    if item.get("moment"):
        try:
            import os
            t = datetime.fromisoformat(item["moment"]).timestamp()
            os.utime(dest, (t, t))
        except (ValueError, OSError):
            pass


def copia_items(items: list[dict], progreso=None, errores: list | None = None) -> dict:
    """Copia una lista de medios y los apunta en el registro. Compartida por el trabajo
    de solo-medios y por la sincronización completa, para que no haya dos versiones.

    Se apunta **por lotes**: reescribir el registro entero 40.000 veces sería el cuello de
    botella, pero volcarlo solo al final haría que un corte perdiera todo el trabajo.
    """
    errores = errores if errores is not None else []
    lote: dict[str, dict] = {}
    hechos = bytes_ = 0

    for item in items:
        if progreso:
            progreso(hechos, bytes_, item["dest_relative"])
        try:
            _trae(item, Path(item["dest"]))
        except Exception as exc:
            errores.append(f"{item['name']}: {exc}")
            continue

        lote[import_key(item)] = {
            "name": item["name"], "size": item.get("size") or 0,
            "dest": item["dest"], "dest_relative": item["dest_relative"],
            "kind": item.get("kind"), "sent": bool(item.get("sent")),
            "moment": item.get("moment"), "copied_at": history.marca_tiempo(),
        }
        hechos += 1
        bytes_ += item.get("size") or 0
        if len(lote) >= 200:
            history.registra(lote)
            lote = {}

    history.registra(lote)
    if progreso:
        progreso(hechos, bytes_, None)
    return {"copiados": hechos, "bytes": bytes_, "errores": errores}


def _run_media(job: dict, items: list[dict]) -> None:
    def progreso(hechos, bytes_, actual):
        job["done"], job["bytes_done"], job["current"] = hechos, bytes_, actual

    copia_items(items, progreso=progreso, errores=job["errors"])
    job["state"] = "finalizado" if not job["errors"] else "finalizado_con_errores"
    history.registra_run({
        "source": job["source"], "destination": load_config()["destination"],
        "finished_at": history.marca_tiempo(), "copied": job["done"],
        "errors": len(job["errors"]), "bytes": job["bytes_done"],
    })


# ------------------------------------------------- descarga de la copia de seguridad

def start_backup(copia: dict) -> str:
    """La descarga va en segundo plano porque son ~150 MB por USB."""
    job_id, job = _nuevo("backup", name=copia["name"], done=0,
                         total=copia.get("size") or 0, path=None)
    threading.Thread(target=_run_backup, args=(job, copia), daemon=True).start()
    return job_id


def _run_backup(job: dict, copia: dict) -> None:
    try:
        def progreso(hechos, total):
            job["done"] = hechos
            if total:
                job["total"] = total

        destino = backup.descarga_copia(copia, progress_cb=progreso)
        # Se deja siempre con el nombre que espera el resto del paquete, para que una
        # copia con fecha en el nombre no obligue a elegirla otra vez más adelante.
        from .config import CIFRADA
        if destino != CIFRADA:
            destino.replace(CIFRADA)
            destino = CIFRADA
        job["path"] = str(destino)
        job["done"] = job["total"] = destino.stat().st_size
        job["state"] = "finalizado"
    except Exception as exc:
        job["state"] = "error"
        job["error"] = str(exc)
