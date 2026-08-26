"""Descifra la copia de seguridad de WhatsApp desde la terminal.

**Lo normal es hacerlo desde la app** (sección WhatsApp), que además se encarga de
descargar la copia del móvil. Esto queda para cuando interesa una terminal: probar otra
copia distinta, un fichero traído a mano, o automatizarlo.

La lógica de verdad vive en `whatsapp/backup.py`; aquí solo se pide la clave sin hacer
eco de ella y se imprime el resumen.

    python3 laboratorio/whatsapp/descifra.py [ruta al .crypt15]
"""

import os
import sys
from getpass import getpass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from whatsapp import backup                                          # noqa: E402
from whatsapp.config import CIFRADA                                  # noqa: E402


def main() -> None:
    cifrada = Path(sys.argv[1]).expanduser() if len(sys.argv) > 1 else CIFRADA
    if not cifrada.is_file():
        raise SystemExit(f"No existe: {cifrada}")
    print(f"Copia cifrada: {cifrada}  ({cifrada.stat().st_size / 1e6:.1f} MB)")

    # `WA_KEY` evita teclearla dos veces, pero queda en el historial del shell si se
    # escribe en la misma línea. Mejor exportarla desde el gestor de contraseñas.
    clave = os.environ.get("WA_KEY") or getpass(
        "Clave de 64 dígitos (no se verá al teclearla; los espacios dan igual): ")

    try:
        salida = backup.descifra(clave, cifrada)
    except backup.BackupError as exc:
        raise SystemExit(str(exc))
    finally:
        del clave

    print(f"\nDescifrada en: {salida}")
    resumen = backup.resumen(salida)
    print(f"{resumen['total_tablas']} tablas, {resumen['size'] / 1e6:.1f} MB")
    for t in resumen["tablas"]:
        filas = f"{t['filas']:,}" if t["presente"] else "no está"
        print(f"  {t['tabla']:16} {filas:>12}   {t['para_que']}")
    if resumen["first_day"]:
        print(f"\nMensajes desde {resumen['first_day']} hasta {resumen['last_day']}.")
    print("\nEse .db tiene TODAS tus conversaciones en claro. Trátalo como tal.")


if __name__ == "__main__":
    main()
