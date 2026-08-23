"""Agrupación de fotos y vídeos en sesiones por cercanía en el tiempo.

Un día entero es demasiado grueso para asignar ubicaciones: en una jornada te mueves de
sitio varias veces. Aquí se corta la secuencia allí donde hay un hueco largo sin
disparar, que en la práctica es lo que separa "la mañana en un sitio" de "la tarde en
otro" — las fotos de las 9:00 forman un grupo y las de las 11:00 otro.

Deliberadamente NO se separa por cámara: si la cámara y el móvil disparan a la vez en el
mismo lugar deben caer en el mismo grupo, que es justo lo que permite después usar la
posición del móvil para la cámara.
"""

from datetime import datetime, timedelta
from pathlib import Path

from .geowrite import can_write

DEFAULT_GAP_MINUTES = 60


def _parse(value: str) -> datetime | None:
    try:
        return datetime.fromisoformat(value)
    except (TypeError, ValueError):
        return None


def _centroid(points: list[tuple[float, float]]) -> list[float] | None:
    """Media aritmética de las posiciones conocidas del grupo.

    Vale porque un grupo cubre minutos u horas en un mismo sitio, donde la curvatura de
    la Tierra es irrelevante. No serviría para puntos repartidos por el mundo.
    """
    if not points:
        return None
    return [sum(p[0] for p in points) / len(points), sum(p[1] for p in points) / len(points)]


def build_groups(files: dict[str, dict], gap_minutes: int = DEFAULT_GAP_MINUTES) -> list[dict]:
    """files: {ruta relativa: entrada del índice}. Devuelve grupos ordenados por fecha."""
    entries = []
    for relative, data in files.items():
        moment = _parse(data.get("capture_dt", ""))
        if moment:
            entries.append((moment, relative, data))
    entries.sort(key=lambda e: e[0])

    gap = timedelta(minutes=max(1, gap_minutes))
    groups: list[dict] = []
    current: list[tuple[datetime, str, dict]] = []

    def flush():
        if not current:
            return
        members = [
            {
                "relative": relative,
                "capture_dt": moment.isoformat(),
                "gps": data.get("gps"),
                "source": data.get("source"),
                "place": data.get("place", ""),
                "writable": can_write(Path(relative)),
            }
            for moment, relative, data in current
        ]
        located = [m for m in members if m["gps"]]
        blocked = [m for m in members if not m["gps"] and not m["writable"]]
        places = [m["place"] for m in members if m.get("place")]
        groups.append({
            "id": f"g{len(groups) + 1}",
            "start": current[0][0].isoformat(),
            "end": current[-1][0].isoformat(),
            "day": current[0][0].strftime("%Y-%m-%d"),
            "count": len(members),
            "with_gps": len(located),
            "without_gps": len(members) - len(located),
            # Sin ubicación y además imposible de escribir (AVCHD): la sesión nunca podrá
            # quedar completa sin convertir esos clips antes.
            "unwritable": len(blocked),
            "center": _centroid([tuple(m["gps"]) for m in located]),
            "place": places[0] if places else "",
            "files": members,
        })
        current.clear()

    for item in entries:
        if current and item[0] - current[-1][0] > gap:
            flush()
        current.append(item)
    flush()

    return groups


def label(group: dict) -> str:
    start = datetime.fromisoformat(group["start"])
    end = datetime.fromisoformat(group["end"])
    same_day = start.date() == end.date()
    tail = end.strftime("%H:%M") if same_day else end.strftime("%d/%m %H:%M")
    return f"{start.strftime('%d/%m/%Y %H:%M')} – {tail}"
