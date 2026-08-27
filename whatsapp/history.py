"""Registro de lo ya copiado, para no traerlo dos veces.

**Aparte del historial del importador**, y no por purismo: el material de WhatsApp son
decenas de miles de memes y reenvíos, y mezclarlo con el historial de fotos de cámara
hacía que todo apareciera en «Subir pendientes al NAS». Con dos ficheros distintos, el
problema no existe en vez de necesitar una marca para esquivarlo.
"""

import json
import threading
from datetime import datetime

from .config import DIR_DATOS

RUTA = DIR_DATOS / "copiado.json"

_lock = threading.Lock()
_MAX_RUNS = 50


def _vacio() -> dict:
    return {"version": 1, "copiado": {}, "runs": []}


def load() -> dict:
    if not RUTA.exists():
        return _vacio()
    try:
        with open(RUTA, "r", encoding="utf-8") as f:
            return {**_vacio(), **json.load(f)}
    except (json.JSONDecodeError, OSError):
        return _vacio()


def _write(datos: dict) -> None:
    DIR_DATOS.mkdir(parents=True, exist_ok=True)
    with open(RUTA, "w", encoding="utf-8") as f:
        json.dump(datos, f, indent=2, ensure_ascii=False)


def claves_copiadas() -> set[str]:
    """Llaves de lo ya copiado.

    Se derivan del **nombre guardado en cada entrada**, no de las claves del diccionario,
    para que sigan valiendo los registros escritos cuando la llave incluía el tamaño
    (`wa|nombre|12345`). Sin esto, cambiar el formato de la llave habría hecho que todo
    lo copiado hasta ahora se volviera a traer.
    """
    return {f"wa|{v['name']}" for v in load()["copiado"].values() if v.get("name")}


def registra(entradas: dict[str, dict]) -> None:
    """Apunta un lote de una vez. Se llama por lotes y no fichero a fichero porque
    reescribir el JSON entero 40.000 veces sería el cuello de botella de la copia."""
    if not entradas:
        return
    with _lock:
        datos = load()
        datos["copiado"].update(entradas)
        _write(datos)


def registra_run(run: dict) -> None:
    with _lock:
        datos = load()
        datos["runs"].insert(0, run)
        del datos["runs"][_MAX_RUNS:]
        _write(datos)


def olvida_destinos(destinos: list[str]) -> int:
    """Saca del registro los ficheros que ya no están en el ordenador.

    Hace falta al borrar desde la galería: si la entrada se quedara, la próxima
    sincronización daría el fichero por copiado y no lo traería, y el usuario tendría un
    hueco permanente sin saber por qué.
    """
    if not destinos:
        return 0
    fuera = set(destinos)
    with _lock:
        datos = load()
        sobreviven = {k: v for k, v in datos["copiado"].items() if v.get("dest") not in fuera}
        quitados = len(datos["copiado"]) - len(sobreviven)
        if quitados:
            datos["copiado"] = sobreviven
            _write(datos)
        return quitados


def runs(limit: int = 10) -> list[dict]:
    return load()["runs"][:limit]


def marca_tiempo() -> str:
    return datetime.now().isoformat(timespec="seconds")
