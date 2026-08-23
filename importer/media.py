"""Escaneo y clasificación del contenido de un origen (tarjeta o carpeta volcada)."""

import os
from datetime import datetime
from pathlib import Path

from .cameras import UNKNOWN_FOLDER, hint_from_structure, resolve_folder, suggest_folder
from .exif import read_metadata
from .sources import is_bundle

JPG_EXTS = {".jpg", ".jpeg", ".heic", ".heif", ".png"}
RAW_EXTS = {
    ".arw", ".sr2", ".srf", ".cr2", ".cr3", ".crw", ".nef", ".nrw", ".orf", ".raf",
    ".rw2", ".rwl", ".dng", ".pef", ".srw", ".3fr", ".iiq", ".x3f", ".mrw", ".erf",
    ".kdc", ".dcr", ".mef", ".mos", ".raw",
}
AVCHD_EXTS = {".mts", ".m2ts"}
MP4_EXTS = {".mp4", ".mov", ".m4v", ".avi", ".mkv", ".wmv", ".3gp"}
SIDECAR_EXTS = {".xmp", ".aae"}
TIFF_EXTS = {".tif", ".tiff"}

VIDEO_EXTS = AVCHD_EXTS | MP4_EXTS
PHOTO_EXTS = JPG_EXTS | RAW_EXTS | TIFF_EXTS

# Ficheros que las cámaras dejan al lado del material bueno y que no interesa importar.
_IGNORED_NAMES = {"thumbs.db", "desktop.ini", "sonycard.ind", "status.bin", "mediapro.xml"}
_IGNORED_SUFFIXES = {".thm", ".lrv", ".ctg", ".cpi", ".mpl", ".bdm", ".bnp", ".inp", ".int", ".pmp", ".ind", ".bin", ".modd", ".moff"}

# Salidas de los otros módulos de la app: si alguien apunta el importador a una carpeta
# de proyecto en vez de a una tarjeta, no debe volver a importar lo que ya generó.
# Y carpetas de servicio de las propias tarjetas: THMBNL guarda un JPG por clip XAVC y
# SUB una copia en baja resolución, que si no se filtran se importan como si fueran
# fotos y vídeos de verdad.
_IGNORED_DIRS = {
    "conversion", "estabilizado", "recompresion", "montaje",
    "thmbnl", "sub", "general", "canonmsc", "misc", "avf_info", "clipinf", "playlist",
}


def _category(suffix: str) -> str | None:
    if suffix in RAW_EXTS:
        return "raw"
    if suffix in JPG_EXTS or suffix in TIFF_EXTS:
        return "jpg"
    if suffix in VIDEO_EXTS:
        return "video"
    if suffix in SIDECAR_EXTS:
        return "sidecar"
    return None


def _iter_files(root: Path):
    for dirpath, dirnames, filenames in os.walk(root):
        # Los bundles de macOS (.app, .photoslibrary…) son carpetas llenas de PNG y JPG:
        # descender en ellos importaría iconos de aplicaciones como si fueran fotos.
        dirnames[:] = [
            d for d in dirnames
            if not d.startswith(".")
            and d.lower() not in _IGNORED_DIRS
            and not is_bundle(Path(d))
        ]
        for name in filenames:
            if name.startswith(".") or name.lower() in _IGNORED_NAMES:
                continue
            path = Path(dirpath) / name
            if path.suffix.lower() in _IGNORED_SUFFIXES:
                continue
            yield path


def _camera_key(meta: dict) -> str:
    """Clave estable por cámara. El modelo EXIF es lo fiable; sin él, todo va a un grupo
    común que la interfaz muestra como pendiente de identificar."""
    return meta["model"] or ""


def scan_source(source_path: str, config: dict, already_imported: set[str] | None = None) -> dict:
    """Recorre el origen, clasifica cada fichero y lo agrupa por cámara y por día."""
    root = Path(source_path).expanduser().resolve()
    if not root.is_dir():
        raise NotADirectoryError(str(root))

    already_imported = already_imported or set()
    mapping = config.get("cameras", {})

    candidates: list[tuple[Path, str]] = []
    for path in _iter_files(root):
        category = _category(path.suffix.lower())
        if category:
            candidates.append((path, category))

    metadata = read_metadata([p for p, c in candidates if c != "sidecar"])

    files = []
    cameras: dict[str, dict] = {}
    skipped_duplicates = 0

    for path, category in candidates:
        try:
            size = path.stat().st_size
        except OSError:
            continue

        meta = metadata.get(str(path), {"make": "", "model": "", "capture_dt": None,
                                        "date_source": "archivo", "duration": None, "gps": None})
        capture_dt = meta["capture_dt"] or datetime.fromtimestamp(path.stat().st_mtime)

        key = _camera_key(meta)
        camera = cameras.get(key)
        if camera is None:
            camera = {
                "key": key,
                "model": meta["model"],
                "make": meta["make"],
                "folder": resolve_folder(meta["make"], meta["model"], mapping) if key else "",
                "suggested": suggest_folder(meta["make"], meta["model"]) if key else "",
                "known": bool(key and key in mapping),
                "counts": {"jpg": 0, "raw": 0, "video": 0, "sidecar": 0},
                "bytes": 0,
                "days": {},
            }
            cameras[key] = camera

        day = capture_dt.strftime("%Y-%m-%d")
        entry = {
            "path": str(path),
            "relative": str(path.relative_to(root)),
            "name": path.name,
            "size": size,
            "category": category,
            "video_kind": ("avchd" if path.suffix.lower() in AVCHD_EXTS else "mp4") if category == "video" else None,
            "camera_key": key,
            "day": day,
            "capture_dt": capture_dt.isoformat(),
            "date_source": meta["date_source"],
            "group": str(path.parent / path.stem),
            "duplicate": import_key(path.name, size, capture_dt.isoformat()) in already_imported,
            "gps": list(meta["gps"]) if meta.get("gps") else None,
        }
        if entry["duplicate"]:
            skipped_duplicates += 1

        files.append(entry)
        camera["counts"][category] += 1
        camera["bytes"] += size

        day_stats = camera["days"].setdefault(
            day, {"date": day, "photos": 0, "videos": 0, "bytes": 0, "with_gps": 0, "without_gps": 0}
        )
        if category == "video":
            day_stats["videos"] += 1
        elif category != "sidecar":
            day_stats["photos"] += 1
        day_stats["bytes"] += size
        if category != "sidecar":
            day_stats["with_gps" if entry["gps"] else "without_gps"] += 1

    camera_list = []
    for camera in cameras.values():
        camera["days"] = sorted(camera["days"].values(), key=lambda d: d["date"])
        if not camera["key"]:
            hint = hint_from_structure([f["relative"] for f in files])
            camera["folder"] = ""
            camera["suggested"] = hint or UNKNOWN_FOLDER
            camera["hint"] = hint
        camera_list.append(camera)
    camera_list.sort(key=lambda c: (not c["key"], -c["bytes"]))

    files.sort(key=lambda f: f["capture_dt"])

    return {
        "source": str(root),
        "files": files,
        "cameras": camera_list,
        "totals": {
            "files": len(files),
            "bytes": sum(f["size"] for f in files),
            "jpg": sum(1 for f in files if f["category"] == "jpg"),
            "raw": sum(1 for f in files if f["category"] == "raw"),
            "video": sum(1 for f in files if f["category"] == "video"),
            "duplicates": skipped_duplicates,
            "with_gps": sum(1 for f in files if f["gps"]),
            "without_gps": sum(1 for f in files if not f["gps"] and f["category"] != "sidecar"),
        },
    }


def import_key(name: str, size: int, capture_iso: str) -> str:
    """Identidad de una toma sin tener que leer el fichero entero.

    Hashear una tarjeta de 64 GB solo para detectar repetidos costaría más que la propia
    copia; nombre + tamaño exacto + segundo de captura ya es único en la práctica. El
    checksum de verdad se calcula al copiar, que es cuando hay que leer el fichero igual.
    """
    return f"{name}|{size}|{capture_iso}"
