"""Miniaturas del contenido del origen, para verlo antes de decidir qué importar.

Las cachea en `~/.conversor-importador/miniaturas/` y no en la tarjeta: la tarjeta puede
estar protegida contra escritura, montada en solo lectura, o desaparecer en cualquier
momento, y en todo caso no conviene escribir nada en ella antes de haber copiado.
"""

import hashlib
import platform
import subprocess
from pathlib import Path

from .config import CACHE_DIR
from .media import RAW_EXTS, VIDEO_EXTS

_HEIC_EXTS = {".heic", ".heif"}
_SIZE = 320


def _cache_path(source: Path) -> Path:
    try:
        stat = source.stat()
        seed = f"{source}|{stat.st_size}|{int(stat.st_mtime)}"
    except OSError:
        seed = str(source)
    return CACHE_DIR / f"{hashlib.sha1(seed.encode('utf-8')).hexdigest()[:16]}.jpg"


def _run(cmd: list[str], stdout=None) -> bool:
    try:
        result = subprocess.run(cmd, stdout=stdout or subprocess.DEVNULL,
                                stderr=subprocess.DEVNULL, timeout=60)
        return result.returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


def _from_raw_preview(source: Path, dest: Path) -> bool:
    """Los RAW llevan dentro un JPEG de previsualización: extraerlo es inmediato,
    frente a revelar el RAW entero, que necesitaría un decodificador aparte."""
    for tag in ("-PreviewImage", "-JpgFromRaw", "-ThumbnailImage"):
        with open(dest, "wb") as out:
            if _run(["exiftool", "-b", tag, str(source)], stdout=out) and dest.stat().st_size > 0:
                return True
    dest.unlink(missing_ok=True)
    return False


def _from_sips(source: Path, dest: Path) -> bool:
    """macOS decodifica HEIC de serie; ffmpeg a menudo no lo lleva compilado."""
    return platform.system() == "Darwin" and _run(
        ["sips", "-Z", str(_SIZE), "-s", "format", "jpeg", str(source), "--out", str(dest)]
    ) and dest.exists()


def _from_ffmpeg(source: Path, dest: Path, is_video: bool) -> bool:
    cmd = ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error"]
    if is_video:
        cmd += ["-ss", "1"]
    cmd += ["-i", str(source), "-frames:v", "1", "-vf", f"scale={_SIZE}:-2", "-q:v", "5", str(dest)]
    return _run(cmd) and dest.exists()


def get_phone_thumbnail(mtp_path: str) -> Path:
    """Miniatura de un fichero que está en el móvil, no en disco.

    Se cachea igual que las demás: la previsualización se pide una sola vez al móvil, y
    las siguientes cargas de la cuadrícula salen del disco sin volver a tocar el USB.
    """
    from . import mtp

    cached = CACHE_DIR / (hashlib.sha1(mtp_path.encode()).hexdigest()[:16] + ".jpg")
    if cached.exists() and cached.stat().st_size > 0:
        return cached

    folder, _, name = mtp_path.rstrip("/").rpartition("/")
    data = mtp.preview(folder, name)
    if not data:
        raise FileNotFoundError(mtp_path)

    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cached.write_bytes(data)
    return cached


def get_thumbnail(source_path: str) -> Path:
    source = Path(source_path).expanduser()
    if not source.is_file():
        raise FileNotFoundError(source_path)

    cached = _cache_path(source)
    if cached.exists() and cached.stat().st_size > 0:
        return cached

    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    suffix = source.suffix.lower()

    if suffix in RAW_EXTS:
        if _from_raw_preview(source, cached):
            # El preview embebido viene a resolución completa: reducirlo evita mandar
            # varios MB al navegador por cada miniatura de la cuadrícula.
            shrunk = cached.with_name(cached.stem + ".small.jpg")
            if _from_ffmpeg(cached, shrunk, is_video=False):
                shrunk.replace(cached)
            return cached
    elif suffix in _HEIC_EXTS:
        if _from_sips(source, cached):
            return cached

    if _from_ffmpeg(source, cached, is_video=suffix in VIDEO_EXTS):
        return cached
    if _from_sips(source, cached):
        return cached

    cached.unlink(missing_ok=True)
    raise RuntimeError(f"No se pudo generar la vista previa de {source.name}")
