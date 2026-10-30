"""Right panel: project 'Détails' when nothing is selected, clip properties otherwise."""
from __future__ import annotations

import dataclasses

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (QCheckBox, QColorDialog, QDoubleSpinBox, QFrame, QGridLayout, QHBoxLayout, QLabel,
                               QPlainTextEdit, QPushButton, QScrollArea, QSlider, QStackedWidget, QVBoxLayout,
                               QWidget)

from ..core.editor import EditError
from ..core.model import CANVAS_RATIOS, MaterialKind, Segment, TrackKind
from .session import Session
from .theme import C


class SliderSpin(QWidget):
    """Slider + spin box pair. ``changed(value)`` fires for user edits only."""
    changed = Signal(float)

    def __init__(self, lo: float, hi: float, step: float = 1.0, decimals: int = 0, suffix: str = "", slider: bool = True):
        super().__init__()
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(8)
        self.scale = 10 ** decimals
        self.sl = QSlider(Qt.Horizontal)
        self.sl.setRange(int(lo * self.scale), int(hi * self.scale))
        self.sp = QDoubleSpinBox()
        self.sp.setRange(lo, hi)
        self.sp.setDecimals(decimals)
        self.sp.setSingleStep(step)
        self.sp.setSuffix(suffix)
        self.sp.setFixedWidth(72)
        self.sp.setAlignment(Qt.AlignCenter)
        if slider:
            lay.addWidget(self.sl, 1)
        else:
            self.sl.hide()
            lay.addStretch(1)
        lay.addWidget(self.sp)
        self.sl.valueChanged.connect(lambda v: self._from_slider(v))
        self.sp.valueChanged.connect(self._from_spin)

    def _from_slider(self, v: int) -> None:
        self.sp.blockSignals(True)
        self.sp.setValue(v / self.scale)
        self.sp.blockSignals(False)
        self.changed.emit(v / self.scale)

    def _from_spin(self, v: float) -> None:
        self.sl.blockSignals(True)
        self.sl.setValue(int(round(v * self.scale)))
        self.sl.blockSignals(False)
        self.changed.emit(v)

    def set(self, v: float) -> None:
        for w in (self.sl, self.sp):
            w.blockSignals(True)
        self.sp.setValue(v)
        self.sl.setValue(int(round(v * self.scale)))
        for w in (self.sl, self.sp):
            w.blockSignals(False)


def label(text: str, muted: bool = True) -> QLabel:
    l = QLabel(text)
    l.setStyleSheet(f"color:{C.muted if muted else C.text};")
    return l


class DetailsPage(QWidget):
    """'Détails' of the project (matches CapCut's right panel with nothing selected)."""

    def __init__(self, session: Session, edit_cb) -> None:
        super().__init__()
        self.s = session
        lay = QVBoxLayout(self)
        lay.setContentsMargins(12, 14, 12, 0)
        lay.setSpacing(0)
        self.grid = QGridLayout()
        self.grid.setHorizontalSpacing(18)
        self.grid.setVerticalSpacing(14)
        self.grid.setColumnMinimumWidth(0, 130)
        self.grid.setColumnStretch(1, 1)
        lay.addLayout(self.grid)
        lay.addStretch(1)
        foot = QHBoxLayout()
        foot.setContentsMargins(0, 0, 0, 10)
        foot.addStretch(1)
        mod = QPushButton("Modifier")
        mod.setStyleSheet(f"QPushButton{{background:{C.button};border-radius:4px;padding:5px 16px;}}")
        mod.clicked.connect(edit_cb)
        foot.addWidget(mod)
        lay.addLayout(foot)
        session.project_changed.connect(lambda *_: self.refresh())
        self.refresh()

    def refresh(self) -> None:
        while self.grid.count():
            it = self.grid.takeAt(0)
            w = it.widget()
            if w:
                w.hide()
                w.setParent(None)
                w.deleteLater()
        p = self.s.project
        rows = [("Nom :", p.name), ("Parcours :", p.path or "(pas encore enregistré)"),
                ("Virgule flottante", "Désactivé"), ("Fichier multimédia importé :", "Conserver à l'emplacement d'origine"),
                ("Organiser les calques", "Activé"), ("Proxy :", "Désactivé"), None,
                ("Format :", "Originale" if p.ratio == "original" else p.ratio),
                ("Résolution :", "Adaptée"), ("Fréquence d'images :", f"{p.fps:.2f}fps")]
        r = 0
        for row in rows:
            if row is None:
                line = QFrame()
                line.setFixedHeight(1)
                line.setStyleSheet(f"background:{C.line};")
                self.grid.addWidget(line, r, 0, 1, 2)
                r += 1
                continue
            k, v = row
            lk, lv = label(k), QLabel(v)
            lv.setWordWrap(True)
            lv.setTextInteractionFlags(Qt.TextSelectableByMouse)
            self.grid.addWidget(lk, r, 0, Qt.AlignTop)
            self.grid.addWidget(lv, r, 1, Qt.AlignTop)
            r += 1


class ClipPage(QWidget):
    """Basic properties of the selected clip (transform, opacity, volume, speed, adjustments, text)."""

    def __init__(self, session: Session) -> None:
        super().__init__()
        self.s = session
        self.seg: Segment | None = None
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        self.tabs = QHBoxLayout()
        self.tabs.setContentsMargins(12, 8, 12, 0)
        self.tabs.setSpacing(18)
        outer.addLayout(self.tabs)
        sep = QFrame()
        sep.setFixedHeight(1)
        sep.setStyleSheet(f"background:{C.line};")
        outer.addWidget(sep)
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.NoFrame)
        self.scroll.setStyleSheet("QScrollArea{background:transparent;border:none;}")
        self.scroll.viewport().setAutoFillBackground(False)
        outer.addWidget(self.scroll, 1)
        self.tab_names: list[str] = []
        self.cur_tab = 0

    # -- building -----------------------------------------------------------------
    def bind(self, seg: Segment, kind: TrackKind) -> None:
        self.seg = seg
        self.kind = kind
        if kind == TrackKind.TEXT:
            self.tab_names = ["Texte", "Animation", "Suivi", "Voix off"]
        elif kind == TrackKind.AUDIO:
            self.tab_names = ["Audio", "Vitesse"]
        else:
            self.tab_names = ["Vidéo", "Audio", "Vitesse", "Animation", "Ajustement"]
        self.cur_tab = min(self.cur_tab, len(self.tab_names) - 1)
        self._build_tabs()
        self._build_body()

    def _build_tabs(self) -> None:
        while self.tabs.count():
            w = self.tabs.takeAt(0).widget()
            if w:
                w.hide()
                w.setParent(None)
                w.deleteLater()
        for i, n in enumerate(self.tab_names):
            b = QPushButton(n)
            b.setCursor(Qt.PointingHandCursor)
            on = i == self.cur_tab
            b.setStyleSheet(f"QPushButton{{background:transparent;border:none;border-bottom:2px solid "
                            f"{C.accent if on else 'transparent'};padding:6px 0 8px 0;color:{C.text if on else C.muted};font-size:12px;}}")
            b.clicked.connect(lambda _=False, i=i: self._switch(i))
            self.tabs.addWidget(b)
        self.tabs.addStretch(1)

    def _switch(self, i: int) -> None:
        self.cur_tab = i
        self._build_tabs()
        self._build_body()

    def _build_body(self) -> None:
        name = self.tab_names[self.cur_tab]
        body = QWidget()
        body.setObjectName("clipBody")
        body.setStyleSheet("#clipBody{background:transparent;}")
        lay = QVBoxLayout(body)
        lay.setContentsMargins(14, 12, 14, 12)
        lay.setSpacing(12)
        self._rows: dict[str, SliderSpin] = {}
        seg = self.seg
        if name == "Texte":
            self._text_section(lay)
            self._transform_section(lay, title=False)
        elif name == "Vidéo":
            self._transform_section(lay)
        elif name == "Audio":
            self._audio_section(lay)
        elif name == "Vitesse":
            self._speed_section(lay)
        elif name == "Ajustement":
            self._adjust_section(lay)
        else:
            n = QLabel(f"« {name} » n'est pas encore disponible dans PyCut")
            n.setStyleSheet(f"color:{C.muted};")
            n.setWordWrap(True)
            lay.addWidget(n)
        lay.addStretch(1)
        self.scroll.setWidget(body)

    def _title(self, lay, text: str) -> None:
        t = QLabel(text)
        t.setStyleSheet("font-size:13px;font-weight:600;")
        lay.addWidget(t)

    def _row(self, lay, text: str, widget: QWidget) -> None:
        row = QHBoxLayout()
        l = label(text)
        l.setFixedWidth(88)
        row.addWidget(l)
        row.addWidget(widget, 1)
        lay.addLayout(row)

    def _slider_row(self, lay, key: str, text: str, lo, hi, step, dec, suffix, value, apply, slider=True) -> SliderSpin:
        w = SliderSpin(lo, hi, step, dec, suffix, slider)
        w.set(value)
        w.changed.connect(apply)
        self._row(lay, text, w)
        self._rows[key] = w
        return w

    # -- sections -----------------------------------------------------------------
    def _upd(self, **kw) -> None:
        if self.seg is None:
            return
        try:
            self.s.editor.update(self.seg.id, merge=True, **kw)
        except EditError as ex:
            self.s.toast(str(ex))

    def _transform_section(self, lay, title: bool = True) -> None:
        seg, pr = self.seg, self.s.project
        tf = seg.transform
        if title:
            self._title(lay, "Basique")
        self._title_small(lay, "Position et taille")
        self._slider_row(lay, "scale", "Échelle", 1, 500, 1, 0, "%", tf.scale_x * 100,
                         lambda v: self._set_scale(v / 100), True)
        uni = QCheckBox("Échelle uniforme")
        uni.setChecked(tf.uniform_scale)
        uni.toggled.connect(lambda on: self._upd(transform=dataclasses.replace(self.seg.transform, uniform_scale=on,
                                                                               scale_y=self.seg.transform.scale_x)))
        lay.addWidget(uni)
        w, h = pr.width, pr.height
        self._slider_row(lay, "x", "Position X", -w, w, 1, 0, "", tf.x * w / 2,
                         lambda v: self._upd(transform=dataclasses.replace(self.seg.transform, x=v * 2 / w)), False)
        self._slider_row(lay, "y", "Position Y", -h, h, 1, 0, "", tf.y * h / 2,
                         lambda v: self._upd(transform=dataclasses.replace(self.seg.transform, y=v * 2 / h)), False)
        self._slider_row(lay, "rot", "Rotation", -360, 360, 1, 0, "°", tf.rotation,
                         lambda v: self._upd(transform=dataclasses.replace(self.seg.transform, rotation=v)))
        self._title_small(lay, "Mélange")
        self._slider_row(lay, "alpha", "Opacité", 0, 100, 1, 0, "%", tf.alpha * 100,
                         lambda v: self._upd(transform=dataclasses.replace(self.seg.transform, alpha=v / 100)))
        flips = QHBoxLayout()
        for text, attr in (("Miroir ↔", "flip_h"), ("Miroir ↕", "flip_v")):
            b = QPushButton(text)
            b.setCheckable(True)
            b.setChecked(getattr(tf, attr))
            b.toggled.connect(lambda on, a=attr: self._upd(transform=dataclasses.replace(self.seg.transform, **{a: on})))
            flips.addWidget(b)
        lay.addLayout(flips)

    def _title_small(self, lay, text: str) -> None:
        t = QLabel(text)
        t.setStyleSheet(f"color:{C.text};font-size:12px;margin-top:6px;")
        lay.addWidget(t)

    def _set_scale(self, v: float) -> None:
        tf = self.seg.transform
        self._upd(transform=dataclasses.replace(tf, scale_x=v, scale_y=v if tf.uniform_scale else tf.scale_y))

    def _audio_section(self, lay) -> None:
        a = self.seg.audio
        self._title(lay, "Basique")
        self._slider_row(lay, "vol", "Volume", 0, 200, 1, 0, "%", a.volume * 100,
                         lambda v: self._upd(audio=dataclasses.replace(self.seg.audio, volume=v / 100)))
        self._slider_row(lay, "fi", "Fondu entrant", 0, 10, 0.1, 1, "s", a.fade_in / 1e6,
                         lambda v: self._upd(audio=dataclasses.replace(self.seg.audio, fade_in=int(v * 1e6))))
        self._slider_row(lay, "fo", "Fondu sortant", 0, 10, 0.1, 1, "s", a.fade_out / 1e6,
                         lambda v: self._upd(audio=dataclasses.replace(self.seg.audio, fade_out=int(v * 1e6))))
        mute = QCheckBox("Muet")
        mute.setChecked(a.muted)
        mute.toggled.connect(lambda on: self._upd(audio=dataclasses.replace(self.seg.audio, muted=on)))
        lay.addWidget(mute)

    def _speed_section(self, lay) -> None:
        seg = self.seg
        self._title(lay, "Standard")
        w = self._slider_row(lay, "speed", "Vitesse", 0.1, 10, 0.1, 1, "x", seg.speed.speed,
                             self._set_speed)
        presets = QHBoxLayout()
        for v in (0.5, 1.0, 1.5, 2.0, 4.0):
            b = QPushButton(f"{v:g}x")
            b.clicked.connect(lambda _=False, v=v: self._set_speed(v, refresh=True))
            presets.addWidget(b)
        lay.addLayout(presets)
        rev = QCheckBox("Inverser")
        rev.setChecked(seg.reverse)
        rev.toggled.connect(lambda _: self.s.editor.toggle_reverse(self.seg.id))
        lay.addWidget(rev)

    def _set_speed(self, v: float, refresh: bool = False) -> None:
        try:
            self.s.editor.set_speed(self.seg.id, max(0.1, v))
        except EditError as ex:
            self.s.toast(str(ex))

    def _adjust_section(self, lay) -> None:
        adj = self.seg.adjust
        self._title(lay, "Basique")
        for key, text in (("brightness", "Luminosité"), ("contrast", "Contraste"), ("saturation", "Saturation")):
            self._slider_row(lay, key, text, -100, 100, 1, 0, "", getattr(adj, key),
                             lambda v, k=key: self._upd(adjust=dataclasses.replace(self.seg.adjust, **{k: v})))
        reset = QPushButton("Réinitialiser")
        reset.clicked.connect(lambda: (self._upd(adjust=dataclasses.replace(self.seg.adjust, brightness=0, contrast=0,
                                                                            saturation=0)), self._build_body()))
        lay.addWidget(reset)

    def _text_section(self, lay) -> None:
        ts = self.seg.text
        self._title(lay, "Basique")
        ed = QPlainTextEdit(ts.text)
        ed.setFixedHeight(70)
        ed.textChanged.connect(lambda: self._set_text(ed.toPlainText()))
        lay.addWidget(ed)
        self._slider_row(lay, "size", "Taille", 1, 100, 1, 0, "", ts.size,
                         lambda v: self._upd(text=dataclasses.replace(self.seg.text, size=v)))
        row = QHBoxLayout()
        cb = QPushButton("Couleur")
        cb.setStyleSheet(f"QPushButton{{background:{ts.color};color:#000;border-radius:4px;padding:4px 12px;}}")
        cb.clicked.connect(self._pick_color)
        row.addWidget(cb)
        for text, attr in (("G", "bold"), ("I", "italic"), ("S", "underline")):
            b = QPushButton(text)
            b.setCheckable(True)
            b.setFixedWidth(34)
            b.setChecked(getattr(ts, attr))
            b.toggled.connect(lambda on, a=attr: self._upd(text=dataclasses.replace(self.seg.text, **{a: on})))
            row.addWidget(b)
        lay.addLayout(row)
        al = QHBoxLayout()
        for i, text in enumerate(("Gauche", "Centre", "Droite")):
            b = QPushButton(text)
            b.setCheckable(True)
            b.setChecked(ts.align == i)
            b.clicked.connect(lambda _=False, i=i: (self._upd(text=dataclasses.replace(self.seg.text, align=i)), self._build_body()))
            al.addWidget(b)
        lay.addLayout(al)
        self._slider_row(lay, "ls", "Espacement", -10, 50, 1, 0, "", ts.letter_spacing,
                         lambda v: self._upd(text=dataclasses.replace(self.seg.text, letter_spacing=v)))
        self._slider_row(lay, "stroke", "Contour", 0, 1, 0.05, 2, "", ts.stroke_width,
                         lambda v: self._upd(text=dataclasses.replace(self.seg.text, stroke_width=v)))
        sh = QCheckBox("Ombre")
        sh.setChecked(ts.shadow.enabled)
        sh.toggled.connect(lambda on: self._upd(text=dataclasses.replace(
            self.seg.text, shadow=dataclasses.replace(self.seg.text.shadow, enabled=on))))
        lay.addWidget(sh)
        self._slider_row(lay, "bg", "Arrière-plan", 0, 100, 1, 0, "%", ts.background_alpha * 100,
                         lambda v: self._upd(text=dataclasses.replace(self.seg.text, background_alpha=v / 100)))

    def _set_text(self, s: str) -> None:
        if self.seg and s != self.seg.text.text:
            self._upd(text=dataclasses.replace(self.seg.text, text=s), name=s[:40])

    def _pick_color(self) -> None:
        c = QColorDialog.getColor(QColor(self.seg.text.color), self, "Couleur du texte")
        if c.isValid():
            self._upd(text=dataclasses.replace(self.seg.text, color=c.name().upper()))
            self._build_body()


class InspectorPanel(QWidget):
    def __init__(self, session: Session, edit_project_cb, parent=None) -> None:
        super().__init__(parent)
        self.s = session
        self.setObjectName("inspector")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setStyleSheet(f"#inspector{{background:{C.panel};border-radius:4px;}}")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        head = QWidget()
        head.setFixedHeight(41)
        head.setAttribute(Qt.WA_StyledBackground, True)
        head.setStyleSheet(f"background:{C.header};border-top-left-radius:4px;border-top-right-radius:4px;")
        hl = QHBoxLayout(head)
        hl.setContentsMargins(12, 0, 12, 0)
        self.title = QLabel("Détails")
        self.title.setStyleSheet(f"color:{C.accent if False else C.text};font-size:13px;")
        hl.addWidget(self.title)
        lay.addWidget(head)
        self.stack = QStackedWidget()
        self.details = DetailsPage(session, edit_project_cb)
        self.clip = ClipPage(session)
        self.stack.addWidget(self.details)
        self.stack.addWidget(self.clip)
        lay.addWidget(self.stack, 1)
        session.selection_changed.connect(self.sync)
        session.project_changed.connect(self._on_project)
        self._last_sid: str | None = None
        self.sync()

    def _on_project(self, label: str) -> None:
        # rebuild only when the structure changed, not while a slider is being dragged
        if label not in ("update", "keyframe"):
            self.sync(force=True)
        elif self.clip.seg is not None:
            f = self.s.project.find_segment(self.clip.seg.id)
            if f:
                self.clip.seg = f[1]

    def sync(self, force: bool = False) -> None:
        segs = self.s.selected_segments()
        if len(segs) != 1:
            self.title.setText("Détails" if not segs else f"{len(segs)} clips sélectionnés")
            self.stack.setCurrentIndex(0)
            self._last_sid = None
            return
        seg = segs[0]
        tr = self.s.project.track_of(seg)
        self.title.setText({"text": "Texte", "audio": "Audio"}.get(tr.kind.value, "Vidéo"))
        if seg.id != self._last_sid or force:
            self.clip.bind(seg, tr.kind)
            self._last_sid = seg.id
        self.stack.setCurrentIndex(1)
