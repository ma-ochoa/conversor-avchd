"""Guardado y carga de proyectos de montaje (timeline, recortes, títulos, transición)."""

import json
import re
import uuid
from pathlib import Path

from .config import resolve_output_base

PROJECTS_DIR_NAME = "montaje/proyectos"
EXPORTS_DIR_NAME = "montaje"

_SAFE_NAME_RE = re.compile(r"[^A-Za-z0-9 _\-áéíóúÁÉÍÓÚñÑ]")


def _projects_dir(root: Path) -> Path:
    return resolve_output_base(root) / PROJECTS_DIR_NAME


def exports_dir(root: Path) -> Path:
    return resolve_output_base(root) / EXPORTS_DIR_NAME


def sanitize_project_name(name: str) -> str:
    name = _SAFE_NAME_RE.sub("", name).strip()
    return name or "proyecto"


def list_projects(root: Path) -> list[str]:
    directory = _projects_dir(root)
    if not directory.is_dir():
        return []
    return sorted(p.stem for p in directory.glob("*.json"))


def project_path(root: Path, name: str) -> Path:
    return _projects_dir(root) / f"{sanitize_project_name(name)}.json"


def new_project(root: str) -> dict:
    return {
        "version": 1,
        "root": root,
        "transition_seconds": 2.0,
        "clips": [],
    }


def new_clip_entry(path: str, in_point: float, out_point: float) -> dict:
    return {
        "id": uuid.uuid4().hex[:12],
        "path": path,
        "in": round(in_point, 3),
        "out": round(out_point, 3),
        "title": None,
    }


def save_project(root: Path, name: str, project: dict) -> Path:
    path = project_path(root, name)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(project, f, indent=2, ensure_ascii=False)
    return path


def load_project(root: Path, name: str) -> dict:
    path = project_path(root, name)
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)
