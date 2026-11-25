"""Roles por posición: quién ancla, quién rota, quién lurkea y quién toma espacio (ver positions.py)."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pyqtgraph as pg
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QWidget

from .. import positions
from ..maps import pretty_map
from ..multi import Library
from ..palette import MUTED, SERIES
from ..parser import DemoData
from . import charts
from .page import Combo, Page, Slot
from .widgets import DataTable

METHOD_NOTE = ("el rol sale de dónde juega, no de cuánto mata. En cada partida se reparte a los 5 jugadores de cada "
               "equipo entre los 5 puestos del mapa (en Mirage CT: AWPer, A Anchor, A Connector, B Short, B Anchor) "
               "según la zona que ocupan en cada momento de la ronda. Cada puesto tiene un peso: en CT, 0 = ancla un "
               "sitio y 1 = rota; en T, 0 = lurkea un extremo y 1 = toma espacio. El rol es el promedio de los pesos "
               "de los puestos que jugó en sus mapas. Plantillas y pesos aprendidos de partidas profesionales con "
               "la base de posiciones de Harry \"NER0\" Richards (@NER0cs); contra esa base acierta ~80 % de los "
               "puestos y de los roles.")


def _maps_note(maps: list[str]) -> str:
    return "Mapas con plantillas: " + ", ".join(pretty_map(m) for m in maps) + "."


def build(lib: Library) -> QWidget:
    p = Page()
    known = sorted(positions.templates())
    roles = lib.roles()
    if roles.empty:
        p.info("Ninguna de estas partidas es de un mapa con plantillas de puestos. " + _maps_note(known))
        return p
    teams = sorted(roles["team_name"].dropna().unique())
    team = Combo("Equipo", [("", "Todos"), *[(t, t) for t in teams]], min_width=220)
    p.add(team)
    body = p.add(Slot(lambda: _body(roles, team.value)))
    team.changed.connect(body.refresh)
    p.note(METHOD_NOTE)
    p.caption(_maps_note(known) + " Con menos de 3 mapas por jugador, el rol es una primera lectura.")
    p.stretch()
    return p


def _wide(roles: pd.DataFrame) -> pd.DataFrame:
    out = None
    for side in ("CT", "T"):
        r = roles[roles["side"] == side][["steamid", "name", "team_name", "role", "score", "maps", "detail"]]
        r = r.rename(columns={"role": f"role_{side}", "score": f"score_{side}", "maps": f"maps_{side}",
                              "detail": f"detail_{side}"})
        out = r if out is None else out.merge(r.drop(columns=["name", "team_name"]), on="steamid", how="outer")
    return out


def _body(roles: pd.DataFrame, team: str) -> QWidget:
    p = Page(margins=(0, 0, 0, 0))
    r = roles if not team else roles[roles["team_name"] == team]
    wide = _wide(r)
    p.add(_quadrant(wide))
    p.note("cada punto es un jugador. Hacia la derecha, más rotador en CT; hacia arriba, más toma de espacio en T. "
           "Abajo a la izquierda, el perfil clásico de lurker-ancla; arriba a la derecha, el de entry-rotador. "
           "Los AWPers van aparte (en la tabla): su puesto lo define el arma.")
    show = pd.DataFrame({
        "Jugador": wide["name"], "Equipo": wide["team_name"],
        "Rol CT": wide["role_CT"].map(positions.ROLE_ES), "Puntaje CT": wide["score_CT"],
        "Rol T": wide["role_T"].map(positions.ROLE_ES), "Puntaje T": wide["score_T"],
        "Mapas": wide[["maps_CT", "maps_T"]].max(axis=1),
        "Puestos CT": wide["detail_CT"], "Puestos T": wide["detail_T"],
    }).sort_values(["Equipo", "Jugador"])
    p.add(DataTable(show, decimals=2)).setMinimumHeight(min(80 + 26 * len(show), 520))
    p.caption("Puntaje CT: 0 = ancla siempre, 1 = rota siempre. Puntaje T: 0 = lurk siempre, 1 = toma espacio siempre.")
    return p


def _quadrant(wide: pd.DataFrame) -> pg.PlotWidget:
    w = charts.plot("Ancla ↔ Rotador (CT) y Lurker ↔ Toma espacio (T)", 460)
    rifle = wide[wide["score_CT"].notna() & wide["score_T"].notna()]
    for v in (0.3, 0.5):
        w.addItem(pg.InfiniteLine(v, angle=90, pen=pg.mkPen(MUTED, width=1, style=Qt.DotLine)))
    for v in (0.34, 0.63):
        w.addItem(pg.InfiniteLine(v, angle=0, pen=pg.mkPen(MUTED, width=1, style=Qt.DotLine)))
    teams = list(dict.fromkeys(rifle["team_name"]))
    for i, t in enumerate(teams):
        g = rifle[rifle["team_name"] == t]
        color = SERIES[i % len(SERIES)]
        tips = [f"{n} ({t})\nCT: {positions.ROLE_ES.get(a, a)} {x:.2f} · T: {positions.ROLE_ES.get(b, b)} {y:.2f}"
                for n, a, x, b, y in zip(g["name"], g["role_CT"], g["score_CT"], g["role_T"], g["score_T"],
                                         strict=True)]
        w.addItem(pg.ScatterPlotItem(g["score_CT"].to_numpy(float), g["score_T"].to_numpy(float), size=11,
                                     brush=pg.mkBrush(color), pen=pg.mkPen("#14110c", width=1.5), data=tips,
                                     hoverable=True, tip=lambda x, y, data: data))
        for n, x, y in zip(g["name"], g["score_CT"], g["score_T"], strict=True):
            charts.text(w, x, y, str(n), color="#e8e6e3", anchor=(0, 1.3), size=8)
    if len(teams) <= 8:
        charts.legend(w, [(t, SERIES[i % len(SERIES)]) for i, t in enumerate(teams)])
    w.setXRange(-0.05, 1.05, padding=0)
    w.setYRange(-0.05, 1.08, padding=0)
    w.setLabel("bottom", "CT: 0 = ancla · 1 = rota")
    w.setLabel("left", "T: 0 = lurk · 1 = toma espacio")
    return w


def single_block(p: Page, d: DemoData, names: dict[str, str]) -> None:
    """Para una partida: el puesto de cada jugador en cada lado."""
    a = positions.assign_positions(d)
    if a.empty:
        p.info(f"Sin plantillas de puestos para {pretty_map(d.meta['map'])}. "
               + _maps_note(sorted(positions.templates())))
        return
    tables = []
    for team, g in a.groupby("team"):
        ct = g[g["side"] == "CT"].set_index("steamid")
        t = g[g["side"] == "T"].set_index("steamid")
        sids = list(dict.fromkeys([*ct.index, *t.index]))

        def cell(df, sid, col):
            return df.loc[sid, col] if sid in df.index else None

        show = pd.DataFrame({
            "Jugador": [cell(ct, s, "name") or cell(t, s, "name") for s in sids],
            "Puesto CT": [cell(ct, s, "position") for s in sids],
            "Tipo CT": [_kind("CT", cell(ct, s, "position"), cell(ct, s, "weight")) for s in sids],
            "Puesto T": [cell(t, s, "position") for s in sids],
            "Tipo T": [_kind("T", cell(t, s, "position"), cell(t, s, "weight")) for s in sids],
            "Encaje": [np.nanmean([x for x in (cell(ct, s, "match"), cell(t, s, "match")) if x is not None])
                       for s in sids],
        })
        page = Page(margins=(0, 0, 0, 0))
        page.sub(names.get(team, team))
        page.add(DataTable(show, fit_rows=True, decimals=2))
        tables.append(page)
    p.row(*tables)
    p.note("el puesto de cada jugador en esta partida, según dónde se paró en cada momento de las rondas. Tipo: "
           "ancla o rota (CT), lurk o toma espacio (T). Encaje: qué tan parecido es su recorrido al de un "
           "profesional en ese puesto (1 = idéntico); con encaje bajo, el equipo jugó algo poco convencional. "
           "El rol a lo largo de varias partidas está en Multi-demo → Roles.")


def _kind(side: str, position, weight) -> str:
    if position is None:
        return ""
    if position == "AWPer":
        return "AWP"
    if weight is None or pd.isna(weight):
        return ""
    if side == "CT":
        return "ancla" if weight < 0.3 else "rota" if weight > 0.6 else "mixto"
    return "lurk" if weight < 0.34 else "espacio" if weight > 0.63 else "flex"
