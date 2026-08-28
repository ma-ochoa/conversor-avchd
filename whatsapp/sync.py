"""Sincronización completa: medios y base de datos en una sola operación.

**Por qué en un solo paso.** Los medios y la base son inseparables: los ficheros sin la
base son archivos sueltos sin contexto, y la base sin los ficheros es una lista de cosas
que no se pueden ver. Sincronizar la mitad deja el conjunto incoherente, así que se hace
junto o no se hace.

**La base se trae entera cada vez, a propósito.** WhatsApp escribe copias incrementales,
pero reconstruir el estado aplicando incrementales exigiría entender un formato que no
está documentado y que cambia entre versiones. Traerse los ~150 MB de la copia completa
tarda unos segundos por USB y no puede salir mal. Es el intercambio correcto.

**Lo que llega puede tener menos que lo que ya había.** El móvil se limpia: se borran
conversaciones y fotos para liberar espacio. Por eso la copia del ordenador **no es un
espejo del móvil, es un histórico**, y una sincronización nunca destruye lo que ya tenía:

  · los medios ya copiados se quedan aunque desaparezcan del teléfono — el registro solo
    apunta lo que se trajo, nunca se poda contra lo que hay ahora en el móvil;
  · la base descifrada anterior se conserva en `ANTERIOR` antes de reemplazarla;
  · cada sincronización deja una instantánea de recuentos en `INSTANTANEAS`.

La **fusión acumulativa** de dos generaciones de base —quedarse con la unión de mensajes
en vez de con la última— es fase 2 y está diseñada en `HISTORICO.md`. Lo de aquí es lo
que hace falta para que esa fase pueda escribirse: sin conservar la anterior, no habría
nada que fusionar.

**El descifrado va aparte, después.** Necesita la clave de 64 dígitos, que la
sincronización no tiene ni debe guardar. La sincronización deja la copia cifrada en su
sitio y la interfaz pide la clave a continuación.

Las fases están numeradas y son observables desde fuera (`FASES`), porque esta
orquestación es lo primero que habrá que reescribir al migrar a .NET y conviene que el
contrato sea explícito.
"""

import threading
import uuid

from . import backup, history, media
from .config import (AGENDA_CIFRADA, ANTERIOR, CIFRADA, DESCIFRADA,
                     DIR_DATOS, INSTANTANEAS, load_config)

# El contrato de progreso: qué fases hay y en qué orden. La interfaz las pinta a partir
# de aquí en vez de llevar su propia copia de la lista.
FASES = (
    ("buscando",   "Buscando WhatsApp en el móvil"),
    ("inventario", "Inventariando los medios"),
    ("medios",     "Copiando los medios nuevos"),
    ("base",       "Descargando la base de datos"),
    ("agenda",     "Descargando la agenda de contactos"),
    ("terminado",  "Terminado"),
)

_jobs: dict[str, dict] = {}
_lock = threading.Lock()


def get_job(job_id: str) -> dict | None:
    with _lock:
        job = _jobs.get(job_id)
        return dict(job) if job else None


def start(kinds: list[str] | None = None, destino: str | None = None,
          con_medios: bool = True, con_base: bool = True) -> str:
    """Lanza una sincronización. Devuelve el identificador para seguir su progreso."""
    job_id = uuid.uuid4().hex
    job = {
        "id": job_id,
        "state": "en_curso",
        "fase": "buscando",
        "fases": [{"clave": c, "titulo": t} for c, t in FASES],
        "error": None,
        "avisos": [],
        "medios": {"total": 0, "copiados": 0, "omitidos": 0, "bytes": 0,
                   "bytes_total": 0, "actual": None, "errores": []},
        # El inventario recorre las 9 carpetas de WhatsApp por USB y en un móvil con
        # años de uso son decenas de miles de ficheros: varios minutos en los que hay
        # que enseñar algo, o parece que se ha colgado.
        "inventario": {"tipo": None, "vistos": 0, "de": len(media.KINDS),
                       "hechos": 0},
        "base": {"nombre": None, "bytes": 0, "bytes_total": 0, "descargada": False},
        "agenda": {"descargada": False},
        "empezado": history.marca_tiempo(),
        "terminado": None,
    }
    with _lock:
        _jobs[job_id] = job

    threading.Thread(
        target=_run, args=(job, kinds, destino, con_medios, con_base), daemon=True
    ).start()
    return job_id


def _run(job: dict, kinds, destino, con_medios: bool, con_base: bool) -> None:
    try:
        cfg = load_config()
        destino = destino or cfg["destination"]
        kinds = kinds if kinds is not None else (cfg["kinds"] or None)

        job["fase"] = "buscando"
        raiz = media.find_root()

        if con_medios:
            _sincroniza_medios(job, raiz, kinds, destino)
        if con_base:
            _descarga_base(job)

        job["fase"] = "terminado"
        job["state"] = "finalizado"
    except media.WhatsAppNotFound as exc:
        job["state"] = "error"
        job["error"] = str(exc)
    except Exception as exc:
        job["state"] = "error"
        job["error"] = f"{type(exc).__name__}: {exc}"
    finally:
        job["terminado"] = history.marca_tiempo()


def _sincroniza_medios(job: dict, raiz: str, kinds, destino: str) -> None:
    job["fase"] = "inventario"

    def avance(etiqueta, vistos):
        job["inventario"].update(tipo=etiqueta, vistos=vistos,
                                 hechos=job["inventario"]["hechos"] + 1)

    # Inventario siempre completo, aunque solo se copie un tipo: el plan necesita saber
    # qué hay para poder decir qué falta.
    escaneo = media.scan_phone(root=raiz, kinds=None, progress_cb=avance)

    plan = media.build_plan(
        escaneo, destino, kinds=kinds,
        already_imported=history.claves_copiadas(), skip_duplicates=True,
    )
    job["medios"]["total"] = plan["totals"]["files"]
    job["medios"]["omitidos"] = plan["totals"]["skipped_duplicates"]
    job["medios"]["bytes_total"] = plan["totals"]["bytes"]
    # Se publica para que la interfaz no presente como total una cifra que sabe corta.
    job["medios"]["sin_tamano"] = plan["totals"].get("sin_tamano", 0)

    if not plan["items"]:
        job["avisos"].append("No había ningún medio nuevo que copiar.")
        return

    job["fase"] = "medios"
    from .jobs import copia_items                          # tardío: evita el ciclo
    copia_items(plan["items"], progreso=lambda hechos, bytes_, actual: job["medios"].update(
        copiados=hechos, bytes=bytes_, actual=actual),
        errores=job["medios"]["errores"])

    history.registra_run({
        "source": raiz, "destination": destino,
        "finished_at": history.marca_tiempo(),
        "copied": job["medios"]["copiados"], "errors": len(job["medios"]["errores"]),
        "bytes": job["medios"]["bytes"],
    })


def _descarga_base(job: dict) -> None:
    job["fase"] = "base"
    copias = backup.busca_copias()
    if copias["needs_e2e"]:
        # No es un fallo de la sincronización: los medios sí se han traído. Se avisa y se
        # sigue, porque exigir el cifrado de extremo a extremo para copiar fotos sería
        # castigar al usuario por algo que no tiene que ver.
        job["avisos"].append(
            "No hay ninguna copia .crypt15 en el móvil: la base de datos no se puede "
            "traer todavía. Activa la copia cifrada de extremo a extremo en WhatsApp "
            "(Ajustes → Chats → Copia de seguridad) y vuelve a sincronizar."
        )
        return

    mejor = copias["best"]
    job["base"]["nombre"] = mejor["name"]
    job["base"]["bytes_total"] = mejor["size"]

    def progreso(hechos, total):
        job["base"]["bytes"] = hechos
        if total:
            job["base"]["bytes_total"] = total

    # La base descifrada de la vuelta anterior se aparta ANTES de traer la nueva: en
    # cuanto se descifre la nueva, la vieja se perdería, y con ella la única prueba de
    # qué había en el móvil antes de que el usuario borrara nada.
    _conserva_anterior(job)

    destino = backup.descarga_copia(mejor, progress_cb=progreso)
    if destino != CIFRADA:
        destino.replace(CIFRADA)
    job["base"]["descargada"] = True
    job["base"]["bytes"] = CIFRADA.stat().st_size

    # Lo hablado desde esa copia completa está en las incrementales, que son diminutas
    # (decenas de KB) y sin ellas se pierde el último tramo: aquí, un día entero.
    try:
        traidas = backup.descarga_incrementales(copias["incrementales"])
        job["base"]["incrementales"] = [t["name"] for t in traidas]
        if traidas:
            job["avisos"].append(
                f"Se han traído {len(traidas)} copias incrementales con lo posterior a "
                f"«{mejor['name']}». Se descifran junto a la base y se guardan aparte: "
                f"no la sustituyen."
            )
    except Exception as exc:
        job["avisos"].append(f"No se pudieron traer las copias incrementales: {exc}")

    # La agenda es un fichero aparte y diminuto (30 KB), pero es lo único que convierte
    # números de teléfono en nombres. Sin ella la interfaz es mucho peor.
    job["fase"] = "agenda"
    try:
        _descarga_agenda(job, copias["folder"])
    except Exception as exc:
        job["avisos"].append(f"No se pudo traer la agenda de contactos: {exc}")


def _conserva_anterior(job: dict) -> None:
    """Aparta la base descifrada actual y deja constancia de lo que contenía."""
    if not DESCIFRADA.is_file():
        return
    try:
        from . import chats
        resumen = chats.resumen_chats()
    except Exception:
        resumen = {}

    try:
        INSTANTANEAS.mkdir(parents=True, exist_ok=True)
        sello = history.marca_tiempo().replace(":", "").replace("-", "")
        import json
        (INSTANTANEAS / f"{sello}.json").write_text(
            json.dumps({"cuando": history.marca_tiempo(), **resumen},
                       indent=2, ensure_ascii=False), encoding="utf-8")
        DESCIFRADA.replace(ANTERIOR)
        job["avisos"].append(
            f"La base anterior ({resumen.get('mensajes', 0):,} mensajes) se ha guardado "
            f"como copia de la vuelta pasada, para poder comparar qué ha desaparecido."
        )
    except OSError as exc:
        job["avisos"].append(f"No se pudo conservar la base anterior: {exc}")


def _descarga_agenda(job: dict, carpeta_databases: str) -> None:
    """`wa.db` no vive en `Databases/` sino en `Backups/`, que es la carpeta hermana."""
    from . import dispositivo

    backups = f"{carpeta_databases.rsplit('/', 1)[0]}/Backups"
    ficheros = {f["name"]: f for f in dispositivo.lista_ficheros(backups, recursivo=False)}
    entrada = ficheros.get("wa.db.crypt15")
    if not entrada:
        job["avisos"].append(
            "No hay `wa.db.crypt15` en el móvil: la interfaz enseñará números de "
            "teléfono en vez de nombres."
        )
        return

    DIR_DATOS.mkdir(parents=True, exist_ok=True)
    dispositivo.descarga(backups, entrada["name"], AGENDA_CIFRADA, entrada["size"])
    job["agenda"]["descargada"] = True


def estado() -> dict:
    """Qué hay ahora mismo: para que la interfaz sepa qué ofrecer sin tocar el móvil."""
    from . import chats

    info = backup.estado()
    lista = history.load()["copiado"]
    info["medios_copiados"] = len(lista)
    info["ultima_sync"] = (history.runs(1) or [{}])[0].get("finished_at")
    info["agenda_cifrada"] = AGENDA_CIFRADA.is_file()
    from . import archivo
    info["archivo"] = archivo.estado()
    try:
        info["indices_listos"] = chats.indices_listos()
    except Exception:
        info["indices_listos"] = False
    return info
