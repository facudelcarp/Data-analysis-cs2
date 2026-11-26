"""Informe de rival: una hoja por mapa con lo que el equipo hace (ver scouting.py), exportable a HTML."""
from __future__ import annotations

from pathlib import Path

import numpy as np

from PySide6.QtWidgets import QFileDialog, QLabel, QMessageBox, QPushButton, QWidget

from .. import scouting
from ..maps import pretty_map
from ..parser import DemoData
from .page import AsyncSlot, Page
from .widgets import DataTable

LINEUP_COLS = scouting.LINEUP_COLS


def build(demos: list[DemoData], instances: list[tuple[str, str]], map_name: str, team: str) -> QWidget:
    p = Page()
    by_id = {d.demo_id: d for d in demos}

    def job():
        inst = [i for i in instances if map_name == "Todos los mapas"
                or next((d.meta["map"] for d in demos if d.demo_id == i[0]), None) == map_name]
        return lambda: scouting.scout(demos, inst)

    p.add(AsyncSlot(job, lambda reps: _render(reps, team, by_id)))
    p.stretch()
    return p


def _render(reports: list[scouting.MapReport], team: str, demos: dict) -> QWidget:
    p = Page(margins=(0, 0, 0, 0))
    if not reports:
        p.info("Sin partidas de este equipo con los filtros elegidos.")
        return p
    export = QPushButton("Exportar informe (HTML)…")
    export.setObjectName("Primary")
    export.clicked.connect(lambda: _export(export, team, reports))
    p.row(QLabel(f"Una hoja por mapa con lo que {team} hace: para preparar el partido o pasárselo al equipo. "
                 "El HTML se abre en cualquier navegador y se imprime bien."), export, stretches=[4, 1])
    for r in reports:
        (tw, tn), (cw, cn) = r.rounds_t, r.rounds_ct
        p.section(f"{pretty_map(r.map)} · {r.matches} partida(s), ganó {r.wins} · T {scouting._rate(tw, tn)} · "
                  f"CT {scouting._rate(cw, cn)}")
        notes = QLabel("<ul style='margin:0 0 0 -20px'>" + "".join(f"<li>{_esc(n)}</li>" for n in r.notes) + "</ul>")
        notes.setWordWrap(True)
        notes.setObjectName("Notes")
        notes.setStyleSheet("QLabel#Notes { background: rgba(240,163,61,0.08); border-left: 3px solid #f0a33d; "
                            "padding: 8px 12px; border-radius: 4px; }")
        p.add(notes)
        p.row(_titled("Puestos", r.seats), _titled("Jugadores en este mapa", r.players, 2))
        p.row(_titled("Sitios atacados (T)", r.sites, 0), _titled("Planes de T", r.t_plan, 0))
        p.add(_titled("Setups de CT (A-Mid-B a los 15 s)", r.ct_setups, 0))
        p.sub("Playbook: cada plan sobre el mapa")
        p.add(playbook(demos, r))
        p.row(_titled("Pistolas", r.pistols), _titled("Granadas repetidas", r.lineups[[c for c in LINEUP_COLS if c in r.lineups]]
                                                      .rename(columns=LINEUP_COLS) if len(r.lineups) else r.lineups))
    p.note("puestos: el más jugado y en cuántas partidas (ver Multi-demo → Roles). Planes de T y setups de CT: "
           "lectura por posiciones (ver Demo individual → Tácticas → Estrategias por ronda). Granadas repetidas: mismo lanzamiento y destino "
           "en 2 o más rondas. «Rating*» es la aproximación de Rating 2.0 de la app.")
    return p


def _titled(title: str, df, decimals: int = 1) -> QWidget:
    box = Page(margins=(0, 0, 0, 0))
    box.sub(title)
    if df is None or df.empty:
        box.caption("Sin datos.")
    else:
        box.add(DataTable(df.reset_index(drop=True), fit_rows=len(df) <= 12, decimals=decimals)).setMinimumHeight(
            min(70 + 26 * len(df), 360))
    box.stretch()
    return box


def _esc(s: str) -> str:
    from html import escape
    return escape(str(s))


def _export(parent: QWidget, team: str, reports) -> None:
    safe = "".join(c if c.isalnum() else "_" for c in team)[:40] or "rival"
    path, _ = QFileDialog.getSaveFileName(parent, "Guardar informe de rival", f"informe_{safe}.html", "HTML (*.html)")
    if not path:
        return
    try:
        Path(path).write_text(scouting.to_html(team, reports), encoding="utf-8")
    except OSError as exc:
        QMessageBox.warning(parent, "No se pudo guardar", str(exc))


# --------------------------------------------------------------------------------------------
# Playbook: cada plan como jugada sobre el mapa
# --------------------------------------------------------------------------------------------

def playbook(demos: dict, r: scouting.MapReport) -> QWidget:
    """Elegís un plan T (o un setup CT) y se dibujan juntas todas las rondas en que el rival lo jugó."""
    from .. import strategy
    from .page import Segmented, Slot
    box = Page(margins=(0, 0, 0, 0))
    rounds = r.rounds
    if rounds is None or rounds.empty:
        box.caption("Sin lectura de estrategias para este mapa.")
        return box
    t_r = rounds[rounds["mine_t"]].assign(key=lambda x: strategy.plan_of(x))
    ct_r = rounds[~rounds["mine_t"]].assign(key=lambda x: x["ct_setup"] + np.where(x["ct_stack"] != "",
                                                                                    " · stack " + x["ct_stack"], ""))
    side = Segmented(["T", "CT"], label="Lado")

    def items(df):
        vc = df["key"].value_counts()
        return [(k, f"{k} ({n} ronda{'s' if n != 1 else ''})") for k, n in vc.items()]

    box.row(side, QWidget(), stretches=[1, 4])
    holder = box.add(Slot(lambda: _plays(demos, t_r if side.value == "T" else ct_r, side.value, items)))
    side.changed.connect(holder.refresh)
    return box


def _plays(demos: dict, df, side: str, items) -> QWidget:
    from .page import Combo, Slot
    p = Page(margins=(0, 0, 0, 0))
    opts = items(df)
    if not opts:
        p.caption("Sin rondas.")
        return p
    pick = Combo("Plan" if side == "T" else "Setup", opts, min_width=520)
    p.add(pick)
    body = p.add(Slot(lambda: _play_map(demos, df[df["key"] == pick.value], side)))
    pick.changed.connect(body.refresh)
    return p


def _play_map(demos: dict, rows, side: str) -> QWidget:
    from ..palette import SIDE_COLORS
    from .mapview import MapView
    from .nav import goto_replay
    p = Page(margins=(0, 0, 0, 0))
    if rows.empty:
        return p
    d0 = demos[rows["demo_id"].iloc[0]]
    m = MapView(d0.meta["map"], backdrop=d0.positions, height=560)
    paths, ends = [], []
    for row in rows.itertuples():
        d = demos.get(row.demo_id)
        if d is None:
            continue
        team = row.letter  # el equipo analizado, en el lado que se está mirando
        if side == "CT":
            t_end = 15.0
        else:
            t_end = row.commit_s + 3 if np.isfinite(row.commit_s) else 40.0
        pos = d.positions[(d.positions["round"] == row.round) & (d.positions["side"] == side)
                          & (d.positions["team"] == team) & (d.positions["time_in_round"] <= t_end)]
        for _, g in pos.groupby("steamid"):
            g = g.sort_values("time_in_round")
            if len(g) >= 2:
                paths.append((g["x"].to_numpy(float), g["y"].to_numpy(float)))
                last = g.iloc[-1]
                if last["health"] > 0:
                    ends.append((last["x"], last["y"]))
    n = len(rows)
    m.paths(paths, SIDE_COLORS[side], alpha=150 if n < 4 else 95 if n < 10 else 70, width=2.0 if n < 4 else 1.6)
    if ends:
        m.points([e[0] for e in ends], [e[1] for e in ends], "#e8e6e3", size=7)
    p.add(m.finish())
    starts = (rows["commit_s"] - 8).clip(lower=0).fillna(0).to_numpy()
    show = rows.assign(Partida=rows["demo_id"].map(lambda i: f"{demos[i].meta['team_a']} vs {demos[i].meta['team_b']}"
                                                   if i in demos else i))
    table = show[["Partida", "round", "t_name" if side == "T" else "ct_name", "winner_side"]].rename(columns={
        "round": "Ronda", "t_name": "Lectura", "ct_name": "Lectura", "winner_side": "Ganó"})
    ids, rnds = rows["demo_id"].to_numpy(), rows["round"].to_numpy()
    p.add(DataTable(table.reset_index(drop=True), fit_rows=len(table) <= 10,
                    on_activate=lambda i: goto_replay(ids[i], int(rnds[i]), float(starts[i]))))
    p.caption(("Recorrido de los 5 T de cada ronda desde el inicio hasta el golpe; el punto es dónde estaba cada "
               "uno al golpear." if side == "T" else "Recorrido de los CT en los primeros 15 s; el punto es dónde "
               "estaba cada uno a los 15 s.") + " Doble clic en una ronda para verla en el replay.")
    return p
