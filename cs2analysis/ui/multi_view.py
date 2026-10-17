"""Vista: análisis sobre varias demos."""
from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from .. import tactics
from ..maps import pretty_map
from ..multi import Library
from . import charts, common as ui
from . import micro_view, tactics_view

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

    # --- Destacados ---
    _highlights(lb, lib)

    # --- Leaderboard ---
    st.subheader("Leaderboard agregado")
    st.plotly_chart(charts.ranking_bars(lb, "rating2", "name", fmt="{:.2f}", ref=1.0, ref_label="1.00 = promedio",
                                        title="¿Quién rindió mejor en el total de partidas?"), width="stretch")
    charts.explain("cada barra es el rating agregado del jugador (combinando kills, muertes, daño y KAST sobre "
                   "todas sus rondas). Más de 1.00 es bueno; menos de 0.85, flojo. La línea punteada es la "
                   "referencia 1.00.")
    st.dataframe(ui.stat_table(lb, LB_COLS), hide_index=True, width="stretch")
    st.caption("Las métricas se recalculan sobre el total de rondas (no es un promedio de promedios). " + ui.RATING_NOTE)
    ui.download_buttons(lb, "leaderboard", "lb")

    # --- Comparar jugadores ---
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
                                   text=[_fmt_metric(v, metric) for v in sub[metric]], textposition="outside",
                                   hovertemplate="%{x}: %{text}<extra>" + label + "</extra>"))
            fig.update_layout(title=f"¿Quién tiene mejor {label}?")
            fig.update_xaxes(showticklabels=False)
            cols[i % 4].plotly_chart(ui.style(fig, height=230, legend=False), width="stretch")
        st.caption("Colores: " + " · ".join(f"{names[s]}" for s in chosen) + " (mismo orden en todos los gráficos)")
        charts.explain("cada grupo de barras compara una métrica entre los jugadores elegidos, calculada sobre "
                       "todas sus rondas. Los colores se mantienen iguales en todos los gráficos para identificar "
                       "a cada jugador de un vistazo.")

        st.markdown("**¿Cómo fue evolucionando partida a partida?**")
        metric = st.selectbox("Métrica", list(COMPARE_METRICS), format_func=COMPARE_METRICS.get, key="trend_metric")
        fig = go.Figure()
        for s in chosen:
            pdm = lib.per_demo(s)
            if pdm.empty or metric not in pdm:
                continue
            fig.add_scatter(x=pdm["Partida"], y=pdm[metric], mode="lines+markers", name=names[s],
                            line=dict(color=ui.SERIES[chosen.index(s)], width=2), marker=dict(size=8),
                            customdata=pdm[["Mapa", "Marcador propio", "Resultado"]],
                            hovertemplate="%{x}<br>%{customdata[0]} %{customdata[1]} (%{customdata[2]})<br>"
                                          + COMPARE_METRICS[metric] + ": %{y}<extra>" + names[s] + "</extra>")
        ref_val = _trend_reference(metric)
        if ref_val is not None:
            fig.add_hline(y=ref_val, line_dash="dot", line_color=ui.TEXT_MUTED)
        fig.update_layout(title=f"¿Cómo evoluciona el {COMPARE_METRICS[metric]} partida a partida?")
        st.plotly_chart(ui.style(fig), width="stretch")
        charts.explain("cada punto es una partida. La línea conecta los valores en orden cronológico. "
                       "Sirve para ver si un jugador está mejorando, empeorando o se mantiene estable. "
                       "Pasá el mouse para ver el mapa, el marcador y el resultado.")

    # --- Aim / micro-game ---
    if len(lib.duels):
        st.subheader("Aim / micro-game")
        all_names = dict(zip(lb["steamid"], lb["name"])) if not lb.empty else {}
        # Completar con jugadores que no llegaron al leaderboard
        for d in lib.demos:
            for _, p in d.players.iterrows():
                all_names.setdefault(p["steamid"], p["name"])
        team_of: dict[str, str] = {}  # sin equipos en multi-demo (mezcla partidas)
        micro_view.render(lib.duels, lib.shots, all_names, "malla", key="multi_micro", team_of=team_of)

    # --- Mapas ---
    st.subheader("Mapas")
    lb_names = dict(zip(lb["steamid"], lb["name"])) if not lb.empty else {}
    focus = st.selectbox("Perspectiva", [""] + list(lb_names),
                         format_func=lambda s: lb_names.get(s, "General (todas las partidas)"),
                         key="map_focus")
    ms = lib.map_summary(focus or None)
    if not ms.empty:
        ms["Mapa"] = ms["Mapa"].map(pretty_map)
        c1, c2 = st.columns([1, 1])
        c1.dataframe(ms, hide_index=True, width="stretch")
        ycol = "Winrate %" if focus else "Partidas"
        title = "¿En qué mapas gana más?" if focus else "¿En qué mapas se juega más?"
        fig = go.Figure(go.Bar(x=ms["Mapa"], y=ms[ycol],
                               marker_color=ui.SERIES[0],
                               text=[f"{v:.0f}{'%' if focus else ''}" for v in ms[ycol]],
                               textposition="outside",
                               hovertemplate="%{x}: %{text}<extra></extra>"))
        fig.update_layout(title=title)
        fig.update_xaxes(showgrid=False)
        fig.update_yaxes(showgrid=False, range=[0, ms[ycol].max() * 1.2] if len(ms) else None)
        c2.plotly_chart(ui.style(fig, height=300, legend=False), width="stretch")
        if focus:
            charts.explain("cada barra es el winrate del jugador en ese mapa. Los mapas con una sola partida "
                           "no son representativos: necesitás al menos 5-10 para ver una tendencia.")
        else:
            charts.explain("cada barra es la cantidad de partidas jugadas en ese mapa. Los mapas más jugados "
                           "son los que más datos aportan al leaderboard.")

    # --- Tácticas ---
    st.subheader("Tácticas por equipo")
    tmap = st.selectbox("Mapa", sel_maps, format_func=pretty_map, key="tac_map")
    same_map = [d for d in lib.demos if d.meta["map"] == tmap]
    rt, gr, refs = tactics.library_tactics(same_map)
    st.caption(f"{len(same_map)} demo(s) en {pretty_map(tmap)}. Los equipos se identifican por nombre: en "
               "matchmaking todos se llaman 'Equipo A/B', así que mezcla partidas distintas.")
    identity = {}
    tactics_view.site_block(rt, identity, team_col="t_team_name")
    tactics_view.lineups_block(gr, refs, tmap, "team_name", identity, key="multi_lu")


def _highlights(lb: pd.DataFrame, lib: Library) -> None:
    """Tarjetas con lo más destacado de toda la biblioteca, para leer en 5 segundos."""
    if lb.empty:
        return

    def best(col, asc=False):
        x = lb.dropna(subset=[col])
        return x.sort_values(col, ascending=asc).iloc[0] if len(x) else None

    items: list[tuple[str, str, str]] = []
    if (r := best("rating2")) is not None:
        items.append(("⭐ Mejor rating", r["name"],
                      f"rating {r['rating2']:.2f} · {int(r['rounds'])} rondas"))
    if (r := best("adr")) is not None:
        items.append(("💥 Más daño", r["name"],
                      f"{r['adr']:.0f} ADR · {int(r['rounds'])} rondas"))
    if (r := best("opening_kills")) is not None and r["opening_kills"] > 0:
        items.append(("🚪 Más aperturas", r["name"],
                      f"{int(r['opening_kills'])} primeras kills"))
    if (r := best("clutches_won")) is not None and r["clutches_won"] > 0:
        items.append(("🧊 Clutches", r["name"],
                      f"{int(r['clutches_won'])} ganados de {int(r['clutches'])}"))
    mi = lib.micro()
    if len(mi):
        mi = mi[mi["duels_won"].fillna(0) >= 5].dropna(subset=["crosshair_deg"])
        if len(mi):
            r = mi.sort_values("crosshair_deg").iloc[0]
            name = lb.set_index("steamid")["name"].get(r["steamid"], "?")
            items.append(("🎯 Mejor mira", name,
                          f"{r['crosshair_deg']:.1f}° del rival al verlo"))
    if items:
        charts.highlight_cards(items)
        st.write("")


def _fmt_metric(v, metric: str) -> str:
    """Formatea el valor de una métrica de comparación."""
    if pd.isna(v):
        return "—"
    if metric in ("rating2", "kd"):
        return f"{v:.2f}"
    if metric in ("ttd_ms", "reaction_ms"):
        return f"{v:.0f} ms"
    if metric == "crosshair_deg":
        return f"{v:.1f}°"
    if "pct" in metric or metric == "hs_pct":
        return f"{v:.0f}%"
    return f"{v:.1f}"


def _trend_reference(metric: str) -> float | None:
    """Línea de referencia horizontal para la evolución temporal."""
    refs = {"rating2": 1.0, "kd": 1.0, "kast_pct": 70, "hs_pct": 50, "opening_success_pct": 50}
    return refs.get(metric)
