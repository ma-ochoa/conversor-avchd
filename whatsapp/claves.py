"""Guarda la clave de 64 dígitos para no tener que teclearla en cada sincronización.

**La clave nunca se escribe en claro.** Se cifra con Fernet, y la clave maestra de ese
cifrado vive en el llavero del sistema — Keychain en macOS, Credential Manager en Windows,
Secret Service en Linux—, que es el único sitio donde la protege el usuario del sistema y
no un permiso de fichero.

**El respaldo a fichero existe por portabilidad, y es más débil a propósito.** En un
contenedor, en un servidor sin sesión gráfica o en una instalación sin llavero,
`keyring` no funciona; ahí la clave maestra cae a `clave.maestra` junto al fichero
cifrado. Eso ya no protege frente a quien tenga acceso a la carpeta —tiene las dos
piezas—, y sigue sirviendo para lo que sí resuelve: que la clave no aparezca en claro en
una copia de seguridad, en el portapapeles ni al mirar un fichero por encima.
`donde_esta()` lo dice sin adornos para que la interfaz pueda avisar.

Lo que se guarda es una clave de cifrado de WhatsApp: quien la tenga puede descifrar las
copias, pero **no da acceso a la cuenta** ni sirve para suplantar a nadie.
"""

import os
import stat
from pathlib import Path

from .config import CLAVE_GUARDADA, CLAVE_RESPALDO, DIR_DATA

# Con qué nombre aparece en el llavero del sistema, para que se reconozca al verla ahí.
_SERVICIO = "Conversor de vídeo — WhatsApp"
_CUENTA = "clave-copia-e2e"


class SinCifrado(RuntimeError):
    """Falta `cryptography`: sin ella no se guarda nada, antes que guardarlo en claro."""


def _fernet():
    try:
        from cryptography.fernet import Fernet
    except ImportError as exc:
        import sys
        raise SinCifrado(
            "Para guardar la clave hace falta «cryptography». Instálala con:\n"
            f"    {sys.executable} -m pip install cryptography"
        ) from exc
    return Fernet


def _llavero():
    """El módulo `keyring`, o `None` si no está o no hay llavero utilizable."""
    try:
        import keyring
        from keyring.backends.fail import Keyring as SinBackend
    except ImportError:
        return None
    try:
        if isinstance(keyring.get_keyring(), SinBackend):
            return None
    except Exception:
        return None
    return keyring


def _maestra(crear: bool = False) -> bytes | None:
    """La clave con la que se cifra la clave de WhatsApp. Del llavero, o del respaldo."""
    Fernet = _fernet()

    llavero = _llavero()
    if llavero is not None:
        try:
            guardada = llavero.get_password(_SERVICIO, _CUENTA)
            if guardada:
                return guardada.encode()
            if crear:
                nueva = Fernet.generate_key()
                llavero.set_password(_SERVICIO, _CUENTA, nueva.decode())
                return nueva
            return None
        except Exception:
            pass          # llavero presente pero inservible: se sigue por el respaldo

    if CLAVE_RESPALDO.is_file():
        return CLAVE_RESPALDO.read_bytes().strip()
    if not crear:
        return None

    nueva = Fernet.generate_key()
    DIR_DATA.mkdir(parents=True, exist_ok=True)
    CLAVE_RESPALDO.write_bytes(nueva)
    # Legible solo por su dueño. No sustituye al llavero, pero evita el caso tonto de
    # dejarla abierta a cualquier cuenta del equipo.
    try:
        CLAVE_RESPALDO.chmod(stat.S_IRUSR | stat.S_IWUSR)
    except OSError:
        pass
    return nueva


def donde_esta() -> str:
    """`llavero`, `fichero` o `ninguno`. La interfaz lo enseña para no prometer de más."""
    if not hay_clave():
        return "ninguno"
    llavero = _llavero()
    if llavero is not None:
        try:
            if llavero.get_password(_SERVICIO, _CUENTA):
                return "llavero"
        except Exception:
            pass
    return "fichero" if CLAVE_RESPALDO.is_file() else "ninguno"


def hay_clave() -> bool:
    return CLAVE_GUARDADA.is_file()


def guarda(clave: str) -> str:
    """Cifra y guarda la clave. Devuelve dónde quedó la maestra (`llavero`/`fichero`)."""
    Fernet = _fernet()
    maestra = _maestra(crear=True)
    DIR_DATA.mkdir(parents=True, exist_ok=True)
    CLAVE_GUARDADA.write_bytes(Fernet(maestra).encrypt(clave.encode()))
    try:
        CLAVE_GUARDADA.chmod(stat.S_IRUSR | stat.S_IWUSR)
    except OSError:
        pass
    return donde_esta()


def recupera() -> str | None:
    """La clave guardada, o `None` si no hay o ya no se puede descifrar."""
    if not CLAVE_GUARDADA.is_file():
        return None
    try:
        Fernet = _fernet()
        maestra = _maestra()
        if not maestra:
            return None
        return Fernet(maestra).decrypt(CLAVE_GUARDADA.read_bytes()).decode()
    except Exception:
        # Maestra perdida (llavero borrado, otro equipo): la guardada ya no vale de nada.
        return None


def olvida() -> bool:
    """Borra la clave y su maestra. Devuelve si había algo que borrar."""
    habia = CLAVE_GUARDADA.is_file()
    for ruta in (CLAVE_GUARDADA, CLAVE_RESPALDO):
        try:
            ruta.unlink(missing_ok=True)
        except OSError:
            pass
    llavero = _llavero()
    if llavero is not None:
        try:
            llavero.delete_password(_SERVICIO, _CUENTA)
        except Exception:
            pass
    return habia
