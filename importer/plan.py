"""Construcción del plan de destino: qué fichero acaba exactamente en qué ruta.

Es una función pura sin efectos en disco, para poder enseñar el plan completo antes de
copiar nada y para que la interfaz muestre el árbol resultante tal cual quedará.
"""

import shutil
from datetime import datetime
from pathlib import Path

from .cameras import UNKNOWN_FOLDER, sanitize_folder_name

_PRIORITY = {"raw": 0, "jpg": 1, "video": 2, "sidecar": 3}


def day_folder_name(day: str, event: str) -> str:
    event = sanitize_folder_name(event or "")
    return f"{day} - {event}" if event else day


def _base_name(files: list[dict], rename_by_date: bool) -> str:
    main = min(files, key=lambda f: _PRIORITY.get(f["category"], 9))
    if not rename_by_date:
        return Path(main["name"]).stem
    return datetime.fromisoformat(main["capture_dt"]).strftime("%Y%m%d_%H%M%S")


def _target_dir(file_entry: dict, camera_folder: str, day_name: str, config: dict,
                group_videos_by_day: bool) -> Path:
    if file_entry["category"] == "video":
        parts = [config["videos_dir_name"], camera_folder]
        if group_videos_by_day:
            parts.append(day_name)
        return Path(*parts)

    parts = [config["photos_dir_name"], camera_folder, day_name]
    if file_entry["category"] == "raw":
        parts.append(config["raw_dir_name"])
    else:
        # Las fotos normales van directas a la carpeta del día. Solo los RAW se apartan,
        # que es lo que de verdad conviene separar: meter los JPG en su propia subcarpeta
        # añadía un nivel que no aporta nada cuando, además, es el caso habitual.
        # `jpg_dir_name` vacío (lo normal) significa "sin subcarpeta".
        subfolder = (config.get("jpg_dir_name") or "").strip()
        if subfolder:
            parts.append(subfolder)
    return Path(*parts)


def build_plan(scan: dict, config: dict, camera_folders: dict, events: dict,
               options: dict) -> dict:
    """Devuelve {'items': [...], 'tree': {...}, 'totals': {...}}.

    `camera_folders` mapea clave de cámara -> nombre de carpeta ya confirmado por el
    usuario, y `events` mapea "<clave cámara>|<día>" -> nombre del evento de ese día.
    """
    destination = Path(config["destination"]).expanduser()
    rename_by_date = bool(options.get("rename_by_date", config["rename_by_date"]))
    group_videos_by_day = bool(options.get("group_videos_by_day", config["group_videos_by_day"]))
    skip_duplicates = bool(options.get("skip_duplicates", config["skip_duplicates"]))
    excluded_days = set(options.get("excluded_days") or [])

    groups: dict[str, list[dict]] = {}
    skipped = []
    for entry in scan["files"]:
        if f"{entry['camera_key']}|{entry['day']}" in excluded_days:
            continue
        if skip_duplicates and entry["duplicate"]:
            skipped.append(entry)
            continue
        groups.setdefault(entry["group"], []).append(entry)

    used_names: set[str] = set()
    items = []

    for group_key in sorted(groups):
        files = groups[group_key]
        main = min(files, key=lambda f: _PRIORITY.get(f["category"], 9))
        camera_key = main["camera_key"]
        camera_folder = sanitize_folder_name(camera_folders.get(camera_key, "")) or UNKNOWN_FOLDER
        day_name = day_folder_name(main["day"], events.get(f"{camera_key}|{main['day']}", ""))

        dirs = {
            f["path"]: _target_dir(f, camera_folder, day_name, config, group_videos_by_day)
            for f in files
        }
        # Los sidecars acompañan al fichero principal de su grupo, no van sueltos.
        for f in files:
            if f["category"] == "sidecar":
                dirs[f["path"]] = dirs[main["path"]]

        # El nombre se decide por grupo, no por fichero: así un RAW y su JPG mantienen el
        # mismo nombre base aunque acaben en carpetas distintas, y siguen emparejados.
        base = _base_name(files, rename_by_date)
        stem = base
        suffix_index = 1
        while True:
            collisions = [
                str(dirs[f["path"]] / f"{stem}{Path(f['name']).suffix}") for f in files
            ]
            taken = any(c in used_names for c in collisions) or any(
                (destination / c).exists() for c in collisions
            )
            if not taken:
                used_names.update(collisions)
                break
            suffix_index += 1
            stem = f"{base}_{suffix_index}"

        for f in files:
            relative = dirs[f["path"]] / f"{stem}{Path(f['name']).suffix}"
            items.append({
                **f,
                "dest_relative": str(relative),
                "dest": str(destination / relative),
                "camera_folder": camera_folder,
                "day_folder": day_name,
            })

    items.sort(key=lambda i: i["dest_relative"])

    tree: dict[str, dict] = {}
    for item in items:
        folder = str(Path(item["dest_relative"]).parent)
        node = tree.setdefault(folder, {"files": 0, "bytes": 0})
        node["files"] += 1
        node["bytes"] += item["size"]

    return {
        "destination": str(destination),
        "items": items,
        "tree": [{"folder": k, **v} for k, v in sorted(tree.items())],
        "totals": {
            "files": len(items),
            "bytes": sum(i["size"] for i in items),
            "skipped_duplicates": len(skipped),
        },
    }


def free_space(destination: str) -> int | None:
    """Bytes libres en el volumen del destino, subiendo hasta el primer padre existente."""
    path = Path(destination).expanduser()
    while not path.exists() and path != path.parent:
        path = path.parent
    try:
        return shutil.disk_usage(path).free
    except OSError:
        return None
