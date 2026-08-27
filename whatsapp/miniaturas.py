"""Miniaturas de los medios ya copiados, para que la galería sea usable.

**Por qué hace falta.** Una conversación de las grandes tiene miles de fotos, y cada una
es un JPEG de 1824×1026 que la rejilla pinta en una celda de 140 px. Sirviendo los
originales, cargar 400 celdas obligaba al navegador a descargar y decodificar más de 100
megapíxeles: a los doce segundos solo habían aparecido 63 de 400. Con miniaturas de 320 px
cada celda pesa unas cien veces menos.

**Se cachean por contenido, no por ruta.** La semilla del nombre incluye tamaño y fecha de
modificación, así que si un fichero cambia se regenera solo, y si se borra y vuelve a
copiarse idéntico se reaprovecha la que ya había.

**Duplicación deliberada con `importer/thumbs.py`**, igual que en el resto del paquete:
`whatsapp/` no importa nada de `importer/` salvo por `dispositivo.py`, para poder
extraerlo entero como aplicación aparte. Si se toca la técnica de aquí, mirar también
allí. Ver README.md.
"""

import hashlib
import platform
import subprocess
from pathlib import Path

from .config import DIR_DATOS

CACHE = DIR_DATOS / "miniaturas"

# 320 px de lado mayor: suficiente para una celda de rejilla incluso en pantallas densas,
# y unas cien veces más ligero que el original.
_LADO = 320

_VIDEO = {".mp4", ".3gp", ".mov", ".mkv", ".avi", ".webm"}
_HEIC = {".heic", ".heif"}


class SinMiniatura(RuntimeError):
    """No se ha podido generar una miniatura de ese fichero."""


def _ruta_cache(origen: Path) -> Path:
    try:
        st = origen.stat()
        semilla = f"{origen}|{st.st_size}|{int(st.st_mtime)}"
    except OSError:
        semilla = str(origen)
    return CACHE / f"{hashlib.sha1(semilla.encode('utf-8')).hexdigest()[:16]}.jpg"


def _corre(cmd: list[str]) -> bool:
    try:
        return subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                              timeout=30).returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


def _con_sips(origen: Path, destino: Path) -> bool:
    """macOS decodifica HEIC de serie; ffmpeg a menudo no lo lleva compilado."""
    return platform.system() == "Darwin" and _corre(
        ["sips", "-Z", str(_LADO), "-s", "format", "jpeg", str(origen), "--out", str(destino)]
    ) and destino.exists()


def _con_ffmpeg(origen: Path, destino: Path, es_video: bool) -> bool:
    cmd = ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error"]
    if es_video:
        # Un fotograma del segundo 1: el 0 suele ser negro en los vídeos de WhatsApp.
        cmd += ["-ss", "1"]
    cmd += ["-i", str(origen), "-frames:v", "1",
            # `-2` mantiene la proporción y fuerza altura par, que exige el codificador.
            "-vf", f"scale={_LADO}:-2", "-q:v", "5", str(destino)]
    if _corre(cmd) and destino.exists() and destino.stat().st_size:
        return True
    # Un vídeo más corto que el punto de búsqueda deja a ffmpeg sin fotograma: se
    # reintenta desde el principio antes de darlo por perdido.
    if es_video:
        destino.unlink(missing_ok=True)
        return _corre(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
                       "-i", str(origen), "-frames:v", "1",
                       "-vf", f"scale={_LADO}:-2", "-q:v", "5", str(destino)]) \
            and destino.exists()
    return False


def miniatura(ruta: str | Path) -> Path:
    """Devuelve la ruta de la miniatura, generándola la primera vez.

    Lanza `SinMiniatura` para lo que no tiene imagen posible (un PDF, un .opus): quien
    llama decide qué icono enseñar, en vez de recibir una imagen rota.
    """
    origen = Path(ruta).expanduser()
    if not origen.is_file():
        raise SinMiniatura(f"No existe: {origen}")

    cache = _ruta_cache(origen)
    if cache.exists() and cache.stat().st_size:
        return cache

    CACHE.mkdir(parents=True, exist_ok=True)
    sufijo = origen.suffix.lower()

    if sufijo in _HEIC and _con_sips(origen, cache):
        return cache
    if _con_ffmpeg(origen, cache, es_video=sufijo in _VIDEO):
        return cache

    cache.unlink(missing_ok=True)
    raise SinMiniatura(f"No se pudo generar una miniatura de {origen.name}")


def limpia_cache() -> int:
    """Borra la caché entera. Devuelve cuántos ficheros ha quitado.

    Es seguro en cualquier momento: todo lo que hay aquí se puede regenerar del original.
    """
    if not CACHE.is_dir():
        return 0
    quitados = 0
    for f in CACHE.glob("*.jpg"):
        try:
            f.unlink()
            quitados += 1
        except OSError:
            continue
    return quitados


def tamano_cache() -> dict:
    if not CACHE.is_dir():
        return {"ficheros": 0, "bytes": 0}
    ficheros = list(CACHE.glob("*.jpg"))
    return {"ficheros": len(ficheros),
            "bytes": sum(f.stat().st_size for f in ficheros if f.exists())}
