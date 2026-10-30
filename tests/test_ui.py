"""Headless UI tests (Qt offscreen): real mouse/keyboard events on the timeline and inspector."""
import os
import sys

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")
cv2 = pytest.importorskip("cv2")
import numpy as np  # noqa: E402
from PySide6.QtCore import QPoint, QPointF, Qt  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from pycut.core.timebase import US  # noqa: E402


@pytest.fixture(scope="module")
def app():
    a = QApplication.instance() or QApplication([])
    from pycut.ui.theme import stylesheet
    a.setStyleSheet(stylesheet())
    return a


@pytest.fixture()
def win(app, tmp_path, monkeypatch):
    monkeypatch.setenv("PYCUT_HOME", str(tmp_path / "proj"))
    from pycut.ui.editor_window import EditorWindow
    from pycut.ui.media_panel import import_files
    paths = []
    for name, col in (("a", (120, 70, 30)), ("b", (40, 110, 60))):
        p = str(tmp_path / f"{name}.mp4")
        w = cv2.VideoWriter(p, cv2.VideoWriter_fourcc(*"mp4v"), 30, (320, 180))
        for i in range(90):
            f = np.zeros((180, 320, 3), np.uint8)
            f[:] = col
            w.write(f)
        w.release()
        paths.append(p)
    win = EditorWindow()
    win.resize(1400, 820)
    win.show()
    app.processEvents()
    import_files(win.session, paths)
    win.ids = list(win.editor.project.materials)
    yield win
    win.session.dirty = False
    win.close()


def press_drag(canvas, a: QPointF, b: QPointF, steps=6):
    QTest.mousePress(canvas, Qt.LeftButton, Qt.NoModifier, a.toPoint())
    for i in range(1, steps + 1):
        p = a + (b - a) * (i / steps)
        QTest.mouseMove(canvas, p.toPoint())
    QTest.mouseRelease(canvas, Qt.LeftButton, Qt.NoModifier, b.toPoint())


def test_click_selects_and_ruler_seeks(win, app):
    ed, s, cv = win.editor, win.session, win.timeline.canvas
    seg = ed.add_segment(win.ids[0])
    cv.fit()
    app.processEvents()
    tr, ry, h = cv.layout_rows()[0]
    r = cv.seg_rect(tr, ry, h, seg)
    QTest.mouseClick(cv, Qt.LeftButton, Qt.NoModifier, QPoint(int(r.center().x()), int(r.center().y())))
    assert s.selection == [seg.id]
    QTest.mouseClick(cv, Qt.LeftButton, Qt.NoModifier, QPoint(int(cv.t2x(US)), 10))
    assert abs(s.playhead - US) < US // 20


def test_trim_by_dragging_right_edge(win, app):
    ed, cv = win.editor, win.timeline.canvas
    seg = ed.add_segment(win.ids[0])          # 3 s clip
    cv.fit()
    app.processEvents()
    tr, ry, h = cv.layout_rows()[0]
    r = cv.seg_rect(tr, ry, h, seg)
    y = r.center().y()
    press_drag(cv, QPointF(r.right() - 2, y), QPointF(cv.t2x(2 * US), y))
    assert abs(seg.duration - 2 * US) < US // 10
    assert seg.source.duration == seg.duration
    ed.undo()
    assert abs(ed.project.main_track().segments[0].duration - 3 * US) < 2


def test_reorder_on_main_track_by_dragging(win, app):
    ed, cv = win.editor, win.timeline.canvas
    a = ed.add_segment(win.ids[0])
    b = ed.add_segment(win.ids[1])
    cv.fit()
    app.processEvents()
    tr, ry, h = cv.layout_rows()[0]
    rb = cv.seg_rect(tr, ry, h, b)
    y = rb.center().y()
    press_drag(cv, QPointF(rb.center().x(), y), QPointF(cv.t2x(0.2 * US), y))
    ids = [s.id for s in ed.project.main_track().segments]
    assert ids == [b.id, a.id]


def test_keyboard_split_delete_undo(win, app):
    ed, s = win.editor, win.session
    seg = ed.add_segment(win.ids[0])
    s.select([seg.id])
    s.set_playhead(US)
    QTest.keyClick(win, Qt.Key_B, Qt.ControlModifier)
    assert len(ed.project.main_track().segments) == 2
    QTest.keyClick(win, Qt.Key_Z, Qt.ControlModifier)
    assert len(ed.project.main_track().segments) == 1
    QTest.keyClick(win, Qt.Key_Right)
    assert s.playhead == US + int(US / 30)


def test_playback_advances_and_stops(win, app):
    s = win.session
    win.editor.add_segment(win.ids[0])
    s.play()
    assert s.playing
    QTest.qWait(250)
    assert s.playhead > 0
    s.pause()
    assert not s.playing


def test_inspector_slider_merges_undo_and_updates_model(win, app):
    ed, s = win.editor, win.session
    seg = ed.add_segment(win.ids[0])
    s.select([seg.id])
    app.processEvents()
    row = win.inspector.clip._rows["scale"]
    undo_before = len(ed.project.tracks) and len(ed._undo)
    for v in (110, 120, 130, 150):
        row.sp.setValue(v)
    assert abs(ed.project.main_track().segments[0].transform.scale_x - 1.5) < 1e-6
    assert len(ed._undo) == undo_before + 1       # one undo step for the whole drag
    ed.undo()
    assert ed.project.main_track().segments[0].transform.scale_x == 1.0


def test_drop_external_media_creates_overlay(win, app):
    from pycut.ui.timeline import MIME_MATERIAL
    from PySide6.QtCore import QMimeData
    ed, cv = win.editor, win.timeline.canvas
    ed.add_segment(win.ids[0])
    cv.fit()
    app.processEvents()
    md = QMimeData()
    md.setData(MIME_MATERIAL, win.ids[1].encode())
    from PySide6.QtGui import QDropEvent
    ev = QDropEvent(QPointF(cv.t2x(US), 40), Qt.CopyAction, md, Qt.LeftButton, Qt.NoModifier)
    cv.dropEvent(ev)
    kinds = [(t.kind.value, t.is_main, len(t.segments)) for t in ed.project.tracks]
    assert ("video", False, 1) in kinds


def test_save_and_reopen(win, app, tmp_path):
    ed = win.editor
    ed.add_segment(win.ids[0])
    assert win.save()
    from pycut.core.store import load_project
    p = load_project(win.project_dir)
    assert p.duration == ed.project.duration
    assert (tmp_path / "proj").exists()
