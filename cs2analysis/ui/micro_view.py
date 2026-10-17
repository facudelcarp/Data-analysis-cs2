"""Vista de micro-game (aim, reacción, movimiento) para una demo o una biblioteca."""
from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from .. import micro
from ..labels import MICRO_COLS, MICRO_LABELS, MICRO_NOTE
from ..translate import weapon_name
from . import common as ui

AIM_TYPES = ["pre-aim", "ajuste", "flick", "prefire"]
AIM_COLORS = dict(zip(AIM_TYPES, ui.SERIES[:4]))


def table(duels: pd.DataFrame, shots: pd.DataFrame, names: dict[str, str]) -> pd.DataFrame:
    pm = micro.player_micro(duels, shots)
    if pm.empty:
        return pm
    pm.insert(1, "name", pm["steamid"].map(names))
    return pm.sort_values("crosshair_deg").reset_index(drop=True)


def render(duels: pd.DataFrame, shots: pd.DataFrame, names: dict[str, str], vis_method: str, key: str) -> None:
    if duels is None or duels.empty:
        st.info("Esta demo no tiene datos de micro-game (caché de una versión anterior): volvé a cargar el .dem.")
        return
    if vis_method != "malla":
        st.warning("Visibilidad aproximada (radar del juego): bajá las mallas con `cs2a assets` o el botón de abajo "
                   "y volvé a cargar la demo para TTD/crosshair placement con línea de visión real.")
        if st.button("Descargar mallas de colisión", key=f"{key}_geo"):
            from ..geometry import download_geometry
            with st.spinner("Descargando ~57 MB…"):
                st.success(f"{len(download_geometry())} mallas descargadas. Borrá la caché o recargá la demo.")
    pm = table(duels, shots, names)
    st.dataframe(pm[[c for c in MICRO_COLS if c in pm]].rename(columns=MICRO_LABELS), hide_index=True, width="stretch")
    st.caption(MICRO_NOTE)
    _review_flags(pm)

    valid = duels[duels["crosshair_deg"].notna()].copy()
    valid["name"] = valid["attacker_steamid"].map(names)
    order = pm.dropna(subset=["crosshair_deg"])["name"].tolist()
    c1, c2 = st.columns(2)
    fig = go.Figure()
    for n in order:
        sub = valid[valid["name"] == n]
        fig.add_box(x=sub["crosshair_deg"].clip(upper=40), name=n, marker_color=ui.SERIES[0], boxpoints="all",
                    jitter=0.4, pointpos=0, marker=dict(size=5, opacity=0.6), line=dict(width=1.5), showlegend=False,
                    hovertemplate="%{x:.1f}°<extra>" + n + "</extra>")
    fig.update_layout(title="Crosshair placement al ver al rival (° · recortado a 40)")
    fig.update_xaxes(title="grados")
    c1.plotly_chart(ui.style(fig, height=60 + 32 * max(len(order), 3), legend=False), width="stretch")

    fig = go.Figure()
    for i, n in enumerate(order):
        sub = valid[valid["name"] == n]
        fig.add_box(x=sub["ttd_ms"].clip(upper=1500), name=n, marker_color=ui.SERIES[1], boxpoints="all",
                    jitter=0.4, pointpos=0, marker=dict(size=5, opacity=0.6), line=dict(width=1.5), showlegend=False,
                    hovertemplate="%{x:.0f} ms<extra>" + n + "</extra>")
    fig.update_layout(title="TTD: de ver al rival al primer daño (ms · recortado a 1.5 s)")
    fig.update_xaxes(title="ms")
    c2.plotly_chart(ui.style(fig, height=60 + 32 * max(len(order), 3), legend=False), width="stretch")

    st.subheader("Duelos")
    players = {"": "Todos", **{sid: names.get(sid, sid) for sid in duels["attacker_steamid"].unique()}}
    who = st.selectbox("Jugador", list(players), format_func=players.get, key=f"{key}_who")
    dd = duels if not who else duels[duels["attacker_steamid"] == who]
    fig = go.Figure()
    for t in AIM_TYPES:
        sub = dd[dd["aim_type"] == t]
        if sub.empty:
            continue
        fig.add_scatter(x=sub["crosshair_deg"].clip(upper=60), y=sub["reaction_ms"].clip(upper=1500), mode="markers", name=t,
                        marker=dict(size=9, color=AIM_COLORS[t], line=dict(width=2, color="#1a1a19")),
                        customdata=sub[["attacker_name", "victim_name", "weapon", "round", "ttd_ms"]],
                        hovertemplate="%{customdata[0]} → %{customdata[1]} (%{customdata[2]}, ronda %{customdata[3]})"
                                      "<br>error %{x:.1f}° · reacción %{y:.0f} ms · TTD %{customdata[4]:.0f} ms<extra></extra>")
    fig.update_layout(title="Cada duelo ganado: qué tan lejos estaba la mira vs. cuánto tardó en disparar")
    fig.update_xaxes(title="crosshair placement (°, escala log)", type="log",
                     tickvals=[0.3, 1, 3, 10, 30], ticktext=["0.3°", "1°", "3°", "10°", "30°"])
    fig.update_yaxes(title="reacción (ms)")
    st.plotly_chart(ui.style(fig, height=420), width="stretch")
    st.caption(f"Pre-aim ≤ {micro.PREAIM_DEG:.0f}° · flick ≥ {micro.FLICK_DEG:.0f}° y disparo en ≤ {micro.FLICK_MAX_MS:.0f} ms · "
               "prefire = disparó antes de tener visión.")
    show = dd.copy()
    show["weapon"] = show["weapon"].map(weapon_name)
    st.dataframe(show[["round", "attacker_name", "victim_name", "weapon", "aim_type", "crosshair_deg", "ttd_ms",
                       "reaction_ms", "ttk_ms", "shots_in_duel", "distance", "victim_shot_back"]].rename(columns={
        "round": "Ronda", "attacker_name": "Atacante", "victim_name": "Víctima", "weapon": "Arma", "aim_type": "Tipo",
        "crosshair_deg": "Error (°)", "ttd_ms": "TTD (ms)", "reaction_ms": "Reacción (ms)", "ttk_ms": "TTK (ms)",
        "shots_in_duel": "Disparos", "distance": "Distancia (m)", "victim_shot_back": "Rival disparó"}),
        hide_index=True, width="stretch")

    if len(shots) and "burst_index" in shots:
        st.subheader("Spray y movimiento")
        f = shots[shots["is_firearm"] & shots["weapon"].isin(["ak47", "m4a1", "m4a1_silencer", "famas", "galilar"])]
        if who:
            f = f[f["player_steamid"] == who]
        if len(f):
            by = f.assign(b=f["burst_index"].clip(upper=15)).groupby("b").agg(acc=("hit", "mean"), n=("hit", "size"))
            fig = go.Figure(go.Bar(x=by.index, y=100 * by["acc"], marker_color=ui.SERIES[0],
                                   customdata=by["n"], hovertemplate="bala %{x}: %{y:.0f}% (%{customdata} disparos)<extra></extra>"))
            fig.update_layout(title="Rifles: % de impacto según el número de bala en la ráfaga (15 = 15 o más)")
            fig.update_xaxes(title="bala de la ráfaga", dtick=1)
            fig.update_yaxes(title="% impacto")
            c1, c2 = st.columns(2)
            c1.plotly_chart(ui.style(fig, height=320, legend=False), width="stretch")
            fig = go.Figure(go.Histogram(x=f["speed"].clip(upper=260), nbinsx=26, marker_color=ui.SERIES[0]))
            fig.add_vline(x=micro.COUNTER_STRAFE_RATIO * 215, line_dash="dot", line_color=ui.TEXT_MUTED,
                          annotation_text="umbral AK", annotation_font_color=ui.TEXT_MUTED)
            fig.update_layout(title="Velocidad horizontal al disparar (u/s)")
            c2.plotly_chart(ui.style(fig, height=320, legend=False), width="stretch")


def _review_flags(pm: pd.DataFrame) -> None:
    """Jugadores con patrones que conviene revisar en la demo (no es un anticheat)."""
    if pm.empty or "inhuman_snaps" not in pm:
        return
    snaps = pm["inhuman_snaps"].fillna(0)
    blind = (pm["no_los_kill_pct"].fillna(0) >= 50) & (pm["wallbang_kills"].fillna(0) >= 5)
    flagged = pm[(snaps > 0) | blind]
    if flagged.empty:
        return
    with st.expander(f"⚠️ Indicadores a revisar ({len(flagged)} jugador/es)", expanded=True):
        st.dataframe(flagged[["name", "inhuman_snaps", "no_los_kill_pct", "wallbang_kills", "crosshair_deg", "reaction_ms"]]
                     .rename(columns=MICRO_LABELS), hide_index=True, width="stretch")
        st.caption(f"Snap inhumano: mira a ≥ {micro.SNAP_DEG:.0f}° del rival al aparecer y disparo en ≤ {micro.SNAP_MAX_MS:.0f} ms "
                   "(un humano tarda ≥ 150 ms solo en reaccionar). Kills sin visión + wallbangs: mata a través de paredes sin "
                   "haber visto al rival. Son señales para mirar esas rondas, no una prueba: revisalas en la pestaña de duelos.")
