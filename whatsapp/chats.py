"""Lectura de la base de datos descifrada: chats, mensajes y agenda.

**Solo lectura, siempre.** Se abre con `mode=ro` y nunca se escribe: esta base es una
copia de seguridad, y si algo se rompe aquí no hay dónde volver a por ella salvo repitiendo
todo el proceso.

Lo aprendido mirando una base real de 611.637 mensajes (Galaxy S25, WhatsApp 2.26):

**Los nombres no están aquí.** `msgstore.db` guarda el asunto de los grupos
(`chat.subject`, 107 de 5.188 chats) y poco más. La agenda vive en `wa.db`, otra base
que WhatsApp guarda aparte. Sin ella, una conversación individual solo puede enseñar el
número. Por eso se adjunta con ATTACH cuando está.

**La tabla `jid` no es la agenda.** Tiene 120.011 filas porque guarda *todo identificador
que la base ha visto alguna vez*: cada miembro de cada grupo, cada canal, cada número que
escribió una vez. Y desde que WhatsApp introdujo los `lid` (identificadores que no revelan
el teléfono), **la misma persona aparece dos veces**, una por servidor. De esas 120.011,
solo 1.569 han escrito algún mensaje.

**Los mensajes eliminados dejan rastro, pero no texto.** Los de tipo 15 son los
«Se eliminó este mensaje»: los 1.568 están en `message_revoked`, con quién y cuándo, pero
`text_data` viene vacío — WhatsApp lo borra de verdad. Ver `hay_texto_borrado()`.
"""

import sqlite3
from pathlib import Path

from .config import AGENDA, DESCIFRADA

# Qué es cada `message.message_type`, deducido cruzando con `message_media.mime_type`
# sobre una base real. No están documentados en ninguna parte oficial.
TIPOS = {
    0: "texto",
    1: "imagen",
    2: "audio",
    3: "video",
    4: "contacto",
    5: "ubicacion",
    7: "sistema",
    9: "documento",
    10: "llamada",
    13: "gif",
    15: "eliminado",       # los 1.568 de la base de prueba están en message_revoked
    20: "sticker",         # image/webp
    42: "efimero",
    64: "eliminado",
    81: "notas_video",       # PTV, las notas de vídeo redondas
    90: "encuesta",
    99: "otro",
}


def tipo_de(message_type: int | None, mime: str | None = None) -> str:
    """Qué es un mensaje, con el mime como red de seguridad.

    `TIPOS` cubre lo que se ha podido identificar, pero WhatsApp **sigue inventando
    códigos**: en una base real aparecieron los tipos 25, 28, 43, 57, 62 y 82 con medio
    adjunto y sin nombre conocido. Deducirlo del mime cuando el código no suena deja la
    galería y el visor completos hoy y resistentes a la próxima versión, en vez de tirar
    en silencio lo que no se reconoce.
    """
    conocido = TIPOS.get(message_type)
    if conocido and conocido != "otro":
        return conocido
    if mime:
        if mime.startswith("image/"):
            return "imagen"
        if mime.startswith("video/"):
            return "video"
        if mime.startswith("audio/"):
            return "audio"
        return "documento"
    return conocido or "otro"


# Índices que la copia de seguridad NO trae. WhatsApp guarda la base sin ellos —tiene 30
# índices, pero ninguno sobre `message.chat_row_id`— así que abrir un chat obligaba a
# recorrer los 611.637 mensajes enteros, y listar los 5.188 chats hacía eso 5.188 veces:
# minutos por pantalla. Creándolos una vez, cada consulta baja a milisegundos.
#
# Se crean sobre **nuestra copia descifrada**, que es un artefacto derivado: el original
# intocable es el `.crypt15`, y esto se puede rehacer descifrando otra vez.
_INDICES = (
    ("wa_idx_message_chat",        "message(chat_row_id, _id)"),
    ("wa_idx_message_sender",      "message(sender_jid_row_id)"),
    ("wa_idx_message_ts",          "message(timestamp)"),
    ("wa_idx_media_message",       "message_media(message_row_id)"),
    ("wa_idx_media_chat",          "message_media(chat_row_id)"),
    ("wa_idx_revoked_message",     "message_revoked(message_row_id)"),
    ("wa_idx_quoted_message",      "message_quoted(message_row_id)"),
    ("wa_idx_chat_jid",            "chat(jid_row_id)"),
)


def indices_listos(con: sqlite3.Connection | None = None) -> bool:
    cerrar = con is None
    con = con or _con()
    try:
        hay = {r[0] for r in con.execute(
            "SELECT name FROM sqlite_master WHERE type='index' AND name LIKE 'wa_idx_%'")}
        return all(nombre in hay for nombre, _ in _INDICES)
    finally:
        if cerrar:
            con.close()


def prepara(progress_cb=None) -> dict:
    """Crea los índices que faltan. Idempotente: se puede llamar siempre.

    Es la única operación de todo el paquete que **escribe** en la base descifrada.
    """
    if not DESCIFRADA.is_file():
        raise SinBaseDeDatos("No hay base descifrada que preparar.")
    con = sqlite3.connect(DESCIFRADA)
    creados, fallidos = [], []
    try:
        for i, (nombre, sobre) in enumerate(_INDICES, start=1):
            if progress_cb:
                progress_cb(i, len(_INDICES), nombre)
            try:
                con.execute(f"CREATE INDEX IF NOT EXISTS {nombre} ON {sobre}")
                con.commit()
                creados.append(nombre)
            except sqlite3.Error as exc:
                # Una tabla que no exista en esta versión de WhatsApp no debe tumbar el
                # resto, pero **el fallo se cuenta**: tragárselo dejaba la base a medio
                # indexar sin que nadie se enterase, y la lentitud reaparecía sin causa
                # aparente.
                fallidos.append({"indice": nombre, "sobre": sobre, "motivo": str(exc)})
        try:
            con.execute("ANALYZE")
            con.commit()
        except sqlite3.Error:
            pass
    finally:
        con.close()
    return {"indices": creados, "fallidos": fallidos,
            "completo": not fallidos}


class SinBaseDeDatos(RuntimeError):
    """Todavía no hay base descifrada."""


def _con() -> sqlite3.Connection:
    if not DESCIFRADA.is_file():
        raise SinBaseDeDatos(
            "Todavía no hay ninguna base de datos descifrada. Descarga la copia del "
            "móvil y descífrala con tu clave de 64 dígitos."
        )
    con = sqlite3.connect(f"file:{DESCIFRADA}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    if AGENDA.is_file():
        # La agenda es opcional: sin ella todo funciona, solo que con números en vez de
        # nombres. Por eso el ATTACH va en try y no rompe nada si falla.
        try:
            con.execute("ATTACH DATABASE ? AS agenda", (f"file:{AGENDA}?mode=ro",))
        except sqlite3.Error:
            pass
    return con


def _tiene_agenda(con: sqlite3.Connection) -> bool:
    try:
        con.execute("SELECT 1 FROM agenda.wa_contacts LIMIT 1").fetchone()
        return True
    except sqlite3.Error:
        return False


def _nombres(con: sqlite3.Connection) -> dict[str, str]:
    """`raw_string` del jid -> nombre de la agenda.

    Se trae entera de una vez (son unos pocos miles) en vez de hacer un JOIN por consulta:
    `wa.db` está adjunta como base separada y cruzarla en cada listado de mensajes salía
    caro sin aportar nada.
    """
    if not _tiene_agenda(con):
        return {}
    # WhatsApp ha ido cambiando las columnas; se cogen las que existan.
    columnas = {r["name"] for r in con.execute("PRAGMA agenda.table_info(wa_contacts)")}
    prefiere = [c for c in ("display_name", "wa_name", "given_name", "nickname")
                if c in columnas]
    if not prefiere or "jid" not in columnas:
        return {}
    expr = "COALESCE(" + ", ".join(f"NULLIF({c}, '')" for c in prefiere) + ")"
    return {r["jid"]: r["nombre"] for r in con.execute(
        f"SELECT jid, {expr} AS nombre FROM agenda.wa_contacts WHERE {expr} IS NOT NULL")}


def _bonito(raw: str | None, user: str | None, server: str | None,
            nombres: dict[str, str]) -> str:
    """Cómo llamar a alguien: nombre de la agenda, y si no, su número."""
    if raw and raw in nombres:
        return nombres[raw]
    if server == "g.us":
        return "Grupo"
    if server == "lid":
        # Un `lid` no lleva teléfono dentro: no hay número que enseñar.
        return "Contacto sin identificar"
    if server == "newsletter":
        return "Canal"
    if user and user.isdigit():
        return f"+{user}"
    # Sin nada que enseñar se devuelve vacío, no "?": un interrogante en mitad de una
    # conversación parece un error de la aplicación cuando en realidad no hay autor que
    # mostrar. Quien llama decide si pinta algo o no.
    return user or raw or ""


def resumen_chats(con: sqlite3.Connection | None = None) -> dict:
    """Cuántos chats, mensajes y medios hay. Para la cabecera de la interfaz."""
    cerrar = con is None
    con = con or _con()
    try:
        fila = con.execute("""
            SELECT (SELECT count(*) FROM message)                              AS mensajes,
                   (SELECT count(DISTINCT chat_row_id) FROM message)           AS chats,
                   (SELECT count(*) FROM message_media)                        AS medios,
                   (SELECT count(*) FROM message_revoked)                      AS eliminados,
                   (SELECT min(timestamp) FROM message WHERE timestamp > 0)    AS desde,
                   (SELECT max(timestamp) FROM message)                        AS hasta
        """).fetchone()
        return {k: fila[k] for k in fila.keys()} | {"agenda": _tiene_agenda(con)}
    finally:
        if cerrar:
            con.close()


def lista_chats(busca: str = "", limit: int = 200, offset: int = 0) -> dict:
    """Conversaciones ordenadas por actividad, como la lista de WhatsApp.

    Se excluyen los chats sin ningún mensaje: la tabla `chat` guarda 5.188 filas, pero
    410 no tienen ni un mensaje (contactos que se abrieron y nunca se usaron).
    """
    con = _con()
    try:
        nombres = _nombres(con)
        # Los recuentos van como agregados de **una sola pasada** por tabla y se cruzan
        # después. Con subconsultas correlacionadas esto tardaba minutos: eran 5.188
        # barridos de una tabla de 611.637 filas. `message_media` trae su propio
        # `chat_row_id`, así que ni siquiera hace falta pasar por `message` para contarlo.
        filas = con.execute("""
            WITH conteo AS (
                SELECT chat_row_id, count(*) AS n FROM message GROUP BY chat_row_id
            ), medios AS (
                SELECT chat_row_id, count(*) AS n FROM message_media GROUP BY chat_row_id
            )
            SELECT c._id, c.subject, c.archived, c.unseen_message_count,
                   j.user, j.server, j.raw_string,
                   conteo.n AS mensajes,
                   COALESCE(medios.n, 0) AS medios,
                   last.timestamp AS ultima_fecha,
                   last.message_type AS ultimo_tipo,
                   last.from_me AS ultimo_mio,
                   last.text_data AS ultimo_texto
              FROM chat c
              JOIN jid j        ON j._id = c.jid_row_id
              JOIN conteo       ON conteo.chat_row_id = c._id
              LEFT JOIN medios  ON medios.chat_row_id = c._id
              LEFT JOIN message last ON last._id = c.last_message_row_id
             ORDER BY COALESCE(c.sort_timestamp, last.timestamp, 0) DESC
        """).fetchall()

        chats = []
        for f in filas:
            nombre = f["subject"] or _bonito(f["raw_string"], f["user"], f["server"], nombres)
            if busca and busca.lower() not in nombre.lower():
                continue
            chats.append({
                "id": f["_id"],
                "nombre": nombre,
                "es_grupo": f["server"] == "g.us",
                "es_canal": f["server"] == "newsletter",
                "archivado": bool(f["archived"]),
                "sin_leer": f["unseen_message_count"] or 0,
                "mensajes": f["mensajes"],
                "medios": f["medios"],
                "ultima_fecha": f["ultima_fecha"],
                "ultimo_tipo": TIPOS.get(f["ultimo_tipo"], "otro"),
                "ultimo_mio": bool(f["ultimo_mio"]),
                "ultimo_texto": (f["ultimo_texto"] or "")[:120],
            })

        return {"total": len(chats), "chats": chats[offset:offset + limit]}
    finally:
        con.close()


def mensajes(chat_id: int, antes_de: int | None = None, limit: int = 60) -> dict:
    """Mensajes de una conversación, del más nuevo al más viejo.

    Se pagina hacia atrás con `antes_de` (un `_id`) porque es como se lee un chat: se
    abre por el final y se sube. Cargar 40.000 mensajes de golpe no es una opción.
    """
    con = _con()
    try:
        nombres = _nombres(con)
        cabecera = con.execute("""
            SELECT c._id, c.subject, j.user, j.server, j.raw_string
              FROM chat c JOIN jid j ON j._id = c.jid_row_id WHERE c._id = ?
        """, (chat_id,)).fetchone()
        if not cabecera:
            raise SinBaseDeDatos(f"No hay ninguna conversación con id {chat_id}.")

        # En una conversación individual `sender_jid_row_id` viene a 0: el remitente es
        # el propio chat y no hay nada que nombrar. Solo los grupos necesitan autor, que
        # es exactamente lo que hace WhatsApp.
        es_grupo = cabecera["server"] == "g.us"

        tope = "AND m._id < ?" if antes_de else ""
        args = [chat_id] + ([antes_de] if antes_de else []) + [limit]
        filas = con.execute(f"""
            SELECT m._id, m.from_me, m.timestamp, m.message_type, m.text_data, m.starred,
                   s.user AS autor_user, s.server AS autor_server, s.raw_string AS autor_raw,
                   mm.file_path, mm.file_size, mm.mime_type, mm.media_caption,
                   mm.media_duration, mm.width, mm.height, mm.media_name,
                   rv.revoke_timestamp,
                   q.text_data AS citado_texto, q.message_type AS citado_tipo
              FROM message m
              LEFT JOIN jid s            ON s._id = m.sender_jid_row_id
              LEFT JOIN message_media mm ON mm.message_row_id = m._id
              LEFT JOIN message_revoked rv ON rv.message_row_id = m._id
              LEFT JOIN message_quoted q ON q.message_row_id = m._id
             WHERE m.chat_row_id = ? {tope}
             ORDER BY m._id DESC
             LIMIT ?
        """, args).fetchall()

        salida = []
        for f in filas:
            tipo = tipo_de(f["message_type"], f["mime_type"])
            # Un mensaje revocado se marca aparte: el tipo real interesa igual, porque
            # **el fichero puede seguir en el disco aunque el mensaje se borrara**.
            eliminado = f["revoke_timestamp"] is not None
            salida.append({
                "id": f["_id"],
                "mio": bool(f["from_me"]),
                "fecha": f["timestamp"],
                "tipo": "eliminado" if eliminado else tipo,
                "tipo_real": tipo,
                "texto": f["text_data"],
                "destacado": bool(f["starred"]),
                "autor": (_bonito(f["autor_raw"], f["autor_user"], f["autor_server"], nombres)
                          or None) if (es_grupo and not f["from_me"]) else None,
                "eliminado": eliminado,
                "citado": {"texto": (f["citado_texto"] or "")[:200],
                           "tipo": tipo_de(f["citado_tipo"])} if f["citado_tipo"] is not None else None,
                "medio": {
                    "ruta_original": f["file_path"],
                    "nombre": Path(f["file_path"]).name if f["file_path"] else f["media_name"],
                    "bytes": f["file_size"],
                    "mime": f["mime_type"],
                    "pie": f["media_caption"],
                    "duracion": f["media_duration"],
                    "ancho": f["width"], "alto": f["height"],
                } if f["file_path"] or f["mime_type"] else None,
            })

        salida.reverse()                       # se devuelven en orden de lectura
        return {
            "chat": {
                "id": cabecera["_id"],
                "nombre": cabecera["subject"] or _bonito(
                    cabecera["raw_string"], cabecera["user"], cabecera["server"], nombres),
                "es_grupo": cabecera["server"] == "g.us",
            },
            "mensajes": salida,
            # `_id` más bajo de la tanda: lo que hay que pedir para seguir subiendo.
            "hay_mas": len(filas) == limit,
            "siguiente": filas[-1]["_id"] if filas else None,
        }
    finally:
        con.close()


def contactos(busca: str = "", limit: int = 200, offset: int = 0,
              solo_con_mensajes: bool = True) -> dict:
    """La tabla `jid`, que **no es la agenda** — ver el docstring del módulo.

    `solo_con_mensajes` es lo que hace la lista utilizable: de 120.011 identificadores,
    los que han escrito alguna vez son 1.569, que es el orden de magnitud de una agenda
    real. Sin ese filtro la lista es ruido.
    """
    con = _con()
    try:
        nombres = _nombres(con)
        union = "JOIN" if solo_con_mensajes else "LEFT JOIN"
        filas = con.execute(f"""
            WITH escritos AS (
                SELECT sender_jid_row_id AS jid, count(*) AS n FROM message
                 WHERE sender_jid_row_id > 0 GROUP BY sender_jid_row_id
            ), suyos AS (
                SELECT jid_row_id AS jid, min(_id) AS chat_id FROM chat GROUP BY jid_row_id
            )
            SELECT j._id, j.user, j.server, j.raw_string,
                   escritos.n AS mensajes, suyos.chat_id AS chat_id
              FROM jid j
              {union} escritos ON escritos.jid = j._id
              LEFT JOIN suyos  ON suyos.jid = j._id
        """).fetchall()

        gente = []
        for f in filas:
            nombre = _bonito(f["raw_string"], f["user"], f["server"], nombres)
            if busca and busca.lower() not in nombre.lower() and busca not in (f["user"] or ""):
                continue
            gente.append({
                "id": f["_id"], "nombre": nombre,
                "numero": f["user"] if f["server"] == "s.whatsapp.net" else None,
                "servidor": f["server"], "mensajes": f["mensajes"] or 0,
                "en_agenda": bool(f["raw_string"] in nombres),
                "chat_id": f["chat_id"],
            })
        gente.sort(key=lambda p: (-p["mensajes"], p["nombre"].lower()))
        return {"total": len(gente), "contactos": gente[offset:offset + limit]}
    finally:
        con.close()


def estadisticas_jid() -> dict:
    """Por qué hay 120.011 «contactos». Se enseña en la propia interfaz, porque el número
    asusta y la explicación no es evidente."""
    con = _con()
    try:
        por_servidor = [{"servidor": r["server"] or "(vacío)", "total": r["n"]}
                        for r in con.execute(
                            "SELECT server, count(*) n FROM jid GROUP BY server ORDER BY n DESC")]
        fila = con.execute("""
            SELECT (SELECT count(*) FROM jid)                                          AS total,
                   (SELECT count(DISTINCT sender_jid_row_id) FROM message
                     WHERE sender_jid_row_id > 0)                                      AS han_escrito,
                   (SELECT count(*) FROM chat)                                         AS con_chat
        """).fetchone()
        return {**{k: fila[k] for k in fila.keys()}, "por_servidor": por_servidor}
    finally:
        con.close()


def hay_texto_borrado() -> dict:
    """Si de los mensajes eliminados queda algo más que el hueco.

    La creencia habitual es que en un SQLite las filas borradas siguen ahí hasta un
    VACUUM, y que por tanto se podrían rescatar. **En esta base no**, y se comprueba en
    vez de suponerlo: `auto_vacuum` y `freelist_count` dicen si queda espacio sin
    reclamar, y `message_revoked` dice si WhatsApp conservó el texto (no lo conserva).
    """
    con = _con()
    try:
        auto = con.execute("PRAGMA auto_vacuum").fetchone()[0]
        libres = con.execute("PRAGMA freelist_count").fetchone()[0]
        fila = con.execute("""
            SELECT count(*) AS revocados,
                   sum(CASE WHEN m.text_data IS NOT NULL AND m.text_data != ''
                            THEN 1 ELSE 0 END) AS con_texto
              FROM message_revoked rv JOIN message m ON m._id = rv.message_row_id
        """).fetchone()
        return {
            "auto_vacuum": auto,
            "paginas_libres": libres,
            "revocados": fila["revocados"],
            "con_texto_conservado": fila["con_texto"] or 0,
            # Con auto_vacuum en FULL, SQLite devuelve las páginas liberadas al sistema en
            # cada commit: no queda espacio sin reclamar donde pudiera sobrevivir nada.
            "recuperable": auto == 0 and libres > 0,
        }
    finally:
        con.close()
