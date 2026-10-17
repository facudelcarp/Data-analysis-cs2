"""Vista: análisis sobre varias demos."""
from __future__ import annotations

import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

from .. import tactics
from ..maps import pretty_map
from ..multi import Library
from . import common as ui
from . import tactics_view

LB_COLS = ["name", "demos", "rounds", "kills", "deaths", "kd", "adr", "hs_pct", "kast_pct", "opening_success_pct",
           "opening_kills", "trade_kills", "clutches_won", "clutches", "k3", "k4", "k5", "utility_adr",
           "enemies_flashed", "accuracy_pct", "rating1", "rating2", "ttd_ms", "reaction_ms", "crosshair_deg",
           "preaim_pct", "counter_strafe_pct", "first_bullet_acc_pct"]
COMPARE_METRICS = {"rating2": "Rating 2.0*", "adr": "ADR", "kast_pct": "KAST %", "hs_pct": "HS %",
                   "kd": "K/D", "opening_success_pct": "Entry %", "utility_adr": "ADR utilidad",
                   "accuracy_pct": "Precisión %", "ttd_ms": "TTD (ms)", "crosshair_deg": "Crosshair (°)",
                   "preaim_pct": "Pre-aim %", "counter_strafe_pct": "Counter-strafe %"}


def render() -> None:
    st.header("📚 Multi-demo")
    lib_all = ui.library()
    if len(lib_all) == 0:
        ui.empty_state()
        return

    matches = lib_all.matches()
    maps = sorted(matches["Mapa"].unique())
    c1, c2 = st.columns([3, 1])
    sel_maps = c1.multiselect("Mapas", maps, default=maps, format_func=pretty_map)
    min_rounds = c2.number_input("Mínimo de rondas por jugador", 0, 10_000, 0, step=10)
    ids = matches.loc[matches["Mapa"].isin(sel_maps), "demo_id"].tolist()
    lib = Library([lib_all.by_id[i] for i in ids]) if len(ids) != len(lib_all) else lib_all
    if len(lib) == 0:
        st.warning("Ningún mapa seleccionado.")
        return

    st.subheader(f"Partidas ({len(lib)})")
    st.dataframe(lib.matches().drop(columns=["demo_id"]), hide_index=True, width="stretch")

    lb = lib.leaderboard(min_rounds=min_rounds)
    st.subheader("Leaderboard agregado")
    st.dataframe(ui.stat_table(lb, LB_COLS), hide_index=True, width="stretch")
    st.caption("Las métricas se recalculan sobre el total de rondas (no es un promedio de promedios). " + ui.RATING_NOTE)
    ui.download_buttons(lb, "leaderboard", "lb")

    st.subheader("Comparar jugadores")
    names = dict(zip(lb["steamid"], lb["name"]))
    default = list(lb["steamid"].head(min(4, len(lb))))
    chosen = st.multiselect("Jugadores (máx. 4 para mantener colores distinguibles)", list(names), default=default[:2],
                            format_func=names.get, max_selections=4)
    if chosen:
        sub = lb[lb["steamid"].isin(chosen)].set_index("steamid").loc[chosen].reset_index()
        cols = st.columns(4)
        metrics = [(m, l) for m, l in COMPARE_METRICS.items() if m in sub and sub[m].notna().any()]
        for i, (metric, label) in enumerate(metrics):
            fig = go.Figure(go.Bar(x=sub["name"], y=sub[metric],
                                   marker_color=[ui.SERIES[chosen.index(s)] for s in sub["steamid"]],
                                   text=sub[metric], textposition="outside",
                                   hovertemplate="%{x}: %{y}<extra>" + label + "</extra>"))
            fig.update_layout(title=label)
            fig.update_xaxes(showticklabels=False)
            cols[i % 4].plotly_chart(ui.style(fig, height=230, legend=False), width="stretch")
        st.caption("Colores: " + " · ".join(f"{names[s]}" for s in chosen) + " (mismo orden en todos los gráficos)")

        st.markdown("**Evolución por partida**")
        metric = st.selectbox("Métrica", list(COMPARE_METRICS), format_func=COMPARE_METRICS.get, key="trend_metric")
        fig = go.Figure()
        for s in chosen:
            pdm = lib.per_demo(s)
            if pdm.empty or metric not in pdm:
                continue
            fig.add_scatter(x=pdm["Fecha"], y=pdm[metric], mode="lines+markers", name=names[s],
                            line=dict(color=ui.SERIES[chosen.index(s)], width=2), marker=dict(size=8),
                            customdata=pdm[["Mapa", "Marcador propio", "Resultado"]],
                            hovertemplate="%{x}<br>%{customdata[0]} %{customdata[1]} (%{customdata[2]})<br>"
                                          + COMPARE_METRICS[metric] + ": %{y}<extra>" + names[s] + "</extra>")
        fig.update_layout(title=COMPARE_METRICS[metric])
        st.plotly_chart(ui.style(fig), width="stretch")

    st.subheader("Mapas")
    focus = st.selectbox("Perspectiva", [""] + list(names), format_func=lambda s: names.get(s, "General (todas las partidas)"),
                         key="map_focus")
    ms = lib.map_summary(focus or None)
    if not ms.empty:
        ms["Mapa"] = ms["Mapa"].map(pretty_map)
        c1, c2 = st.columns([1, 1])
        c1.dataframe(ms, hide_index=True, width="stretch")
        ycol = "Winrate %" if focus else "Partidas"
        fig = px.bar(ms, x="Mapa", y=ycol, text=ycol, title=ycol)
        fig.update_traces(marker_color=ui.SERIES[0], textposition="outside")
        c2.plotly_chart(ui.style(fig, height=300, legend=False), width="stretch")

    st.subheader("Tácticas por equipo")
    tmap = st.selectbox("Mapa", sel_maps, format_func=pretty_map, key="tac_map")
    same_map = [d for d in lib.demos if d.meta["map"] == tmap]
    rt, gr, refs = tactics.library_tactics(same_map)
    st.caption(f"{len(same_map)} demo(s) en {pretty_map(tmap)}. Los equipos se identifican por nombre: en "
               "matchmaking todos se llaman 'Equipo A/B', así que mezcla partidas distintas.")
    identity = {}
    tactics_view.site_block(rt, identity, team_col="t_team_name")
    tactics_view.lineups_block(gr, refs, tmap, "team_name", identity, key="multi_lu")
