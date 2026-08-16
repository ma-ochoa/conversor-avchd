"""Configuración global de la app — no ligada a ninguna carpeta de proyecto en
concreto. Por ahora solo guarda la "carpeta de trabajo": el sitio donde se guardan
conversion/, estabilizado/, recompresion/, montaje/ (proyectos y exportaciones) y las
cachés (.vidstab_cache/, .proxies/, .miniaturas/).

Por defecto (sin configurar) cada carpeta de origen es su propia carpeta de trabajo,
igual que siempre. Si el usuario fija una carpeta de trabajo desde Ajustes, TODO lo
generado para CUALQUIER carpeta de origen va ahí, centralizado — pensado como una
única librería de material ya tratado, en vez de una copia de conversion/estabilizado
esparcida dentro de cada carpeta que se escanea."""

import json
import threading
from pathlib import Path

_CONFIG_PATH = Path.home() / ".conversor-avchd" / "config.json"
_lock = threading.Lock()


def load_config() -> dict:
    if not _CONFIG_PATH.exists():
        return {}
    try:
        with open(_CONFIG_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return {}


def save_config(data: dict) -> None:
    with _lock:
        _CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(_CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)


def get_working_dir() -> Path | None:
    raw = load_config().get("working_dir")
    return Path(raw).expanduser() if raw else None


def set_working_dir(path: str | None) -> Path | None:
    """path=None (o cadena vacía) vuelve al comportamiento por defecto (cada carpeta
    de origen es su propia carpeta de trabajo). Devuelve la ruta resuelta, o None."""
    config = load_config()
    resolved = None
    if path:
        resolved = Path(path).expanduser().resolve()
        config["working_dir"] = str(resolved)
    else:
        config.pop("working_dir", None)
    save_config(config)
    return resolved


def resolve_output_base(root: Path) -> Path:
    """Base para conversion/, estabilizado/, recompresion/, montaje/, .vidstab_cache/,
    .proxies/, .miniaturas/ — la carpeta de trabajo configurada si hay una, si no la
    propia carpeta de origen (comportamiento de siempre). Idempotente: da igual si
    `root` ya viene resuelta o no."""
    working_dir = get_working_dir()
    return working_dir if working_dir else root
