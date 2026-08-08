"""Lista los clips ya convertidos/estabilizados disponibles para montar (son los que
se pueden reproducir en el navegador; los .MTS originales no)."""

from pathlib import Path

from .ffmpeg_ops import get_duration_seconds
from .scanner import OUTPUT_DIR_NAME, STABILIZE_DIR_NAME

_SOURCE_LABELS = {
    OUTPUT_DIR_NAME: "convertido",
    STABILIZE_DIR_NAME: "estabilizado",
}


def list_available_clips(root: str) -> list[dict]:
    root_path = Path(root).expanduser().resolve()
    clips = []
    for subfolder, label in _SOURCE_LABELS.items():
        folder = root_path / subfolder
        if not folder.is_dir():
            continue
        for file_path in sorted(folder.glob("*.mp4")):
            try:
                duration = get_duration_seconds(file_path)
                size = file_path.stat().st_size
            except OSError:
                continue
            clips.append({
                "path": str(file_path),
                "name": file_path.stem,
                "source": label,
                "duration": round(duration, 2),
                "size": size,
            })
    clips.sort(key=lambda c: c["name"])
    return clips
