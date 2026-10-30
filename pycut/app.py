"""PyCut entry point: home screen <-> editor."""
from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtWidgets import QApplication, QMessageBox

from . import APP_NAME, ORG_NAME
from .core.model import Project
from .core.store import PROJECT_FILE, load_project
from .io.capcut import read_draft
from .ui import library
from .ui.editor_window import EditorWindow
from .ui.home import HomeWindow
from .ui.theme import app_font, stylesheet


class Controller:
    def __init__(self) -> None:
        self.home = HomeWindow()
        self.home.create.connect(self.new_project)
        self.home.open_entry.connect(self.open_entry)
        self.home.unavailable.connect(lambda t: QMessageBox.information(self.home, APP_NAME, t))
        self.editor: EditorWindow | None = None

    def show_home(self) -> None:
        if self.editor is not None:
            self.editor.session.dirty = False
            self.editor.close()
            self.editor = None
        self.home.show()
        self.home.raise_()

    def _open(self, project: Project, folder: str | None, dirty: bool = False) -> None:
        if self.editor is not None:
            self.editor.session.dirty = False
            self.editor.close()
        self.editor = EditorWindow(project, folder)
        self.editor.go_home.connect(self.show_home)
        self.editor.show()
        self.editor.timeline.canvas.fit()
        if folder is None and not dirty:
            self.editor.save()
        self.editor.session.dirty = dirty
        self.editor._retitle()
        self.home.hide()

    def new_project(self) -> None:
        self._open(Project.new(library.default_project_name()), None)

    def open_entry(self, e: library.Entry) -> None:
        try:
            if e.source == "pycut":
                self._open(load_project(e.path), e.path)
            else:
                p = read_draft(e.path)
                p.name = library.unique_name(p.name)
                p.path = ""
                self._open(p, None, dirty=True)
        except Exception as ex:
            QMessageBox.warning(self.home, APP_NAME, f"Impossible d'ouvrir ce projet :\n{ex}")

    def open_path(self, path: str) -> None:
        p = Path(path)
        if (p / PROJECT_FILE).is_file() or p.name == PROJECT_FILE:
            folder = str(p if p.is_dir() else p.parent)
            self._open(load_project(folder), folder)
        elif (p / "draft_content.json").is_file():
            proj = read_draft(p)
            proj.name = library.unique_name(proj.name)
            proj.path = ""
            self._open(proj, None, dirty=True)
        else:
            raise FileNotFoundError(path)


def main(argv: list[str] | None = None) -> int:
    argv = list(argv if argv is not None else sys.argv)
    app = QApplication(argv)
    app.setApplicationName(APP_NAME)
    app.setOrganizationName(ORG_NAME)
    app.setStyleSheet(stylesheet())
    app.setFont(app_font(12))
    ctl = Controller()
    if len(argv) > 1:
        try:
            ctl.open_path(argv[1])
        except Exception as ex:
            QMessageBox.warning(None, APP_NAME, f"Impossible d'ouvrir « {argv[1]} » :\n{ex}")
            ctl.show_home()
    else:
        ctl.show_home()
    return app.exec()
