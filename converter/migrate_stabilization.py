"""Migración del esquema antiguo de estabilización (carpeta "estabilizado/"
centralizada + caché ".vidstab_cache/" por hash) al esquema nuevo, co-localizado junto
a cada vídeo ("stabilization_data/" + "<nombre>_stabilized.mp4"). Pensada para
ejecutarse una vez por cada carpeta que tenga contenido con el esquema antiguo:

    python3 -m converter.migrate_stabilization "/ruta/a/la/carpeta"

No borra el vídeo original ni pierde el ya estabilizado — lo MUEVE a su nueva
ubicación (respetando la carpeta de trabajo configurada, si hay una, igual que hacía el
esquema antiguo). Si el análisis (.trf) de algún clip coincide exactamente con los
parámetros con los que se generó, también se migra; si no, simplemente no se arrastra
(se puede volver a analizar cuando haga falta). Seguro de ejecutar más de una vez — las
entradas ya migradas se saltan."""

import hashlib
import json
import shutil
import sys
from pathlib import Path

from .config import resolve_output_base
from .manifest import load_manifest
from .stabilize import (
    DEFAULT_PARAMS,
    _append_log,
    save_stabilize_draft,
    stab_data_dir,
    stabilized_output_path,
)

OLD_STABILIZE_DIR_NAME = "estabilizado"
OLD_CACHE_DIR_NAME = ".vidstab_cache"


def _migrate_cache(root_path: Path, source: Path, old_cache_dir: Path,
                    shakiness: int, accuracy: int) -> bool:
    """Copia el .trf antiguo (si existe uno para esta combinación exacta de
    shakiness/accuracy) a la nueva ubicación. Best-effort: si no hay un .trf que
    corresponda, no pasa nada — se puede volver a analizar cuando haga falta."""
    if not source.exists():
        return False
    key = f"{source}|{shakiness}|{accuracy}"
    digest = hashlib.sha1(key.encode("utf-8")).hexdigest()[:20]
    old_trf = old_cache_dir / f"{digest}.trf"
    old_meta = old_cache_dir / f"{digest}.json"
    if not (old_trf.exists() and old_meta.exists()):
        return False

    try:
        old_meta_data = json.loads(old_meta.read_text())
    except (json.JSONDecodeError, OSError):
        return False

    new_data_dir = stab_data_dir(root_path, source)
    new_data_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy2(old_trf, new_data_dir / f"{source.stem}.trf")
    (new_data_dir / f"{source.stem}_analisis.json").write_text(json.dumps({
        "source_size": source.stat().st_size,
        "shakiness": shakiness, "accuracy": accuracy,
        "stepsize": DEFAULT_PARAMS["stepsize"], "mincontrast": DEFAULT_PARAMS["mincontrast"],
        "stats": old_meta_data.get("stats", {}),
    }, indent=2))
    return True


def migrate(root: str) -> dict:
    root_path = Path(root).expanduser().resolve()
    old_base = resolve_output_base(root_path)  # el esquema antiguo ya respetaba la carpeta de trabajo
    old_dir = old_base / OLD_STABILIZE_DIR_NAME
    old_cache_dir = old_base / OLD_CACHE_DIR_NAME

    report = {"migrated": [], "skipped": [], "missing_source": [], "cache_migrated": []}
    if not old_dir.is_dir():
        return report

    old_manifest = load_manifest(root_path, OLD_STABILIZE_DIR_NAME)
    old_drafts = load_manifest(root_path, OLD_CACHE_DIR_NAME)

    for source_str, entry in old_manifest.items():
        source = Path(source_str)
        old_output = old_dir / entry.get("output", "")
        if not old_output.exists():
            report["skipped"].append(source_str)
            continue

        new_dest = stabilized_output_path(root_path, source)
        if new_dest.exists():
            report["skipped"].append(source_str)
            continue
        if not source.exists():
            report["missing_source"].append(source_str)

        new_dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(old_output), str(new_dest))
        report["migrated"].append({"source": source_str, "old": str(old_output), "new": str(new_dest)})

        if source.exists():
            _append_log(root_path, source, "migrado", {
                "desde": str(old_output), "hasta": str(new_dest),
                "stats_historicas": entry.get("stats", {}),
            })

            draft = old_drafts.get(source_str)
            if draft:
                save_stabilize_draft(root_path, source, draft)

            shakiness = draft.get("shakiness", 5) if draft else 5
            accuracy = draft.get("accuracy", 15) if draft else 15
            if _migrate_cache(root_path, source, old_cache_dir, shakiness, accuracy):
                report["cache_migrated"].append(source_str)

    return report


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Uso: python3 -m converter.migrate_stabilization <carpeta>")
        sys.exit(1)
    result = migrate(sys.argv[1])
    print(json.dumps(result, indent=2, ensure_ascii=False))
