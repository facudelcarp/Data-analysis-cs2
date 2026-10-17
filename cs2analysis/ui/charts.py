"""Gráficos "de un vistazo" para la vista de demo individual.

Reglas de todos los gráficos de este módulo:
- el título es una pregunta en lenguaje llano y el gráfico la responde sin necesidad de hover;
- los valores van escritos sobre las barras o los puntos;
- donde sirve hay una línea de referencia (el promedio del partido, el rating 1.0);
- debajo va una línea "Cómo leerlo" (con `explain`).
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from . import common as ui

ROUND_ICONS = {1: "💣", 7: "✂️", 8: "💀", 9: "💀", 12: "⏱", 17: "🏳", 18: "🏳"}
ROUND_ICON_LEGEND = "💀 eliminación · 💣 bomba detonada · ✂️ bomba desactivada · ⏱ se acabó el tiempo · 🏳 rendición"
# Sin reutilizar los colores de equipo: de mejor (azul fuerte) a "no es aim" (gris)
AIM_TYPE_COLORS = {"pre-aim": "#2a78d6", "ajuste": "#86b6ef", "flick": "#c98500", "prefire": "#52514e"}
NEUTRAL = "#52514e"


def explain(text: str) -> None:
    st.caption(f"💡 **Cómo leerlo:** {text}")


def _hbar_height(n: int) -> int:
    return 90 + 34 * max(n, 2)


def ranking_bars(df: pd.DataFrame, value: str, label: str, color_col: str | None = None, colors: dict | None = None,
                 fmt: str = "{:.2f}", ref: float | None = None, ref_label: str = "", lower_is_better: bool = False,
                 title: str = "") -> go.Figure:
    """Barras horizontales ordenadas (lo mejor arriba), con el valor escrito y una línea de referencia."""
    d = df.dropna(subset=[value]).sort_values(value, ascending=not lower_is_better)
    color = [colors.get(c, ui.SERIES[0]) for c in d[color_col]] if color_col and colors else ui.SERIES[0]
    fig = go.Figure(go.Bar(x=d[value], y=d[label], orientation="h", marker_color=color,
                           text=[fmt.format(v) for v in d[value]], textposition="inside", insidetextanchor="end",
                           textfont=dict(color="#ffffff"), hovertemplate="%{y}: %{text}<extra></extra>"))
    if ref is not None and np.isfinite(ref):
        fig.add_vline(x=ref, line_dash="dot", line_color=ui.TEXT_MUTED, annotation_text=ref_label,
                      annotation_position="top", annotation_font_color=ui.TEXT_MUTED)
    fig.update_layout(title=title)
    fig.update_xaxes(showgrid=False, showticklabels=False, range=[0, d[value].max() * 1.18 if len(d) else 1])
    return ui.style(fig, height=_hbar_height(len(d)), legend=False)


def team_legend(names: dict[str, str]) -> str:
    return " · ".join(f"<span style='color:{ui.TEAM_COLORS[t]}'>■</span> {names[t]}" for t in ("A", "B"))


def score_progression(rt: pd.DataFrame, names: dict[str, str]) -> go.Figure:
    """Marcador acumulado de cada equipo ronda a ronda, con el cambio de lado marcado."""
    fig = go.Figure()
    for t in ("A", "B"):
        y = rt[f"score_{t.lower()}"]
        fig.add_scatter(x=rt["round"], y=y, mode="lines+markers", name=names[t], line=dict(color=ui.TEAM_COLORS[t], width=3,
                        shape="hv"), marker=dict(size=7), hovertemplate="Ronda %{x}: %{y} rondas<extra>" + names[t] + "</extra>")
        fig.add_annotation(x=rt["round"].iloc[-1], y=y.iloc[-1], text=f"<b>{names[t]} {y.iloc[-1]}</b>", showarrow=False,
                           xanchor="left", xshift=8, font=dict(color=ui.TEAM_COLORS[t], size=13))
    for cut, text in _side_switches(rt):
        fig.add_vline(x=cut, line_dash="dot", line_color=ui.TEXT_MUTED, annotation_text=text,
                      annotation_position="top left", annotation_font_color=ui.TEXT_MUTED)
    fig.update_layout(title="¿Cómo se fue dando el marcador?", margin=dict(r=120))
    fig.update_xaxes(dtick=1, title="Ronda", showgrid=False, range=[0.5, rt["round"].max() + 0.5])
    fig.update_yaxes(title="Rondas ganadas", rangemode="tozero")
    return ui.style(fig, height=320, legend=False)


def _side_switches(rt: pd.DataFrame) -> list[tuple[float, str]]:
    """Rondas antes de las cuales los equipos cambian de lado (halftime, overtime)."""
    out = []
    side = rt.set_index("round")["ct_team"]
    for r in side.index[1:]:
        if side[r] != side.get(r - 1, side[r]):
            out.append((r - 0.5, "cambio de lado"))
    return out


def round_strip(rt: pd.DataFrame, names: dict[str, str]) -> go.Figure:
    """Una celda por ronda: color = quién la ganó, ícono = cómo terminó."""
    icons = rt["reason_code"].map(ROUND_ICONS).fillna("•")
    fig = go.Figure()
    for t in ("A", "B"):
        m = rt["winner_team"] == t
        sub = rt[m]
        fig.add_bar(x=sub["round"], y=[1] * len(sub), name=names[t], marker_color=ui.TEAM_COLORS[t],
                    text=icons[m], textposition="inside", insidetextanchor="middle", textfont=dict(size=16),
                    customdata=sub[["reason", "winner_side", "score_a", "score_b"]],
                    hovertemplate="Ronda %{x}: gana " + names[t] + " de %{customdata[1]}<br>%{customdata[0]}"
                                  "<br>Marcador %{customdata[2]}-%{customdata[3]}<extra></extra>")
    for cut, _ in _side_switches(rt):
        fig.add_vline(x=cut, line_dash="dot", line_color=ui.TEXT_MUTED)
    fig.update_layout(title="¿Quién ganó cada ronda y cómo?", bargap=0.08)
    fig.update_yaxes(visible=False)
    fig.update_xaxes(dtick=1, title="Ronda", showgrid=False)
    return ui.style(fig, height=190)


def economy_lines(rt: pd.DataFrame, names: dict[str, str]) -> go.Figure:
    """Valor de equipo por ronda sobre bandas de tipo de compra. Punto lleno = ganó la ronda."""
    fig = go.Figure()
    top = max(rt[["equip_a", "equip_b"]].max().max() * 1.1, 26_000)
    bands = [(0, 5_000, "Eco"), (5_000, 10_000, "Semi-eco"), (10_000, 20_000, "Force"), (20_000, top, "Full buy")]
    for i, (lo, hi, label) in enumerate(bands):
        fig.add_hrect(y0=lo, y1=hi, fillcolor="rgba(255,255,255,0.035)" if i % 2 else "rgba(0,0,0,0)", line_width=0,
                      annotation_text=label, annotation_position="left", annotation_font_color=ui.TEXT_MUTED,
                      annotation_font_size=11)
    for t in ("A", "B"):
        won = rt["winner_team"] == t
        fig.add_scatter(x=rt["round"], y=rt[f"equip_{t.lower()}"], mode="lines+markers", name=names[t],
                        line=dict(color=ui.TEAM_COLORS[t], width=2),
                        marker=dict(size=10, color=[ui.TEAM_COLORS[t] if w else "#1a1a19" for w in won],
                                    line=dict(width=2, color=ui.TEAM_COLORS[t])),
                        customdata=np.stack([rt[f"buy_{t.lower()}"], np.where(won, "ganó", "perdió")], axis=1),
                        hovertemplate="Ronda %{x}: $%{y:,.0f} (%{customdata[0]}) · %{customdata[1]}<extra>" + names[t] + "</extra>")
    for cut, text in _side_switches(rt):
        fig.add_vline(x=cut, line_dash="dot", line_color=ui.TEXT_MUTED)
    fig.update_layout(title="¿Con cuánta plata jugó cada equipo cada ronda?", margin=dict(l=70))
    fig.update_xaxes(dtick=1, title="Ronda", showgrid=False, range=[0.5, rt["round"].max() + 0.5])
    fig.update_yaxes(title="", tickformat="$,.0f", range=[0, top], showgrid=False)
    return ui.style(fig, height=380)


def buy_win_bars(bp: pd.DataFrame, names: dict[str, str], order: list[str]) -> go.Figure:
    """Para cada tipo de compra: cuántas rondas ganó cada equipo de las que jugó así."""
    agg = bp.groupby(["team", "buy"]).agg(n=("won", "size"), w=("won", "sum")).reset_index()
    fig = go.Figure()
    present = [b for b in order if b in set(agg["buy"])]
    for t in ("A", "B"):
        sub = agg[agg["team"] == t].set_index("buy").reindex(present)
        pct = 100 * sub["w"] / sub["n"]
        fig.add_bar(y=present, x=pct.fillna(0), orientation="h", name=names[t], marker_color=ui.TEAM_COLORS[t],
                    text=[f"{int(w)} de {int(n)}" if pd.notna(n) else "—" for w, n in zip(sub["w"], sub["n"])],
                    textposition="outside", hovertemplate="%{y}: %{x:.0f}% (%{text})<extra>" + names[t] + "</extra>")
    fig.update_layout(title="¿Cuántas rondas gana cada equipo según lo que compró?", barmode="group")
    fig.update_xaxes(range=[0, 118], ticksuffix="%", title="", showgrid=False)
    fig.update_yaxes(autorange="reversed")
    return ui.style(fig, height=90 + 60 * len(present))


def damage_by_round(pr: pd.DataFrame, adr: float) -> go.Figure:
    """Daño por ronda, kills escritas arriba (2K, 3K…), color por lado, línea de ADR."""
    fig = go.Figure()
    for side in ("CT", "T"):
        sub = pr[pr["side"] == side]
        text = [(f"{int(k)}K" if k > 0 else "") + (" 💀" if not s else "") for k, s in zip(sub["kills"], sub["survived"])]
        fig.add_bar(x=sub["round"], y=sub["damage"], name=f"jugando de {side}", marker_color=ui.SIDE_COLORS[side],
                    text=text, textposition="outside",
                    hovertemplate="Ronda %{x}: %{y} de daño<extra></extra>")
    fig.add_hline(y=adr, line_dash="dot", line_color=ui.TEXT_MUTED, annotation_text=f"ADR {adr:.0f}",
                  annotation_position="top left", annotation_font_color=ui.TEXT_MUTED)
    fig.update_layout(title="¿En qué rondas pegó y en cuáles no?")
    fig.update_xaxes(dtick=1, title="Ronda", showgrid=False)
    fig.update_yaxes(title="Daño", range=[0, max(pr["damage"].max() * 1.25, adr * 1.5, 100)])
    return ui.style(fig, height=320)


def head_to_head(kills: pd.DataFrame, players: pd.DataFrame, names: dict[str, str]) -> go.Figure | None:
    """Cada jugador de A contra cada jugador de B: 'kills-muertes' en la celda, color = quién domina."""
    k = kills[kills["is_enemy_kill"]]
    a = players.loc[players["team"] == "A", "name"].tolist()
    b = players.loc[players["team"] == "B", "name"].tolist()
    if not a or not b:
        return None
    ab = pd.crosstab(k["attacker_name"], k["victim_name"]).reindex(index=a + b, columns=a + b, fill_value=0)
    won = ab.loc[a, b].to_numpy()          # A mató a B
    lost = ab.loc[b, a].to_numpy().T       # B mató a A
    diff = won - lost
    lim = max(1, np.abs(diff).max())
    text = [[f"{w}-{l}" for w, l in zip(rw, rl)] for rw, rl in zip(won, lost)]
    scale = [[0, ui.TEAM_COLORS["B"]], [0.5, NEUTRAL], [1, ui.TEAM_COLORS["A"]]]
    fig = go.Figure(go.Heatmap(z=diff, x=b, y=a, text=text, texttemplate="%{text}", textfont=dict(size=14, color="#f0efec"),
                               colorscale=scale, zmin=-lim, zmax=lim, showscale=False, xgap=3, ygap=3,
                               hovertemplate="%{y} vs %{x}: %{text}<extra></extra>"))
    fig.update_layout(title=f"¿Quién le gana a quién? ({names['A']} en filas, {names['B']} en columnas)",
                      margin=dict(t=100))
    fig.update_xaxes(side="top", showgrid=False)
    fig.update_yaxes(autorange="reversed", showgrid=False)
    return ui.style(fig, height=140 + 52 * len(a), legend=False)


def opening_bars(kills: pd.DataFrame, players: pd.DataFrame) -> go.Figure:
    """Duelos de apertura por jugador: ganados a la derecha, perdidos a la izquierda."""
    o = kills[kills["is_opening"]]
    won = o.groupby("attacker_name").size()
    lost = o.groupby("victim_name").size()
    df = pd.DataFrame({"name": players["name"], "team": players["team"]})
    df["won"] = df["name"].map(won).fillna(0).astype(int)
    df["lost"] = df["name"].map(lost).fillna(0).astype(int)
    df = df[(df["won"] + df["lost"]) > 0].sort_values(["won", "lost"], ascending=[True, False])
    fig = go.Figure()
    fig.add_bar(y=df["name"], x=df["won"], orientation="h", name="Ganó la apertura", marker_color="#2a78d6",
                text=df["won"].replace(0, ""), textposition="outside", hovertemplate="%{y}: ganó %{x}<extra></extra>")
    fig.add_bar(y=df["name"], x=-df["lost"], orientation="h", name="Murió primero", marker_color="#8a8984",
                text=df["lost"].replace(0, ""), textposition="outside", hovertemplate="%{y}: murió primero %{text}<extra></extra>")
    lim = max(1, df[["won", "lost"]].max().max()) * 1.3
    fig.update_layout(title="¿Quién abre las rondas, y le sale bien?", barmode="relative")
    fig.update_xaxes(range=[-lim, lim], showticklabels=False, showgrid=False, zeroline=True, zerolinecolor=ui.TEXT_MUTED)
    return ui.style(fig, height=_hbar_height(len(df)))


def aim_type_bars(duels: pd.DataFrame, names: dict[str, str]) -> go.Figure:
    """Para cada jugador, cómo ganó sus duelos: pre-aim / ajuste / flick / prefire (en %)."""
    d = duels[duels["aim_type"] != "sin dato"].copy()
    d["name"] = d["attacker_steamid"].map(names)
    tab = pd.crosstab(d["name"], d["aim_type"], normalize="index") * 100
    tab = tab.reindex(columns=[c for c in AIM_TYPE_COLORS if c in tab.columns]).fillna(0)
    counts = d.groupby("name").size()
    tab = tab.loc[tab.get("pre-aim", pd.Series(0, index=tab.index)).sort_values().index]
    fig = go.Figure()
    for t in tab.columns:
        fig.add_bar(y=[f"{n} ({counts[n]})" for n in tab.index], x=tab[t], orientation="h", name=t,
                    marker_color=AIM_TYPE_COLORS[t], text=[f"{v:.0f}%" if v >= 12 else "" for v in tab[t]],
                    textposition="inside", insidetextanchor="middle",
                    hovertemplate="%{y}: %{x:.0f}% " + t + "<extra></extra>")
    fig.update_layout(title="¿Cómo gana sus duelos cada jugador?", barmode="stack", legend_traceorder="normal")
    fig.update_xaxes(range=[0, 100], ticksuffix="%", showgrid=False)
    return ui.style(fig, height=_hbar_height(len(tab)) + 30)


def highlight_cards(items: list[tuple[str, str, str]]) -> None:
    """Fila de tarjetas 'destacados': (título, jugador, dato)."""
    cols = st.columns(len(items))
    for col, (title, who, value) in zip(cols, items):
        col.markdown(
            f"<div style='border:1px solid rgba(255,255,255,.12);border-radius:10px;padding:10px 12px'>"
            f"<div style='font-size:.8rem;color:{ui.TEXT_MUTED}'>{title}</div>"
            f"<div style='font-size:1.15rem;font-weight:600;margin:2px 0'>{who}</div>"
            f"<div style='font-size:.9rem;color:{ui.TEXT_MUTED}'>{value}</div></div>", unsafe_allow_html=True)


def player_archetype_radar(scores: dict[str, float], avg_scores: dict[str, float] | None = None,
                           player_name: str = "", player_color: str = "#ffd166",
                           compare_scores: dict[str, float] | None = None,
                           compare_name: str = "", compare_color: str = "#3987e5",
                           title: str | None = None) -> go.Figure:
    """Gráfico de radar / araña de 6 dimensiones tácticas con opción de comparar lados (T vs CT)."""
    axes = list(scores.keys())
    r_player = [scores[k] for k in axes] + [scores[axes[0]]]
    theta = axes + [axes[0]]

    fig = go.Figure()

    if avg_scores:
        r_avg = [avg_scores.get(k, 50.0) for k in axes] + [avg_scores.get(axes[0], 50.0)]
        fig.add_trace(go.Scatterpolar(
            r=r_avg,
            theta=theta,
            name="Promedio match",
            line=dict(color="rgba(195, 194, 183, 0.45)", dash="dot", width=1.5),
            fill="toself",
            fillcolor="rgba(195, 194, 183, 0.05)",
            hovertemplate="Promedio · %{theta}: %{r:.0f} pts<extra></extra>",
        ))

    # Primer polígono (jugador o lado principal)
    fill_rgba = "rgba(217, 89, 38, 0.22)" if player_color == "#d95926" else "rgba(255, 209, 102, 0.20)"
    fig.add_trace(go.Scatterpolar(
        r=r_player,
        theta=theta,
        name=player_name or "Jugador",
        line=dict(color=player_color, width=2.5),
        fill="toself",
        fillcolor=fill_rgba,
        hovertemplate=f"{player_name} · %{{theta}}: %{{r:.0f}} pts<extra></extra>",
    ))

    # Segundo polígono opcional (ej: Lado CT)
    if compare_scores:
        r_comp = [compare_scores.get(k, 0.0) for k in axes] + [compare_scores.get(axes[0], 0.0)]
        comp_fill = "rgba(57, 135, 229, 0.22)" if compare_color == "#3987e5" else "rgba(255, 255, 255, 0.15)"
        fig.add_trace(go.Scatterpolar(
            r=r_comp,
            theta=theta,
            name=compare_name or "Comparación",
            line=dict(color=compare_color, width=2.5),
            fill="toself",
            fillcolor=comp_fill,
            hovertemplate=f"{compare_name} · %{{theta}}: %{{r:.0f}} pts<extra></extra>",
        ))

    chart_title = title or f"¿Cuál es el perfil táctico de {player_name}?"
    fig.update_layout(
        title=chart_title,
        polar=dict(
            radialaxis=dict(
                visible=True,
                range=[0, 100],
                tickvals=[25, 50, 75, 100],
                ticktext=["25", "50", "75", "100"],
                tickfont=dict(size=9, color="#8a8984"),
                gridcolor="rgba(255, 255, 255, 0.10)",
                linecolor="rgba(255, 255, 255, 0.15)",
            ),
            angularaxis=dict(
                gridcolor="rgba(255, 255, 255, 0.10)",
                linecolor="rgba(255, 255, 255, 0.15)",
                tickfont=dict(size=12, color="#f0efec"),
            ),
            bgcolor="rgba(0,0,0,0)",
        ),
    )
    return ui.style(fig, height=390, legend=True)
