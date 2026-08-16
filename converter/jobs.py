"""Orquesta un trabajo de conversión en segundo plano y expone su progreso."""

import os
import shutil
import threading
import uuid
from datetime import datetime
from pathlib import Path

from .config import resolve_output_base
from .ffmpeg_ops import remux_clip
from .manifest import load_manifest, record_conversion
from .metadata import get_capture_datetime
from .naming import unique_name
from .scanner import OUTPUT_DIR_NAME

_jobs: dict[str, dict] = {}
_jobs_lock = threading.Lock()


def _new_item(path: str, relative: str, kind: str) -> dict:
    return {
        "path": path,
        "relative": relative,
        "type": kind,
        "status": "pendiente",
        "percent": 0.0,
        "output_name": None,
        "error": None,
    }


def start_job(root: str, avchd_paths: list[str], photo_paths: list[str],
              transcode_audio: bool, force: bool, prefix: str = "") -> str:
    root_path = Path(root).expanduser().resolve()
    job_id = uuid.uuid4().hex

    items = []
    for p in avchd_paths:
        pp = Path(p)
        items.append(_new_item(str(pp), str(pp.relative_to(root_path)), "avchd"))
    for p in photo_paths:
        pp = Path(p)
        items.append(_new_item(str(pp), str(pp.relative_to(root_path)), "photo"))

    job = {
        "id": job_id,
        "root": str(root_path),
        "output_dir": str(resolve_output_base(root_path) / OUTPUT_DIR_NAME),
        "items": items,
        "state": "en_curso",
        "started_at": datetime.now().isoformat(timespec="seconds"),
    }
    with _jobs_lock:
        _jobs[job_id] = job

    thread = threading.Thread(
        target=_run_job, args=(job_id, root_path, transcode_audio, force, prefix), daemon=True
    )
    thread.start()
    return job_id


def get_job(job_id: str) -> dict | None:
    with _jobs_lock:
        job = _jobs.get(job_id)
        return dict(job) if job else None


def _run_job(job_id: str, root_path: Path, transcode_audio: bool, force: bool, prefix: str = "") -> None:
    output_dir = resolve_output_base(root_path) / OUTPUT_DIR_NAME
    output_dir.mkdir(parents=True, exist_ok=True)

    manifest = load_manifest(root_path)
    used_names = {f.name for f in output_dir.iterdir() if f.is_file()} if output_dir.exists() else set()

    job = _jobs[job_id]
    for item in job["items"]:
        source = Path(item["path"])
        try:
            size = source.stat().st_size
        except OSError as exc:
            item["status"] = "error"
            item["error"] = str(exc)
            continue

        entry = manifest.get(str(source))
        if not force and entry and entry.get("size") == size and entry.get("output") and \
                (output_dir / entry["output"]).exists():
            item["status"] = "omitido (ya convertido)"
            item["output_name"] = entry["output"]
            item["percent"] = 1.0
            continue

        item["status"] = "procesando"
        is_video = item["type"] == "avchd"
        capture_dt, _ = get_capture_datetime(source, is_video=is_video)
        ext = ".mp4" if is_video else source.suffix.lower()
        output_name = unique_name(capture_dt, ext, used_names, prefix)
        dest = output_dir / output_name

        try:
            if is_video:
                def progress_cb(fraction, item=item):
                    item["percent"] = fraction

                remux_clip(source, dest, transcode_audio=transcode_audio,
                           capture_dt=capture_dt, progress_cb=progress_cb)
            else:
                shutil.copy2(source, dest)
                item["percent"] = 1.0

            timestamp = capture_dt.timestamp()
            os.utime(dest, (timestamp, timestamp))

            record_conversion(root_path, str(source), size, output_name)
            manifest[str(source)] = {"size": size, "output": output_name}
            item["status"] = "completado"
            item["output_name"] = output_name
        except Exception as exc:
            item["status"] = "error"
            item["error"] = str(exc)

    job["state"] = "finalizado"
