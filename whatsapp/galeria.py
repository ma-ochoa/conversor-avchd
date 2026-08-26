"""Galería de medios organizada por conversación, y limpieza de lo copiado.

**El puente entre las dos mitades.** La base de datos sabe a qué chat pertenece cada
archivo pero no dónde está en el ordenador; el registro de copia sabe dónde está cada
archivo pero no de qué chat vino. Aquí se cruzan, y ese cruce es lo que permite lo demás:
ver las fotos agrupadas por conversación, saltar de una foto a su punto del chat, y borrar
del disco lo que no interesa guardar.

**La llave del cruce es el nombre del fichero.** `message_media.file_path` guarda la ruta
tal cual estaba en el móvil (`Media/WhatsApp Images/IMG-20260819-WA0012.jpg`) y el registro
guarda dónde acabó en el ordenador. El nombre es común a los dos y WhatsApp lo garantiza
único, que es exactamente por lo que `media.py` **nunca renombra**.

**No todo lo que está en la base está en el disco.** Sobre una base real: 98.887 medios
registrados frente a 53.125 ficheros en el móvil. WhatsApp descarga bajo demanda y libera
espacio por su cuenta, así que la mitad de los mensajes con foto apuntan a algo que ya no
existe. La interfaz tiene que enseñar ese hueco, no fingir que no está.
"""

import os
from pathlib import Path

from . import history
from .chats import _bonito, _con, _nombres, tipo_de

# Qué tipos de mensaje son "medio visual" a efectos de galería.
VISUALES = {"imagen", "video", "gif", "sticker", "notas_video"}


def indice_local() -> dict[str, str]:
    """Nombre de fichero -> dónde está en el ordenador.

    Sale del registro de copia, no de recorrer el disco: recorrer 40.000 ficheros en cada
    carga de la galería sería inaceptable, y el registro ya lo sabe.
    """
    indice = {}
    for entrada in history.load()["copiado"].values():
        nombre = entrada.get("name")
        destino = entrada.get("dest")
        if nombre and destino:
            indice[nombre] = destino
    return indice


def _existe(ruta: str | None) -> bool:
    return bool(ruta) and Path(ruta).is_file()


def chats_con_medios(solo_visuales: bool = True) -> dict:
    """La estructura virtual: qué conversaciones tienen medios y cuántos hay de cada una.

    Es el índice de la galería. Se cuenta lo que dice la base y, aparte, cuántos de esos
    están de verdad en el ordenador — que es la diferencia que importa al limpiar.
    """
    con = _con()
    try:
        nombres = _nombres(con)
        tipos_sql = _filtro_tipos(solo_visuales)
        filas = con.execute(f"""
            SELECT m.chat_row_id                      AS chat_id,
                   c.subject, j.user, j.server, j.raw_string,
                   count(*)                           AS medios,
                   sum(COALESCE(mm.file_size, 0))     AS bytes,
                   min(m.timestamp)                   AS desde,
                   max(m.timestamp)                   AS hasta
              FROM message m
              JOIN message_media mm ON mm.message_row_id = m._id
              JOIN chat c           ON c._id = m.chat_row_id
              JOIN jid j            ON j._id = c.jid_row_id
             WHERE {tipos_sql}
             GROUP BY m.chat_row_id
             ORDER BY medios DESC
        """).fetchall()

        salida = [{
            "chat_id": f["chat_id"],
            "nombre": f["subject"] or _bonito(f["raw_string"], f["user"], f["server"], nombres),
            "es_grupo": f["server"] == "g.us",
            "medios": f["medios"],
            "bytes": f["bytes"] or 0,
            "desde": f["desde"],
            "hasta": f["hasta"],
        } for f in filas]
        return {"total": len(salida), "chats": salida}
    finally:
        con.close()


def _filtro_tipos(solo_visuales: bool) -> str:
    """Qué cuenta como «visual».

    Se filtra por **mime**, no por lista de `message_type`: WhatsApp sigue añadiendo
    códigos (en una base real había seis sin identificar, todos con foto o vídeo dentro)
    y una lista fija los habría dejado fuera sin decir nada.
    """
    if not solo_visuales:
        return "mm.file_path IS NOT NULL"
    return "(mm.mime_type LIKE 'image/%' OR mm.mime_type LIKE 'video/%')"


def medios_de_chat(chat_id: int, solo_visuales: bool = True,
                   solo_en_disco: bool = False, limit: int = 500,
                   offset: int = 0) -> dict:
    """Los medios de una conversación, con dónde está cada uno en el ordenador.

    `solo_en_disco` deja fuera lo que la base conoce pero ya no existe: es el modo útil
    para limpiar, porque solo se puede borrar lo que se tiene.
    """
    con = _con()
    try:
        nombres = _nombres(con)
        cabecera = con.execute("""
            SELECT c._id, c.subject, j.user, j.server, j.raw_string
              FROM chat c JOIN jid j ON j._id = c.jid_row_id WHERE c._id = ?
        """, (chat_id,)).fetchone()
        if not cabecera:
            raise ValueError(f"No hay ninguna conversación con id {chat_id}.")

        filas = con.execute(f"""
            SELECT m._id, m.from_me, m.timestamp, m.message_type, m.text_data,
                   mm.file_path, mm.file_size, mm.mime_type, mm.media_caption,
                   mm.media_duration, mm.width, mm.height,
                   s.user AS autor_user, s.server AS autor_server, s.raw_string AS autor_raw
              FROM message m
              JOIN message_media mm ON mm.message_row_id = m._id
              LEFT JOIN jid s       ON s._id = m.sender_jid_row_id
             WHERE m.chat_row_id = ? AND {_filtro_tipos(solo_visuales)}
             ORDER BY m.timestamp DESC
        """, (chat_id,)).fetchall()

        indice = indice_local()
        medios = []
        for f in filas:
            nombre = Path(f["file_path"]).name if f["file_path"] else None
            local = indice.get(nombre) if nombre else None
            en_disco = _existe(local)
            if solo_en_disco and not en_disco:
                continue
            medios.append({
                "mensaje_id": f["_id"],
                "chat_id": chat_id,
                "nombre": nombre,
                "tipo": tipo_de(f["message_type"], f["mime_type"]),
                "mio": bool(f["from_me"]),
                "fecha": f["timestamp"],
                "bytes": f["file_size"],
                "mime": f["mime_type"],
                "pie": f["media_caption"],
                "duracion": f["media_duration"],
                "ancho": f["width"], "alto": f["height"],
                "autor": (None if f["from_me"] else
                          _bonito(f["autor_raw"], f["autor_user"], f["autor_server"], nombres)),
                "local": local if en_disco else None,
                "en_disco": en_disco,
            })

        return {
            "chat": {
                "id": cabecera["_id"],
                "nombre": cabecera["subject"] or _bonito(
                    cabecera["raw_string"], cabecera["user"], cabecera["server"], nombres),
            },
            "total": len(medios),
            "en_disco": sum(1 for m in medios if m["en_disco"]),
            "medios": medios[offset:offset + limit],
        }
    finally:
        con.close()


def donde_esta(nombre: str) -> dict:
    """Búsqueda cruzada: dado un fichero, en qué conversaciones aparece y en qué mensaje.

    Un mismo archivo puede estar en varias conversaciones —un reenvío conserva el nombre—
    así que devuelve una lista, no un único resultado. Es la base del salto «de esta foto
    a su punto del chat».
    """
    con = _con()
    try:
        nombres = _nombres(con)
        filas = con.execute("""
            SELECT m._id, m.chat_row_id, m.timestamp, m.from_me, m.message_type,
                   mm.mime_type, mm.media_caption, c.subject, j.user, j.server, j.raw_string
              FROM message_media mm
              JOIN message m ON m._id = mm.message_row_id
              JOIN chat c    ON c._id = m.chat_row_id
              JOIN jid j     ON j._id = c.jid_row_id
             WHERE mm.file_path LIKE ?
             ORDER BY m.timestamp
        """, (f"%/{nombre}",)).fetchall()

        return {
            "nombre": nombre,
            "apariciones": [{
                "mensaje_id": f["_id"],
                "chat_id": f["chat_row_id"],
                "chat": f["subject"] or _bonito(f["raw_string"], f["user"], f["server"], nombres),
                "fecha": f["timestamp"],
                "mio": bool(f["from_me"]),
                "tipo": tipo_de(f["message_type"], f["mime_type"]),
                "pie": f["media_caption"],
            } for f in filas],
        }
    finally:
        con.close()


def repetidos(minimo: int = 2, limit: int = 200) -> dict:
    """Ficheros que aparecen en más de una conversación: reenvíos y material duplicado.

    Es lo que permite decidir qué se puede borrar sin perder nada, y de paso enseña por
    dónde ha circulado una imagen.
    """
    con = _con()
    try:
        filas = con.execute("""
            SELECT mm.file_path,
                   count(DISTINCT m.chat_row_id) AS chats,
                   count(*)                      AS veces,
                   max(mm.file_size)             AS bytes
              FROM message_media mm
              JOIN message m ON m._id = mm.message_row_id
             WHERE mm.file_path IS NOT NULL
             GROUP BY mm.file_path
            HAVING chats >= ?
             ORDER BY chats DESC, veces DESC
             LIMIT ?
        """, (minimo, limit)).fetchall()

        indice = indice_local()
        salida = []
        for f in filas:
            nombre = Path(f["file_path"]).name
            local = indice.get(nombre)
            salida.append({"nombre": nombre, "chats": f["chats"], "veces": f["veces"],
                           "bytes": f["bytes"], "local": local if _existe(local) else None})
        return {"total": len(salida), "ficheros": salida}
    finally:
        con.close()


# ------------------------------------------------------------------------ limpieza

def borra(rutas: list[str]) -> dict:
    """Borra ficheros del ordenador y los saca del registro de copia.

    **Solo toca lo que está dentro de la carpeta de destino configurada.** Es una
    salvaguarda deliberada: la lista de rutas llega desde el navegador, y sin esta
    comprobación una petición manipulada podría pedir el borrado de cualquier cosa.

    No se toca nada del móvil: esto limpia la copia local, no el original.
    """
    from .config import load_config

    raiz = Path(load_config()["destination"]).expanduser().resolve()
    borrados, rechazados, fallidos = [], [], []

    for ruta in rutas:
        p = Path(ruta).expanduser()
        try:
            resuelta = p.resolve()
            dentro = resuelta.is_relative_to(raiz)
        except (OSError, ValueError):
            dentro = False
        if not dentro:
            rechazados.append(str(p))
            continue
        try:
            resuelta.unlink()
            borrados.append(str(resuelta))
        except FileNotFoundError:
            # Ya no estaba: cuenta como borrado para que el registro quede coherente.
            borrados.append(str(resuelta))
        except OSError as exc:
            fallidos.append(f"{p.name}: {exc}")

    if borrados:
        history.olvida_destinos(borrados)
        _limpia_vacias(raiz)

    return {"borrados": len(borrados), "rechazados": rechazados, "fallidos": fallidos,
            "bytes_liberados": 0}


def _limpia_vacias(raiz: Path) -> None:
    """Quita las carpetas que se hayan quedado sin nada. Un árbol de meses vacíos es
    ruido que estorba al navegar por el destino."""
    for carpeta, _, _ in sorted(os.walk(raiz), key=lambda t: -len(t[0])):
        p = Path(carpeta)
        if p == raiz:
            continue
        try:
            next(p.iterdir())
        except StopIteration:
            p.rmdir()
        except OSError:
            continue
