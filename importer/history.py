"""Historial global de importaciones.

Sirve para dos cosas: saber qué tomas ya se importaron (para no volver a copiarlas si
se reinserta la misma tarjeta) y qué ficheros quedan por subir al NAS (para poder
reintentar una subida que se cortó a mitad sin repetir la importación entera).
"""

import json
import threading
from datetime import datetime
from pathlib import Path

from .config import CONFIG_DIR

HISTORY_PATH = CONFIG_DIR / "historial.json"

_lock = threading.Lock()
_MAX_RUNS = 50


def _empty() -> dict:
    return {"version": 1, "imported": {}, "runs": []}


def load_history() -> dict:
    if not HISTORY_PATH.exists():
        return _empty()
    try:
        with open(HISTORY_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError):
        return _empty()
    return {**_empty(), **data}


def _write(history: dict) -> None:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    with open(HISTORY_PATH, "w", encoding="utf-8") as f:
        json.dump(history, f, indent=2, ensure_ascii=False)


def imported_keys() -> set[str]:
    return set(load_history()["imported"].keys())


def record_import(key: str, entry: dict) -> None:
    with _lock:
        history = load_history()
        history["imported"][key] = entry
        _write(history)


def record_run(run: dict) -> None:
    with _lock:
        history = load_history()
        history["runs"].insert(0, run)
        del history["runs"][_MAX_RUNS:]
        _write(history)


def mark_uploaded(dest_paths: list[str]) -> None:
    with _lock:
        history = load_history()
        stamp = datetime.now().isoformat(timespec="seconds")
        by_dest = {v.get("dest"): k for k, v in history["imported"].items()}
        for dest in dest_paths:
            key = by_dest.get(dest)
            if key:
                history["imported"][key]["uploaded_at"] = stamp
        _write(history)


def pending_upload() -> list[dict]:
    """Ficheros ya importados que siguen sin subir al NAS y aún existen en disco."""
    pending = []
    for entry in load_history()["imported"].values():
        if entry.get("uploaded_at"):
            continue
        dest = entry.get("dest")
        if dest and Path(dest).exists():
            pending.append(entry)
    pending.sort(key=lambda e: e.get("dest", ""))
    return pending


def recent_runs(limit: int = 10) -> list[dict]:
    return load_history()["runs"][:limit]
