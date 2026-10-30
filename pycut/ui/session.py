"""Shared UI state: playhead, selection, playback clock. One ``Session`` per open project."""
from __future__ import annotations

import time

from PySide6.QtCore import QObject, QTimer, Signal

from ..core.editor import Editor
from ..core.timebase import US, snap_to_frame


class Session(QObject):
    project_changed = Signal(str)     # any edit / undo / redo / load (argument = label)
    playhead_changed = Signal(int)
    selection_changed = Signal()
    play_state_changed = Signal(bool)
    message = Signal(str)             # toast text
    options_changed = Signal()

    def __init__(self, editor: Editor, parent=None) -> None:
        super().__init__(parent)
        self.editor = editor
        self.playhead = 0
        self.selection: list[str] = []
        self.playing = False
        self.snapping = True          # auto snapping
        self.magnet = True            # main track magnet (always on in this version)
        self.linkage = True
        self.dirty = False
        self._t0 = 0.0
        self._p0 = 0
        self._timer = QTimer(self)
        self._timer.setInterval(16)
        self._timer.timeout.connect(self._tick)
        editor.subscribe(self._on_edit)

    # -- project -----------------------------------------------------------------
    @property
    def project(self):
        return self.editor.project

    def _on_edit(self, label: str) -> None:
        self.dirty = label != "load"
        alive = {s.id for _, s in self.project.iter_segments()}
        keep = [i for i in self.selection if i in alive]
        if keep != self.selection:
            self.selection = keep
            self.selection_changed.emit()
        self.project_changed.emit(label)

    def fps(self) -> float:
        return self.project.fps

    # -- playhead ----------------------------------------------------------------
    def set_playhead(self, t: int, snap: bool = True) -> None:
        end = max(self.project.duration, 0)
        t = max(0, min(int(t), end))
        if snap:
            t = min(snap_to_frame(t, self.fps()), end)
        if t != self.playhead:
            self.playhead = t
            self.playhead_changed.emit(t)

    def step_frames(self, n: int) -> None:
        self.set_playhead(self.playhead + int(n * US / self.fps()))

    # -- selection ---------------------------------------------------------------
    def select(self, ids: list[str], add: bool = False) -> None:
        new = list(dict.fromkeys(([*self.selection, *ids]) if add else ids))
        if new != self.selection:
            self.selection = new
            self.selection_changed.emit()

    def selected_segments(self):
        out = []
        for sid in self.selection:
            f = self.project.find_segment(sid)
            if f:
                out.append(f[1])
        return out

    # -- playback ----------------------------------------------------------------
    def toggle_play(self) -> None:
        self.pause() if self.playing else self.play()

    def play(self) -> None:
        if self.project.duration <= 0:
            return
        if self.playhead >= self.project.duration:
            self.playhead = 0
        self.playing = True
        self._t0, self._p0 = time.monotonic(), self.playhead
        self._timer.start()
        self.play_state_changed.emit(True)

    def pause(self) -> None:
        if self.playing:
            self.playing = False
            self._timer.stop()
            self.play_state_changed.emit(False)

    def _tick(self) -> None:
        t = self._p0 + int((time.monotonic() - self._t0) * US)
        if t >= self.project.duration:
            self.playhead = self.project.duration
            self.playhead_changed.emit(self.playhead)
            self.pause()
            return
        self.playhead = t
        self.playhead_changed.emit(t)

    def toast(self, text: str) -> None:
        self.message.emit(text)
