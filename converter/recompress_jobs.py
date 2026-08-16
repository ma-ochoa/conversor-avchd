"""Orquesta un trabajo de recompresión en segundo plano, independiente del resto."""

import os
import threading
import uuid
from datetime import datetime
from pathlib import Path

from .config import resolve_output_base
from .manifest import load_manifest, record_entry
from .metadata import get_capture_datetime
from .naming import unique_name
from .recompress import recompress_clip

OUTPUT_DIR_NAME = "recompresion"

_jobs: dict[str, dict] = {}
_jobs_lock = threading.Lock()


def start_job(root: str, paths: list[str], quality: str, max_width: str, force: bool) -> str:
    root_path = Path(root).expanduser().resolve()
    job_id = uuid.uuid4().hex

    items = [
        {
            "path": str(Path(p)),
            "relative": str(Path(p).relative_to(root_path)) if Path(p).is_relative_to(root_path) else Path(p).name,
            "status": "pendiente",
            "percent": 0.0,
            "output_name": None,
            "stats": None,
            "error": None,
        }
        for p in paths
    ]

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
        target=_run_job, args=(job_id, root_path, quality, max_width, force), daemon=True
    )
    thread.start()
    return job_id


def get_job(job_id: str) -> dict | None:
    with _jobs_lock:
        job = _jobs.get(job_id)
        return dict(job) if job else None


def _run_job(job_id: str, root_path: Path, quality: str, max_width: str, force: bool) -> None:
    output_dir = resolve_output_base(root_path) / OUTPUT_DIR_NAME
    output_dir.mkdir(parents=True, exist_ok=True)

    manifest = load_manifest(root_path, OUTPUT_DIR_NAME)
    used_names = {f.name for f in output_dir.iterdir() if f.is_file()}

    job = _jobs[job_id]
    for item in job["items"]:
        source = Path(item["path"])
        try:
            size = source.stat().st_size
        except OSError as exc:
            item["status"] = "error"
            item["error"] = str(exc)
            continue

        cache_key = f"{source}|{quality}|{max_width}"
        entry = manifest.get(cache_key)
        if not force and entry and entry.get("size") == size and entry.get("output") and \
                (output_dir / entry["output"]).exists():
            item["status"] = "omitido (ya recomprimido)"
            item["output_name"] = entry["output"]
            item["stats"] = entry.get("stats")
            item["percent"] = 1.0
            continue

        item["status"] = "procesando"
        capture_dt, _ = get_capture_datetime(source, is_video=True)
        output_name = unique_name(capture_dt, ".mp4", used_names)
        dest = output_dir / output_name

        try:
            def progress_cb(fraction, item=item):
                item["percent"] = fraction

            stats = recompress_clip(source, dest, quality=quality, max_width=max_width, progress_cb=progress_cb)

            timestamp = capture_dt.timestamp()
            os.utime(dest, (timestamp, timestamp))

            entry = {"size": size, "output": output_name, "stats": stats}
            record_entry(root_path, OUTPUT_DIR_NAME, cache_key, entry)
            manifest[cache_key] = entry
            item["status"] = "completado"
            item["output_name"] = output_name
            item["stats"] = stats
        except Exception as exc:
            item["status"] = "error"
            item["error"] = str(exc)

    job["state"] = "finalizado"
