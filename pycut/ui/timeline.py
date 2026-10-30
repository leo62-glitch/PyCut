"""Timeline: toolbar + custom painted canvas (ruler, track headers, clips, playhead) with drag & drop editing."""
from __future__ import annotations

import math

from PySide6.QtCore import QMimeData, QPoint, QPointF, QRect, QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QCursor, QFont, QFontMetrics, QPainter, QPainterPath, QPen, QPixmap, QPolygonF
from PySide6.QtWidgets import (QHBoxLayout, QMenu, QPushButton, QScrollBar, QSlider, QToolButton, QVBoxLayout,
                               QWidget)

from ..core.editor import EditError
from ..core.model import MaterialKind, Segment, Track, TrackKind
from ..core.probe import kind_of, probe
from ..core.timebase import US, format_timecode
from . import icons
from .session import Session
from .theme import C, qcolor

HEAD_W = 78          # track header column (CapCut: timeline origin at x=87 of the window, panel starts at 9)
RULER_H = 26
MAIN_H = 58
ROW_H = 36
GAP = 3
MIME_MATERIAL = "application/x-pycut-material"
EDGE = 7

KIND_COLOR = {TrackKind.VIDEO: C.clip_video, TrackKind.AUDIO: C.clip_audio, TrackKind.TEXT: C.clip_text}


class TimelineCanvas(QWidget):
    def __init__(self, session: Session, thumbs, parent=None) -> None:
        super().__init__(parent)
        self.s = session
        self.thumbs = thumbs                 # callable(material) -> QPixmap | None
        self.pps = 90.0                      # pixels per second
        self.x_off = 0.0
        self.y_off = 0
        self.setMouseTracking(True)
        self.setAcceptDrops(True)
        self.setFocusPolicy(Qt.StrongFocus)
        self.drag = None                     # dict describing the active gesture
        self.snap_line: int | None = None
        self.drop_hint: tuple[int, int] | None = None   # (time, row index) for external drops
        self._rows: list[tuple[Track, int, int]] = []
        session.project_changed.connect(lambda *_: self.update())
        session.playhead_changed.connect(self._follow_playhead)
        session.selection_changed.connect(self.update)

    # -- geometry ----------------------------------------------------------------
    def t2x(self, t: float) -> float:
        return HEAD_W + t / US * self.pps - self.x_off

    def x2t(self, x: float) -> int:
        return int(max(0.0, (x - HEAD_W + self.x_off) / self.pps * US))

    def content_width(self) -> int:
        return int(max(self.s.project.duration / US * self.pps + 400, self.width() - HEAD_W))

    def display_tracks(self) -> list[Track]:
        tracks = self.s.project.tracks
        visual = [t for t in tracks if t.kind != TrackKind.AUDIO and not t.is_main]
        main = [t for t in tracks if t.is_main]
        audio = [t for t in tracks if t.kind == TrackKind.AUDIO]
        return list(reversed(visual)) + main + audio

    def top_pad(self) -> int:
        """Free lane above the top track (drop zone for a new overlay track); bigger when the project is empty."""
        empty = not any(t.segments for t in self.s.project.tracks)
        return 150 if empty else 2 * (ROW_H + GAP)

    def layout_rows(self) -> list[tuple[Track, int, int]]:
        rows, y = [], RULER_H + 6 + self.top_pad() - self.y_off
        for tr in self.display_tracks():
            h = MAIN_H if tr.is_main else ROW_H
            rows.append((tr, y, h))
            y += h + GAP
        self._rows = rows
        return rows

    def content_height(self) -> int:
        return RULER_H + 6 + self.top_pad() + sum((MAIN_H if t.is_main else ROW_H) + GAP for t in self.display_tracks()) + 60

    def row_at(self, y: float):
        for tr, ry, h in self.layout_rows():
            if ry - 2 <= y <= ry + h + 2:
                return tr, ry, h
        return None

    def seg_rect(self, tr: Track, ry: int, h: int, seg: Segment, start=None, dur=None) -> QRectF:
        s = seg.start if start is None else start
        d = seg.duration if dur is None else dur
        x1, x2 = self.t2x(s), self.t2x(s + d)
        return QRectF(x1, ry, max(2.0, x2 - x1), h)

    def seg_at(self, pos: QPointF):
        for tr, ry, h in self.layout_rows():
            for seg in tr.segments:
                if self.seg_rect(tr, ry, h, seg).contains(pos):
                    return tr, ry, h, seg
        return None

    # -- zoom / scroll ----------------------------------------------------------------
    def set_zoom(self, pps: float, anchor_t: int | None = None) -> None:
        anchor_t = self.s.playhead if anchor_t is None else anchor_t
        ax = self.t2x(anchor_t)
        self.pps = max(3.0, min(1500.0, pps))
        self.x_off = max(0.0, HEAD_W + anchor_t / US * self.pps - ax)
        self.zoom_changed.emit()
        self.update()

    zoom_changed = Signal()
    scrolled = Signal()

    def fit(self) -> None:
        dur = max(self.s.project.duration, US)
        self.x_off = 0
        self.set_zoom((self.width() - HEAD_W - 60) / (dur / US), 0)

    def _follow_playhead(self, t: int) -> None:
        if self.s.playing:
            x = self.t2x(t)
            if x > self.width() - 40 or x < HEAD_W:
                self.x_off = max(0.0, HEAD_W + t / US * self.pps - HEAD_W - 20)
                self.scrolled.emit()
        self.update()

    def wheelEvent(self, e) -> None:
        d = e.angleDelta()
        if e.modifiers() & Qt.ControlModifier:
            self.set_zoom(self.pps * (1.15 if d.y() > 0 else 1 / 1.15), self.x2t(e.position().x()))
        elif e.modifiers() & Qt.ShiftModifier or abs(d.x()) > abs(d.y()):
            self.x_off = max(0.0, min(self.content_width() - self.width() + HEAD_W, self.x_off - (d.x() or d.y())))
            self.scrolled.emit()
        else:
            self.y_off = max(0, min(max(0, self.content_height() - self.height()), self.y_off - d.y() // 2))
        self.update()

    # -- painting ----------------------------------------------------------------
    def paintEvent(self, ev) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.fillRect(self.rect(), qcolor(C.panel))
        proj = self.s.project
        rows = self.layout_rows()
        empty = not any(tr.segments for tr in proj.tracks)
        # clip region for the scrolling area (right of the headers)
        p.save()
        p.setClipRect(QRect(HEAD_W, 0, self.width() - HEAD_W, self.height()))
        for tr, ry, h in rows:
            if tr.is_main and empty:
                self._paint_empty_main(p, ry, h)
            else:
                p.fillRect(QRectF(HEAD_W, ry, self.width(), h), qcolor("#2B2B2B", 0.6 if not tr.is_main else 0.0))
            for seg in tr.segments:
                self._paint_segment(p, tr, ry, h, seg)
        if self.drag and self.drag.get("kind") in ("move", "trim_l", "trim_r"):
            self._paint_ghost(p)
        if self.drop_hint:
            t, ri = self.drop_hint
            p.setPen(QPen(qcolor(C.accent), 2))
            x = self.t2x(t)
            p.drawLine(QPointF(x, RULER_H), QPointF(x, self.height()))
        if self.snap_line is not None:
            p.setPen(QPen(qcolor(C.warn), 1, Qt.DashLine))
            x = self.t2x(self.snap_line)
            p.drawLine(QPointF(x, RULER_H), QPointF(x, self.height()))
        p.restore()
        if not empty:
            self._paint_ruler(p)
            self._paint_headers(p, rows)
        self._paint_playhead(p)
        p.end()

    def _paint_empty_main(self, p: QPainter, ry: int, h: int) -> None:
        r = QRectF(HEAD_W + 8, ry + 4, self.width() - HEAD_W - 20, h - 8)
        p.setPen(Qt.NoPen)
        p.setBrush(qcolor(C.track))
        p.drawRoundedRect(r, 6, 6)
        p.drawPixmap(int(r.left() + 20), int(r.center().y() - 8), icons.pixmap("multimedia", "#A0A0A0", 16))
        p.setPen(qcolor(C.text))
        p.drawText(QPointF(r.left() + 44, r.center().y() + 4), "Fais glisser les ressources ici et commence à créer")

    def _paint_segment(self, p: QPainter, tr: Track, ry: int, h: int, seg: Segment) -> None:
        r = self.seg_rect(tr, ry, h, seg)
        if r.right() < HEAD_W or r.left() > self.width():
            return
        if self.drag and self.drag.get("sid") == seg.id and self.drag["kind"] == "move":
            p.setOpacity(0.35)
        mat = self.s.project.material_of(seg)
        color = qcolor(KIND_COLOR.get(tr.kind, C.clip_other))
        selected = seg.id in self.s.selection
        path = QPainterPath()
        path.addRoundedRect(r.adjusted(0.5, 0.5, -0.5, -0.5), 4, 4)
        p.save()
        p.setClipPath(path)
        p.fillPath(path, color)
        if mat is not None and tr.kind == TrackKind.VIDEO and mat.kind != MaterialKind.TEXT:
            pm = self.thumbs(mat)
            if pm is not None and not pm.isNull():
                th = int(h)
                tw = max(1, int(pm.width() * th / max(1, pm.height())))
                x = r.left()
                while x < r.right():
                    p.drawPixmap(QRectF(x, r.top(), tw, th).toRect(), pm)
                    x += tw
                p.fillRect(r, qcolor("#000000", 0.25))
        if tr.kind == TrackKind.AUDIO:
            p.setPen(QPen(qcolor("#7FE3EA", 0.55), 1))
            my = r.center().y() + 4
            x = max(r.left() + 2, HEAD_W)
            while x < min(r.right(), self.width()):
                amp = 3 + 6 * abs(math.sin((x - r.left()) * 0.13 + seg.start * 1e-6) * math.sin((x - r.left()) * 0.037))
                p.drawLine(QPointF(x, my - amp), QPointF(x, my + amp))
                x += 3
        p.restore()
        # label
        p.setPen(qcolor("#FFFFFF", 0.95))
        f = p.font()
        f.setPixelSize(11)
        p.setFont(f)
        label = seg.name or (mat.name if mat else "")
        if seg.reverse:
            label = "⟲ " + label
        if seg.speed.mode == 0 and abs(seg.speed.speed - 1) > 1e-3:
            label += f"  {seg.speed.speed:.1f}x"
        if r.width() > 24:
            p.setClipRect(r.adjusted(4, 0, -4, 0))
            p.drawText(QPointF(r.left() + 6, r.top() + 14), label)
            p.setClipping(False)
        # keyframes
        if seg.has_keyframes():
            p.setBrush(qcolor(C.warn))
            p.setPen(Qt.NoPen)
            times = {k.time_offset for kt in seg.keyframes for k in kt.keyframes}
            for off in times:
                cx = self.t2x(seg.start + off)
                p.drawPolygon(QPolygonF([QPointF(cx, r.bottom() - 9), QPointF(cx + 4, r.bottom() - 5),
                                         QPointF(cx, r.bottom() - 1), QPointF(cx - 4, r.bottom() - 5)]))
        if seg.transition is not None:
            p.setBrush(qcolor(C.accent))
            p.setPen(Qt.NoPen)
            p.drawRoundedRect(QRectF(r.right() - 9, r.center().y() - 9, 18, 18), 4, 4)
            p.drawPixmap(int(r.right() - 7), int(r.center().y() - 7), icons.pixmap("transitions", "#04282B", 14))
        p.setOpacity(1.0)
        if selected:
            p.setPen(QPen(qcolor(C.select), 2))
            p.setBrush(Qt.NoBrush)
            p.drawRoundedRect(r.adjusted(1, 1, -1, -1), 4, 4)

    def _paint_ghost(self, p: QPainter) -> None:
        d = self.drag
        if "ghost" not in d:
            return
        t0, dur, row = d["ghost"]
        tr, ry, h = row
        r = QRectF(self.t2x(t0), ry, max(2.0, self.t2x(t0 + dur) - self.t2x(t0)), h)
        p.setPen(QPen(qcolor(C.select), 1.5, Qt.DashLine))
        p.setBrush(qcolor("#FFFFFF", 0.12))
        p.drawRoundedRect(r, 4, 4)

    def _paint_ruler(self, p: QPainter) -> None:
        p.fillRect(QRect(0, 0, self.width(), RULER_H), qcolor(C.panel))
        p.save()
        p.setClipRect(QRect(HEAD_W, 0, self.width() - HEAD_W, RULER_H))
        f = p.font()
        f.setPixelSize(10)
        p.setFont(f)
        fps = self.s.fps()
        steps = [1 / fps, 2 / fps, 5 / fps, 10 / fps, 0.5, 1, 2, 5, 10, 15, 30, 60, 120, 300, 600, 1800, 3600]
        step = next((s for s in steps if s * self.pps >= 90), steps[-1])
        sub = step / 5
        t = (math.floor(max(0, self.x_off - 20) / self.pps / step)) * step
        end_t = (self.x_off + self.width()) / self.pps
        while t <= end_t:
            x = HEAD_W + t * self.pps - self.x_off
            p.setPen(qcolor("#8C8C8C"))
            p.drawLine(QPointF(x, RULER_H - 9), QPointF(x, RULER_H - 1))
            tc = format_timecode(int(t * US), fps, show_frames=step < 1, show_hours=False)
            p.drawText(QPointF(x + 4, RULER_H - 12), tc if step < 1 else tc[:5])
            p.setPen(qcolor("#555555"))
            for i in range(1, 5):
                xs = x + i * sub * self.pps
                p.drawLine(QPointF(xs, RULER_H - 4), QPointF(xs, RULER_H - 1))
            t += step
        for m in self.s.project.markers:
            x = self.t2x(m.time)
            p.setBrush(qcolor(m.color))
            p.setPen(Qt.NoPen)
            p.drawPolygon(QPolygonF([QPointF(x - 5, 2), QPointF(x + 5, 2), QPointF(x + 5, 10), QPointF(x, 15), QPointF(x - 5, 10)]))
        p.restore()

    def _paint_headers(self, p: QPainter, rows) -> None:
        p.fillRect(QRect(0, RULER_H, HEAD_W - 2, self.height()), qcolor(C.panel))
        p.setClipRect(QRect(0, RULER_H, HEAD_W - 2, self.height()))
        for tr, ry, h in rows:
            ico = {"video": "video", "audio": "audio", "text": "text"}.get(tr.kind.value, "video")
            x = 6
            for name, on, active_name in (("lock" if tr.locked else "unlock", tr.locked, None),
                                          ("eye_off" if tr.hidden else "eye", tr.hidden, None),
                                          ("mute" if tr.muted else "volume", tr.muted, None)):
                if name in ("volume", "mute") and tr.kind == TrackKind.TEXT:
                    continue
                p.drawPixmap(x, int(ry + h / 2 - 8), icons.pixmap(name, C.accent if on else "#9A9A9A", 16))
                x += 22
        p.setClipping(False)

    def header_hit(self, pos: QPointF):
        for tr, ry, h in self._rows:
            if ry <= pos.y() <= ry + h and pos.x() < HEAD_W:
                idx = int((pos.x() - 6) // 22)
                names = ["locked", "hidden", "muted"]
                if 0 <= idx < 3:
                    return tr, names[idx]
        return None

    def _paint_playhead(self, p: QPainter) -> None:
        x = self.t2x(self.s.playhead)
        if x < HEAD_W - 1 or x > self.width():
            return
        p.setPen(QPen(qcolor(C.playhead), 1.5))
        p.drawLine(QPointF(x, 8), QPointF(x, self.height()))
        p.setBrush(qcolor(C.playhead))
        p.setPen(Qt.NoPen)
        path = QPainterPath()
        path.addRoundedRect(QRectF(x - 6, 1, 12, 10), 2, 2)
        path.moveTo(x - 6, 9)
        path.lineTo(x, 16)
        path.lineTo(x + 6, 9)
        p.drawPath(path)

    # -- snapping ----------------------------------------------------------------
    def snap_candidates(self, ignore: set[str]) -> list[int]:
        pts = {0, self.s.playhead}
        for _, seg in self.s.project.iter_segments():
            if seg.id not in ignore:
                pts.add(seg.start)
                pts.add(seg.end)
        pts.update(m.time for m in self.s.project.markers)
        return sorted(pts)

    def snap(self, t: int, ignore: set[str], also: int = 0) -> int:
        self.snap_line = None
        if not self.s.snapping:
            return t
        tol = 9 / self.pps * US
        best = None
        for c in self.snap_candidates(ignore):
            for off in (0, also):
                d = abs((t + off) - c)
                if d < tol and (best is None or d < best[0]):
                    best = (d, c - off, c)
        if best:
            self.snap_line = best[2]
            return best[1]
        return t

    # -- mouse ----------------------------------------------------------------
    def mousePressEvent(self, e) -> None:
        pos = e.position()
        self.setFocus()
        if e.button() == Qt.RightButton:
            hit = self.seg_at(pos)
            if hit and hit[3].id not in self.s.selection:
                self.s.select([hit[3].id])
            self._context_menu(e.globalPosition().toPoint(), hit[3] if hit else None, self.x2t(pos.x()))
            return
        if e.button() != Qt.LeftButton:
            return
        if pos.y() < RULER_H and pos.x() >= HEAD_W:
            self.drag = {"kind": "scrub"}
            self.s.pause()
            self.s.set_playhead(self.x2t(pos.x()))
            return
        hh = self.header_hit(pos)
        if hh:
            tr, flag = hh
            self.s.editor.set_track_flags(tr.id, **{flag: not getattr(tr, flag)})
            return
        if pos.x() < HEAD_W:
            return
        hit = self.seg_at(pos)
        if not hit:
            self.s.select([])
            self.drag = {"kind": "scrub"}
            self.s.set_playhead(self.x2t(pos.x()))
            return
        tr, ry, h, seg = hit
        add = bool(e.modifiers() & (Qt.ControlModifier | Qt.ShiftModifier))
        if seg.id not in self.s.selection or add:
            self.s.select([seg.id], add=add)
        if tr.locked:
            return
        r = self.seg_rect(tr, ry, h, seg)
        kind = "move"
        if pos.x() - r.left() < EDGE:
            kind = "trim_l"
        elif r.right() - pos.x() < EDGE:
            kind = "trim_r"
        self.drag = {"kind": kind, "sid": seg.id, "press": pos, "start": seg.start, "dur": seg.duration,
                     "grab": self.x2t(pos.x()) - seg.start, "moved": False, "track": tr.id}

    def mouseMoveEvent(self, e) -> None:
        pos = e.position()
        d = self.drag
        if d is None:
            hit = self.seg_at(pos) if pos.x() >= HEAD_W and pos.y() >= RULER_H else None
            cur = Qt.ArrowCursor
            if hit:
                r = self.seg_rect(*hit[:3], hit[3])
                cur = Qt.SizeHorCursor if (pos.x() - r.left() < EDGE or r.right() - pos.x() < EDGE) else Qt.OpenHandCursor
            self.setCursor(cur)
            return
        if d["kind"] == "scrub":
            self.s.set_playhead(self.x2t(pos.x()))
            return
        if (pos - d["press"]).manhattanLength() < 4 and not d["moved"]:
            return
        d["moved"] = True
        fps = self.s.fps()
        f = int(US / fps)
        found = self.s.project.find_segment(d["sid"])
        if not found:
            return
        tr, seg = found
        ign = {s_id for s_id in self.s.selection} | {seg.id}
        if d["kind"] == "move":
            t = self.x2t(pos.x()) - d["grab"]
            t = max(0, self.snap(t, ign, also=d["dur"]))
            t = round(t / f) * f
            row = self.row_at(pos.y())
            if row is None:
                row = next(((tt, y, hh) for tt, y, hh in self._rows if tt is tr), None)
            else:
                row = (row[0], row[1], row[2])
            d["ghost"] = (t, d["dur"], row)
            d["target"] = (t, row[0].id)
            self.setCursor(Qt.ClosedHandCursor)
        elif d["kind"] == "trim_r":
            t = self.snap(self.x2t(pos.x()), ign)
            t = max(d["start"] + f, round(t / f) * f)
            row = next(r for r in self._rows if r[0] is tr)
            d["ghost"] = (d["start"], t - d["start"], row)
            d["target"] = (None, t)
        elif d["kind"] == "trim_l":
            t = self.snap(self.x2t(pos.x()), ign)
            t = min(d["start"] + d["dur"] - f, max(0, round(t / f) * f))
            row = next(r for r in self._rows if r[0] is tr)
            d["ghost"] = (t, d["start"] + d["dur"] - t, row)
            d["target"] = (t, None)
        self.update()

    def mouseReleaseEvent(self, e) -> None:
        d, self.drag = self.drag, None
        self.snap_line = None
        if d and d["kind"] in ("move", "trim_l", "trim_r") and d.get("moved") and "target" in d:
            try:
                if d["kind"] == "move":
                    t, tid = d["target"]
                    self.s.editor.move(d["sid"], t, tid)
                elif d["kind"] == "trim_r":
                    self.s.editor.trim(d["sid"], end=d["target"][1])
                else:
                    self.s.editor.trim(d["sid"], start=d["target"][0])
            except EditError as ex:
                self.s.toast(str(ex))
        self.update()

    def mouseDoubleClickEvent(self, e) -> None:
        hit = self.seg_at(e.position())
        if hit:
            self.s.set_playhead(hit[3].start)

    # -- context menu ----------------------------------------------------------------
    def _context_menu(self, gpos: QPoint, seg: Segment | None, t: int) -> None:
        ed = self.s.editor
        m = QMenu(self)
        if seg is not None:
            ids = list(self.s.selection)
            m.addAction("Diviser", lambda: self._split(ids)).setEnabled(seg.start < self.s.playhead < seg.end)
            m.addAction("Copier", lambda: ed.copy(ids))
            m.addAction("Dupliquer", lambda: [ed.duplicate(i) for i in ids])
            m.addAction("Supprimer", lambda: ed.delete(ids))
            m.addAction("Supprimer et fermer l'espace", lambda: ed.delete(ids, ripple=True))
            m.addSeparator()
            if seg.source is not None:
                m.addAction("Inverser", lambda: ed.toggle_reverse(seg.id))
                sp = m.addMenu("Vitesse")
                for v in (0.25, 0.5, 1.0, 1.5, 2.0, 4.0):
                    sp.addAction(f"{v:g}x", lambda v=v: self._try(lambda: ed.set_speed(seg.id, v)))
                m.addAction("Image figée", lambda: self._try(lambda: ed.freeze_frame(seg.id, self.s.playhead)))
        m.addAction("Coller", lambda: ed.paste(self.s.playhead)).setEnabled(bool(ed.clipboard))
        m.addAction("Ajouter un repère", lambda: ed.add_marker(self.s.playhead))
        m.exec(gpos)

    def _try(self, fn) -> None:
        try:
            fn()
        except EditError as ex:
            self.s.toast(str(ex))

    def _split(self, ids) -> None:
        self._try(lambda: self.s.editor.split_at_playhead(self.s.playhead, ids or None))

    # -- external drops ----------------------------------------------------------------
    def dragEnterEvent(self, e) -> None:
        if e.mimeData().hasFormat(MIME_MATERIAL) or e.mimeData().hasUrls():
            e.acceptProposedAction()

    def dragMoveEvent(self, e) -> None:
        self.drop_hint = (self.x2t(e.position().x()), 0)
        self.update()
        e.acceptProposedAction()

    def dragLeaveEvent(self, e) -> None:
        self.drop_hint = None
        self.update()

    def dropEvent(self, e) -> None:
        self.drop_hint = None
        t = self.x2t(e.position().x())
        row = self.row_at(e.position().y())
        ed = self.s.editor
        mids: list[str] = []
        md = e.mimeData()
        if md.hasFormat(MIME_MATERIAL):
            mids = bytes(md.data(MIME_MATERIAL)).decode().split(",")
        elif md.hasUrls():
            for u in md.urls():
                if kind_of(u.toLocalFile()):
                    m = probe(u.toLocalFile())
                    if m:
                        ed.import_material(m)
                        mids.append(m.id)
        try:
            cursor_t = t
            for mid in mids:
                mat = ed.project.materials.get(mid)
                if mat is None:
                    continue
                visual = mat.kind in (MaterialKind.VIDEO, MaterialKind.PHOTO, MaterialKind.GIF)
                if row and row[0].accepts(mat.kind) and not row[0].is_main:
                    seg = ed.add_segment(mid, start=cursor_t, track_id=row[0].id)
                elif visual and (row is None or not row[0].is_main) and ed.project.main_track().segments:
                    seg = ed.add_segment(mid, start=cursor_t, overlay=True)
                else:
                    seg = ed.add_segment(mid, start=cursor_t if row and row[0].is_main else None)
                cursor_t = seg.end if not seg.start == 0 or True else cursor_t
            e.acceptProposedAction()
        except EditError as ex:
            self.s.toast(str(ex))
        self.update()

    def resizeEvent(self, e) -> None:
        self.scrolled.emit()


class TimelineToolbar(QWidget):
    def __init__(self, session: Session, canvas: TimelineCanvas, parent=None) -> None:
        super().__init__(parent)
        self.s, self.canvas = session, canvas
        self.setFixedHeight(32)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(8, 0, 10, 0)
        lay.setSpacing(2)
        ed = session.editor

        def btn(name, tip, fn=None, color="#E1E1E1", checkable=False):
            b = QToolButton()
            b.setIcon(icons.icon(name, color, 18))
            b.setIconSize(QSize(18, 18))
            b.setToolTip(tip)
            b.setFixedSize(30, 28)
            b.setAutoRaise(True)
            b.setStyleSheet("QToolButton{border:none;border-radius:4px;} QToolButton:hover{background:#3A3A3A;} "
                            "QToolButton:disabled{opacity:.4}")
            if fn:
                b.clicked.connect(fn)
            return b

        def sep():
            w = QWidget(); w.setFixedSize(1, 16); w.setStyleSheet(f"background:{C.line}"); return w

        lay.addWidget(btn("plus", "Ajouter une piste", lambda: self._add_track()))
        lay.addWidget(sep())
        self.sel = btn("select", "Sélection")
        lay.addWidget(self.sel)
        lay.addWidget(btn("chevron_down", "", None))
        lay.itemAt(lay.count() - 1).widget().setFixedWidth(16)
        lay.addWidget(sep())
        self.undo = btn("undo", "Annuler (Ctrl+Z)", lambda: ed.undo())
        self.redo = btn("redo", "Rétablir (Ctrl+Maj+Z)", lambda: ed.redo())
        lay.addWidget(self.undo)
        lay.addWidget(self.redo)
        lay.addWidget(btn("split", "Diviser (Ctrl+B)", lambda: self.canvas._split(self.s.selection)))
        lay.addWidget(btn("trim_l", "Supprimer à gauche (Q)", lambda: self._quick_trim(True)))
        lay.addWidget(btn("trim_r", "Supprimer à droite (W)", lambda: self._quick_trim(False)))
        lay.addWidget(btn("delete", "Supprimer (Suppr)", lambda: ed.delete(self.s.selection)))
        lay.addWidget(btn("shield", "Verrouiller la piste sélectionnée", self._lock_selected))
        lay.addStretch(1)
        lay.addWidget(btn("mic", "Enregistrer (bientôt)", lambda: self.s.toast("L'enregistrement audio n'est pas encore disponible")))
        lay.addSpacing(10)
        self.b_magnet = btn("magnet", "Aimant de la piste principale", lambda: self._toggle("magnet"), checkable=True)
        self.b_snap = btn("snap", "Alignement automatique (S)", lambda: self._toggle("snapping"), checkable=True)
        self.b_link = btn("link", "Liaison", lambda: self._toggle("linkage"), checkable=True)
        for b in (self.b_magnet, self.b_snap, self.b_link):
            lay.addWidget(b)
        lay.addSpacing(10)
        lay.addWidget(btn("fit", "Ajuster à la fenêtre", canvas.fit))
        lay.addWidget(btn("zoom_out", "Zoom arrière (Ctrl+-)", lambda: canvas.set_zoom(canvas.pps / 1.3)))
        self.zoom = QSlider(Qt.Horizontal)
        self.zoom.setRange(0, 1000)
        self.zoom.setFixedWidth(96)
        self.zoom.valueChanged.connect(self._slider)
        lay.addWidget(self.zoom)
        lay.addWidget(btn("zoom_in", "Zoom avant (Ctrl++)", lambda: canvas.set_zoom(canvas.pps * 1.3)))
        canvas.zoom_changed.connect(self._sync_zoom)
        session.project_changed.connect(lambda *_: self._refresh())
        session.options_changed.connect(self._refresh)
        self._sync_zoom()
        self._refresh()

    def _slider(self, v: int) -> None:
        pps = 3 * (500 ** (v / 1000))
        if abs(pps - self.canvas.pps) / pps > 0.01:
            self.canvas.set_zoom(pps)

    def _sync_zoom(self) -> None:
        self.zoom.blockSignals(True)
        self.zoom.setValue(int(1000 * math.log(max(3.0, self.canvas.pps) / 3, 500)))
        self.zoom.blockSignals(False)

    def _refresh(self) -> None:
        ed = self.s.editor
        self.undo.setEnabled(ed.can_undo)
        self.redo.setEnabled(ed.can_redo)
        for b, on, name in ((self.b_magnet, self.s.magnet, "magnet"), (self.b_snap, self.s.snapping, "snap"),
                            (self.b_link, self.s.linkage, "link")):
            b.setIcon(icons.icon(name, C.accent if on else "#9A9A9A", 18))

    def _toggle(self, attr: str) -> None:
        if attr == "magnet":
            self.s.toast("L'aimant de la piste principale est toujours actif dans cette version")
            return
        setattr(self.s, attr, not getattr(self.s, attr))
        self.s.options_changed.emit()

    def _add_track(self) -> None:
        m = QMenu(self)
        for label, kind in (("Piste vidéo", TrackKind.VIDEO), ("Piste audio", TrackKind.AUDIO), ("Piste texte", TrackKind.TEXT)):
            m.addAction(label, lambda k=kind: self.s.editor.add_track(k))
        m.exec(QCursor.pos())

    def _quick_trim(self, left: bool) -> None:
        t = self.s.playhead
        ed = self.s.editor
        ids = self.s.selection or [s.id for _, s in self.s.project.segments_at(t)]
        for sid in ids:
            f = self.s.project.find_segment(sid)
            if not f or not (f[1].start < t < f[1].end):
                continue
            try:
                ed.trim(sid, start=t) if left else ed.trim(sid, end=t)
            except EditError as ex:
                self.s.toast(str(ex))

    def _lock_selected(self) -> None:
        for seg in self.s.selected_segments():
            tr = self.s.project.track_of(seg)
            if tr:
                self.s.editor.set_track_flags(tr.id, locked=not tr.locked)


class TimelinePanel(QWidget):
    """Toolbar + canvas + horizontal scrollbar, in a rounded #262626 panel."""

    def __init__(self, session: Session, thumbs, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("timelinePanel")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setStyleSheet(f"#timelinePanel{{background:{C.panel};border-radius:4px;}}")
        self.s = session
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        self.canvas = TimelineCanvas(session, thumbs)
        self.toolbar = TimelineToolbar(session, self.canvas)
        self.hbar = QScrollBar(Qt.Horizontal)
        lay.addWidget(self.toolbar)
        lay.addWidget(self.canvas, 1)
        lay.addWidget(self.hbar)
        self.hbar.valueChanged.connect(self._hbar)
        self.canvas.scrolled.connect(self._sync_bar)
        self.canvas.zoom_changed.connect(self._sync_bar)
        session.project_changed.connect(lambda *_: self._sync_bar())

    def _hbar(self, v: int) -> None:
        self.canvas.x_off = float(v)
        self.canvas.update()

    def _sync_bar(self) -> None:
        span = max(0, self.canvas.content_width() - (self.canvas.width() - HEAD_W))
        self.hbar.blockSignals(True)
        self.hbar.setRange(0, span)
        self.hbar.setPageStep(max(1, self.canvas.width() - HEAD_W))
        self.hbar.setValue(int(self.canvas.x_off))
        self.hbar.blockSignals(False)
