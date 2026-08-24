"""Restos de descargas del móvil hechas con el flujo anterior.

**Ya no se descarga a ninguna carpeta intermedia**: desde `mtp_scan.py`, el móvil es un
origen más y sus archivos se bajan directamente a su destino final. Este módulo solo
queda para recoger lo que dejó el flujo antiguo — material que se descargó a
`~/.conversor-importador/descargas-movil/` y quizá nunca se llegó a importar — y poder
importarlo o borrarlo desde la interfaz.

Cuando esa carpeta esté vacía, este módulo se puede eliminar entero.
"""

import shutil
from pathlib import Path

from .config import CONFIG_DIR

DOWNLOAD_DIR = CONFIG_DIR / "descargas-movil"


def pending_downloads() -> list[dict]:
    """Descargas del flujo antiguo que siguen en disco sin haberse importado.

    La carpeta está oculta, así que sin esto el material desaparecía de la vista si no se
    completaba la importación en el momento — que es justo lo que pasó la primera vez que
    se usó, y una de las razones para quitar el paso intermedio.
    """
    if not DOWNLOAD_DIR.is_dir():
        return []
    found = []
    for path in sorted(DOWNLOAD_DIR.iterdir(), reverse=True):
        if not path.is_dir():
            continue
        # Los .parcial son restos de una descarga cortada: no son material importable.
        files = [f for f in path.rglob("*") if f.is_file() and f.suffix != ".parcial"]
        partials = [f for f in path.rglob("*.parcial") if f.is_file()]
        if files or partials:
            found.append({
                "path": str(path),
                "name": path.name,
                "files": len(files),
                "bytes": sum(f.stat().st_size for f in files),
                "partial": len(partials),
            })
    return found


def cleanup(path: str) -> bool:
    """Borra una carpeta de descarga ya importada. Solo dentro de DOWNLOAD_DIR."""
    target = Path(path).expanduser().resolve()
    try:
        # Nunca borrar fuera de la carpeta de descargas, pase lo que pase por parámetro.
        target.relative_to(DOWNLOAD_DIR.resolve())
    except ValueError:
        return False
    if not target.is_dir():
        return False
    shutil.rmtree(target)
    return True
