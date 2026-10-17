"""Vista: dashboard ejecutivo (de un jugador foco o de toda la biblioteca)."""
from __future__ import annotations

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

from .. import stats
from ..maps import pretty_map
from ..translate import weapon_name
from . import common as ui


def render() -> None:
    st.header("📊 Dashboard")
    lib = ui.library()
    if len(lib) == 0:
        ui.empty_state()
        return
    players = lib.players()
    names = dict(zip(players["steamid"], players["name"] + " (" + players["demos"].astype(str) + " demos)"))
    saved = st.session_state.get("focus_player", "")
    options = [""] + list(names)
    focus = st.selectbox("Jugador foco", options, index=options.index(saved) if saved in options else 0,
                         format_func=lambda s: names.get(s, "— Biblioteca completa —"))
    st.session_state["focus_player"] = focus
    if focus:
        _player_dashboard(lib, focus, names[focus].rsplit(" (", 1)[0])
    else:
        _library_dashboard(lib)


def _library_dashboard(lib) -> None:
    m = lib.matches()
    pr = lib.player_rounds
    total_rounds = int(m["Rondas"].sum())
    k = lib.concat("kills")
    ek = k[k["is_enemy_kill"]] if len(k) else k
    ui.kpi_row([
        ("Demos", f"{len(m)}", None),
        ("Rondas", f"{total_rounds:,}", None),
        ("Jugadores únicos", f"{pr['steamid'].nunique()}", None),
        ("Kills", f"{len(ek):,}", None),
        ("HS global", f"{100 * ek['headshot'].mean():.0f}%" if len(ek) else "—", None),
        ("Horas de juego", f"{m['Duración (min)'].sum() / 60:.1f}", None),
    ])
    c1, c2 = st.columns(2)
    by_map = m.groupby("Mapa").size().rename("Partidas").reset_index()
    by_map["Mapa"] = by_map["Mapa"].map(pretty_map)
    fig = px.bar(by_map.sort_values("Partidas"), x="Partidas", y="Mapa", orientation="h", text="Partidas",
                 title="Partidas por mapa")
    fig.update_traces(marker_color=ui.SERIES[0])
    c1.plotly_chart(ui.style(fig, height=320, legend=False), width="stretch")

    r = lib.concat("rounds")
    side = r.groupby("winner_side").size().reindex(["CT", "T"]).fillna(0)
    fig = go.Figure(go.Bar(x=side.index, y=side.values, marker_color=[ui.SIDE_COLORS["CT"], ui.SIDE_COLORS["T"]],
                           text=[f"{100 * v / max(side.sum(), 1):.0f}%" for v in side.values], textposition="outside"))
    fig.update_layout(title="Rondas ganadas por lado")
    c2.plotly_chart(ui.style(fig, height=320, legend=False), width="stretch")

    c1, c2 = st.columns(2)
    if len(ek):
        w = ek.groupby("weapon").size().sort_values(ascending=False).head(10).rename("Kills").reset_index()
        w["weapon"] = w["weapon"].map(weapon_name)
        fig = px.bar(w.sort_values("Kills"), x="Kills", y="weapon", orientation="h", text="Kills",
                     title="Armas con más kills", labels={"weapon": ""})
        fig.update_traces(marker_color=ui.SERIES[0])
        c1.plotly_chart(ui.style(fig, height=360, legend=False), width="stretch")
    reasons = r.groupby("reason").size().sort_values().rename("Rondas").reset_index()
    fig = px.bar(reasons, x="Rondas", y="reason", orientation="h", text="Rondas", title="Cómo terminan las rondas",
                 labels={"reason": ""})
    fig.update_traces(marker_color=ui.SERIES[0])
    c2.plotly_chart(ui.style(fig, height=360, legend=False), width="stretch")

    st.subheader("Top jugadores (mín. 30 rondas)")
    lb = lib.leaderboard(min_rounds=30)
    if lb.empty:
        lb = lib.leaderboard()
    st.dataframe(ui.stat_table(lb.head(15), ["name", "demos", "rounds", "kd", "adr", "kast_pct", "hs_pct", "rating2"]),
                 hide_index=True, width="stretch")
    st.caption(ui.RATING_NOTE)


def _player_dashboard(lib, sid: str, name: str) -> None:
    pr = lib.player_rounds[lib.player_rounds["steamid"] == sid]
    cl = lib.clutches[lib.clutches["steamid"] == sid]
    acc = lib.accuracy[lib.accuracy["steamid"] == sid]
    agg = stats.aggregate(pr, cl, acc).iloc[0]
    per = lib.per_demo(sid)
    wins = int((per["Resultado"] == "Victoria").sum())
    st.subheader(name)
    ui.kpi_row([
        ("Partidas", f"{len(per)}", None),
        ("Winrate", f"{100 * wins / max(len(per), 1):.0f}%", f"{wins} victorias"),
        ("Rating 2.0*", f"{agg['rating2']:.2f}", ui.RATING_NOTE),
        ("ADR", f"{agg['adr']:.1f}", None),
        ("KAST", f"{agg['kast_pct']:.0f}%", None),
        ("K/D", f"{agg['kd']:.2f}", None),
        ("HS", f"{agg['hs_pct']:.0f}%", None),
    ])
    ui.kpi_row([
        ("Entry", f"{int(agg['opening_kills'])}-{int(agg['opening_deaths'])}", f"{agg['opening_success_pct']:.0f}% de éxito"),
        ("Clutches", f"{int(agg['clutches_won'])}/{int(agg['clutches'])}", "Ganados / disputados (1vX)"),
        ("Multikills", f"{int(agg['multikill_rounds'])}", f"3K: {int(agg['k3'])} · 4K: {int(agg['k4'])} · ACE: {int(agg['k5'])}"),
        ("Tradeos", f"{int(agg['trade_kills'])}", "Kills que vengaron a un compañero en < 5 s"),
        ("ADR utilidad", f"{agg['utility_adr']:.1f}", None),
        ("Precisión", f"{agg['accuracy_pct']:.0f}%" if pd.notna(agg.get("accuracy_pct")) else "—", "Impactos / disparos con armas de fuego"),
        ("MVPs", f"{int(agg['mvps'])}", None),
    ])

    mi = lib.micro(sid)
    if len(mi):
        m = mi.iloc[0]

        def fmt(col, unit, digits=0):
            v = m.get(col)
            return "—" if v is None or pd.isna(v) else f"{v:.{digits}f}{unit}"
        st.markdown("**Aim y micro-game**")
        ui.kpi_row([
            ("TTD", fmt("ttd_ms", " ms"), "Mediana: de tener línea de visión al primer daño"),
            ("Reacción", fmt("reaction_ms", " ms"), "Mediana: de ver al rival al primer disparo"),
            ("Crosshair placement", fmt("crosshair_deg", "°", 1), "Mediana del ángulo mira→cabeza al ver al rival"),
            ("Pre-aim", fmt("preaim_pct", "%"), "Duelos ganados con la mira a ≤ 3° de la cabeza"),
            ("Counter-strafe", fmt("counter_strafe_pct", "%"), "Disparos frenado (≤ 34% de la velocidad máx. del arma)"),
            ("1ª bala", fmt("first_bullet_acc_pct", "%"), "Impactos de la primera bala de cada ráfaga"),
            ("Mal parado", fmt("caught_off_angle_pct", "%"), "Muertes en las que miraba a > 45° de quien lo mató"),
        ])

    c1, c2 = st.columns([3, 2])
    fig = go.Figure()
    fig.add_scatter(x=per["Fecha"], y=per["rating2"], mode="lines+markers", name="Rating 2.0*",
                    line=dict(color=ui.SERIES[0], width=2),
                    marker=dict(size=10, color=[ui.TEAM_COLORS["A"] if r == "Victoria" else ui.SIDE_COLORS["T"] for r in per["Resultado"]],
                                line=dict(width=2, color="#1a1a19")),
                    customdata=per[["Mapa", "Marcador propio", "Resultado", "adr"]],
                    hovertemplate="%{x}<br>%{customdata[0]} %{customdata[1]} · %{customdata[2]}<br>"
                                  "Rating %{y} · ADR %{customdata[3]}<extra></extra>")
    fig.add_hline(y=1.0, line_dash="dot", line_color=ui.GRID)
    fig.update_layout(title="Rating por partida (punto verde = victoria, naranja = derrota)")
    c1.plotly_chart(ui.style(fig, height=340, legend=False), width="stretch")

    ms = lib.map_summary(sid)
    if not ms.empty:
        ms["Mapa"] = ms["Mapa"].map(pretty_map)
        fig = px.bar(ms.sort_values("Winrate %"), x="Winrate %", y="Mapa", orientation="h",
                     text=ms.sort_values("Winrate %").apply(lambda r: f"{r['Winrate %']:.0f}% ({r['Partidas']})", axis=1),
                     title="Winrate por mapa (partidas)", range_x=[0, 110])
        fig.update_traces(marker_color=ui.SERIES[0])
        c2.plotly_chart(ui.style(fig, height=340, legend=False), width="stretch")

    c1, c2, c3 = st.columns(3)
    sides = stats.aggregate(pr, by=["steamid", "side"])
    if not sides.empty:
        sides = sides.set_index("side").reindex(["CT", "T"]).dropna(how="all").reset_index()
        fig = go.Figure(go.Bar(x=sides["side"], y=sides["adr"], marker_color=[ui.SIDE_COLORS[s] for s in sides["side"]],
                               text=sides["adr"], textposition="outside",
                               customdata=sides[["rating2", "kast_pct", "rounds"]],
                               hovertemplate="%{x}: ADR %{y}<br>Rating %{customdata[0]} · KAST %{customdata[1]}%"
                                             "<br>%{customdata[2]} rondas<extra></extra>"))
        fig.update_layout(title="ADR por lado")
        c1.plotly_chart(ui.style(fig, height=300, legend=False), width="stretch")

    k = lib.concat("kills")
    mine = k[(k["attacker_steamid"] == sid) & k["is_enemy_kill"]] if len(k) else k
    if len(mine):
        w = mine.groupby("weapon").size().sort_values(ascending=False).head(8).rename("Kills").reset_index()
        w["weapon"] = w["weapon"].map(weapon_name)
        fig = px.bar(w.sort_values("Kills"), x="Kills", y="weapon", orientation="h", text="Kills",
                     title="Kills por arma", labels={"weapon": ""})
        fig.update_traces(marker_color=ui.SERIES[0])
        c2.plotly_chart(ui.style(fig, height=300, legend=False), width="stretch")

    mk = pd.Series({"1K": agg["k1"], "2K": agg["k2"], "3K": agg["k3"], "4K": agg["k4"], "ACE": agg["k5"]})
    fig = go.Figure(go.Bar(x=mk.index, y=mk.values, marker_color=ui.SERIES[0], text=mk.values.astype(int),
                           textposition="outside"))
    fig.update_layout(title="Rondas por cantidad de kills")
    c3.plotly_chart(ui.style(fig, height=300, legend=False), width="stretch")

    st.subheader("Partidas")
    cols = ["Fecha", "Mapa", "Marcador propio", "Resultado", "kills", "deaths", "assists", "adr", "kast_pct", "hs_pct",
            "rating2"]
    show = per[cols].copy()
    show["Mapa"] = show["Mapa"].map(pretty_map)
    st.dataframe(ui.stat_table(show, cols), hide_index=True, width="stretch")
