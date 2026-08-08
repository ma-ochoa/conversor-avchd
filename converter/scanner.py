"""Recorre una carpeta buscando clips AVCHD, fotos y otros vídeos (fase 2)."""

import os
from pathlib import Path

from .metadata import get_capture_datetime
from .manifest import load_manifest

AVCHD_EXTS = {".mts", ".m2ts"}
PHOTO_EXTS = {".jpg", ".jpeg", ".png", ".heic", ".heif", ".tif", ".tiff"}
OTHER_VIDEO_EXTS = {".mp4", ".mov", ".avi", ".mkv", ".wmv", ".m4v", ".3gp"}

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


def scan_folder(root: str) -> dict:
    root_path = Path(root).expanduser().resolve()
    if not root_path.is_dir():
        raise NotADirectoryError(str(root_path))

    manifest = load_manifest(root_path)
    stabilize_manifest = load_manifest(root_path, STABILIZE_DIR_NAME)

    avchd_clips = []
    photos = []
    other_videos = []

    for file_path in _iter_files(root_path):
        ext = file_path.suffix.lower()
        try:
            size = file_path.stat().st_size
        except OSError:
            continue

        if ext in AVCHD_EXTS:
            dt, source = get_capture_datetime(file_path, is_video=True)
            entry = manifest.get(str(file_path))
            already_done = bool(
                entry
                and entry.get("size") == size
                and entry.get("output")
                and (root_path / OUTPUT_DIR_NAME / entry["output"]).exists()
            )
            stab_entry = stabilize_manifest.get(str(file_path))
            already_stabilized = bool(
                stab_entry
                and stab_entry.get("size") == size
                and stab_entry.get("output")
                and (root_path / STABILIZE_DIR_NAME / stab_entry["output"]).exists()
            )
            avchd_clips.append(
                {
                    "path": str(file_path),
                    "relative": str(file_path.relative_to(root_path)),
                    "size": size,
                    "capture_dt": dt.isoformat(),
                    "date_source": source,
                    "already_converted": already_done,
                    "output_name": entry.get("output") if already_done else None,
                    "already_stabilized": already_stabilized,
                    "stabilize_output_name": stab_entry.get("output") if already_stabilized else None,
                    "stabilize_stats": stab_entry.get("stats") if already_stabilized else None,
                }
            )
        elif ext in PHOTO_EXTS:
            dt, source = get_capture_datetime(file_path, is_video=False)
            entry = manifest.get(str(file_path))
            already_done = bool(
                entry
                and entry.get("size") == size
                and entry.get("output")
                and (root_path / OUTPUT_DIR_NAME / entry["output"]).exists()
            )
            photos.append(
                {
                    "path": str(file_path),
                    "relative": str(file_path.relative_to(root_path)),
                    "size": size,
                    "capture_dt": dt.isoformat(),
                    "date_source": source,
                    "already_converted": already_done,
                    "output_name": entry.get("output") if already_done else None,
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
        "output_dir": str(root_path / OUTPUT_DIR_NAME),
        "stabilize_output_dir": str(root_path / STABILIZE_DIR_NAME),
        "avchd_clips": avchd_clips,
        "photos": photos,
        "other_videos": other_videos,
    }
