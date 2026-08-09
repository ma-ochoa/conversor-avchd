"""Recompresión genérica: para formatos que no admiten remuxeo sin pérdida (.avi,
.mkv, .wmv, .3gp) y para reducir el tamaño de clips ya convertidos (compartir por
WhatsApp/email, etc.). A diferencia del remuxeo, esto SIEMPRE recodifica el vídeo."""

import re
import subprocess
from pathlib import Path

from .ffmpeg_ops import get_duration_seconds
from .stabilize import find_ffmpeg_with_vidstab as find_ffmpeg_full

_TIME_RE = re.compile(r"out_time_ms=(\d+)")

QUALITY_PRESETS = {
    "alta": 20,
    "media": 23,
    "baja": 28,
}

# Resoluciones máximas típicas para reducir tamaño manteniendo proporción.
MAX_WIDTH_PRESETS = {
    "original": None,
    "1080p": 1920,
    "720p": 1280,
    "480p": 854,
}


def _ffprobe_for(ffmpeg_bin: str) -> str:
    candidate = str(Path(ffmpeg_bin).with_name("ffprobe"))
    return candidate if Path(candidate).exists() else "ffprobe"


def _source_width(source: Path, ffmpeg_bin: str) -> int:
    cmd = [
        _ffprobe_for(ffmpeg_bin), "-v", "error", "-select_streams", "v:0",
        "-show_entries", "stream=width",
        "-of", "default=noprint_wrappers=1:nokey=1", str(source),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    try:
        return int(result.stdout.strip())
    except ValueError:
        return 0


def recompress_clip(source: Path, dest: Path, quality: str = "media",
                     max_width: str = "original", progress_cb=None) -> dict:
    """Recodifica `source` a `dest` (.mp4, H.264/AAC). `quality` controla el CRF
    (alta/media/baja); `max_width` limita la resolución (original/1080p/720p/480p) —
    nunca amplía un vídeo más pequeño que el tope elegido."""
    ffmpeg_bin = find_ffmpeg_full()
    duration = get_duration_seconds(source)
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp_dest = dest.with_suffix(dest.suffix + ".part")

    crf = QUALITY_PRESETS.get(quality, QUALITY_PRESETS["media"])
    target_width = MAX_WIDTH_PRESETS.get(max_width)

    vf_parts = ["yadif=mode=0:deint=interlaced"]
    if target_width:
        source_width = _source_width(source, ffmpeg_bin)
        if source_width and source_width > target_width:
            vf_parts.append(f"scale={target_width}:-2")
    vf_parts.append("format=yuv420p")

    cmd = [
        ffmpeg_bin, "-y", "-hide_banner", "-loglevel", "error",
        "-i", str(source),
        "-map", "0:v:0", "-map", "0:a:0?",
        "-vf", ",".join(vf_parts),
        "-c:v", "libx264", "-crf", str(crf), "-preset", "medium",
        "-c:a", "aac", "-b:a", "160k",
        "-movflags", "+faststart", "-f", "mp4",
        "-progress", "pipe:1", "-nostats",
        str(tmp_dest),
    ]

    process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    for line in process.stdout:
        match = _TIME_RE.search(line)
        if match and progress_cb and duration > 0:
            seconds = int(match.group(1)) / 1_000_000
            progress_cb(min(seconds / duration, 1.0))
    stderr_text = process.stderr.read()
    process.wait()

    if process.returncode != 0:
        tmp_dest.unlink(missing_ok=True)
        raise RuntimeError(f"Recompresión falló ({process.returncode}): {stderr_text.strip()[-2000:]}")

    tmp_dest.rename(dest)
    if progress_cb:
        progress_cb(1.0)

    original_size = source.stat().st_size
    new_size = dest.stat().st_size
    return {
        "quality": quality,
        "max_width": max_width,
        "original_size": original_size,
        "new_size": new_size,
        "reduction_percent": round(100 * (1 - new_size / original_size), 1) if original_size else None,
    }
