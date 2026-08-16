"""Lista los clips ya convertidos/estabilizados disponibles para montar (son los que
se pueden reproducir en el navegador; los .MTS originales no)."""

from pathlib import Path

from .config import resolve_output_base
from .ffmpeg_ops import get_duration_seconds
from .manifest import load_manifest
from .scanner import OUTPUT_DIR_NAME
from .stabilize import load_stabilize_draft


def list_available_clips(root: str) -> list[dict]:
    root_path = Path(root).expanduser().resolve()
    output_base = resolve_output_base(root_path)
    clips = []

    # Convertidos: centralizados en conversion/, con su borrador de estabilización
    # enlazado a través del manifiesto (origen -> nombre de salida).
    conv_folder = output_base / OUTPUT_DIR_NAME
    if conv_folder.is_dir():
        conv_manifest = load_manifest(root_path, OUTPUT_DIR_NAME)
        source_by_output = {
            entry["output"]: source for source, entry in conv_manifest.items() if entry.get("output")
        }
        for file_path in sorted(conv_folder.glob("*.mp4")):
            try:
                duration = get_duration_seconds(file_path)
                size = file_path.stat().st_size
            except OSError:
                continue
            source_path = source_by_output.get(file_path.name)
            draft = load_stabilize_draft(root_path, Path(source_path)) if source_path else None
            clips.append({
                "path": str(file_path),
                "name": file_path.stem,
                "source": "convertido",
                "duration": round(duration, 2),
                "size": size,
                "stabilize_draft": draft,
            })

    # Estabilizados: ahora co-localizados junto a cada original (o replicados con la
    # misma ruta relativa bajo la carpeta de trabajo, si hay una configurada) — se
    # descubren recorriendo el árbol en vez de un glob a una carpeta fija. Nunca se les
    # asocia ningún borrador: el clip ya está estabilizado, heredarlo otra vez en el
    # montaje aplicaría vid.stab dos veces sobre un vídeo que ya no tiembla.
    if output_base.is_dir():
        for file_path in sorted(output_base.rglob("*_stabilized.mp4")):
            try:
                duration = get_duration_seconds(file_path)
                size = file_path.stat().st_size
            except OSError:
                continue
            clips.append({
                "path": str(file_path),
                "name": file_path.stem,
                "source": "estabilizado",
                "duration": round(duration, 2),
                "size": size,
                "stabilize_draft": None,
            })

    clips.sort(key=lambda c: c["name"])
    return clips
