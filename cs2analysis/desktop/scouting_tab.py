"""Informe de rival: una hoja por mapa con lo que el equipo hace (ver scouting.py), exportable a HTML."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtWidgets import QFileDialog, QLabel, QMessageBox, QPushButton, QWidget

from .. import scouting
from ..maps import pretty_map
from ..parser import DemoData
from .page import AsyncSlot, Page
from .widgets import DataTable

LINEUP_COLS = scouting.LINEUP_COLS


def build(demos: list[DemoData], instances: list[tuple[str, str]], map_name: str, team: str) -> QWidget:
    p = Page()

    def job():
        inst = [i for i in instances if map_name == "Todos los mapas"
                or next((d.meta["map"] for d in demos if d.demo_id == i[0]), None) == map_name]
        return lambda: scouting.scout(demos, inst)

    p.add(AsyncSlot(job, lambda reps: _render(reps, team)))
    p.stretch()
    return p


def _render(reports: list[scouting.MapReport], team: str) -> QWidget:
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
