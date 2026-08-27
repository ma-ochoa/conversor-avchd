"""Interfaz web para convertir clips AVCHD (.MTS) a MP4 sin recompresión de vídeo,
y renombrar vídeos/fotos con su fecha y hora de captura."""

import os
import platform
import subprocess
import uuid
from pathlib import Path

from flask import Flask, abort, jsonify, render_template, request, send_file

from converter.avanzada import DepsMissingError, check_deps
from converter.avanzada_jobs import (
    PROCESOS,
    get_job as get_avanzada_job,
    start_job as start_avanzada_job,
)
from converter.config import get_working_dir, set_working_dir
from converter.ffmpeg_ops import ToolsMissingError, check_tools
from converter.fonts import list_system_fonts
from converter.fs_access import FolderAccessBlockedError, list_subdirs
from converter.jobs import get_job, start_job
from converter.montaje_clips import list_available_clips
from converter.project import (
    list_projects,
    load_project,
    new_project,
    project_path,
    save_project,
)
from converter.scanner import scan_folder
from converter.stabilize import (
    ZOOM_AUTO_DYNAMIC,
    ZOOM_AUTO_STATIC,
    ZOOM_MANUAL,
    VidstabMissingError,
    discard_stabilize_draft,
    find_ffmpeg_with_vidstab,
    save_stabilize_draft,
)
from converter.stabilize_jobs import get_job as get_stabilize_job, start_job as start_stabilize_job
from converter.thumbnails import get_or_create_thumbnail
from converter.timeline_jobs import get_export_job, start_export
from converter.analyze_jobs import get_analysis_job, start_analysis
from converter.recompress_jobs import get_job as get_recompress_job, start_job as start_recompress_job

from importer import geoindex, history as import_history
from importer.config import load_config, public_config, save_config
from importer.geomatch import (
    DEFAULT_TOLERANCE_MINUTES,
    match_groups,
    references_from_folder,
    references_from_index,
)
from importer.geowrite import restore as restore_original
from importer.gpx import GpxError, default_utc_offset, load_gpx
from importer.groups import DEFAULT_GAP_MINUTES, build_groups
from importer.location_jobs import get_assign_job, start_assign, start_reindex
from importer.places import PlacesError, reverse as reverse_place, search as search_places
from importer.jobs import get_job as get_import_job, start_job as start_import_job
from importer.media import scan_source
from importer.nas import (
    NasError,
    NasOtpRequired,
    create_folder as nas_create_folder,
    list_folders as nas_list_folders,
    test_connection,
)
from importer import mtp
from importer.history import imported_keys
from importer.mtp_jobs import cleanup as mtp_cleanup, pending_downloads
from importer.mtp_scan import is_mtp_source, scan_phone, to_mtp_path, to_source as mtp_source
from importer.phones import detect_phones, open_transfer_app
from importer.nas_jobs import get_upload_job, start_upload
from importer.plan import build_plan, free_space
from importer.sources import describe_source, detect_sources
from importer.thumbs import get_phone_thumbnail, get_thumbnail
import whatsapp as wa
from whatsapp import (agenda as wa_agenda, backup as wa_backup,
                      chats as wa_chats,
                      galeria as wa_galeria, jobs as wa_jobs,
                      media as wa_media, miniaturas as wa_miniaturas,
                      sync as wa_sync)

app = Flask(__name__)

_MEDIA_EXTS = {".mp4", ".mov", ".jpg", ".jpeg", ".png", ".gif"}

# El escaneo de una tarjeta puede tener miles de ficheros: se guarda aquí y el navegador
# solo maneja el identificador, en vez de reenviar el listado completo en cada paso.
_scans: dict[str, dict] = {}
_MAX_SCANS = 5



@app.route("/")
def index():
    return render_template("index.html", home=str(Path.home()), active="conversion")


@app.route("/ajustes")
def ajustes_page():
    return render_template("ajustes.html", home=str(Path.home()), active="ajustes")


@app.route("/api/config", methods=["GET", "POST"])
def config():
    if request.method == "POST":
        data = request.get_json(force=True)
        raw_path = (data.get("working_dir") or "").strip()
        if raw_path:
            candidate = Path(raw_path).expanduser()
            if not candidate.is_dir():
                return jsonify({"error": f"No es una carpeta válida: {candidate}"}), 400
            set_working_dir(raw_path)
        else:
            set_working_dir(None)

    working_dir = get_working_dir()
    return jsonify({"working_dir": str(working_dir) if working_dir else None})


@app.route("/api/browse")
def browse():
    raw_path = request.args.get("path") or str(Path.home())
    path = Path(raw_path).expanduser()

    if not path.is_dir():
        return jsonify({"error": f"No es una carpeta: {path}"}), 400

    # `retry=1` lo manda el botón "Reintentar" que sale al bloquearse una carpeta:
    # sirve para volver a probar tras conceder el permiso, sin reiniciar la app.
    retry = request.args.get("retry") in ("1", "true")

    try:
        entries = list_subdirs(path, retry_blocked=retry)
    except FolderAccessBlockedError as exc:
        # macOS no contesta al listar una carpeta protegida sin permiso concedido; sin
        # esto la petición no volvería nunca y la página se quedaría colgada.
        return jsonify({"error": str(exc), "blocked": True}), 403
    except PermissionError:
        return jsonify({"error": f"Sin permiso para leer: {path}"}), 403
    except OSError as exc:
        return jsonify({"error": f"No se pudo leer {path}: {exc.strerror or exc}"}), 400

    return jsonify({
        "path": str(path),
        "parent": str(path.parent) if path != path.parent else None,
        "dirs": [{"name": p.name, "path": str(p)} for p in entries],
    })


def _escape_applescript(text: str) -> str:
    return text.replace("\\", "\\\\").replace('"', '\\"')


@app.route("/api/pick-folder", methods=["POST"])
def pick_folder():
    if platform.system() != "Darwin":
        return jsonify({"error": "El selector nativo de carpetas solo está disponible en macOS."}), 400

    data = request.get_json(silent=True) or {}
    start_path = Path(data.get("path") or Path.home()).expanduser()
    if not start_path.is_dir():
        start_path = Path.home()

    script = (
        'POSIX path of (choose folder with prompt "Selecciona la carpeta de origen" '
        f'default location (POSIX file "{_escape_applescript(str(start_path))}"))'
    )
    result = subprocess.run(["osascript", "-e", script], capture_output=True, text=True)
    if result.returncode != 0:
        return jsonify({"canceled": True})
    return jsonify({"path": result.stdout.strip()})


@app.route("/api/pick-file", methods=["POST"])
def pick_file():
    if platform.system() != "Darwin":
        return jsonify({"error": "El selector nativo de archivos solo está disponible en macOS."}), 400

    data = request.get_json(silent=True) or {}
    start_path = Path(data.get("path") or Path.home()).expanduser()
    if not start_path.is_dir():
        start_path = Path.home()

    script = (
        'POSIX path of (choose file with prompt "Selecciona una imagen (PNG con transparencia recomendado)" '
        f'default location (POSIX file "{_escape_applescript(str(start_path))}") '
        'of type {"png", "jpg", "jpeg", "gif"})'
    )
    result = subprocess.run(["osascript", "-e", script], capture_output=True, text=True)
    if result.returncode != 0:
        return jsonify({"canceled": True})
    return jsonify({"path": result.stdout.strip()})


@app.route("/api/scan", methods=["POST"])
def scan():
    data = request.get_json(force=True)
    folder = data.get("path", "")
    try:
        check_tools()
    except ToolsMissingError as exc:
        return jsonify({"error": str(exc)}), 500
    try:
        result = scan_folder(folder)
    except NotADirectoryError:
        return jsonify({"error": f"No es una carpeta válida: {folder}"}), 400
    return jsonify(result)


@app.route("/api/convert", methods=["POST"])
def convert():
    data = request.get_json(force=True)
    root = data.get("root")
    avchd_paths = data.get("avchd_paths", [])
    photo_paths = data.get("photo_paths", [])
    transcode_audio = bool(data.get("transcode_audio", False))
    force = bool(data.get("force", False))
    prefix = data.get("prefix", "")

    if not root or (not avchd_paths and not photo_paths):
        return jsonify({"error": "Nada que convertir"}), 400

    job_id = start_job(root, avchd_paths, photo_paths, transcode_audio, force, prefix)
    return jsonify({"job_id": job_id})


@app.route("/api/status/<job_id>")
def status(job_id):
    job = get_job(job_id)
    if not job:
        return jsonify({"error": "Trabajo no encontrado"}), 404
    return jsonify(job)


def _clamp(value, lo, hi):
    return max(lo, min(hi, value))


_INTERPOL_VALUES = ("no", "linear", "bilinear", "bicubic")
_OPTALGO_VALUES = ("gauss", "avg")


def _parse_stab_params(data: dict) -> dict:
    zoom_mode = data.get("zoom_mode", ZOOM_AUTO_STATIC)
    if zoom_mode not in (ZOOM_AUTO_STATIC, ZOOM_AUTO_DYNAMIC, ZOOM_MANUAL):
        zoom_mode = ZOOM_AUTO_STATIC
    interpol = data.get("interpol", "bilinear")
    if interpol not in _INTERPOL_VALUES:
        interpol = "bilinear"
    optalgo = data.get("optalgo", "gauss")
    if optalgo not in _OPTALGO_VALUES:
        optalgo = "gauss"
    maxshift = int(data.get("maxshift", -1))
    maxshift = maxshift if maxshift < 0 else int(_clamp(maxshift, 0, 500))
    maxangle = float(data.get("maxangle", -1.0))
    maxangle = maxangle if maxangle < 0 else _clamp(maxangle, 0.0, 90.0)
    return {
        "shakiness": int(_clamp(int(data.get("shakiness", 5)), 1, 10)),
        "accuracy": int(_clamp(int(data.get("accuracy", 15)), 1, 15)),
        "smoothing": int(_clamp(int(data.get("smoothing", 10)), 0, 100)),
        "zoom_mode": zoom_mode,
        "zoom_percent": _clamp(float(data.get("zoom_percent", 0.0)), -50.0, 50.0),
        "stepsize": int(_clamp(int(data.get("stepsize", 6)), 1, 32)),
        "mincontrast": _clamp(float(data.get("mincontrast", 0.25)), 0.0, 1.0),
        "interpol": interpol,
        "optalgo": optalgo,
        "maxshift": maxshift,
        "maxangle": maxangle,
    }


@app.route("/api/stabilize", methods=["POST"])
def stabilize():
    data = request.get_json(force=True)
    root = data.get("root")
    avchd_paths = data.get("avchd_paths", [])
    force = bool(data.get("force", False))
    fast_hw = bool(data.get("fast_hw", False))

    if not root or not avchd_paths:
        return jsonify({"error": "Nada que estabilizar"}), 400

    try:
        find_ffmpeg_with_vidstab()
    except VidstabMissingError as exc:
        return jsonify({"error": str(exc)}), 500

    params = _parse_stab_params(data)

    job_id = start_stabilize_job(root, avchd_paths, force, fast_hw, params)
    return jsonify({"job_id": job_id})


@app.route("/api/stabilize-status/<job_id>")
def stabilize_status(job_id):
    job = get_stabilize_job(job_id)
    if not job:
        return jsonify({"error": "Trabajo no encontrado"}), 404
    return jsonify(job)


@app.route("/api/stabilize-draft", methods=["POST"])
def stabilize_draft_save():
    data = request.get_json(force=True)
    root = data.get("root")
    path = data.get("path")
    if not root or not path:
        return jsonify({"error": "Falta root o path"}), 400
    entry = save_stabilize_draft(Path(root), Path(path), _parse_stab_params(data))
    return jsonify({"draft": entry})


@app.route("/api/stabilize-draft", methods=["DELETE"])
def stabilize_draft_discard():
    data = request.get_json(force=True)
    root = data.get("root")
    path = data.get("path")
    if not root or not path:
        return jsonify({"error": "Falta root o path"}), 400
    discard_stabilize_draft(Path(root), Path(path))
    return jsonify({"ok": True})


@app.route("/estabilizacion")
def estabilizacion_page():
    return render_template("estabilizacion.html", home=str(Path.home()), active="estabilizacion")


@app.route("/montaje")
def montaje_page():
    return render_template("montaje.html", home=str(Path.home()), active="montaje")


@app.route("/media")
def media():
    raw_path = request.args.get("path", "")
    path = Path(raw_path).expanduser()
    if path.suffix.lower() not in _MEDIA_EXTS or not path.is_file():
        abort(404)
    return send_file(path, conditional=True)


@app.route("/api/montaje/clips")
def montaje_clips():
    root = request.args.get("root", "")
    if not root:
        return jsonify({"error": "Falta la carpeta de origen"}), 400
    try:
        clips = list_available_clips(root)
    except Exception as exc:
        return jsonify({"error": str(exc)}), 400
    return jsonify({"clips": clips})


@app.route("/api/montaje/thumbnail")
def montaje_thumbnail():
    root = request.args.get("root", "")
    clip_path = request.args.get("path", "")
    if not root or not clip_path:
        abort(404)
    try:
        thumb = get_or_create_thumbnail(Path(root).expanduser().resolve(), Path(clip_path))
    except Exception:
        abort(404)
    return send_file(thumb, conditional=True)


@app.route("/api/montaje/fonts")
def montaje_fonts():
    return jsonify({"fonts": list_system_fonts()[:80]})


@app.route("/api/montaje/projects")
def montaje_projects():
    root = request.args.get("root", "")
    if not root:
        return jsonify({"error": "Falta la carpeta de origen"}), 400
    root_path = Path(root).expanduser().resolve()
    return jsonify({"projects": list_projects(root_path)})


@app.route("/api/montaje/project", methods=["GET", "POST", "DELETE"])
def montaje_project():
    if request.method == "GET":
        root = request.args.get("root", "")
        name = request.args.get("name", "")
        if not root or not name:
            return jsonify({"error": "Falta carpeta o nombre de proyecto"}), 400
        root_path = Path(root).expanduser().resolve()
        try:
            return jsonify(load_project(root_path, name))
        except FileNotFoundError:
            return jsonify({"error": f"No existe el proyecto '{name}'"}), 404

    if request.method == "DELETE":
        root = request.args.get("root", "")
        name = request.args.get("name", "")
        if not root or not name:
            return jsonify({"error": "Falta carpeta o nombre de proyecto"}), 400
        root_path = Path(root).expanduser().resolve()
        path = project_path(root_path, name)
        path.unlink(missing_ok=True)
        return jsonify({"deleted": True})

    data = request.get_json(force=True)
    root = data.get("root", "")
    name = data.get("name", "")
    project = data.get("project")
    if not root or not name or project is None:
        return jsonify({"error": "Falta carpeta, nombre o contenido del proyecto"}), 400
    root_path = Path(root).expanduser().resolve()
    saved_path = save_project(root_path, name, project)
    return jsonify({"saved": str(saved_path)})


@app.route("/api/montaje/new-project")
def montaje_new_project():
    root = request.args.get("root", "")
    if not root:
        return jsonify({"error": "Falta la carpeta de origen"}), 400
    return jsonify(new_project(root))


@app.route("/api/montaje/export", methods=["POST"])
def montaje_export():
    data = request.get_json(force=True)
    root = data.get("root")
    project_name = data.get("name", "montaje")
    clips = data.get("clips", [])
    transition_seconds = float(data.get("transition_seconds", 2.0))

    if not root or not clips:
        return jsonify({"error": "El montaje no tiene clips"}), 400

    try:
        find_ffmpeg_with_vidstab()
    except VidstabMissingError as exc:
        return jsonify({"error": str(exc)}), 500

    job_id = start_export(root, project_name, clips, transition_seconds)
    return jsonify({"job_id": job_id})


@app.route("/api/montaje/export-status/<job_id>")
def montaje_export_status(job_id):
    job = get_export_job(job_id)
    if not job:
        return jsonify({"error": "Trabajo no encontrado"}), 404
    return jsonify(job)


@app.route("/api/montaje/analyze", methods=["POST"])
def montaje_analyze():
    data = request.get_json(force=True)
    root = data.get("root")
    path = data.get("path")
    if not root or not path:
        return jsonify({"error": "Falta carpeta o clip"}), 400

    try:
        find_ffmpeg_with_vidstab()
    except VidstabMissingError as exc:
        return jsonify({"error": str(exc)}), 500

    shakiness = int(_clamp(int(data.get("shakiness", 5)), 1, 10))
    accuracy = int(_clamp(int(data.get("accuracy", 15)), 1, 15))
    stepsize = int(_clamp(int(data.get("stepsize", 6)), 1, 32))
    mincontrast = _clamp(float(data.get("mincontrast", 0.25)), 0.0, 1.0)
    job_id = start_analysis(root, path, shakiness, accuracy, stepsize, mincontrast)
    return jsonify({"job_id": job_id})


@app.route("/api/montaje/analyze-status/<job_id>")
def montaje_analyze_status(job_id):
    job = get_analysis_job(job_id)
    if not job:
        return jsonify({"error": "Trabajo no encontrado"}), 404
    return jsonify(job)


@app.route("/avanzada")
def avanzada_page():
    return render_template("avanzada.html", home=str(Path.home()), active="avanzada")


@app.route("/api/avanzada", methods=["POST"])
def avanzada():
    data = request.get_json(force=True)
    root = data.get("root")
    proceso = data.get("proceso")
    paths = data.get("paths", [])
    params = data.get("params") or {}

    if not root or not paths:
        return jsonify({"error": "No hay nada seleccionado"}), 400
    if proceso not in PROCESOS:
        return jsonify({"error": f"Proceso desconocido: {proceso}"}), 400

    try:
        check_tools()
        check_deps()
    except (ToolsMissingError, DepsMissingError) as exc:
        return jsonify({"error": str(exc)}), 500

    job_id = start_avanzada_job(root, proceso, paths, params)
    return jsonify({"job_id": job_id})


@app.route("/api/avanzada-status/<job_id>")
def avanzada_status(job_id):
    job = get_avanzada_job(job_id)
    if not job:
        return jsonify({"error": "Trabajo no encontrado"}), 404
    return jsonify(job)


@app.route("/recompresion")
def recompresion_page():
    return render_template("recompresion.html", home=str(Path.home()), active="recompresion")


@app.route("/api/recompress", methods=["POST"])
def recompress():
    data = request.get_json(force=True)
    root = data.get("root")
    paths = data.get("paths", [])
    quality = data.get("quality", "media")
    max_width = data.get("max_width", "original")
    force = bool(data.get("force", False))

    if not root or not paths:
        return jsonify({"error": "Nada que recomprimir"}), 400

    try:
        find_ffmpeg_with_vidstab()
    except VidstabMissingError as exc:
        return jsonify({"error": str(exc)}), 500

    if quality not in ("alta", "media", "baja"):
        quality = "media"
    if max_width not in ("original", "1080p", "720p", "480p"):
        max_width = "original"

    job_id = start_recompress_job(root, paths, quality, max_width, force)
    return jsonify({"job_id": job_id})


@app.route("/api/recompress-status/<job_id>")
def recompress_status(job_id):
    job = get_recompress_job(job_id)
    if not job:
        return jsonify({"error": "Trabajo no encontrado"}), 404
    return jsonify(job)


@app.route("/importacion")
def importacion_page():
    return render_template("importacion.html", active="importacion")


@app.route("/api/importacion/config", methods=["GET", "POST"])
def importacion_config():
    if request.method == "GET":
        return jsonify(public_config())

    updates = request.get_json(force=True)
    nas = updates.get("nas")
    if isinstance(nas, dict):
        # El navegador nunca recibe las credenciales, así que tampoco las reenvía: una
        # cadena vacía significa "deja la que ya había", no "bórrala".
        for field in ("password", "otp"):
            if not nas.get(field):
                nas.pop(field, None)
        nas.pop("has_password", None)
        nas.pop("has_otp", None)
    save_config(updates)
    return jsonify(public_config())


@app.route("/api/importacion/sources")
def importacion_sources():
    return jsonify(detect_sources(retry_blocked=request.args.get("retry") == "1"))


@app.route("/api/importacion/scan", methods=["POST"])
def importacion_scan():
    data = request.get_json(force=True)
    path = data.get("path", "")
    if not path:
        return jsonify({"error": "Falta el origen a escanear"}), 400

    config = load_config()
    imported = import_history.imported_keys() if config["skip_duplicates"] else set()

    # El móvil es un origen más: se escanea leyendo sus metadatos por MTP, sin descargar
    # nada, y a partir de aquí el flujo es idéntico al de una tarjeta.
    if is_mtp_source(path):
        try:
            scan = scan_phone(to_mtp_path(path), config, already_imported=imported)
        except mtp.MtpError as exc:
            return jsonify({"error": str(exc)}), 400
        source = {
            "path": path,
            "label": scan["cameras"][0]["suggested"] if scan["cameras"] else "Móvil",
            "kind": "movil",
            "is_card": True,
            "parent": None,
            "removable": True,
            "total_bytes": None,
            "free_bytes": None,
        }
    else:
        try:
            source = describe_source(path)
        except NotADirectoryError:
            return jsonify({"error": f"No es una carpeta válida: {path}"}), 400
        scan = scan_source(source["path"], config, already_imported=imported)

    scan_id = uuid.uuid4().hex
    _scans[scan_id] = scan
    for stale in list(_scans)[:-_MAX_SCANS]:
        _scans.pop(stale, None)

    return jsonify({
        "scan_id": scan_id,
        "source": source,
        "cameras": scan["cameras"],
        "totals": scan["totals"],
        "files": [
            {k: f[k] for k in ("path", "name", "size", "category", "day", "camera_key",
                               "capture_dt", "date_source", "duplicate", "gps")}
            for f in scan["files"] if f["category"] != "sidecar"
        ],
        "free_bytes": free_space(config["destination"]),
    })


@app.route("/api/importacion/plan", methods=["POST"])
def importacion_plan():
    data = request.get_json(force=True)
    scan = _scans.get(data.get("scan_id", ""))
    if scan is None:
        return jsonify({"error": "El escaneo ha caducado. Vuelve a escanear el origen."}), 404

    config = load_config()
    if data.get("destination"):
        config["destination"] = data["destination"]

    plan = build_plan(scan, config, data.get("camera_folders", {}),
                      data.get("events", {}), data.get("options", {}))
    return jsonify({
        "destination": plan["destination"],
        "tree": plan["tree"],
        "totals": plan["totals"],
        "free_bytes": free_space(plan["destination"]),
        "preview": plan["items"][:40],
    })


@app.route("/api/importacion/start", methods=["POST"])
def importacion_start():
    data = request.get_json(force=True)
    scan = _scans.get(data.get("scan_id", ""))
    if scan is None:
        return jsonify({"error": "El escaneo ha caducado. Vuelve a escanear el origen."}), 404

    config = load_config()
    if data.get("destination"):
        config["destination"] = data["destination"]
        save_config({"destination": data["destination"]})

    options = data.get("options", {})
    camera_folders = data.get("camera_folders", {})
    plan = build_plan(scan, config, camera_folders, data.get("events", {}), options)
    if not plan["items"]:
        return jsonify({"error": "No hay nada que importar con las opciones elegidas."}), 400

    available = free_space(plan["destination"])
    if available is not None and available < plan["totals"]["bytes"]:
        return jsonify({
            "error": "No hay espacio suficiente en el destino: "
                     f"hacen falta {plan['totals']['bytes'] / 1e9:.1f} GB y quedan {available / 1e9:.1f} GB."
        }), 400

    job_id = start_import_job(
        scan["source"], plan["items"],
        {**options, "destination": plan["destination"]},
        camera_folders,
    )
    return jsonify({"job_id": job_id, "totals": plan["totals"]})


@app.route("/api/importacion/status/<job_id>")
def importacion_status(job_id):
    job = get_import_job(job_id)
    if not job:
        return jsonify({"error": "Trabajo no encontrado"}), 404
    return jsonify(job)


@app.route("/api/importacion/thumb")
def importacion_thumb():
    path = request.args.get("path", "")
    if not path:
        abort(404)
    try:
        # Un origen del móvil no es un fichero en disco: su miniatura hay que pedírsela
        # al propio dispositivo, que guarda una previsualización de cada foto.
        if is_mtp_source(path):
            return send_file(get_phone_thumbnail(to_mtp_path(path)), conditional=True)
        return send_file(get_thumbnail(path), conditional=True)
    except Exception:
        abort(404)


@app.route("/api/importacion/history")
def importacion_history():
    return jsonify({
        "runs": import_history.recent_runs(),
        "pending_upload": import_history.pending_upload(),
    })


@app.route("/api/importacion/nas-test", methods=["POST"])
def importacion_nas_test():
    data = request.get_json(silent=True) or {}
    settings = {**load_config()["nas"], **{k: v for k, v in data.items() if v not in ("", None)}}
    try:
        result = test_connection(settings)
    except NasOtpRequired as exc:
        # No es un fallo: el navegador tiene que pedir el código y reintentar. Va como
        # `message` y no como `error` a propósito — el ayudante del frontend convierte
        # cualquier `error` en una excepción, y esto no lo es.
        return jsonify({"ok": False, "needs_otp": True, "message": str(exc)}), 200
    except NasError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400
    except Exception as exc:
        return jsonify({"ok": False, "error": f"Error inesperado: {exc}"}), 400

    # Si el NAS ha devuelto un token de dispositivo, se guarda: es lo que evita volver a
    # pedir el código en los siguientes envíos.
    device_id = result.pop("device_id", None)
    if device_id and device_id != load_config()["nas"].get("device_id"):
        config = load_config()
        config["nas"]["device_id"] = device_id
        save_config(config)
        result["device_token_saved"] = True

    return jsonify(result)


@app.route("/api/importacion/nas-browse", methods=["POST"])
def importacion_nas_browse():
    data = request.get_json(force=True)
    settings = {**load_config()["nas"], **{k: v for k, v in data.items()
                                           if k != "path" and v not in ("", None)}}
    try:
        return jsonify(nas_list_folders(settings, data.get("path", "")))
    except NasOtpRequired as exc:
        return jsonify({"needs_otp": True, "message": str(exc)}), 200
    except NasError as exc:
        return jsonify({"error": str(exc)}), 400


@app.route("/api/importacion/nas-mkdir", methods=["POST"])
def importacion_nas_mkdir():
    data = request.get_json(force=True)
    settings = {**load_config()["nas"], **{k: v for k, v in data.items()
                                           if k not in ("parent", "name") and v not in ("", None)}}
    try:
        return jsonify(nas_create_folder(settings, data.get("parent", ""), data.get("name", "")))
    except NasOtpRequired as exc:
        return jsonify({"needs_otp": True, "message": str(exc)}), 200
    except NasError as exc:
        return jsonify({"error": str(exc)}), 400


@app.route("/api/importacion/phones")
def importacion_phones():
    # `detect_phones` mira el USB (rápido y siempre disponible); `mtp.detect` dice cuáles
    # se pueden además abrir para leer sus carpetas.
    usb = detect_phones()
    readable = mtp.detect() if usb else []
    return jsonify({
        "phones": usb,
        "readable": readable,
        "mtp_available": mtp.available(),
        # La interfaz enseña este mismo comando, para no inventarse uno que no funcione.
        "mtp_install_command": mtp.como_instalar(),
    })


@app.route("/api/importacion/mtp/folder", methods=["POST"])
def importacion_mtp_folder():
    data = request.get_json(silent=True) or {}
    try:
        return jsonify(mtp.list_folder(data.get("path") or "/"))
    except mtp.MtpError as exc:
        return jsonify({"error": str(exc)}), 400


@app.route("/api/importacion/mtp/pending")
def importacion_mtp_pending():
    return jsonify({"downloads": pending_downloads()})


@app.route("/api/importacion/mtp/cleanup", methods=["POST"])
def importacion_mtp_cleanup():
    data = request.get_json(force=True)
    return jsonify({"removed": mtp_cleanup(data.get("path", ""))})


@app.route("/api/importacion/open-transfer-app", methods=["POST"])
def importacion_open_transfer_app():
    data = request.get_json(silent=True) or {}
    ok, message = open_transfer_app(data.get("kind", "android"))
    return jsonify({"ok": ok, "message": message}), (200 if ok else 400)


@app.route("/api/importacion/nas-forget-device", methods=["POST"])
def importacion_nas_forget_device():
    """Olvida el token de dispositivo: el próximo envío volverá a pedir el código 2FA.

    Solo lo borra de este equipo. Para revocarlo también en el NAS hay que quitarlo en
    DSM → Panel de control → Usuario → Avanzado → dispositivos de confianza.
    """
    config = load_config()
    config["nas"]["device_id"] = ""
    save_config(config)
    return jsonify({"ok": True})


@app.route("/api/importacion/nas-upload", methods=["POST"])
def importacion_nas_upload():
    pending = import_history.pending_upload()
    if not pending:
        return jsonify({"error": "No hay nada pendiente de subir al NAS."}), 400
    return jsonify({"job_id": start_upload(pending), "total": len(pending)})


@app.route("/api/importacion/nas-status/<job_id>")
def importacion_nas_status(job_id):
    job = get_upload_job(job_id)
    if not job:
        return jsonify({"error": "Trabajo no encontrado"}), 404
    return jsonify(job)



# =============================================================================
# WhatsApp
#
# Todo bajo /whatsapp y /api/whatsapp, hablando solo con el paquete `whatsapp`.
# Está así para poder sacarlo entero a una app aparte: al extraerlo, estas rutas
# se van con él y aquí no queda nada. Ver whatsapp/__init__.py.
# =============================================================================

_wa_scans: dict[str, dict] = {}
_WA_MAX_SCANS = 5


def _wa_error(exc: Exception, codigo: int = 400):
    return jsonify({"error": str(exc)}), codigo


# ------------------------------------------------------------------------ páginas

@app.route("/whatsapp")
def whatsapp_page():
    return render_template("whatsapp_sync.html", active="whatsapp", sub="sync")


@app.route("/whatsapp/chats")
def whatsapp_chats_page():
    return render_template("whatsapp_chats.html", active="whatsapp", sub="chats")


@app.route("/whatsapp/galeria")
def whatsapp_galeria_page():
    return render_template("whatsapp_galeria.html", active="whatsapp", sub="galeria")


@app.route("/whatsapp/contactos")
def whatsapp_contactos_page():
    return render_template("whatsapp_contactos.html", active="whatsapp", sub="contactos")


# ------------------------------------------------------------------ estado general

@app.route("/api/whatsapp/estado")
def whatsapp_estado():
    cfg = wa.config.load_config()
    datos = {
        **cfg,
        "all_kinds": [{"key": k["key"], "label": k["label"], "default": k["default"]}
                      for k in wa_media.KINDS],
        "sync": wa_sync.estado(),
        "runs": wa.history.runs(),
    }
    try:
        datos["db"] = wa_chats.resumen_chats()
    except wa_chats.SinBaseDeDatos:
        datos["db"] = None
    return jsonify(datos)


@app.route("/api/whatsapp/config", methods=["POST"])
def whatsapp_guarda_config():
    data = request.get_json(force=True)
    permitido = {k: v for k, v in data.items() if k in ("destination", "kinds")}
    return jsonify(wa.config.save_config(permitido))


# ---------------------------------------------------------------- sincronización

@app.route("/api/whatsapp/sync", methods=["POST"])
def whatsapp_sync():
    data = request.get_json(silent=True) or {}
    kinds = data.get("kinds") if isinstance(data.get("kinds"), list) else None
    return jsonify({"job_id": wa_sync.start(
        kinds=kinds, destino=data.get("destination"),
        con_medios=data.get("con_medios", True),
        con_base=data.get("con_base", True),
    )})


@app.route("/api/whatsapp/sync/<job_id>")
def whatsapp_sync_estado(job_id):
    job = wa_sync.get_job(job_id) or wa_jobs.get_job(job_id)
    if not job:
        return jsonify({"error": "Trabajo no encontrado"}), 404
    return jsonify(job)


@app.route("/api/whatsapp/backups")
def whatsapp_backups():
    try:
        return jsonify(wa_backup.busca_copias())
    except (wa_media.WhatsAppNotFound, wa_backup.BackupError) as exc:
        return _wa_error(exc, 404)
    except Exception as exc:
        return _wa_error(exc)


@app.route("/api/whatsapp/decrypt", methods=["POST"])
def whatsapp_decrypt():
    """La clave llega por POST, se usa y se descarta.

    **No se guarda en ningún sitio**: ni en la configuración, ni en un registro, ni
    vuelve al navegador. Flask no escribe los cuerpos de las peticiones en su log.
    """
    clave = (request.get_json(silent=True) or {}).get("key", "")
    try:
        resultado = wa_backup.descifra_todo(clave)
        # Los índices se crean aquí y no la primera vez que alguien abre los chats: son
        # ~45 s sobre una base de 600.000 mensajes, y pagarlos en mitad de una consulta
        # daría la sensación de que la aplicación se ha colgado.
        indices = wa_chats.prepara()
        return jsonify({"ok": True, "resultado": resultado, "indices": indices,
                        "resumen": wa_chats.resumen_chats()})
    except wa_backup.ClaveInvalida as exc:
        return jsonify({"error": str(exc), "bad_key": True}), 400
    except wa_backup.BackupError as exc:
        return _wa_error(exc)
    finally:
        del clave


# ------------------------------------------------------------ visor de conversaciones

@app.route("/api/whatsapp/chats")
def whatsapp_lista_chats():
    try:
        return jsonify(wa_chats.lista_chats(
            busca=request.args.get("q", ""),
            limit=int(request.args.get("limit", 200)),
            offset=int(request.args.get("offset", 0)),
        ))
    except wa_chats.SinBaseDeDatos as exc:
        return _wa_error(exc, 404)


@app.route("/api/whatsapp/chat/<int:chat_id>/mensajes")
def whatsapp_mensajes(chat_id):
    antes = request.args.get("antes_de", type=int)
    try:
        datos = wa_chats.mensajes(chat_id, antes_de=antes,
                                  limit=int(request.args.get("limit", 60)))
    except wa_chats.SinBaseDeDatos as exc:
        return _wa_error(exc, 404)

    # Se resuelve dónde está cada medio en el ordenador para que el navegador pueda
    # pedirlo. La base no lo sabe: solo guarda la ruta que tenía en el móvil.
    indice = wa_galeria.indice_local()
    for m in datos["mensajes"]:
        if m["medio"] and m["medio"]["nombre"]:
            local = indice.get(m["medio"]["nombre"])
            m["medio"]["local"] = local if local and Path(local).is_file() else None
    return jsonify(datos)


@app.route("/api/whatsapp/chat/<int:chat_id>/contexto")
def whatsapp_contexto(chat_id):
    """Salto desde una foto a su punto exacto de la conversación."""
    mensaje = request.args.get("mensaje", type=int)
    if not mensaje:
        return jsonify({"error": "Falta el mensaje al que saltar."}), 400
    try:
        datos = wa_chats.contexto(chat_id, mensaje,
                                  alrededor=int(request.args.get("alrededor", 25)))
    except wa_chats.SinBaseDeDatos as exc:
        return _wa_error(exc, 404)

    indice = wa_galeria.indice_local()
    for m in datos["mensajes"]:
        if m["medio"] and m["medio"]["nombre"]:
            local = indice.get(m["medio"]["nombre"])
            m["medio"]["local"] = local if local and Path(local).is_file() else None
    return jsonify(datos)


@app.route("/api/whatsapp/contactos")
def whatsapp_contactos():
    try:
        return jsonify(wa_chats.contactos(
            busca=request.args.get("q", ""),
            limit=int(request.args.get("limit", 200)),
            offset=int(request.args.get("offset", 0)),
            solo_con_mensajes=request.args.get("todos") != "1",
        ))
    except wa_chats.SinBaseDeDatos as exc:
        return _wa_error(exc, 404)


# ---------------------------------------------------------------- agenda externa

@app.route("/api/whatsapp/agenda")
def whatsapp_agenda():
    datos = wa_agenda.cargada()
    return jsonify({"origen": datos.get("origen"), "contactos": datos.get("contactos", 0),
                    "numeros": datos.get("numeros", 0),
                    "formato": datos.get("formato")})


@app.route("/api/whatsapp/agenda/elegir", methods=["POST"])
def whatsapp_agenda_elegir():
    """Abre el diálogo del sistema para elegir el fichero de contactos."""
    script = (
        'POSIX path of (choose file with prompt "Elige la agenda exportada (.vcf o .csv)" '
        'of type {"vcf", "vcard", "csv", "txt", "public.text", "public.vcard"})'
    )
    result = subprocess.run(["osascript", "-e", script], capture_output=True, text=True)
    if result.returncode != 0:
        return jsonify({"canceled": True})
    return jsonify({"path": result.stdout.strip()})


@app.route("/api/whatsapp/agenda/importar", methods=["POST"])
def whatsapp_agenda_importar():
    ruta = (request.get_json(silent=True) or {}).get("path", "")
    if not ruta:
        return jsonify({"error": "No se ha indicado ningún fichero."}), 400
    try:
        return jsonify(wa_agenda.importa(ruta))
    except (FileNotFoundError, ValueError) as exc:
        return _wa_error(exc)
    except Exception as exc:
        return jsonify({"error": f"No se pudo leer la agenda: {exc}"}), 400


@app.route("/api/whatsapp/agenda/olvidar", methods=["POST"])
def whatsapp_agenda_olvidar():
    return jsonify({"olvidada": wa_agenda.olvida()})


@app.route("/api/whatsapp/jids")
def whatsapp_jids():
    try:
        return jsonify(wa_chats.estadisticas_jid())
    except wa_chats.SinBaseDeDatos as exc:
        return _wa_error(exc, 404)


@app.route("/api/whatsapp/eliminados")
def whatsapp_eliminados():
    """Si de los mensajes borrados queda algo recuperable. Se comprueba, no se supone."""
    try:
        return jsonify(wa_chats.hay_texto_borrado())
    except wa_chats.SinBaseDeDatos as exc:
        return _wa_error(exc, 404)


# --------------------------------------------------------------------- galería

@app.route("/api/whatsapp/galeria/chats")
def whatsapp_galeria_chats():
    try:
        return jsonify(wa_galeria.chats_con_medios(
            solo_visuales=request.args.get("todos") != "1"))
    except wa_chats.SinBaseDeDatos as exc:
        return _wa_error(exc, 404)


@app.route("/api/whatsapp/galeria/chat/<int:chat_id>")
def whatsapp_galeria_chat(chat_id):
    try:
        return jsonify(wa_galeria.medios_de_chat(
            chat_id,
            solo_visuales=request.args.get("todos") != "1",
            solo_en_disco=request.args.get("en_disco") == "1",
            limit=int(request.args.get("limit", 300)),
            offset=int(request.args.get("offset", 0)),
        ))
    except wa_chats.SinBaseDeDatos as exc:
        return _wa_error(exc, 404)
    except ValueError as exc:
        return _wa_error(exc, 404)


@app.route("/api/whatsapp/galeria/donde")
def whatsapp_galeria_donde():
    """Búsqueda cruzada: en qué conversaciones aparece este fichero."""
    nombre = request.args.get("nombre", "")
    if not nombre:
        return jsonify({"error": "Falta el nombre del fichero."}), 400
    try:
        return jsonify(wa_galeria.donde_esta(nombre))
    except wa_chats.SinBaseDeDatos as exc:
        return _wa_error(exc, 404)


@app.route("/api/whatsapp/galeria/repetidos")
def whatsapp_galeria_repetidos():
    try:
        return jsonify(wa_galeria.repetidos(
            minimo=int(request.args.get("minimo", 2)),
            limit=int(request.args.get("limit", 200))))
    except wa_chats.SinBaseDeDatos as exc:
        return _wa_error(exc, 404)


@app.route("/api/whatsapp/galeria/borrar", methods=["POST"])
def whatsapp_galeria_borrar():
    rutas = (request.get_json(force=True) or {}).get("rutas") or []
    if not isinstance(rutas, list) or not rutas:
        return jsonify({"error": "No se ha indicado qué borrar."}), 400
    return jsonify(wa_galeria.borra([str(r) for r in rutas]))


@app.route("/api/whatsapp/miniatura")
def whatsapp_miniatura():
    """Versión pequeña de un medio, para las rejillas.

    Mismo control de contención que `/archivo`: la ruta llega del navegador y solo se
    admite dentro de la carpeta de destino. Si no se puede generar (un PDF, un audio) se
    responde 404 y el navegador enseña el icono del tipo, que es lo correcto.
    """
    destino = _wa_ruta_permitida(request.args.get("ruta", ""))
    try:
        return send_file(wa_miniaturas.miniatura(destino), conditional=True,
                         max_age=86400)
    except wa_miniaturas.SinMiniatura:
        abort(404)


def _wa_ruta_permitida(ruta: str) -> Path:
    """Resuelve una ruta pedida por el navegador y comprueba que cae dentro del destino.

    Sin esto bastaría pedir `?ruta=/etc/passwd` para leer cualquier fichero del equipo.
    Se compara la ruta **resuelta** —con enlaces simbólicos deshechos— para que un enlace
    colocado dentro del destino tampoco sirva de puente hacia fuera.
    """
    if not ruta:
        abort(404)
    raiz = Path(wa.config.load_config()["destination"]).expanduser().resolve()
    try:
        destino = Path(ruta).expanduser().resolve(strict=True)
    except OSError:
        abort(404)
    if not destino.is_relative_to(raiz) or not destino.is_file():
        abort(403)
    return destino


@app.route("/api/whatsapp/archivo")
def whatsapp_archivo():
    """Sirve un medio ya copiado al ordenador.

    **Solo dentro de la carpeta de destino.** La ruta llega desde el navegador, y sin
    esta comprobación bastaría pedir `?ruta=/etc/passwd` para leer cualquier fichero del
    equipo. Se compara la ruta *resuelta* (con enlaces simbólicos deshechos) para que un
    enlace dentro del destino tampoco sirva de puente hacia fuera.
    """
    return send_file(_wa_ruta_permitida(request.args.get("ruta", "")), conditional=True)


# --------------------------------------------------------- medios: escaneo y copia

def _wa_kinds(data: dict) -> list[str] | None:
    kinds = data.get("kinds")
    return list(kinds) if isinstance(kinds, list) else None


@app.route("/api/whatsapp/scan", methods=["POST"])
def whatsapp_scan():
    data = request.get_json(silent=True) or {}
    kinds = _wa_kinds(data)
    try:
        if data.get("path"):
            scan = wa_media.scan_folder(Path(data["path"]).expanduser(), kinds=kinds)
        else:
            scan = wa_media.scan_phone(kinds=kinds)
    except wa_media.WhatsAppNotFound as exc:
        return _wa_error(exc, 404)
    except Exception as exc:
        return jsonify({"error": f"No se pudo leer WhatsApp: {exc}"}), 400

    scan_id = uuid.uuid4().hex
    _wa_scans[scan_id] = scan
    for stale in list(_wa_scans)[:-_WA_MAX_SCANS]:
        _wa_scans.pop(stale, None)
    return jsonify({"scan_id": scan_id, "source": scan["source"], "origin": scan["origin"],
                    "kinds": scan["kinds"], "totals": scan["totals"]})


def _wa_plan(data: dict):
    scan = _wa_scans.get(data.get("scan_id", ""))
    if scan is None:
        return None, (jsonify({"error": "El escaneo ha caducado. Vuelve a buscar."}), 404)
    destino = data.get("destination") or wa.config.load_config()["destination"]
    plan = wa_media.build_plan(
        scan, destino, kinds=_wa_kinds(data),
        already_imported=wa.history.claves_copiadas(),
        skip_duplicates=bool(data.get("skip_duplicates", True)))
    return plan, None


@app.route("/api/whatsapp/plan", methods=["POST"])
def whatsapp_plan():
    plan, error = _wa_plan(request.get_json(force=True))
    if error:
        return error
    return jsonify({"destination": plan["destination"], "tree": plan["tree"],
                    "totals": plan["totals"], "free_bytes": free_space(plan["destination"])})


@app.route("/api/whatsapp/copy", methods=["POST"])
def whatsapp_copy():
    data = request.get_json(force=True)
    plan, error = _wa_plan(data)
    if error:
        return error
    if not plan["items"]:
        return jsonify({"error": "No hay nada que copiar con los tipos elegidos."}), 400
    # El aviso de espacio solo se da cuando el total es fiable. El inventario de WhatsApp
    # no pregunta el tamaño de cada fichero (serían decenas de miles de viajes por USB),
    # así que un total incompleto **no debe bloquear**: negarse a copiar por una cifra
    # que se sabe corta sería peor que dejar que empiece y falle por disco lleno.
    libre = free_space(plan["destination"])
    totales = plan["totals"]
    if (libre is not None and not totales.get("sin_tamano")
            and libre < totales["bytes"]):
        return jsonify({"error":
            f"No hay espacio suficiente: hacen falta {totales['bytes'] / 1e9:.1f} GB "
            f"y quedan {libre / 1e9:.1f} GB."}), 400
    wa.config.save_config({"destination": plan["destination"],
                           "kinds": _wa_kinds(data) or []})
    scan = _wa_scans.get(data.get("scan_id", ""), {})
    return jsonify({"job_id": wa_jobs.start_media(plan["items"], scan.get("source", "")),
                    "totals": plan["totals"]})


@app.route("/api/whatsapp/job/<job_id>")
def whatsapp_job(job_id):
    job = wa_jobs.get_job(job_id) or wa_sync.get_job(job_id)
    if not job:
        return jsonify({"error": "Trabajo no encontrado"}), 404
    return jsonify(job)


@app.route("/ubicacion")
def ubicacion_page():
    return render_template(
        "ubicacion.html",
        active="ubicacion",
        default_gap=DEFAULT_GAP_MINUTES,
        default_tolerance=DEFAULT_TOLERANCE_MINUTES,
        default_utc_offset=default_utc_offset(),
    )


@app.route("/api/ubicacion/groups", methods=["POST"])
def ubicacion_groups():
    data = request.get_json(force=True)
    root = Path(data.get("root") or load_config()["destination"]).expanduser()
    if not root.is_dir():
        return jsonify({"error": f"No es una carpeta válida: {root}"}), 400

    index = geoindex.load_index(root)
    groups = build_groups(index["files"], int(data.get("gap_minutes", DEFAULT_GAP_MINUTES)))
    return jsonify({
        "root": str(root),
        "indexed": bool(index["files"]),
        "stats": geoindex.stats(root),
        "groups": groups,
    })


@app.route("/api/ubicacion/reindex", methods=["POST"])
def ubicacion_reindex():
    data = request.get_json(force=True)
    root = Path(data.get("root") or load_config()["destination"]).expanduser()
    if not root.is_dir():
        return jsonify({"error": f"No es una carpeta válida: {root}"}), 400
    return jsonify({"job_id": start_reindex(str(root), full=bool(data.get("full")))})


@app.route("/api/ubicacion/match", methods=["POST"])
def ubicacion_match():
    data = request.get_json(force=True)
    root = Path(data.get("root") or load_config()["destination"]).expanduser()
    if not root.is_dir():
        return jsonify({"error": f"No es una carpeta válida: {root}"}), 400

    references = []
    used = []
    if data.get("use_index", True):
        found = references_from_index(root)
        references.extend(found)
        used.append(f"{len(found)} archivos ya importados con ubicación")

    folder = (data.get("reference_folder") or "").strip()
    if folder:
        try:
            found = references_from_folder(folder)
        except NotADirectoryError:
            return jsonify({"error": f"No es una carpeta válida: {folder}"}), 400
        references.extend(found)
        used.append(f"{len(found)} archivos con ubicación en {Path(folder).name}")

    gpx_path = (data.get("gpx_path") or "").strip()
    if gpx_path:
        try:
            points = load_gpx(gpx_path, data.get("utc_offset"))
        except GpxError as exc:
            return jsonify({"error": str(exc)}), 400
        references.extend(
            {"dt": p["dt"], "gps": p["gps"], "label": Path(gpx_path).name, "origin": "gpx"}
            for p in points
        )
        used.append(f"{len(points)} puntos del track {Path(gpx_path).name}")

    groups = build_groups(
        geoindex.load_index(root)["files"],
        int(data.get("gap_minutes", DEFAULT_GAP_MINUTES)),
    )
    groups = match_groups(
        groups, references, int(data.get("tolerance_minutes", DEFAULT_TOLERANCE_MINUTES))
    )
    return jsonify({
        "groups": groups,
        "references": len(references),
        "used": used,
        "matched": sum(1 for g in groups if g.get("suggestion")),
    })


@app.route("/api/ubicacion/assign", methods=["POST"])
def ubicacion_assign():
    data = request.get_json(force=True)
    root = Path(data.get("root") or "").expanduser()
    relatives = data.get("relatives", [])
    gps = data.get("gps")

    if not root.is_dir():
        return jsonify({"error": f"No es una carpeta válida: {root}"}), 400
    if not relatives or not gps or len(gps) != 2:
        return jsonify({"error": "Falta la selección de archivos o la posición."}), 400

    job_id = start_assign(
        str(root), relatives, [float(gps[0]), float(gps[1])],
        data.get("source", geoindex.SOURCE_MANUAL),
        data.get("place", ""),
        make_backup=bool(data.get("backup", True)),
    )
    return jsonify({"job_id": job_id, "total": len(relatives)})


@app.route("/api/ubicacion/assign-status/<job_id>")
def ubicacion_assign_status(job_id):
    job = get_assign_job(job_id)
    if not job:
        return jsonify({"error": "Trabajo no encontrado"}), 404
    return jsonify(job)


@app.route("/api/ubicacion/restore", methods=["POST"])
def ubicacion_restore():
    data = request.get_json(force=True)
    root = Path(data.get("root") or "").expanduser()
    relatives = data.get("relatives", [])
    if not root.is_dir() or not relatives:
        return jsonify({"error": "Falta la carpeta o la selección."}), 400

    restored = sum(1 for relative in relatives if restore_original(root / relative))
    if restored:
        geoindex.set_location(root, relatives, None, "", "")
    return jsonify({"restored": restored, "total": len(relatives)})


@app.route("/api/ubicacion/search")
def ubicacion_search():
    try:
        return jsonify({"results": search_places(request.args.get("q", ""))})
    except PlacesError as exc:
        return jsonify({"error": str(exc)}), 502


@app.route("/api/ubicacion/reverse")
def ubicacion_reverse():
    try:
        lat = float(request.args.get("lat", ""))
        lon = float(request.args.get("lon", ""))
    except ValueError:
        return jsonify({"error": "Coordenadas no válidas"}), 400
    return jsonify({"name": reverse_place(lat, lon)})


@app.route("/api/ubicacion/pick-gpx", methods=["POST"])
def ubicacion_pick_gpx():
    if platform.system() != "Darwin":
        return jsonify({"error": "El selector nativo de archivos solo está disponible en macOS."}), 400

    script = (
        'POSIX path of (choose file with prompt "Selecciona un track GPX" '
        'of type {"gpx", "xml"})'
    )
    result = subprocess.run(["osascript", "-e", script], capture_output=True, text=True)
    if result.returncode != 0:
        return jsonify({"canceled": True})
    return jsonify({"path": result.stdout.strip()})


if __name__ == "__main__":
    try:
        check_tools()
    except ToolsMissingError as exc:
        print(f"AVISO: {exc}")
    # 127.0.0.1 por defecto (solo accesible en local, sin autenticación de por medio).
    # Dentro de Docker hace falta 0.0.0.0 para que el puerto publicado sea alcanzable
    # desde fuera del contenedor — lo fija HOST en el Dockerfile/docker-compose.yml.
    app.run(host=os.environ.get("HOST", "127.0.0.1"), port=5050, debug=False)
