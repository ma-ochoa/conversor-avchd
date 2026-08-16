"""Orquesta los trabajos de estabilización avanzada en segundo plano.

Mismo patrón que stabilize_jobs/recompress_jobs: se lanza un hilo, se devuelve un
job_id y la página va sondeando el estado. Cada proceso decide su propio destino
dentro de `avanzada/` (respetando la carpeta de trabajo global de Ajustes), así que
no hace falta manifiesto ni carpeta de salida única para todo el trabajo."""

import os
import threading
import uuid
from datetime import datetime
from pathlib import Path

from .avanzada import (
    advanced_output_dir,
    auditar,
    check_deps,
    estabilizar_bloqueo,
    extraer_fotogramas,
    hoja_contacto,
    probe_video,
    radio_px,
    seguir_objeto,
)
from .metadata import get_capture_datetime

_jobs: dict[str, dict] = {}
_jobs_lock = threading.Lock()

PROCESOS = ("extraccion", "bloqueo", "seguimiento", "hoja", "auditoria")


def start_job(root: str, proceso: str, paths: list[str], params: dict) -> str:
    root_path = Path(root).expanduser().resolve()
    job_id = uuid.uuid4().hex

    items = []
    for p in paths:
        pp = Path(p)
        try:
            relative = str(pp.relative_to(root_path))
        except ValueError:
            relative = pp.name
        items.append({
            "path": str(pp),
            "relative": relative,
            "status": "pendiente",
            "percent": 0.0,
            "phase": "",
            "output_name": None,
            "stats": None,
            "error": None,
        })

    job = {
        "id": job_id,
        "root": str(root_path),
        "proceso": proceso,
        "items": items,
        "state": "en_curso",
        "started_at": datetime.now().isoformat(timespec="seconds"),
    }
    with _jobs_lock:
        _jobs[job_id] = job

    thread = threading.Thread(target=_run_job, args=(job_id, root_path, proceso, params),
                              daemon=True)
    thread.start()
    return job_id


def get_job(job_id: str) -> dict | None:
    with _jobs_lock:
        job = _jobs.get(job_id)
        return dict(job) if job else None


def _resolver_radio(source: Path, params: dict) -> float:
    """El radio se puede dar directamente en píxeles o deducir de la óptica."""
    if params.get("radio_modo") == "manual":
        return float(params.get("radio_px") or 0) or 1.0
    info = probe_video(source)
    return radio_px(
        float(params.get("focal_mm") or 240),
        float(params.get("sensor_mm") or 23.5),
        info["width"],
        params.get("objeto") or "sol",
    )


def _run_job(job_id: str, root_path: Path, proceso: str, params: dict) -> None:
    job = _jobs[job_id]

    try:
        check_deps()
    except Exception as exc:
        for item in job["items"]:
            item["status"] = "error"
            item["error"] = str(exc)
        job["state"] = "finalizado"
        return

    for item in job["items"]:
        source = Path(item["path"])
        try:
            source.stat()
        except OSError as exc:
            item["status"] = "error"
            item["error"] = str(exc)
            continue

        item["status"] = "procesando"

        def progress_cb(fraction, phase="", item=item):
            item["percent"] = max(0.0, min(1.0, float(fraction)))
            if phase:
                item["phase"] = phase

        try:
            destino_dir = advanced_output_dir(root_path, proceso)
            deint = bool(params.get("deinterlace", False))
            formato = params.get("formato", "prores")
            ext = ".mov" if formato == "prores" else ".mp4"

            if proceso == "extraccion":
                salida = params.get("salida", "png")
                sub = destino_dir / f"{source.stem}_{int(params.get('ratio', 1))}a1"
                stats = extraer_fotogramas(
                    source, sub,
                    ratio=int(params.get("ratio", 1)),
                    descartar_negros=bool(params.get("descartar_negros", True)),
                    descartar_movidos=bool(params.get("descartar_movidos", True)),
                    salida=salida, deinterlace=deint, progress_cb=progress_cb)
                item["output_name"] = Path(stats["destino"]).name

            elif proceso == "bloqueo":
                dest = destino_dir / f"{source.stem}_bloqueado{ext}"
                stats = estabilizar_bloqueo(
                    source, dest,
                    modo=params.get("modo", "bloqueo"),
                    suavizado_seg=float(params.get("suavizado_seg", 1.0)),
                    anclas_seg=float(params.get("anclas_seg", 5.0)),
                    calidad_min=float(params.get("calidad_min", 30.0)),
                    recorte_extra=float(params.get("recorte_extra", 0.0)),
                    deinterlace=deint, formato=formato, progress_cb=progress_cb)
                item["output_name"] = dest.name

            elif proceso == "seguimiento":
                radio = _resolver_radio(source, params)
                lado = params.get("lado")
                dest = destino_dir / f"{source.stem}_centrado{ext}"
                stats = seguir_objeto(
                    source, dest, radio,
                    lado=int(lado) if lado else None,
                    formato=formato, deinterlace=deint, progress_cb=progress_cb)
                item["output_name"] = dest.name

            elif proceso == "hoja":
                dest = destino_dir / f"{source.stem}_contacto.jpg"
                stats = hoja_contacto(
                    source, dest,
                    columnas=int(params.get("columnas", 10)),
                    celda=int(params.get("celda", 240)),
                    reticula=bool(params.get("reticula", True)))
                item["percent"] = 1.0
                item["output_name"] = dest.name

            elif proceso == "auditoria":
                radio = _resolver_radio(source, params) if params.get("medir_objeto") else None
                stats = auditar(source, radio, progress_cb=lambda f: progress_cb(f, "midiendo"))
                item["output_name"] = "—"

            else:
                raise ValueError(f"Proceso desconocido: {proceso}")

            # Fecha de captura del original, para que la salida no pierda el orden
            salida_path = destino_dir / (item["output_name"] or "")
            if salida_path.exists() and salida_path.is_file():
                capture_dt, _ = get_capture_datetime(source, is_video=True)
                if capture_dt:
                    ts = capture_dt.timestamp()
                    os.utime(salida_path, (ts, ts))

            item["percent"] = 1.0
            item["phase"] = ""
            item["status"] = "completado"
            item["stats"] = stats
        except Exception as exc:
            item["status"] = "error"
            item["error"] = str(exc)

    job["state"] = "finalizado"
