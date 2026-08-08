"""Generación de nombres de archivo únicos a partir de la fecha/hora de captura."""

from datetime import datetime


def base_name(dt: datetime) -> str:
    return dt.strftime("%Y%m%d_%H%M%S")


def unique_name(dt: datetime, ext: str, used_names: set[str]) -> str:
    """ext incluye el punto, p.ej. '.mp4'. Añade _2, _3... si hay colisión."""
    stem = base_name(dt)
    candidate = f"{stem}{ext}"
    counter = 2
    while candidate in used_names:
        candidate = f"{stem}_{counter}{ext}"
        counter += 1
    used_names.add(candidate)
    return candidate
