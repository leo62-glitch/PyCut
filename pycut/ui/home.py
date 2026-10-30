"""Home screen: sidebar, 'Créer un projet' banner, tool cards and the project grid."""
from __future__ import annotations

import os
import time
from pathlib import Path

from PySide6.QtCore import QRect, QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QFont, QLinearGradient, QPainter, QPainterPath, QPixmap
from PySide6.QtWidgets import (QFrame, QHBoxLayout, QLabel, QLineEdit, QListWidget, QListWidgetItem, QMenu,
                               QMessageBox, QPushButton, QScrollArea, QStyle, QStyledItemDelegate, QToolButton, QVBoxLayout,
                               QWidget)

from ..core.timebase import format_timecode
from . import icons, library
from .theme import C


def H(c: str) -> QColor:
    return QColor(c)


class Banner(QFrame):
    clicked = Signal()

    def __init__(self) -> None:
        super().__init__()
        self.setFixedHeight(144)
        self.setCursor(Qt.PointingHandCursor)

    def paintEvent(self, e) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        g = QLinearGradient(0, 0, self.width(), 0)
        g.setColorAt(0, H(C.h_a1))
        g.setColorAt(0.45, H("#13BDDC"))
        g.setColorAt(1, H(C.h_a2))
        path = QPainterPath()
        path.addRoundedRect(QRectF(self.rect()), 8, 8)
        p.fillPath(path, g)
        cx, cy = self.width() / 2, self.height() / 2 + 6
        p.setBrush(H("#061E22"))
        p.setPen(Qt.NoPen)
        p.drawRoundedRect(QRectF(cx - 134, cy - 14, 28, 28), 6, 6)
        p.drawPixmap(int(cx - 128), int(cy - 8), icons.pixmap("plus", "#FFFFFF", 16, 2.6))
        f = QFont(self.font())
        f.setPixelSize(24)
        f.setBold(True)
        p.setFont(f)
        p.setPen(H("#061E22"))
        p.drawText(QRect(int(cx - 94), int(cy - 20), 300, 40), Qt.AlignLeft | Qt.AlignVCenter, "Créer un projet")

    def mousePressEvent(self, e) -> None:
        self.clicked.emit()


class ToolCard(QFrame):
    def __init__(self, icon: str, title: str, sub: str, on_click) -> None:
        super().__init__()
        self.setFixedHeight(136)
        self.setCursor(Qt.PointingHandCursor)
        self.setStyleSheet(f"ToolCard{{background:{C.h_card};border-radius:8px;}} ToolCard:hover{{background:#13262A;}}")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(12, 12, 12, 12)
        lay.setSpacing(2)
        tile = QLabel()
        tile.setFixedSize(44, 44)
        tile.setAlignment(Qt.AlignCenter)
        tile.setPixmap(icons.pixmap(icon, "#E8F4F5", 22))
        tile.setStyleSheet(f"background:{C.h_tile};border-radius:8px;")
        lay.addWidget(tile)
        lay.addStretch(1)
        t = QLabel(title)
        t.setStyleSheet("font-size:13px;font-weight:600;")
        s = QLabel(sub)
        s.setStyleSheet(f"font-size:12px;color:{C.h_muted};")
        lay.addWidget(t)
        lay.addWidget(s)
        self._cb = on_click

    def mousePressEvent(self, e) -> None:
        self._cb()


class AssistCard(QFrame):
    def __init__(self, on_click) -> None:
        super().__init__()
        self.setFixedHeight(136)
        self._cb = on_click
        lay = QVBoxLayout(self)
        lay.setContentsMargins(16, 12, 16, 12)
        top = QHBoxLayout()
        ic = QLabel()
        ic.setPixmap(icons.pixmap("sparkle", "#3DE0F0", 18))
        top.addWidget(ic)
        top.addWidget(QLabel("EditPilot"))
        top.addStretch(1)
        lay.addLayout(top)
        q = QLabel("Comment puis-je t'aider à éditer aujourd'hui ?")
        q.setStyleSheet("font-size:16px;font-weight:700;font-style:italic;")
        lay.addWidget(q)
        inp = QLineEdit()
        inp.setPlaceholderText("Décris ce que tu souhaitais éditer")
        inp.setStyleSheet(f"QLineEdit{{background:{C.h_input};border-radius:6px;padding:9px 10px;color:#fff;}}")
        inp.returnPressed.connect(on_click)
        lay.addWidget(inp)

    def paintEvent(self, e) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        g = QLinearGradient(0, 0, self.width(), self.height())
        g.setColorAt(0, H("#17616F"))
        g.setColorAt(1, H("#034C5A"))
        path = QPainterPath()
        path.addRoundedRect(QRectF(self.rect()), 8, 8)
        p.fillPath(path, g)


class CardDelegate(QStyledItemDelegate):
    W, H_ = 146, 196

    def sizeHint(self, option, index) -> QSize:
        return QSize(self.W, self.H_)

    def paint(self, p: QPainter, option, index) -> None:
        e: library.Entry = index.data(Qt.UserRole)
        p.save()
        p.setRenderHint(QPainter.Antialiasing)
        r = option.rect
        cover = QRectF(r.left() + 4, r.top() + 4, 124, 124)
        path = QPainterPath()
        path.addRoundedRect(cover, 4, 4)
        p.fillPath(path, H("#090909"))
        pm: QPixmap | None = index.data(Qt.DecorationRole)
        if pm and not pm.isNull():
            p.setClipPath(path)
            sc = pm.scaled(124, 124, Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation)
            p.drawPixmap(int(cover.left() + (124 - sc.width()) / 2), int(cover.top() + (124 - sc.height()) / 2), sc)
            p.setClipping(False)
        if option.state & (QStyle.State_MouseOver | QStyle.State_Selected):
            p.setPen(H(C.h_a2))
            p.setBrush(Qt.NoBrush)
            p.drawRoundedRect(cover, 4, 4)
        if e.source == "capcut":
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(0, 0, 0, 170))
            p.drawRoundedRect(QRectF(cover.right() - 50, cover.top() + 5, 45, 15), 3, 3)
            f = p.font(); f.setPixelSize(9); f.setBold(True); p.setFont(f)
            p.setPen(H("#CFEFF2"))
            p.drawText(QRectF(cover.right() - 50, cover.top() + 5, 45, 15), Qt.AlignCenter, "CapCut")
        f = p.font(); f.setPixelSize(12); f.setBold(True); p.setFont(f)
        p.setPen(H("#F2F7F8"))
        fm = p.fontMetrics()
        p.drawText(r.left() + 4, r.top() + 146, fm.elidedText(e.name, Qt.ElideRight, 124))
        f.setBold(False); f.setPixelSize(11); p.setFont(f)
        p.setPen(H(C.h_muted))
        dur = format_timecode(e.duration_us, 30, show_frames=False, show_hours=e.duration_us >= 3_600_000_000)
        p.drawText(r.left() + 4, r.top() + 164, f"{library.human_size(e.size_bytes)} | {dur}")
        p.restore()


class HomeWindow(QWidget):
    create = Signal()
    open_entry = Signal(object)
    unavailable = Signal(str)

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("PyCut")
        self.resize(1400, 820)
        self.setMinimumSize(1000, 600)
        self.setObjectName("home")
        self.setStyleSheet(f"#home{{background:{C.h_bg};}} QLabel{{color:#EAF3F4;}}")
        self.setAttribute(Qt.WA_StyledBackground, True)
        root = QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        root.addWidget(self._sidebar())
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.NoFrame)
        self.scroll.setStyleSheet("QScrollArea{background:transparent;} QScrollBar:vertical{width:8px;}")
        self.scroll.viewport().setAutoFillBackground(False)
        body = QWidget()
        body.setObjectName("homebody")
        body.setStyleSheet("#homebody{background:transparent;}")
        bl = QVBoxLayout(body)
        bl.setContentsMargins(24, 44, 56, 24)
        bl.setSpacing(20)
        ban = Banner()
        ban.clicked.connect(self.create)
        bl.addWidget(ban)
        cards = QHBoxLayout()
        cards.setSpacing(20)
        na = lambda: self.unavailable.emit("Les fonctions IA ne sont pas disponibles dans PyCut")
        cards.addWidget(AssistCard(na), 38)
        for ic, t, s in (("image", "Image IA", "Transforme tes idées en images"),
                         ("fit", "Étends la vidéo", "Prolonge n'importe quel clip en toute fluidité"),
                         ("edit", "Édition par l'IA", "Édite les clips en les décrivant")):
            cards.addWidget(ToolCard(ic, t, s, na), 40)
        bl.addLayout(cards)
        bl.addSpacing(30)
        head = QHBoxLayout()
        t = QLabel("Projets")
        t.setStyleSheet("font-size:14px;font-weight:700;")
        head.addWidget(t)
        head.addStretch(1)
        self.search = QLineEdit()
        self.search.setPlaceholderText("Rechercher")
        self.search.setFixedWidth(180)
        self.search.setStyleSheet(f"QLineEdit{{background:{C.h_card};border-radius:6px;padding:5px 8px;}}")
        self.search.textChanged.connect(lambda *_: self.reload())
        head.addWidget(self.search)
        bl.addLayout(head)
        self.list = QListWidget()
        self.list.setViewMode(QListWidget.IconMode)
        self.list.setResizeMode(QListWidget.Adjust)
        self.list.setMovement(QListWidget.Static)
        self.list.setFrameShape(QFrame.NoFrame)
        self.list.setSpacing(0)
        self.list.setUniformItemSizes(True)
        self.list.setMouseTracking(True)
        self.list.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.list.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.list.setItemDelegate(CardDelegate())
        self.list.setStyleSheet("QListWidget{background:transparent;} QListWidget::item{background:transparent;}")
        self.list.itemClicked.connect(lambda it: self.open_entry.emit(it.data(Qt.UserRole)))
        self.list.setContextMenuPolicy(Qt.CustomContextMenu)
        self.list.customContextMenuRequested.connect(self._menu)
        bl.addWidget(self.list)
        self.empty = QLabel("Aucun projet pour le moment. Clique sur « Créer un projet ».")
        self.empty.setStyleSheet(f"color:{C.h_muted};padding:20px 0;")
        bl.addWidget(self.empty)
        bl.addStretch(1)
        self.scroll.setWidget(body)
        root.addWidget(self.scroll, 1)
        self.reload()

    def _sidebar(self) -> QWidget:
        sb = QWidget()
        sb.setFixedWidth(216)
        lay = QVBoxLayout(sb)
        lay.setContentsMargins(20, 14, 20, 16)
        lay.setSpacing(4)
        brand = QHBoxLayout()
        lg = QLabel()
        lg.setPixmap(icons.pixmap("logo", "#8AA0A3", 16))
        bt = QLabel("PyCut")
        bt.setStyleSheet(f"color:{C.h_muted};font-weight:700;font-size:13px;")
        brand.addWidget(lg)
        brand.addWidget(bt)
        brand.addStretch(1)
        lay.addLayout(brand)
        lay.addSpacing(8)
        card = QFrame()
        card.setStyleSheet(f"QFrame{{background:{C.h_user};border-radius:8px;}}")
        cl = QVBoxLayout(card)
        cl.setContentsMargins(10, 10, 10, 10)
        row = QHBoxLayout()
        av = QLabel()
        av.setFixedSize(32, 32)
        av.setAlignment(Qt.AlignCenter)
        av.setPixmap(icons.pixmap("avatar", "#9FB4B7", 18))
        av.setStyleSheet(f"background:{C.h_tile};border-radius:16px;")
        nm = QLabel("Espace local")
        nm.setStyleSheet("font-weight:600;background:transparent;")
        row.addWidget(av)
        row.addWidget(nm)
        row.addStretch(1)
        cl.addLayout(row)
        sub = QLabel("Tes projets restent sur cet ordinateur")
        sub.setWordWrap(True)
        sub.setStyleSheet(f"color:{C.h_muted};font-size:11px;background:transparent;")
        cl.addWidget(sub)
        lay.addWidget(card)
        lay.addSpacing(18)

        def item(icon, text, active=False, indent=0, cb=None, muted=False):
            b = QPushButton("  " + text)
            b.setIcon(icons.icon(icon, "#EAF3F4", 16))
            b.setFixedHeight(32)
            bg = C.h_nav if active else "transparent"
            b.setStyleSheet(f"QPushButton{{background:{bg};border-radius:6px;text-align:left;padding-left:{10 + indent}px;"
                            f"font-weight:500;font-size:12px;}} QPushButton:hover{{background:{C.h_nav};}}")
            b.clicked.connect(cb or (lambda: self.unavailable.emit("Pas encore disponible dans PyCut")))
            lay.addWidget(b)

        def section(text):
            lay.addSpacing(10)
            line = QFrame(); line.setFixedHeight(1); line.setStyleSheet(f"background:{C.h_line};")
            lay.addWidget(line)
            lay.addSpacing(8)
            l = QLabel(text)
            l.setStyleSheet(f"color:{C.h_muted};font-size:11px;")
            lay.addWidget(l)

        item("home", "Accueil", True, cb=lambda: self.scroll.verticalScrollBar().setValue(0))
        item("templates", "Modèles")
        section("Créer avec l'IA")
        item("video_studio", "Studio de vidéos")
        item("design", "Studio de conceptions")
        item("tools", "Autres outils")
        item("sparkle", "Créer avec l'IA", indent=24)
        item("marketing", "Outils marketing", indent=24)
        section("Gestion")
        item("library", "Bibliothèque", cb=lambda: self.scroll.verticalScrollBar().setValue(10_000))
        lay.addStretch(1)
        return sb

    def reload(self) -> None:
        q = self.search.text().strip().lower() if hasattr(self, "search") else ""
        self.list.clear()
        entries = [e for e in library.list_all() if q in e.name.lower()]
        for e in entries:
            it = QListWidgetItem()
            it.setData(Qt.UserRole, e)
            if e.cover and Path(e.cover).is_file():
                it.setData(Qt.DecorationRole, QPixmap(e.cover))
            it.setSizeHint(QSize(CardDelegate.W, CardDelegate.H_))
            self.list.addItem(it)
        self.empty.setVisible(not entries)
        self.list.setVisible(bool(entries))
        self._fit_list()

    def _fit_list(self) -> None:
        n = self.list.count()
        cols = max(1, (self.list.viewport().width() or self.width() - 300) // CardDelegate.W)
        rows = -(-n // cols) if n else 0
        self.list.setFixedHeight(rows * CardDelegate.H_ + 8)

    def resizeEvent(self, e) -> None:
        super().resizeEvent(e)
        self._fit_list()

    def showEvent(self, e) -> None:
        super().showEvent(e)
        self.reload()

    def _menu(self, pos) -> None:
        it = self.list.itemAt(pos)
        if not it:
            return
        e: library.Entry = it.data(Qt.UserRole)
        m = QMenu(self)
        m.addAction("Ouvrir", lambda: self.open_entry.emit(e))
        if e.source == "pycut":
            m.addAction("Supprimer", lambda: self._delete(e))
        m.addAction("Afficher dans le dossier", lambda: self._reveal(e))
        m.exec(self.list.mapToGlobal(pos))

    def _delete(self, e: library.Entry) -> None:
        if QMessageBox.question(self, "Supprimer", f"Supprimer définitivement « {e.name} » ?") == QMessageBox.Yes:
            library.delete_project(e.path)
            self.reload()

    def _reveal(self, e: library.Entry) -> None:
        from PySide6.QtCore import QUrl
        from PySide6.QtGui import QDesktopServices
        QDesktopServices.openUrl(QUrl.fromLocalFile(e.path))
