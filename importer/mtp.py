"""Acceso al contenido de un móvil por MTP, con su estructura de carpetas real.

**Por qué existe esto y no vale Captura de Imagen**: un móvil en modo PTP ("Transferencia
de imágenes") expone sus fotos como una lista plana sin carpetas, todo mezclado — la
cámara junto a lo descargado de Telegram, de WhatsApp y las capturas de pantalla. Así no
se puede elegir qué importar. En modo **MTP** ("Transferencia de archivos") el móvil
expone el árbol de verdad y se puede entrar en `DCIM/Camera` dejando el resto fuera.

Dos decisiones que vienen de medir sobre un Galaxy S25 real:

1. **Se usan los bindings de Python, no el ejecutable `gphoto2`.** Cada invocación del
   programa renegocia la conexión MTP entera: 12-16 s *por carpeta*, lo que hace la
   navegación inservible. Con una sesión abierta, conectar cuesta 0,3 s y listar una
   carpeta 0,00-0,05 s.
2. **Se navega bajo demanda, nunca el móvil entero.** Recorrer todo tarda y acaba
   abortando dentro de `Android/`, que tiene cientos de carpetas de aplicaciones.

**El estorbo de macOS**: la interfaz MTP se anuncia con clase USB 6 (Still Image), así que
el sistema le adjudica `ptpcamerad` aunque el móvil esté en modo MTP, y entonces la
interfaz no se puede reclamar. Hay que **matarlo** — suspenderlo con `-STOP` no sirve,
porque el proceso congelado conserva abierto su descriptor de la interfaz. `launchd` lo
relanza solo cuando el sistema vuelva a necesitarlo.
"""

import subprocess
import threading
import time
from datetime import datetime
from pathlib import Path

# Demonios de macOS que retienen la interfaz USB del móvil.
_BLOCKING_DAEMONS = ("ptpcamerad", "mscamerad-xpc")

# Carpetas de sistema y de servicio que solo estorban al elegir de dónde importar.
_NOISE = {
    "android", "log", ".thumbnails", ".aceself", ".gs", ".gs_fs0", "smartswitch",
    "notifications", "ringtones", "alarms", "audiobooks", "podcasts", "recordings",
    "music", "documents",
}

# Carpetas que casi siempre son lo que se busca: se marcan para poder destacarlas.
_INTERESTING = {"dcim", "camera", "pictures", "movies", "expert raw", "dcim/camera"}

_PHOTO_EXTS = {".jpg", ".jpeg", ".png", ".heic", ".heif", ".dng", ".webp"}
_VIDEO_EXTS = {".mp4", ".mov", ".3gp", ".mkv", ".avi", ".m4v"}

_lock = threading.RLock()
_session = None
_session_used = 0.0
# Tras un rato sin usarla, la sesión se cierra: dejarla abierta impide que Fotos o
# Captura de Imagen vuelvan a hablar con el móvil.
_IDLE_TIMEOUT = 120.0


class MtpError(RuntimeError):
    pass


class MtpUnavailable(MtpError):
    """Falta la librería: es un problema de instalación, no de uso."""


def _gphoto():
    try:
        import gphoto2
    except ImportError as exc:
        raise MtpUnavailable(
            "Para leer las carpetas del móvil hace falta gphoto2. Instálalo con:\n"
            "    brew install libgphoto2\n"
            "    pip install gphoto2"
        ) from exc
    return gphoto2


def available() -> bool:
    try:
        _gphoto()
        return True
    except MtpUnavailable:
        return False


def _release_device() -> None:
    killed = False
    for name in _BLOCKING_DAEMONS:
        if subprocess.run(["killall", name], capture_output=True).returncode == 0:
            killed = True
    if killed:
        time.sleep(0.3)   # dar tiempo al kernel a cerrar los descriptores


def _explain(exc: Exception) -> str:
    text = str(exc).lower()
    if "could not claim" in text or "-53" in text:
        return (
            "macOS tiene el móvil reservado para su servicio de cámara. Comprueba que el "
            "móvil está en modo «Transferencia de archivos (MTP)» y no en «Transferencia "
            "de imágenes (PTP)»: en PTP el sistema lo retiene siempre, y además no muestra "
            "las carpetas."
        )
    if "could not find" in text or "-105" in text:
        return "Esa carpeta ya no existe en el móvil. Vuelve a cargar el listado."
    if "no camera" in text or "-52" in text or "-1" in text:
        return (
            "No se ha detectado ningún móvil. Comprueba que está conectado por cable, "
            "desbloqueado, y en modo «Transferencia de archivos (MTP)»."
        )
    return str(exc)


def _connect():
    """Sesión abierta con el móvil, reutilizada entre llamadas."""
    global _session, _session_used
    gp = _gphoto()

    with _lock:
        if _session is not None and time.monotonic() - _session_used > _IDLE_TIMEOUT:
            close()

        if _session is None:
            _release_device()
            try:
                camera = gp.Camera()
                camera.init()
            except Exception as exc:
                raise MtpError(_explain(exc)) from exc
            _session = camera

        _session_used = time.monotonic()
        return _session


def close() -> None:
    global _session
    with _lock:
        if _session is not None:
            try:
                _session.exit()
            except Exception:
                pass
            _session = None


def _retry(operation):
    """Ejecuta `operation(camera)`, reconectando una vez si la sesión se había caído.

    Desenchufar y volver a enchufar el móvil, o que `ptpcamerad` recupere el dispositivo,
    dejan la sesión inservible sin avisar hasta la siguiente operación.
    """
    with _lock:
        try:
            return operation(_connect())
        except MtpError:
            raise
        except Exception:
            close()
            try:
                return operation(_connect())
            except MtpError:
                raise
            except Exception as exc:
                raise MtpError(_explain(exc)) from exc


def _names(camera_list) -> list[str]:
    return [camera_list.get_name(i) for i in range(len(camera_list))]


def detect() -> list[dict]:
    """Móviles que se pueden abrir ahora mismo. Lista vacía si no hay ninguno."""
    if not available():
        return []
    gp = _gphoto()
    try:
        _release_device()
        cameras = gp.Camera.autodetect()
        return [{"model": cameras.get_name(i), "port": cameras.get_value(i)}
                for i in range(len(cameras))]
    except Exception:
        return []


def list_folder(path: str = "/", count_files: bool = False) -> dict:
    """Subcarpetas de `path`, y opcionalmente cuántos ficheros tiene.

    El recuento está apagado por defecto porque es caro: listar los ficheros de
    `DCIM/Camera` (3322 en el móvil de prueba) tarda unos 13 s, y pagar eso solo para
    enseñar un número haría que navegar fuese insoportable. Listar las carpetas, en
    cambio, es instantáneo.
    """
    def operation(camera):
        folders = _names(camera.folder_list_folders(path))
        files = _names(camera.folder_list_files(path)) if count_files else []
        return folders, files

    folders, filenames = _retry(operation)
    base = path.rstrip("/")

    subfolders = []
    for name in sorted(folders, key=str.lower):
        if name.lower() in _NOISE:
            continue
        child = f"{base}/{name}" if base else f"/{name}"
        subfolders.append({
            "name": name,
            "path": child,
            "interesting": name.lower() in _INTERESTING,
        })

    return {
        "path": path,
        "parent": base.rsplit("/", 1)[0] if "/" in base.strip("/") else ("/" if base else ""),
        "folders": subfolders,
        # None = no se ha contado (no que esté vacía), que la interfaz distingue.
        "file_count": len(filenames) if count_files else None,
    }


def list_files(path: str, with_details: bool = True, limit: int = 0) -> list[dict]:
    """Ficheros de medios de `path`, con tamaño y fecha de captura.

    `file_get_info` es una llamada por fichero: en una carpeta con miles de fotos eso son
    varios minutos. Con `with_details=False` solo se devuelven los nombres, que es lo que
    basta para contar y para elegir.
    """
    def operation(camera):
        names = _names(camera.folder_list_files(path))
        if limit:
            names = names[:limit]
        if not with_details:
            return [(name, None) for name in names]
        details = []
        for name in names:
            try:
                details.append((name, camera.file_get_info(path, name)))
            except Exception:
                details.append((name, None))
        return details

    entries = []
    for name, info in _retry(operation):
        suffix = Path(name).suffix.lower()
        if suffix not in _PHOTO_EXTS and suffix not in _VIDEO_EXTS:
            continue
        entry = {
            "name": name,
            "path": f"{path.rstrip('/')}/{name}",
            "category": "video" if suffix in _VIDEO_EXTS else "photo",
            "size": None,
            "captured": None,
        }
        if info is not None:
            entry["size"] = getattr(info.file, "size", None)
            mtime = getattr(info.file, "mtime", 0)
            if mtime:
                entry["captured"] = datetime.fromtimestamp(mtime).isoformat()
        entries.append(entry)

    entries.sort(key=lambda e: e["captured"] or "", reverse=True)
    return entries


def download(folder: str, names: list[str], destination: Path, progress_cb=None) -> list[Path]:
    """Descarga ficheros concretos de una carpeta del móvil al disco.

    De uno en uno a propósito: permite informar del progreso y que un fichero ilegible no
    tumbe toda la importación.
    """
    gp = _gphoto()
    destination = Path(destination)
    destination.mkdir(parents=True, exist_ok=True)
    saved = []

    for index, name in enumerate(names, start=1):
        target = destination / name
        try:
            def operation(camera, name=name, target=target):
                camera_file = camera.file_get(folder, name, gp.GP_FILE_TYPE_NORMAL)
                # Se escribe a un temporal y se renombra: una desconexión a mitad no debe
                # dejar un fichero truncado con aspecto de completo (mismo criterio que
                # `copier.py` para las tarjetas).
                partial = target.with_name(target.name + ".parcial")
                camera_file.save(str(partial))
                partial.replace(target)
                return target

            _retry(operation)
            if target.is_file():
                saved.append(target)
        except Exception:
            pass
        if progress_cb:
            progress_cb(index, len(names), name)

    return saved
