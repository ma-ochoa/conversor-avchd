"""Genera y cachea una copia ligera (proxy) de un clip, misma proporción y fps, solo
para que la previsualización de ajustes vaya fluida en el navegador. Nunca se usa para
el resultado final."""

import hashlib
import subprocess
from pathlib import Path

from .ffmpeg_ops import FFMPEG_BIN

PROXY_DIR_NAME = ".proxies"
PROXY_WIDTH = 640


def _proxy_path(root: Path, source: Path) -> Path:
    digest = hashlib.sha1(str(source).encode("utf-8")).hexdigest()[:16]
    return root / PROXY_DIR_NAME / f"{digest}.mp4"


def get_or_create_proxy(root: Path, source: Path) -> Path:
    proxy_path = _proxy_path(root, source)
    if proxy_path.exists() and proxy_path.stat().st_mtime >= source.stat().st_mtime:
        return proxy_path

    proxy_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = proxy_path.with_suffix(".mp4.part")
    cmd = [
        FFMPEG_BIN, "-y", "-hide_banner", "-loglevel", "error",
        "-i", str(source),
        "-map", "0:v:0", "-map", "0:a:0?",
        "-vf", f"yadif=mode=0:deint=interlaced,scale={PROXY_WIDTH}:-2",
        "-c:v", "libx264", "-preset", "ultrafast", "-crf", "28",
        "-c:a", "aac", "-b:a", "96k",
        "-movflags", "+faststart", "-f", "mp4",
        str(tmp_path),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
    if result.returncode != 0 or not tmp_path.exists():
        tmp_path.unlink(missing_ok=True)
        raise RuntimeError(f"No se pudo generar el proxy de {source.name}: {result.stderr.strip()[-500:]}")
    tmp_path.rename(proxy_path)
    return proxy_path
