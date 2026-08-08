"""Operaciones ffmpeg/ffprobe: remuxeo AVCHD -> MP4 sin recompresión de vídeo."""

import re
import shutil
import subprocess
from pathlib import Path

FFMPEG_BIN = "ffmpeg"
FFPROBE_BIN = "ffprobe"


class ToolsMissingError(RuntimeError):
    pass


def check_tools() -> None:
    missing = [b for b in (FFMPEG_BIN, FFPROBE_BIN, "exiftool") if shutil.which(b) is None]
    if missing:
        raise ToolsMissingError(
            "Faltan herramientas en el PATH: " + ", ".join(missing) +
            ". Instálalas con 'brew install ffmpeg exiftool'."
        )


def get_duration_seconds(path: Path) -> float:
    cmd = [
        FFPROBE_BIN, "-v", "error",
        "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1",
        str(path),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    try:
        return float(result.stdout.strip())
    except ValueError:
        return 0.0


def get_audio_codec(path: Path) -> str | None:
    cmd = [
        FFPROBE_BIN, "-v", "error",
        "-select_streams", "a:0",
        "-show_entries", "stream=codec_name",
        "-of", "default=noprint_wrappers=1:nokey=1",
        str(path),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    codec = result.stdout.strip()
    return codec or None


_TIME_RE = re.compile(r"out_time_ms=(\d+)")


def remux_clip(source: Path, dest: Path, transcode_audio: bool, capture_dt=None, progress_cb=None) -> None:
    """Copia el vídeo sin recompresión (stream copy). Si transcode_audio es True y el
    audio no es ya AAC, recodifica solo el audio a AAC para compatibilidad de
    reproducción; el vídeo siempre se copia sin pérdida. Si se indica capture_dt, se
    graba como fecha de creación en los metadatos del MP4 (para que apps como
    Synology Photos, Plex o Emby ordenen por fecha de captura real)."""
    duration = get_duration_seconds(source)
    audio_codec = get_audio_codec(source)

    audio_args = ["-c:a", "copy"]
    if transcode_audio and audio_codec and audio_codec != "aac":
        audio_args = ["-c:a", "aac", "-b:a", "256k"]

    metadata_args = []
    if capture_dt is not None:
        metadata_args = ["-metadata", f"creation_time={capture_dt.strftime('%Y-%m-%dT%H:%M:%S')}"]

    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp_dest = dest.with_suffix(dest.suffix + ".part")

    cmd = [
        FFMPEG_BIN, "-y", "-hide_banner", "-loglevel", "error",
        "-i", str(source),
        "-map", "0:v:0", "-map", "0:a:0?",
        "-c:v", "copy", *audio_args,
        *metadata_args,
        "-movflags", "+faststart",
        "-f", "mp4",
        "-progress", "pipe:1", "-nostats",
        str(tmp_dest),
    ]

    process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    stderr_lines = []
    try:
        for line in process.stdout:
            match = _TIME_RE.search(line)
            if match and progress_cb and duration > 0:
                seconds = int(match.group(1)) / 1_000_000
                progress_cb(min(seconds / duration, 1.0))
    finally:
        stderr_lines = process.stderr.read()
        process.wait()

    if process.returncode != 0:
        tmp_dest.unlink(missing_ok=True)
        raise RuntimeError(f"ffmpeg falló ({process.returncode}): {stderr_lines.strip()}")

    tmp_dest.rename(dest)
    if progress_cb:
        progress_cb(1.0)
