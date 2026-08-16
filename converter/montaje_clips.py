"""Lista los clips ya convertidos/estabilizados disponibles para montar (son los que
se pueden reproducir en el navegador; los .MTS originales no)."""

from pathlib import Path

from .ffmpeg_ops import get_duration_seconds
from .manifest import load_manifest
from .scanner import OUTPUT_DIR_NAME, STABILIZE_DIR_NAME
from .stabilize import CACHE_DIR_NAME as STABILIZE_CACHE_DIR_NAME

_SOURCE_LABELS = {
    OUTPUT_DIR_NAME: "convertido",
    STABILIZE_DIR_NAME: "estabilizado",
}


def _source_by_output(root_path: Path, subfolder: str) -> dict:
    """Invierte el manifiesto de esa carpeta (origen -> nombre de salida) para, dado
    un fichero ya convertido/estabilizado, encontrar el clip original del que procede
    y así poder consultar sus ajustes de estabilización guardados."""
    manifest = load_manifest(root_path, subfolder)
    return {entry["output"]: source for source, entry in manifest.items() if entry.get("output")}


def list_available_clips(root: str) -> list[dict]:
    root_path = Path(root).expanduser().resolve()
    stabilize_drafts = load_manifest(root_path, STABILIZE_CACHE_DIR_NAME)
    clips = []
    for subfolder, label in _SOURCE_LABELS.items():
        folder = root_path / subfolder
        if not folder.is_dir():
            continue
        source_by_output = _source_by_output(root_path, subfolder)
        for file_path in sorted(folder.glob("*.mp4")):
            try:
                duration = get_duration_seconds(file_path)
                size = file_path.stat().st_size
            except OSError:
                continue
            source_path = source_by_output.get(file_path.name)
            clips.append({
                "path": str(file_path),
                "name": file_path.stem,
                "source": label,
                "duration": round(duration, 2),
                "size": size,
                "stabilize_draft": stabilize_drafts.get(source_path) if source_path else None,
            })
    clips.sort(key=lambda c: c["name"])
    return clips
