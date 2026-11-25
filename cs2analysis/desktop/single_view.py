"""Vista: análisis de una demo."""
from __future__ import annotations

import time

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QComboBox, QHBoxLayout, QLabel, QStackedWidget, QVBoxLayout, QWidget

from ..maps import pretty_map
from ..parser import DemoData
from . import micro_tab, replay_view, single_tabs
from . import widgets as w
from .page import LazyTabs


def _micro(d: DemoData) -> QWidget:
    return micro_tab.build(d.duels, d.shots, dict(zip(d.players["steamid"], d.players["name"], strict=True)),
                           d.meta.get("visibility", ""), team_of=dict(zip(d.players["steamid"], d.players["team"],
                                                                          strict=True)))


# (título, función que arma la página, va dentro de un scroll)
TABS = [
    ("Scoreboard", single_tabs.scoreboard, True),
    ("🎬 Replay 2D", replay_view.build, False),
    ("Ronda a ronda", single_tabs.rounds, True),
    ("Economía", single_tabs.economy, True),
    ("Jugador", single_tabs.player, True),
    ("Duelos", single_tabs.duels, True),
    ("Aim / micro", _micro, True),
    ("Utilidad", single_tabs.utility, True),
    ("Tácticas", single_tabs.tactics_page, True),
    ("Mapa", single_tabs.map_page, True),
]


class SingleDemoView(QWidget):
    rendered = Signal(str, float)  # demo_id, segundos que tardó en armarse

    def __init__(self, parent=None):
        super().__init__(parent)
        self._demos: dict[str, DemoData] = {}
        self._pages: dict[str, QWidget] = {}  # vista ya armada por demo: volver a una demo es instantáneo
        lay = QVBoxLayout(self)
        lay.setContentsMargins(22, 16, 22, 10)
        lay.setSpacing(10)
        lay.addWidget(w.label("Demo individual", "PageTitle"))
        lay.addWidget(w.label("Una partida a fondo: quién rindió, cómo se dio cada ronda y por qué.", "PageSubtitle"))
        top = QHBoxLayout()
        top.addWidget(QLabel("Partida"))
        self.picker = QComboBox()
        self.picker.setMinimumWidth(420)
        self.picker.currentIndexChanged.connect(self._on_pick)
        top.addWidget(self.picker, 1)
        top.addStretch()
        lay.addLayout(top)
        # Una página por demo, todas montadas: cambiar de demo es solo cambiar cuál se ve (sin rearmar layouts)
        self.body = QStackedWidget()
        self._empty = w.label("Abrí una o más demos (.dem) o un análisis guardado (.cs2a) con «Abrir demos…» o "
                              "«Abrir carpeta…».", "Empty", wrap=True)
        self._empty.setAlignment(Qt.AlignCenter)
        self.body.addWidget(self._empty)
        lay.addWidget(self.body, 1)

    # ------------------------------------------------------------------ estado
    def set_demos(self, demos: dict[str, DemoData], select: str | None = None) -> None:
        current = select or self.picker.currentData()
        self._demos = demos
        for gone in set(self._pages) - set(demos):  # demos que salieron de la sesión
            page = self._pages.pop(gone)
            self.body.removeWidget(page)
            page.deleteLater()
        ordered = sorted(demos.values(), key=lambda d: d.meta.get("file_mtime", ""), reverse=True)
        self.picker.blockSignals(True)
        self.picker.clear()
        for d in ordered:
            m = d.meta
            self.picker.addItem(f"{pretty_map(m['map'])} · {m['score_a']}-{m['score_b']} · "
                                f"{str(m.get('file_mtime', ''))[:10]} · {m['file_name']}", d.demo_id)
        idx = self.picker.findData(current)
        self.picker.setCurrentIndex(idx if idx >= 0 else 0)
        self.picker.blockSignals(False)
        self._on_pick()

    def _on_pick(self) -> None:
        demo_id = self.picker.currentData()
        if demo_id not in self._demos:
            self.body.setCurrentWidget(self._empty)
            return
        t0 = time.perf_counter()
        page = self._pages.get(demo_id)
        if page is None:
            page = self._pages[demo_id] = self._build(self._demos[demo_id])
            self.body.addWidget(page)
        self.body.setCurrentWidget(page)
        self.rendered.emit(demo_id, time.perf_counter() - t0)

    def reset_pages(self) -> None:
        """Descarta las páginas armadas (p. ej. después de bajar los radares) y vuelve a armar la actual."""
        for page in self._pages.values():
            self.body.removeWidget(page)
            page.deleteLater()
        self._pages.clear()
        self._on_pick()

    def _build(self, d: DemoData) -> QWidget:
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(w.match_banner(d.meta, pretty_map(d.meta["map"])))
        tabs = LazyTabs()
        for title, factory, scroll in TABS:
            tabs.add_lazy(lambda f=factory: f(d), title, scroll)
        lay.addWidget(tabs, 1)
        page.tabs = tabs
        return page
