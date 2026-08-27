"""Configuración y almacén propios del paquete.

Vive aparte de la configuración del importador **a propósito**: cuando esto salga como
app independiente, solo hay que cambiar `DIR_DATOS` y no queda ningún hilo suelto.
"""

import json
import threading
from pathlib import Path

# Único sitio que decide dónde se guarda todo lo de WhatsApp.
DIR_DATOS = Path.home() / ".conversor-importador" / "whatsapp"
RUTA_CONFIG = DIR_DATOS / "config.json"

# La copia cifrada tal cual sale del móvil, y la descifrada.
CIFRADA = DIR_DATOS / "msgstore.db.crypt15"
DESCIFRADA = DIR_DATOS / "msgstore.db"

# **Los nombres de los contactos NO están en msgstore.db.** Viven en `wa.db`, una segunda
# base de datos que WhatsApp guarda aparte (en `Backups/`, no en `Databases/`). Sin ella,
# una conversación individual solo puede enseñar un número de teléfono. Va cifrada con la
# misma clave, así que se descifra a la vez.
AGENDA_CIFRADA = DIR_DATOS / "wa.db.crypt15"
AGENDA = DIR_DATOS / "wa.db"

# **Las copias incrementales.** WhatsApp hace una copia completa cada varios días y, entre
# medias, incrementales con lo hablado desde entonces. La completa por sí sola deja fuera
# ese hueco: en el móvil de prueba, un día entero de mensajes.
#
# Van en su propia carpeta y **no sustituyen a la base**: son un complemento con las filas
# nuevas, y mezclarlas a ciegas con `msgstore.db` sería inventarse una fusión que WhatsApp
# hace de otra manera al restaurar.
INCREMENTALES = DIR_DATOS / "incrementales"

# **La copia anterior, conservada a propósito.** Cada sincronización trae una base nueva
# del móvil, y esa base puede tener MENOS que la anterior: el usuario borra conversaciones
# y fotos para liberar espacio en el teléfono. Sobrescribir sin más convertiría el archivo
# del ordenador en un espejo del móvil en vez de en un histórico.
#
# Guardar la generación anterior cuesta un fichero y es lo que permitirá construir la
# fusión acumulativa (fase 2, ver HISTORICO.md) contra datos reales en vez de a ciegas.
ANTERIOR = DIR_DATOS / "msgstore.anterior.db"

# Carpeta de instantáneas: un resumen por sincronización (recuentos, no contenido) para
# poder ver qué desapareció entre una y otra sin guardar 330 MB cada vez.
INSTANTANEAS = DIR_DATOS / "instantaneas"

_lock = threading.Lock()

DEFAULTS = {
    "version": 1,
    "destination": str(Path.home() / "Pictures" / "WhatsApp"),
    # Vacío = los tipos marcados por defecto en `media.KINDS`.
    "kinds": [],
}


def load_config() -> dict:
    if not RUTA_CONFIG.exists():
        return dict(DEFAULTS)
    try:
        with open(RUTA_CONFIG, "r", encoding="utf-8") as f:
            return {**DEFAULTS, **json.load(f)}
    except (json.JSONDecodeError, OSError):
        return dict(DEFAULTS)


def save_config(updates: dict) -> dict:
    with _lock:
        merged = {**load_config(), **updates}
        DIR_DATOS.mkdir(parents=True, exist_ok=True)
        with open(RUTA_CONFIG, "w", encoding="utf-8") as f:
            json.dump(merged, f, indent=2, ensure_ascii=False)
        return merged
