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


def _almacenamientos(camera) -> list[tuple[str, str]]:
    """(carpeta, nombre legible) de cada almacenamiento que anuncia el móvil.

    En MTP la raíz del dispositivo son sus almacenamientos, pero hay móviles que no los
    exponen como carpetas de `/`: la raíz sale vacía aunque todo el contenido esté ahí,
    un nivel más abajo, colgando de `/store_00010001`. Le pasa al Galaxy S25 (SM-S938B),
    y deja el explorador en blanco con el móvil conectado, desbloqueado y en MTP — es
    decir, con el mismo aspecto que un móvil bloqueado o en «solo carga», que es el
    diagnóstico equivocado al que llevaba.

    Preguntando por los almacenamientos sí aparecen, y de paso traen un nombre que se
    puede enseñar («Almacenamiento interno») en vez del identificador crudo.
    """
    gp = _gphoto()
    salida = []
    for info in gp.check_result(gp.gp_camera_get_storageinfo(camera)):
        base = (getattr(info, "basedir", "") or "").rstrip("/")
        if not base:
            continue
        etiqueta = (getattr(info, "description", "") or "").strip()
        salida.append((base, etiqueta or base.lstrip("/")))
    return salida


def _raices(camera, path: str) -> list[str]:
    """Por dónde empezar a recorrer `path`: normalmente él mismo.

    La excepción es la raíz de un móvil que no anuncia sus almacenamientos como carpetas
    (ver `_almacenamientos`): hay que entrar por cada uno, o el recorrido no ve nada.
    """
    if path.rstrip("/"):
        return [path]
    try:
        if _names(camera.folder_list_folders(path)):
            return [path]
    except Exception:
        pass          # la raíz no se deja listar; se prueba por almacenamiento
    return [base for base, _ in _almacenamientos(camera)] or [path]


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


def device_model() -> str:
    """Modelo que anuncia el propio móvil por MTP, p. ej. `SM-S938B`.

    Lo da el dispositivo sin descargar ni un fichero, y es el mismo identificador que
    llevan dentro los vídeos (`Samsung:SamsungModel`), así que encaja directamente con la
    tabla de cámaras conocidas: `SM-S938B` → «Samsung S25 Ultra».
    """
    def operation(camera):
        return str(camera.get_summary())

    try:
        summary = _retry(operation)
    except MtpError:
        return ""

    for line in summary.splitlines():
        parts = line.split(":", 1)
        # gphoto2 traduce la etiqueta según el idioma del sistema.
        if len(parts) == 2 and parts[0].strip().lower() in ("model", "modelo"):
            return parts[1].strip()
    return ""


def list_folder(path: str = "/", count_files: bool = False) -> dict:
    """Subcarpetas de `path`, y opcionalmente cuántos ficheros tiene.

    El recuento está apagado por defecto porque es caro: listar los ficheros de
    `DCIM/Camera` (3322 en el móvil de prueba) tarda unos 13 s, y pagar eso solo para
    enseñar un número haría que navegar fuese insoportable. Listar las carpetas, en
    cambio, es instantáneo.
    """
    def operation(camera):
        en_raiz = not path.rstrip("/")
        fallo = None
        try:
            folders = _names(camera.folder_list_folders(path))
        except Exception as exc:
            # Que la raíz no se deje listar no es concluyente: hay móviles que solo
            # responden por almacenamiento (ver `_almacenamientos`). Se guarda el error
            # por si al final tampoco hay almacenamientos que enseñar.
            if not en_raiz:
                raise
            folders, fallo = [], exc
        # Sin carpetas en la raíz, los almacenamientos son la única entrada al contenido.
        stores = _almacenamientos(camera) if en_raiz and not folders else []
        if fallo is not None and not stores:
            raise fallo
        files = _names(camera.folder_list_files(path)) if count_files else []
        return folders, files, stores

    folders, filenames, stores = _retry(operation)
    base = path.rstrip("/")

    # Los almacenamientos no pasan por el filtro de ruido: sin ellos no se llega a nada.
    subfolders = [{"name": etiqueta, "path": ruta, "interesting": True}
                  for ruta, etiqueta in stores]
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


def list_files(path: str, recursive: bool = True, limit: int = 0,
               progress_cb=None, extensions: set[str] | None = None,
               skip_noise: bool = True, necesita_info=None) -> list[dict]:
    """Ficheros de medios de `path`, con tamaño y fecha de captura.

    **Recursivo por defecto.** Pedir "los archivos de DCIM" tiene que traer los de
    `DCIM/Camera`, `DCIM/Screenshots` y demás: en DCIM a secas no suele haber nada suelto,
    y una lista vacía ahí no le sirve a nadie.

    El coste está en el primer `folder_list_files` de cada carpeta (13 s para las 3322
    fotos de Camera); después, leer los metadatos de cada fichero sale gratis porque
    gphoto2 deja la carpeta en caché.

    `extensions` cambia qué se considera un fichero interesante; por defecto, fotos y
    vídeos. WhatsApp lo usa para llevarse también notas de voz (.opus) y documentos, que
    no son medios de cámara pero sí parte de la copia de seguridad. `skip_noise` se apaga
    para bajar por rutas que el explorador esconde a propósito, como `Android/`.

    **`necesita_info` es lo que hace viable inventariar un WhatsApp entero.** Listar los
    nombres de una carpeta es una sola llamada; pedir tamaño y fecha es **una llamada por
    fichero**, y con 53.000 ficheros eso son 53.000 viajes por USB — decenas de minutos.
    Quien llama puede decidir, por el nombre, si de verdad le hacen falta: WhatsApp lleva
    la fecha dentro del nombre (`IMG-20260819-WA0012.jpg`) y no necesita preguntar. Por
    defecto se piden siempre, que es lo que espera el importador de fotos de cámara.
    """
    entries: list[dict] = []
    allowed = extensions if extensions is not None else (_PHOTO_EXTS | _VIDEO_EXTS)

    def scan(camera, folder):
        try:
            names = _names(camera.folder_list_files(folder))
        except Exception:
            return
        for name in names:
            suffix = Path(name).suffix.lower()
            if allowed and suffix not in allowed:
                continue
            size = captured = None
            if necesita_info is None or necesita_info(name):
                try:
                    info = camera.file_get_info(folder, name)
                    size = getattr(info.file, "size", None)
                    mtime = getattr(info.file, "mtime", 0)
                    if mtime:
                        captured = datetime.fromtimestamp(mtime).isoformat()
                except Exception:
                    pass
            entries.append({
                "name": name,
                "folder": folder,
                "path": f"{folder.rstrip('/')}/{name}",
                "category": "video" if suffix in _VIDEO_EXTS else "photo",
                "size": size,
                "captured": captured,
            })
            if limit and len(entries) >= limit:
                return

        if not recursive:
            return
        try:
            children = _names(camera.folder_list_folders(folder))
        except Exception:
            return
        for child in sorted(children, key=str.lower):
            if (skip_noise and child.lower() in _NOISE) or (limit and len(entries) >= limit):
                continue
            if progress_cb:
                progress_cb(f"{folder.rstrip('/')}/{child}", len(entries))
            scan(camera, f"{folder.rstrip('/')}/{child}")

    def operation(camera):
        if progress_cb:
            progress_cb(path, 0)
        for raiz in _raices(camera, path):
            scan(camera, raiz)
        return entries

    _retry(operation)
    entries.sort(key=lambda e: e["captured"] or "", reverse=True)
    return entries


def preview(folder: str, name: str) -> bytes:
    """Miniatura que el propio móvil tiene guardada para ese fichero.

    Es lo que hace viable la vista rápida sobre un móvil: la previsualización pesa unas
    decenas de KB y llega en centésimas de segundo, frente a los megas de la foto entera.
    """
    gp = _gphoto()

    def operation(camera):
        camera_file = camera.file_get(folder, name, gp.GP_FILE_TYPE_PREVIEW)
        return bytes(memoryview(camera_file.get_data_and_size()))

    return _retry(operation)


def fetch(folder: str, name: str, target: Path, expected_size: int | None = None) -> int:
    """Descarga **un** fichero del móvil a su ruta final. Devuelve los bytes escritos.

    Se escribe a `.parcial` y se renombra al terminar, igual que `copier.py` hace con las
    tarjetas: si se desconecta el cable a mitad, en el destino no queda un fichero
    truncado con aspecto de completo.
    """
    gp = _gphoto()
    target = Path(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    partial = target.with_name(target.name + ".parcial")

    def operation(camera):
        camera_file = camera.file_get(folder, name, gp.GP_FILE_TYPE_NORMAL)
        camera_file.save(str(partial))
        return partial

    try:
        _retry(operation)
        written = partial.stat().st_size
        # No hay checksum del lado del móvil con el que comparar, así que el tamaño
        # exacto que anuncia MTP es la única verificación posible.
        if expected_size and written != expected_size:
            partial.unlink(missing_ok=True)
            raise MtpError(
                f"{name}: se esperaban {expected_size} bytes y llegaron {written}."
            )
        partial.replace(target)
        return written
    except Exception:
        partial.unlink(missing_ok=True)
        raise
