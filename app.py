"""Interfaz web para convertir clips AVCHD (.MTS) a MP4 sin recompresión de vídeo,
y renombrar vídeos/fotos con su fecha y hora de captura."""

import platform
import subprocess
from pathlib import Path

from flask import Flask, jsonify, render_template, request

from converter.ffmpeg_ops import ToolsMissingError, check_tools
from converter.jobs import get_job, start_job
from converter.scanner import scan_folder
from converter.stabilize import VidstabMissingError, find_ffmpeg_with_vidstab
from converter.stabilize_jobs import get_job as get_stabilize_job, start_job as start_stabilize_job

app = Flask(__name__)


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

    job_id = start_stabilize_job(root, avchd_paths, force, fast_hw)
    return jsonify({"job_id": job_id})


@app.route("/api/stabilize-status/<job_id>")
def stabilize_status(job_id):
    job = get_stabilize_job(job_id)
    if not job:
        return jsonify({"error": "Trabajo no encontrado"}), 404
    return jsonify(job)


if __name__ == "__main__":
    try:
        check_tools()
    except ToolsMissingError as exc:
        print(f"AVISO: {exc}")
    app.run(host="127.0.0.1", port=5050, debug=False)
