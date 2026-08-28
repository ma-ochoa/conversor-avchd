"""El archivo histórico: la base que crece y **nunca pierde nada**.

La copia del ordenador no debe ser un espejo del móvil. El móvil se limpia —se borran
conversaciones enteras y años de fotos para hacer sitio—, así que la copia de la vuelta
N+1 puede traer menos que la de la vuelta N. Sobrescribir sin más iría destruyendo el
archivo poco a poco, y justo por el material más antiguo, que es el que más interesa.

Aquí se hace lo contrario: cada copia nueva **se suma** a un archivo que solo crece. Lo
que el móvil ya no tiene se queda, marcado con la fecha de la última copia en que
todavía estaba.

**La llave es `message.key_id`**, el identificador que asigna WhatsApp y que se conserva
entre copias. `message._id` no sirve: es un autonumérico local que WhatsApp reasigna al
restaurar, y usarlo como llave duplicaría la base entera en cada fusión. Para los chats
la llave es el `raw_string` de su jid, por lo mismo.

**Columnas propias, con prefijo `wa_`** para que se distingan a simple vista de lo que
trae WhatsApp:

  · `wa_visto`   — fecha de la última copia en la que esa fila seguía en el móvil.
  · `wa_llegada` — cuándo entró en el archivo.

Un mensaje o un chat cuyo `wa_visto` sea anterior a la última fusión es exactamente lo
que el usuario borró del teléfono: sigue aquí, y se sabe desde cuándo no está allí.

**Nada de esto toca `msgstore.db`**, que se sigue usando tal cual llega del móvil. El
archivo es un fichero aparte (`archivo.db`), y si algo saliera mal se puede borrar y
reconstruir desde las copias.
"""

import shutil
import sqlite3
import time
from datetime import datetime, timezone
from pathlib import Path

from .config import ARCHIVO, DESCIFRADA

# Las tablas hijas de `message` no se enumeran: se descubren mirando cuáles tienen una
# columna `message_row_id`. Son más de veinte —reacciones, menciones, miniaturas,
# ubicaciones, vCards, enlaces, acuses de recibo…— y suman casi medio millón de filas de
# contenido; enumerarlas a mano garantizaba dejarse alguna, y además WhatsApp añade tablas
# nuevas en cada versión. Descubrirlas hace que la fusión siga funcionando sin tocarla.
#
# Las que además tienen `chat_row_id` o `sender_jid_row_id` se remapean solas: `_REMAPEOS`
# se completa para cada una en cuanto se sabe qué columnas tiene.
_HIJAS_EXCLUIDAS = {"message_media", "message_quoted", "message_revoked"}   # ya explícitas

# Columnas que apuntan a filas de otra tabla y hay que traducir al `_id` del archivo.
_REMAPEOS = {
    "chat": {"jid_row_id": "jid", "account_jid_row_id": "jid"},
    "message": {"chat_row_id": "chat", "sender_jid_row_id": "jid"},
    "message_media": {"message_row_id": "msg", "chat_row_id": "chat"},
    "message_quoted": {"message_row_id": "msg", "chat_row_id": "chat",
                       "parent_message_chat_row_id": "chat", "sender_jid_row_id": "jid"},
    "message_revoked": {"message_row_id": "msg", "admin_jid_row_id": "jid"},
}

# Punteros de `chat` a mensajes concretos (el último, el último leído…). Son estado de la
# interfaz de WhatsApp, no contenido, y sus `_id` no valen fuera de su base. Se anulan al
# insertar y se recalculan al final: dejarlos apuntando a un `_id` ajeno haría que la
# lista de chats enseñara el último mensaje de otra conversación.
_PUNTEROS_A_MENSAJE = (
    "display_message_row_id", "last_message_row_id", "last_read_message_row_id",
    "last_read_receipt_sent_message_row_id", "last_important_message_row_id",
    "change_number_notified_message_row_id", "last_read_ephemeral_message_row_id",
    "last_message_reaction_row_id", "last_seen_message_reaction_row_id",
)

# De qué fila depende cada tabla para tener sitio en el archivo. Si esa no se puede
# mapear, la fila se descarta: un mensaje sin conversación no tiene dónde ir.
#
# **No es un caso raro ni culpa de la fusión**: la propia base del móvil trae 503 mensajes
# cuyo `chat_row_id` apunta a un chat que ya no existe. WhatsApp los deja ahí; aquí se
# cuentan y se dicen, en vez de tumbar la fusión con un NOT NULL o colarlos en silencio.
_OBLIGATORIO = {
    "chat": "jid_row_id",
    "message": "chat_row_id",
    "message_media": "message_row_id",
    "message_quoted": "message_row_id",
    "message_revoked": "message_row_id",
}

# Qué identifica una fila como «la misma» entre dos copias.
#
# **`key_id` por sí solo no vale**, aunque lo natural sea suponerlo: en la base de prueba
# 12 de sus 611.637 mensajes comparten `key_id` con otro. Son mensajes enviados a varias
# conversaciones a la vez —encuestas y difusiones—, que llevan el mismo identificador en
# cada copia del mensaje. Con `key_id` a secas, el mapa de equivalencias reventaba por
# clave duplicada; con la pareja, cada copia del mensaje es una fila distinta, que es lo
# que de verdad son.
_LLAVES = {"jid": ("raw_string",), "chat": ("jid_row_id",),
           "message": ("key_id", "chat_row_id")}


class ArchivoError(RuntimeError):
    pass


def _ahora() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def _columnas(con: sqlite3.Connection, tabla: str, base: str = "main") -> list[str]:
    return [r[1] for r in con.execute(f'PRAGMA {base}.table_info("{tabla}")')]


def _tablas_hijas(con: sqlite3.Connection) -> list[str]:
    """Tablas que cuelgan de `message`, descubiertas por tener `message_row_id`.

    Se piden a la base **nueva** y se cruzan con las del archivo: si una versión de
    WhatsApp trae una tabla que el archivo no tiene, no hay dónde meterla, y al revés no
    hay nada que traer.
    """
    def con_columna(base):
        salida = []
        for (t,) in con.execute(
                f"SELECT name FROM {base}.sqlite_master WHERE type='table' "
                "AND name LIKE 'message%' OR name IN ('receipt_user', 'call_log')"):
            if t in _HIJAS_EXCLUIDAS or t == "message":
                continue
            if "message_row_id" in _columnas(con, t, base):
                salida.append(t)
        return set(salida)

    return sorted(con_columna("nueva") & con_columna("main"))


def _añade_columnas_propias(con: sqlite3.Connection) -> None:
    """Añade `wa_visto` y `wa_llegada` donde hagan falta. Idempotente."""
    for tabla in ("chat", "message"):
        existentes = set(_columnas(con, tabla))
        for columna in ("wa_visto", "wa_llegada"):
            if columna not in existentes:
                con.execute(f"ALTER TABLE {tabla} ADD COLUMN {columna} TEXT")
    # Por la pareja, que es la llave real (ver `_LLAVES`), y es la búsqueda de la fusión.
    con.execute("CREATE INDEX IF NOT EXISTS wa_idx_message_key "
                "ON message(key_id, chat_row_id)")
    # **El que más se nota con diferencia.** `jid` tiene 120.011 filas y la fusión busca
    # cada una por `raw_string`; sin índice son 120.011 barridos completos de la tabla, y
    # ese único paso se llevaba 454 de los 482 segundos que tardaba la fusión entera.
    # WhatsApp no lo trae porque su `jid` se consulta por `_id`, no por el texto.
    con.execute("CREATE INDEX IF NOT EXISTS wa_idx_jid_raw ON jid(raw_string)")
    con.execute("CREATE INDEX IF NOT EXISTS wa_idx_chat_visto ON chat(wa_visto)")
    con.execute("CREATE INDEX IF NOT EXISTS wa_idx_message_visto ON message(wa_visto)")
    # Para `_recalcula_punteros`, que busca el último mensaje de cada una de las 5.188
    # conversaciones: sin este índice es un barrido completo por chat.
    con.execute("CREATE INDEX IF NOT EXISTS wa_idx_message_chat_ts "
                "ON message(chat_row_id, timestamp)")


def existe() -> bool:
    return ARCHIVO.is_file()


def estado() -> dict:
    """Qué hay en el archivo, y cuánto de ello ya no está en el móvil."""
    if not existe():
        return {"existe": False}
    con = sqlite3.connect(f"file:{ARCHIVO}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    try:
        ultima = con.execute("SELECT MAX(wa_visto) AS v FROM message").fetchone()["v"]
        fila = con.execute("""
            SELECT (SELECT COUNT(*) FROM message)                              AS mensajes,
                   (SELECT COUNT(*) FROM chat)                                 AS chats,
                   (SELECT COUNT(*) FROM message WHERE wa_visto < ?)           AS mensajes_idos,
                   (SELECT COUNT(*) FROM chat    WHERE wa_visto < ?)           AS chats_idos
        """, (ultima, ultima)).fetchone()
        return {"existe": True, "ultima_fusion": ultima, "bytes": ARCHIVO.stat().st_size,
                **dict(fila)}
    except sqlite3.Error as exc:
        return {"existe": True, "error": str(exc)}
    finally:
        con.close()


def _remapeos_de(con: sqlite3.Connection, tabla: str) -> dict:
    """Qué columnas de una tabla hija hay que traducir. Depende de las que tenga."""
    if tabla in _REMAPEOS:
        return _REMAPEOS[tabla]
    cols = set(_columnas(con, tabla))
    mapa = {"message_row_id": "msg"}
    for col, destino in (("chat_row_id", "chat"), ("sender_jid_row_id", "jid"),
                         ("parent_message_row_id", "msg"), ("receipt_user_jid_row_id", "jid"),
                         ("jid_row_id", "jid"), ("admin_jid_row_id", "jid")):
        if col in cols:
            mapa[col] = destino
    return {k: v for k, v in mapa.items() if k in cols}


def _expr(tabla: str, col: str, alias: dict) -> str:
    """Cómo se lee una columna de la copia nueva para insertarla en el archivo."""
    if tabla == "chat" and col in _PUNTEROS_A_MENSAJE:
        return "NULL"
    if col in alias:
        return f"{alias[col]}.destino"
    return f"n.\"{col}\""


def _joins(remapeos: dict, cols: list[str], alias: dict) -> str:
    trozos = []
    for col, mapa in remapeos.items():
        if col in cols:
            trozos.append(f"LEFT JOIN map_{mapa} {alias[col]} ON {alias[col]}.origen = n.\"{col}\"")
    return "\n              ".join(trozos)


def _fusiona_tabla(con: sqlite3.Connection, tabla: str, cuando: str,
                   solo_de_mensajes_nuevos: bool = False) -> int:
    """Inserta en el archivo las filas de `nueva.<tabla>` que aún no estén. Devuelve cuántas.

    `solo_de_mensajes_nuevos` es para las tablas hijas: sus filas cuelgan de un mensaje, y
    si el mensaje ya estaba en el archivo, lo suyo también. Filtrar por el mensaje recién
    llegado sale mucho más barato que comprobar fila a fila si ya está, y da lo mismo.
    """
    cols = [c for c in _columnas(con, tabla) if not c.startswith("wa_") and c != "_id"]
    disponibles = set(_columnas(con, tabla, "nueva"))
    cols = [c for c in cols if c in disponibles]
    remapeos = _remapeos_de(con, tabla)
    alias = {col: f"m_{i}" for i, col in enumerate(remapeos)}

    destino_cols = list(cols)
    select = [_expr(tabla, c, alias) for c in cols]
    if tabla in ("chat", "message"):
        destino_cols += ["wa_visto", "wa_llegada"]
        select += ["?", "?"]

    # Qué filas ya están. Para `message_*` la llave es su mensaje, que ya está remapeado.
    if tabla in _LLAVES:
        iguales = " AND ".join(f'a."{k}" = {_expr(tabla, k, alias)}' for k in _LLAVES[tabla])
        falta = f'NOT EXISTS (SELECT 1 FROM "{tabla}" a WHERE {iguales})'
    else:
        falta = f'NOT EXISTS (SELECT 1 FROM "{tabla}" a WHERE a.message_row_id = {alias["message_row_id"]}.destino)'

    obligatoria = _OBLIGATORIO.get(tabla, "message_row_id" if solo_de_mensajes_nuevos else None)
    con_sitio = (f'AND {alias[obligatoria]}.destino IS NOT NULL'
                 if obligatoria and obligatoria in alias else "")

    # Para las hijas, «no estaba» se decide por su mensaje, no fila a fila.
    recien = ""
    args: tuple = ()
    if solo_de_mensajes_nuevos:
        falta = "1=1"
        recien = (f'JOIN message msg ON msg._id = {alias["message_row_id"]}.destino '
                  f'AND msg.wa_llegada = ?')
        args = (cuando,)

    sql = f'''
        INSERT INTO "{tabla}" ({", ".join(f'"{c}"' for c in destino_cols)})
        SELECT {", ".join(select)}
          FROM nueva."{tabla}" n
              {_joins(remapeos, cols, alias)}
              {recien}
         WHERE {falta} {con_sitio}
    '''
    if tabla in ("chat", "message"):
        args = (cuando, cuando)
    return con.execute(sql, args).rowcount


def _mapa(con: sqlite3.Connection, nombre: str, sql: str) -> None:
    con.execute(f"DROP TABLE IF EXISTS temp.map_{nombre}")
    con.execute(f"CREATE TEMP TABLE map_{nombre} (origen INTEGER PRIMARY KEY, destino INTEGER)")
    con.execute(f"INSERT INTO temp.map_{nombre} (origen, destino) {sql}")
    con.execute(f"CREATE INDEX IF NOT EXISTS temp.idx_map_{nombre} ON map_{nombre}(destino)")


def fusiona(nueva: Path | None = None, cuando: str | None = None) -> dict:
    """Suma una copia recién descifrada al archivo. Devuelve el resumen de la vuelta."""
    nueva = Path(nueva or DESCIFRADA)
    cuando = cuando or _ahora()
    if not nueva.is_file():
        raise ArchivoError(f"No está la base a fusionar: {nueva}")

    primera = not existe()
    if primera:
        # La primera vez el archivo *es* la copia: no hay nada con que fusionar, y
        # copiarla entera es más rápido y más seguro que insertar 600.000 filas.
        ARCHIVO.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(nueva, ARCHIVO)

    con = sqlite3.connect(ARCHIVO)
    con.row_factory = sqlite3.Row
    try:
        con.execute("PRAGMA journal_mode=WAL")
        # La fusión es un lote largo sobre un fichero que se puede regenerar desde las
        # copias: no compensa pagar un fsync por escritura. Sin esto tardaba 7 minutos.
        con.execute("PRAGMA synchronous=OFF")
        con.execute("PRAGMA temp_store=MEMORY")
        con.execute("PRAGMA cache_size=-200000")        # ~200 MB de caché
        _añade_columnas_propias(con)
        if primera:
            for tabla in ("chat", "message"):
                con.execute(f"UPDATE {tabla} SET wa_visto = ?, wa_llegada = ?", (cuando, cuando))
            con.commit()
            resumen = {"primera_vez": True, "cuando": cuando, **_recuento(con)}
            return resumen

        antes = _recuento(con)
        # Cuánto tarda cada paso. Con 600.000 mensajes, un paso mal planteado convierte
        # la fusión en algo que nadie va a esperar, y sin medirlo se optimiza a ciegas.
        tiempos, _t0 = {}, time.monotonic()

        def marca(nombre):
            nonlocal _t0
            tiempos[nombre] = round(time.monotonic() - _t0, 1)
            _t0 = time.monotonic()

        con.execute("ATTACH DATABASE ? AS nueva", (f"file:{nueva}?mode=ro",))
        try:
            comprobacion = _comprueba_llaves(con)
            if not comprobacion["fiable"]:
                raise ArchivoError(
                    "Las dos bases no comparten casi ningún `key_id`, así que no son dos "
                    "copias del mismo WhatsApp o la llave ha dejado de ser estable. No se "
                    "fusiona: hacerlo duplicaría el archivo entero.\n"
                    f"En común: {comprobacion['comunes']} de {comprobacion['nueva']}."
                )
            marca("comprobacion")

            _mapa(con, "jid", "SELECT n._id, a._id FROM nueva.jid n "
                              "JOIN main.jid a ON a.raw_string = n.raw_string")
            insertados = {"jid": _fusiona_tabla(con, "jid", cuando)}
            marca("jid")
            # El mapa de jid se rehace: los recién insertados aún no estaban en él.
            _mapa(con, "jid", "SELECT n._id, a._id FROM nueva.jid n "
                              "JOIN main.jid a ON a.raw_string = n.raw_string")

            _mapa(con, "chat", "SELECT n._id, a._id FROM nueva.chat n "
                               "JOIN map_jid mj ON mj.origen = n.jid_row_id "
                               "JOIN main.chat a ON a.jid_row_id = mj.destino")
            insertados["chat"] = _fusiona_tabla(con, "chat", cuando)
            marca("chat")
            _mapa(con, "chat", "SELECT n._id, a._id FROM nueva.chat n "
                               "JOIN map_jid mj ON mj.origen = n.jid_row_id "
                               "JOIN main.chat a ON a.jid_row_id = mj.destino")

            insertados["message"] = _fusiona_tabla(con, "message", cuando)
            marca("message")
            sin_sitio = con.execute("""
                SELECT COUNT(*) FROM nueva.message n
                 WHERE NOT EXISTS (SELECT 1 FROM map_chat mc WHERE mc.origen = n.chat_row_id)
            """).fetchone()[0]
            marca("huerfanos")
            _mapa(con, "msg", "SELECT n._id, a._id FROM nueva.message n "
                              "JOIN map_chat mc ON mc.origen = n.chat_row_id "
                              "JOIN main.message a ON a.key_id = n.key_id "
                              "                   AND a.chat_row_id = mc.destino")

            marca("mapa_mensajes")
            for tabla in ("message_media", "message_quoted", "message_revoked"):
                insertados[tabla] = _fusiona_tabla(con, tabla, cuando,
                                                   solo_de_mensajes_nuevos=True)
            marca("hijas_principales")
            for tabla in _tablas_hijas(con):
                try:
                    insertados[tabla] = _fusiona_tabla(con, tabla, cuando,
                                                       solo_de_mensajes_nuevos=True)
                except sqlite3.Error as exc:
                    # Una tabla hija que no encaje no puede costar la fusión entera: se
                    # apunta y se sigue. Lo importante —mensajes y chats— ya está dentro.
                    insertados[tabla] = f"error: {exc}"
            marca("hijas_descubiertas")

            # Lo que sigue en el móvil se sella con la fecha de hoy. Lo que no aparezca
            # conserva la fecha vieja: eso es exactamente «ya no está en el teléfono».
            con.execute("""
                UPDATE message SET wa_visto = ?
                 WHERE _id IN (SELECT destino FROM map_msg)""", (cuando,))
            con.execute("""
                UPDATE chat SET wa_visto = ?
                 WHERE _id IN (SELECT destino FROM map_chat)""", (cuando,))

            # Los mensajes huérfanos no entran en el mapa —su chat no existe, así que no
            # hay a qué conversación remapearlos— y sin esto salían marcados como
            # desaparecidos del móvil sin haberse ido: 503 falsos positivos frente a 449
            # bajas de verdad. Se sellan por `key_id`, que para ellos es lo único que hay.
            con.execute("""
                UPDATE message SET wa_visto = ?
                 WHERE wa_visto < ?
                   AND NOT EXISTS (SELECT 1 FROM chat c WHERE c._id = message.chat_row_id)
                   AND EXISTS (SELECT 1 FROM nueva.message n WHERE n.key_id = message.key_id)
            """, (cuando, cuando))

            marca("sellado")
            desaparecidos = _desaparecidos(con, cuando)
            _recalcula_punteros(con)
            marca("punteros")
            con.commit()
            marca("commit")
        except Exception:
            # Sin esto, un fallo a mitad deja la transacción abierta y ni siquiera se
            # puede soltar la base adjunta: el error real queda tapado por «is locked».
            con.rollback()
            raise
        finally:
            con.execute("DETACH DATABASE nueva")
        despues = _recuento(con)
        return {"primera_vez": False, "cuando": cuando, "insertados": insertados,
                "antes": antes, "mensajes_sin_conversacion": sin_sitio,
                "segundos": tiempos, **despues, **desaparecidos}
    finally:
        con.close()


def _recuento(con: sqlite3.Connection) -> dict:
    f = con.execute("SELECT (SELECT COUNT(*) FROM message) AS mensajes, "
                    "(SELECT COUNT(*) FROM chat) AS chats").fetchone()
    return dict(f)


def _comprueba_llaves(con: sqlite3.Connection) -> dict:
    """¿Comparten `key_id` las dos bases? Si no, no son dos copias del mismo WhatsApp.

    Es la premisa de toda la fusión, y comprobarla cuesta una consulta. Sin ella, una
    base ajena —o un `key_id` que dejara de ser estable— duplicaría el archivo entero
    en silencio, que es justo el daño que esto existe para evitar.
    """
    f = con.execute("""
        SELECT (SELECT COUNT(*) FROM nueva.message)                          AS nueva,
               (SELECT COUNT(*) FROM nueva.message n
                 WHERE EXISTS (SELECT 1 FROM main.message a WHERE a.key_id = n.key_id)) AS comunes
    """).fetchone()
    nueva, comunes = f["nueva"], f["comunes"]
    # Un margen amplio a propósito: entre dos copias reales el solapamiento es casi
    # total, y lo que se quiere descartar es el caso de «esta base no tiene nada que ver».
    return {"nueva": nueva, "comunes": comunes,
            "fiable": nueva == 0 or comunes >= min(50, nueva * 0.05)}


def _desaparecidos(con: sqlite3.Connection, cuando: str) -> dict:
    f = con.execute("""
        SELECT (SELECT COUNT(*) FROM message WHERE wa_visto < ?) AS mensajes_idos,
               (SELECT COUNT(*) FROM chat    WHERE wa_visto < ?) AS chats_idos
    """, (cuando, cuando)).fetchone()
    return dict(f)


def _recalcula_punteros(con: sqlite3.Connection) -> None:
    """Deja `last_message_row_id` y `sort_timestamp` apuntando a lo que hay en el archivo.

    Se anularon al insertar porque venían con `_id` de la otra base. Sin recalcularlos, la
    lista de conversaciones se quedaría sin último mensaje ni orden.
    """
    con.execute("""
        UPDATE chat SET last_message_row_id = (
            SELECT m._id FROM message m WHERE m.chat_row_id = chat._id
             ORDER BY m.timestamp DESC, m._id DESC LIMIT 1)""")
    con.execute("""
        UPDATE chat SET sort_timestamp = COALESCE((
            SELECT m.timestamp FROM message m WHERE m._id = chat.last_message_row_id),
            sort_timestamp)""")
