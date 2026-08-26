"""Listar carpetas sin que la app se quede colgada.

En macOS, las carpetas protegidas por TCC (Escritorio, Descargas, Documentos) no dan
error cuando el proceso no tiene permiso: la llamada al sistema simplemente NO VUELVE
(el sistema espera a un diálogo de autorización que en un proceso lanzado desde la
terminal puede no llegar a aparecer nunca). Un `try/except PermissionError` no protege
de eso, ni tampoco comprobar un deadline dentro del bucle — no se llega a entrar en el
bucle. La única salida es hacer el listado en un hilo del que se pueda desistir.

Ojo: el hilo abandonado sigue vivo hasta que el sistema le conteste (medido: hasta 94
minutos). Por eso es `daemon` — para que no impida cerrar el proceso — y por eso la
carpeta se apunta como bloqueada: reintentarla en cada clic volvería a dejar un hilo
colgado y a hacer esperar al usuario.

NOTA SOBRE LA DUPLICACIÓN CON `importer/sources.py::_listdir()`: es deliberada, no un
descuido. `importer/` está aislado a propósito (no importa nada de `converter/` ni de
Flask) para poder extraerlo como app independiente; compartir este código obligaría a
que uno de los dos dependiera del otro. Si se toca la lógica de aquí, mirar también
allí.
"""

import threading
from pathlib import Path

# Tiempo que se espera a que el sistema conteste antes de dar la carpeta por bloqueada.
# Un listado normal (incluso de miles de entradas) tarda milisegundos; si a los 3 s no
# ha vuelto, es que hay un permiso pendiente y no va a volver.
DEFAULT_TIMEOUT = 3.0

TCC_HINT = (
    "macOS no ha concedido acceso a esta carpeta; dalo en Ajustes del Sistema → "
    "Privacidad y seguridad → Archivos y carpetas"
)

_blocked: set[str] = set()
_lock = threading.Lock()


class FolderAccessBlockedError(Exception):
    """El sistema no contestó al listar la carpeta (permiso TCC sin conceder)."""

    def __init__(self, path: Path):
        self.path = path
        super().__init__(f"{TCC_HINT}. Carpeta: {path}")


def forget_blocked(path: Path | None = None) -> None:
    """Olvida el bloqueo recordado, para volver a probar tras conceder el permiso.
    Sin argumento, olvida todos."""
    with _lock:
        if path is None:
            _blocked.clear()
        else:
            _blocked.discard(str(path))


def list_subdirs(
    path: Path,
    timeout: float = DEFAULT_TIMEOUT,
    retry_blocked: bool = False,
) -> list[Path]:
    """Subcarpetas visibles de `path`, ordenadas por nombre.

    Lanza `FolderAccessBlockedError` si el sistema no contesta a tiempo, y propaga el
    `OSError`/`PermissionError` original si el listado falla de verdad (que sí son
    casos distintos: uno se arregla dando permiso en Ajustes del Sistema, el otro no).

    El filtrado va dentro del hilo a propósito: no solo puede colgarse `iterdir()`,
    también un `is_dir()` sobre una entrada de un montaje de red caído.
    """
    key = str(path)
    with _lock:
        if retry_blocked:
            _blocked.discard(key)
        elif key in _blocked:
            raise FolderAccessBlockedError(path)

    entries: list[Path] = []
    failure: list[OSError | None] = [None]

    def run():
        found = []
        try:
            for p in path.iterdir():
                if p.name.startswith("."):
                    continue
                try:
                    if p.is_dir():
                        found.append(p)
                except OSError:
                    # Una carpeta puntual sin acceso (p. ej. .Trash a través del
                    # montaje de Docker en macOS) no debe tumbar el listado entero.
                    continue
        except OSError as exc:
            failure[0] = exc
            return
        found.sort(key=lambda p: p.name.lower())
        entries.extend(found)

    thread = threading.Thread(target=run, daemon=True)
    thread.start()
    thread.join(timeout)

    if thread.is_alive():
        with _lock:
            _blocked.add(key)
        raise FolderAccessBlockedError(path)
    if failure[0] is not None:
        raise failure[0]
    return entries
