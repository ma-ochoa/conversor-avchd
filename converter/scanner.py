"""Recorre una carpeta buscando vídeos, fotos y formatos aún no soportados."""

import os
from pathlib import Path

from .config import resolve_output_base
from .metadata import get_capture_datetime
from .manifest import load_manifest
from .stabilize import CACHE_DIR_NAME as STABILIZE_CACHE_DIR_NAME, has_cached_analysis

AVCHD_EXTS = {".mts", ".m2ts"}
MP4_FAMILY_EXTS = {".mp4", ".mov", ".m4v"}
VIDEO_EXTS = AVCHD_EXTS | MP4_FAMILY_EXTS
PHOTO_EXTS = {".jpg", ".jpeg", ".png", ".heic", ".heif", ".tif", ".tiff"}
OTHER_VIDEO_EXTS = {".avi", ".mkv", ".wmv", ".3gp"}

OUTPUT_DIR_NAME = "conversion"
STABILIZE_DIR_NAME = "estabilizado"


def _iter_files(root: Path):
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [
            d for d in dirnames
            if not d.startswith(".") and d not in (OUTPUT_DIR_NAME, STABILIZE_DIR_NAME)
        ]
        for name in filenames:
            if name.startswith("."):
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
    stabilize_manifest = load_manifest(root_path, STABILIZE_DIR_NAME)
    stabilize_drafts = load_manifest(root_path, STABILIZE_CACHE_DIR_NAME)

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
            stab = _processed_entry(stabilize_manifest, STABILIZE_DIR_NAME, output_base, file_path, size)
            draft = stabilize_drafts.get(str(file_path))
            has_analysis = has_cached_analysis(
                root_path, file_path,
                draft.get("shakiness", 5) if draft else 5,
                draft.get("accuracy", 15) if draft else 15,
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
                    "already_stabilized": stab["done"],
                    "stabilize_output_name": stab["output_name"],
                    "stabilize_stats": stab["stats"],
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
        "stabilize_output_dir": str(output_base / STABILIZE_DIR_NAME),
        "avchd_clips": avchd_clips,
        "photos": photos,
        "other_videos": other_videos,
    }
