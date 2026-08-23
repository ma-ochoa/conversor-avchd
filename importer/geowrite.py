"""Escritura de coordenadas GPS en el EXIF de fotos y vídeos.

Synology Photos (y Plex, Emby, Fotos de macOS…) leen la posición **de dentro del
archivo**. Un fichero aparte no sirve para que aparezcan en el mapa, así que aquí sí se
modifica el original — es la única parte de toda la app que lo hace.

Por eso, antes de tocar nada se guarda una copia intacta en una subcarpeta
`_originales_sin_gps/`. Ocupa espacio, pero permite deshacer una asignación equivocada,
que con miles de fotos es cuestión de tiempo que pase.
"""

import shutil
import subprocess
from pathlib import Path

BACKUP_DIR_NAME = "_originales_sin_gps"

_VIDEO_SUFFIXES = {".mp4", ".mov", ".m4v", ".mts", ".m2ts", ".avi", ".mkv"}

# Comprobado con exiftool 13.x: "Writing of MTS files is not yet supported". El flujo de
# transporte AVCHD no tiene dónde meter metadatos de forma estándar, así que no es una
# carencia de exiftool que vaya a resolverse. La salida es convertir el clip a MP4 con el
# módulo de Conversión (que además es remuxeo sin pérdida) y ubicar el MP4 resultante.
UNWRITABLE_SUFFIXES = {".mts", ".m2ts"}


class GeoWriteError(RuntimeError):
    pass


def can_write(path: Path) -> bool:
    return Path(path).suffix.lower() not in UNWRITABLE_SUFFIXES


def backup_path(target: Path) -> Path:
    return target.parent / BACKUP_DIR_NAME / target.name


def _gps_args(lat: float, lon: float) -> list[str]:
    args = [
        f"-GPSLatitude={abs(lat)}",
        f"-GPSLatitudeRef={'N' if lat >= 0 else 'S'}",
        f"-GPSLongitude={abs(lon)}",
        f"-GPSLongitudeRef={'E' if lon >= 0 else 'W'}",
    ]
    return args


def _video_args(lat: float, lon: float) -> list[str]:
    # Los contenedores QuickTime/MP4 no usan el EXIF de las fotos: la posición va en un
    # único campo de texto del contenedor, y en XMP para quien lea eso.
    return [
        f"-QuickTime:GPSCoordinates={lat} {lon}",
        f"-XMP:GPSLatitude={lat}",
        f"-XMP:GPSLongitude={lon}",
    ]


def write_gps(target: Path, lat: float, lon: float, make_backup: bool = True) -> dict:
    """Escribe la posición en `target`. Devuelve {'backup': ruta o None}."""
    target = Path(target)
    if not target.is_file():
        raise GeoWriteError(f"No existe el archivo: {target}")

    # Se comprueba antes de copiar nada: si no se puede escribir, crear la copia de
    # seguridad solo dejaría basura duplicada.
    if not can_write(target):
        raise GeoWriteError(
            f"El formato {target.suffix.upper()} (AVCHD) no admite guardar la ubicación "
            "dentro del archivo. Conviértelo a MP4 en el módulo de Conversión (es remuxeo "
            "sin pérdida) y asigna la ubicación al MP4 resultante."
        )

    backup = None
    if make_backup:
        backup = backup_path(target)
        # Si ya hay copia es de una asignación anterior: la buena es esa, la de antes de
        # que la app tocara nada. No se pisa.
        if not backup.exists():
            backup.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(target, backup)

    is_video = target.suffix.lower() in _VIDEO_SUFFIXES
    args = _video_args(lat, lon) if is_video else _gps_args(lat, lon)

    cmd = ["exiftool", "-q", "-overwrite_original", "-P"]
    if is_video:
        # Sin esto exiftool se niega a escribir en algunos MP4/MOV por no poder reordenar
        # los átomos del contenedor.
        cmd.append("-api")
        cmd.append("QuickTimeHandler=1")
    cmd += args + [str(target)]

    result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    if result.returncode != 0:
        raise GeoWriteError(
            f"exiftool no pudo escribir la posición en {target.name}: "
            f"{(result.stderr or result.stdout).strip()[-300:]}"
        )

    return {"backup": str(backup) if backup else None}


def restore(target: Path) -> bool:
    """Devuelve el archivo a como estaba antes de escribirle el GPS."""
    target = Path(target)
    backup = backup_path(target)
    if not backup.is_file():
        return False
    shutil.copy2(backup, target)
    return True


def verify_gps(target: Path) -> tuple[float, float] | None:
    """Relee la posición del archivo ya escrito, para confirmar que quedó dentro."""
    from .exif import read_metadata

    meta = read_metadata([Path(target)]).get(str(Path(target)))
    return meta.get("gps") if meta else None
