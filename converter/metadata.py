"""Extracción de fecha/hora de captura para vídeos AVCHD y fotos, vía exiftool."""

import json
import re
import subprocess
from datetime import datetime
from pathlib import Path

_DATE_RE = re.compile(r"(\d{4}):(\d{2}):(\d{2})\s+(\d{2}):(\d{2}):(\d{2})")

# Orden de preferencia: la primera etiqueta presente y parseable gana.
_VIDEO_TAGS = ["-DateTimeOriginal", "-CreateDate", "-MediaCreateDate", "-TrackCreateDate"]
_PHOTO_TAGS = ["-DateTimeOriginal", "-CreateDate"]


def _run_exiftool(path: Path, tags: list[str]) -> dict:
    cmd = ["exiftool", "-j", "-G0", "-s", *tags, str(path)]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    if result.returncode != 0 or not result.stdout.strip():
        return {}
    try:
        data = json.loads(result.stdout)
    except json.JSONDecodeError:
        return {}
    return data[0] if data else {}


def _parse_exif_datetime(raw: str) -> datetime | None:
    """Se ignora deliberadamente la zona horaria: se toma la hora local tal cual la
    grabó la cámara, que es también lo que la mayoría de reproductores y galerías
    (Synology Photos, Finder, Plex, Emby) muestran sin convertir desde UTC."""
    match = _DATE_RE.search(raw)
    if not match:
        return None
    year, month, day, hour, minute, second = (int(g) for g in match.groups())
    try:
        return datetime(year, month, day, hour, minute, second)
    except ValueError:
        return None


def _first_valid(data: dict, tags: list[str]) -> datetime | None:
    for tag in tags:
        key = tag.lstrip("-")
        for field_key, value in data.items():
            # exiftool antepone el nombre de grupo (p.ej. "System:FileModifyDate" o "H264:DateTimeOriginal")
            if field_key == key or field_key.endswith(":" + key):
                parsed = _parse_exif_datetime(str(value))
                if parsed:
                    return parsed
    return None


def get_capture_datetime(path: Path, is_video: bool) -> tuple[datetime, str]:
    """Devuelve (fecha_hora, origen) donde origen es 'exif' o 'archivo' (fallback)."""
    tags = _VIDEO_TAGS if is_video else _PHOTO_TAGS
    data = _run_exiftool(path, tags)
    parsed = _first_valid(data, tags)
    if parsed:
        return parsed, "exif"
    return datetime.fromtimestamp(path.stat().st_mtime), "archivo"
