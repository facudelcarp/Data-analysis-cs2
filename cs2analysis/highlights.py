"""Lo más destacado de una partida, para leer en 5 segundos (independiente de la interfaz)."""
from __future__ import annotations

import pandas as pd

from . import micro
from .parser import DemoData


def match_highlights(d: DemoData, ps: pd.DataFrame) -> list[tuple[str, str, str]]:
    """Lista de (título, jugador, detalle): mejor rating, más daño, aperturas, clutches y mejor mira."""
    def best(col, asc=False):
        x = ps.dropna(subset=[col])
        return x.sort_values(col, ascending=asc).iloc[0] if len(x) else None

    items = []
    if (r := best("rating2")) is not None:
        items.append(("⭐ Mejor del partido", r["name"], f"rating {r['rating2']:.2f} · {int(r['kills'])}-{int(r['deaths'])}"))
    if (r := best("adr")) is not None:
        items.append(("💥 Más daño", r["name"], f"{r['adr']:.0f} de daño por ronda"))
    if (r := best("opening_kills")) is not None and r["opening_kills"] > 0:
        items.append(("🚪 Más aperturas ganadas", r["name"], f"{int(r['opening_kills'])} primeras kills"))
    if (r := best("clutches_won")) is not None and r["clutches_won"] > 0:
        items.append(("🧊 Clutches", r["name"], f"{int(r['clutches_won'])} ganados de {int(r['clutches'])}"))
    if d.duels is not None and len(d.duels):
        pm = micro.player_micro(d.duels, d.shots)
        pm = pm[pm["duels_won"].fillna(0) >= 3].dropna(subset=["crosshair_deg"]) if len(pm) else pm
        if len(pm):
            r = pm.sort_values("crosshair_deg").iloc[0]
            items.append(("🎯 Mejor mira", dict(zip(d.players["steamid"], d.players["name"])).get(r["steamid"], "?"),
                          f"{r['crosshair_deg']:.1f}° del rival al verlo"))
    return items
