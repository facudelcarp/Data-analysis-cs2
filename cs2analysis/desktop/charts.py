"""Gráficos nativos (pyqtgraph + QPainter).

Mismas reglas que tenían los de la app web:
- el título es una pregunta en lenguaje llano y el gráfico la responde sin necesidad de pasar el mouse;
- los valores van escritos sobre las barras o los puntos;
- donde sirve hay una línea de referencia (el promedio del partido, el rating 1.0, el 50 %).

Todos los gráficos son widgets de alto fijo (para apilarlos en una página con scroll) y sin zoom/arrastre,
salvo los mapas, que sí se pueden explorar con la rueda del mouse.
"""
from __future__ import annotations

import math
from html import escape

import numpy as np
import pandas as pd
import pyqtgraph as pg
from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QBrush, QColor, QFont, QPainter, QPen, QPolygonF
from PySide6.QtWidgets import QSizePolicy, QWidget

from ..palette import BORDER, MUTED, SERIES, SIDE_COLORS, SURFACE, TEAM_COLORS, TEXT

ROUND_ICONS = {1: "💣", 7: "✂", 8: "💀", 9: "💀", 12: "⏱", 17: "🏳", 18: "🏳"}
ROUND_ICON_LEGEND = "💀 eliminación · 💣 bomba detonada · ✂ bomba desactivada · ⏱ se acabó el tiempo · 🏳 rendición"
# Sin reutilizar los colores de equipo: de mejor (azul fuerte) a "no es aim" (gris)
AIM_TYPE_COLORS = {"pre-aim": "#2a78d6", "ajuste": "#86b6ef", "flick": "#c98500", "prefire": "#52514e"}
NEUTRAL = "#52514e"
WHITE = "#f0efec"
LOSE_FILL = "#1a1a19"


# --------------------------------------------------------------------------------------------
# Base
# --------------------------------------------------------------------------------------------

def _set_title(w: pg.PlotWidget, title: str, legend_html: str = "") -> None:
    html = f"<span style='color:{TEXT};font-size:11pt'>{escape(title)}</span>" if title else ""
    if legend_html:
        html += ("<br>" if html else "") + f"<span style='font-size:9pt'>{legend_html}</span>"
    w.setTitle(html or None)


def plot(title: str = "", height: int = 320, interactive: bool = False) -> pg.PlotWidget:
    w = pg.PlotWidget()
    w.chart_title = title
    if title:
        _set_title(w, title)
    w.setMenuEnabled(False)
    w.setMouseEnabled(x=interactive, y=interactive)
    w.hideButtons()
    w.getPlotItem().getViewBox().setBorder(pg.mkPen(BORDER))
    for ax in ("left", "bottom"):
        w.getAxis(ax).setTextPen(pg.mkPen(MUTED))
        w.getAxis(ax).setPen(pg.mkPen(BORDER))
    w.setFixedHeight(height)
    return w


def text(w: pg.PlotWidget, x: float, y: float, s: str, color: str = WHITE, anchor=(0.5, 0.5), size: int | None = None,
         bold: bool = False) -> pg.TextItem:
    t = pg.TextItem(s, color=color, anchor=anchor)
    if size or bold:
        f = QFont()
        if size:
            f.setPointSize(size)
        f.setBold(bold)
        t.setFont(f)
    t.setPos(x, y)
    w.addItem(t)
    return t


def vline(w: pg.PlotWidget, x: float, label: str = "", label_y: float | None = None) -> None:
    w.addItem(pg.InfiniteLine(pos=x, angle=90, pen=pg.mkPen(MUTED, style=Qt.DotLine)))
    if label and label_y is not None:
        text(w, x, label_y, label, MUTED)


def hline(w: pg.PlotWidget, y: float, label: str = "", label_x: float | None = None) -> None:
    w.addItem(pg.InfiniteLine(pos=y, angle=0, pen=pg.mkPen(MUTED, style=Qt.DotLine)))
    if label and label_x is not None:
        text(w, label_x, y, label, MUTED, anchor=(0, 1))


def category_axis(w: pg.PlotWidget, axis: str, labels: list[str], positions=None) -> None:
    pos = range(len(labels)) if positions is None else positions
    ax = w.getAxis(axis)
    ax.setTicks([[(float(p), str(lbl)) for p, lbl in zip(pos, labels, strict=True)]])
    ax.setTextPen(pg.mkPen(TEXT))
    if axis == "left" and labels:
        # pyqtgraph oculta las etiquetas que no entran: el eje se ensancha según la más larga
        from PySide6.QtGui import QFontMetrics
        ax.setWidth(QFontMetrics(ax.font()).horizontalAdvance(max(map(str, labels), key=len)) + 16)


def legend(w: pg.PlotWidget, items: list[tuple[str, str]]) -> None:
    """Leyenda como una línea debajo del título: [(nombre, color)]."""
    html = " &nbsp; ".join(f"<span style='color:{c}'>■</span> <span style='color:{MUTED}'>{escape(str(n))}</span>"
                           for n, c in items)
    _set_title(w, getattr(w, "chart_title", ""), html)


def _hbar_height(n: int) -> int:
    return 70 + 26 * max(n, 2)


def hbars(labels: list[str], values, colors, texts: list[str] | None = None, title: str = "",
          ref: float | None = None, ref_label: str = "", xmax: float | None = None, text_inside: bool = True,
          height: int | None = None) -> pg.PlotWidget:
    """Barras horizontales; el primer elemento queda arriba."""
    vals = np.asarray(values, dtype=float)
    n = len(vals)
    ys = np.arange(n)[::-1].astype(float)
    colors = colors if isinstance(colors, list) else [colors] * n
    w = plot(title, height or _hbar_height(n) + (18 if ref_label else 0))
    w.addItem(pg.BarGraphItem(x0=0, y=ys, height=0.7, width=np.nan_to_num(vals), brushes=[pg.mkBrush(c) for c in colors],
                              pen=pg.mkPen(None)))
    top = float(np.nanmax(vals)) if n and np.isfinite(vals).any() else 1.0
    top = xmax or (top * (1.08 if text_inside else 1.3)) or 1.0
    for y, v, s in zip(ys, vals, texts or [f"{v:.2f}" for v in vals], strict=True):
        if not s:
            continue
        inside = text_inside and np.isfinite(v) and v > top * 0.12
        text(w, (v if np.isfinite(v) else 0) + (0 if inside else top * 0.01), y, s, "#ffffff" if inside else WHITE,
             anchor=(1.05, 0.5) if inside else (0, 0.5))
    if ref is not None and np.isfinite(ref):
        vline(w, ref, ref_label, n - 0.05 if ref_label else None)
    category_axis(w, "left", list(labels), ys)
    w.hideAxis("bottom")
    w.setXRange(0, top, padding=0)
    w.setYRange(-0.6, n - 0.4 + (0.6 if ref_label else 0), padding=0)
    return w


def ranking_bars(df: pd.DataFrame, value: str, label: str, color_col: str | None = None, colors: dict | None = None,
                 fmt: str = "{:.2f}", ref: float | None = None, ref_label: str = "", lower_is_better: bool = False,
                 title: str = "") -> pg.PlotWidget:
    """Barras horizontales ordenadas (lo mejor arriba), con el valor escrito y una línea de referencia."""
    d = df.dropna(subset=[value]).sort_values(value, ascending=lower_is_better)
    c = [colors.get(x, SERIES[0]) for x in d[color_col]] if color_col and colors else SERIES[0]
    return hbars(d[label].astype(str).tolist(), d[value], c, [fmt.format(v) for v in d[value]], title=title,
                 ref=ref, ref_label=ref_label)


def count_bars(labels, values, title: str, color: str | None = None, total: float | None = None,
               fmt_count: str = "{:.0f}") -> pg.PlotWidget:
    """Barras horizontales simples con el valor (y el % si hay total); de mayor a menor."""
    df = pd.DataFrame({"l": list(labels), "v": list(values)}).sort_values("v", ascending=False)
    texts = [fmt_count.format(v) + (f" ({100 * v / total:.0f}%)" if total else "") for v in df["v"]]
    return hbars(df["l"].astype(str).tolist(), df["v"], color or SERIES[0], texts, title=title, text_inside=False)


def vbars(labels: list[str], values, colors, texts: list[str] | None = None, title: str = "", height: int = 300,
          ref: float | None = None, ref_label: str = "", ymax: float | None = None, show_y: bool = False) -> pg.PlotWidget:
    vals = np.asarray(values, dtype=float)
    xs = np.arange(len(vals)).astype(float)
    colors = colors if isinstance(colors, list) else [colors] * len(vals)
    w = plot(title, height)
    w.addItem(pg.BarGraphItem(x=xs, y0=0, width=0.7, height=np.nan_to_num(vals), brushes=[pg.mkBrush(c) for c in colors],
                              pen=pg.mkPen(None)))
    top = ymax or (float(np.nanmax(vals)) * 1.3 if len(vals) and np.isfinite(vals).any() else 1.0) or 1.0
    for x, v, s in zip(xs, vals, texts or [""] * len(vals), strict=True):
        if s:
            text(w, x, (v if np.isfinite(v) else 0) + top * 0.01, s, WHITE, anchor=(0.5, 1))
    if ref is not None:
        hline(w, ref, ref_label, -0.45)
    category_axis(w, "bottom", list(labels), xs)
    if not show_y:
        w.hideAxis("left")
    w.setXRange(-0.6, len(vals) - 0.4, padding=0)
    w.setYRange(0, top, padding=0)
    return w


def side_split(df: pd.DataFrame, value: str, title: str, fmt: str = "{:.1f}", extra: str | None = None) -> pg.PlotWidget:
    """CT vs T lado a lado (df con columna 'side'), valor escrito y dato extra opcional."""
    d = df.set_index("side").reindex(["CT", "T"]).dropna(subset=[value]).reset_index()
    texts = [fmt.format(v) + (f"  ({e})" if extra else "") for v, e in zip(d[value], d[extra] if extra else [""] * len(d),
                                                                           strict=True)]
    return vbars(d["side"].tolist(), d[value], [SIDE_COLORS[s] for s in d["side"]], texts, title=title)


# --------------------------------------------------------------------------------------------
# Rondas y economía
# --------------------------------------------------------------------------------------------

def side_switches(rt: pd.DataFrame) -> list[float]:
    """Rondas antes de las cuales los equipos cambian de lado (halftime, overtime)."""
    side = rt.set_index("round")["ct_team"]
    return [r - 0.5 for r in side.index[1:] if side[r] != side.get(r - 1, side[r])]


def score_progression(rt: pd.DataFrame, names: dict[str, str]) -> pg.PlotWidget:
    """Marcador acumulado de cada equipo ronda a ronda, con el cambio de lado marcado."""
    w = plot("¿Cómo se fue dando el marcador?", 320)
    x = rt["round"].to_numpy(dtype=float)
    top = 1
    for t in ("A", "B"):
        y = rt[f"score_{t.lower()}"].to_numpy(dtype=float)
        top = max(top, y.max())
        c = TEAM_COLORS[t]
        w.plot(np.append(x - 0.5, x[-1] + 0.5), y, stepMode="center", pen=pg.mkPen(c, width=3))
        w.addItem(pg.ScatterPlotItem(x, y, size=8, brush=pg.mkBrush(c), pen=pg.mkPen(None), hoverable=True,
                                     tip=lambda x, y, data, n=names[t]: f"Ronda {x:.0f}: {n} {y:.0f}"))
        text(w, x[-1] + 0.4, y[-1], f"{names[t]} {int(y[-1])}", c, anchor=(0, 0.5), bold=True)
    for cut in side_switches(rt):
        vline(w, cut, "cambio de lado", top + 0.8)
    w.setXRange(0.5, x.max() + 3.5, padding=0)
    w.setYRange(0, top + 1.5, padding=0)
    w.getAxis("bottom").setTickSpacing(major=1, minor=1)
    w.setLabel("bottom", "Ronda")
    w.setLabel("left", "Rondas ganadas")
    return w


def round_strip(rt: pd.DataFrame, names: dict[str, str]) -> pg.PlotWidget:
    """Una celda por ronda: color = quién la ganó, ícono = cómo terminó."""
    w = plot("¿Quién ganó cada ronda y cómo?", 170)
    x = rt["round"].to_numpy(dtype=float)
    colors = [TEAM_COLORS.get(t, NEUTRAL) for t in rt["winner_team"]]
    w.addItem(pg.BarGraphItem(x=x, y0=0, height=1, width=0.92, brushes=[pg.mkBrush(c) for c in colors],
                              pen=pg.mkPen(None)))
    for xi, code in zip(x, rt["reason_code"], strict=True):
        text(w, xi, 0.5, ROUND_ICONS.get(code, "•"), "#ffffff", size=11)
    for cut in side_switches(rt):
        vline(w, cut)
    legend(w, [(names["A"], TEAM_COLORS["A"]), (names["B"], TEAM_COLORS["B"])])
    w.hideAxis("left")
    w.getAxis("bottom").setTickSpacing(major=1, minor=1)
    w.setXRange(x.min() - 0.5, x.max() + 0.5, padding=0)
    w.setYRange(0, 1, padding=0)
    return w


def economy_lines(rt: pd.DataFrame, names: dict[str, str]) -> pg.PlotWidget:
    """Valor de equipo por ronda sobre bandas de tipo de compra. Punto lleno = ganó la ronda."""
    w = plot("¿Con cuánta plata jugó cada equipo cada ronda?", 380)
    x = rt["round"].to_numpy(dtype=float)
    top = max(float(rt[["equip_a", "equip_b"]].max().max()) * 1.1, 26_000)
    for i, (lo, hi, label) in enumerate([(0, 5_000, "Eco"), (5_000, 10_000, "Semi-eco"), (10_000, 20_000, "Force"),
                                         (20_000, top, "Full buy")]):
        if i % 2:
            w.addItem(pg.LinearRegionItem((lo, hi), orientation="horizontal", movable=False,
                                          brush=pg.mkBrush(255, 255, 255, 9), pen=pg.mkPen(None)))
        text(w, 0.55, (lo + hi) / 2, label, MUTED, anchor=(0, 0.5))
    for t in ("A", "B"):
        y = rt[f"equip_{t.lower()}"].to_numpy(dtype=float)
        won = (rt["winner_team"] == t).to_numpy()
        c = TEAM_COLORS[t]
        w.plot(x, y, pen=pg.mkPen(c, width=2))
        buys = rt[f"buy_{t.lower()}"].tolist()
        w.addItem(pg.ScatterPlotItem(x, y, size=10, pen=pg.mkPen(c, width=2),
                                     brush=[pg.mkBrush(c if wn else LOSE_FILL) for wn in won], data=list(range(len(x))),
                                     hoverable=True,
                                     tip=lambda x, y, data, n=names[t], b=buys, wn=won:
                                     f"{n} · ronda {x:.0f}: ${y:,.0f} ({b[data]}) · {'ganó' if wn[data] else 'perdió'}"))
    for cut in side_switches(rt):
        vline(w, cut)
    legend(w, [(names["A"], TEAM_COLORS["A"]), (names["B"], TEAM_COLORS["B"])])
    w.getAxis("bottom").setTickSpacing(major=1, minor=1)
    w.getAxis("left").setTicks([[(v, f"${v / 1000:.0f}k") for v in range(0, int(top) + 1, 5000)]])
    w.setXRange(0.5, x.max() + 0.5, padding=0)
    w.setYRange(0, top, padding=0)
    w.setLabel("bottom", "Ronda")
    return w


def buy_win_bars(bp: pd.DataFrame, names: dict[str, str], order: list[str]) -> pg.PlotWidget:
    """Para cada tipo de compra: cuántas rondas ganó cada equipo de las que jugó así."""
    agg = bp.groupby(["team", "buy"]).agg(n=("won", "size"), w=("won", "sum")).reset_index()
    present = [b for b in order if b in set(agg["buy"])]
    n = len(present)
    w = plot("¿Cuántas rondas gana cada equipo según lo que compró?", 90 + 56 * max(n, 1))
    ys = np.arange(n)[::-1].astype(float)
    for off, t in ((0.19, "A"), (-0.19, "B")):
        sub = agg[agg["team"] == t].set_index("buy").reindex(present)
        pct = (100 * sub["w"] / sub["n"]).fillna(0).to_numpy()
        w.addItem(pg.BarGraphItem(x0=0, y=ys + off, height=0.36, width=pct, brush=pg.mkBrush(TEAM_COLORS[t]),
                                  pen=pg.mkPen(None)))
        for y, p, wv, nv in zip(ys + off, pct, sub["w"], sub["n"], strict=True):
            text(w, p + 1, y, f"{int(wv)} de {int(nv)}" if pd.notna(nv) else "—", WHITE, anchor=(0, 0.5))
    legend(w, [(names["A"], TEAM_COLORS["A"]), (names["B"], TEAM_COLORS["B"])])
    category_axis(w, "left", present, ys)
    w.getAxis("bottom").setTicks([[(v, f"{v}%") for v in range(0, 101, 25)]])
    w.setXRange(0, 118, padding=0)
    w.setYRange(-0.6, n - 0.4, padding=0)
    return w


def damage_by_round(pr: pd.DataFrame, adr: float) -> pg.PlotWidget:
    """Daño por ronda, kills escritas arriba (2K, 3K…), color por lado, línea de ADR."""
    w = plot("¿En qué rondas pegó y en cuáles no?", 320)
    top = max(float(pr["damage"].max()) * 1.25 if len(pr) else 0, adr * 1.5, 100)
    for side in ("CT", "T"):
        sub = pr[pr["side"] == side]
        w.addItem(pg.BarGraphItem(x=sub["round"].to_numpy(dtype=float), y0=0, width=0.75,
                                  height=sub["damage"].to_numpy(dtype=float), brush=pg.mkBrush(SIDE_COLORS[side]),
                                  pen=pg.mkPen(None)))
        for r, dmg, k, s in zip(sub["round"], sub["damage"], sub["kills"], sub["survived"], strict=True):
            label = (f"{int(k)}K" if k > 0 else "") + (" 💀" if not s else "")
            if label:
                text(w, r, dmg + top * 0.01, label.strip(), WHITE, anchor=(0.5, 1))
    w.addItem(pg.InfiniteLine(pos=adr, angle=0, pen=pg.mkPen(MUTED, style=Qt.DotLine)))
    if len(pr):
        text(w, pr["round"].max() + 0.45, adr, f"ADR {adr:.0f}", MUTED, anchor=(1, 1))
    legend(w, [("jugando de CT", SIDE_COLORS["CT"]), ("jugando de T", SIDE_COLORS["T"])])
    w.getAxis("bottom").setTickSpacing(major=1, minor=1)
    if len(pr):
        w.setXRange(pr["round"].min() - 0.5, pr["round"].max() + 0.5, padding=0)
    w.setYRange(0, top, padding=0)
    w.setLabel("bottom", "Ronda")
    return w


# --------------------------------------------------------------------------------------------
# Duelos y aim
# --------------------------------------------------------------------------------------------

def _mix(c1: str, c2: str, t: float) -> QColor:
    a, b = QColor(c1), QColor(c2)
    return QColor(round(a.red() + (b.red() - a.red()) * t), round(a.green() + (b.green() - a.green()) * t),
                  round(a.blue() + (b.blue() - a.blue()) * t))


class MatrixWidget(QWidget):
    """Matriz con texto por celda y color divergente (negativo = color_neg, positivo = color_pos)."""

    def __init__(self, rows: list[str], cols: list[str], values: np.ndarray, texts: list[list[str]], title: str,
                 color_pos: str, color_neg: str, parent=None):
        super().__init__(parent)
        self.rows, self.cols, self.values, self.texts, self.title = rows, cols, values, texts, title
        self.color_pos, self.color_neg = color_pos, color_neg
        self.lim = max(1.0, float(np.abs(values).max()) if values.size else 1.0)
        self.setFixedHeight(90 + 40 * len(rows))
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

    def paintEvent(self, _):  # noqa: N802 (API de Qt)
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.fillRect(self.rect(), QColor(SURFACE))
        fm = p.fontMetrics()
        left = max((fm.horizontalAdvance(r) for r in self.rows), default=0) + 20
        top = 62
        cw = (self.width() - left - 10) / max(1, len(self.cols))
        ch = 40
        f = p.font()
        f.setPointSize(11)
        f.setBold(True)
        p.setFont(f)
        p.setPen(QColor(TEXT))
        p.drawText(QRectF(0, 4, self.width(), 24), Qt.AlignHCenter | Qt.AlignVCenter, self.title)
        f.setPointSize(9)
        f.setBold(False)
        p.setFont(f)
        for j, c in enumerate(self.cols):
            p.setPen(QColor(self.color_neg))
            p.drawText(QRectF(left + j * cw, 34, cw, 24), Qt.AlignCenter, fm.elidedText(c, Qt.ElideRight, int(cw) - 4))
        for i, r in enumerate(self.rows):
            p.setPen(QColor(self.color_pos))
            p.drawText(QRectF(0, top + i * ch, left - 8, ch), Qt.AlignRight | Qt.AlignVCenter, r)
            for j in range(len(self.cols)):
                v = self.values[i, j] / self.lim
                color = _mix(NEUTRAL, self.color_pos if v > 0 else self.color_neg, min(1.0, abs(v)))
                cell = QRectF(left + j * cw + 2, top + i * ch + 2, cw - 4, ch - 4)
                p.setPen(Qt.NoPen)
                p.setBrush(color)
                p.drawRoundedRect(cell, 4, 4)
                p.setPen(QColor(WHITE))
                p.drawText(cell, Qt.AlignCenter, self.texts[i][j])
        p.end()


def head_to_head(kills: pd.DataFrame, players: pd.DataFrame, names: dict[str, str]) -> MatrixWidget | None:
    """Cada jugador de A contra cada jugador de B: 'kills-muertes' en la celda, color = quién domina."""
    k = kills[kills["is_enemy_kill"]]
    a = players.loc[players["team"] == "A", "name"].tolist()
    b = players.loc[players["team"] == "B", "name"].tolist()
    if not a or not b:
        return None
    ab = pd.crosstab(k["attacker_name"], k["victim_name"]).reindex(index=a + b, columns=a + b, fill_value=0)
    won = ab.loc[a, b].to_numpy()
    lost = ab.loc[b, a].to_numpy().T
    texts = [[f"{w}-{lo}" for w, lo in zip(rw, rl, strict=True)] for rw, rl in zip(won, lost, strict=True)]
    return MatrixWidget(a, b, (won - lost).astype(float), texts,
                        f"¿Quién le gana a quién? ({names['A']} en filas, {names['B']} en columnas)",
                        TEAM_COLORS["A"], TEAM_COLORS["B"])


def opening_bars(kills: pd.DataFrame, players: pd.DataFrame) -> pg.PlotWidget:
    """Duelos de apertura por jugador: ganados a la derecha, perdidos a la izquierda."""
    o = kills[kills["is_opening"]]
    df = pd.DataFrame({"name": players["name"]})
    df["won"] = df["name"].map(o.groupby("attacker_name").size()).fillna(0).astype(int)
    df["lost"] = df["name"].map(o.groupby("victim_name").size()).fillna(0).astype(int)
    df = df[(df["won"] + df["lost"]) > 0].sort_values(["won", "lost"], ascending=[False, True])
    n = len(df)
    ys = np.arange(n)[::-1].astype(float)
    w = plot("¿Quién abre las rondas, y le sale bien?", _hbar_height(n) + 10)
    w.addItem(pg.BarGraphItem(x0=0, y=ys, height=0.7, width=df["won"].to_numpy(), brush=pg.mkBrush("#2a78d6"),
                              pen=pg.mkPen(None)))
    w.addItem(pg.BarGraphItem(x0=-df["lost"].to_numpy(), y=ys, height=0.7, width=df["lost"].to_numpy(),
                              brush=pg.mkBrush("#8a8984"), pen=pg.mkPen(None)))
    lim = max(1, int(df[["won", "lost"]].max().max()) if n else 1) * 1.3
    for y, wv, lv in zip(ys, df["won"], df["lost"], strict=True):
        if wv:
            text(w, wv + lim * 0.02, y, str(wv), WHITE, anchor=(0, 0.5))
        if lv:
            text(w, -lv - lim * 0.02, y, str(lv), WHITE, anchor=(1, 0.5))
    w.addItem(pg.InfiniteLine(pos=0, angle=90, pen=pg.mkPen(MUTED)))
    legend(w, [("Ganó la apertura", "#2a78d6"), ("Murió primero", "#8a8984")])
    category_axis(w, "left", df["name"].tolist(), ys)
    w.hideAxis("bottom")
    w.setXRange(-lim, lim, padding=0)
    w.setYRange(-0.6, n - 0.4, padding=0)
    return w


def stacked_hbars(labels: list[str], parts: dict[str, np.ndarray], colors: dict[str, str], title: str,
                  pct_min: float = 12) -> pg.PlotWidget:
    """Barras horizontales apiladas al 100 %; el primer elemento queda arriba."""
    n = len(labels)
    ys = np.arange(n)[::-1].astype(float)
    w = plot(title, _hbar_height(n) + 20)
    left = np.zeros(n)
    for name, vals in parts.items():
        vals = np.asarray(vals, dtype=float)
        w.addItem(pg.BarGraphItem(x0=left, y=ys, height=0.7, width=vals, brush=pg.mkBrush(colors[name]), pen=pg.mkPen(None)))
        for x0, y, v in zip(left, ys, vals, strict=True):
            if v >= pct_min:
                text(w, x0 + v / 2, y, f"{v:.0f}%", "#ffffff")
        left = left + vals
    legend(w, [(k, colors[k]) for k in parts])
    category_axis(w, "left", labels, ys)
    w.getAxis("bottom").setTicks([[(v, f"{v}%") for v in range(0, 101, 25)]])
    w.setXRange(0, 100, padding=0)
    w.setYRange(-0.6, n - 0.4, padding=0)
    return w


def aim_type_bars(duels: pd.DataFrame, names: dict[str, str]) -> pg.PlotWidget:
    """Para cada jugador, cómo ganó sus duelos: pre-aim / ajuste / flick / prefire (en %)."""
    d = duels[duels["aim_type"] != "sin dato"].copy()
    d["name"] = d["attacker_steamid"].map(names)
    tab = pd.crosstab(d["name"], d["aim_type"], normalize="index") * 100
    tab = tab.reindex(columns=[c for c in AIM_TYPE_COLORS if c in tab.columns]).fillna(0)
    counts = d.groupby("name").size()
    tab = tab.loc[tab.get("pre-aim", pd.Series(0, index=tab.index)).sort_values(ascending=False).index]
    return stacked_hbars([f"{n} ({counts[n]})" for n in tab.index], {c: tab[c].to_numpy() for c in tab.columns},
                         AIM_TYPE_COLORS, "¿Cómo gana sus duelos cada jugador?")


def strip_box(groups: list[tuple[str, np.ndarray]], color: str, title: str, unit: str = "") -> pg.PlotWidget:
    """Distribución por grupo: caja (cuartiles + mediana) con todos los puntos encima. Primer grupo arriba."""
    n = len(groups)
    w = plot(title, 60 + 30 * max(n, 3))
    ys = np.arange(n)[::-1].astype(float)
    rng = np.random.default_rng(0)
    for y, (name, vals) in zip(ys, groups, strict=True):
        vals = vals[np.isfinite(vals)]
        if not len(vals):
            continue
        q1, med, q3 = np.percentile(vals, [25, 50, 75])
        w.addItem(pg.BarGraphItem(x0=q1, y=y, height=0.6, width=max(q3 - q1, 1e-6), brush=pg.mkBrush(color + "40"),
                                  pen=pg.mkPen(color, width=1.5)))
        w.plot([med, med], [y - 0.3, y + 0.3], pen=pg.mkPen(WHITE, width=2))
        w.addItem(pg.ScatterPlotItem(vals, y + rng.uniform(-0.22, 0.22, len(vals)), size=5,
                                     brush=pg.mkBrush(color + "99"), pen=pg.mkPen(None), hoverable=True,
                                     tip=lambda x, y, data, nm=name: f"{nm}: {x:.1f}{unit}"))
    category_axis(w, "left", [g[0] for g in groups], ys)
    w.setYRange(-0.6, n - 0.4, padding=0)
    return w


def scatter_groups(groups: list[tuple[str, np.ndarray, np.ndarray, list[str]]], colors: dict[str, str], title: str,
                   xlabel: str, ylabel: str, log_x: bool = False, height: int = 420) -> pg.PlotWidget:
    """Nube de puntos por grupo, con texto al pasar el mouse por cada punto: [(nombre, x, y, tips)]."""
    w = plot(title, height)
    for name, x, y, tips in groups:
        xs = np.log10(np.clip(x, 0.1, None)) if log_x else x
        w.addItem(pg.ScatterPlotItem(xs, y, size=9, brush=pg.mkBrush(colors[name]), pen=pg.mkPen(LOSE_FILL, width=1.5),
                                     data=tips, hoverable=True, tip=lambda x, y, data: data))
    legend(w, [(g[0], colors[g[0]]) for g in groups])
    if log_x:
        w.getAxis("bottom").setTicks([[(math.log10(v), f"{v:g}°") for v in (0.3, 1, 3, 10, 30)]])
    w.setLabel("bottom", xlabel)
    w.setLabel("left", ylabel)
    return w


def histogram(values: np.ndarray, bins: int, title: str, color: str = SERIES[0], ref: float | None = None,
              ref_label: str = "", height: int = 320) -> pg.PlotWidget:
    w = plot(title, height)
    counts, edges = np.histogram(values[np.isfinite(values)], bins=bins)
    w.addItem(pg.BarGraphItem(x0=edges[:-1], x1=edges[1:] - (edges[1] - edges[0]) * 0.08, y0=0, height=counts,
                              brush=pg.mkBrush(color), pen=pg.mkPen(None)))
    if ref is not None:
        vline(w, ref, ref_label, counts.max() * 1.05 if len(counts) else 1)
    w.setYRange(0, (counts.max() if len(counts) else 1) * 1.15, padding=0)
    return w


# --------------------------------------------------------------------------------------------
# Radar de arquetipo (polar)
# --------------------------------------------------------------------------------------------

class RadarChart(QWidget):
    """Gráfico de araña de N ejes (0-100). series: [(nombre, {eje: valor}, color, relleno, punteado)]."""

    def __init__(self, axes: list[str], series: list[tuple[str, dict, str, bool, bool]], title: str, parent=None):
        super().__init__(parent)
        self.axes, self.series, self.title = axes, series, title
        self.setFixedHeight(400)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

    def paintEvent(self, _):  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.fillRect(self.rect(), QColor(SURFACE))
        f = p.font()
        f.setPointSize(11)
        f.setBold(True)
        p.setFont(f)
        p.setPen(QColor(TEXT))
        p.drawText(QRectF(0, 4, self.width(), 24), Qt.AlignCenter, self.title)
        f.setPointSize(9)
        f.setBold(False)
        p.setFont(f)
        # leyenda
        x = 12.0
        for name, _, color, _, dashed in self.series:
            p.setPen(QPen(QColor(color), 3, Qt.DotLine if dashed else Qt.SolidLine))
            p.drawLine(QPointF(x, 42), QPointF(x + 18, 42))
            p.setPen(QColor(MUTED))
            p.drawText(QPointF(x + 24, 46), name)
            x += 34 + p.fontMetrics().horizontalAdvance(name)
        cx, cy = self.width() / 2, 60 + (self.height() - 60) / 2
        r = min(self.width() / 2 - 110, (self.height() - 60) / 2 - 30)
        n = len(self.axes)

        def pt(i, v):
            a = -math.pi / 2 + 2 * math.pi * i / n
            return QPointF(cx + r * v / 100 * math.cos(a), cy + r * v / 100 * math.sin(a))

        p.setPen(QPen(QColor(255, 255, 255, 30), 1))
        p.setBrush(Qt.NoBrush)
        for ring in (25, 50, 75, 100):
            p.drawPolygon(QPolygonF([pt(i, ring) for i in range(n)]))
        for i, ax in enumerate(self.axes):
            p.setPen(QPen(QColor(255, 255, 255, 30), 1))
            p.drawLine(QPointF(cx, cy), pt(i, 100))
            lp = pt(i, 118)
            p.setPen(QColor(WHITE))
            p.drawText(QRectF(lp.x() - 80, lp.y() - 10, 160, 20), Qt.AlignCenter, ax)
        for _, scores, color, fill, dashed in self.series:
            poly = QPolygonF([pt(i, float(scores.get(ax, 0))) for i, ax in enumerate(self.axes)])
            c = QColor(color)
            p.setPen(QPen(c, 1.5 if dashed else 2.5, Qt.DotLine if dashed else Qt.SolidLine))
            fc = QColor(c)
            fc.setAlpha(14 if dashed else 55)
            p.setBrush(QBrush(fc) if fill else Qt.NoBrush)
            p.drawPolygon(poly)
        p.end()


def player_archetype_radar(scores: dict[str, float], avg_scores: dict[str, float] | None = None,
                           player_name: str = "", player_color: str = "#ffd166",
                           compare_scores: dict[str, float] | None = None, compare_name: str = "",
                           compare_color: str = "#3987e5", title: str | None = None) -> RadarChart:
    series = []
    if avg_scores:
        series.append(("Promedio match", avg_scores, "#c3c2b7", True, True))
    series.append((player_name or "Jugador", scores, player_color, True, False))
    if compare_scores:
        series.append((compare_name or "Comparación", compare_scores, compare_color, True, False))
    return RadarChart(list(scores), series, title or f"¿Cuál es el perfil táctico de {player_name}?")


# --------------------------------------------------------------------------------------------
# Equipos, multi-demo y dashboard
# --------------------------------------------------------------------------------------------

def pct_bars(labels: list[str], values: list[float], colors: list[str], title: str, ref50: bool = True) -> pg.PlotWidget:
    return hbars(labels, values, colors, [f"{v:.1f}%" for v in values], title=title, ref=50.0 if ref50 else None,
                 ref_label="50%" if ref50 else "", xmax=105, height=170)


def trade_impact_bars(with_trades_pct: float, without_trades_pct: float, lift: float) -> pg.PlotWidget:
    sign = "+" if lift >= 0 else ""
    return pct_bars(["Con ≥1 tradeo", "Sin tradeos en ronda"], [with_trades_pct, without_trades_pct],
                    ["#06d6a0", "#8a8984"],
                    f"¿Cuánto influye conseguir tradeos en ganar la ronda? ({sign}{lift:.1f}% impacto)", ref50=False)


def advantage_conversion_bars(conv_5v4: float, rec_4v5: float) -> pg.PlotWidget:
    return pct_bars(["Conversión 5v4 (apertura ganada)", "Recuperación 4v5 (apertura perdida)"], [conv_5v4, rec_4v5],
                    [SIDE_COLORS["CT"], SIDE_COLORS["T"]], "¿Cómo capitaliza el equipo la ventaja de la primera baja?")


def team_side_winrates_bar(t_winrate: float, ct_winrate: float) -> pg.PlotWidget:
    return pct_bars(["Lado T (ataque)", "Lado CT (defensa)"], [t_winrate, ct_winrate],
                    [SIDE_COLORS["T"], SIDE_COLORS["CT"]], "Rendimiento del equipo por bando (T vs CT)")


def results_timeline(per: pd.DataFrame, metric: str = "rating2", ref: float = 1.0, label: str = "Rating") -> pg.PlotWidget:
    """Una métrica partida a partida, con victorias y derrotas diferenciadas y el valor escrito en cada punto."""
    w = plot(f"¿Cómo le fue partida a partida? ({label.lower()})", 340)
    x = np.arange(len(per)).astype(float)
    y = per[metric].to_numpy(dtype=float)
    w.plot(x, y, pen=pg.mkPen("#8a8984", width=1.5))
    styles = {"Victoria": (SERIES[2], True), "Derrota": (SIDE_COLORS["T"], False), "Empate": ("#c3c2b7", True)}
    for res, (color, filled) in styles.items():
        m = (per["Resultado"] == res).to_numpy()
        if not m.any():
            continue
        tips = [f"{p} · {mp} {sc}" for p, mp, sc in zip(per["Partida"][m], per["Mapa"][m], per["Marcador propio"][m],
                                                       strict=True)]
        w.addItem(pg.ScatterPlotItem(x[m], y[m], size=13, pen=pg.mkPen(color, width=2.5),
                                     brush=pg.mkBrush(color if filled else LOSE_FILL), data=tips, hoverable=True,
                                     tip=lambda x, y, data: data))
    for xi, yi in zip(x, y, strict=True):
        text(w, xi, yi, f"{yi:.2f}" if metric in ("rating2", "kd") else f"{yi:.0f}", WHITE, anchor=(0.5, 1.4))
    if ref is not None:
        hline(w, ref, f"{ref:g} = promedio", x.max() if len(x) else 0)
    legend(w, [(k, v[0]) for k, v in styles.items() if (per["Resultado"] == k).any()])
    lo, hi = np.nanmin(y), np.nanmax(y)
    pad = (hi - lo) * 0.25 + 0.15
    w.setYRange(min(lo, ref if ref is not None else lo) - pad, max(hi, ref if ref is not None else hi) + pad, padding=0)
    w.setXRange(-0.5, len(x) - 0.5, padding=0)
    category_axis(w, "bottom", per["Partida"].astype(str).tolist(), x)
    return w


def line_by_category(x_labels: list[str], series: list[tuple[str, np.ndarray, str]], title: str,
                     ylabel: str = "", height: int = 320) -> pg.PlotWidget:
    w = plot(title, height)
    x = np.arange(len(x_labels)).astype(float)
    for name, y, color in series:
        w.plot(x, y, pen=pg.mkPen(color, width=2), symbol="o", symbolBrush=color, symbolPen=None, symbolSize=7)
    legend(w, [(s[0], s[2]) for s in series])
    category_axis(w, "bottom", x_labels, x)
    w.setLabel("left", ylabel)
    return w


def compare_players(sub: pd.DataFrame, metrics: list[tuple[str, str, str, bool]], name_col: str = "name") -> QWidget:
    """Un mini gráfico por métrica, con los nombres escritos y ★ en el mejor. metrics: (col, título, formato, menos_es_mejor)."""
    from PySide6.QtWidgets import QGridLayout
    metrics = [m for m in metrics if m[0] in sub and sub[m[0]].notna().any()]
    box = QWidget()
    grid = QGridLayout(box)
    grid.setContentsMargins(0, 0, 0, 0)
    grid.setSpacing(8)
    names = sub[name_col].astype(str).tolist()
    for i, (col, title, fmt, lower) in enumerate(metrics):
        vals = sub[col]
        best = (vals.min() if lower else vals.max()) if vals.nunique() > 1 else None
        labels = [("—" if pd.isna(v) else fmt.format(v)) + (" ★" if v == best else "") for v in vals]
        colors = [SERIES[0] if v == best else NEUTRAL for v in vals]
        grid.addWidget(hbars(names, vals.fillna(0), colors, labels, title=title, text_inside=False), i // 3, i % 3)
    return box


def team_legend_html(names: dict[str, str]) -> str:
    return " · ".join(f"<span style='color:{TEAM_COLORS[t]}'>■</span> {escape(str(names[t]))}" for t in ("A", "B"))
