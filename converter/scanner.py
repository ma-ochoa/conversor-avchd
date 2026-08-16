"""Recorre una carpeta buscando vídeos, fotos y formatos aún no soportados."""

import os
from pathlib import Path

from .config import resolve_output_base
from .metadata import get_capture_datetime
from .manifest import load_manifest
from .stabilize import (
    STABILIZATION_DATA_DIR,
    has_cached_analysis,
    load_stabilize_draft,
    stabilized_output_path,
)

AVCHD_EXTS = {".mts", ".m2ts"}
MP4_FAMILY_EXTS = {".mp4", ".mov", ".m4v"}
VIDEO_EXTS = AVCHD_EXTS | MP4_FAMILY_EXTS
PHOTO_EXTS = {".jpg", ".jpeg", ".png", ".heic", ".heif", ".tif", ".tiff"}
OTHER_VIDEO_EXTS = {".avi", ".mkv", ".wmv", ".3gp"}

OUTPUT_DIR_NAME = "conversion"
# Nombre histórico de la carpeta de salida de estabilización (antes de pasar a guardar
# cada vídeo estabilizado junto a su original) — se sigue excluyendo del escaneo por si
# queda alguna carpeta sin migrar.
STABILIZE_DIR_NAME = "estabilizado"

_EXCLUDED_DIRS = (OUTPUT_DIR_NAME, STABILIZE_DIR_NAME, STABILIZATION_DATA_DIR)


def _iter_files(root: Path):
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [
            d for d in dirnames
            if not d.startswith(".") and d not in _EXCLUDED_DIRS
        ]
        for name in filenames:
            if name.startswith(".") or name.endswith("_stabilized.mp4"):
                continue
            yield Path(dirpath) / name


def _processed_entry(manifest: dict, dir_name: str, output_base: Path, file_path: Path, size: int) -> dict:
    entry = manifest.get(str(file_path))
    done = bool(
        entry
        and entry.get("size") == size
        and entry.get("output")
        and (output_base / dir_name / entry["output"]).exists()
    )
    return {
        "done": done,
        "output_name": entry.get("output") if done else None,
        "stats": entry.get("stats") if done else None,
    }


def scan_folder(root: str) -> dict:
    root_path = Path(root).expanduser().resolve()
    if not root_path.is_dir():
        raise NotADirectoryError(str(root_path))

    output_base = resolve_output_base(root_path)
    manifest = load_manifest(root_path)

    avchd_clips = []
    photos = []
    other_videos = []

    for file_path in _iter_files(root_path):
        ext = file_path.suffix.lower()
        try:
            size = file_path.stat().st_size
        except OSError:
            continue

        if ext in VIDEO_EXTS:
            dt, source = get_capture_datetime(file_path, is_video=True)
            conv = _processed_entry(manifest, OUTPUT_DIR_NAME, output_base, file_path, size)
            draft = load_stabilize_draft(root_path, file_path)
            stabilized_path = stabilized_output_path(root_path, file_path)
            has_analysis = has_cached_analysis(
                root_path, file_path,
                draft.get("shakiness", 5) if draft else 5,
                draft.get("accuracy", 15) if draft else 15,
                draft.get("stepsize", 6) if draft else 6,
                draft.get("mincontrast", 0.25) if draft else 0.25,
            )
            avchd_clips.append(
                {
                    "path": str(file_path),
                    "relative": str(file_path.relative_to(root_path)),
                    "size": size,
                    "capture_dt": dt.isoformat(),
                    "date_source": source,
                    "format": ext.lstrip("."),
                    "already_converted": conv["done"],
                    "output_name": conv["output_name"],
                    "already_stabilized": stabilized_path.exists(),
                    "stabilize_output_name": stabilized_path.name if stabilized_path.exists() else None,
                    "has_analysis": has_analysis,
                    "stabilize_draft": draft,
                }
            )
        elif ext in PHOTO_EXTS:
            dt, source = get_capture_datetime(file_path, is_video=False)
            conv = _processed_entry(manifest, OUTPUT_DIR_NAME, output_base, file_path, size)
            photos.append(
                {
                    "path": str(file_path),
                    "relative": str(file_path.relative_to(root_path)),
                    "size": size,
                    "capture_dt": dt.isoformat(),
                    "date_source": source,
                    "already_converted": conv["done"],
                    "output_name": conv["output_name"],
                }
            )
        elif ext in OTHER_VIDEO_EXTS:
            other_videos.append(
                {
                    "path": str(file_path),
                    "relative": str(file_path.relative_to(root_path)),
                    "size": size,
                }
            )

    avchd_clips.sort(key=lambda c: c["capture_dt"])
    photos.sort(key=lambda p: p["capture_dt"])
    other_videos.sort(key=lambda v: v["relative"])

    return {
        "root": str(root_path),
        "output_dir": str(output_base / OUTPUT_DIR_NAME),
        "avchd_clips": avchd_clips,
        "photos": photos,
        "other_videos": other_videos,
    }
