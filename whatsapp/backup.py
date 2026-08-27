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
from .config import (AGENDA, AGENDA_CIFRADA, CIFRADA, DESCIFRADA, DIR_DATOS,
                     INCREMENTALES)

# Los 64 dígitos hexadecimales que enseña WhatsApp, normalmente en grupos de 4.
_CLAVE_RE = re.compile(r"^[0-9a-f]{64}$", re.IGNORECASE)

# Firma de un fichero SQLite. Es lo único que distingue un descifrado bueno de uno malo.
_FIRMA_SQLITE = b"SQLite format 3\x00"


class BackupError(RuntimeError):
    """Algo que el usuario puede entender y arreglar."""


class ClaveInvalida(BackupError):
    """La clave no tiene la forma esperada, o no abre esta copia."""


# Cómo empiezan las incrementales. **El nombre no basta para saber si una aporta algo**:
# al hacer una copia completa, WhatsApp renombra las incrementales pendientes añadiéndoles
# la fecha (`msgstore-increment-1.db.crypt15` pasa a
# `msgstore-increment-1-2026-08-28.1.db.crypt15`) y su contenido ya está dentro de la
# completa. Lo que decide es la fecha: solo sirven las posteriores a la completa que se
# vaya a usar. Comprobado en el móvil de prueba, donde la copia de la madrugada absorbió
# la incremental del día anterior.
_PREFIJO_INCREMENTAL = "msgstore-increment"


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
        # Lo hablado **después** de la copia completa que se va a usar. Sin comparar
        # fechas se estarían bajando trozos que la completa ya contiene.
        "incrementales": [c for c in copias
                          if c["usable"] and not c["full"]
                          and c["name"].startswith(_PREFIJO_INCREMENTAL)
                          and utilizable and (c["date"] or "") > (utilizable["date"] or "")],
        # Lo que la interfaz necesita para decidir si enseña las instrucciones.
        "needs_e2e": utilizable is None,
    }


def descarga_incrementales(copias: list[dict], progress_cb=None) -> list[dict]:
    """Trae las incrementales a `INCREMENTALES/`. Devuelve qué se ha traído.

    Se guardan aparte a propósito: no sustituyen a `msgstore.db`, la complementan.
    """
    INCREMENTALES.mkdir(parents=True, exist_ok=True)
    traidas = []
    for copia in copias:
        destino = INCREMENTALES / copia["name"]
        # Ya descargada y del mismo tamaño: no se vuelve a traer. Una incremental no
        # cambia una vez escrita; WhatsApp crea otra con el número siguiente.
        if destino.is_file() and destino.stat().st_size == (copia.get("size") or 0):
            traidas.append({**copia, "ruta": str(destino), "ya_estaba": True})
            continue
        dispositivo.descarga(copia["folder"], copia["name"], destino,
                             copia.get("size") or None)
        traidas.append({**copia, "ruta": str(destino), "ya_estaba": False})
        if progress_cb:
            progress_cb(len(traidas), len(copias))
    return traidas


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
    resultado["incrementales"] = descifra_incrementales(clave)
    return resultado


def descifra_incrementales(clave: str) -> list[dict]:
    """Descifra las incrementales descargadas y dice qué trae cada una.

    Van una a una y **ninguna puede tumbar el descifrado de los mensajes**: son un extra,
    y un fallo aquí no debe costar la base entera. Se comprueba además que lo descifrado
    sea de verdad una base con mensajes, en vez de darlo por bueno por no dar error.
    """
    salida = []
    if not INCREMENTALES.is_dir():
        return salida
    for cifrada in sorted(INCREMENTALES.glob("*.crypt15")):
        entrada = {"nombre": cifrada.name}
        try:
            destino = descifra(clave, cifrada, cifrada.with_suffix("").with_suffix(".db"))
            entrada.update({"ruta": str(destino), **_que_trae(destino)})
        except BackupError as exc:
            entrada["error"] = str(exc)
        salida.append(entrada)
    return salida


def _que_trae(db: Path) -> dict:
    """Cuántos mensajes hay en una base descifrada, y de cuándo son.

    Sirve para dos cosas: enseñar si la incremental aporta algo, y comprobar que el
    fichero es una base legible — que se descifre sin error no garantiza lo segundo.
    """
    try:
        con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    except sqlite3.Error as exc:
        return {"utilizable": False, "detalle": str(exc)}
    try:
        n = con.execute("SELECT COUNT(*) FROM message").fetchone()[0]
        desde, hasta = con.execute(
            "SELECT MIN(timestamp), MAX(timestamp) FROM message WHERE timestamp > 0"
        ).fetchone()
        return {"utilizable": True, "mensajes": n, "desde": desde, "hasta": hasta}
    except sqlite3.Error as exc:
        # Una incremental puede no ser una base al uso; se dice, en vez de fingir que sí.
        return {"utilizable": False, "detalle": str(exc)}
    finally:
        con.close()


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
            "Falta la herramienta de descifrado. Instálala en el mismo entorno que "
            f"ejecuta la app:\n    {_como_instalar()}"
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
        "incrementales": sorted(
            p.name for p in INCREMENTALES.glob("*.crypt15")) if INCREMENTALES.is_dir() else [],
        "tool_installed": _herramienta_instalada(),
        # La interfaz enseña este mismo comando, para no inventarse uno que no funcione.
        "tool_command": _como_instalar(),
    }


def _como_instalar() -> str:
    """El comando que instala wa-crypt-tools **en el entorno que ejecuta la app**.

    Se da la ruta del intérprete en vez de un `pip` a secas porque en macOS ese `pip`
    suele ser el de Homebrew, que rechaza instalar nada (PEP 668) y, aunque funcionara,
    lo instalaría en un entorno distinto del que después va a buscar el módulo.
    """
    return f"{sys.executable} -m pip install wa-crypt-tools"


def _herramienta_instalada() -> bool:
    try:
        import wa_crypt_tools  # noqa: F401
        return True
    except ImportError:
        return False
