import json
from pathlib import Path

import pytest

from pycut.core.editor import Editor
from pycut.core.model import Material, MaterialKind, TrackKind
from pycut.core.timebase import US
from pycut.io.capcut import RES, export_draft, read_draft

TEMPLATE = RES / "capcut_minimal_draft_content.json"


def check_integrity(doc):
    """Every reference CapCut follows must resolve; every material group must exist."""
    tpl = json.loads(TEMPLATE.read_text(encoding="utf-8"))
    assert set(tpl["materials"]) <= set(doc["materials"])
    ids = {o["id"] for lst in doc["materials"].values() for o in lst}
    assert len(ids) == sum(len(l) for l in doc["materials"].values()), "duplicate material ids"
    seg_ids = set()
    for tr in doc["tracks"]:
        for s in tr["segments"]:
            assert s["id"] not in seg_ids
            seg_ids.add(s["id"])
            assert s["material_id"] in ids
            assert all(r in ids for r in s["extra_material_refs"])
            assert set(s) >= {"id", "material_id", "target_timerange", "clip", "common_keyframes", "speed"}
    end = max((s["target_timerange"]["start"] + s["target_timerange"]["duration"]
               for tr in doc["tracks"] for s in tr["segments"]), default=0)
    assert doc["duration"] == end


def build():
    ed = Editor()
    v = ed.import_material(Material(kind=MaterialKind.VIDEO, name="a.mp4", path="C:\\m\\a.mp4",
                                    duration=10 * US, width=1920, height=1080, has_audio=True))
    a = ed.import_material(Material(kind=MaterialKind.AUDIO, name="m.mp3", path="C:\\m\\m.mp3", duration=20 * US))
    ph = ed.import_material(Material(kind=MaterialKind.PHOTO, name="p.png", path="C:\\m\\p.png", width=800, height=600))
    s1 = ed.add_segment(v.id)
    ed.split(s1.id, 4 * US)
    ed.add_segment(ph.id)
    seg = ed.add_segment(a.id, start=0)
    seg.audio.fade_out = 1 * US
    t = ed.add_text("Héllo \"monde\"", 1 * US, 2 * US)
    t.text.color = "#FF8800"
    t.transform.y = -0.7
    ed.set_keyframe(s1.id, "KFTypePositionX", 0, 0.0)
    ed.set_keyframe(s1.id, "KFTypePositionX", 2 * US, 0.5)
    return ed


def test_template_itself_is_importable(tmp_path):
    (tmp_path / "draft_content.json").write_text(TEMPLATE.read_text(encoding="utf-8"), encoding="utf-8")
    p = read_draft(tmp_path)
    kinds = [t.kind for t in p.tracks]
    assert kinds == [TrackKind.VIDEO, TrackKind.TEXT]
    text = p.tracks[1].segments[0]
    assert text.text.text == "Bonjour" and text.transform.y == pytest.approx(-0.7)
    assert p.tracks[0].is_main and p.duration == 5 * US


def test_export_is_self_consistent(tmp_path):
    ed = build()
    folder, warns = export_draft(ed.project, tmp_path, "Test")
    doc = json.loads((folder / "draft_content.json").read_text(encoding="utf-8"))
    check_integrity(doc)
    meta = json.loads((folder / "draft_meta_info.json").read_text(encoding="utf-8"))
    assert meta["draft_id"] == doc["id"] and meta["tm_duration"] == doc["duration"]
    assert len(meta["draft_materials"]) == 7 and len(meta["draft_materials"][0]["value"]) == 3
    photo = next(m for m in doc["materials"]["videos"] if m["type"] == "photo")
    assert photo["duration"] == 10_800_000_000
    seg_ref_groups = {r for tr in doc["tracks"] for s in tr["segments"] for r in s["extra_material_refs"]}
    assert doc["materials"]["audio_fades"] and doc["materials"]["beats"]
    audio_seg = next(s for tr in doc["tracks"] if tr["type"] == "audio" for s in tr["segments"])
    assert audio_seg["clip"] is None and audio_seg["source_timerange"]["duration"] == 20 * US
    root = json.loads((tmp_path / "root_meta_info.json").read_text(encoding="utf-8"))
    assert root["draft_ids"] == 1 and root["all_draft_store"][0]["draft_id"] == doc["id"]
    assert not warns


def test_round_trip(tmp_path):
    ed = build()
    folder, _ = export_draft(ed.project, tmp_path, "RT")
    p2 = read_draft(folder)
    p1 = ed.project
    assert p2.duration == p1.duration and p2.fps == p1.fps
    assert [t.kind for t in p2.tracks] == [t.kind for t in p1.tracks]
    for t1, t2 in zip(p1.tracks, p2.tracks):
        assert [(s.start, s.duration) for s in t1.segments] == [(s.start, s.duration) for s in t2.segments]
    txt = next(s for _, s in p2.iter_segments() if s.text)
    assert txt.text.text == 'Héllo "monde"' and txt.text.color == "#FF8800"
    vid = p2.tracks[0].segments[0]
    assert vid.keyframes[0].property == "KFTypePositionX" and len(vid.keyframes[0].keyframes) == 2
    aud = next(s for tr in p2.tracks if tr.kind == TrackKind.AUDIO for s in tr.segments)
    assert aud.audio.fade_out == 1 * US
    # second export of the imported project stays valid
    folder2, _ = export_draft(p2, tmp_path, "RT2")
    check_integrity(json.loads((folder2 / "draft_content.json").read_text(encoding="utf-8")))


def test_unsupported_features_are_reported_not_faked(tmp_path):
    ed = build()
    s = ed.project.main_track().segments[0]
    ed.set_transition(s.id, "dissolve")
    _, warns = export_draft(ed.project, tmp_path, "W")
    assert any("Transition" in w for w in warns)


def test_existing_foreign_folder_is_never_overwritten(tmp_path):
    (tmp_path / "Mine").mkdir()
    (tmp_path / "Mine" / "draft_content.json").write_text("{}")
    folder, _ = export_draft(build().project, tmp_path, "Mine")
    assert folder.name == "Mine (1)"
    assert (tmp_path / "Mine" / "draft_content.json").read_text() == "{}"
