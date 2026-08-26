"""Job de importación en segundo plano: copiar, verificar, registrar, borrar y subir.

Sigue el mismo patrón que el resto de módulos de la app (hilo + diccionario en memoria
+ polling desde el navegador), pero encadena las cuatro fases en un solo trabajo para
que el usuario siga un único progreso de principio a fin.
"""

import threading
import uuid
from datetime import datetime
from pathlib import Path

from . import geoindex, history, mtp
from .config import load_config, remember_camera
from .exif import read_metadata
from .mtp_scan import is_mtp_source
from .copier import copy_verified, set_file_time
from .media import import_key

_jobs: dict[str, dict] = {}
_jobs_lock = threading.Lock()


def start_job(source: str, items: list[dict], options: dict, camera_folders: dict) -> str:
    job_id = uuid.uuid4().hex

    job = {
        "id": job_id,
        "source": source,
        "destination": options.get("destination", ""),
        "phase": "copiando",
        "state": "en_curso",
        "items": [
            {
                "path": item["path"],
                "relative": item["relative"],
                "dest_relative": item["dest_relative"],
                "dest": item["dest"],
                "size": item["size"],
                "category": item["category"],
                "capture_dt": item["capture_dt"],
                "name": item["name"],
                "gps": item.get("gps"),
                # Solo para orígenes MTP: la carpeta del móvil de la que sacar el fichero,
                # ya que su "path" no es una ruta de disco que se pueda abrir.
                "mtp_folder": item.get("mtp_folder"),
                "status": "pendiente",
                "percent": 0.0,
                "verified": False,
                "error": None,
            }
            for item in items
        ],
        "deleted": 0,
        "delete_errors": [],
        "upload": {
            "enabled": bool(options.get("upload_to_nas")),
            "state": "pendiente",
            "done": 0,
            "total": 0,
            "error": None,
            "current": None,
        },
        "summary": None,
        "started_at": datetime.now().isoformat(timespec="seconds"),
    }
    with _jobs_lock:
        _jobs[job_id] = job

    threading.Thread(
        target=_run_job, args=(job_id, options, camera_folders), daemon=True
    ).start()
    return job_id


def get_job(job_id: str) -> dict | None:
    with _jobs_lock:
        job = _jobs.get(job_id)
        return dict(job) if job else None


def _copy_all(job: dict, verify: bool, destination: Path) -> None:
    geo_entries: dict[str, dict] = {}

    for item in job["items"]:
        dest = Path(item["dest"])
        item["status"] = "copiando"
        try:
            if is_mtp_source(item["path"]):
                # El móvil no es una ruta de disco: se descarga directamente a su destino
                # final, sin pasar por ninguna copia intermedia. No hay checksum del lado
                # del móvil, así que la verificación es por tamaño exacto.
                mtp.fetch(item["mtp_folder"], item["name"], dest, item["size"])
                result = {"sha256": "", "verified": False}
                item["percent"] = 1.0
            else:
                def progress_cb(fraction, item=item, verify=verify):
                    item["percent"] = fraction
                    if verify and fraction >= 0.5 and item["status"] == "copiando":
                        item["status"] = "verificando"

                result = copy_verified(Path(item["path"]), dest, verify=verify,
                                       progress_cb=progress_cb)
            set_file_time(dest, datetime.fromisoformat(item["capture_dt"]).timestamp())

            item["status"] = "completado"
            item["verified"] = result["verified"]
            item["percent"] = 1.0

            history.record_import(
                import_key(item["name"], item["size"], item["capture_dt"]),
                {
                    "source_name": item["name"],
                    "size": item["size"],
                    "capture_dt": item["capture_dt"],
                    "dest": item["dest"],
                    "dest_relative": item["dest_relative"],
                    "sha256": result["sha256"],
                    "verified": result["verified"],
                    "imported_at": datetime.now().isoformat(timespec="seconds"),
                    "uploaded_at": None,
                },
            )
            if item["category"] != "sidecar":
                geo_entries[item["dest_relative"]] = geoindex.entry(
                    item["capture_dt"], item.get("gps"), geoindex.SOURCE_EXIF
                )
        except Exception as exc:
            item["status"] = "error"
            item["error"] = str(exc)

    # Del móvil no se conoce el GPS por adelantado —vive dentro del archivo, y leerlo
    # habría exigido descargarlo antes—, así que se lee ahora, de lo ya copiado, en un
    # solo exiftool por lote.
    _fill_missing_gps(job, geo_entries)

    # Se escribe una sola vez al final: un JSON por fichero copiado sería miles de
    # reescrituras del índice completo durante la importación de una tarjeta.
    geoindex.record_many(destination, geo_entries)


def _fill_missing_gps(job: dict, geo_entries: dict[str, dict]) -> None:
    pending = [
        item for item in job["items"]
        if item["status"] == "completado" and item.get("gps") is None
        and is_mtp_source(item["path"]) and item["category"] != "sidecar"
    ]
    if not pending:
        return

    metadata = read_metadata([Path(item["dest"]) for item in pending])
    for item in pending:
        meta = metadata.get(item["dest"])
        if meta and meta.get("gps"):
            entry = geo_entries.get(item["dest_relative"])
            if entry:
                entry["gps"] = list(meta["gps"])
                entry["source"] = geoindex.SOURCE_EXIF


def _delete_sources(job: dict, verify: bool) -> None:
    """Borra en el origen solo lo que se copió Y verificó. Si la verificación estaba
    desactivada no se borra nada: sería destruir el único ejemplar sin comprobarlo."""
    job["phase"] = "borrando"
    if not verify:
        job["delete_errors"].append(
            "No se ha borrado nada: el borrado del origen exige la verificación por checksum."
        )
        return

    if any(is_mtp_source(item["path"]) for item in job["items"]):
        job["delete_errors"].append(
            "No se borra nada del móvil: la verificación por checksum no es posible sobre "
            "MTP (solo se comprueba el tamaño), y borrar el único ejemplar sin poder "
            "comprobarlo del todo sería temerario. Bórralas desde el móvil si quieres."
        )
        return

    for item in job["items"]:
        if item["status"] != "completado" or not item["verified"]:
            continue
        try:
            Path(item["path"]).unlink()
            item["status"] = "completado (origen borrado)"
            job["deleted"] += 1
        except OSError as exc:
            job["delete_errors"].append(f"{item['relative']}: {exc}")


def _upload(job: dict) -> None:
    from .nas import upload_files

    job["phase"] = "subiendo"
    uploaded = [i for i in job["items"] if i["status"].startswith("completado")]
    job["upload"]["total"] = len(uploaded)
    if not uploaded:
        job["upload"]["state"] = "sin_archivos"
        return

    job["upload"]["state"] = "en_curso"
    # Lo subido se apunta según llega, no todo al final: si esto se corta en el archivo
    # 250 de 257, los 249 anteriores ya cuentan como subidos y no se repiten.
    tracker = history.UploadTracker(uploaded)
    try:
        def progress_cb(done, current):
            job["upload"]["done"] = done
            job["upload"]["current"] = current
            tracker.note(current)

        upload_files(
            [(Path(i["dest"]), i["dest_relative"]) for i in uploaded],
            load_config()["nas"],
            progress_cb=progress_cb,
        )
        job["upload"]["state"] = "completado"
    except Exception as exc:
        job["upload"]["state"] = "error"
        job["upload"]["error"] = str(exc)
    finally:
        tracker.flush()


def _run_job(job_id: str, options: dict, camera_folders: dict) -> None:
    job = _jobs[job_id]
    verify = bool(options.get("verify_checksum", True))

    for model, folder in camera_folders.items():
        if model:
            remember_camera(model, folder)

    _copy_all(job, verify, Path(options.get("destination", ".")))

    errors = [i for i in job["items"] if i["status"] == "error"]
    if options.get("delete_after_import") and not errors:
        _delete_sources(job, verify)
    elif options.get("delete_after_import") and errors:
        job["delete_errors"].append(
            f"No se ha borrado nada del origen: {len(errors)} archivo(s) fallaron al copiarse."
        )

    if job["upload"]["enabled"]:
        _upload(job)

    copied = sum(1 for i in job["items"] if i["status"].startswith("completado"))
    job["summary"] = {
        "copied": copied,
        "errors": len(errors),
        "deleted": job["deleted"],
        "bytes": sum(i["size"] for i in job["items"] if i["status"].startswith("completado")),
    }
    job["phase"] = "terminado"
    job["state"] = "finalizado"

    history.record_run({
        "source": job["source"],
        "destination": job["destination"],
        "finished_at": datetime.now().isoformat(timespec="seconds"),
        **job["summary"],
        "upload_state": job["upload"]["state"] if job["upload"]["enabled"] else None,
    })
