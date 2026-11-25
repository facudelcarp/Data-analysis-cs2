"""Vista: análisis de una demo."""
from __future__ import annotations

import time

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (QComboBox, QFrame, QHBoxLayout, QLabel, QPushButton, QStackedWidget, QVBoxLayout,
                               QWidget)

from ..maps import pretty_map
from ..parser import DemoData
from . import micro_tab, replay_view, review_tab, single_tabs
from . import widgets as w
from .page import LazyTabs, empty_state


def _micro(d: DemoData) -> QWidget:
    return micro_tab.build(d.duels.assign(demo_id=d.demo_id), d.shots, dict(zip(d.players["steamid"], d.players["name"], strict=True)),
                           d.meta.get("visibility", ""), team_of=dict(zip(d.players["steamid"], d.players["team"],
                                                                          strict=True)))


# (título, función que arma la página, va dentro de un scroll)
TABS = [
    ("Scoreboard", single_tabs.scoreboard, True),
    ("🎬 Replay 2D", replay_view.build, False),
    ("Ronda a ronda", single_tabs.rounds, True),
    ("Economía", single_tabs.economy, True),
    ("Jugador", single_tabs.player, True),
    ("Revisión de muertes", review_tab.single, True),
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
        lay.setContentsMargins(24, 16, 24, 8)
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
        # Barra de revisión (lista de momentos a recorrer en el replay); la maneja la ventana
        self.review_bar = QFrame()
        self.review_bar.setObjectName("ReviewBar")
        self.review_bar.setStyleSheet("QFrame#ReviewBar { background: rgba(240,163,61,0.10); border: 1px solid "
                                      "rgba(240,163,61,0.45); border-radius: 8px; } QFrame#ReviewBar QLabel "
                                      "{ border: none; background: transparent; }")
        rb = QHBoxLayout(self.review_bar)
        rb.setContentsMargins(12, 6, 8, 6)
        self.review_text = QLabel()
        self.review_text.setWordWrap(True)
        self.review_prev, self.review_next = QPushButton("◀ Anterior"), QPushButton("Siguiente ▶")
        self.review_next.setObjectName("Primary")
        self.review_close = QPushButton("Terminar")
        self.review_close.setFlat(True)
        rb.addWidget(self.review_text, 1)
        for b in (self.review_prev, self.review_next, self.review_close):
            rb.addWidget(b)
        self.review_bar.hide()
        lay.addWidget(self.review_bar)
        self.body = QStackedWidget()
        self._empty = empty_state(self)
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

    def goto_replay(self, demo_id: str, rnd: int, t: float | None = None) -> bool:
        idx = self.picker.findData(demo_id)
        if idx < 0:
            return False
        self.picker.setCurrentIndex(idx)  # arma (o reusa) la página de esa demo
        tabs: LazyTabs = self._pages[demo_id].tabs
        i = next(i for i, (title, *_) in enumerate(TABS) if "Replay" in title)
        tabs.setCurrentIndex(i)
        panel = tabs.widget(i).findChild(replay_view.ReplayPanel)
        return bool(panel and panel.goto(rnd, t))

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
