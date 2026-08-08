"""Construye el filtro ffmpeg de un montaje (recorte por clip, títulos, transiciones
cruzadas xfade/acrossfade) y renderiza el vídeo final. Esto recodifica siempre."""

import re
import subprocess
from pathlib import Path

from .stabilize import find_ffmpeg_with_vidstab as find_ffmpeg_full

_TIME_RE = re.compile(r"out_time_ms=(\d+)")


def _esc(text: str) -> str:
    """Escapa texto para usarlo dentro de un valor de filtro ffmpeg (drawtext)."""
    return (
        text.replace("\\", "\\\\\\\\")
        .replace(":", "\\:")
        .replace("'", "’")
        .replace("%", "\\%")
        .replace(",", "\\,")
        .replace("[", "\\[")
        .replace("]", "\\]")
    )


def _esc_path(path: str) -> str:
    return path.replace("\\", "\\\\").replace(":", "\\:").replace("'", "\\'")


def build_filter_complex(clips: list, transition_seconds: float, width: int = 1920, height: int = 1080):
    """clips: lista de dicts {path, in, out, title:{text?,font?,image?,duration?}}.
    Devuelve (input_args, filter_complex, video_label, audio_label)."""
    input_args = []
    for clip in clips:
        input_args += ["-i", clip["path"]]

    filters = []
    v_labels = []
    a_labels = []

    for i, clip in enumerate(clips):
        start, end = clip["in"], clip["out"]
        v_base = f"v{i}base"
        filters.append(
            f"[{i}:v]trim=start={start}:end={end},setpts=PTS-STARTPTS,"
            f"scale={width}:{height}:force_original_aspect_ratio=decrease,"
            f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2,fps=25,format=yuv420p[{v_base}]"
        )
        current = v_base

        title = clip.get("title")
        if title:
            duration = float(title.get("duration") or 3.0)
            if title.get("text"):
                font = _esc_path(title.get("font") or "")
                text = _esc(title["text"])
                out_label = f"v{i}txt"
                fontfile = f"fontfile='{font}':" if font else ""
                filters.append(
                    f"[{current}]drawtext={fontfile}text='{text}':fontsize=54:"
                    f"fontcolor=white:borderw=3:bordercolor=black@0.7:"
                    f"x=(w-text_w)/2:y=h-th-70:enable='between(t\\,0\\,{duration})'[{out_label}]"
                )
                current = out_label
            if title.get("image"):
                img = _esc_path(title["image"])
                img_label = f"v{i}img"
                ovl_label = f"v{i}ovl"
                clip_duration = end - start
                filters.append(
                    f"movie='{img}',loop=loop=-1:size=1,setpts=N/(FRAME_RATE*TB),"
                    f"trim=duration={clip_duration}[{img_label}]"
                )
                filters.append(
                    f"[{current}][{img_label}]overlay=(W-w)/2:(H-h)/2:shortest=1:"
                    f"enable='between(t\\,0\\,{duration})'[{ovl_label}]"
                )
                current = ovl_label

        v_labels.append(current)

        a_label = f"a{i}"
        filters.append(
            f"[{i}:a]atrim=start={start}:end={end},asetpts=PTS-STARTPTS,"
            f"aformat=sample_fmts=fltp:sample_rates=48000:channel_layouts=stereo[{a_label}]"
        )
        a_labels.append(a_label)

    if len(clips) == 1:
        return input_args, ";".join(filters), v_labels[0], a_labels[0]

    cumulative = clips[0]["out"] - clips[0]["in"]
    prev_v, prev_a = v_labels[0], a_labels[0]
    for i in range(1, len(clips)):
        dur_i = clips[i]["out"] - clips[i]["in"]
        t = max(min(transition_seconds, cumulative - 0.05, dur_i - 0.05), 0)
        out_v, out_a = f"vx{i}", f"ax{i}"
        if t > 0.05:
            offset = cumulative - t
            filters.append(
                f"[{prev_v}][{v_labels[i]}]xfade=transition=fade:duration={t:.3f}:offset={offset:.3f}[{out_v}]"
            )
            filters.append(f"[{prev_a}][{a_labels[i]}]acrossfade=d={t:.3f}[{out_a}]")
            cumulative = cumulative + dur_i - t
        else:
            filters.append(f"[{prev_v}][{v_labels[i]}]concat=n=2:v=1:a=0[{out_v}]")
            filters.append(f"[{prev_a}][{a_labels[i]}]concat=n=2:v=0:a=1[{out_a}]")
            cumulative = cumulative + dur_i
        prev_v, prev_a = out_v, out_a

    return input_args, ";".join(filters), prev_v, prev_a


def export_timeline(clips: list, transition_seconds: float, dest: Path, progress_cb=None) -> None:
    if not clips:
        raise ValueError("El montaje no tiene ningún clip")

    ffmpeg_bin = find_ffmpeg_full()
    total_duration = sum(c["out"] - c["in"] for c in clips)
    total_duration -= transition_seconds * max(len(clips) - 1, 0)
    total_duration = max(total_duration, 1)

    input_args, filter_complex, v_label, a_label = build_filter_complex(clips, transition_seconds)

    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp_dest = dest.with_suffix(dest.suffix + ".part")

    cmd = [
        ffmpeg_bin, "-y", "-hide_banner", "-loglevel", "error",
        *input_args,
        "-filter_complex", filter_complex,
        "-map", f"[{v_label}]", "-map", f"[{a_label}]",
        "-c:v", "libx264", "-crf", "18", "-preset", "medium",
        "-c:a", "aac", "-b:a", "256k",
        "-movflags", "+faststart", "-f", "mp4",
        "-progress", "pipe:1", "-nostats",
        str(tmp_dest),
    ]

    process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    for line in process.stdout:
        match = _TIME_RE.search(line)
        if match and progress_cb:
            seconds = int(match.group(1)) / 1_000_000
            progress_cb(min(seconds / total_duration, 1.0))
    stderr_text = process.stderr.read()
    process.wait()

    if process.returncode != 0:
        tmp_dest.unlink(missing_ok=True)
        raise RuntimeError(f"Exportación falló ({process.returncode}): {stderr_text.strip()[-2000:]}")

    tmp_dest.rename(dest)
    if progress_cb:
        progress_cb(1.0)
