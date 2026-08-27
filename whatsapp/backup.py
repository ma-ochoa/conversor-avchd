"""La copia de seguridad de los chats: encontrarla, traerla, descifrarla y mirarla.

**El nudo del asunto.** La base de datos de mensajes vive en el almacenamiento privado de
WhatsApp (`/data/data/com.whatsapp/`), donde no llega nadie sin root: no es cuestión de
permisos que se puedan pedir, sino de que cada app de Android corre bajo su propio UID de
Linux y el kernel corta la lectura antes de mirar ningún permiso. Ni una app propia, ni
`adb` (que corre como usuario sin privilegios), ni el modo desarrollador cambian eso.

Lo que sí sale del móvil son las **copias de seguridad**, que WhatsApp escribe en el
almacenamiento compartido y se leen por USB sin nada especial. Y ahí está la diferencia
que lo decide todo:

  · `.crypt14` — cifrada con una clave guardada en el almacenamiento privado. Sin root,
    inservible. Es lo que hay **si no está activado el cifrado de extremo a extremo**.
  · `.crypt15` — copia cifrada de extremo a extremo. La clave es la de 64 dígitos que
    WhatsApp enseña **al usuario**, precisamente para que la copia sea suya. Esta sí.

Comprobado sobre un Galaxy S25: al activar el cifrado de extremo a extremo y forzar una
copia, la copia local pasó de `crypt14` a `crypt15` en el mismo directorio.

**Sobre la clave**: entra por parámetro, se usa y se olvida. No se guarda en la
configuración, no se escribe en ningún registro y no vuelve al navegador.
"""

import re
import sqlite3
import subprocess
import sys
from datetime import datetime
from pathlib import Path

from . import dispositivo
from .config import AGENDA, AGENDA_CIFRADA, CIFRADA, DESCIFRADA, DIR_DATOS

# Los 64 dígitos hexadecimales que enseña WhatsApp, normalmente en grupos de 4.
_CLAVE_RE = re.compile(r"^[0-9a-f]{64}$", re.IGNORECASE)

# Firma de un fichero SQLite. Es lo único que distingue un descifrado bueno de uno malo.
_FIRMA_SQLITE = b"SQLite format 3\x00"


class BackupError(RuntimeError):
    """Algo que el usuario puede entender y arreglar."""


class ClaveInvalida(BackupError):
    """La clave no tiene la forma esperada, o no abre esta copia."""


def _raiz_databases(root_media: str) -> str:
    """`.../WhatsApp/Media` -> `.../WhatsApp/Databases`, que es donde están las copias."""
    return f"{root_media.rsplit('/', 1)[0]}/Databases"


def busca_copias() -> dict:
    """Qué copias de seguridad hay en el móvil conectado.

    Devuelve las copias ordenadas de más nueva a más vieja, y sobre todo **si hay alguna
    utilizable**: solo las `.crypt15` lo son.
    """
    from .media import find_root                     # tardío: comparte los mensajes de error

    databases = _raiz_databases(find_root())
    try:
        ficheros = dispositivo.lista_ficheros(databases, recursivo=False)
    except Exception as exc:
        raise BackupError(f"No se pudo leer la carpeta de copias del móvil: {exc}") from exc

    copias = []
    for f in ficheros:
        nombre = f["name"]
        if ".crypt" not in nombre:
            continue
        formato = nombre.rsplit(".crypt", 1)[1]
        copias.append({
            "name": nombre,
            "folder": databases,
            "size": f.get("size") or 0,
            "date": f.get("captured"),
            "format": f"crypt{formato}",
            "usable": formato == "15",
            # Las incrementales son trozos sueltos entre copias completas; la buena es
            # `msgstore.db.crypt15` a secas.
            "full": nombre.startswith("msgstore.db.crypt"),
        })

    copias.sort(key=lambda c: (c["usable"], c["full"], c["date"] or ""), reverse=True)
    utilizable = next((c for c in copias if c["usable"] and c["full"]), None)
    return {
        "folder": databases,
        "backups": copias,
        "best": utilizable,
        # Lo que la interfaz necesita para decidir si enseña las instrucciones.
        "needs_e2e": utilizable is None,
    }


def descarga_copia(copia: dict, progress_cb=None) -> Path:
    """Trae una copia del móvil a `DIR_DATOS`. Devuelve la ruta local."""
    DIR_DATOS.mkdir(parents=True, exist_ok=True)
    destino = DIR_DATOS / copia["name"]
    if progress_cb:
        progress_cb(0, copia.get("size") or 0)
    escritos = dispositivo.descarga(copia["folder"], copia["name"], destino,
                                    copia.get("size") or None)
    if progress_cb:
        progress_cb(escritos, escritos)
    return destino


def normaliza_clave(clave: str) -> str:
    """Quita los espacios con los que WhatsApp agrupa la clave y comprueba la forma."""
    limpia = re.sub(r"\s+", "", clave or "")
    if not _CLAVE_RE.match(limpia):
        # Se dice cuántos caracteres había, nunca cuáles.
        raise ClaveInvalida(
            f"Eso no parece la clave: se esperan 64 dígitos hexadecimales y has puesto "
            f"{len(limpia)} caracteres.\n\n"
            "Si lo que tienes es una CONTRASEÑA, esta aplicación no puede descifrar "
            "con ella, y no es un fallo suyo: en modo contraseña la clave real no está "
            "en tu poder, sino en un almacén de WhatsApp que la libera tras comprobar "
            "la contraseña contra sus servidores. No hay nada que ejecutar en local.\n\n"
            "Para usar esta aplicación: WhatsApp → Ajustes → Chats → Copia de seguridad "
            "→ Copia cifrada de extremo a extremo → cambiar a «clave de cifrado de 64 "
            "dígitos». Ojo: sustituye a la contraseña, no se suman, y a partir de ahí la "
            "clave es lo único que restaura tus copias."
        )
    return limpia.lower()


def _wadecrypt() -> list[str]:
    """Se invoca el **módulo**, no el ejecutable: pip instala los scripts de
    wa-crypt-tools en el `bin/` del framework de Python, que en macOS no suele estar en
    el PATH. Por `-m` se usa el mismo intérprete que ejecuta esto."""
    return [sys.executable, "-m", "wa_crypt_tools.wadecrypt"]


def descifra_todo(clave: str) -> dict:
    """Descifra las dos bases de una vez: mensajes y agenda.

    Se hace junto porque la clave es la misma y pedirla dos veces no tiene sentido. La
    agenda es opcional: si no se ha descargado, se sigue sin ella y la interfaz enseñará
    números de teléfono en vez de nombres.
    """
    resultado = {"mensajes": str(descifra(clave, CIFRADA, DESCIFRADA)), "agenda": None}
    if AGENDA_CIFRADA.is_file():
        try:
            resultado["agenda"] = str(descifra(clave, AGENDA_CIFRADA, AGENDA))
        except BackupError as exc:
            # Que falle la agenda no debe tumbar lo importante.
            resultado["agenda_error"] = str(exc)
    return resultado


def descifra(clave: str, cifrada: Path | None = None,
             salida: Path | None = None) -> Path:
    """Descifra la copia y devuelve la ruta del `.db` en claro.

    La clave se normaliza antes, y **nunca se registra**: si la herramienta la escupiera
    en un mensaje de error, se tapa antes de devolverlo.
    """
    cifrada = Path(cifrada or CIFRADA)
    salida = Path(salida or DESCIFRADA)
    if not cifrada.is_file():
        raise BackupError(f"No está la copia cifrada: {cifrada}")

    clave = normaliza_clave(clave)
    try:
        resultado = subprocess.run(
            [*_wadecrypt(), clave, str(cifrada), str(salida)],
            capture_output=True, text=True, timeout=600,
        )
    except FileNotFoundError as exc:
        raise BackupError(
            "Falta la herramienta de descifrado. Instálala con:\n"
            "    pip install wa-crypt-tools"
        ) from exc
    except subprocess.TimeoutExpired as exc:
        raise BackupError("El descifrado ha tardado demasiado y se ha cancelado.") from exc

    if resultado.returncode != 0 or not salida.exists():
        detalle = (resultado.stderr or resultado.stdout).replace(clave, "«clave»")
        raise BackupError(f"No se pudo descifrar:\n{detalle[-1200:]}")

    # **Una clave equivocada no da error**: `wadecrypt` termina con éxito y deja un
    # fichero de basura del tamaño correcto. Comprobar la firma de SQLite es lo único
    # que separa un descifrado bueno de uno malo.
    with open(salida, "rb") as f:
        if f.read(16) != _FIRMA_SQLITE:
            salida.unlink(missing_ok=True)
            raise ClaveInvalida(
                "La clave no abre esta copia: lo que sale no es una base de datos. "
                "Comprueba que son los 64 dígitos que enseña WhatsApp en Ajustes → "
                "Chats → Copia de seguridad → Copia cifrada de extremo a extremo."
            )
    return salida


# ------------------------------------------------------- mirar la base de datos abierta

# Nombres que ha ido usando WhatsApp para lo mismo. La tabla vieja `messages` se
# sustituyó por `message` + `chat` + `jid`; conviene aceptar las dos porque una copia
# antigua restaurada puede traer el esquema viejo.
_TABLAS = (
    ("message", "messages", "mensajes"),
    ("chat", None, "conversaciones"),
    ("jid", None, "contactos"),
    ("message_media", None, "vínculo mensaje → archivo"),
)


def resumen(db: Path | None = None) -> dict:
    """Qué hay dentro, **sin leer ni un mensaje**: sirve para confirmar que la copia se
    ha abierto bien y para saber con qué esquema estamos tratando."""
    db = Path(db or DESCIFRADA)
    if not db.is_file():
        raise BackupError("Todavía no hay ninguna base de datos descifrada.")

    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    try:
        existentes = {t for (t,) in con.execute(
            "SELECT name FROM sqlite_master WHERE type='table'")}

        tablas = []
        for nombre, alternativa, para_que in _TABLAS:
            real = nombre if nombre in existentes else (
                alternativa if alternativa in existentes else None)
            filas = None
            if real:
                (filas,) = con.execute(f"SELECT count(*) FROM `{real}`").fetchone()
            tablas.append({"tabla": real or nombre, "presente": bool(real),
                           "filas": filas, "para_que": para_que})

        desde = hasta = None
        tabla_msg = "message" if "message" in existentes else (
            "messages" if "messages" in existentes else None)
        if tabla_msg:
            columna = "timestamp" if tabla_msg == "message" else "timestamp"
            fila = con.execute(
                f"SELECT min({columna}), max({columna}) FROM `{tabla_msg}` "
                f"WHERE {columna} > 0"
            ).fetchone()
            if fila and fila[0]:
                # WhatsApp guarda milisegundos desde época.
                desde, hasta = (datetime.fromtimestamp(v / 1000).date().isoformat()
                                for v in fila)
    finally:
        con.close()

    return {
        "path": str(db),
        "size": db.stat().st_size,
        "modified": datetime.fromtimestamp(db.stat().st_mtime).isoformat(timespec="seconds"),
        "total_tablas": len(existentes),
        "tablas": tablas,
        "first_day": desde,
        "last_day": hasta,
    }


def estado() -> dict:
    """Lo que la interfaz necesita para saber en qué punto está todo, sin tocar el móvil."""
    cifrada = CIFRADA if CIFRADA.is_file() else None
    descifrada = DESCIFRADA if DESCIFRADA.is_file() else None
    return {
        "encrypted": {
            "path": str(CIFRADA),
            "present": bool(cifrada),
            "size": cifrada.stat().st_size if cifrada else 0,
            "modified": (datetime.fromtimestamp(cifrada.stat().st_mtime)
                         .isoformat(timespec="seconds") if cifrada else None),
        },
        "decrypted": {
            "path": str(DESCIFRADA),
            "present": bool(descifrada),
            "size": descifrada.stat().st_size if descifrada else 0,
            "modified": (datetime.fromtimestamp(descifrada.stat().st_mtime)
                         .isoformat(timespec="seconds") if descifrada else None),
        },
        "tool_installed": _herramienta_instalada(),
    }


def _herramienta_instalada() -> bool:
    try:
        import wa_crypt_tools  # noqa: F401
        return True
    except ImportError:
        return False
