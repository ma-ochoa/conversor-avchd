"""Copia de seguridad del material de WhatsApp, en paralelo al flujo de fotos.

**Por qué no es un origen más.** El importador de fotos gira sobre cámara → día → evento,
y renombra por fecha de captura. Nada de eso vale aquí: WhatsApp recomprime lo que envía y
**borra el EXIF**, así que no hay fecha de captura, ni GPS, ni modelo de cámara. Lo único
que queda es el nombre del fichero, que WhatsApp construye siempre igual:

    IMG-20260819-WA0012.jpg
    ^^^ ^^^^^^^^ ^^^^^^
    |   |        contador del día (NO es la hora)
    |   día en que WhatsApp guardó el archivo
    tipo: IMG, VID, AUD, PTT (nota de voz), PTV (nota de vídeo), DOC, STK, GIF…
          — no se da por cerrada la lista, ver `_NAME_RE`

Por eso **nunca se renombra**: ese nombre es la única llave que permitirá luego cruzar
cada archivo con su conversación, ya venga el cruce de un chat exportado o de la base de
datos descifrada. Renombrar por fecha, como se hace con las fotos, destruiría el vínculo.

**Dónde vive.** En Android es siempre la misma ruta, lo que hace que esto funcione en
cualquier móvil sin configurar nada. Desde Android 11 está bajo `Android/media/`, que el
explorador de carpetas del importador esconde a propósito porque tiene cientos
de carpetas de aplicaciones; aquí se va directo a la ruta conocida en vez de navegar.

En iPhone no hay ruta equivalente: el material vive dentro del contenedor de la app, al
que no se llega por USB. Se saca de una copia de seguridad local del móvil, y por eso
`scan_folder()` existe además de `scan_phone()`: una vez extraída la copia, la carpeta
resultante se escanea igual que si fuera un móvil Android.
"""

import re
from datetime import datetime
from pathlib import Path

from . import dispositivo

# Raíces conocidas, en orden de preferencia. La primera que exista es la que se usa.
MEDIA_ROOTS = (
    # Android 11+ (almacenamiento delimitado). Es la ubicación actual.
    "Android/media/com.whatsapp/WhatsApp/Media",
    # Anterior a Android 11. Sigue existiendo en móviles que vienen de una actualización.
    "WhatsApp/Media",
    # WhatsApp Business, por si el móvil tiene las dos.
    "Android/media/com.whatsapp.w4b/WhatsApp Business/Media",
)

# Subcarpeta de origen -> qué es y dónde acaba. El orden es el de la interfaz.
#
# `default` deja fuera stickers y GIF: son lo que más abulta en número y lo que menos se
# parece a una copia de seguridad que alguien quiera conservar. Se pueden marcar a mano.
KINDS = (
    {"key": "imagenes",   "folder": "WhatsApp Images",        "label": "Imágenes",
     "dest": "Imágenes",     "prefix": "IMG", "default": True,  "fem": True},
    {"key": "video",      "folder": "WhatsApp Video",         "label": "Vídeos",
     "dest": "Vídeos",       "prefix": "VID", "default": True,  "fem": False},
    {"key": "documentos", "folder": "WhatsApp Documents",     "label": "Documentos",
     "dest": "Documentos",   "prefix": "DOC", "default": True,  "fem": False},
    {"key": "notas",      "folder": "WhatsApp Voice Notes",   "label": "Notas de voz",
     "dest": "Notas de voz", "prefix": "PTT", "default": True,  "fem": True},
    {"key": "audio",      "folder": "WhatsApp Audio",         "label": "Audio",
     "dest": "Audio",        "prefix": "AUD", "default": True,  "fem": False},
    {"key": "gifs",       "folder": "WhatsApp Animated Gifs", "label": "GIF animados",
     "dest": "GIF",          "prefix": "GIF", "default": False, "fem": False},
    {"key": "stickers",   "folder": "WhatsApp Stickers",      "label": "Stickers",
     "dest": "Stickers",     "prefix": "STK", "default": False, "fem": False},
    # Las notas de vídeo (las redondas) tienen carpeta propia y nombre `PTV-`. Estaban
    # cayendo dentro de «Vídeos», donde se confundían con los vídeos normales.
    {"key": "notas_video", "folder": "WhatsApp Video Notes",  "label": "Notas de vídeo",
     "dest": "Notas de vídeo", "prefix": "PTV", "default": True, "fem": True},
    # **Los estados**. Duran 24 h en la app y desaparecen, pero los ficheros siguen en el
    # móvil: es material que no se puede recuperar de ninguna otra forma una vez caduca.
    # El nombre es un hash, no lleva fecha, así que la del fichero es lo único que hay.
    {"key": "estados",    "folder": ".Statuses",              "label": "Estados",
     "dest": "Estados",      "prefix": "",    "default": False, "fem": False},
)

_BY_KEY = {k["key"]: k for k in KINDS}

# Carpetas que existen en el móvil y **se dejan fuera a propósito**, comprobado sobre un
# Galaxy S25 real:
#   · `.Links`   — 2.626 ficheros, 79 MB: miniaturas de vistas previas de enlaces, con
#                  nombre de hash y sin extensión. No son material del usuario.
#   · `.Shared`  — 1.502 ficheros, 217 MB, pero son `.tmp` y `.chck`: restos de
#                  transferencias a medias, no contenido.
#   · `.Thumbs`, `.StickerThumbs` — caché de miniaturas, regenerable.
#   · `WallPaper`, `WhatsApp Profile Photos` — vacías en la práctica.

# Extensiones que WhatsApp llega a guardar. No se filtra por tipo dentro de cada carpeta:
# lo que hay en `WhatsApp Documents` es un documento sea cual sea su extensión.
_EXTENSIONS = {
    ".jpg", ".jpeg", ".png", ".webp", ".gif", ".heic",
    ".mp4", ".3gp", ".mov", ".mkv", ".avi",
    ".opus", ".m4a", ".aac", ".mp3", ".ogg", ".wav", ".amr",
    ".pdf", ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx", ".txt", ".rtf",
    ".zip", ".rar", ".7z", ".csv", ".epub", ".apk", ".vcf",
}

# IMG-20260819-WA0012.jpg — el grupo del medio es el día; WA#### es un contador, no la hora.
#
# El prefijo NO se enumera. Con un móvil real delante aparecieron `PTV` (notas de vídeo,
# las redondas) que no estaba en la lista, y entonces esos archivos perdían la fecha del
# nombre y caían a la del fichero. La forma `XXX-AAAAMMDD-WA####` es bastante distintiva
# como para aceptar cualquier prefijo y no volver a quedarse corto cuando WhatsApp
# invente el siguiente.
_NAME_RE = re.compile(r"^([A-Z]{2,4})-(\d{8})-WA(\d{4})", re.IGNORECASE)

SENT_FOLDER = "Sent"


class WhatsAppNotFound(RuntimeError):
    """No hay carpeta de WhatsApp donde se ha mirado."""


def parse_name(name: str) -> dict | None:
    """Tipo, día y contador de un nombre de WhatsApp. `None` si no sigue el patrón."""
    match = _NAME_RE.match(name)
    if not match:
        return None
    try:
        day = datetime.strptime(match.group(2), "%Y%m%d").date()
    except ValueError:
        return None
    return {"prefix": match.group(1).upper(), "day": day.isoformat(),
            "counter": int(match.group(3))}


def _entry(name: str, kind_key: str, sent: bool, size: int, mtime_iso: str | None,
           source_path: str, mtp_folder: str | None = None) -> dict:
    """Normaliza un fichero, venga del móvil o de una carpeta en disco.

    La fecha sale de dos sitios que hay que combinar con cuidado: el **nombre** da el día
    y es la referencia buena (lo pone WhatsApp al recibir el mensaje), mientras que la
    **fecha del fichero** da la hora pero puede haberse movido si el archivo se copió de
    un sitio a otro. Se usa la hora solo cuando ambas coinciden en el día.
    """
    parsed = parse_name(name)
    moment = None
    if mtime_iso:
        try:
            moment = datetime.fromisoformat(mtime_iso)
        except ValueError:
            moment = None

    if parsed and moment and moment.date().isoformat() == parsed["day"]:
        day, when, source = parsed["day"], moment, "nombre y hora del archivo"
    elif parsed:
        day, when, source = parsed["day"], datetime.fromisoformat(parsed["day"]), "nombre"
    elif moment:
        day, when, source = moment.date().isoformat(), moment, "archivo"
    else:
        day, when, source = None, None, "desconocida"

    return {
        "name": name,
        "kind": kind_key,
        "sent": sent,
        "size": size or 0,
        "day": day,
        "moment": when.isoformat() if when else None,
        "date_source": source,
        "path": source_path,
        "mtp_folder": mtp_folder,
    }


# --------------------------------------------------------------------------- el móvil

def find_root() -> str:
    """Ruta MTP de la carpeta `Media` de WhatsApp en el móvil conectado.

    Se prueban las raíces conocidas dentro de cada almacenamiento (memoria interna y
    tarjeta). Lanza `WhatsAppNotFound` si no hay ninguna.
    """
    # Sin esto, no tener el móvil enchufado acababa devolviendo el error genérico de
    # gphoto2 («Esa carpeta ya no existe en el móvil»), que no dice nada de lo que pasa.
    if not dispositivo.disponible():
        raise WhatsAppNotFound(
            "Para leer WhatsApp del móvil hace falta gphoto2. Instálalo con:\n"
            "    brew install libgphoto2\n    pip install gphoto2"
        )
    if not dispositivo.conectados():
        raise WhatsAppNotFound(
            "No hay ningún móvil accesible. Conéctalo por USB, desbloquéalo y elige "
            "«Transferencia de archivos (MTP)» en el aviso que sale en el móvil — en "
            "modo «Transferencia de imágenes (PTP)» no se ven las carpetas."
        )

    try:
        stores = [s["path"] for s in dispositivo.lista_carpetas("/")]
    except Exception as exc:
        raise WhatsAppNotFound(f"No se pudo leer el almacenamiento del móvil: {exc}") from exc

    # **Cero almacenamientos con el móvil detectado** es un caso propio, y el más
    # frecuente: el teléfono está enchufado y gphoto2 lo enumera, pero mientras esté
    # bloqueado o en «solo carga» no expone ni la memoria interna. Decir «no se encuentra
    # WhatsApp» aquí manda a buscar en el sitio equivocado.
    if not stores:
        raise WhatsAppNotFound(
            "El móvil está conectado pero no deja ver su almacenamiento. Suele ser una "
            "de estas dos cosas:\n"
            "  · está bloqueado — desbloquéalo con el cable puesto;\n"
            "  · el USB está en «solo carga» — despliega la notificación del móvil y "
            "elige «Transferencia de archivos» (MTP).\n"
            "Después vuelve a intentarlo."
        )

    for store in stores:
        for root in MEDIA_ROOTS:
            candidate = f"{store.rstrip('/')}/{root}"
            try:
                carpetas = dispositivo.lista_carpetas(candidate)
            except Exception:
                continue
            if any(f["name"].lower().startswith("whatsapp ") for f in carpetas):
                return candidate
    raise WhatsAppNotFound(
        "No se ha encontrado la carpeta de WhatsApp en el móvil. Comprueba que está "
        "en modo «Transferencia de archivos» (MTP) y que WhatsApp tiene material "
        "guardado en este dispositivo."
    )


def scan_phone(root: str | None = None, kinds: list[str] | None = None,
               progress_cb=None) -> dict:
    """Inventario del material de WhatsApp en el móvil, sin descargar nada."""
    root = root or find_root()
    entries: list[dict] = []

    for kind in _selected(kinds, all_by_default=True):
        base = f"{root}/{kind['folder']}"
        try:
            dispositivo.lista_carpetas(base)
        except Exception:
            continue
        if progress_cb:
            progress_cb(kind["label"], len(entries))

        # `Sent/` son los archivos que enviaste tú; las notas de voz se reparten además
        # en subcarpetas por mes (`202608/`), así que se baja recursivamente y el envío
        # se decide por si la ruta pasa por `Sent`.
        for found in dispositivo.lista_ficheros(base, extensiones=_EXTENSIONS):
            relative = found["folder"][len(base):].strip("/")
            sent = any(part.lower() == SENT_FOLDER.lower() for part in relative.split("/"))
            entries.append(_entry(
                found["name"], kind["key"], sent, found.get("size") or 0,
                found.get("captured"), found["path"], mtp_folder=found["folder"],
            ))

    return _summarize(entries, source=root, origin="movil")


# ------------------------------------------------------------------- una carpeta local

def scan_folder(path: Path, kinds: list[str] | None = None) -> dict:
    """Lo mismo, pero sobre una carpeta `Media` ya volcada en disco.

    Es la puerta de entrada del iPhone: una vez extraído el material de la copia de
    seguridad del móvil, se escanea con esto y sigue el mismo camino que Android.
    """
    path = Path(path).expanduser()
    if not path.is_dir():
        raise WhatsAppNotFound(f"No es una carpeta: {path}")

    # Se admite tanto la carpeta `Media` como la que la contiene.
    if not any((path / k["folder"]).is_dir() for k in KINDS):
        for root in MEDIA_ROOTS:
            if (path / root).is_dir():
                path = path / root
                break
        else:
            raise WhatsAppNotFound(
                f"En {path} no hay ninguna carpeta «WhatsApp Images», «WhatsApp Video»…"
            )

    entries = []
    for kind in _selected(kinds, all_by_default=True):
        base = path / kind["folder"]
        if not base.is_dir():
            continue
        for found in sorted(base.rglob("*")):
            if not found.is_file() or found.name.startswith("."):
                continue
            if found.suffix.lower() not in _EXTENSIONS:
                continue
            relative = found.parent.relative_to(base)
            sent = any(p.lower() == SENT_FOLDER.lower() for p in relative.parts)
            stat = found.stat()
            entries.append(_entry(
                found.name, kind["key"], sent, stat.st_size,
                datetime.fromtimestamp(stat.st_mtime).isoformat(), str(found),
            ))

    return _summarize(entries, source=str(path), origin="carpeta")


# ------------------------------------------------------------------------------ común

def _selected(kinds: list[str] | None, all_by_default: bool = False) -> list[dict]:
    """Qué tipos entran. Sin lista explícita, **escanear** mira todo y **copiar** solo lo
    marcado por defecto: el inventario tiene que ser completo para poder enseñar qué hay
    (incluidos los stickers, aunque luego no se traigan), mientras que la copia no debe
    llevarse nada que no se haya pedido."""
    if kinds is None:
        return list(KINDS) if all_by_default else [k for k in KINDS if k["default"]]
    return [k for k in KINDS if k["key"] in set(kinds)]


def _summarize(entries: list[dict], source: str, origin: str) -> dict:
    by_kind = {}
    for kind in KINDS:
        rows = [e for e in entries if e["kind"] == kind["key"]]
        if not rows:
            continue
        by_kind[kind["key"]] = {
            "key": kind["key"],
            "label": kind["label"],
            "files": len(rows),
            "sent": sum(1 for e in rows if e["sent"]),
            "received": sum(1 for e in rows if not e["sent"]),
            "bytes": sum(e["size"] for e in rows),
        }

    days = sorted({e["day"] for e in entries if e["day"]})
    entries.sort(key=lambda e: (e["day"] or "", e["name"]))
    return {
        "source": source,
        "origin": origin,
        "entries": entries,
        "kinds": [by_kind[k["key"]] for k in KINDS if k["key"] in by_kind],
        "totals": {
            "files": len(entries),
            "bytes": sum(e["size"] for e in entries),
            "sent": sum(1 for e in entries if e["sent"]),
            "received": sum(1 for e in entries if not e["sent"]),
            "first_day": days[0] if days else None,
            "last_day": days[-1] if days else None,
        },
    }


def import_key(entry: dict) -> str:
    """Identidad de un archivo de WhatsApp: **solo el nombre**.

    WhatsApp lo garantiza único — lleva el día y un contador que no reutiliza — y ese
    nombre es además la llave con la que se cruzan la base de datos y el disco.

    No se mete el tamaño, y esa es una decisión con consecuencias: el inventario ya no
    pregunta el tamaño de cada fichero al móvil (una llamada por fichero, decenas de
    miles de viajes por USB), así que en el momento de decidir si algo está copiado
    **no se conoce**. Meterlo en la llave obligaría a preguntarlo siempre.

    Tampoco se mete la fecha: la del fichero puede cambiar al copiarlo, y entonces el
    mismo archivo parecería nuevo.
    """
    return f"wa|{entry['name']}"


def dest_relative(entry: dict) -> str:
    """Dónde acaba dentro de la carpeta de WhatsApp: tipo / dirección / mes.

    El mes evita carpetas de decenas de miles de archivos, que es lo que hay en un móvil
    con años de uso. El nombre no se toca nunca (ver la explicación de arriba).
    """
    kind = _BY_KEY.get(entry["kind"])
    # Concuerdan con el tipo: "Imágenes/Recibidas" pero "Vídeos/Recibidos".
    fem = bool(kind and kind.get("fem"))
    direccion = ("Enviadas" if fem else "Enviados") if entry["sent"] else \
                ("Recibidas" if fem else "Recibidos")
    parts = [kind["dest"] if kind else "Otros", direccion]
    parts.append(entry["day"][:7] if entry["day"] else "Sin fecha")
    return str(Path(*parts) / entry["name"])


def build_plan(scan: dict, destination: str, kinds: list[str] | None = None,
               already_imported: set[str] | None = None,
               skip_duplicates: bool = True) -> dict:
    """Qué archivo acaba exactamente en qué ruta. Sin efectos en disco."""
    already_imported = already_imported or set()
    root = Path(destination).expanduser()
    wanted = {k["key"] for k in _selected(kinds)}

    items, skipped = [], 0
    tree: dict[str, dict] = {}
    for entry in scan["entries"]:
        if entry["kind"] not in wanted:
            continue
        duplicate = import_key(entry) in already_imported
        if duplicate and skip_duplicates:
            skipped += 1
            continue
        relative = dest_relative(entry)
        items.append({**entry, "duplicate": duplicate,
                      "dest_relative": relative, "dest": str(root / relative)})
        node = tree.setdefault(str(Path(relative).parent), {"files": 0, "bytes": 0})
        node["files"] += 1
        node["bytes"] += entry["size"]

    items.sort(key=lambda i: i["dest_relative"])
    return {
        "destination": str(root),
        "items": items,
        "tree": [{"folder": k, **v} for k, v in sorted(tree.items())],
        "totals": {
            "files": len(items),
            "bytes": sum(i["size"] or 0 for i in items),
            "skipped_duplicates": skipped,
            # Cuántos vienen sin tamaño. No es un fallo: el inventario no se lo pregunta
            # al móvil a propósito (ver `import_key`), así que el total solo es fiable
            # cuando este número es cero. Quien decida sobre el espacio libre tiene que
            # mirarlo, en vez de fiarse de un total que se queda corto.
            "sin_tamano": sum(1 for i in items if not i["size"]),
        },
    }
