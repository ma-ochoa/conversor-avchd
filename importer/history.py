"""Historial global de importaciones.

Sirve para dos cosas: saber qué tomas ya se importaron (para no volver a copiarlas si
se reinserta la misma tarjeta) y qué ficheros quedan por subir al NAS (para poder
reintentar una subida que se cortó a mitad sin repetir la importación entera).
"""

import json
import threading
import time
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


class UploadTracker:
    """Registra en el historial lo que ya llegó al NAS, **fichero a fichero según se sube**.

    Marcarlo todo al final significaba que una subida cortada a la mitad —red, cierre de
    la app, un error cualquiera— dejaba en cero el registro y volvía a subirlo todo desde
    el principio, aunque ya hubiera cientos de archivos en el NAS.
    """

    # Se agrupa para no reescribir el historial entero por cada foto, pero también se
    # vuelca cada pocos segundos: un vídeo grande tarda minutos, y esperar a juntar un
    # lote dejaría sin registrar todo ese rato.
    LOTE = 20
    SEGUNDOS = 20

    def __init__(self, entries: list[dict]):
        self._por_relativa = {e["dest_relative"]: e["dest"] for e in entries}
        self._subidos: list[str] = []
        self._ultimo = time.monotonic()

    def note(self, dest_relative: str) -> None:
        """Apunta un fichero recién subido. Vuelca al historial cuando toca."""
        dest = self._por_relativa.get(dest_relative)
        if not dest:
            return
        self._subidos.append(dest)
        if len(self._subidos) >= self.LOTE or time.monotonic() - self._ultimo > self.SEGUNDOS:
            self.flush()

    def flush(self) -> None:
        """Vuelca lo pendiente de apuntar. Llámalo siempre desde un `finally`: pase lo que
        pase, lo que sí llegó al NAS tiene que quedar registrado."""
        if self._subidos:
            mark_uploaded(self._subidos)
            self._subidos.clear()
        self._ultimo = time.monotonic()


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
