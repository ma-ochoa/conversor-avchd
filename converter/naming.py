"""Generación de nombres de archivo únicos a partir de la fecha/hora de captura."""

import re
from datetime import datetime

_UNSAFE_PREFIX_RE = re.compile(r"[^A-Za-z0-9_\-]")


def sanitize_prefix(prefix: str) -> str:
    """Deja solo caracteres seguros para un nombre de archivo (sin espacios ni
    símbolos de ruta), p. ej. para un identificador de cámara como "a6400"."""
    return _UNSAFE_PREFIX_RE.sub("", prefix or "").strip("_-")


def base_name(dt: datetime, prefix: str = "") -> str:
    stem = dt.strftime("%Y%m%d_%H%M%S")
    prefix = sanitize_prefix(prefix)
    return f"{prefix}_{stem}" if prefix else stem


def unique_name(dt: datetime, ext: str, used_names: set[str], prefix: str = "") -> str:
    """ext incluye el punto, p.ej. '.mp4'. Añade _2, _3... si hay colisión."""
    stem = base_name(dt, prefix)
    candidate = f"{stem}{ext}"
    counter = 2
    while candidate in used_names:
        candidate = f"{stem}_{counter}{ext}"
        counter += 1
    used_names.add(candidate)
    return candidate
