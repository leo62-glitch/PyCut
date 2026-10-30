"""Where projects live and how to list them (PyCut projects + CapCut drafts)."""
from __future__ import annotations

import json
import os
import shutil
import time
from dataclasses import dataclass
from pathlib import Path

from ..core.store import PROJECT_FILE


@dataclass
class Entry:
    name: str
    path: str
    cover: str = ""
    duration_us: int = 0
    size_bytes: int = 0
    modified: float = 0.0
    source: str = "pycut"        # "pycut" | "capcut"


def projects_dir() -> Path:
    base = os.environ.get("PYCUT_HOME")
    d = Path(base) if base else Path.home() / "Documents" / "PyCut" / "Projects"
    d.mkdir(parents=True, exist_ok=True)
    return d


def capcut_root() -> Path:
    env = os.environ.get("PYCUT_CAPCUT_ROOT")
    if env:
        return Path(env)
    la = os.environ.get("LOCALAPPDATA")
    if la:
        return Path(la) / "CapCut" / "User Data" / "Projects" / "com.lveditor.draft"
    return Path.home() / "CapCut" / "User Data" / "Projects" / "com.lveditor.draft"


def unique_name(base: str, root: Path | None = None) -> str:
    root = root or projects_dir()
    name, n = base, 1
    while (root / name).exists():
        name = f"{base} ({n})"
        n += 1
    return name


def default_project_name() -> str:
    return unique_name(time.strftime("%m%d"))


def list_pycut() -> list[Entry]:
    out = []
    for d in projects_dir().iterdir():
        f = d / PROJECT_FILE
        if not f.is_file():
            continue
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        dur = 0
        for tr in data.get("tracks", []):
            for s in tr.get("segments", []):
                t = s.get("target", {})
                dur = max(dur, t.get("start", 0) + t.get("duration", 0))
        size = sum(m.get("size_bytes", 0) for m in data.get("materials", {}).values()) \
            if isinstance(data.get("materials"), dict) else 0
        cover = d / "cover.jpg"
        out.append(Entry(d.name, str(d), str(cover) if cover.exists() else "", dur, size, f.stat().st_mtime, "pycut"))
    return out


def list_capcut() -> list[Entry]:
    root = capcut_root()
    idx = root / "root_meta_info.json"
    out = []
    try:
        store = json.loads(idx.read_text(encoding="utf-8")).get("all_draft_store", [])
    except (OSError, ValueError):
        store = []
    for it in store:
        folder = Path(it.get("draft_fold_path", ""))
        if not (folder / "draft_content.json").is_file():
            continue
        cover = it.get("draft_cover") or ""
        if not Path(cover).is_file():
            cover = str(folder / "draft_cover.jpg")
        out.append(Entry(it.get("draft_name", folder.name), str(folder), cover if Path(cover).is_file() else "",
                         it.get("tm_duration", 0), it.get("draft_timeline_materials_size", 0),
                         it.get("tm_draft_modified", 0) / 1_000_000, "capcut"))
    return out


def list_all() -> list[Entry]:
    return sorted(list_pycut() + list_capcut(), key=lambda e: e.modified, reverse=True)


def delete_project(path: str) -> None:
    shutil.rmtree(path, ignore_errors=True)


def human_size(n: int) -> str:
    if n <= 0:
        return "0.0B"
    for unit, div in (("G", 1 << 30), ("M", 1 << 20), ("K", 1 << 10)):
        if n >= div:
            return f"{n / div:.1f}{unit}"
    return f"{n}B"
