import pytest
from pycut.core.editor import Editor, EditError
from pycut.core.model import Material, MaterialKind, TrackKind, Project
from pycut.core.store import save_project, load_project
from pycut.core.timebase import US


def vid(ed, name="a", dur=10 * US):
    return ed.import_material(Material(kind=MaterialKind.VIDEO, name=name, duration=dur, width=1920, height=1080, fps=30))


def test_magnetic_main_track_and_undo():
    ed = Editor()
    a, b = vid(ed, "a"), vid(ed, "b", 5 * US)
    s1 = ed.add_segment(a.id)
    s2 = ed.add_segment(b.id)
    assert (s1.start, s2.start, ed.project.duration) == (0, 10 * US, 15 * US)
    ed.delete([s1.id])
    assert ed.project.main_track().segments[0].start == 0      # gap closed
    ed.undo()
    assert len(ed.project.main_track().segments) == 2
    ed.redo()
    assert len(ed.project.main_track().segments) == 1


def test_split_preserves_source_continuity():
    ed = Editor()
    s = ed.add_segment(vid(ed).id)
    left, right = ed.split(s.id, 4 * US)
    assert left.duration == 4 * US and right.duration == 6 * US
    assert right.source.start == 4 * US and left.source.end == 4 * US
    assert right.start == 4 * US


def test_split_too_close_rolls_back():
    ed = Editor()
    s = ed.add_segment(vid(ed).id)
    with pytest.raises(EditError):
        ed.split(s.id, 1000)
    assert len(ed.project.main_track().segments) == 1


def test_trim_and_speed():
    ed = Editor()
    s = ed.add_segment(vid(ed).id)
    ed.trim(s.id, end=6 * US)
    assert s.duration == 6 * US and s.source.duration == 6 * US
    ed.set_speed(s.id, 2.0)
    assert s.duration == 3 * US
    with pytest.raises(EditError):
        ed.set_speed(s.id, 0.01)


def test_overlay_goes_to_new_track_and_no_overlap():
    ed = Editor()
    a = vid(ed)
    ed.add_segment(a.id)
    t1 = ed.add_text("hi", 1 * US, 3 * US)
    t2 = ed.add_text("yo", 2 * US, 3 * US)   # overlaps → second text track
    kinds = [t.kind for t in ed.project.tracks]
    assert kinds.count(TrackKind.TEXT) == 2


def test_freeze_and_keyframes():
    ed = Editor()
    s = ed.add_segment(vid(ed).id)
    ed.set_keyframe(s.id, "KFTypePositionX", 0, 0.0)
    ed.set_keyframe(s.id, "KFTypePositionX", 2 * US, 1.0)
    assert s.animated_value("KFTypePositionX", 1 * US, 0) == pytest.approx(0.5)
    f = ed.freeze_frame(s.id, 5 * US, 2 * US)
    assert f.freeze and f.duration == 2 * US
    assert ed.project.duration == 12 * US


def test_save_load_roundtrip(tmp_path):
    ed = Editor()
    s = ed.add_segment(vid(ed).id)
    ed.split(s.id, 3 * US)
    ed.add_text("héllo")
    save_project(ed.project, tmp_path)
    p = load_project(tmp_path)
    assert p.duration == ed.project.duration
    assert [len(t.segments) for t in p.tracks] == [len(t.segments) for t in ed.project.tracks]


def test_reorder_on_main_track():
    ed = Editor()
    a = ed.add_segment(vid(ed, "a", 4 * US).id)
    b = ed.add_segment(vid(ed, "b", 2 * US).id)
    ed.move(b.id, 0)
    assert [s.id for s in ed.project.main_track().segments] == [b.id, a.id]
    assert (b.start, a.start) == (0, 2 * US)
