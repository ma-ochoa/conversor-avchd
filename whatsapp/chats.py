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

from . import agenda as agenda_externa
from .config import AGENDA, DESCIFRADA

# Qué es cada `message.message_type`, deducido cruzando con `message_media.mime_type`
# sobre una base real. No están documentados en ninguna parte oficial.
# Qué dice cada aviso del sistema (`message_system.action_type`). **WhatsApp no publica
# estos códigos**: casi todos están deducidos cruzando los tipos con las tablas
# `message_system_*` de esta misma base —el 6 solo aparece en `photo_change`, el 67 solo
# en `initial_privacy_provider`—, y los que no dejan rastro en ninguna tabla se han
# identificado mirando qué escribe la aplicación. Los que siguen sin identificar se
# enseñan con su número, que es más honesto que inventarles un texto.
#
# El 67 se lleva 7.265 de los 13.902 avisos: es el «cifrado de extremo a extremo» que
# WhatsApp escribe al abrir cualquier conversación.
AVISOS = {
    1:   "Cambió el nombre del grupo",
    5:   "Se creó el grupo",
    6:   "Cambió la foto del grupo",
    10:  "Cambió su número de teléfono",
    12:  "Alguien salió del grupo",
    14:  "Alguien entró en el grupo",
    # El 18 no aparece en ninguna tabla de detalle y llega sin autor ni texto, así que
    # por cruce era imposible. Identificado mirando la propia aplicación: es el «cambió
    # tu código de seguridad con…» que WhatsApp escribe cuando alguien reinstala o
    # cambia de teléfono. Con sus 2.265 casos es el segundo aviso más frecuente.
    18:  "Cambió el código de seguridad",
    20:  "Se añadió a alguien al grupo",
    28:  "Cambió su número de teléfono",
    46:  "Cambió la descripción del grupo",
    50:  "Cambiaron los ajustes del grupo",
    58:  "Contacto bloqueado o desbloqueado",
    67:  "Los mensajes están cifrados de extremo a extremo",
    69:  "Esta cuenta pasó a ser de empresa",
    70:  "Llamada de grupo",
    165: "Cambió su nombre de usuario",
}

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


def _nombres_wa_db(con: sqlite3.Connection) -> dict[str, str]:
    """`raw_string` del jid -> nombre según la agenda que WhatsApp guarda en `wa.db`.

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


def _telefonos_de_lid(con: sqlite3.Connection) -> dict[str, str]:
    """`raw_string` de un LID -> su número de teléfono real.

    **Sin esto, media conversación de grupo se queda sin autor.** Desde que WhatsApp usa
    LID (identificadores que no revelan el teléfono), el remitente de un mensaje de grupo
    llega como `239423019081732@lid`, que no lleva número dentro — y se enseñaba como
    «Contacto sin identificar» aunque la persona estuviera en la agenda.

    La correspondencia está en `jid_map`, que WhatsApp mantiene precisamente para eso. En
    esta base son 38.942 mensajes de 464 remitentes, y 446 de ellos sí tienen número.
    """
    try:
        filas = con.execute("""
            SELECT lid.raw_string AS lid, pn.user AS tel
              FROM jid_map m
              JOIN jid lid ON lid._id = m.lid_row_id
              JOIN jid pn  ON pn._id  = m.jid_row_id
             WHERE pn.user IS NOT NULL AND pn.user != ''
        """).fetchall()
    except sqlite3.Error:
        return {}          # bases anteriores a los LID no traen `jid_map`
    return {f["lid"]: f["tel"] for f in filas}


def telefono_de(raw: str | None, user: str | None, server: str | None,
                lids: dict[str, str]) -> str | None:
    """El teléfono de alguien, resolviendo el LID si hace falta. `None` si no se sabe."""
    if server == "lid":
        return lids.get(raw or "")
    return user if (user or "").isdigit() else None


def _nombres(con: sqlite3.Connection) -> dict[str, str]:
    """Identificador de contacto -> nombre, juntando las dos fuentes posibles.

    Primero la agenda que WhatsApp guarda en `wa.db`; después la que el usuario haya
    importado de fuera, que **manda sobre la anterior** porque es la que acaba de traer
    y la que refleja cómo tiene guardada a la gente hoy.

    La segunda hace falta más de lo que parece: en un Galaxy S25 real, `wa_contacts`
    estaba **vacía** —WhatsApp lee la agenda del sistema al vuelo en vez de copiarla—,
    así que sin importar nada de fuera la interfaz solo puede enseñar números.
    """
    nombres = _nombres_wa_db(con)

    indice = agenda_externa.cargada()["indice"]
    if not indice:
        return nombres

    # Se cruza una sola vez por consulta: recorrer 120.000 identificadores llamando a
    # `busca()` por cada mensaje pintado sería absurdo.
    for fila in con.execute(
            "SELECT raw_string, user FROM jid WHERE server = 's.whatsapp.net'"):
        encontrado = agenda_externa.busca(fila["user"] or "", indice)
        if encontrado:
            nombres[fila["raw_string"]] = encontrado

    # Un LID hereda el nombre del teléfono al que corresponde: para la agenda es la
    # misma persona, y quien escribe en un grupo suele hacerlo desde su LID.
    for lid, tel in _telefonos_de_lid(con).items():
        encontrado = agenda_externa.busca(tel, indice)
        if encontrado:
            nombres.setdefault(lid, encontrado)
    return nombres


def contactos_en_wa_db() -> dict:
    """Cuántos nombres trae la `wa.db` recién descifrada.

    Es la comprobación que hay que hacer tras cada copia nueva: WhatsApp dejó de rellenar
    `wa_contacts` —lee la agenda del sistema al vuelo— y si algún día volviera a hacerlo,
    esta es la fuente de nombres buena, la que trae también los de quien no está en tu
    agenda. Hasta entonces, la respuesta es cero y la agenda importada es lo único que hay.
    """
    con = _con()
    try:
        if not _tiene_agenda(con):
            return {"disponible": False, "con_nombre": 0, "filas": 0}
        columnas = {r["name"] for r in con.execute("PRAGMA agenda.table_info(wa_contacts)")}
        filas = con.execute("SELECT COUNT(*) AS n FROM agenda.wa_contacts").fetchone()["n"]
        prefiere = [c for c in ("display_name", "wa_name", "given_name", "nickname")
                    if c in columnas]
        con_nombre = 0
        if prefiere and filas:
            expr = " OR ".join(f"NULLIF({c}, '') IS NOT NULL" for c in prefiere)
            con_nombre = con.execute(
                f"SELECT COUNT(*) AS n FROM agenda.wa_contacts WHERE {expr}").fetchone()["n"]
        return {"disponible": True, "filas": filas, "con_nombre": con_nombre,
                "columnas": sorted(prefiere)}
    except sqlite3.Error as exc:
        return {"disponible": False, "con_nombre": 0, "filas": 0, "detalle": str(exc)}
    finally:
        con.close()


def _bonito(raw: str | None, user: str | None, server: str | None,
            nombres: dict[str, str], lids: dict[str, str] | None = None) -> str:
    """Cómo llamar a alguien: nombre de la agenda, y si no, su número.

    `lids` es el mapa de `_telefonos_de_lid`. Sin él, un LID no tiene número que enseñar;
    con él, la mayoría lo tienen.
    """
    if raw and raw in nombres:
        return nombres[raw]
    if server == "g.us":
        return "Grupo"
    if server == "lid":
        telefono = (lids or {}).get(raw or "")
        # Un `lid` no lleva el teléfono dentro; solo queda esto cuando tampoco está en
        # `jid_map` — en esta base, 18 de 464 remitentes.
        return f"+{telefono}" if telefono else "Contacto sin identificar"
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
        lids = _telefonos_de_lid(con)
        # Los recuentos van como agregados de **una sola pasada** por tabla y se cruzan
        # después. Con subconsultas correlacionadas esto tardaba minutos: eran 5.188
        # barridos de una tabla de 611.637 filas. `message_media` trae su propio
        # `chat_row_id`, así que ni siquiera hace falta pasar por `message` para contarlo.
        filas = con.execute("""
            WITH conteo AS (
                -- Los avisos del sistema (tipo 7) se cuentan aparte: 3.319 de las 5.188
                -- conversaciones de esta base **no tienen una sola palabra**, solo el
                -- «cifrado de extremo a extremo». Sin distinguirlo, la lista es sobre
                -- todo ruido y no hay forma de filtrarlo.
                SELECT chat_row_id, count(*) AS n,
                       sum(CASE WHEN message_type != 7 THEN 1 ELSE 0 END) AS reales
                  FROM message GROUP BY chat_row_id
            ), medios AS (
                SELECT chat_row_id, count(*) AS n FROM message_media GROUP BY chat_row_id
            )
            SELECT c._id, c.subject, c.archived, c.unseen_message_count,
                   j.user, j.server, j.raw_string,
                   conteo.n AS mensajes, conteo.reales AS mensajes_reales,
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

        from . import avatares as _avatares
        con_foto = _avatares.mapa_chats()

        chats = []
        for f in filas:
            nombre = f["subject"] or _bonito(f["raw_string"], f["user"], f["server"],
                                             nombres, lids)
            if busca and busca.lower() not in nombre.lower():
                continue
            chats.append({
                "id": f["_id"],
                "nombre": nombre,
                "es_grupo": f["server"] == "g.us",
                "es_canal": f["server"] == "newsletter",
                "avatar": f["_id"] in con_foto,
                # En qué grupo cae al filtrar. `sin_nombre` es alguien con quien has
                # hablado pero que no está en tu agenda: se le ve el número y nada más.
                "tipo": ("grupo" if f["server"] == "g.us"
                         else "canal" if f["server"] == "newsletter"
                         else ("contacto" if not nombre.startswith("+")
                               and nombre != "Contacto sin identificar" else "sin_nombre")
                         if f["server"] in ("s.whatsapp.net", "lid") else "otro"),
                "mensajes_reales": f["mensajes_reales"] or 0,
                "medios": f["medios"] or 0,
                "archivado": bool(f["archived"]),
                "sin_leer": f["unseen_message_count"] or 0,
                "mensajes": f["mensajes"],
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
        lids = _telefonos_de_lid(con)
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
                   sys.action_type AS aviso,
                   q.text_data AS citado_texto, q.message_type AS citado_tipo
              FROM message m
              LEFT JOIN message_system sys ON sys.message_row_id = m._id
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
                # Los avisos vienen con `text_data` vacío: lo que dicen está en su
                # código, no en el propio mensaje.
                "texto": f["text_data"] or (
                    AVISOS.get(f["aviso"], f"Aviso del sistema (tipo {f['aviso']})")
                    if f["aviso"] is not None else None),
                "destacado": bool(f["starred"]),
                "autor": (_bonito(f["autor_raw"], f["autor_user"], f["autor_server"],
                                  nombres, lids)
                          or None) if (es_grupo and not f["from_me"]) else None,
                # El teléfono va aparte para poder enseñarlo al pasar por encima cuando
                # lo que se ve es el nombre. Con LID no está en la fila: hay que resolverlo.
                "autor_numero": telefono_de(f["autor_raw"], f["autor_user"],
                                            f["autor_server"], lids)
                                if (es_grupo and not f["from_me"]) else None,
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
                    cabecera["raw_string"], cabecera["user"], cabecera["server"],
                    nombres, lids),
                "es_grupo": cabecera["server"] == "g.us",
            },
            "mensajes": salida,
            # `_id` más bajo de la tanda: lo que hay que pedir para seguir subiendo.
            "hay_mas": len(filas) == limit,
            "siguiente": filas[-1]["_id"] if filas else None,
        }
    finally:
        con.close()


def contexto(chat_id: int, mensaje_id: int, alrededor: int = 25) -> dict:
    """Los mensajes que rodean a uno concreto, para saltar desde una foto a su conversación.

    Es lo que convierte la galería en algo más que un álbum: ver una imagen y poder leer
    **qué se estaba diciendo alrededor**. Se devuelven `alrededor` mensajes a cada lado y
    se marca cuál era el buscado.

    Se pagina igual que `mensajes()` para poder seguir subiendo o bajando desde ahí.
    """
    con = _con()
    try:
        # Se piden los de antes y los de después por separado porque un único BETWEEN
        # sobre _id no reparte bien: los ids no son contiguos dentro de un chat.
        antes = con.execute("""
            SELECT _id FROM message WHERE chat_row_id = ? AND _id <= ?
             ORDER BY _id DESC LIMIT ?
        """, (chat_id, mensaje_id, alrededor + 1)).fetchall()
        despues = con.execute("""
            SELECT _id FROM message WHERE chat_row_id = ? AND _id > ?
             ORDER BY _id ASC LIMIT ?
        """, (chat_id, mensaje_id, alrededor)).fetchall()
    finally:
        con.close()

    if not antes:
        raise SinBaseDeDatos(
            f"El mensaje {mensaje_id} no está en la conversación {chat_id}.")

    # `mensajes()` pagina hacia atrás desde un tope, así que se pide desde el más nuevo
    # del tramo y se recorta a la ventana que interesa.
    tope = (despues[-1]["_id"] if despues else mensaje_id) + 1
    datos = mensajes(chat_id, antes_de=tope, limit=len(antes) + len(despues))
    datos["destacado"] = mensaje_id
    return datos


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
        lids = _telefonos_de_lid(con)
        union = "JOIN" if solo_con_mensajes else "LEFT JOIN"
        filas = con.execute(f"""
            WITH escritos AS (
                SELECT sender_jid_row_id AS jid, count(*) AS n FROM message
                 WHERE sender_jid_row_id > 0 GROUP BY sender_jid_row_id
            ), suyos AS (
                SELECT jid_row_id AS jid, min(_id) AS chat_id FROM chat GROUP BY jid_row_id
            ), en_su_chat AS (
                -- Los avisos del sistema (tipo 7: «cifrado de extremo a extremo», cambios
                -- de número) se cuentan aparte: son más de la mitad de las conversaciones
                -- individuales, y contarlos como mensajes hacía que un chat sin una sola
                -- palabra dijera que tenía contenido.
                SELECT chat_row_id AS chat_id, count(*) AS n_todo,
                       sum(CASE WHEN message_type != 7 THEN 1 ELSE 0 END) AS n
                  FROM message GROUP BY chat_row_id
            )
            SELECT j._id, j.user, j.server, j.raw_string,
                   escritos.n AS mensajes, suyos.chat_id AS chat_id,
                   en_su_chat.n AS mensajes_chat,
                   en_su_chat.n_todo AS mensajes_chat_todo
              FROM jid j
              {union} escritos ON escritos.jid = j._id
              LEFT JOIN suyos  ON suyos.jid = j._id
              LEFT JOIN en_su_chat ON en_su_chat.chat_id = suyos.chat_id
        """).fetchall()

        gente = []
        for f in filas:
            nombre = _bonito(f["raw_string"], f["user"], f["server"], nombres, lids)
            if busca and busca.lower() not in nombre.lower() and busca not in (f["user"] or ""):
                continue
            gente.append({
                "id": f["_id"], "nombre": nombre,
                # Un LID también tiene número: está en `jid_map`, no en la fila.
                "numero": telefono_de(f["raw_string"], f["user"], f["server"], lids),
                "servidor": f["server"], "mensajes": f["mensajes"] or 0,
                # Dos cifras distintas que antes se enseñaban como una: `mensajes` es
                # todo lo que ha escrito esa persona **en cualquier conversación**, y
                # `mensajes_chat` lo que hay en la vuestra a solas. Alguien de un grupo
                # muy activo puede tener miles de los primeros y cero de los segundos.
                "mensajes_chat": f["mensajes_chat"] or 0,
                # Un chat que solo tiene avisos se ve vacío al abrirlo: hay que poder
                # distinguirlo de uno en el que de verdad no hay nada.
                "avisos_chat": (f["mensajes_chat_todo"] or 0) - (f["mensajes_chat"] or 0),
                "en_agenda": bool(f["raw_string"] in nombres),
                "chat_id": f["chat_id"],
            })
        gente.sort(key=lambda p: (-p["mensajes"], p["nombre"].lower()))
        return {"total": len(gente), "contactos": gente[offset:offset + limit]}
    finally:
        con.close()


def donde_escribe(jid_id: int, limit: int = 30) -> dict:
    """En qué conversaciones ha escrito esa persona, y cuánto en cada una.

    Es lo que explica un contacto con miles de mensajes cuya conversación a solas está
    vacía: todo lo suyo está en grupos. Sin poder verlo, la cifra de la lista parece un
    fallo de la aplicación — que es exactamente como se leía antes.
    """
    con = _con()
    try:
        nombres = _nombres(con)
        lids = _telefonos_de_lid(con)
        filas = con.execute("""
            SELECT c._id AS chat_id, c.subject, j.user, j.server, j.raw_string,
                   count(*) AS n,
                   min(m.timestamp) AS primera, max(m.timestamp) AS ultima
              FROM message m
              JOIN chat c ON c._id = m.chat_row_id
              JOIN jid  j ON j._id = c.jid_row_id
             WHERE m.sender_jid_row_id = ?
             GROUP BY m.chat_row_id
             ORDER BY n DESC
        """, (jid_id,)).fetchall()

        sitios = [{
            "chat_id": f["chat_id"],
            "nombre": f["subject"] or _bonito(f["raw_string"], f["user"], f["server"],
                                              nombres, lids),
            "es_grupo": f["server"] == "g.us",
            "mensajes": f["n"],
            "primera": f["primera"],
            "ultima": f["ultima"],
        } for f in filas]

        return {"total": len(sitios), "escritos": sum(s["mensajes"] for s in sitios),
                "chats": sitios[:limit]}
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
