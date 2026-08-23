"""Lectura de tracks GPX como fuente de referencias de posición.

Un GPX de un reloj, un móvil o un registrador da cobertura continua (un punto cada pocos
segundos), frente a las fotos con GPS que solo cubren los instantes en que disparaste.

Aviso sobre husos horarios: el GPX guarda la hora en **UTC**, mientras que las cámaras
graban la **hora local sin indicar zona** (ver `converter/metadata.py`, que lo asume así a
propósito). Comparar ambas directamente desplazaría todo el track varias horas, así que
`load_gpx()` recibe el desfase que hay que aplicar y devuelve los puntos ya convertidos a
hora local.
"""

import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from pathlib import Path


class GpxError(RuntimeError):
    pass


def _local_utc_offset_hours() -> float:
    """Desfase actual del sistema respecto a UTC, como valor por defecto razonable."""
    offset = datetime.now().astimezone().utcoffset()
    return offset.total_seconds() / 3600 if offset else 0.0


def _parse_time(raw: str) -> datetime | None:
    raw = (raw or "").strip()
    if not raw:
        return None
    try:
        moment = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    # Se normaliza a UTC "ingenuo" para poder sumarle el desfase sin ambigüedades.
    if moment.tzinfo is not None:
        moment = moment.astimezone(timezone.utc).replace(tzinfo=None)
    return moment


def load_gpx(path: str | Path, utc_offset_hours: float | None = None) -> list[dict]:
    """Devuelve [{'dt': iso local, 'gps': [lat, lon]}] ordenado por tiempo."""
    path = Path(path).expanduser()
    if not path.is_file():
        raise GpxError(f"No existe el fichero GPX: {path}")

    if utc_offset_hours is None:
        utc_offset_hours = _local_utc_offset_hours()
    shift = timedelta(hours=utc_offset_hours)

    try:
        root = ET.parse(path).getroot()
    except ET.ParseError as exc:
        raise GpxError(f"El fichero GPX no se pudo leer: {exc}") from exc

    points = []
    # El GPX declara namespace y varía entre la versión 1.0 y la 1.1, así que se busca por
    # el nombre de etiqueta sin prefijo en vez de fijar una URI concreta.
    for element in root.iter():
        tag = element.tag.rsplit("}", 1)[-1]
        if tag not in ("trkpt", "wpt", "rtept"):
            continue
        lat, lon = element.get("lat"), element.get("lon")
        if lat is None or lon is None:
            continue
        moment = None
        for child in element:
            if child.tag.rsplit("}", 1)[-1] == "time":
                moment = _parse_time(child.text or "")
                break
        if moment is None:
            continue
        try:
            points.append({"dt": (moment + shift).isoformat(), "gps": [float(lat), float(lon)]})
        except ValueError:
            continue

    if not points:
        raise GpxError(
            "El GPX no contiene ningún punto con hora. Se necesitan puntos con marca de "
            "tiempo para poder cruzarlos con las fotos."
        )

    points.sort(key=lambda p: p["dt"])
    return points


def default_utc_offset() -> float:
    return _local_utc_offset_hours()
