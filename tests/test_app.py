import os
import shutil

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")
from PySide6.QtWidgets import QApplication  # noqa: E402

from pycut.io.capcut import RES  # noqa: E402


def test_controller_creates_and_reopens_projects(tmp_path, monkeypatch):
    monkeypatch.setenv("PYCUT_HOME", str(tmp_path / "proj"))
    monkeypatch.setenv("PYCUT_CAPCUT_ROOT", str(tmp_path / "nocapcut"))
    app = QApplication.instance() or QApplication([])
    from pycut.app import Controller
    from pycut.ui import library
    c = Controller()
    c.new_project()
    assert c.editor is not None and c.home.isHidden()
    folder = c.editor.project_dir
    assert (tmp_path / "proj").exists() and folder
    c.show_home()
    names = [e.name for e in library.list_pycut()]
    assert len(names) == 1
    c.open_entry(library.list_pycut()[0])
    assert c.editor.project_dir == folder
    c.editor.session.dirty = False
    c.editor.close()


def test_open_capcut_draft_from_path(tmp_path, monkeypatch):
    monkeypatch.setenv("PYCUT_HOME", str(tmp_path / "proj"))
    app = QApplication.instance() or QApplication([])
    from pycut.app import Controller
    d = tmp_path / "draft"
    d.mkdir()
    shutil.copy(RES / "capcut_minimal_draft_content.json", d / "draft_content.json")
    c = Controller()
    c.open_path(str(d))
    assert [t.kind.value for t in c.editor.editor.project.tracks] == ["video", "text"]
    assert c.editor.session.dirty                      # imported, not saved yet
    c.editor.session.dirty = False
    c.editor.close()
