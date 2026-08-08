"""Registro persistente de qué ficheros ya se han procesado, para no repetir trabajo.
Se usa tanto para la carpeta 'conversion' (remuxeo) como 'estabilizado' (vid.stab)."""

import json
import threading
from pathlib import Path

_lock = threading.Lock()


def _manifest_path(root: Path, subfolder: str) -> Path:
    return root / subfolder / ".manifest.json"


def load_manifest(root: Path, subfolder: str = "conversion") -> dict:
    path = _manifest_path(root, subfolder)
    if not path.exists():
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return {}


def record_entry(root: Path, subfolder: str, source_path: str, entry: dict) -> None:
    path = _manifest_path(root, subfolder)
    path.parent.mkdir(parents=True, exist_ok=True)
    with _lock:
        manifest = load_manifest(root, subfolder)
        manifest[source_path] = entry
        with open(path, "w", encoding="utf-8") as f:
            json.dump(manifest, f, indent=2, ensure_ascii=False)


def record_conversion(root: Path, source_path: str, size: int, output_name: str) -> None:
    record_entry(root, "conversion", source_path, {"size": size, "output": output_name})
