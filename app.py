"""Interfaz web para convertir clips AVCHD (.MTS) a MP4 sin recompresión de vídeo,
y renombrar vídeos/fotos con su fecha y hora de captura."""

import platform
import subprocess
from pathlib import Path

from flask import Flask, abort, jsonify, render_template, request, send_file

from converter.ffmpeg_ops import ToolsMissingError, check_tools
from converter.fonts import list_system_fonts
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
    find_ffmpeg_with_vidstab,
)
from converter.stabilize_jobs import get_job as get_stabilize_job, start_job as start_stabilize_job
from converter.thumbnails import get_or_create_thumbnail
from converter.timeline_jobs import get_export_job, start_export

app = Flask(__name__)

_MEDIA_EXTS = {".mp4", ".mov", ".jpg", ".jpeg", ".png", ".gif"}


@app.route("/")
def index():
    return render_template("index.html", home=str(Path.home()))


@app.route("/api/browse")
def browse():
    raw_path = request.args.get("path") or str(Path.home())
    path = Path(raw_path).expanduser()

    if not path.is_dir():
        return jsonify({"error": f"No es una carpeta: {path}"}), 400

    try:
        entries = sorted(
            (p for p in path.iterdir() if p.is_dir() and not p.name.startswith(".")),
            key=lambda p: p.name.lower(),
        )
    except PermissionError:
        return jsonify({"error": f"Sin permiso para leer: {path}"}), 403

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

    if not root or (not avchd_paths and not photo_paths):
        return jsonify({"error": "Nada que convertir"}), 400

    job_id = start_job(root, avchd_paths, photo_paths, transcode_audio, force)
    return jsonify({"job_id": job_id})


@app.route("/api/status/<job_id>")
def status(job_id):
    job = get_job(job_id)
    if not job:
        return jsonify({"error": "Trabajo no encontrado"}), 404
    return jsonify(job)


def _clamp(value, lo, hi):
    return max(lo, min(hi, value))


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

    zoom_mode = data.get("zoom_mode", ZOOM_AUTO_STATIC)
    if zoom_mode not in (ZOOM_AUTO_STATIC, ZOOM_AUTO_DYNAMIC, ZOOM_MANUAL):
        zoom_mode = ZOOM_AUTO_STATIC
    params = {
        "shakiness": int(_clamp(int(data.get("shakiness", 5)), 1, 10)),
        "accuracy": int(_clamp(int(data.get("accuracy", 15)), 1, 15)),
        "smoothing": int(_clamp(int(data.get("smoothing", 10)), 0, 100)),
        "zoom_mode": zoom_mode,
        "zoom_percent": _clamp(float(data.get("zoom_percent", 0.0)), -50.0, 50.0),
    }

    job_id = start_stabilize_job(root, avchd_paths, force, fast_hw, params)
    return jsonify({"job_id": job_id})


@app.route("/api/stabilize-status/<job_id>")
def stabilize_status(job_id):
    job = get_stabilize_job(job_id)
    if not job:
        return jsonify({"error": "Trabajo no encontrado"}), 404
    return jsonify(job)


@app.route("/montaje")
def montaje_page():
    return render_template("montaje.html", home=str(Path.home()))


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


if __name__ == "__main__":
    try:
        check_tools()
    except ToolsMissingError as exc:
        print(f"AVISO: {exc}")
    app.run(host="127.0.0.1", port=5050, debug=False)
