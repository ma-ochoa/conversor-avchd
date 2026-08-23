"""Índice de qué fotos y vídeos llevan posición y cuáles no.

Vive como `.ubicaciones.json` en la raíz de la carpeta de destino, no en la configuración
global: así viaja con las fotos, sobrevive a mover la carpeta a otro disco, y el módulo
Ubicación puede trabajar sin volver a leer el EXIF de miles de ficheros cada vez.

Las rutas se guardan **relativas a la raíz**, para que renombrar o mover la carpeta padre
no invalide el índice entero.
"""

import json
import threading
from datetime import datetime
from pathlib import Path

INDEX_NAME = ".ubicaciones.json"

_lock = threading.Lock()

# De dónde salió la posición de un fichero.
SOURCE_EXIF = "exif"          # ya venía en el archivo
SOURCE_MATCH = "referencia"   # deducida de una foto con GPS tomada a hora cercana
SOURCE_GPX = "gpx"            # deducida de un track GPX
SOURCE_MANUAL = "manual"      # elegida a mano en el mapa


def index_path(root: Path) -> Path:
    return Path(root) / INDEX_NAME


def load_index(root: Path) -> dict:
    path = index_path(root)
    if not path.exists():
        return {"version": 1, "updated_at": None, "files": {}}
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError):
        return {"version": 1, "updated_at": None, "files": {}}
    data.setdefault("files", {})
    return data


def _write(root: Path, data: dict) -> None:
    data["updated_at"] = datetime.now().isoformat(timespec="seconds")
    path = index_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    # Escritura atómica: un corte a mitad no debe dejar el índice ilegible, porque es lo
    # único que evita releer el EXIF de toda la biblioteca.
    temporal = path.with_suffix(".tmp")
    with open(temporal, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    temporal.replace(path)


def entry(capture_dt: str, gps, source: str, place: str = "") -> dict:
    return {
        "capture_dt": capture_dt,
        "gps": list(gps) if gps else None,
        "source": source if gps else None,
        "place": place,
    }


def record_many(root: Path, entries: dict[str, dict]) -> None:
    """entries: {ruta relativa: entry(...)}. Fusiona sobre lo que ya hubiera."""
    if not entries:
        return
    with _lock:
        data = load_index(root)
        data["files"].update(entries)
        _write(root, data)


def set_location(root: Path, relatives: list[str], gps, source: str, place: str = "") -> int:
    """Asigna la misma posición a varios ficheros. Devuelve cuántos se actualizaron."""
    with _lock:
        data = load_index(root)
        changed = 0
        for relative in relatives:
            current = data["files"].get(relative)
            if current is None:
                continue
            current["gps"] = list(gps) if gps else None
            current["source"] = source if gps else None
            current["place"] = place
            changed += 1
        _write(root, data)
        return changed


def rebuild(root: Path, only_missing: bool = True, progress_cb=None) -> dict:
    """Recorre la carpeta y mete en el índice lo que aún no esté.

    Hace falta para carpetas importadas antes de que existiera el índice, y para recoger
    lo que se haya copiado ahí por otros medios. Con `only_missing=False` se releen
    también los que ya estaban, que es la forma de recuperarse de un índice desfasado.
    """
    from .exif import read_metadata
    from .geowrite import BACKUP_DIR_NAME
    from .media import PHOTO_EXTS, VIDEO_EXTS, _iter_files

    root = Path(root)
    data = load_index(root)
    known = data["files"]

    candidates = []
    for path in _iter_files(root):
        if path.suffix.lower() not in (PHOTO_EXTS | VIDEO_EXTS):
            continue
        # Las copias de seguridad no son fotos de la biblioteca: son el estado anterior.
        if BACKUP_DIR_NAME in path.parts:
            continue
        relative = str(path.relative_to(root))
        if only_missing and relative in known:
            continue
        candidates.append((path, relative))

    if progress_cb:
        progress_cb(0, len(candidates))

    added = {}
    CHUNK = 400
    for start in range(0, len(candidates), CHUNK):
        chunk = candidates[start:start + CHUNK]
        metadata = read_metadata([p for p, _ in chunk])
        for path, relative in chunk:
            meta = metadata.get(str(path), {})
            capture = meta.get("capture_dt")
            added[relative] = entry(
                capture.isoformat() if capture else "",
                meta.get("gps"),
                SOURCE_EXIF,
            )
        if progress_cb:
            progress_cb(min(start + CHUNK, len(candidates)), len(candidates))

    # Lo que ya no existe en disco se cae del índice, para que los recuentos no mientan.
    if not only_missing:
        alive = {relative for _, relative in candidates}
        known = {k: v for k, v in known.items() if k in alive}
        data["files"] = known

    if added or not only_missing:
        with _lock:
            data["files"].update(added)
            _write(root, data)

    return {"scanned": len(candidates), "added": len(added)}


def stats(root: Path) -> dict:
    files = load_index(root)["files"]
    with_gps = sum(1 for e in files.values() if e.get("gps"))
    return {"total": len(files), "with_gps": with_gps, "without_gps": len(files) - with_gps}
