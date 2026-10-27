"""Componentes de UI para el análisis táctico (se usan en demo individual y multi-demo)."""
from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from .. import tactics
from ..translate import place_name
from . import common as ui

KINDS = ["Humo", "Fuego", "Flash", "Granada HE"]


def site_block(rt: pd.DataFrame, team_label: dict[str, str], team_col: str = "t_team") -> None:
    """Distribución de sitios y win rate del lado T por equipo."""
    if rt.empty:
        st.info("Sin rondas.")
        return
    x = rt.copy()
    x["t_team"] = x[team_col]
    ss = tactics.site_summary(x)
    ss["Equipo"] = ss["t_team"].map(lambda t: team_label.get(t, t))
    cols = st.columns(max(1, ss["Equipo"].nunique()))
    for col, (team, sub) in zip(cols, ss.groupby("Equipo")):
        fig = go.Figure(go.Bar(
            x=sub["site"], y=sub["rondas"], textposition="outside",
            text=[f"{n} rondas · {w:.0f}% ganadas" for n, w in zip(sub["rondas"], sub["win_pct"])],
            marker_color=[ui.SERIES[0] if s != "Sin planta" else "#52514e" for s in sub["site"]],
            customdata=sub[["planta_media", "utilidad_media", "pct_rondas"]],
            hovertemplate="%{x}: %{y} rondas (%{customdata[2]}%)<br>Planta media %{customdata[0]} s<br>"
                          "Utilidad media antes de plantar: %{customdata[1]}<extra></extra>"))
        fig.update_layout(title=f"¿A qué sitio va {team} cuando juega de T?")
        fig.update_yaxes(showticklabels=False, showgrid=False)
        col.plotly_chart(ui.style(fig, height=280, legend=False), width="stretch")
    from .charts import explain
    explain("cada barra es un sitio en el que el equipo plantó la bomba, con cuántas rondas fue ahí y qué porcentaje "
            "ganó. 'Sin planta' = rondas en las que no llegó a plantar (las perdió o ganó matando a todos).")
    ss["planta_media"] = ss["planta_media"].map(lambda v: "" if pd.isna(v) else f"{v:.1f}")
    st.dataframe(ss[["Equipo", "site", "rondas", "pct_rondas", "ganadas", "win_pct", "planta_media", "utilidad_media"]].rename(
        columns={"site": "Sitio", "rondas": "Rondas", "pct_rondas": "% rondas", "ganadas": "Ganadas", "win_pct": "% victoria",
                 "planta_media": "Planta (s)", "utilidad_media": "Utilidad T antes de plantar"}),
        hide_index=True, width="stretch")


def lineups_block(grenades: pd.DataFrame, places: pd.DataFrame, map_name: str, team_col: str,
                  team_label: dict[str, str], key: str, backdrop: pd.DataFrame | None = None) -> None:
    """Tabla + mapa de lineups repetidos, con filtros de equipo, granada y lado."""
    if grenades.empty or "throw_x" not in grenades:
        st.info("Sin granadas con posición de lanzamiento (caché vieja: volvé a cargar la demo).")
        return
    teams = [t for t in grenades[team_col].dropna().unique() if t]
    c1, c2, c3, c4 = st.columns([2, 2, 1, 1])
    team = c1.selectbox("Equipo", teams, format_func=lambda t: team_label.get(t, t), key=f"{key}_team")
    kinds = c2.multiselect("Granadas", KINDS, default=["Humo", "Fuego"], key=f"{key}_kinds", placeholder="Elegí…")
    side = c3.radio("Lado", ["T", "CT"], horizontal=True, key=f"{key}_side")
    min_count = c4.number_input("Mín. repeticiones", 2, 50, 2, key=f"{key}_min")
    g = grenades[(grenades[team_col] == team) & (grenades["thrower_side"] == side)]
    lu = tactics.lineups(g, min_count=min_count, kinds=tuple(kinds), places=places, team_col=team_col)
    if lu.empty:
        st.caption("No hay granadas repetidas con esos filtros.")
        return
    st.caption(f"{len(lu)} lineups repetidos. Agrupados por zona de lanzamiento (~{tactics.THROW_CELL} u) y "
               f"punto de caída (~{tactics.LINEUP_CELL} u).")
    show = lu.head(40).copy()
    show["desde"] = show["desde"].map(place_name)
    show["hacia"] = show["hacia"].map(place_name)
    cols = ["grenade", "desde", "hacia", "veces", "rondas", "tiempo_medio", "jugadores"]
    if "demos" in show and show["demos"].max() > 1:
        cols.insert(5, "demos")
    if "Flash" in kinds:
        cols.append("enemigos_cegados")
    st.dataframe(show[cols].rename(columns={
        "grenade": "Granada", "desde": "Desde", "hacia": "Hacia", "veces": "Veces", "rondas": "Rondas",
        "demos": "Demos", "tiempo_medio": "Seg. de ronda (mediana)", "jugadores": "Quién",
        "enemigos_cegados": "Enemigos cegados"}), hide_index=True, width="stretch")

    top = (st.slider("Lineups en el mapa", 1, min(40, len(lu)), min(15, len(lu)), key=f"{key}_top")
           if len(lu) > 1 else 1)
    fig, tf = ui.map_figure(map_name, height=640, backdrop=backdrop)
    for kind in kinds:
        sub = lu.head(top)
        sub = sub[sub["grenade"] == kind]
        if sub.empty:
            continue
        color = ui.GRENADE_COLORS.get(kind, ui.SERIES[0])
        tx, ty = tf(sub["throw_x"], sub["throw_y"])
        lx, ly = tf(sub["x"], sub["y"])
        xs, ys = [], []
        for a, b, c, d in zip(tx, ty, lx, ly):
            xs += [a, c, None]
            ys += [b, d, None]
        fig.add_scatter(x=xs, y=ys, mode="lines", line=dict(color=color, width=2, dash="dot"), opacity=0.7,
                        showlegend=False, hoverinfo="skip")
        fig.add_scatter(x=tx, y=ty, mode="markers", marker=dict(size=7, color=color, symbol="circle-open", line=dict(width=2)),
                        showlegend=False, hoverinfo="skip")
        fig.add_scatter(x=lx, y=ly, mode="markers", name=kind,
                        marker=dict(size=10 + 2 * sub["veces"].clip(upper=10), color=color, line=dict(width=2, color="#1a1a19")),
                        customdata=sub[["desde", "hacia", "veces", "tiempo_medio", "jugadores"]],
                        hovertemplate="%{customdata[0]} → %{customdata[1]}<br>%{customdata[2]} veces · ~%{customdata[3]} s"
                                      "<br>%{customdata[4]}<extra>" + kind + "</extra>")
    st.plotly_chart(fig, width="stretch")
    from .charts import explain
    explain("cada granada que el equipo repite ronda tras ronda. El círculo vacío es desde dónde la tira y el lleno, "
            "dónde cae; cuanto más grande, más veces la usó. Sirve para ver qué humos y molotovs tiene armados un equipo.")
    ui.radar_hint(map_name, f"{key}_radar")


def rounds_block(rt: pd.DataFrame, team_label: dict[str, str]) -> None:
    show = rt.copy()
    show["t_team"] = show["t_team"].map(lambda t: team_label.get(t, t))
    show["first_kill_place"] = show["first_kill_place"].map(place_name)
    st.dataframe(show[["round", "t_team", "t_buy", "round_type", "plant_time", "first_kill_time", "first_kill_side",
                       "first_kill_place", "t_smokes", "t_flashes", "t_molos", "t_he", "winner_side"]].rename(columns={
        "round": "Ronda", "t_team": "Equipo T", "t_buy": "Compra T", "round_type": "Tipo", "plant_time": "Planta (s)",
        "first_kill_time": "1ª kill (s)", "first_kill_side": "1ª kill lado", "first_kill_place": "1ª kill zona",
        "t_smokes": "Humos T", "t_flashes": "Flashes T", "t_molos": "Molos T", "t_he": "HE T", "winner_side": "Gana"}),
        hide_index=True, width="stretch")
    st.caption("Utilidad T contada hasta el momento del plante (o toda la ronda si no hubo plante).")
