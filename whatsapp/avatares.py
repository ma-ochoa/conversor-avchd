"""Fotos de perfil traídas desde WhatsApp Web.

**Por qué desde ahí y no del móvil.** Los avatares no están en la copia de seguridad ni
en el almacenamiento compartido: viven en `/data/data/com.whatsapp/files/Avatars`, dentro
del directorio privado de la aplicación, donde no llega ni MTP ni `adb` sin root (ver
`documentacion/whatsapp/avatares-y-nombres.md`). En WhatsApp Web, en cambio, la lista de
chats los pinta, y de ahí sí se pueden leer.

**Cómo aparecen en la página, que costó dar con ello.** No son `<img>`: son elementos
`<image>` **dentro de un `<svg>`** con una máscara circular, y su `xlink:href` apunta al
CDN de WhatsApp:

    <svg height="48" width="48">
      <mask id="…"><circle cx="50%" cy="50%" r="calc(50% - 0px)"/></mask>
      <g mask="url(#…)"><image xlink:href="https://media-…cdn.whatsapp.net/v/t61…"/></g>
    </svg>

`querySelectorAll('img')` no los encuentra —`<image>` de SVG es otro elemento— y esa es la
razón de que los primeros intentos dieran uno de setenta y tres.

**Las URLs se descargan sin sesión** (comprobado: 200 y `image/jpeg` con las cookies
omitidas), así que las trae esto en Python y no el navegador. Llevan firma (`oh`) y
caducidad (`oe`) en la propia URL, con unos diez días de margen.

**El casado va por nombre**, porque el jid no aparece en el DOM: lo que se ve en la lista
es el nombre de la agenda o el asunto del grupo. Se cruza con `chat.subject` para los
grupos y con la agenda importada para las personas.
"""

import json
import re
import threading
import time
import unicodedata
from pathlib import Path

from .config import DIR_DATA

DIR_AVATARES = DIR_DATA / "avatares"
INDICE = DIR_AVATARES / "indice.json"
# Resultado del casado: chat -> fichero. Se guarda para que pintar la lista de
# conversaciones no tenga que recalcularlo, que son varios segundos.
CASADOS = DIR_AVATARES / "casados.json"

# Entre descarga y descarga. No es por miedo a un bloqueo —son ficheros de un CDN
# público, servidos con su propia firma— sino por no abrir 400 conexiones de golpe.
PAUSA = 0.25

_lock = threading.Lock()
_trabajo = {"estado": "parado", "hechos": 0, "total": 0, "errores": 0}


def _clave(nombre: str) -> str:
    """Nombre normalizado para comparar: sin acentos, sin signos y en minúsculas.

    Hace falta porque el mismo contacto puede estar como «José Mª Pérez» en un sitio y
    «Jose Ma Perez» en otro, y ninguna de las dos formas es la equivocada.
    """
    limpio = unicodedata.normalize("NFKD", nombre or "")
    limpio = "".join(c for c in limpio if not unicodedata.combining(c))
    limpio = re.sub(r"[^\w\s]", " ", limpio.lower())
    return re.sub(r"\s+", " ", limpio).strip()


def _fichero(nombre: str) -> str:
    """Nombre del fichero de un avatar. Mismo criterio al guardar y al buscarlo."""
    return f"{_clave(nombre).replace(' ', '_')[:80]}.jpg"


_mapa_cache: dict = {}


def mapa_chats() -> dict:
    """chat_id (int) -> ruta del avatar. En memoria: se consulta por cada lista de chats."""
    if not _mapa_cache:
        if not CASADOS.is_file():
            return {}
        try:
            crudo = json.loads(CASADOS.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return {}
        for chat_id, fichero in crudo.items():
            ruta = DIR_AVATARES / fichero
            if ruta.is_file():
                _mapa_cache[int(chat_id)] = ruta
    return _mapa_cache


def ruta_de(chat_id: int) -> Path | None:
    return mapa_chats().get(int(chat_id))


def estado() -> dict:
    guardados = list(DIR_AVATARES.glob("*.jpg")) if DIR_AVATARES.is_dir() else []
    return {"guardados": len(guardados),
            "bytes": sum(f.stat().st_size for f in guardados),
            "trabajo": dict(_trabajo),
            "indice": INDICE.is_file()}


def guarda_lista(pares: list[dict]) -> dict:
    """Apunta los pares (nombre, url) que ha extraído el navegador."""
    utiles = [p for p in pares
              if isinstance(p, dict) and p.get("nombre") and str(p.get("url", "")).startswith("http")]
    DIR_AVATARES.mkdir(parents=True, exist_ok=True)
    INDICE.write_text(json.dumps(utiles, ensure_ascii=False, indent=1), encoding="utf-8")
    return {"recibidos": len(pares), "utiles": len(utiles)}


def descarga_pendientes(progreso=None) -> dict:
    """Baja las fotos que aún no estén en disco. Una por contacto, por su nombre."""
    import requests

    if not INDICE.is_file():
        return {"error": "No hay lista de avatares que descargar."}
    pares = json.loads(INDICE.read_text(encoding="utf-8"))

    DIR_AVATARES.mkdir(parents=True, exist_ok=True)
    _trabajo.update({"estado": "descargando", "hechos": 0, "total": len(pares), "errores": 0})
    sesion = requests.Session()
    for i, p in enumerate(pares, 1):
        destino = DIR_AVATARES / _fichero(p["nombre"])
        if destino.is_file() and destino.stat().st_size > 0:
            _trabajo["hechos"] = i
            continue
        try:
            r = sesion.get(p["url"], timeout=20)
            # Un 403 aquí es la firma caducada, no un bloqueo: hay que volver a extraer
            # la lista desde el navegador, que trae URLs nuevas.
            if r.status_code == 200 and r.content[:3] == b"\xff\xd8\xff":
                destino.write_bytes(r.content)
            else:
                _trabajo["errores"] += 1
        except Exception:
            _trabajo["errores"] += 1
        _trabajo["hechos"] = i
        if progreso:
            progreso(i, len(pares))
        time.sleep(PAUSA)
    _trabajo["estado"] = "terminado"
    return dict(_trabajo)


def casa_con_la_base() -> dict:
    """Cruza cada avatar con su conversación. Devuelve el reparto y lo que no casó."""
    from . import agenda as agenda_externa
    from . import chats

    if not INDICE.is_file():
        return {"error": "No hay lista de avatares."}
    pares = json.loads(INDICE.read_text(encoding="utf-8"))

    con = chats._con()
    try:
        nombres = chats._nombres(con)
        lids = chats._telefonos_de_lid(con)
        por_nombre: dict[str, list] = {}
        for f in con.execute("""
                SELECT c._id, c.subject, j.raw_string, j.user, j.server
                  FROM chat c JOIN jid j ON j._id = c.jid_row_id"""):
            visible = f["subject"] or chats._bonito(f["raw_string"], f["user"], f["server"],
                                                    nombres, lids)
            por_nombre.setdefault(_clave(visible), []).append(
                {"chat_id": f["_id"], "jid": f["raw_string"]})
    finally:
        con.close()

    # Quien no está en la agenda aparece en WhatsApp Web con su propio número por nombre
    # («+34 646 95 61 43»). Esos no casan por texto pero sí por número, que es más fiable
    # que cualquier nombre.
    con = chats._con()
    try:
        por_numero = {}
        for f in con.execute("""
                SELECT c._id, j.user FROM chat c JOIN jid j ON j._id = c.jid_row_id
                 WHERE j.server = 's.whatsapp.net' AND j.user IS NOT NULL"""):
            for llave in agenda_externa._claves(f["user"]):
                por_numero.setdefault(llave, []).append({"chat_id": f["_id"], "jid": f["user"]})
    finally:
        con.close()

    casados, ambiguos, sueltos, por_tel = [], [], [], 0
    for p in pares:
        k = _clave(p["nombre"])
        cand = por_nombre.get(k, [])
        if not cand and re.fullmatch(r"[+\d\s().-]{7,}", p["nombre"] or ""):
            for llave in agenda_externa._claves(p["nombre"]):
                if llave in por_numero:
                    cand = por_numero[llave]
                    por_tel += 1
                    break
        if len(cand) == 1:
            casados.append({"nombre": p["nombre"], **cand[0]})
        elif len(cand) > 1:
            ambiguos.append({"nombre": p["nombre"], "cuantos": len(cand)})
        else:
            sueltos.append(p["nombre"])

    DIR_AVATARES.mkdir(parents=True, exist_ok=True)
    CASADOS.write_text(json.dumps(
        {str(c["chat_id"]): _fichero(c["nombre"]) for c in casados},
        ensure_ascii=False, indent=1), encoding="utf-8")
    _mapa_cache.clear()

    return {"total": len(pares), "casados": len(casados), "por_telefono": por_tel,
            "ambiguos": len(ambiguos), "sin_casar": len(sueltos),
            "detalle_casados": casados, "ejemplos_sin_casar": sueltos[:10]}
