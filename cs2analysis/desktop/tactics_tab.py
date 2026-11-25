"""Bloques tácticos (sitios, lineups, ronda a ronda): se usan en demo individual y multi-demo."""
from __future__ import annotations

import pandas as pd
from PySide6.QtWidgets import QSpinBox, QWidget

from .. import tactics
from ..palette import GRENADE_COLORS, SERIES
from ..translate import place_name
from . import charts
from .mapview import MapView
from .page import Combo, Page, Segmented, Slider, Slot
from .widgets import DataTable

KINDS = ["Humo", "Fuego", "Flash", "Granada HE"]


def site_block(p: Page, rt: pd.DataFrame, team_label: dict[str, str], team_col: str = "t_team") -> None:
    """Distribución de sitios y win rate del lado T por equipo."""
    if rt.empty:
        p.info("Sin rondas.")
        return
    x = rt.copy()
    x["t_team"] = x[team_col]
    ss = tactics.site_summary(x)
    ss["Equipo"] = ss["t_team"].map(lambda t: team_label.get(t, t))
    plots = []
    for team, sub in ss.groupby("Equipo"):
        plots.append(charts.vbars(sub["site"].tolist(), sub["rondas"],
                                  [SERIES[0] if s != "Sin planta" else charts.NEUTRAL for s in sub["site"]],
                                  [f"{n} rondas · {w:.0f}%" for n, w in zip(sub["rondas"], sub["win_pct"], strict=True)],
                                  title=f"¿A qué sitio va {team} cuando juega de T?", height=280))
    p.row(*plots)
    p.note("cada barra es un sitio en el que el equipo plantó la bomba, con cuántas rondas fue ahí y qué porcentaje "
           "ganó. 'Sin planta' = rondas en las que no llegó a plantar (las perdió o ganó matando a todos).")
    ss["planta_media"] = ss["planta_media"].map(lambda v: "" if pd.isna(v) else f"{v:.1f}")
    p.add(DataTable(ss[["Equipo", "site", "rondas", "pct_rondas", "ganadas", "win_pct", "planta_media",
                        "utilidad_media"]].rename(columns={
        "site": "Sitio", "rondas": "Rondas", "pct_rondas": "% rondas", "ganadas": "Ganadas", "win_pct": "% victoria",
        "planta_media": "Planta (s)", "utilidad_media": "Utilidad T antes de plantar"}), fit_rows=True, decimals=1))


def lineups_block(p: Page, grenades: pd.DataFrame, places: pd.DataFrame, map_name: str, team_col: str,
                  team_label: dict[str, str], backdrop: pd.DataFrame | None = None) -> None:
    """Tabla + mapa de lineups repetidos, con filtros de equipo, granada y lado."""
    if grenades.empty or "throw_x" not in grenades:
        p.info("Sin granadas con posición de lanzamiento (caché vieja: volvé a cargar la demo).")
        return
    teams = [t for t in grenades[team_col].dropna().unique() if t]
    team = Combo("Equipo", [(t, team_label.get(t, t)) for t in teams])
    kinds = Segmented(KINDS, label="Granadas", multi=True, values=["Humo", "Fuego"])
    side = Segmented(["T", "CT"], label="Lado")
    min_count = QSpinBox()
    min_count.setRange(2, 50)
    min_count.setPrefix("Mín. repeticiones: ")
    top = Slider("Lineups en el mapa", 1, 40, 15)
    p.row(team, kinds, side, min_count, stretches=[2, 3, 1, 1])
    p.add(top)

    def render() -> QWidget:
        out = Page(margins=(0, 0, 0, 0))
        g = grenades[(grenades[team_col] == team.value) & (grenades["thrower_side"] == side.value)]
        lu = tactics.lineups(g, min_count=min_count.value(), kinds=tuple(kinds.values), places=places, team_col=team_col)
        if lu.empty:
            out.caption("No hay granadas repetidas con esos filtros.")
            return out
        out.caption(f"{len(lu)} lineups repetidos. Agrupados por zona de lanzamiento (~{tactics.THROW_CELL} u) y "
                    f"punto de caída (~{tactics.LINEUP_CELL} u).")
        show = lu.head(40).copy()
        show["desde"] = show["desde"].map(place_name)
        show["hacia"] = show["hacia"].map(place_name)
        cols = ["grenade", "desde", "hacia", "veces", "rondas", "tiempo_medio", "jugadores"]
        if "demos" in show and show["demos"].max() > 1:
            cols.insert(5, "demos")
        if "Flash" in kinds.values:
            cols.append("enemigos_cegados")
        out.add(DataTable(show[cols].rename(columns={
            "grenade": "Granada", "desde": "Desde", "hacia": "Hacia", "veces": "Veces", "rondas": "Rondas",
            "demos": "Demos", "tiempo_medio": "Seg. de ronda (mediana)", "jugadores": "Quién",
            "enemigos_cegados": "Enemigos cegados"}), decimals=1)).setMinimumHeight(280)
        m = MapView(map_name, backdrop=backdrop)
        head = show.head(top.value)
        for kind in kinds.values:
            sub = head[head["grenade"] == kind]
            if sub.empty:
                continue
            color = GRENADE_COLORS.get(kind, SERIES[0])
            m.segments(sub["throw_x"], sub["throw_y"], sub["x"], sub["y"], color, width=2, alpha=180, dashed=True)
            m.points(sub["throw_x"], sub["throw_y"], color, size=8, filled=False)
            tips = [f"{kind}: {a} → {b}\n{v} veces · ~{t} s\n{j}" for a, b, v, t, j in
                    zip(sub["desde"], sub["hacia"], sub["veces"], sub["tiempo_medio"], sub["jugadores"], strict=True)]
            m.points(sub["x"], sub["y"], color, kind, size=(10 + 2 * sub["veces"].clip(upper=10)).to_numpy(), tips=tips)
        out.add(m.finish())
        out.note("cada granada que el equipo repite ronda tras ronda. El círculo vacío es desde dónde la tira y el lleno, "
                 "dónde cae; cuanto más grande, más veces la usó. Sirve para ver qué humos y molotovs tiene armados un "
                 "equipo. Rueda del mouse = zoom.")
        return out

    slot = p.add(Slot(render))
    for sig in (team.changed, kinds.changed, side.changed, min_count.valueChanged, top.changed):
        sig.connect(slot.refresh)


def rounds_block(p: Page, rt: pd.DataFrame, team_label: dict[str, str]) -> None:
    show = rt.copy()
    show["t_team"] = show["t_team"].map(lambda t: team_label.get(t, t))
    show["first_kill_place"] = show["first_kill_place"].map(place_name)
    p.add(DataTable(show[["round", "t_team", "t_buy", "round_type", "plant_time", "first_kill_time", "first_kill_side",
                          "first_kill_place", "t_smokes", "t_flashes", "t_molos", "t_he", "winner_side"]].rename(columns={
        "round": "Ronda", "t_team": "Equipo T", "t_buy": "Compra T", "round_type": "Tipo", "plant_time": "Planta (s)",
        "first_kill_time": "1ª kill (s)", "first_kill_side": "1ª kill lado", "first_kill_place": "1ª kill zona",
        "t_smokes": "Humos T", "t_flashes": "Flashes T", "t_molos": "Molos T", "t_he": "HE T", "winner_side": "Gana"}),
        decimals=1)).setMinimumHeight(360)
    p.caption("Utilidad T contada hasta el momento del plante (o toda la ronda si no hubo plante).")
