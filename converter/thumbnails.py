"""Genera y cachea miniaturas de los clips ya convertidos, para la cuadrícula de montaje."""

import hashlib
import subprocess
from pathlib import Path

from .config import resolve_output_base
from .ffmpeg_ops import FFMPEG_BIN

THUMBS_DIR_NAME = ".miniaturas"


def _thumb_cache_path(root: Path, clip_path: Path) -> Path:
    digest = hashlib.sha1(str(clip_path).encode("utf-8")).hexdigest()[:16]
    return resolve_output_base(root) / THUMBS_DIR_NAME / f"{digest}.jpg"


def get_or_create_thumbnail(root: Path, clip_path: Path, at_seconds: float = 1.0) -> Path:
    thumb_path = _thumb_cache_path(root, clip_path)
    if thumb_path.exists() and thumb_path.stat().st_mtime >= clip_path.stat().st_mtime:
        return thumb_path

    thumb_path.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        FFMPEG_BIN, "-y", "-hide_banner", "-loglevel", "error",
        "-ss", str(at_seconds), "-i", str(clip_path),
        "-frames:v", "1", "-vf", "scale=320:-1",
        "-q:v", "4",
        str(thumb_path),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    if result.returncode != 0 or not thumb_path.exists():
        raise RuntimeError(f"No se pudo generar la miniatura de {clip_path.name}: {result.stderr.strip()[-500:]}")
    return thumb_path
