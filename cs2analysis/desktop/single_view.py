"""Vista: análisis de una demo."""
from __future__ import annotations

import time

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (QComboBox, QHBoxLayout, QLabel, QScrollArea, QStackedWidget, QTabWidget,
                               QVBoxLayout, QWidget)

from .. import stats
from ..highlights import match_highlights
from ..labels import RATING_NOTE, SCOREBOARD_COLS, TEAM_SIDE_LABELS, stat_table
from ..maps import pretty_map
from ..palette import TEAM_COLORS
from ..parser import DemoData
from . import widgets as w

# Pestañas de la app web que todavía no se migraron (se muestran deshabilitadas)
PENDING_TABS = ["🎬 Replay 2D", "Ronda a ronda", "Economía", "Jugador", "Duelos", "Aim / micro", "Utilidad",
                "Tácticas", "Mapa"]


def scrollable(content: QWidget) -> QScrollArea:
    area = QScrollArea()
    area.setWidgetResizable(True)
    area.setFrameShape(QScrollArea.NoFrame)
    area.setWidget(content)
    return area


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

    def _build(self, d: DemoData) -> QWidget:
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(w.match_banner(d.meta, pretty_map(d.meta["map"])))
        tabs = QTabWidget()
        tabs.addTab(scrollable(self._scoreboard(d)), "Scoreboard")
        for name in PENDING_TABS:
            i = tabs.addTab(QWidget(), name)
            tabs.setTabEnabled(i, False)
            tabs.setTabToolTip(i, "Todavía en migración: por ahora está en la app web (cs2a app).")
        lay.addWidget(tabs, 1)
        return page

    # ------------------------------------------------------------------ pestañas
    def _scoreboard(self, d: DemoData) -> QWidget:
        ps = stats.player_stats(d)
        names = {"A": d.meta["team_a"], "B": d.meta["team_b"]}
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setContentsMargins(0, 12, 0, 12)
        lay.setSpacing(10)

        items = match_highlights(d, ps)
        if items:
            lay.addWidget(w.card_row(items))

        lay.addWidget(w.ranking_bars(ps.assign(team_name=ps["team"].map(names)), "rating2", "name",
                                     color_col="team", colors=TEAM_COLORS, ref=1.0, ref_label="1.00 = promedio",
                                     title="¿Quién rindió más? (rating por jugador)"))
        lay.addWidget(w.team_legend(names))
        lay.addWidget(w.label("Cada barra es el rating del jugador en esta partida. Más de 1.00 es una buena partida "
                              "y menos de 0.85, una floja. El rating combina kills, muertes, daño y KAST.",
                              "Note", wrap=True))

        for team in ("A", "B"):
            t = ps[ps["team"] == team].sort_values("rating2", ascending=False)
            score = d.meta["score_a"] if team == "A" else d.meta["score_b"]
            title = w.label(f"{names[team]} — {score}", "Section")
            title.setTextFormat(Qt.PlainText)
            title.setStyleSheet(f"color:{TEAM_COLORS[team]}")
            lay.addWidget(title)
            lay.addWidget(w.DataTable(stat_table(t, SCOREBOARD_COLS), fit_rows=True))
        lay.addWidget(w.label(RATING_NOTE, "Note", wrap=True))

        ts = stats.team_stats(d)
        lay.addWidget(w.label("Por lado", "Section"))
        ts = ts[["team_name", *[c for c in ts.columns if c not in ("team", "team_name")]]].sort_values(["team_name", "side"])
        lay.addWidget(w.DataTable(ts.rename(columns=TEAM_SIDE_LABELS), fit_rows=True, decimals=1))
        lay.addStretch()
        return page
