"""Configuración y almacén propios del paquete.

Vive aparte de la configuración del importador **a propósito**: cuando esto salga como
app independiente, solo hay que cambiar `DIR_DATOS` y no queda ningún hilo suelto.

**Dos almacenes, y la diferencia importa.**

  · `DIR_DATOS` (`~/.conversor-importador/whatsapp/`) guarda lo que describe la
    instalación: qué destino se ha elegido, qué medios se han copiado ya, qué agenda se
    importó. Es pequeño y no se mueve nunca.
  · `DIR_DATA` (`data/`, **dentro del destino, junto a las imágenes**) guarda el material:
    las copias cifradas, las bases descifradas y la clave. Es lo que pesa y lo que uno
    querría llevarse entero a otro disco.

La configuración no puede vivir en `data/` porque `data/` se deduce de ella: sería
morderse la cola, y cambiar el destino dejaría la instalación sin saber dónde estaba.
"""

import json
import shutil
import threading
from pathlib import Path

# Único sitio que decide dónde se guarda la configuración de la instalación.
DIR_DATOS = Path.home() / ".conversor-importador" / "whatsapp"
RUTA_CONFIG = DIR_DATOS / "config.json"

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


def dir_data() -> Path:
    """`data/` dentro del destino: donde van las bases y la clave."""
    return Path(load_config()["destination"]).expanduser() / "data"


# Se resuelve al importar. Cambiar el destino en Ajustes mueve los ficheros (ver
# `muda_data`), así que estas rutas siguen siendo válidas mientras dure el proceso.
DIR_DATA = dir_data()

# La copia cifrada tal cual sale del móvil, y la descifrada.
CIFRADA = DIR_DATA / "msgstore.db.crypt15"
DESCIFRADA = DIR_DATA / "msgstore.db"

# **Los nombres de los contactos NO están en msgstore.db.** Viven en `wa.db`, una segunda
# base de datos que WhatsApp guarda aparte (en `Backups/`, no en `Databases/`). Sin ella,
# una conversación individual solo puede enseñar un número de teléfono. Va cifrada con la
# misma clave, así que se descifra a la vez.
AGENDA_CIFRADA = DIR_DATA / "wa.db.crypt15"
AGENDA = DIR_DATA / "wa.db"

# **Las copias incrementales.** WhatsApp hace una copia completa cada varios días y, entre
# medias, incrementales con lo hablado desde entonces. La completa por sí sola deja fuera
# ese hueco: en el móvil de prueba, un día entero de mensajes.
#
# Van en su propia carpeta y **no sustituyen a la base**: son un complemento con las filas
# nuevas, y mezclarlas a ciegas con `msgstore.db` sería inventarse una fusión que WhatsApp
# hace de otra manera al restaurar.
INCREMENTALES = DIR_DATA / "incrementales"

# **La copia anterior, conservada a propósito.** Cada sincronización trae una base nueva
# del móvil, y esa base puede tener MENOS que la anterior: el usuario borra conversaciones
# y fotos para liberar espacio en el teléfono. Sobrescribir sin más convertiría el archivo
# del ordenador en un espejo del móvil en vez de en un histórico.
ANTERIOR = DIR_DATA / "msgstore.anterior.db"

# **El archivo histórico**: la base que crece y nunca pierde nada. Es la fusión de todas
# las copias traídas, con lo que el móvil ya borró marcado en vez de eliminado.
ARCHIVO = DIR_DATA / "archivo.db"

# Carpeta de instantáneas: un resumen por sincronización (recuentos, no contenido) para
# poder ver qué desapareció entre una y otra sin guardar 330 MB cada vez.
INSTANTANEAS = DIR_DATA / "instantaneas"

# La clave de 64 dígitos, cifrada. Ver `claves.py`.
CLAVE_GUARDADA = DIR_DATA / "clave.bin"
CLAVE_RESPALDO = DIR_DATA / "clave.maestra"

# Lo que se traslada cuando cambia el destino o al migrar del almacén antiguo.
# Los `-wal`/`-shm` son los auxiliares que SQLite deja junto a cada base: si la base se
# muda y ellos no, quedan huérfanos apuntando a un fichero que ya no está ahí.
_MATERIAL = ("msgstore.db.crypt15", "msgstore.db", "msgstore.db-wal", "msgstore.db-shm",
             "wa.db.crypt15", "wa.db", "wa.db-wal", "wa.db-shm",
             "msgstore.anterior.db", "archivo.db", "archivo.db-wal", "archivo.db-shm",
             "clave.bin", "clave.maestra", "incrementales", "instantaneas")


def _mueve(origen: Path, destino: Path) -> list[str]:
    """Traslada el material de `origen` a `destino`. Devuelve qué se movió."""
    movidos = []
    if not origen.is_dir() or origen.resolve() == destino.resolve():
        return movidos
    destino.mkdir(parents=True, exist_ok=True)
    for nombre in _MATERIAL:
        de, a = origen / nombre, destino / nombre
        if not de.exists() or a.exists():
            continue
        try:
            shutil.move(str(de), str(a))
            movidos.append(nombre)
        except OSError:
            pass          # lo que no se pueda mover se queda donde está, sin romper nada
    return movidos


def migra_almacen() -> list[str]:
    """Sube el material del almacén antiguo (`DIR_DATOS`) a `data/`.

    Se llama al arrancar. Sin esto, quien ya tuviera 500 MB descargados los vería
    desaparecer de la interfaz y volvería a bajarlos.
    """
    return _mueve(DIR_DATOS, DIR_DATA)


def muda_data(destino_nuevo: str) -> list[str]:
    """Lleva el material a la `data/` del nuevo destino cuando este cambia en Ajustes."""
    nueva = Path(destino_nuevo).expanduser() / "data"
    return _mueve(DIR_DATA, nueva)
