"""Ventana principal: barra lateral con las vistas y la carga de demos."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QAction, QKeySequence
from PySide6.QtWidgets import (QFileDialog, QFrame, QListWidget, QListWidgetItem, QMainWindow, QMessageBox,
                               QProgressBar, QPushButton, QStackedWidget, QVBoxLayout, QWidget, QHBoxLayout)

from ..multi import find_demos
from ..parser import DemoData
from .loader import Loader
from .single_view import SingleDemoView
from . import widgets as w

# Mismo orden que la app web; las que todavía no se migraron quedan deshabilitadas
VIEWS = ["🎯 Demo individual", "👥 Análisis de Equipos", "📚 Multi-demo", "📊 Dashboard",
         "🈯 Datos crudos traducidos", "🧾 Datos crudos"]
READY = {"🎯 Demo individual"}


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("CS2 Data Analysis")
        self.resize(1440, 900)
        self.demos: dict[str, DemoData] = {}
        self._seen: set[str] = set()
        self.loader = Loader(self)
        self.loader.progress.connect(self._on_progress)
        self.loader.finished.connect(self._on_loaded)

        root = QWidget()
        h = QHBoxLayout(root)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(0)
        h.addWidget(self._sidebar())
        self.stack = QStackedWidget()
        self.single = SingleDemoView()
        self.single.rendered.connect(lambda _id, s: self.statusBar().showMessage(f"Vista armada en {s * 1000:.0f} ms", 6000))
        self.stack.addWidget(self.single)
        h.addWidget(self.stack, 1)
        self.setCentralWidget(root)

        self.progress = QProgressBar()
        self.progress.setMaximumWidth(260)
        self.progress.hide()
        self.statusBar().addPermanentWidget(self.progress)
        self._shortcuts()

    def _sidebar(self) -> QWidget:
        side = QFrame()
        side.setObjectName("Sidebar")
        side.setFixedWidth(260)
        v = QVBoxLayout(side)
        v.setContentsMargins(0, 6, 0, 12)
        v.addWidget(w.label("CS2 · Data Analysis", "Brand"))
        v.addWidget(w.label("Análisis de demos: partidas, jugadores y equipos", "BrandTag", wrap=True))
        self.nav = QListWidget()
        self.nav.setObjectName("Nav")
        for name in VIEWS:
            item = QListWidgetItem(name)
            if name not in READY:
                item.setFlags(item.flags() & ~Qt.ItemIsEnabled)
                item.setToolTip("Todavía en migración: por ahora está en la app web (cs2a app).")
            self.nav.addItem(item)
        self.nav.setCurrentRow(0)
        v.addWidget(self.nav, 1)
        box = QVBoxLayout()
        box.setContentsMargins(12, 0, 12, 0)
        for text, slot, primary in (("Abrir demos…", self.open_files, True), ("Abrir carpeta…", self.open_folder, False),
                                    ("Guardar sesión (.cs2a)…", self.save_session, False),
                                    ("Vaciar sesión", self.clear_session, False)):
            b = QPushButton(text)
            if primary:
                b.setObjectName("Primary")
            b.clicked.connect(slot)
            box.addWidget(b)
        self.count = w.label("", "Muted")
        box.addWidget(self.count)
        v.addLayout(box)
        return side

    def _shortcuts(self) -> None:
        for seq, slot in ((QKeySequence.Open, self.open_files), (QKeySequence.Save, self.save_session)):
            a = QAction(self)
            a.setShortcut(seq)
            a.triggered.connect(slot)
            self.addAction(a)

    # ------------------------------------------------------------------ carga
    def add_paths(self, paths: list[Path]) -> None:
        new = [p for p in paths if str(p) not in self._seen]
        if not new:
            self.statusBar().showMessage("Esas demos ya están cargadas", 4000)
            return
        if self.loader.start(new):
            self._seen.update(str(p) for p in new)
            self.progress.setRange(0, len(new))
            self.progress.setValue(0)
            self.progress.show()
            self.statusBar().showMessage(f"Cargando {len(new)} archivo(s)…")

    def _on_progress(self, i: int, n: int) -> None:
        self.progress.setValue(i)
        self.statusBar().showMessage(f"Cargando {i}/{n}…")

    def _on_loaded(self, demos: list, errors: list, seconds: float) -> None:
        self.progress.hide()
        newest = None
        for d in demos:
            self.demos[d.demo_id] = d
            newest = d.demo_id
        self._refresh(select=newest)
        self.statusBar().showMessage(f"{len(demos)} demo(s) cargadas en {seconds:.1f} s", 8000)
        if errors:
            QMessageBox.warning(self, "Algunas demos no se pudieron cargar", "\n".join(errors))

    def _refresh(self, select: str | None = None) -> None:
        self.count.setText(f"📚 {len(self.demos)} demo(s) en la sesión" if self.demos else "")
        self.single.set_demos(self.demos, select=select)

    # ------------------------------------------------------------------ acciones
    def open_files(self) -> None:
        files, _ = QFileDialog.getOpenFileNames(self, "Abrir demos", "", "Demos y análisis (*.dem *.cs2a)")
        self.add_paths([Path(f) for f in files])

    def open_folder(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "Carpeta con demos (.dem / .cs2a)")
        if folder:
            found = find_demos(folder)
            if not found:
                QMessageBox.information(self, "Sin demos", "No se encontraron archivos .dem ni .cs2a en esa carpeta.")
            self.add_paths(found)

    def save_session(self) -> None:
        if not self.demos:
            return
        path, _ = QFileDialog.getSaveFileName(self, "Guardar sesión", "biblioteca.cs2a", "Análisis CS2 (*.cs2a)")
        if path:
            from ..storage import write_cs2a
            write_cs2a(path, list(self.demos.values()))
            self.statusBar().showMessage(f"Guardado en {path}", 6000)

    def clear_session(self) -> None:
        self.demos.clear()
        self._seen.clear()
        self._refresh()


