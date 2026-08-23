"""Copia con verificación por checksum.

El borrado en la tarjeta solo puede ofrecerse con seguridad si antes se ha comprobado
que la copia es idéntica al original. Se calcula el hash del origen mientras se copia
(una sola lectura) y después se relee el destino para compararlo.
"""

import hashlib
import os
import shutil
from pathlib import Path

_CHUNK = 1024 * 1024


class VerificationError(RuntimeError):
    pass


def _hash_file(path: Path, progress_cb=None, total: int = 0) -> str:
    digest = hashlib.sha256()
    done = 0
    with open(path, "rb") as f:
        while chunk := f.read(_CHUNK):
            digest.update(chunk)
            done += len(chunk)
            if progress_cb and total:
                progress_cb(done / total)
    return digest.hexdigest()


def copy_verified(source: Path, dest: Path, verify: bool = True, progress_cb=None) -> dict:
    """Copia `source` en `dest` conservando fechas. Devuelve {'sha256', 'size', 'verified'}.

    Escribe primero en un `.parcial` y renombra al terminar, para que una interrupción
    (cierre de la app, tarjeta desconectada) nunca deje un fichero a medias que parezca
    completo en el destino.
    """
    dest.parent.mkdir(parents=True, exist_ok=True)
    size = source.stat().st_size
    partial = dest.with_name(dest.name + ".parcial")

    digest = hashlib.sha256()
    copied = 0
    try:
        with open(source, "rb") as src, open(partial, "wb") as dst:
            while chunk := src.read(_CHUNK):
                dst.write(chunk)
                digest.update(chunk)
                copied += len(chunk)
                if progress_cb and size:
                    # La verificación es la segunda mitad de la barra cuando toca releer.
                    progress_cb(copied / size * (0.5 if verify else 1.0))
            dst.flush()
            os.fsync(dst.fileno())

        shutil.copystat(source, partial)
        source_hash = digest.hexdigest()

        verified = False
        if verify:
            dest_hash = _hash_file(
                partial,
                progress_cb=(lambda f: progress_cb(0.5 + f * 0.5)) if progress_cb else None,
                total=size,
            )
            if dest_hash != source_hash:
                raise VerificationError(
                    f"La copia de {source.name} no coincide con el original (checksum distinto)."
                )
            verified = True

        partial.replace(dest)
    except Exception:
        partial.unlink(missing_ok=True)
        raise

    if progress_cb:
        progress_cb(1.0)
    return {"sha256": source_hash, "size": size, "verified": verified}


def set_file_time(path: Path, timestamp: float) -> None:
    try:
        os.utime(path, (timestamp, timestamp))
    except OSError:
        pass
