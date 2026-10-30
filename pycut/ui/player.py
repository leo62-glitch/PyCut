"""Centre panel: header, preview canvas rendered by the compositor, transport bar."""
from __future__ import annotations

from PySide6.QtCore import QRectF, QSize, Qt, QTimer
from PySide6.QtGui import QColor, QImage, QPainter
from PySide6.QtWidgets import QHBoxLayout, QLabel, QMenu, QPushButton, QToolButton, QVBoxLayout, QWidget

from ..core.model import CANVAS_RATIOS
from ..core.timebase import US, format_timecode
from ..render.preview import Compositor
from . import icons
from .session import Session
from .theme import C

QUALITY = {"Maximale": 1600, "Équilibrée": 960, "Rapide": 540}


class PreviewView(QWidget):
    def __init__(self, session: Session, parent=None) -> None:
        super().__init__(parent)
        self.s = session
        self.comp = Compositor()
        self.img: QImage | None = None
        self.quality = "Maximale"
        self.setMinimumSize(200, 120)
        self._pending = False
        session.playhead_changed.connect(self.refresh)
        session.project_changed.connect(lambda *_: self.refresh())

    def canvas_rect(self) -> QRectF:
        pr = self.s.project
        m = 14
        avail = QRectF(m, m, self.width() - 2 * m, self.height() - 2 * m)
        ar = pr.width / max(1, pr.height)
        w, h = avail.width(), avail.width() / ar
        if h > avail.height():
            h, w = avail.height(), avail.height() * ar
        return QRectF(avail.center().x() - w / 2, avail.center().y() - h / 2, w, h)

    def refresh(self, *_) -> None:
        if self._pending:
            return
        self._pending = True
        QTimer.singleShot(0, self._render)

    def _render(self) -> None:
        self._pending = False
        r = self.canvas_rect()
        if r.width() < 4:
            return
        cap = QUALITY[self.quality]
        k = min(1.0, cap / max(r.width(), r.height()))
        w, h = max(2, int(r.width() * k)), max(2, int(r.height() * k))
        self.img = self.comp.render(self.s.project, self.s.playhead, w, h)
        self.update()

    def paintEvent(self, e) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.SmoothPixmapTransform)
        p.fillRect(self.rect(), QColor(C.panel))
        r = self.canvas_rect()
        if self.img is not None:
            p.drawImage(r, self.img)
        else:
            p.fillRect(r, QColor("#000000"))
        p.setPen(QColor("#3A3A3A"))
        p.drawRect(r)

    def resizeEvent(self, e) -> None:
        self.refresh()


class PlayerPanel(QWidget):
    def __init__(self, session: Session, parent=None) -> None:
        super().__init__(parent)
        self.s = session
        self.setObjectName("playerPanel")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setStyleSheet(f"#playerPanel{{background:{C.panel};border-radius:4px;}}")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        head = QWidget()
        head.setFixedHeight(41)
        head.setAttribute(Qt.WA_StyledBackground, True)
        head.setStyleSheet(f"background:{C.header};border-top-left-radius:4px;border-top-right-radius:4px;")
        hl = QHBoxLayout(head)
        hl.setContentsMargins(12, 0, 12, 0)
        t = QLabel("Lecteur-Chronologie 01")
        t.setStyleSheet("font-size:13px;")
        hl.addWidget(t)
        hl.addStretch(1)
        mb = QToolButton()
        mb.setIcon(icons.icon("menu", "#8C8C8C", 16))
        mb.setStyleSheet("border:none;")
        hl.addWidget(mb)
        lay.addWidget(head)
        self.view = PreviewView(session)
        lay.addWidget(self.view, 1)
        bar = QWidget()
        bar.setFixedHeight(44)
        bl = QHBoxLayout(bar)
        bl.setContentsMargins(8, 0, 10, 0)
        self.time = QLabel()
        self.time.setMinimumWidth(190)
        self.time.setStyleSheet("font-family:Consolas,'DejaVu Sans Mono',monospace;font-size:11px;")
        bl.addWidget(self.time)
        bl.addStretch(1)
        self.play = QToolButton()
        self.play.setIconSize(QSize(18, 18))
        self.play.setStyleSheet("QToolButton{border:none;border-radius:4px;} QToolButton:hover{background:#3A3A3A;}")
        self.play.setFixedSize(34, 30)
        self.play.clicked.connect(session.toggle_play)
        bl.addWidget(self.play)
        bl.addStretch(1)
        self.q = QPushButton("Maximale")
        self.q.setStyleSheet(f"QPushButton{{background:transparent;border:1px solid #555;border-radius:2px;padding:1px 6px;"
                             f"font-size:10px;color:{C.muted};}} QPushButton:hover{{color:{C.text};}}")
        self.q.clicked.connect(self._quality_menu)
        bl.addWidget(self.q)
        self.ratio = QPushButton("Rapport")
        self.ratio.setStyleSheet(self.q.styleSheet())
        self.ratio.clicked.connect(self._ratio_menu)
        bl.addWidget(self.ratio)
        self.full = QToolButton()
        self.full.setIcon(icons.icon("fullscreen", "#BBBBBB", 16))
        self.full.setStyleSheet("border:none;")
        self.full.clicked.connect(lambda: self.s.toast("Plein écran : touche F11 sur la fenêtre"))
        bl.addWidget(self.full)
        lay.addWidget(bar)
        session.playhead_changed.connect(self._update_time)
        session.project_changed.connect(lambda *_: self._update_time())
        session.play_state_changed.connect(self._update_play)
        self._update_play(False)
        self._update_time()
        self._sync_labels()

    def _sync_labels(self) -> None:
        self.q.setText(self.view.quality)
        p = self.s.project
        self.ratio.setText("Rapport" if p.ratio == "original" else p.ratio)

    def _update_time(self, *_) -> None:
        fps = self.s.fps()
        cur = format_timecode(self.s.playhead, fps)
        tot = format_timecode(self.s.project.duration, fps)
        empty = self.s.project.duration == 0
        self.time.setText(f"<span style='color:{C.muted if empty else C.accent}'>{cur}</span>"
                          f" <span style='color:{C.muted}'>/ {tot}</span>")
        self._sync_labels()

    def _update_play(self, playing: bool) -> None:
        self.play.setIcon(icons.icon("pause" if playing else "play", "#E1E1E1", 18, fill=not playing))

    def _quality_menu(self) -> None:
        m = QMenu(self)
        for k in QUALITY:
            m.addAction(k, lambda k=k: (setattr(self.view, "quality", k), self._sync_labels(), self.view.refresh()))
        m.exec(self.q.mapToGlobal(self.q.rect().topLeft()) - self._menu_offset(m))

    def _ratio_menu(self) -> None:
        m = QMenu(self)
        for k in CANVAS_RATIOS:
            m.addAction("Originale" if k == "original" else k, lambda k=k: self.s.editor.set_ratio(k))
        m.exec(self.ratio.mapToGlobal(self.ratio.rect().topLeft()) - self._menu_offset(m))

    @staticmethod
    def _menu_offset(m: QMenu):
        from PySide6.QtCore import QPoint
        return QPoint(0, m.sizeHint().height())
