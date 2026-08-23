"""Deduce la posición de una foto sin GPS a partir de referencias con hora conocida.

La idea: si el móvil sacó una foto con GPS a las 19:47 y la cámara disparó a las 19:48
desde el mismo sitio, la posición del móvil sirve para la de la cámara. Lo mismo con los
puntos de un track GPX, que además dan cobertura continua.

Es una **aproximación deliberada**, no una medición: se muestra siempre el desfase de
tiempo con el que se dedujo, para que quien decide pueda descartar las que se apoyan en
una referencia demasiado lejana.
"""

from datetime import datetime
from math import asin, cos, radians, sin, sqrt
from pathlib import Path

from .exif import read_metadata
from .geoindex import load_index
from .media import PHOTO_EXTS, VIDEO_EXTS, _iter_files

DEFAULT_TOLERANCE_MINUTES = 20
EARTH_RADIUS_M = 6371000


def haversine_m(a: tuple[float, float], b: tuple[float, float]) -> float:
    lat1, lon1, lat2, lon2 = map(radians, (a[0], a[1], b[0], b[1]))
    h = sin((lat2 - lat1) / 2) ** 2 + cos(lat1) * cos(lat2) * sin((lon2 - lon1) / 2) ** 2
    return 2 * EARTH_RADIUS_M * asin(sqrt(h))


def references_from_index(root: Path) -> list[dict]:
    """Referencias sacadas de lo ya importado: todo fichero del índice que tenga posición."""
    references = []
    for relative, data in load_index(root)["files"].items():
        if data.get("gps") and data.get("capture_dt"):
            references.append({
                "dt": data["capture_dt"],
                "gps": list(data["gps"]),
                "label": Path(relative).name,
                "origin": "importado",
            })
    references.sort(key=lambda r: r["dt"])
    return references


def references_from_folder(folder: str) -> list[dict]:
    """Referencias de una carpeta cualquiera (las fotos del móvil sin importar).

    No copia ni modifica nada: solo lee metadatos.
    """
    base = Path(folder).expanduser().resolve()
    if not base.is_dir():
        raise NotADirectoryError(str(base))

    paths = [p for p in _iter_files(base) if p.suffix.lower() in (PHOTO_EXTS | VIDEO_EXTS)]
    metadata = read_metadata(paths)

    references = []
    for path in paths:
        meta = metadata.get(str(path))
        if meta and meta.get("gps") and meta.get("capture_dt"):
            references.append({
                "dt": meta["capture_dt"].isoformat(),
                "gps": list(meta["gps"]),
                "label": path.name,
                "origin": "carpeta",
            })
    references.sort(key=lambda r: r["dt"])
    return references


def _nearest(references: list[dict], moment: datetime) -> tuple[dict | None, float]:
    """Referencia más próxima en el tiempo y su distancia en segundos."""
    best, best_delta = None, float("inf")
    for reference in references:
        try:
            delta = abs((datetime.fromisoformat(reference["dt"]) - moment).total_seconds())
        except (TypeError, ValueError):
            continue
        if delta < best_delta:
            best, best_delta = reference, delta
    return best, best_delta


def match_groups(groups: list[dict], references: list[dict],
                 tolerance_minutes: int = DEFAULT_TOLERANCE_MINUTES) -> list[dict]:
    """Añade a cada grupo sin posición una propuesta `suggestion`, si la encuentra.

    Se propone por grupo y no por fichero: los ficheros de un grupo están por definición
    juntos en el tiempo y en el sitio, así que asignarles posiciones distintas sería
    fingir una precisión que no existe.
    """
    tolerance = max(1, tolerance_minutes) * 60

    for group in groups:
        group["suggestion"] = None
        if group["without_gps"] == 0 or not references:
            continue

        # Se busca contra el centro temporal del grupo, no contra su inicio: es lo que
        # menos se desvía cuando el grupo dura un rato.
        start = datetime.fromisoformat(group["start"])
        end = datetime.fromisoformat(group["end"])
        middle = start + (end - start) / 2

        reference, delta = _nearest(references, middle)
        if reference is None or delta > tolerance:
            continue

        group["suggestion"] = {
            "gps": reference["gps"],
            "delta_seconds": int(delta),
            "label": reference["label"],
            "origin": reference["origin"],
            # Si el grupo ya tiene alguna foto localizada, se puede contrastar la
            # propuesta con ella y avisar si no cuadran.
            "distance_m": (
                round(haversine_m(tuple(group["center"]), tuple(reference["gps"])))
                if group["center"] else None
            ),
        }

    return groups
