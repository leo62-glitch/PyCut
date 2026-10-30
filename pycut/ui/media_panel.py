"""Left panel: tab strip (Multimédia, Son, Texte, ...) + side navigation + media library."""
from __future__ import annotations

from PySide6.QtCore import QMimeData, QSize, Qt, Signal
from PySide6.QtGui import QDrag, QFont, QPainter, QPixmap
from PySide6.QtWidgets import (QAbstractItemView, QFileDialog, QFrame, QHBoxLayout, QLabel, QListWidget,
                               QListWidgetItem, QPushButton, QStackedWidget, QToolButton, QVBoxLayout, QWidget)

from ..core.editor import EditError
from ..core.model import MaterialKind
from ..core.probe import MEDIA_FILTER, kind_of, probe
from ..core.timebase import US, format_timecode
from . import icons
from .session import Session
from .theme import C
from .timeline import MIME_MATERIAL

TABS = [("multimedia", "Multimédia"), ("sound", "Son"), ("text", "Texte"), ("sticker", "Stickers"),
        ("effects", "Effets"), ("transitions", "Transitions"), ("captions", "Légendes"), ("filters", "Filtres"),
        ("adjust", "Ajustement"), ("models", "Modèles"), ("avatar", "Avatar IA")]


class MediaList(QListWidget):
    def __init__(self, session: Session, thumbs, audio_only: bool = False, parent=None) -> None:
        super().__init__(parent)
        self.s, self.thumbs, self.audio_only = session, thumbs, audio_only
        self.setViewMode(QListWidget.IconMode)
        self.setIconSize(QSize(112, 112))
        self.setGridSize(QSize(124, 150))
        self.setResizeMode(QListWidget.Adjust)
        self.setMovement(QListWidget.Static)
        self.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.setDragEnabled(True)
        self.setAcceptDrops(True)
        self.setWordWrap(True)
        self.setSpacing(2)
        self.setFrameShape(QFrame.NoFrame)
        self.setStyleSheet(f"QListWidget{{background:transparent;}} QListWidget::item{{color:{C.text};border-radius:4px;}}"
                           f"QListWidget::item:selected{{background:{C.raised};}} QListWidget::item:hover{{background:#303030;}}")
        self.itemDoubleClicked.connect(lambda it: self.add_to_timeline([it]))
        session.project_changed.connect(lambda *_: self.reload())
        self.reload()

    def reload(self) -> None:
        sel = {i.data(Qt.UserRole) for i in self.selectedItems()}
        self.clear()
        for m in self.s.project.materials.values():
            if m.kind == MaterialKind.TEXT or (self.audio_only and m.kind != MaterialKind.AUDIO):
                continue
            used = any(seg.material_id == m.id for _, seg in self.s.project.iter_segments())
            it = QListWidgetItem(self._icon(m, used), m.name)
            it.setData(Qt.UserRole, m.id)
            it.setToolTip(f"{m.name}\n{format_timecode(m.duration, self.s.fps(), show_frames=False, show_hours=False)}"
                          f"  {m.width}×{m.height}" if m.width else m.name)
            self.addItem(it)
            if m.id in sel:
                it.setSelected(True)

    def _icon(self, m, used: bool):
        pm = QPixmap(112, 112)
        pm.fill(Qt.transparent)
        p = QPainter(pm)
        p.setRenderHint(QPainter.Antialiasing)
        p.setPen(Qt.NoPen)
        p.setBrush(Qt.black if m.kind != MaterialKind.AUDIO else Qt.GlobalColor.transparent)
        p.setBrush(__import__("PySide6.QtGui", fromlist=["QColor"]).QColor("#1E1E1E"))
        p.drawRoundedRect(0, 0, 112, 112, 4, 4)
        t = self.thumbs.get(m)
        if t is not None:
            sc = t.scaled(112, 112, Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation)
            p.setClipRect(0, 0, 112, 112)
            p.drawPixmap((112 - sc.width()) // 2, (112 - sc.height()) // 2, sc)
            p.setClipping(False)
        elif m.kind == MaterialKind.AUDIO:
            p.drawPixmap(40, 40, icons.pixmap("audio", "#7FE3EA", 32))
        if m.kind != MaterialKind.PHOTO:
            f = p.font(); f.setPixelSize(10); p.setFont(f)
            tc = format_timecode(m.duration, 30, show_frames=False, show_hours=False)
            p.setBrush(__import__("PySide6.QtGui", fromlist=["QColor"]).QColor(0, 0, 0, 150))
            p.drawRoundedRect(112 - 42, 112 - 18, 38, 14, 3, 3)
            p.setPen(Qt.white)
            p.drawText(112 - 42, 112 - 18, 38, 14, Qt.AlignCenter, tc)
        if used:
            p.setPen(Qt.NoPen)
            p.setBrush(__import__("PySide6.QtGui", fromlist=["QColor"]).QColor(C.accent))
            p.drawEllipse(100, 4, 8, 8)
        p.end()
        return icons.QIcon(pm)

    def selected_ids(self) -> list[str]:
        return [i.data(Qt.UserRole) for i in self.selectedItems()]

    def add_to_timeline(self, items) -> None:
        ed = self.s.editor
        try:
            for it in items:
                mid = it.data(Qt.UserRole)
                m = ed.project.materials[mid]
                if m.kind == MaterialKind.AUDIO:
                    ed.add_segment(mid, start=self.s.playhead)
                else:
                    ed.add_segment(mid)
        except EditError as ex:
            self.s.toast(str(ex))

    def startDrag(self, actions) -> None:
        ids = self.selected_ids()
        if not ids:
            return
        md = QMimeData()
        md.setData(MIME_MATERIAL, ",".join(ids).encode())
        d = QDrag(self)
        d.setMimeData(md)
        it = self.selectedItems()[0]
        d.setPixmap(it.icon().pixmap(72, 72))
        d.exec(Qt.CopyAction)


def import_files(session: Session, paths: list[str]) -> int:
    n = 0
    for path in paths:
        if not kind_of(path):
            continue
        m = probe(path)
        if m is not None:
            session.editor.import_material(m)
            n += 1
    if n == 0 and paths:
        session.toast("Format de fichier non pris en charge")
    return n


def pick_and_import(session: Session, parent=None) -> None:
    paths, _ = QFileDialog.getOpenFileNames(parent, "Importer", "", MEDIA_FILTER + ";;Tous les fichiers (*)")
    if paths:
        import_files(session, paths)


class DropZone(QFrame):
    clicked = Signal()
    dropped = Signal(list)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setAcceptDrops(True)
        self.setCursor(Qt.PointingHandCursor)
        self.setStyleSheet(f"DropZone{{background:{C.raised};border-radius:6px;}}")
        lay = QVBoxLayout(self)
        lay.setAlignment(Qt.AlignCenter)
        row = QHBoxLayout()
        row.setAlignment(Qt.AlignCenter)
        dot = QLabel()
        dot.setFixedSize(20, 20)
        dot.setPixmap(icons.pixmap("plus", "#04282B", 12, 2.4))
        dot.setAlignment(Qt.AlignCenter)
        dot.setStyleSheet(f"background:{C.accent};border-radius:10px;")
        t = QLabel("Importer")
        t.setStyleSheet("font-size:14px;font-weight:600;")
        row.addWidget(dot)
        row.addWidget(t)
        lay.addLayout(row)
        h = QLabel("Fais glisser des vidéos, photos et fichiers audio et dépose-les ici")
        h.setStyleSheet(f"color:{C.muted};font-size:11px;")
        h.setAlignment(Qt.AlignCenter)
        lay.addWidget(h)

    def mousePressEvent(self, e) -> None:
        self.clicked.emit()

    def dragEnterEvent(self, e) -> None:
        if e.mimeData().hasUrls():
            e.acceptProposedAction()

    def dropEvent(self, e) -> None:
        self.dropped.emit([u.toLocalFile() for u in e.mimeData().urls()])


class SideNav(QWidget):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setFixedWidth(121)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(8, 10, 5, 8)
        lay.setSpacing(8)

        def head(text, chevron=None, active=False, badge=False):
            b = QPushButton(text)
            b.setFixedHeight(24)
            col = C.accent if active else C.text
            b.setStyleSheet(f"QPushButton{{background:{C.raised};color:{col};text-align:left;padding:0 8px;"
                            f"border-radius:4px;font-size:11px;}} QPushButton:hover{{background:#444;}}")
            if chevron:
                b.setIcon(icons.icon(chevron, col, 12))
                b.setLayoutDirection(Qt.RightToLeft)
                b.setStyleSheet(b.styleSheet().replace("text-align:left", "text-align:left"))
            return b

        def sub(text, active=False):
            b = QPushButton(text)
            b.setFixedHeight(24)
            col = C.accent if active else C.text
            bg = C.raised if active else "transparent"
            b.setStyleSheet(f"QPushButton{{background:{bg};color:{col};text-align:left;padding:0 8px;border-radius:4px;"
                            f"font-size:11px;}} QPushButton:hover{{background:#303030;}}")
            return b

        lay.addWidget(head("Importer", "chevron_up", True))
        for i, t in enumerate(("Fichiers multimé…", "Chronologie", "Sous-projets")):
            lay.addWidget(sub(t, i == 0))
        for t in ("Les tiennes", "Générer", "Espaces", "Bibliothèque"):
            lay.addWidget(head(t, "chevron_down"))
        lay.addStretch(1)


class MediaPanel(QWidget):
    """Whole left panel including its tab strip."""

    def __init__(self, session: Session, thumbs, parent=None) -> None:
        super().__init__(parent)
        self.s = session
        self.setObjectName("mediaPanel")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setStyleSheet(f"#mediaPanel{{background:{C.panel};border-radius:4px;}}")
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        strip = QWidget()
        strip.setFixedHeight(41)
        strip.setAttribute(Qt.WA_StyledBackground, True)
        strip.setStyleSheet(f"background:{C.header};border-top-left-radius:4px;border-top-right-radius:4px;")
        sl = QHBoxLayout(strip)
        sl.setContentsMargins(4, 0, 4, 0)
        sl.setSpacing(0)
        self.tab_btns: list[QToolButton] = []
        for i, (ic, label) in enumerate(TABS):
            b = QToolButton()
            b.setText(label)
            b.setToolButtonStyle(Qt.ToolButtonTextUnderIcon)
            b.setIconSize(QSize(18, 18))
            b.setFixedSize(52 if len(label) < 9 else 58, 40)
            b.setCursor(Qt.PointingHandCursor)
            b.clicked.connect(lambda _=False, i=i: self.set_tab(i))
            self.tab_btns.append(b)
            sl.addWidget(b)
        sl.addStretch(1)
        root.addWidget(strip)
        self.stack = QStackedWidget()
        root.addWidget(self.stack, 1)
        self.lib = self._library_page(thumbs, audio=False)
        self.snd = self._library_page(thumbs, audio=True)
        self.stack.addWidget(self.lib)
        self.stack.addWidget(self.snd)
        self.stack.addWidget(self._text_page())
        self.stack.addWidget(self._soon_page())
        self.set_tab(0)

    def set_tab(self, i: int) -> None:
        for j, b in enumerate(self.tab_btns):
            ic = TABS[j][0]
            col = C.accent if j == i else "#E1E1E1"
            b.setIcon(icons.icon(ic, col, 18))
            b.setStyleSheet(f"QToolButton{{border:none;background:transparent;color:{col};font-size:10px;}}"
                            f"QToolButton:hover{{color:{C.accent if j == i else '#FFFFFF'};}}")
        self.stack.setCurrentIndex({0: 0, 1: 1, 2: 2}.get(i, 3))
        self._soon_label.setText(f"« {TABS[i][1]} » n'est pas encore disponible dans PyCut") if i > 2 else None

    def _library_page(self, thumbs, audio: bool) -> QWidget:
        page = QWidget()
        lay = QHBoxLayout(page)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        if not audio:
            lay.addWidget(SideNav())
        body = QWidget()
        bl = QVBoxLayout(body)
        bl.setContentsMargins(10, 10, 12, 12)
        bl.setSpacing(10)
        st = QStackedWidget()
        zone = DropZone()
        zone.clicked.connect(lambda: pick_and_import(self.s, self))
        zone.dropped.connect(lambda p: import_files(self.s, p))
        empty = QWidget()
        el = QVBoxLayout(empty)
        el.setContentsMargins(0, 0, 0, 0)
        el.setSpacing(10)
        el.addWidget(zone, 1)
        hint = QLabel("— Tu n'as pas de fichier multimédia ? Crées-en un à l'aide de ces outils —")
        hint.setAlignment(Qt.AlignCenter)
        hint.setStyleSheet(f"color:{C.muted};font-size:11px;")
        el.addWidget(hint)
        tools = QHBoxLayout()
        tools.setSpacing(8)
        for ic, text in (("generate", "Générer"), ("avatar", "Avatars IA"), ("record", "Enregistrer")):
            b = QPushButton(text)
            b.setIcon(icons.icon(ic, "#E1E1E1", 20))
            b.setIconSize(QSize(20, 20))
            b.setFixedHeight(80)
            b.setStyleSheet(f"QPushButton{{background:{C.raised};border-radius:4px;padding-top:34px;}}"
                            f"QPushButton:hover{{background:#444;}}")
            b.clicked.connect(lambda _=False: self.s.toast("Cette fonction n'est pas encore disponible"))
            tools.addWidget(b)
        el.addLayout(tools)
        full = QWidget()
        fl = QVBoxLayout(full)
        fl.setContentsMargins(0, 0, 0, 0)
        fl.setSpacing(8)
        top = QHBoxLayout()
        imp = QPushButton("  Importer")
        imp.setIcon(icons.icon("plus", C.accent, 14))
        imp.setStyleSheet(f"QPushButton{{background:{C.raised};color:{C.accent};border-radius:4px;padding:4px 12px;}}")
        imp.clicked.connect(lambda: pick_and_import(self.s, self))
        top.addWidget(imp)
        top.addStretch(1)
        fl.addLayout(top)
        lst = MediaList(self.s, thumbs, audio_only=audio)
        fl.addWidget(lst, 1)
        st.addWidget(empty)
        st.addWidget(full)
        bl.addWidget(st)
        lay.addWidget(body, 1)

        def refresh(*_):
            has = any(m.kind != MaterialKind.TEXT and (not audio or m.kind == MaterialKind.AUDIO)
                      for m in self.s.project.materials.values())
            st.setCurrentIndex(1 if has else 0)
        self.s.project_changed.connect(refresh)
        refresh()
        page.setAcceptDrops(True)
        return page

    def _text_page(self) -> QWidget:
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setContentsMargins(14, 14, 14, 14)
        lay.setSpacing(10)
        b = QPushButton("+  Texte par défaut")
        b.setFixedHeight(64)
        b.setStyleSheet(f"QPushButton{{background:{C.raised};border-radius:6px;font-size:13px;}} QPushButton:hover{{background:#444;}}")
        b.clicked.connect(lambda: self.s.editor.add_text("Texte par défaut", self.s.playhead))
        lay.addWidget(b)
        n = QLabel("Clique pour ajouter un texte à la position de la tête de lecture, puis modifie-le dans le panneau de droite.")
        n.setWordWrap(True)
        n.setStyleSheet(f"color:{C.muted};")
        lay.addWidget(n)
        lay.addStretch(1)
        return page

    def _soon_page(self) -> QWidget:
        page = QWidget()
        lay = QVBoxLayout(page)
        self._soon_label = QLabel("")
        self._soon_label.setAlignment(Qt.AlignCenter)
        self._soon_label.setStyleSheet(f"color:{C.muted};font-size:13px;")
        lay.addWidget(self._soon_label)
        return page
