"""Configuración global del importador.

Vive en `~/.conversor-importador/` y NO dentro de la carpeta de proyecto: el importador
es global (destino local, mapeo de cámaras, credenciales del NAS), a diferencia del
resto de módulos, que trabajan sobre una carpeta concreta.
"""

import json
import os
import threading
from pathlib import Path

CONFIG_DIR = Path.home() / ".conversor-importador"
CONFIG_PATH = CONFIG_DIR / "config.json"
CACHE_DIR = CONFIG_DIR / "miniaturas"

_lock = threading.Lock()

DEFAULT_NAS = {
    "enabled": False,
    "method": "synology",           # synology | sftp | ftp | ftps
    "host": "",
    "port": 0,                      # 0 = puerto por defecto del método
    "user": "",
    "password": "",
    # El código 2FA NO se guarda: caduca en 30 s. Lo que se guarda es el token de
    # dispositivo que devuelve el NAS tras un login con código, y que en los siguientes
    # logins evita tener que volver a pedirlo.
    "device_id": "",                # solo Synology, token de "dispositivo de confianza"
    "use_https": True,              # solo Synology
    "verify_tls": True,
    "remote_root": "/photo",        # carpeta indexada por Synology Photos
    "upload_after_import": False,
}

DEFAULTS = {
    "version": 1,
    "destination": str(Path.home() / "Pictures" / "Importaciones"),
    "photos_dir_name": "Fotos",
    "videos_dir_name": "Videos",
    # Vacío = las fotos normales van directas a la carpeta del día, sin subcarpeta. Solo
    # los RAW se apartan, que es lo que interesa separar de verdad.
    "jpg_dir_name": "",
    "raw_dir_name": "RAW",
    "group_videos_by_day": False,
    "rename_by_date": True,
    "verify_checksum": True,
    "skip_duplicates": True,
    "cameras": {},                  # modelo EXIF -> nombre de carpeta
    "nas": dict(DEFAULT_NAS),
}


def _merge(base: dict, override: dict) -> dict:
    merged = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _merge(merged[key], value)
        else:
            merged[key] = value
    return merged


# Claves que existieron en versiones anteriores y ya no deben usarse. Se descartan al
# cargar para que no queden campos muertos que alguien pueda volver a rellenar por error.
_RETIRED_NAS_KEYS = ("otp",)


def _migrate(config: dict) -> dict:
    """El código 2FA llegó a guardarse en disco, y no debe: caduca en 30 s y guardarlo solo
    deja una credencial parada sin ninguna utilidad. Lo sustituye `device_id`."""
    for key in _RETIRED_NAS_KEYS:
        config.get("nas", {}).pop(key, None)
    # Las fotos normales ya no van en subcarpeta: una configuración anterior con "JPG"
    # guardado seguiría creándola.
    if config.get("jpg_dir_name") == "JPG":
        config["jpg_dir_name"] = ""
    return config


def load_config() -> dict:
    if not CONFIG_PATH.exists():
        return _merge(DEFAULTS, {})
    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            return _migrate(_merge(DEFAULTS, json.load(f)))
    except (json.JSONDecodeError, OSError):
        return _merge(DEFAULTS, {})


def save_config(updates: dict) -> dict:
    """Fusiona `updates` sobre lo guardado y devuelve la configuración resultante."""
    with _lock:
        current = load_config()
        merged = _merge(current, updates)
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        with open(CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump(merged, f, indent=2, ensure_ascii=False)
        # El fichero guarda la contraseña del NAS en claro: al menos que solo la lea su dueño.
        os.chmod(CONFIG_PATH, 0o600)
        return merged


def remember_camera(model: str, folder_name: str) -> None:
    if model and folder_name:
        save_config({"cameras": {model: folder_name}})


def public_config() -> dict:
    """Configuración apta para enviar al navegador: sin credenciales en claro."""
    config = load_config()
    nas = dict(config["nas"])
    nas["has_password"] = bool(nas.pop("password", ""))
    # El token de dispositivo es una credencial: al navegador solo le interesa si existe,
    # para poder decir "este equipo ya está autorizado" y ofrecer olvidarlo.
    nas["has_device_token"] = bool(nas.pop("device_id", ""))
    config["nas"] = nas
    return config
