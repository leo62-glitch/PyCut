"""Native project persistence: ``<project>/project.pycut.json`` (atomic writes + backup)."""
from __future__ import annotations

import json
import os
import shutil
from pathlib import Path

from .model import Project, project_from_dict, project_to_dict

PROJECT_FILE = "project.pycut.json"


def save_project(project: Project, folder: str | os.PathLike | None = None) -> Path:
    folder = Path(folder or project.path)
    if not str(folder):
        raise ValueError("project has no folder")
    folder.mkdir(parents=True, exist_ok=True)
    project.path = str(folder)
    target = folder / PROJECT_FILE
    tmp = folder / (PROJECT_FILE + ".tmp")
    tmp.write_text(json.dumps(project_to_dict(project), ensure_ascii=False, indent=1), encoding="utf-8")
    if target.exists():
        shutil.copy2(target, folder / (PROJECT_FILE + ".bak"))
    os.replace(tmp, target)
    return target


def load_project(folder: str | os.PathLike) -> Project:
    folder = Path(folder)
    f = folder / PROJECT_FILE if folder.is_dir() else folder
    try:
        data = json.loads(f.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        bak = f.with_name(f.name + ".bak")
        if not bak.exists():
            raise
        data = json.loads(bak.read_text(encoding="utf-8"))
    p = project_from_dict(data)
    p.path = str(f.parent)
    return p
