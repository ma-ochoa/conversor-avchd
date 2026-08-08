"""Estabilización de vídeo con vid.stab (dos pasadas: detección + transformación).

A diferencia del remuxeo AVCHD, este paso SÍ recodifica el vídeo (es inevitable para
poder corregir el temblor de la cámara), por eso es una opción independiente y no
forma parte del remuxeo sin pérdida."""

import re
import shutil
import subprocess
import tempfile
from pathlib import Path

from .ffmpeg_ops import get_duration_seconds

_CANDIDATE_BINARIES = [
    "/opt/homebrew/opt/ffmpeg-full/bin/ffmpeg",
    "/usr/local/opt/ffmpeg-full/bin/ffmpeg",
]

_TIME_RE = re.compile(r"out_time_ms=(\d+)")
_ZOOM_RE = re.compile(r"Final zoom:\s*([\d.]+)")
_CONTRAST_RE = re.compile(r"too low contrast", re.IGNORECASE)


class VidstabMissingError(RuntimeError):
    pass


def find_ffmpeg_with_vidstab() -> str:
    for candidate in _CANDIDATE_BINARIES:
        if Path(candidate).exists():
            return candidate
    which = shutil.which("ffmpeg")
    if which:
        result = subprocess.run([which, "-filters"], capture_output=True, text=True, timeout=15)
        if "vidstabdetect" in result.stdout:
            return which
    raise VidstabMissingError(
        "No se encontró un ffmpeg con soporte vid.stab. Instálalo con 'brew install ffmpeg-full'."
    )


def _ffprobe_for(ffmpeg_bin: str) -> str:
    candidate = str(Path(ffmpeg_bin).with_name("ffprobe"))
    return candidate if Path(candidate).exists() else "ffprobe"


def _estimate_frame_count(source: Path, ffmpeg_bin: str, duration: float) -> int:
    cmd = [
        _ffprobe_for(ffmpeg_bin), "-v", "error", "-select_streams", "v:0",
        "-show_entries", "stream=r_frame_rate",
        "-of", "default=noprint_wrappers=1:nokey=1", str(source),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    try:
        num, den = result.stdout.strip().split("/")
        fps = float(num) / float(den)
    except (ValueError, ZeroDivisionError):
        fps = 25.0
    return max(int(round(duration * fps)), 1)


_DEFAULT_VIDEO_BITRATE = 16_000_000
_AUDIO_BITRATE_ESTIMATE = 256_000


def _estimate_source_video_bitrate(source: Path, ffmpeg_bin: str) -> int:
    """Bitrate de vídeo aproximado del original, usado como objetivo para el
    encoder de hardware (que no tiene un modo de calidad constante tipo CRF)."""
    cmd = [
        _ffprobe_for(ffmpeg_bin), "-v", "error",
        "-show_entries", "format=bit_rate",
        "-of", "default=noprint_wrappers=1:nokey=1", str(source),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    try:
        total_bitrate = int(result.stdout.strip())
    except ValueError:
        return _DEFAULT_VIDEO_BITRATE
    return max(total_bitrate - _AUDIO_BITRATE_ESTIMATE, 4_000_000)


def _run_pass(cmd: list, duration: float, progress_start: float, progress_span: float,
              progress_cb, log_path: Path) -> int:
    with open(log_path, "w") as log_file:
        process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=log_file, text=True)
        for line in process.stdout:
            match = _TIME_RE.search(line)
            if match and progress_cb and duration > 0:
                seconds = int(match.group(1)) / 1_000_000
                fraction = progress_start + progress_span * min(seconds / duration, 1.0)
                progress_cb(fraction)
        process.wait()
    return process.returncode


def stabilize_clip(source: Path, dest: Path, progress_cb=None, fast_hw: bool = False) -> dict:
    """Desentrelaza + estabiliza `source` (fichero AVCHD original) y escribe `dest` (.mp4).
    Devuelve estadísticas sobre cuánto ha tenido que corregir/recortar el vídeo.

    fast_hw=True codifica con el encoder de hardware (VideoToolbox) en vez de libx264:
    unas 2 veces más rápido en esa fase, con calidad ligeramente inferior (VMAF ~96/100
    frente a libx264 al mismo bitrate) y solo aporta esa mejora en Apple Silicon con motor
    de vídeo dedicado (M-series recientes, idealmente M5 o superior) — el análisis del
    temblor (la fase que más tarda) no se acelera, así que el ahorro total del proceso es
    modesto (~15%), no proporcional a esa cifra."""
    ffmpeg_bin = find_ffmpeg_with_vidstab()
    duration = get_duration_seconds(source)
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp_dest = dest.with_suffix(dest.suffix + ".part")

    with tempfile.TemporaryDirectory() as tmp:
        tmp_dir = Path(tmp)
        transforms_path = tmp_dir / "transforms.trf"
        detect_log = tmp_dir / "detect.log"
        transform_log = tmp_dir / "transform.log"

        detect_cmd = [
            ffmpeg_bin, "-y", "-hide_banner", "-loglevel", "warning",
            "-i", str(source),
            "-vf", f"yadif=1,vidstabdetect=shakiness=5:accuracy=15:result={transforms_path}",
            "-progress", "pipe:1", "-nostats",
            "-f", "null", "-",
        ]
        rc = _run_pass(detect_cmd, duration, 0.0, 0.5, progress_cb, detect_log)
        if rc != 0:
            raise RuntimeError(f"vidstabdetect falló ({rc}): {detect_log.read_text()[-2000:]}")

        if fast_hw:
            video_bitrate = _estimate_source_video_bitrate(source, ffmpeg_bin)
            encoder_args = ["-c:v", "h264_videotoolbox", "-b:v", str(video_bitrate), "-profile:v", "high"]
        else:
            encoder_args = ["-c:v", "libx264", "-crf", "18", "-preset", "medium"]

        transform_cmd = [
            ffmpeg_bin, "-y", "-hide_banner", "-loglevel", "info",
            "-i", str(source),
            "-vf",
            f"yadif=1,vidstabtransform=input={transforms_path}:smoothing=10:optzoom=1:interpol=bilinear,"
            "unsharp=5:5:0.8:3:3:0.4",
            *encoder_args,
            "-c:a", "copy",
            "-movflags", "+faststart", "-f", "mp4",
            "-progress", "pipe:1", "-nostats",
            str(tmp_dest),
        ]
        rc = _run_pass(transform_cmd, duration, 0.5, 0.5, progress_cb, transform_log)
        if rc != 0:
            tmp_dest.unlink(missing_ok=True)
            raise RuntimeError(f"vidstabtransform falló ({rc}): {transform_log.read_text()[-2000:]}")

        detect_text = detect_log.read_text(errors="ignore")
        transform_text = transform_log.read_text(errors="ignore")
        total_frames = _estimate_frame_count(source, ffmpeg_bin, duration)

    tmp_dest.rename(dest)
    if progress_cb:
        progress_cb(1.0)

    zoom_match = _ZOOM_RE.search(transform_text)
    zoom_percent = round(float(zoom_match.group(1)), 2) if zoom_match else None
    low_contrast_frames = len(_CONTRAST_RE.findall(detect_text))
    confidence_percent = (
        round(100 * (1 - low_contrast_frames / total_frames), 1) if total_frames else None
    )

    return {
        "zoom_percent": zoom_percent,
        "low_contrast_frames": low_contrast_frames,
        "total_frames": total_frames,
        "confidence_percent": confidence_percent,
        "encoder": "h264_videotoolbox (hardware)" if fast_hw else "libx264 (software)",
    }
