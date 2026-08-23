"""Detección de orígenes: tarjetas montadas y carpetas volcadas a mano.

Una carpeta que alguien copió al Escritorio se trata exactamente igual que una tarjeta
insertada — misma detección de cámara, mismo plan de destino, mismo job. Lo único que
cambia es de dónde sale la ruta y que el borrado del origen se ofrece con más cautela.
"""

import platform
import plistlib
import subprocess
import threading
import time
from pathlib import Path

# Marcadores de "esto es una tarjeta de cámara", no un disco cualquiera.
CARD_MARKERS = ("DCIM", "PRIVATE", "AVCHD", "M4ROOT", "MISC", "CLIP", "MP_ROOT")

# Carpetas donde la gente suelta volcados manuales; se miran solo un nivel.
DROP_FOLDERS = ("Desktop", "Escritorio", "Downloads", "Descargas")

_MEDIA_SUFFIXES = {
    ".jpg", ".jpeg", ".heic", ".heif", ".png", ".tif", ".tiff",
    ".arw", ".cr2", ".cr3", ".nef", ".orf", ".raf", ".rw2", ".dng",
    ".mts", ".m2ts", ".mp4", ".mov", ".m4v", ".avi",
}

# En macOS un montón de cosas que el Finder muestra como un único fichero son en realidad
# carpetas: las aplicaciones llevan iconos PNG dentro y una fototeca de Fotos son miles de
# JPG. Sin esto, `iPhoto.app` o `Fotos.photoslibrary` aparecerían en la lista de orígenes
# como si fueran tarjetas — y recorrer una fototeca entera además sería lentísimo.
_BUNDLE_SUFFIXES = {
    ".app", ".bundle", ".framework", ".plugin", ".kext", ".pkg", ".xcodeproj",
    ".photoslibrary", ".aplibrary", ".migratedaperturelibrary", ".fcpbundle",
    ".imovielibrary", ".theater", ".lrdata", ".lrlibrary", ".download",
}


def is_bundle(path: Path) -> bool:
    return path.suffix.lower() in _BUNDLE_SUFFIXES


# Carpetas que macOS protege con TCC (Escritorio, Descargas, Documentos): hasta que el
# usuario concede el permiso, listarlas NO devuelve error — la llamada se queda esperando
# indefinidamente a un diálogo del sistema. Sin un límite de tiempo eso colgaría la
# petición HTTP entera, así que el listado se hace en un hilo del que se puede desistir.
_blocked_folders: set[str] = set()


def _listdir(path: Path, timeout: float = 3.0) -> list[Path] | None:
    """Contenido de `path`, o None si no hay permiso o la llamada se queda colgada."""
    result: list[list[Path] | None] = [None]

    def run():
        try:
            result[0] = list(path.iterdir())
        except (OSError, PermissionError):
            result[0] = None

    thread = threading.Thread(target=run, daemon=True)
    thread.start()
    thread.join(timeout)
    if thread.is_alive():
        _blocked_folders.add(str(path))
        return None
    return result[0]


def _has_card_structure(path: Path) -> bool:
    entries = _listdir(path)
    if entries is None:
        return False
    return bool({p.name.upper() for p in entries if p.is_dir()} & set(CARD_MARKERS))


def _has_media(path: Path, max_depth: int = 2, deadline: float | None = None) -> bool:
    """Mira si hay algún fichero de foto/vídeo, sin recorrer la carpeta entera.

    Con `deadline` se rinde en cuanto se agota el tiempo: una carpeta del Escritorio
    puede ser un proyecto con decenas de miles de ficheros, y la detección de orígenes
    tiene que responder rápido aunque no llegue a mirarlo todo.
    """
    stack = [(path, 0)]
    while stack:
        if deadline and time.monotonic() > deadline:
            return False
        current, depth = stack.pop()
        entries = _listdir(current)
        if entries is None:
            continue
        for entry in entries:
            if entry.name.startswith("."):
                continue
            if entry.is_file() and entry.suffix.lower() in _MEDIA_SUFFIXES:
                return True
            if entry.is_dir() and depth < max_depth and not is_bundle(entry):
                stack.append((entry, depth + 1))
    return False


# Ruta absoluta a propósito: al abrir un `.command` desde el Finder, el PATH heredado no
# incluye `/usr/sbin`, así que llamar a "diskutil" a secas lanza FileNotFoundError. Como
# el fallo se capturaba, las tarjetas simplemente **desaparecían de la lista** sin ningún
# aviso — pero solo al arrancar desde el Finder, no desde una terminal.
_DISKUTIL = "/usr/sbin/diskutil"


def _macos_volumes() -> list[dict]:
    volumes = []
    root = Path("/Volumes")
    if not root.is_dir():
        return volumes

    for mount in sorted(root.iterdir(), key=lambda p: p.name.lower()):
        if not mount.is_dir() or mount.name.startswith("."):
            continue
        if mount.resolve() == Path("/"):
            continue

        # Lo que aporta diskutil (si es extraíble, cuánto ocupa) es información
        # adicional: si falla, el volumen tiene que salir igualmente en la lista. Antes
        # una excepción aquí tumbaba la detección entera y no aparecía ninguna tarjeta.
        removable, total, free = False, None, None
        try:
            result = subprocess.run(
                [_DISKUTIL, "info", "-plist", str(mount)], capture_output=True, timeout=15
            )
            if result.returncode == 0:
                info = plistlib.loads(result.stdout)
                removable = bool(info.get("Ejectable") or info.get("RemovableMedia"))
                total = info.get("TotalSize")
                free = info.get("FreeSpace")
        except (OSError, plistlib.InvalidFileException, subprocess.SubprocessError):
            pass

        volumes.append({
            "path": str(mount),
            "label": mount.name,
            "removable": removable,
            "total_bytes": total,
            "free_bytes": free,
        })
    return volumes


def _windows_volumes() -> list[dict]:
    import ctypes
    import string

    DRIVE_REMOVABLE = 2
    DRIVE_FIXED = 3
    kernel32 = ctypes.windll.kernel32

    volumes = []
    mask = kernel32.GetLogicalDrives()
    for index, letter in enumerate(string.ascii_uppercase):
        if not mask >> index & 1:
            continue
        root = f"{letter}:\\"
        drive_type = kernel32.GetDriveTypeW(ctypes.c_wchar_p(root))
        if drive_type not in (DRIVE_REMOVABLE, DRIVE_FIXED):
            continue
        if drive_type == DRIVE_FIXED and letter == "C":
            continue

        label_buf = ctypes.create_unicode_buffer(261)
        kernel32.GetVolumeInformationW(
            ctypes.c_wchar_p(root), label_buf, 261, None, None, None, None, 0
        )
        free = ctypes.c_ulonglong(0)
        total = ctypes.c_ulonglong(0)
        kernel32.GetDiskFreeSpaceExW(
            ctypes.c_wchar_p(root), ctypes.byref(free), ctypes.byref(total), None
        )
        volumes.append({
            "path": root,
            "label": label_buf.value or root,
            "removable": drive_type == DRIVE_REMOVABLE,
            "total_bytes": total.value or None,
            "free_bytes": free.value or None,
        })
    return volumes


def _linux_volumes() -> list[dict]:
    volumes = []
    candidates = [Path("/media"), Path("/media") / Path.home().name,
                  Path("/run/media") / Path.home().name, Path("/mnt")]
    seen = set()
    for base in candidates:
        if not base.is_dir():
            continue
        for mount in sorted(base.iterdir(), key=lambda p: p.name.lower()):
            if not mount.is_dir() or str(mount) in seen:
                continue
            seen.add(str(mount))
            volumes.append({
                "path": str(mount), "label": mount.name, "removable": True,
                "total_bytes": None, "free_bytes": None,
            })
    return volumes


def _mounted_volumes() -> list[dict]:
    system = platform.system()
    try:
        if system == "Darwin":
            return _macos_volumes()
        if system == "Windows":
            return _windows_volumes()
        return _linux_volumes()
    except Exception:
        return []


def _dropped_folders(deadline: float, retry_blocked: bool) -> tuple[list[dict], list[str]]:
    """Carpetas del Escritorio/Descargas que parecen un volcado manual de tarjeta.

    Devuelve también qué carpetas no se pudieron leer, para poder decirle al usuario que
    tiene que dar permiso en lugar de dejarle pensando que no hay nada ahí.
    """
    found: list[dict] = []
    blocked: list[str] = []

    for folder_name in DROP_FOLDERS:
        base = Path.home() / folder_name
        if not base.is_dir():
            continue
        if str(base) in _blocked_folders and not retry_blocked:
            blocked.append(folder_name)
            continue

        listing = _listdir(base)
        if listing is None:
            blocked.append(folder_name)
            continue
        entries = sorted(listing, key=lambda p: p.name.lower())

        for entry in entries:
            if time.monotonic() > deadline:
                return found, blocked
            if not entry.is_dir() or entry.name.startswith(".") or is_bundle(entry):
                continue
            is_card = _has_card_structure(entry)
            if not is_card and not _has_media(entry, deadline=deadline):
                continue
            found.append({
                "path": str(entry),
                "label": entry.name,
                "kind": "carpeta",
                "removable": False,
                "is_card": is_card,
                "parent": folder_name,
                "total_bytes": None,
                "free_bytes": None,
            })
    return found, blocked


def detect_sources(budget_seconds: float = 8.0, retry_blocked: bool = False) -> dict:
    """Tarjetas montadas y carpetas volcadas a mano, ordenadas por probabilidad."""
    deadline = time.monotonic() + budget_seconds

    sources = []
    for volume in _mounted_volumes():
        path = Path(volume["path"])
        is_card = _has_card_structure(path)
        if not is_card and not volume["removable"] and not _has_media(path, deadline=deadline):
            continue
        sources.append({**volume, "kind": "tarjeta" if volume["removable"] else "volumen",
                        "is_card": is_card, "parent": None})

    dropped, blocked = _dropped_folders(deadline, retry_blocked)
    sources.extend(dropped)
    sources.sort(key=lambda s: (not s["is_card"], not s["removable"], s["label"].lower()))
    return {"sources": sources, "blocked_folders": blocked}


def describe_source(path: str) -> dict:
    """Datos de una carpeta elegida a mano, para tratarla igual que una tarjeta."""
    resolved = Path(path).expanduser().resolve()
    if not resolved.is_dir():
        raise NotADirectoryError(str(resolved))
    return {
        "path": str(resolved),
        "label": resolved.name or str(resolved),
        "kind": "carpeta",
        "removable": False,
        "is_card": _has_card_structure(resolved),
        "parent": None,
        "total_bytes": None,
        "free_bytes": None,
    }
