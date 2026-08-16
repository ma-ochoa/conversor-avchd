"""Estabilización de vídeo con vid.stab (dos pasadas: detección + transformación).

A diferencia del remuxeo, este paso SÍ recodifica el vídeo (es inevitable para poder
corregir el temblor de la cámara), por eso es una opción independiente y no forma parte
del remuxeo sin pérdida.

El resultado del análisis (pase 1) se cachea por clip: si solo cambian los parámetros
del pase 2 (suavizado, zoom) no hace falta repetir el análisis, que es la parte más
lenta — especialmente notable en 4K."""

import hashlib
import json
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

from . import manifest
from .config import resolve_output_base
from .ffmpeg_ops import get_duration_seconds

_CANDIDATE_BINARIES = [
    "/opt/homebrew/opt/ffmpeg-full/bin/ffmpeg",
    "/usr/local/opt/ffmpeg-full/bin/ffmpeg",
]

_TIME_RE = re.compile(r"out_time_ms=(\d+)")
_ZOOM_RE = re.compile(r"Final zoom:\s*([\d.]+)")
_CONTRAST_RE = re.compile(r"too low contrast", re.IGNORECASE)

CACHE_DIR_NAME = ".vidstab_cache"

ZOOM_AUTO_STATIC = "auto_static"
ZOOM_AUTO_DYNAMIC = "auto_dynamic"
ZOOM_MANUAL = "manual"


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


def _cache_paths(root: Path, source: Path, shakiness: int, accuracy: int) -> tuple:
    key = f"{source}|{shakiness}|{accuracy}"
    digest = hashlib.sha1(key.encode("utf-8")).hexdigest()[:20]
    cache_dir = resolve_output_base(root) / CACHE_DIR_NAME
    return cache_dir / f"{digest}.trf", cache_dir / f"{digest}.json"


def _path_cache_file(root: Path, source: Path, shakiness: int, accuracy: int) -> Path:
    trf_path, _ = _cache_paths(root, source, shakiness, accuracy)
    return trf_path.with_suffix(".path.json")


def _ensure_transforms(root: Path, source: Path, ffmpeg_bin: str, shakiness: int, accuracy: int,
                        duration: float, progress_cb, progress_start: float, progress_span: float,
                        log_path: Path) -> tuple:
    """Reutiliza el análisis (.trf) si ya existe uno válido para este clip y estos
    parámetros de detección; si no, lo genera. Devuelve (ruta_trf, stats_deteccion, del_cache)."""
    trf_path, meta_path = _cache_paths(root, source, shakiness, accuracy)
    source_size = source.stat().st_size

    if trf_path.exists() and meta_path.exists():
        try:
            meta = json.loads(meta_path.read_text())
        except (json.JSONDecodeError, OSError):
            meta = None
        if meta and meta.get("source_size") == source_size:
            if progress_cb:
                progress_cb(progress_start + progress_span)
            return trf_path, meta["stats"], True

    trf_path.parent.mkdir(parents=True, exist_ok=True)
    detect_cmd = [
        ffmpeg_bin, "-y", "-hide_banner", "-loglevel", "warning",
        "-i", str(source),
        "-vf",
        f"yadif=mode=1:deint=interlaced,"
        f"vidstabdetect=shakiness={shakiness}:accuracy={accuracy}:result={trf_path}",
        "-progress", "pipe:1", "-nostats",
        "-f", "null", "-",
    ]
    rc = _run_pass(detect_cmd, duration, progress_start, progress_span, progress_cb, log_path)
    if rc != 0:
        raise RuntimeError(f"vidstabdetect falló ({rc}): {log_path.read_text()[-2000:]}")

    detect_text = log_path.read_text(errors="ignore")
    total_frames = _estimate_frame_count(source, ffmpeg_bin, duration)
    low_contrast_frames = len(_CONTRAST_RE.findall(detect_text))
    confidence_percent = (
        round(100 * (1 - low_contrast_frames / total_frames), 1) if total_frames else None
    )
    stats = {
        "low_contrast_frames": low_contrast_frames,
        "total_frames": total_frames,
        "confidence_percent": confidence_percent,
    }
    meta_path.write_text(json.dumps({"source_size": source_size, "stats": stats}))
    return trf_path, stats, False


def ensure_analysis(root: Path, source: Path, shakiness: int = 5, accuracy: int = 15,
                     progress_cb=None) -> dict:
    """API pública: se asegura de que existe el análisis (detección) para este clip y
    estos parámetros, reutilizando la caché si es válida. No genera ningún vídeo."""
    ffmpeg_bin = find_ffmpeg_with_vidstab()
    duration = get_duration_seconds(source)
    with tempfile.TemporaryDirectory() as tmp:
        log_path = Path(tmp) / "detect.log"
        trf_path, stats, from_cache = _ensure_transforms(
            root, source, ffmpeg_bin, shakiness, accuracy, duration, progress_cb, 0.0, 1.0, log_path,
        )
    return {
        "trf_path": trf_path, "stats": stats, "reused": from_cache,
        "ffmpeg_bin": ffmpeg_bin, "duration": duration,
    }


def has_cached_analysis(root: Path, source: Path, shakiness: int = 5, accuracy: int = 15) -> bool:
    """Comprueba si ya existe un análisis (pase 1) válido en caché para este clip y
    estos parámetros de detección, sin ejecutar ffmpeg. Pensado para el escaneo, que
    recorre muchos clips y no puede permitirse lanzar un proceso por cada uno."""
    trf_path, meta_path = _cache_paths(root, source.resolve(), shakiness, accuracy)
    if not (trf_path.exists() and meta_path.exists()):
        return False
    try:
        meta = json.loads(meta_path.read_text())
    except (json.JSONDecodeError, OSError):
        return False
    try:
        return meta.get("source_size") == source.stat().st_size
    except OSError:
        return False


def save_stabilize_draft(root: Path, source: Path, params: dict) -> dict:
    """Guarda los ajustes de estabilización elegidos por el usuario para este clip
    (shakiness, accuracy, smoothing, zoom_mode, zoom_percent), sin necesidad de haber
    renderizado (ni siquiera analizado) todavía el vídeo. Es un borrador independiente
    tanto de la caché de análisis (.trf) como del manifiesto de vídeos ya renderizados,
    para poder probar, guardar o descartar ajustes libremente."""
    entry = {
        "shakiness": int(params.get("shakiness", 5)),
        "accuracy": int(params.get("accuracy", 15)),
        "smoothing": int(params.get("smoothing", 10)),
        "zoom_mode": params.get("zoom_mode", ZOOM_AUTO_STATIC),
        "zoom_percent": float(params.get("zoom_percent", 0.0)),
    }
    manifest.record_entry(root, CACHE_DIR_NAME, str(source.resolve()), entry)
    return entry


def load_stabilize_draft(root: Path, source: Path) -> dict | None:
    """Devuelve los ajustes guardados para este clip, o None si no se ha guardado
    ninguno todavía."""
    drafts = manifest.load_manifest(root, CACHE_DIR_NAME)
    return drafts.get(str(source.resolve()))


def discard_stabilize_draft(root: Path, source: Path) -> None:
    manifest.remove_entry(root, CACHE_DIR_NAME, str(source.resolve()))


def _parse_raw_path(dump_path: Path) -> list:
    frames = []
    with open(dump_path) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            parts = line.split()
            if len(parts) < 4:
                continue
            try:
                frames.append({
                    "dx": float(parts[1]),
                    "dy": float(parts[2]),
                    "angle": float(parts[3]),
                })
            except ValueError:
                continue
    return frames


def _probe_video_info(source: Path, ffmpeg_bin: str) -> dict:
    cmd = [
        _ffprobe_for(ffmpeg_bin), "-v", "error", "-select_streams", "v:0",
        "-show_entries", "stream=width,height,r_frame_rate",
        "-of", "default=noprint_wrappers=1", str(source),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    info = {}
    for line in result.stdout.splitlines():
        if "=" in line:
            key, _, value = line.partition("=")
            info[key] = value
    fps = 25.0
    if "/" in info.get("r_frame_rate", ""):
        try:
            num, den = info["r_frame_rate"].split("/")
            fps = float(num) / float(den) if float(den) else 25.0
        except ValueError:
            pass
    return {
        "width": int(info.get("width", 0) or 0),
        "height": int(info.get("height", 0) or 0),
        "fps": fps,
    }


def get_preview_analysis(root: Path, source: Path, shakiness: int = 5, accuracy: int = 15,
                          progress_cb=None) -> dict:
    """Devuelve la trayectoria de cámara (desplazamiento x/y y ángulo por fotograma,
    SIN suavizar) para poder previsualizar la estabilización en el navegador aplicando
    el suavizado/zoom en JavaScript, sin generar ningún vídeo. Se ejecuta y cachea una
    sola vez por clip+shakiness+accuracy — cambiar el suavizado o el zoom después no
    requiere volver a llamar a esto."""
    source = source.resolve()
    analysis = ensure_analysis(root, source, shakiness, accuracy, progress_cb)
    ffmpeg_bin = analysis["ffmpeg_bin"]
    path_cache = _path_cache_file(root, source, shakiness, accuracy)

    if path_cache.exists():
        try:
            cached = json.loads(path_cache.read_text())
            if cached.get("source_size") == source.stat().st_size:
                return cached["data"]
        except (json.JSONDecodeError, OSError, KeyError):
            pass

    with tempfile.TemporaryDirectory() as tmp:
        work_dir = Path(tmp)
        dump_path = work_dir / "global_motions.trf"
        cmd = [
            ffmpeg_bin, "-y", "-hide_banner", "-loglevel", "error",
            "-i", str(source),
            "-vf", f"yadif=mode=1:deint=interlaced,vidstabtransform=input={analysis['trf_path']}:debug=1",
            "-f", "null", "-",
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, cwd=work_dir, timeout=1800)
        if result.returncode != 0 or not dump_path.exists():
            raise RuntimeError(f"No se pudo calcular la trayectoria: {result.stderr.strip()[-1000:]}")
        raw_path = _parse_raw_path(dump_path)

    video_info = _probe_video_info(source, ffmpeg_bin)
    data = {
        "path": raw_path,
        "fps": video_info["fps"],
        "width": video_info["width"],
        "height": video_info["height"],
        "duration": analysis["duration"],
        "stats": analysis["stats"],
    }
    path_cache.write_text(json.dumps({"source_size": source.stat().st_size, "data": data}))
    return data


def _zoom_filter_args(zoom_mode: str, zoom_percent: float) -> str:
    if zoom_mode == ZOOM_MANUAL:
        return f"optzoom=0:zoom={zoom_percent}"
    if zoom_mode == ZOOM_AUTO_DYNAMIC:
        return "optzoom=2"
    return "optzoom=1"


def stabilize_clip(source: Path, dest: Path, root: Path, progress_cb=None, fast_hw: bool = False,
                    shakiness: int = 5, accuracy: int = 15, smoothing: int = 10,
                    zoom_mode: str = ZOOM_AUTO_STATIC, zoom_percent: float = 0.0) -> dict:
    """Desentrelaza + estabiliza `source` y escribe `dest` (.mp4). `root` es la carpeta
    del proyecto, donde se cachea el análisis (pase 1) para poder reprocesar (pase 2)
    con otro suavizado/zoom sin repetirlo.

    zoom_mode: 'auto_static' (recorte fijo mínimo para todo el vídeo, el más habitual),
    'auto_dynamic' (recorte que varía por fotograma según haga falta) o 'manual' (recorte
    fijo elegido por el usuario en zoom_percent, como el control de Pinnacle).

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
    transform_log = dest.parent / f".{dest.stem}.transform.log"
    detect_log = dest.parent / f".{dest.stem}.detect.log"

    try:
        transforms_path, detect_stats, from_cache = _ensure_transforms(
            root, source, ffmpeg_bin, shakiness, accuracy, duration,
            progress_cb, 0.0, 0.5, detect_log,
        )

        if fast_hw:
            video_bitrate = _estimate_source_video_bitrate(source, ffmpeg_bin)
            encoder_args = ["-c:v", "h264_videotoolbox", "-b:v", str(video_bitrate), "-profile:v", "high"]
        else:
            encoder_args = ["-c:v", "libx264", "-crf", "18", "-preset", "medium"]

        zoom_args = _zoom_filter_args(zoom_mode, zoom_percent)
        transform_cmd = [
            ffmpeg_bin, "-y", "-hide_banner", "-loglevel", "info",
            "-i", str(source),
            "-vf",
            f"yadif=mode=1:deint=interlaced,"
            f"vidstabtransform=input={transforms_path}:smoothing={smoothing}:{zoom_args}:interpol=bilinear,"
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

        transform_text = transform_log.read_text(errors="ignore")
    finally:
        detect_log.unlink(missing_ok=True)
        transform_log.unlink(missing_ok=True)

    tmp_dest.rename(dest)
    if progress_cb:
        progress_cb(1.0)

    if zoom_mode == ZOOM_MANUAL:
        zoom_percent_result = round(zoom_percent, 2)
    else:
        zoom_match = _ZOOM_RE.search(transform_text)
        zoom_percent_result = round(float(zoom_match.group(1)), 2) if zoom_match else None

    return {
        "zoom_percent": zoom_percent_result,
        "low_contrast_frames": detect_stats.get("low_contrast_frames"),
        "total_frames": detect_stats.get("total_frames"),
        "confidence_percent": detect_stats.get("confidence_percent"),
        "encoder": "h264_videotoolbox (hardware)" if fast_hw else "libx264 (software)",
        "reused_analysis": from_cache,
        "mode": "personalizado" if (zoom_mode != ZOOM_AUTO_STATIC or smoothing != 10 or shakiness != 5) else "automático",
    }
