"""Lectura de metadatos en lote con exiftool.

`converter/metadata.py` lanza un exiftool por fichero, lo que va bien para decenas de
clips pero no para una tarjeta con miles de fotos. Aquí se pasa la lista completa por
stdin (`-@ -`) y se recibe un único JSON, lo que reduce el escaneo de una tarjeta de
varios minutos a unos segundos.
"""

import json
import re
import subprocess
from datetime import datetime
from pathlib import Path

_DATE_RE = re.compile(r"(\d{4})[:\-](\d{2})[:\-](\d{2})[ T](\d{2}):(\d{2}):(\d{2})")

_TAGS = [
    "-Make",
    "-Model",
    # Los MP4 XAVC de Sony (carpeta M4ROOT) no traen Make/Model: el modelo va en el
    # bloque XML del contenedor. Sin esto, los vídeos 4K quedarían separados de las
    # fotos de la misma cámara.
    "-DeviceManufacturer",
    "-DeviceModelName",
    # Los MP4 grabados con un móvil Samsung tampoco traen Make/Model: el modelo va en un
    # tag propio del fabricante, como el código interno ("SM-S938B" para un Galaxy S25
    # Ultra). Sin esto, los vídeos del móvil quedaban "sin identificar" mientras sus
    # fotos, tomadas en el mismo momento, sí se agrupaban bien.
    "-Samsung:SamsungModel",
    "-DateTimeOriginal",
    "-CreateDate",
    "-MediaCreateDate",
    "-TrackCreateDate",
    "-FileType",
    "-ImageWidth",
    "-ImageHeight",
    "-Duration",
    # El sufijo # pide el valor numérico con signo (-3.7 en vez de "3 deg 42' 0.00\" W"),
    # que es lo que hace falta para calcular distancias y para el mapa.
    "-GPSLatitude#",
    "-GPSLongitude#",
    # Los vídeos guardan la posición en un único tag combinado, no en dos.
    "-GPSCoordinates#",
]

_DATE_PREFERENCE = ["DateTimeOriginal", "CreateDate", "MediaCreateDate", "TrackCreateDate"]

_BATCH_SIZE = 400


def _parse_datetime(raw: str) -> datetime | None:
    """Se ignora la zona horaria a propósito: se toma la hora local tal cual la grabó la
    cámara, igual que hace `converter/metadata.py` y que muestran Synology Photos o Finder."""
    match = _DATE_RE.search(raw)
    if not match:
        return None
    try:
        return datetime(*(int(g) for g in match.groups()))
    except ValueError:
        return None


def _strip_group(key: str) -> str:
    return key.split(":", 1)[1] if ":" in key else key


def _coords(flat: dict) -> tuple[float, float] | None:
    """(latitud, longitud) en grados decimales, o None si el fichero no lleva posición."""
    lat, lon = flat.get("GPSLatitude"), flat.get("GPSLongitude")
    if lat is None or lon is None:
        # Formato de vídeo: "37.123 -3.456" (a veces con una tercera cifra de altitud).
        raw = str(flat.get("GPSCoordinates", "")).replace(",", " ").split()
        if len(raw) < 2:
            return None
        lat, lon = raw[0], raw[1]
    try:
        lat, lon = float(lat), float(lon)
    except (TypeError, ValueError):
        return None
    # Una posición exactamente en (0, 0) es el marcador habitual de "GPS no fijado".
    if abs(lat) > 90 or abs(lon) > 180 or (lat == 0 and lon == 0):
        return None
    return lat, lon


def _run_batch(paths: list[Path]) -> list[dict]:
    cmd = ["exiftool", "-j", "-G0", "-s", "-charset", "filename=utf8", *_TAGS, "-@", "-"]
    stdin = "\n".join(str(p) for p in paths)
    result = subprocess.run(cmd, input=stdin, capture_output=True, text=True, timeout=600)
    if not result.stdout.strip():
        return []
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError:
        return []


def read_metadata(paths: list[Path]) -> dict[str, dict]:
    """Devuelve {ruta: {'make', 'model', 'capture_dt', 'date_source', 'width', 'height', 'duration'}}.

    Si no hay fecha en los metadatos se cae a la fecha de modificación del fichero, igual
    que el resto de la app, marcándolo como origen 'archivo'.
    """
    found: dict[str, dict] = {}

    for start in range(0, len(paths), _BATCH_SIZE):
        for record in _run_batch(paths[start:start + _BATCH_SIZE]):
            source = record.get("SourceFile")
            if not source:
                continue

            flat = {_strip_group(k): v for k, v in record.items() if k != "SourceFile"}

            capture_dt = None
            for tag in _DATE_PREFERENCE:
                if tag in flat:
                    capture_dt = _parse_datetime(str(flat[tag]))
                    if capture_dt:
                        break

            found[str(Path(source))] = {
                "make": str(flat.get("Make") or flat.get("DeviceManufacturer") or "").strip(),
                "model": str(flat.get("Model") or flat.get("DeviceModelName")
                             or flat.get("SamsungModel") or "").strip(),
                "capture_dt": capture_dt,
                "date_source": "exif" if capture_dt else "archivo",
                "width": flat.get("ImageWidth"),
                "height": flat.get("ImageHeight"),
                "duration": flat.get("Duration"),
                "gps": _coords(flat),
            }

    for path in paths:
        key = str(path)
        entry = found.get(key)
        if entry is None:
            entry = {"make": "", "model": "", "capture_dt": None, "date_source": "archivo",
                     "width": None, "height": None, "duration": None, "gps": None}
            found[key] = entry
        if entry["capture_dt"] is None:
            try:
                entry["capture_dt"] = datetime.fromtimestamp(path.stat().st_mtime)
            except OSError:
                entry["capture_dt"] = datetime.now()
            entry["date_source"] = "archivo"

    return found
