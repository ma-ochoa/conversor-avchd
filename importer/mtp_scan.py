"""Convierte el contenido de un móvil en el mismo «escaneo» que produce una tarjeta.

La idea es que **el móvil sea un origen más**: se lista lo que hay, se agrupa por cámara y
día, se elige qué días importar y con qué nombre de evento, se ve el plan y se importa. Un
solo flujo, el mismo que para una SD.

Antes había un paso intermedio —descargar todo a una carpeta oculta y luego importar desde
ahí— que duplicaba el material en disco, escondía los archivos si no se completaba la
importación, y obligaba a hacer el trabajo en dos tiempos. Ya no: aquí solo se leen los
metadatos, y cada fichero se descarga directamente a su destino final.

Es posible porque MTP da, sin descargar nada:
  · el **modelo del móvil** (`SM-S938B`), que es la clave de cámara;
  · la **fecha** y el **tamaño exacto** de cada fichero, que es lo que hace falta para
    agrupar por día y para planificar.

Lo único que no se puede saber por adelantado es el GPS de cada foto: eso vive dentro del
archivo. Se lee después de copiarlo, al alimentar el índice de ubicaciones.
"""

from datetime import datetime
from pathlib import Path

from . import mtp
from .cameras import resolve_folder, suggest_folder
from .media import JPG_EXTS, RAW_EXTS, TIFF_EXTS, AVCHD_EXTS, import_key

# Prefijo que identifica una ruta del móvil frente a una del disco.
MTP_PREFIX = "mtp://"


def is_mtp_source(path: str) -> bool:
    return str(path).startswith(MTP_PREFIX)


def to_mtp_path(source: str) -> str:
    return str(source)[len(MTP_PREFIX):] or "/"


def to_source(mtp_path: str) -> str:
    return f"{MTP_PREFIX}{mtp_path}"


def _category(name: str) -> str:
    suffix = Path(name).suffix.lower()
    if suffix in RAW_EXTS:
        return "raw"
    if suffix in JPG_EXTS or suffix in TIFF_EXTS:
        return "jpg"
    return "video"


def scan_phone(mtp_path: str, config: dict, already_imported: set[str] | None = None,
               progress_cb=None) -> dict:
    """Mismo formato que `media.scan_source`, pero leyendo del móvil."""
    already_imported = already_imported or set()
    mapping = config.get("cameras", {})

    model = mtp.device_model()
    files_raw = mtp.list_files(mtp_path, recursive=True, progress_cb=progress_cb)

    camera = {
        "key": model,
        "model": model,
        "make": "",
        "folder": resolve_folder("", model, mapping) if model else "",
        "suggested": suggest_folder("", model) if model else "",
        "known": bool(model and model in mapping),
        "counts": {"jpg": 0, "raw": 0, "video": 0, "sidecar": 0},
        "bytes": 0,
        "days": {},
    }

    files = []
    skipped_duplicates = 0

    for entry in files_raw:
        captured = entry.get("captured")
        if not captured:
            continue
        moment = datetime.fromisoformat(captured)
        category = _category(entry["name"])
        size = entry.get("size") or 0
        day = moment.strftime("%Y-%m-%d")

        item = {
            # La ruta del móvil no es una ruta de disco: se marca para que quede claro
            # que nadie debe intentar abrirla con open().
            "path": to_source(entry["path"]),
            "mtp_folder": entry["folder"],
            "relative": entry["name"],
            "name": entry["name"],
            "size": size,
            "category": category,
            "video_kind": ("avchd" if Path(entry["name"]).suffix.lower() in AVCHD_EXTS
                           else "mp4") if category == "video" else None,
            "camera_key": model,
            "day": day,
            "capture_dt": moment.isoformat(),
            "date_source": "archivo",
            # Cada fichero es su propio grupo: un móvil no genera pares RAW+JPG con el
            # mismo nombre como hace una cámara.
            "group": entry["path"],
            "duplicate": import_key(entry["name"], size, moment.isoformat()) in already_imported,
            # Se rellena tras copiar, leyendo el EXIF del archivo ya en disco.
            "gps": None,
        }
        if item["duplicate"]:
            skipped_duplicates += 1

        files.append(item)
        camera["counts"][category] += 1
        camera["bytes"] += size

        stats = camera["days"].setdefault(
            day, {"date": day, "photos": 0, "videos": 0, "bytes": 0,
                  "with_gps": 0, "without_gps": 0}
        )
        if category == "video":
            stats["videos"] += 1
        else:
            stats["photos"] += 1
        stats["bytes"] += size
        # El GPS no se conoce todavía; se cuenta como pendiente para no prometer de más.
        stats["without_gps"] += 1

    camera["days"] = sorted(camera["days"].values(), key=lambda d: d["date"])
    files.sort(key=lambda f: f["capture_dt"])

    return {
        "source": to_source(mtp_path),
        "files": files,
        "cameras": [camera] if files else [],
        "totals": {
            "files": len(files),
            "bytes": sum(f["size"] for f in files),
            "jpg": sum(1 for f in files if f["category"] == "jpg"),
            "raw": sum(1 for f in files if f["category"] == "raw"),
            "video": sum(1 for f in files if f["category"] == "video"),
            "duplicates": skipped_duplicates,
            "with_gps": 0,
            "without_gps": len(files),
        },
    }
