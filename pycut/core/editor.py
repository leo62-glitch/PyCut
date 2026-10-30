"""Editing operations with snapshot-based undo/redo.

``Editor`` is the only place that mutates a ``Project`` in response to user
actions. Every public mutating method is wrapped in ``_edit`` which stores a
snapshot *before* the change, so undo/redo is a simple stack swap. The class is
Qt-free: the UI subscribes with ``editor.subscribe(callback)``.

The main video track is *magnetic* like in CapCut: segments are packed
end-to-end, with no gaps, after every operation that touches it.
"""
from __future__ import annotations

import copy
import time
from contextlib import contextmanager
from typing import Callable, Iterable

from .model import (
    DEFAULT_TRACK_FOR_MATERIAL, Marker, Material, MaterialKind, Project, Segment,
    TimeRange, Track, TrackKind, Transition, project_from_dict, project_to_dict,
    new_text_segment,
)
from .timebase import snap_to_frame, US

MIN_SEGMENT_US = 33_333  # one frame at 30 fps
MAX_HISTORY = 200


class EditError(Exception):
    """Raised when an operation is impossible (the project is left untouched)."""


class Editor:
    def __init__(self, project: Project | None = None) -> None:
        self.project = project or Project.new()
        self._undo: list[dict] = []
        self._redo: list[dict] = []
        self._listeners: list[Callable[[str], None]] = []
        self._depth = 0
        self.clipboard: list[Segment] = []
        self._merge: tuple | None = None
        self._merge_t = 0.0

    # ------------------------------------------------------------------ infra
    def subscribe(self, cb: Callable[[str], None]) -> None:
        self._listeners.append(cb)

    def _notify(self, what: str) -> None:
        for cb in list(self._listeners):
            cb(what)

    @contextmanager
    def _edit(self, label: str, merge: tuple | None = None):
        """Group nested operations into one undo step; roll back on error.

        ``merge``: consecutive edits with the same key within one second share one undo step
        (used for sliders so that dragging does not flood the history)."""
        outer = self._depth == 0
        snap = project_to_dict(self.project) if outer else None
        self._depth += 1
        try:
            yield
        except Exception:
            self._depth -= 1
            if outer:
                self.project = project_from_dict(snap)
            raise
        self._depth -= 1
        if outer:
            now = time.monotonic()
            if merge is not None and merge == self._merge and now - self._merge_t < 1.0 and self._undo:
                pass    # keep the snapshot taken at the start of the gesture
            else:
                self._undo.append(snap)
                del self._undo[:-MAX_HISTORY]
            self._merge, self._merge_t = merge, now
            self._redo.clear()
            self._normalize()
            self.project.touch()
            self._notify(label)

    def set_project(self, project: Project) -> None:
        self.project = project
        self._undo.clear()
        self._redo.clear()
        self._notify("load")

    @property
    def can_undo(self) -> bool:
        return bool(self._undo)

    @property
    def can_redo(self) -> bool:
        return bool(self._redo)

    def undo(self) -> bool:
        if not self._undo:
            return False
        self._redo.append(project_to_dict(self.project))
        self.project = project_from_dict(self._undo.pop())
        self._notify("undo")
        return True

    def redo(self) -> bool:
        if not self._redo:
            return False
        self._undo.append(project_to_dict(self.project))
        self.project = project_from_dict(self._redo.pop())
        self._notify("redo")
        return True

    def _normalize(self) -> None:
        """Keep tracks sorted, close gaps on the magnetic main track."""
        for tr in self.project.tracks:
            tr.sort()
        main = self.project.main_track()
        if main is not None:
            t = 0
            for s in main.segments:
                s.target.start = t
                t += s.target.duration

    def _seg(self, sid: str) -> tuple[Track, Segment]:
        found = self.project.find_segment(sid)
        if found is None:
            raise EditError(f"segment {sid} not found")
        return found

    def _snap(self, t: int) -> int:
        return max(0, snap_to_frame(int(t), self.project.fps))

    # --------------------------------------------------------------- materials
    def import_material(self, mat: Material) -> Material:
        with self._edit("import"):
            return self.project.add_material(mat)

    def remove_material(self, mid: str) -> None:
        with self._edit("remove_material"):
            for tr in self.project.tracks:
                tr.segments = [s for s in tr.segments if s.material_id != mid]
            self.project.materials.pop(mid, None)
            self.project.remove_empty_tracks()

    # ------------------------------------------------------------------ tracks
    def add_track(self, kind: TrackKind, index: int | None = None) -> Track:
        with self._edit("add_track"):
            return self.project.add_track(kind, index)

    def remove_track(self, tid: str) -> None:
        with self._edit("remove_track"):
            tr = self.project.track_by_id(tid)
            if tr is None or tr.is_main:
                raise EditError("cannot remove this track")
            self.project.tracks.remove(tr)

    def move_track(self, tid: str, new_index: int) -> None:
        with self._edit("move_track"):
            tr = self.project.track_by_id(tid)
            if tr is None:
                raise EditError("track not found")
            self.project.tracks.remove(tr)
            self.project.tracks.insert(max(0, min(new_index, len(self.project.tracks))), tr)

    def set_track_flags(self, tid: str, *, muted: bool | None = None, locked: bool | None = None,
                        hidden: bool | None = None) -> None:
        with self._edit("track_flags"):
            tr = self.project.track_by_id(tid)
            if tr is None:
                raise EditError("track not found")
            for name, val in (("muted", muted), ("locked", locked), ("hidden", hidden)):
                if val is not None:
                    setattr(tr, name, val)

    def _free_track_for(self, kind: TrackKind, start: int, duration: int,
                        ignore: set[str] | None = None) -> Track:
        for tr in self.project.tracks:
            if tr.kind == kind and not tr.is_main and not tr.locked \
                    and tr.free_space(start, duration, ignore):
                return tr
        # overlays stack above, audio goes below the existing tracks
        idx = len(self.project.tracks) if kind == TrackKind.AUDIO else None
        return self.project.add_track(kind, idx)

    # ---------------------------------------------------------------- segments
    def add_segment(self, material_id: str, start: int | None = None, track_id: str | None = None,
                    duration: int | None = None, source_start: int = 0, overlay: bool = False) -> Segment:
        """Place a material on the timeline (appends to the main track by default)."""
        with self._edit("add_segment"):
            mat = self.project.materials.get(material_id)
            if mat is None:
                raise EditError("unknown material")
            dur = duration
            if dur is None:
                dur = mat.duration if not mat.is_still else self.project.image_duration
            dur = max(MIN_SEGMENT_US, int(dur))
            kind = DEFAULT_TRACK_FOR_MATERIAL[mat.kind]
            if track_id:
                tr = self.project.track_by_id(track_id)
                if tr is None or not tr.accepts(mat.kind):
                    raise EditError("this track does not accept that material")
            elif kind == TrackKind.VIDEO and not overlay:
                tr = self.project.main_track() or self.project.add_track(TrackKind.VIDEO)
            else:
                tr = None
            if tr is not None and tr.locked:
                raise EditError("track is locked")
            t0 = self._snap(start) if start is not None else (tr.end if tr else 0)
            if tr is None:
                tr = self._free_track_for(kind, t0, dur)
            source = None if mat.is_still and mat.kind != MaterialKind.PHOTO else \
                TimeRange(source_start, dur)
            seg = Segment(material_id=mat.id, target=TimeRange(t0, dur), source=source, name=mat.name)
            if tr.is_main:
                # magnetic insert: shift following clips right
                for s in tr.segments:
                    if s.start >= t0:
                        s.start += dur
            elif not tr.free_space(t0, dur):
                raise EditError("no room on that track at this position")
            tr.segments.append(seg)
            return seg

    def add_text(self, text: str = "Default text", start: int = 0, duration: int = 3 * US) -> Segment:
        with self._edit("add_text"):
            seg = new_text_segment(self.project, text, self._snap(start), duration)
            tr = self._free_track_for(TrackKind.TEXT, seg.start, seg.duration)
            tr.segments.append(seg)
            return seg

    def split(self, sid: str, at: int) -> tuple[Segment, Segment]:
        """Cut a segment in two at timeline time ``at``."""
        with self._edit("split"):
            tr, seg = self._seg(sid)
            at = self._snap(at)
            if not (seg.start + MIN_SEGMENT_US <= at <= seg.end - MIN_SEGMENT_US):
                raise EditError("split point too close to the segment edge")
            right = seg.clone()
            left_dur = at - seg.start
            if seg.source is not None:
                src_cut = seg.source_time_at(at) if not seg.reverse else seg.source_time_at(at)
                if seg.reverse:
                    right.source = TimeRange(seg.source.start, src_cut - seg.source.start + 1)
                    seg.source = TimeRange(src_cut + 1, seg.source.end - src_cut - 1)
                else:
                    right.source = TimeRange(src_cut, seg.source.end - src_cut)
                    seg.source = TimeRange(seg.source.start, src_cut - seg.source.start)
            right.target = TimeRange(at, seg.duration - left_dur)
            seg.target.duration = left_dur
            # shift keyframes of the right half; drop transition on the left half
            for kt in right.keyframes:
                for k in kt.keyframes:
                    k.time_offset -= left_dur
                kt.keyframes = [k for k in kt.keyframes if k.time_offset >= 0]
            seg.transition = None
            right.animation.in_name = ""
            seg.animation.out_name = ""
            tr.segments.append(right)
            return seg, right

    def split_at_playhead(self, t: int, ids: Iterable[str] | None = None) -> int:
        """Split every selected (or every) segment under the playhead. Returns the cut count."""
        n = 0
        with self._edit("split"):
            for tr, seg in list(self.project.segments_at(t)):
                if ids is not None and seg.id not in set(ids):
                    continue
                if tr.locked:
                    continue
                try:
                    self.split(seg.id, t)
                    n += 1
                except EditError:
                    pass
            if n == 0:
                raise EditError("nothing to split here")
        return n

    def delete(self, ids: Iterable[str], ripple: bool = False) -> None:
        ids = set(ids)
        with self._edit("delete"):
            for tr in self.project.tracks:
                if tr.locked:
                    continue
                gone = [s for s in tr.segments if s.id in ids]
                if not gone:
                    continue
                tr.segments = [s for s in tr.segments if s.id not in ids]
                if ripple and not tr.is_main:
                    for g in sorted(gone, key=lambda s: s.start, reverse=True):
                        for s in tr.segments:
                            if s.start >= g.end:
                                s.start -= g.duration
            self.project.remove_empty_tracks()

    def move(self, sid: str, new_start: int, track_id: str | None = None) -> None:
        with self._edit("move"):
            tr, seg = self._seg(sid)
            if tr.locked:
                raise EditError("track is locked")
            dest = self.project.track_by_id(track_id) if track_id else tr
            mat = self.project.material_of(seg)
            if dest is None or (mat and not dest.accepts(mat.kind)):
                raise EditError("this track does not accept that clip")
            t0 = self._snap(new_start)
            if dest.is_main:
                # reorder: insert before the first clip whose midpoint is after t0
                if dest is tr:
                    dest.segments.remove(seg)
                else:
                    tr.segments.remove(seg)
                dest.sort()
                idx = 0
                while idx < len(dest.segments) and dest.segments[idx].start + dest.segments[idx].duration / 2 < t0:
                    idx += 1
                dest.segments.insert(idx, seg)
                t = 0                          # re-pack now, otherwise _normalize re-sorts by the old start
                for s in dest.segments:
                    s.target.start = t
                    t += s.target.duration
                return
            if not dest.free_space(t0, seg.duration, {seg.id}):
                raise EditError("no room at that position")
            if dest is not tr:
                tr.segments.remove(seg)
                dest.segments.append(seg)
            seg.start = t0

    def trim(self, sid: str, *, start: int | None = None, end: int | None = None) -> None:
        """Trim the head (``start``) or tail (``end``) of a segment, in timeline time."""
        with self._edit("trim"):
            tr, seg = self._seg(sid)
            if tr.locked:
                raise EditError("track is locked")
            mat = self.project.material_of(seg)
            if end is not None:
                new_dur = self._snap(end) - seg.start
                new_dur = max(MIN_SEGMENT_US, new_dur)
                if seg.source is not None and mat and not mat.is_still:
                    avail = int((mat.duration - seg.source.start) / max(seg.speed.speed, 1e-6))
                    new_dur = min(new_dur, avail)
                if not tr.is_main and not tr.free_space(seg.start, new_dur, {seg.id}):
                    raise EditError("overlaps the next clip")
                if seg.source is not None:
                    seg.source.duration = int(new_dur * seg.speed.speed)
                seg.target.duration = new_dur
            if start is not None:
                new_start = self._snap(start)
                delta = new_start - seg.start
                if seg.duration - delta < MIN_SEGMENT_US:
                    raise EditError("clip would be too short")
                if seg.source is not None:
                    src_delta = int(delta * seg.speed.speed)
                    if seg.source.start + src_delta < 0:
                        raise EditError("no more media before the clip start")
                    seg.source.start += src_delta
                    seg.source.duration -= src_delta
                if not tr.is_main and not tr.free_space(new_start, seg.duration - delta, {seg.id}):
                    raise EditError("overlaps the previous clip")
                seg.target.start = new_start if not tr.is_main else seg.start
                seg.target.duration -= delta

    def duplicate(self, sid: str) -> Segment:
        with self._edit("duplicate"):
            tr, seg = self._seg(sid)
            copy_ = seg.clone()
            if tr.is_main:
                copy_.start = seg.end
                for s in tr.segments:
                    if s.start >= seg.end:
                        s.start += seg.duration
                tr.segments.append(copy_)
            else:
                t0 = seg.end
                dest = tr if tr.free_space(t0, seg.duration) else \
                    self._free_track_for(tr.kind, t0, seg.duration)
                copy_.start = t0
                dest.segments.append(copy_)
            return copy_

    # -------------------------------------------------------- clipboard / paste
    def copy(self, ids: Iterable[str]) -> None:
        ids = set(ids)
        self.clipboard = [s.clone(new_ids=False) for _, s in self.project.iter_segments() if s.id in ids]

    def paste(self, at: int) -> list[Segment]:
        if not self.clipboard:
            return []
        out: list[Segment] = []
        with self._edit("paste"):
            base = min(s.start for s in self.clipboard)
            for src in self.clipboard:
                seg = src.clone()
                seg.start = self._snap(at + src.start - base)
                kind = DEFAULT_TRACK_FOR_MATERIAL[self.project.materials[seg.material_id].kind]
                tr = self.project.main_track() if kind == TrackKind.VIDEO and \
                    self.project.main_track().free_space(seg.start, seg.duration) else \
                    self._free_track_for(kind, seg.start, seg.duration)
                tr.segments.append(seg)
                out.append(seg)
        return out

    # --------------------------------------------------------- clip properties
    def set_speed(self, sid: str, speed: float) -> None:
        if not 0.1 <= speed <= 100:
            raise EditError("speed must be between 0.1x and 100x")
        with self._edit("speed"):
            tr, seg = self._seg(sid)
            if seg.source is None:
                raise EditError("this clip has no source media")
            seg.speed.mode = 0
            seg.speed.speed = speed
            seg.target.duration = max(MIN_SEGMENT_US, int(seg.source.duration / speed))
            if not tr.is_main and not tr.free_space(seg.start, seg.duration, {seg.id}):
                raise EditError("slowing down would overlap the next clip")

    def toggle_reverse(self, sid: str) -> bool:
        with self._edit("reverse"):
            _, seg = self._seg(sid)
            seg.reverse = not seg.reverse
            return seg.reverse

    def freeze_frame(self, sid: str, at: int, duration: int = 3 * US) -> Segment:
        """Insert a still frame of the clip at ``at`` (splits the clip, like CapCut)."""
        with self._edit("freeze"):
            tr, seg = self._seg(sid)
            if seg.source is None:
                raise EditError("cannot freeze this clip")
            left, right = self.split(sid, at)
            frozen = right.clone()
            frozen.freeze = True
            frozen.speed.speed = 1.0
            frozen.target = TimeRange(right.start, duration)
            frozen.source = TimeRange(right.source.start, duration)
            frozen.keyframes = []
            for s in tr.segments:
                if s.start >= right.start:
                    s.start += duration
            tr.segments.append(frozen)
            return frozen

    def set_transition(self, sid: str, name: str | None, duration: int = 500_000) -> None:
        with self._edit("transition"):
            tr, seg = self._seg(sid)
            if name is None:
                seg.transition = None
                return
            if tr.next_segment(seg) is None:
                raise EditError("a transition needs a following clip")
            seg.transition = Transition(name=name, duration=min(duration, seg.duration))

    def update(self, sid: str, merge: bool = False, **changes) -> None:
        """Generic attribute update, e.g. ``update(id, transform=Transform(...))``.

        ``merge=True`` folds repeated updates of the same clip into one undo step (sliders)."""
        with self._edit("update", merge=("update", sid, tuple(sorted(changes))) if merge else None):
            _, seg = self._seg(sid)
            for k, v in changes.items():
                if not hasattr(seg, k):
                    raise EditError(f"unknown segment property {k!r}")
                setattr(seg, k, copy.deepcopy(v))

    def set_keyframe(self, sid: str, prop: str, t: int, value: float, curve: str = "Line") -> None:
        from .model import Keyframe
        with self._edit("keyframe"):
            _, seg = self._seg(sid)
            offset = max(0, min(int(t) - seg.start, seg.duration))
            kt = seg.keyframe_track(prop, create=True)
            kt.keyframes = [k for k in kt.keyframes if k.time_offset != offset]
            kt.keyframes.append(Keyframe(time_offset=offset, value=value, curve=curve))
            kt.keyframes.sort(key=lambda k: k.time_offset)

    def remove_keyframe(self, sid: str, prop: str, t: int) -> None:
        with self._edit("keyframe"):
            _, seg = self._seg(sid)
            kt = seg.keyframe_track(prop)
            if kt:
                off = int(t) - seg.start
                kt.keyframes = [k for k in kt.keyframes if k.time_offset != off]
                if not kt.keyframes:
                    seg.keyframes.remove(kt)

    # ------------------------------------------------------------------ project
    def set_ratio(self, ratio: str) -> None:
        with self._edit("ratio"):
            self.project.set_ratio(ratio)

    def add_marker(self, t: int, name: str = "") -> Marker:
        with self._edit("marker"):
            m = Marker(time=self._snap(t), name=name)
            self.project.markers.append(m)
            self.project.markers.sort(key=lambda x: x.time)
            return m
