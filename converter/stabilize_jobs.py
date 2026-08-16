"""Orquesta un trabajo de estabilización en segundo plano, independiente del remuxeo."""

import os
import threading
import uuid
from datetime import datetime
from pathlib import Path

from .manifest import load_manifest, record_entry
from .metadata import get_capture_datetime
from .naming import unique_name
from .stabilize import ZOOM_AUTO_STATIC, load_stabilize_draft, stabilize_clip

OUTPUT_DIR_NAME = "estabilizado"

_jobs: dict[str, dict] = {}
_jobs_lock = threading.Lock()

_DEFAULT_PARAMS = {
    "shakiness": 5,
    "accuracy": 15,
    "smoothing": 10,
    "zoom_mode": ZOOM_AUTO_STATIC,
    "zoom_percent": 0.0,
}


def start_job(root: str, avchd_paths: list[str], force: bool, fast_hw: bool = False,
              params: dict | None = None) -> str:
    root_path = Path(root).expanduser().resolve()
    job_id = uuid.uuid4().hex
    stab_params = {**_DEFAULT_PARAMS, **(params or {})}

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
        "output_dir": str(root_path / OUTPUT_DIR_NAME),
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
    output_dir = root_path / OUTPUT_DIR_NAME
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

        entry = manifest.get(str(source))
        if not force and entry and entry.get("size") == size and entry.get("output") and \
                (output_dir / entry["output"]).exists():
            item["status"] = "omitido (ya estabilizado)"
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

            draft = load_stabilize_draft(root_path, source)
            effective_params = {**stab_params, **draft} if draft else stab_params
            stats = stabilize_clip(
                source, dest, root_path, progress_cb=progress_cb, fast_hw=fast_hw, **effective_params
            )

            timestamp = capture_dt.timestamp()
            os.utime(dest, (timestamp, timestamp))

            entry = {"size": size, "output": output_name, "stats": stats}
            record_entry(root_path, OUTPUT_DIR_NAME, str(source), entry)
            manifest[str(source)] = entry
            item["status"] = "completado"
            item["output_name"] = output_name
            item["stats"] = stats
        except Exception as exc:
            item["status"] = "error"
            item["error"] = str(exc)

    job["state"] = "finalizado"
