"""Datos crudos traducidos y datos crudos (tablas de la caché, eventos y ticks de demoparser2, header)."""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

import pandas as pd
from PySide6.QtCore import Qt
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QLineEdit, QListWidget, QListWidgetItem, QPlainTextEdit, QPushButton, QSpinBox, QWidget

from .. import translate
from ..maps import pretty_map
from ..parser import TABLES
from .library_views import LibraryView
from .page import Combo, Page, Segmented, Slot
from .widgets import DataTable

TICK_PROPS = [
    "X", "Y", "Z", "pitch", "yaw", "velocity_X", "velocity_Y", "velocity_Z", "health", "armor_value",
    "is_alive", "team_num", "last_place_name", "active_weapon_name", "inventory", "balance",
    "current_equip_value", "has_helmet", "has_defuser", "is_scoped", "is_walking", "ducking", "flash_duration",
    "kills_total", "deaths_total", "assists_total", "damage_total", "headshot_kills_total",
    "utility_damage_total", "enemies_flashed_total", "mvps", "score", "spotted", "rank", "crosshair_code",
]
OTHER_PROPS = ["total_rounds_played", "is_warmup_period", "game_time", "is_bomb_planted", "round_start_time"]


@lru_cache(maxsize=8)
def _parser(path: str):
    from demoparser2 import DemoParser
    return DemoParser(path)


class FilteredTable(QWidget):
    """Tabla grande con filtro por ronda y búsqueda de texto (con cientos de miles de filas sigue fluida)."""

    def __init__(self, df: pd.DataFrame, parent=None):
        super().__init__(parent)
        self.df = df
        p = Page(margins=(0, 0, 0, 0))
        self.setLayout(p.lay)
        self.rcol = next((c for c in ("round", "Ronda") if c in df.columns), None)
        items = [(None, "Todas")]
        if self.rcol and df[self.rcol].notna().any():
            items += [(r, str(r)) for r in sorted(df[self.rcol].dropna().unique().tolist())]
        self.rnd = Combo("Ronda", items, min_width=90)
        self.q = QLineEdit()
        self.q.setPlaceholderText("Buscar (jugador, arma, zona…)")
        self.q.setClearButtonEnabled(True)
        p.row(self.rnd, self.q, stretches=[1, 3])
        self.slot = p.add(Slot(self._table), 1)
        self.rnd.changed.connect(self.slot.refresh)
        self.q.textChanged.connect(self.slot.refresh)

    def _table(self) -> QWidget:
        df = self.df
        if self.rcol and self.rnd.value is not None:
            df = df[df[self.rcol] == self.rnd.value]
        q = self.q.text().strip()
        if q:
            mask = pd.Series(False, index=df.index)
            for c in df.columns:
                if df[c].dtype == object or pd.api.types.is_string_dtype(df[c]):
                    mask |= df[c].astype(str).str.contains(q, case=False, na=False, regex=False)
            df = df[mask]
        p = Page(margins=(0, 0, 0, 0))
        p.caption(f"{len(df):,} filas · {len(df.columns)} columnas · clic derecho = copiar o exportar")
        p.add(DataTable(df), 1).setMinimumHeight(560)
        return p


class DemoPickView(LibraryView):
    """Vista de una demo a elección."""

    def build(self) -> QWidget:
        p = Page()
        ds = sorted(self.demos.values(), key=lambda d: d.meta.get("file_mtime", ""), reverse=True)
        self.pick = Combo("Partida", [(d.demo_id, f"{pretty_map(d.meta['map'])} · {d.meta['score_a']}-{d.meta['score_b']} · "
                                                  f"{d.meta['file_name']}") for d in ds], min_width=420)
        p.add(self.pick)
        body = p.add(Slot(lambda: self.body(self.demos[self.pick.value])), 1)
        self.pick.changed.connect(body.refresh)
        return p

    def body(self, d) -> QWidget:  # pragma: no cover - lo implementa cada vista
        raise NotImplementedError


class TranslatedView(DemoPickView):
    title = "Datos traducidos"
    subtitle = "Cada evento de la demo, en español y con valores legibles. Filtrá, copiá y exportá."

    def body(self, d) -> QWidget:
        p = Page(margins=(0, 0, 0, 0))
        table = Segmented(list(translate.TABLES), label="Tabla")
        p.add(table)
        slot = p.add(Slot(lambda: FilteredTable(translate.TABLES[table.value](d))), 1)
        table.changed.connect(slot.refresh)
        return p


class RawView(DemoPickView):
    title = "Datos crudos"
    subtitle = "Eventos y ticks tal como salen de la demo, sin procesar, para análisis propios."

    def body(self, d) -> QWidget:
        p = Page(margins=(0, 0, 0, 0))
        mode = Segmented(["Tablas normalizadas", "Eventos del juego", "Ticks por jugador", "Header", "meta.json"],
                         label="Fuente")
        p.add(mode)
        slot = p.add(Slot(lambda: self._mode(d, mode.value)), 1)
        mode.changed.connect(slot.refresh)
        return p

    def _mode(self, d, mode: str) -> QWidget:
        p = Page(margins=(0, 0, 0, 0))
        if mode == "Tablas normalizadas":
            p.caption("Tablas tal como las guarda la caché (parquet), con los nombres de columna originales.")
            table = Segmented(list(TABLES), label="Tabla")
            p.add(table)
            slot = p.add(Slot(lambda: FilteredTable(getattr(d, table.value))), 1)
            table.changed.connect(slot.refresh)
            return p
        if mode == "meta.json":
            return _json_box(d.meta)
        path = d.meta.get("source_path", "")
        if not path or not Path(path).exists():
            p.info("El archivo .dem original ya no está disponible (solo queda la caché o el .cs2a). "
                   "Volvé a abrirlo para explorar eventos y ticks crudos.", "warn")
            return p
        parser = _parser(path)
        if mode == "Header":
            return _json_box(parser.parse_header())
        if mode == "Eventos del juego":
            events = sorted(parser.list_game_events())
            ev = Combo("Evento", [(e, e) for e in events], value="player_death")
            pprops = _checklist(TICK_PROPS, "Props de jugador extra (prefijo user_/attacker_)")
            oprops = _checklist(OTHER_PROPS, "Props de partida")
            run = QPushButton("Leer evento")
            run.setObjectName("Primary")
            p.row(ev, run, stretches=[3, 1])
            p.row(pprops, oprops)
            out = p.add(Slot(lambda: QWidget()), 1)

            def read():
                QGuiApplication.setOverrideCursor(Qt.WaitCursor)
                try:
                    df = parser.parse_event(ev.value, player=_checked(pprops) or None, other=_checked(oprops) or None)
                    out._render = lambda: FilteredTable(df)
                    out.refresh_now()
                finally:
                    QGuiApplication.restoreOverrideCursor()

            run.clicked.connect(read)
            return p
        # Ticks
        rounds = d.rounds
        rnd = Combo("Ronda", [(r, str(r)) for r in rounds["round"]], min_width=80)
        step = QSpinBox()
        step.setRange(1, 640)
        step.setValue(64)
        step.setPrefix("Cada ")
        step.setSuffix(" ticks")
        step.setToolTip("64 = 1 muestra por segundo")
        who = Combo("Jugador", [("", "Todos"), *zip(d.players["steamid"], d.players["name"], strict=True)])
        props = _checklist(TICK_PROPS, "Props", ["X", "Y", "Z", "health", "active_weapon_name", "last_place_name"])
        run = QPushButton("Leer ticks")
        run.setObjectName("Primary")
        p.row(rnd, step, who, run)
        p.add(props)
        out = p.add(Slot(lambda: QWidget()), 1)

        def read():
            chosen = _checked(props)
            if not chosen:
                return
            r = rounds[rounds["round"] == rnd.value].iloc[0]
            ticks = list(range(int(r["freeze_end_tick"]), int(r["end_tick"]) + 1, step.value()))
            QGuiApplication.setOverrideCursor(Qt.WaitCursor)
            try:
                df = parser.parse_ticks(chosen, ticks=ticks)
                if who.value:
                    df = df[df["steamid"].astype(str) == who.value]
                out._render = lambda: FilteredTable(df)
                out.refresh_now()
            finally:
                QGuiApplication.restoreOverrideCursor()

        run.clicked.connect(read)
        return p


def _json_box(obj) -> QPlainTextEdit:
    box = QPlainTextEdit(json.dumps(obj, indent=2, ensure_ascii=False, default=str))
    box.setReadOnly(True)
    box.setMinimumHeight(500)
    return box


def _checklist(options: list[str], title: str, checked: list[str] | None = None) -> QListWidget:
    lst = QListWidget()
    lst.setToolTip(title)
    lst.setFixedHeight(120)
    lst.setFlow(QListWidget.LeftToRight)
    lst.setWrapping(True)
    lst.setResizeMode(QListWidget.Adjust)
    for o in options:
        it = QListWidgetItem(o)
        it.setFlags(it.flags() | Qt.ItemIsUserCheckable)
        it.setCheckState(Qt.Checked if o in (checked or []) else Qt.Unchecked)
        lst.addItem(it)
    return lst


def _checked(lst: QListWidget) -> list[str]:
    return [lst.item(i).text() for i in range(lst.count()) if lst.item(i).checkState() == Qt.Checked]
