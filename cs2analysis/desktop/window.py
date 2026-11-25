"""Ventana principal: barra lateral con las vistas y la carga de demos."""
from __future__ import annotations

from html import escape
from pathlib import Path

from PySide6.QtCore import QSize, QUrl
from PySide6.QtGui import QDesktopServices, QKeySequence
from PySide6.QtWidgets import (QFileDialog, QFrame, QListWidget, QListWidgetItem, QMainWindow, QMessageBox,
                               QProgressBar, QPushButton, QStackedWidget, QVBoxLayout, QWidget, QHBoxLayout)

from ..multi import find_demos
from ..parser import DemoData, is_demo
from ..parser import DEFAULT_CACHE_DIR
from .loader import Loader, run_in_background
from ..constants import TICKRATE
from .nav import navigator
from .library_views import DashboardView, MultiDemoView
from .raw_views import RawView, TranslatedView
from .single_view import SingleDemoView
from .team_view import TeamView
from . import icons
from . import widgets as w
from ..palette import ACCENT, MUTED, TEXT

# (nombre, ícono): el orden es el de las páginas del QStackedWidget
VIEWS = [("Demo individual", "demo"), ("Análisis de equipos", "team"), ("Multi-demo", "library"),
         ("Dashboard", "dashboard"), ("Datos traducidos", "translate"), ("Datos crudos", "raw")]


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("CS2 Data Analysis")
        self.setAcceptDrops(True)
        self.headless = False
        self.load_errors: list[str] = []
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
        self.library_views = [TeamView(), MultiDemoView(), DashboardView(), TranslatedView(), RawView()]
        for v in self.library_views:
            self.stack.addWidget(v)
        self.nav.currentRowChanged.connect(self.stack.setCurrentIndex)
        navigator().replay.connect(self.goto_replay)
        navigator().replay_tick.connect(self.goto_tick)
        navigator().demo.connect(self.open_demo)
        navigator().review.connect(self.start_review)
        self._review: list = []
        self._review_i = 0
        self._review_title = ""
        self.single.review_prev.clicked.connect(lambda: self._review_step(-1))
        self.single.review_next.clicked.connect(lambda: self._review_step(1))
        self.single.review_close.clicked.connect(self.stop_review)
        h.addWidget(self.stack, 1)
        self.setCentralWidget(root)

        self.progress = QProgressBar()
        self.progress.setMaximumWidth(260)
        self.progress.hide()
        self.statusBar().addPermanentWidget(self.progress)
        self._menus()
        from ..maps import RADAR_DIR
        if not any(RADAR_DIR.glob("de_*.png")):
            self.statusBar().showMessage("Sin imágenes de radar: Herramientas → Descargar radares (los mapas se dibujan "
                                         "igual, sobre la silueta de las posiciones).")

    def _sidebar(self) -> QWidget:
        side = QFrame()
        side.setObjectName("Sidebar")
        side.setFixedWidth(248)
        v = QVBoxLayout(side)
        v.setContentsMargins(0, 4, 0, 16)
        v.setSpacing(0)
        v.addWidget(w.label("CS2 · Data Analysis", "Brand"))
        v.addWidget(w.label("Análisis de demos para equipos y analistas", "BrandTag", wrap=True))
        v.addWidget(w.label("VISTAS", "NavLabel"))
        self.nav = QListWidget()
        self.nav.setObjectName("Nav")
        self.nav.setIconSize(QSize(18, 18))
        for name, ic in VIEWS:
            item = QListWidgetItem(icons.icon(ic, MUTED, active=ACCENT), name)
            item.setSizeHint(QSize(0, 38))  # el padding del QSS no se aplica a ítems con ícono
            self.nav.addItem(item)
        self.nav.setSpacing(1)
        self.nav.setCurrentRow(0)
        v.addWidget(self.nav, 1)
        box = QVBoxLayout()
        box.setContentsMargins(16, 0, 16, 0)
        box.setSpacing(8)
        for text, ic, slot, primary in (("Abrir demos…", "open", self.open_files, True),
                                        ("Abrir carpeta…", "folder", self.open_folder, False),
                                        ("Guardar sesión…", "save", self.save_session, False)):
            b = QPushButton(icons.icon(ic, "#14110c" if primary else TEXT), f"  {text}")
            b.setIconSize(QSize(16, 16))
            if primary:
                b.setObjectName("Primary")
            b.clicked.connect(slot)
            box.addWidget(b)
        clear = QPushButton(icons.icon("trash", MUTED), "  Vaciar sesión")
        clear.setIconSize(QSize(16, 16))
        clear.setFlat(True)
        clear.setStyleSheet(f"QPushButton {{ border: none; background: transparent; color: {MUTED}; text-align: left; }}"
                            f"QPushButton:hover {{ color: {TEXT}; }}")
        clear.clicked.connect(self.confirm_clear)
        box.addWidget(clear)
        self.count = w.label("", "SideCount")
        box.addWidget(self.count)
        v.addLayout(box)
        return side

    def confirm_clear(self) -> None:
        """Vaciar es destructivo: se confirma (salvo en el smoke test, donde no hay nadie para responder)."""
        if self.demos and not self.headless:
            r = QMessageBox.question(self, "Vaciar sesión", f"¿Sacar las {len(self.demos)} demos de la sesión? "
                                     "La caché en disco se conserva: volver a abrirlas es instantáneo.")
            if r != QMessageBox.Yes:
                return
        self.clear_session()

    def _menus(self) -> None:
        bar = self.menuBar()
        file_menu = bar.addMenu("&Archivo")
        for text, seq, slot in (("Abrir demos…", QKeySequence.Open, self.open_files),
                                ("Abrir carpeta…", "Ctrl+Shift+O", self.open_folder),
                                ("Guardar sesión (.cs2a)…", QKeySequence.Save, self.save_session),
                                (None, None, None),
                                ("Exportar Match Report (HTML)…", "Ctrl+R", self.export_report),
                                (None, None, None),
                                ("Vaciar sesión", None, self.confirm_clear),
                                ("Salir", QKeySequence.Quit, self.close)):
            if text is None:
                file_menu.addSeparator()
                continue
            a = file_menu.addAction(text, slot)
            if seq:
                a.setShortcut(QKeySequence(seq))
        tools = bar.addMenu("&Herramientas")
        tools.addAction("Descargar radares de los mapas", self.download_radars)
        tools.addAction("Descargar mallas de colisión (línea de visión real)", self.download_meshes)
        tools.addSeparator()
        tools.addAction("Abrir carpeta de caché", lambda: self._open_path(DEFAULT_CACHE_DIR))
        help_menu = bar.addMenu("A&yuda")
        help_menu.addAction("Atajos y uso", self.show_help)
        help_menu.addAction("Acerca de", lambda: QMessageBox.about(
            self, "CS2 Data Analysis", "<b>CS2 Data Analysis</b><br>Análisis de demos de Counter-Strike 2.<br>"
            "Parseo con demoparser2 · interfaz Qt (PySide6) · gráficos pyqtgraph."))

    # ------------------------------------------------------------------ herramientas
    def _open_path(self, path: Path) -> None:
        path.mkdir(parents=True, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))

    def _download(self, what: str, fn, after) -> None:
        self.statusBar().showMessage(f"Descargando {what}…")
        self.progress.setRange(0, 0)  # indeterminado
        self.progress.show()

        def done(result, error):
            self.progress.hide()
            if error:
                QMessageBox.warning(self, "No se pudo descargar", f"{what}: {error}")
                self.statusBar().clearMessage()
                return
            after(result)

        self._bg = run_in_background(self, fn, done)

    def download_radars(self) -> None:
        from ..maps import download_radars

        def after(files):
            self.statusBar().showMessage(f"{len(files)} radares descargados", 8000)
            self.single.reset_pages()  # los mapas se vuelven a dibujar con el radar de fondo
            for v in self.library_views:
                v.set_demos(self.demos)
        self._download("radares", download_radars, after)

    def download_meshes(self) -> None:
        from ..geometry import download_geometry

        def after(meshes):
            QMessageBox.information(self, "Mallas descargadas",
                                    f"{len(meshes)} mallas descargadas. Las demos ya analizadas sin malla se recalculan "
                                    "al volver a abrir el .dem (o vaciando la carpeta de caché).")
        self._download("mallas de colisión (~57 MB)", download_geometry, after)

    def export_report(self) -> None:
        d = self.demos.get(self.single.picker.currentData())
        if d is None:
            QMessageBox.information(self, "Match Report", "Abrí una demo primero.")
            return
        from ..report import generate_html_report
        path, _ = QFileDialog.getSaveFileName(self, "Guardar Match Report", f"report_{d.meta['file_name']}.html",
                                              "HTML (*.html)")
        if not path:
            return
        Path(path).write_text(generate_html_report(d), encoding="utf-8")
        QDesktopServices.openUrl(QUrl.fromLocalFile(path))
        self.statusBar().showMessage(f"Match Report guardado en {path}", 8000)

    def show_help(self) -> None:
        QMessageBox.information(self, "Atajos y uso", (
            "Ctrl+O  abrir demos · Ctrl+Shift+O  abrir carpeta · Ctrl+S  guardar sesión · Ctrl+R  Match Report\n\n"
            "Replay 2D: Espacio = play/pausa · ← → = 5 s · rueda = zoom · arrastrar = mover · "
            "doble clic = encuadre inicial · clic en un jugador = seguirlo · clic en el kill feed = ir a esa kill.\n\n"
            "Mapas: rueda = zoom, arrastrar = mover. Tablas: clic en un encabezado = ordenar; "
            "clic derecho = copiar o exportar a CSV/Parquet.\n\n"
            "También se puede arrastrar archivos .dem/.cs2a o carpetas a la ventana."))

    def closeEvent(self, e):  # noqa: N802 (API de Qt)
        from .loader import wait_all
        wait_all(10_000)  # no cerrar con un cálculo a mitad de camino
        nav = navigator()
        for sig, slot in ((nav.replay, self.goto_replay), (nav.replay_tick, self.goto_tick), (nav.demo, self.open_demo),
                          (nav.review, self.start_review)):
            try:
                sig.disconnect(slot)
            except (RuntimeError, TypeError):
                pass
        super().closeEvent(e)

    # ------------------------------------------------------------------ arrastrar y soltar
    def dragEnterEvent(self, e):  # noqa: N802 (API de Qt)
        if e.mimeData().hasUrls():
            e.acceptProposedAction()

    def dropEvent(self, e):  # noqa: N802
        paths = []
        for url in e.mimeData().urls():
            p = Path(url.toLocalFile())
            if p.is_dir():
                paths += find_demos(p)
            elif is_demo(p) or p.suffix.lower() == ".cs2a":
                paths.append(p)
        self.add_paths(paths)

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
        self.load_errors = list(errors)
        if errors and not self.headless:  # en --smoke-test no hay nadie para cerrar un diálogo
            QMessageBox.warning(self, "Algunas demos no se pudieron cargar", "\n".join(errors))

    def _refresh(self, select: str | None = None) -> None:
        self.count.setText(f"{len(self.demos)} demo(s) en la sesión" if self.demos else "Sin demos cargadas")
        self.single.set_demos(self.demos, select=select)
        for v in self.library_views:
            v.set_demos(self.demos)

    def goto_replay(self, demo_id: str, rnd: int, t=None) -> None:
        """Salto desde cualquier vista al replay de una ronda (clic en una ruta, un kill, una ronda...)."""
        if demo_id not in self.demos:
            return
        self.nav.setCurrentRow(0)
        if self.single.goto_replay(demo_id, rnd, t):
            when = "" if t is None else f", segundo {max(0, t):.0f}"
            self.statusBar().showMessage(f"Replay: ronda {rnd}{when}", 5000)

    def goto_tick(self, demo_id: str, rnd: int, tick: int) -> None:
        """Como goto_replay, desde un tick: arranca 3 s antes para ver cómo se llegó a ese momento."""
        d = self.demos.get(demo_id)
        if d is None:
            return
        r = d.rounds[d.rounds["round"] == rnd]
        t = (tick - int(r["freeze_end_tick"].iloc[0])) / TICKRATE - 3 if len(r) else None
        self.goto_replay(demo_id, rnd, t)

    def start_review(self, items: list, title: str) -> None:
        """Recorrer una lista de momentos (p. ej. muertes para revisar) en el replay, con Anterior / Siguiente."""
        self._review = [it for it in items if it[0] in self.demos]
        self._review_title = title
        self._review_i = 0
        if self._review:
            self._review_step(0)

    def stop_review(self) -> None:
        self._review = []
        self.single.review_bar.hide()

    def _review_step(self, delta: int) -> None:
        if not self._review:
            return
        self._review_i = max(0, min(len(self._review) - 1, self._review_i + delta))
        demo_id, rnd, t, text, *rest = self._review[self._review_i]
        self.single.review_text.setText(f"<b>{escape(self._review_title)}</b> · {self._review_i + 1} de "
                                        f"{len(self._review)} · {escape(text)}")
        self.single.review_prev.setEnabled(self._review_i > 0)
        self.single.review_next.setEnabled(self._review_i < len(self._review) - 1)
        self.single.review_bar.show()
        self.goto_replay(demo_id, rnd, t)
        if rest:  # a quién mirar: queda seleccionado en el replay
            from .replay_view import ReplayPanel
            panel = self.single.body.currentWidget().findChild(ReplayPanel)
            if panel is not None:
                panel.follow(rest[0])

    def open_demo(self, demo_id: str) -> None:
        if demo_id in self.demos:
            self.nav.setCurrentRow(0)
            self.single.picker.setCurrentIndex(self.single.picker.findData(demo_id))

    # ------------------------------------------------------------------ acciones
    def open_files(self) -> None:
        files, _ = QFileDialog.getOpenFileNames(self, "Abrir demos", "", "Demos y análisis (*.dem *.dem.gz *.dem.bz2 *.dem.zst *.dem.xz *.cs2a)")
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


