"""Estrategias por ronda (strategy.py): resumen de planes T y setups CT, y la lectura ronda a ronda."""
from __future__ import annotations

import pandas as pd
from PySide6.QtWidgets import QWidget

from .. import strategy
from ..parser import DemoData
from .nav import goto_replay
from .page import AsyncSlot, Page
from .widgets import DataTable

NOTE = ("lectura por lo que se ve, no por cómo terminó la ronda. Apertura: cómo se reparten los T a los 20 s "
        "(Default = abiertos en A, Mid y B). Golpe: el momento en que 3+ T pisan un sitio; Rush = antes de los 25 s y "
        "con poca utilidad, Execute = 3+ granadas en el sitio alrededor del golpe; split = entran por dos accesos; "
        "fake = antes cargaron el otro sitio. CT: setup a los 15 s como A-Mid-B, stack = 3+ sobre un sitio, "
        "agresión = CT del lado T del mapa antes de los 20 s; al golpe, cuántos aguantan, cuántos rotan y en "
        "cuánto llegan. Doble clic en una ronda la abre en el replay un poco antes del golpe. Para medir el "
        "acierto, etiquetá rondas en el replay (Etiquetar ronda…).")


def single_block(p: Page, d: DemoData, names: dict[str, str]) -> None:
    def job():
        return lambda: strategy.round_strategies(d)

    def render(s: pd.DataFrame) -> QWidget:
        out = Page(margins=(0, 0, 0, 0))
        if s.empty:
            out.info("Sin geografía para este mapa (hacen falta plantes en A y en B entre las demos cargadas).")
            return out
        tt, ct = strategy.summary_tables(s, s["winner_side"] == "T", s["winner_side"] == "CT")
        left, right = Page(margins=(0, 0, 0, 0)), Page(margins=(0, 0, 0, 0))
        left.sub("Planes T")
        left.add(DataTable(tt, fit_rows=len(tt) <= 14, decimals=0))
        right.sub("Setups CT")
        right.add(DataTable(ct, fit_rows=len(ct) <= 14, decimals=0))
        out.row(left, right)
        rows = pd.DataFrame({
            "Ronda": s["round"], "T": s["t_team"].map(names), "Compra T": s["t_buy"], "Estrategia T": s["t_name"],
            "CT": s["ct_name"], "Ganó": s["winner_side"], "Evidencia T": s["t_evidence"],
        })
        starts = (s["commit_s"] - 8).clip(lower=0).fillna(0).to_numpy()
        rounds = s["round"].to_numpy()
        out.sub("Ronda a ronda")
        out.add(DataTable(rows, on_activate=lambda i: goto_replay(d.demo_id, int(rounds[i]), float(starts[i]))
                          )).setMinimumHeight(min(90 + 26 * len(rows), 520))
        out.note(NOTE)
        return out

    p.add(AsyncSlot(job, render))
