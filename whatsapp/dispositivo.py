"""Acceso al móvil. **El único sitio de este paquete que mira fuera.**

Hoy se apoya en `importer.mtp`, que es un envoltorio de gphoto2 con bastante cicatriz
dentro: en macOS hay que apartar `ptpcamerad` porque reclama la interfaz USB aunque el
móvil esté en modo MTP, y hay que mantener una sola sesión abierta porque renegociarla
cuesta 12-16 s por carpeta. Duplicar todo eso aquí solo para no importarlo sería copiar
340 líneas de conocimiento ganado a base de golpes.

**Para extraer este paquete como app independiente**, hay dos caminos, y los dos empiezan
y acaban en este fichero:

  · llevarse también `importer/mtp.py` y cambiar el import de abajo, o
  · sustituir estas funciones por otra implementación (libmtp, adb, lo que sea).

El resto del paquete solo conoce estas cuatro funciones y `ErrorDispositivo`.
"""

from pathlib import Path

from importer import mtp

# Se reexporta con nombre propio para que el resto del paquete no nombre a `mtp` jamás.
ErrorDispositivo = mtp.MtpError


def disponible() -> bool:
    """Si la librería de acceso al móvil está instalada."""
    return mtp.available()


def conectados() -> list[dict]:
    """Móviles que se pueden abrir ahora mismo. Lista vacía si no hay ninguno."""
    return mtp.detect()


def lista_carpetas(ruta: str) -> list[dict]:
    """Subcarpetas de `ruta` en el móvil: [{'name', 'path'}]."""
    return mtp.list_folder(ruta)["folders"]


def lista_ficheros(ruta: str, recursivo: bool = True,
                   extensiones: set[str] | None = None) -> list[dict]:
    """Ficheros de `ruta`: [{'name', 'folder', 'path', 'size', 'captured'}].

    `extensiones` vacío o None = sin filtrar. Se pide `skip_noise=False` siempre porque
    todo lo de WhatsApp vive bajo `Android/`, que el explorador de carpetas esconde a
    propósito por tener cientos de carpetas de aplicaciones.
    """
    return mtp.list_files(ruta, recursive=recursivo,
                          extensions=extensiones if extensiones is not None else set(),
                          skip_noise=False)


def descarga(carpeta: str, nombre: str, destino: Path,
             tamano: int | None = None) -> int:
    """Trae **un** fichero del móvil a `destino`. Devuelve los bytes escritos.

    Escribe a `.parcial` y renombra al terminar: si se desconecta el cable a mitad, no
    queda un fichero truncado con aspecto de completo.
    """
    return mtp.fetch(carpeta, nombre, destino, tamano)
