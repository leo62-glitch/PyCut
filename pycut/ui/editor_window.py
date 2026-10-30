"""Main editor window: top bar, media / player / inspector panels and the timeline."""
from __future__ import annotations

import os
import shutil
from pathlib import Path

from PySide6.QtCore import QSize, Qt, QTimer, Signal
from PySide6.QtGui import QAction, QCloseEvent, QKeySequence, QShortcut
from PySide6.QtWidgets import (QAbstractSpinBox, QApplication, QComboBox, QDialog, QFileDialog, QFormLayout,
                               QHBoxLayout, QLabel, QLineEdit, QMainWindow, QMenu, QMessageBox, QPlainTextEdit,
                               QProgressDialog, QPushButton, QSplitter, QToolButton, QVBoxLayout, QWidget)

from ..core.editor import EditError, Editor
from ..core.model import CANVAS_RATIOS, Project
from ..core.store import load_project, save_project
from ..core.timebase import US
from ..io.capcut import ExportOptions, export_draft, read_draft
from ..render.export import RESOLUTIONS, export_video
from ..render.preview import Compositor
from . import icons, library
from .inspector import InspectorPanel
from .media_panel import MediaPanel, import_files, pick_and_import
from .player import PlayerPanel
from .session import Session
from .theme import C
from .thumbs import ThumbCache
from .timeline import TimelinePanel


class ProjectSettingsDialog(QDialog):
    def __init__(self, project: Project, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Paramètres du projet")
        self.setMinimumWidth(340)
        f = QFormLayout(self)
        self.name = QLineEdit(project.name)
        self.ratio = QComboBox()
        self.ratio.addItems(list(CANVAS_RATIOS))
        self.ratio.setCurrentText(project.ratio)
        self.fps = QComboBox()
        self.fps.addItems(["24", "25", "30", "50", "60"])
        self.fps.setCurrentText(str(int(project.fps)))
        f.addRow("Nom", self.name)
        f.addRow("Format", self.ratio)
        f.addRow("Images/s", self.fps)
        row = QHBoxLayout()
        ok, no = QPushButton("OK"), QPushButton("Annuler")
        ok.setProperty("accent", True)
        ok.clicked.connect(self.accept)
        no.clicked.connect(self.reject)
        row.addStretch(1)
        row.addWidget(no)
        row.addWidget(ok)
        f.addRow(row)


class ExportDialog(QDialog):
    def __init__(self, project: Project, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Exporter")
        self.setMinimumWidth(460)
        f = QFormLayout(self)
        self.name = QLineEdit(project.name)
        self.folder = QLineEdit(str(Path.home() / "Videos"))
        b = QPushButton("…")
        b.setFixedWidth(34)
        b.clicked.connect(lambda: self.folder.setText(QFileDialog.getExistingDirectory(self, "Dossier", self.folder.text()) or self.folder.text()))
        row = QHBoxLayout()
        row.addWidget(self.folder, 1)
        row.addWidget(b)
        self.res = QComboBox()
        self.res.addItems(list(RESOLUTIONS))
        self.res.setCurrentText("1080p")
        self.fps = QComboBox()
        self.fps.addItems(["24", "25", "30", "50", "60"])
        self.fps.setCurrentText(str(int(project.fps)))
        f.addRow("Nom", self.name)
        f.addRow("Exporter vers", row)
        f.addRow("Résolution", self.res)
        f.addRow("Images/s", self.fps)
        note = QLabel("Format MP4. L'audio est ajouté si ffmpeg est installé.")
        note.setStyleSheet(f"color:{C.muted};")
        f.addRow(note)
        r2 = QHBoxLayout()
        ok, no = QPushButton("Exporter"), QPushButton("Annuler")
        ok.setProperty("accent", True)
        ok.clicked.connect(self.accept)
        no.clicked.connect(self.reject)
        r2.addStretch(1)
        r2.addWidget(no)
        r2.addWidget(ok)
        f.addRow(r2)

    def values(self):
        return (str(Path(self.folder.text()) / (self.name.text() or "PyCut")) + ".mp4",
                RESOLUTIONS[self.res.currentText()], float(self.fps.currentText()))


class Toast(QLabel):
    def __init__(self, parent) -> None:
        super().__init__(parent)
        self.setStyleSheet(f"background:{C.warn};color:#1A1A1A;border-radius:12px;padding:6px 14px;font-size:12px;")
        self.hide()
        self._t = QTimer(self, singleShot=True)
        self._t.timeout.connect(self.hide)

    def show_text(self, text: str) -> None:
        self.setText(text)
        self.adjustSize()
        p = self.parentWidget()
        self.move((p.width() - self.width()) // 2, p.height() - 90)
        self.show()
        self.raise_()
        self._t.start(2600)


class EditorWindow(QMainWindow):
    go_home = Signal()

    def __init__(self, project: Project | None = None, project_dir: str | None = None) -> None:
        super().__init__()
        self.editor = Editor(project or Project.new(library.default_project_name()))
        self.session = Session(self.editor)
        self.project_dir = project_dir
        self.thumbs = ThumbCache()
        self.resize(1400, 820)
        self.setMinimumSize(1000, 640)
        central = QWidget()
        central.setObjectName("central")
        central.setStyleSheet(f"#central{{background:{C.bg};}}")
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(9, 0, 8, 8)
        root.setSpacing(0)
        root.addWidget(self._top_bar())
        self.vsplit = QSplitter(Qt.Vertical)
        self.hsplit = QSplitter(Qt.Horizontal)
        for sp in (self.vsplit, self.hsplit):
            sp.setHandleWidth(6)
            sp.setChildrenCollapsible(False)
        self.media = MediaPanel(self.session, self.thumbs)
        self.player = PlayerPanel(self.session)
        self.inspector = InspectorPanel(self.session, self.edit_settings)
        self.timeline = TimelinePanel(self.session, self.thumbs.get)
        for w in (self.media, self.player, self.inspector):
            self.hsplit.addWidget(w)
        self.hsplit.setSizes([644, 641, 603])
        self.vsplit.addWidget(self.hsplit)
        self.vsplit.addWidget(self.timeline)
        self.vsplit.setSizes([529, 450])
        root.addWidget(self.vsplit, 1)
        self.toast = Toast(central)
        self.session.message.connect(self.toast.show_text)
        self.session.project_changed.connect(lambda *_: self._retitle())
        self._shortcuts()
        self._retitle()
        self.autosave = QTimer(self)
        self.autosave.timeout.connect(self._autosave)
        self.autosave.start(60_000)
        self.setAcceptDrops(True)

    # -- top bar ----------------------------------------------------------------
    def _top_bar(self) -> QWidget:
        bar = QWidget()
        bar.setFixedHeight(36)
        lay = QHBoxLayout(bar)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(8)
        logo = QLabel()
        logo.setPixmap(icons.pixmap("logo", C.text, 16))
        brand = QLabel("PyCut")
        brand.setStyleSheet("font-weight:700;font-size:13px;")
        lay.addWidget(logo)
        lay.addWidget(brand)
        menu = QPushButton("Menu")
        menu.setIcon(icons.icon("chevron_down", C.text, 10))
        menu.setLayoutDirection(Qt.RightToLeft)
        menu.setFixedHeight(20)
        menu.setStyleSheet(f"QPushButton{{background:{C.menu_btn};border-radius:3px;padding:0 8px;font-size:11px;font-weight:600;}}"
                           f"QPushButton:hover{{background:#444;}}")
        menu.clicked.connect(lambda: self._main_menu(menu))
        lay.addWidget(menu)
        lay.addStretch(1)
        self.title = QLabel("")
        self.title.setStyleSheet("font-size:12px;")
        lay.addWidget(self.title)
        lay.addStretch(1)
        share = QPushButton("  Partager")
        share.setIcon(icons.icon("share", C.text, 14))
        share.setFixedHeight(22)
        share.setStyleSheet(f"QPushButton{{background:{C.button};border-radius:3px;padding:0 10px;font-size:11px;font-weight:600;}}"
                            f"QPushButton:hover{{background:#5E5E5E;}}")
        share.clicked.connect(self._share_menu(share))
        exp = QPushButton("  Exporter")
        exp.setIcon(icons.icon("export", "#04282B", 14))
        exp.setFixedHeight(22)
        exp.setProperty("accent", True)
        exp.setStyleSheet(f"QPushButton{{background:{C.accent};color:#04282B;border-radius:3px;padding:0 10px;font-size:11px;font-weight:700;}}"
                          f"QPushButton:hover{{background:#20D2DD;}}")
        exp.clicked.connect(self.export_video_dialog)
        lay.addWidget(share)
        lay.addWidget(exp)
        return bar

    def _share_menu(self, anchor: QWidget):
        def show():
            m = QMenu(self)
            m.addAction("Exporter vers un brouillon CapCut…", self.export_capcut)
            m.exec(anchor.mapToGlobal(anchor.rect().bottomLeft()))
        return show

    def _main_menu(self, anchor: QWidget) -> None:
        m = QMenu(self)
        f = m.addMenu("Fichier")
        f.addAction("Nouveau projet", lambda: self.new_project()).setShortcut(QKeySequence("Ctrl+N"))
        f.addAction("Accueil", self._home)
        f.addSeparator()
        f.addAction("Importer des médias…", lambda: pick_and_import(self.session, self)).setShortcut(QKeySequence("Ctrl+I"))
        f.addAction("Importer un brouillon CapCut…", self.import_capcut)
        f.addSeparator()
        f.addAction("Enregistrer", self.save).setShortcut(QKeySequence("Ctrl+S"))
        f.addAction("Enregistrer sous…", lambda: self.save(as_new=True))
        f.addSeparator()
        f.addAction("Exporter la vidéo…", self.export_video_dialog).setShortcut(QKeySequence("Ctrl+E"))
        f.addAction("Exporter vers un brouillon CapCut…", self.export_capcut)
        f.addSeparator()
        f.addAction("Quitter", self.close)
        e = m.addMenu("Édition")
        e.addAction("Annuler", self.editor.undo).setShortcut(QKeySequence("Ctrl+Z"))
        e.addAction("Rétablir", self.editor.redo).setShortcut(QKeySequence("Ctrl+Shift+Z"))
        e.addSeparator()
        e.addAction("Copier", lambda: self.editor.copy(self.session.selection))
        e.addAction("Coller", lambda: self.editor.paste(self.session.playhead))
        e.addAction("Supprimer", lambda: self.editor.delete(self.session.selection))
        e.addAction("Diviser", lambda: self.timeline.canvas._split(self.session.selection))
        m.addAction("Paramètres du projet…", self.edit_settings)
        m.addSeparator()
        m.addAction("À propos de PyCut", lambda: QMessageBox.information(
            self, "PyCut", "PyCut — éditeur vidéo en Python, inspiré de CapCut.\nProjet indépendant, sans lien avec CapCut ni ByteDance."))
        m.exec(anchor.mapToGlobal(anchor.rect().bottomLeft()))

    # -- shortcuts ----------------------------------------------------------------
    def _shortcuts(self) -> None:
        s, ed, tl = self.session, self.editor, self.timeline

        def typing() -> bool:
            w = QApplication.focusWidget()
            return isinstance(w, (QLineEdit, QPlainTextEdit, QAbstractSpinBox)) or (isinstance(w, QComboBox) and w.isEditable())

        def bind(keys, fn, guard=True):
            for k in ([keys] if isinstance(keys, str) else keys):
                sc = QShortcut(QKeySequence(k), self)
                sc.setContext(Qt.WindowShortcut)
                sc.activated.connect(lambda fn=fn: (None if guard and typing() else fn()))

        bind("Space", s.toggle_play)
        bind("Ctrl+Z", ed.undo, guard=False)
        bind(["Ctrl+Shift+Z", "Ctrl+Y"], ed.redo, guard=False)
        bind("Ctrl+B", lambda: tl.canvas._split(s.selection))
        bind(["Delete", "Backspace"], lambda: ed.delete(s.selection))
        bind("Shift+Delete", lambda: ed.delete(s.selection, ripple=True))
        bind("Ctrl+C", lambda: ed.copy(s.selection))
        bind("Ctrl+V", lambda: ed.paste(s.playhead))
        bind("Ctrl+D", lambda: [ed.duplicate(i) for i in list(s.selection)])
        bind("Left", lambda: s.step_frames(-1))
        bind("Right", lambda: s.step_frames(1))
        bind("Home", lambda: s.set_playhead(0))
        bind("End", lambda: s.set_playhead(s.project.duration))
        bind("Q", lambda: tl.toolbar._quick_trim(True))
        bind("W", lambda: tl.toolbar._quick_trim(False))
        bind("S", lambda: tl.toolbar._toggle("snapping"))
        bind("M", lambda: ed.add_marker(s.playhead))
        bind("Ctrl+=", lambda: tl.canvas.set_zoom(tl.canvas.pps * 1.3))
        bind("Ctrl+-", lambda: tl.canvas.set_zoom(tl.canvas.pps / 1.3))
        bind("Shift+Z", tl.canvas.fit)
        bind("Ctrl+S", self.save, guard=False)
        bind("Ctrl+E", self.export_video_dialog, guard=False)
        bind("Ctrl+I", lambda: pick_and_import(s, self), guard=False)
        bind("F11", lambda: self.showNormal() if self.isFullScreen() else self.showFullScreen(), guard=False)

    # -- project lifecycle ----------------------------------------------------------------
    def _retitle(self) -> None:
        name = self.editor.project.name
        mark = " •" if self.session.dirty else ""
        self.title.setText(name + mark)
        self.setWindowTitle(f"{name}{mark} — PyCut")

    def edit_settings(self) -> None:
        d = ProjectSettingsDialog(self.editor.project, self)
        if d.exec():
            p = self.editor.project
            with self.editor._edit("settings"):
                p.name = d.name.text().strip() or p.name
                p.set_ratio(d.ratio.currentText())
                p.fps = float(d.fps.currentText())

    def new_project(self) -> None:
        if not self._confirm_discard():
            return
        self.project_dir = None
        self.editor.set_project(Project.new(library.default_project_name()))
        self.session.dirty = False
        self.session.set_playhead(0)
        self._retitle()

    def open_project(self, project: Project, folder: str | None) -> None:
        self.project_dir = folder
        self.editor.set_project(project)
        self.session.dirty = False
        self.session.selection = []
        self.session.set_playhead(0)
        self.timeline.canvas.fit()
        self._retitle()

    def save(self, as_new: bool = False) -> bool:
        p = self.editor.project
        if self.project_dir is None or as_new:
            name = library.unique_name(p.name) if as_new or not (library.projects_dir() / p.name).exists() else p.name
            if as_new:
                p.name = name
            self.project_dir = str(library.projects_dir() / (name if as_new else library.unique_name(p.name)))
        try:
            save_project(p, self.project_dir)
            cover = Compositor()
            img = cover.render(p, min(p.duration, 0), 320, int(320 * p.height / max(1, p.width)))
            img.save(str(Path(self.project_dir) / "cover.jpg"), "JPG", 85)
            cover.close()
        except OSError as ex:
            QMessageBox.warning(self, "Enregistrement", f"Impossible d'enregistrer : {ex}")
            return False
        self.session.dirty = False
        self._retitle()
        self.session.toast("Enregistré dans le projet")
        return True

    def _autosave(self) -> None:
        if self.session.dirty and self.project_dir:
            try:
                save_project(self.editor.project, self.project_dir)
                self.session.dirty = False
                self._retitle()
            except OSError:
                pass

    def _confirm_discard(self) -> bool:
        if not self.session.dirty:
            return True
        r = QMessageBox.question(self, "PyCut", "Enregistrer les modifications du projet ?",
                                 QMessageBox.Save | QMessageBox.Discard | QMessageBox.Cancel)
        if r == QMessageBox.Cancel:
            return False
        if r == QMessageBox.Save:
            return self.save()
        return True

    def _home(self) -> None:
        if self._confirm_discard():
            self.session.pause()
            self.go_home.emit()

    def closeEvent(self, e: QCloseEvent) -> None:
        if not self._confirm_discard():
            e.ignore()
            return
        self.session.pause()
        self.player.view.comp.close()
        e.accept()

    # -- import / export ----------------------------------------------------------------
    def dragEnterEvent(self, e) -> None:
        if e.mimeData().hasUrls():
            e.acceptProposedAction()

    def dropEvent(self, e) -> None:
        import_files(self.session, [u.toLocalFile() for u in e.mimeData().urls()])

    def import_capcut(self) -> None:
        d = QFileDialog.getExistingDirectory(self, "Dossier du brouillon CapCut", str(library.capcut_root()))
        if not d:
            return
        try:
            p = read_draft(d)
        except Exception as ex:
            QMessageBox.warning(self, "Import CapCut", f"Brouillon illisible : {ex}")
            return
        if self._confirm_discard():
            p.name = library.unique_name(p.name)
            self.open_project(p, None)
            self.session.dirty = True
            self._retitle()

    def export_capcut(self) -> None:
        root = QFileDialog.getExistingDirectory(self, "Dossier des brouillons CapCut (fermez CapCut avant)",
                                                str(library.capcut_root()))
        if not root:
            return
        try:
            folder, warns = export_draft(self.editor.project, root)
        except Exception as ex:
            QMessageBox.warning(self, "Export CapCut", f"Échec : {ex}")
            return
        msg = f"Brouillon écrit dans :\n{folder}\n\nRouvrez CapCut pour le voir dans vos projets."
        if warns:
            msg += "\n\nÉléments non exportés :\n• " + "\n• ".join(warns)
        QMessageBox.information(self, "Export CapCut", msg)

    def export_video_dialog(self) -> None:
        p = self.editor.project
        if p.duration <= 0:
            self.session.toast("Ajoute d'abord des clips à la chronologie")
            return
        d = ExportDialog(p, self)
        if not d.exec():
            return
        out, short, fps = d.values()
        Path(out).parent.mkdir(parents=True, exist_ok=True)
        self.session.pause()
        dlg = QProgressDialog("Exportation en cours…", "Annuler", 0, 100, self)
        dlg.setWindowModality(Qt.WindowModal)
        dlg.setMinimumDuration(0)

        def cb(frac: float) -> bool:
            dlg.setValue(int(frac * 100))
            QApplication.processEvents()
            return not dlg.wasCanceled()
        try:
            note = export_video(p, out, short, fps, cb)
        except Exception as ex:
            dlg.close()
            QMessageBox.warning(self, "Export", f"Échec : {ex}")
            return
        dlg.close()
        if note != "annulé":
            QMessageBox.information(self, "Export terminé", f"{out}\n\n{note}")
