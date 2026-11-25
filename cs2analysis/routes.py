"""Rutas de un jugador: su recorrido en cada ronda, a lo largo de varias partidas del mismo mapa (sin interfaz).

Sale de las posiciones que ya guarda cada demo (una muestra cada 0.5 s), así que no hace falta volver a parsear.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from .parser import DemoData

BUY_GROUPS = {"Todas": None, "Full buy": ("Full buy",), "Force": ("Force / semi-buy",),
              "Eco": ("Eco", "Semi-eco"), "Pistola": ("Pistola",)}


@dataclass
class Route:
    demo_id: str
    match: str          # "Mirage · 13-9 · archivo.dem"
    round: int
    won: bool
    buy: str
    t: np.ndarray       # segundos de ronda
    x: np.ndarray
    y: np.ndarray
    z: np.ndarray
    died: bool          # murió dentro de la ventana de tiempo

    @property
    def label(self) -> str:
        return f"{self.match} · ronda {self.round} · {'ganada' if self.won else 'perdida'} · {self.buy}"


def player_maps(demos: list[DemoData], steamid: str) -> dict[str, int]:
    """Mapas en los que jugó el jugador y en cuántas partidas."""
    out: dict[str, int] = {}
    for d in demos:
        if (d.players["steamid"] == steamid).any():
            out[d.meta["map"]] = out.get(d.meta["map"], 0) + 1
    return dict(sorted(out.items(), key=lambda kv: -kv[1]))


def player_routes(demos: list[DemoData], steamid: str, map_name: str, side: str, t0: float = 0, t1: float = 30,
                  buy: str = "Todas") -> list[Route]:
    """Una ruta por ronda en la que el jugador jugó de `side` en `map_name`, recortada a [t0, t1] segundos."""
    wanted = BUY_GROUPS.get(buy)
    routes: list[Route] = []
    for d in demos:
        if d.meta["map"] != map_name or d.positions.empty:
            continue
        pos = d.positions[(d.positions["steamid"] == steamid) & (d.positions["side"] == side)]
        if pos.empty:
            continue
        rounds = d.rounds.set_index("round")
        team = pos["team"].iloc[0]
        deaths = (d.kills[d.kills["victim_steamid"] == steamid].groupby("round")["time_in_round"].min()
                  if len(d.kills) else pd.Series(dtype=float))
        m = d.meta
        match = f"{m['file_name']} ({m['score_a']}-{m['score_b']})"
        win = pos[(pos["time_in_round"] >= t0) & (pos["time_in_round"] <= t1)].sort_values("tick")
        for rnd, g in win.groupby("round"):
            if rnd not in rounds.index or len(g) < 2:
                continue
            r = rounds.loc[rnd]
            team_buy = r["ct_buy"] if side == "CT" else r["t_buy"]
            if wanted and team_buy not in wanted:
                continue
            death = deaths.get(rnd, np.nan)
            routes.append(Route(d.demo_id, match, int(rnd), r["winner_team"] == team, str(team_buy),
                                g["time_in_round"].to_numpy(float), g["x"].to_numpy(float), g["y"].to_numpy(float),
                                g["z"].to_numpy(float), bool(np.isfinite(death) and t0 <= death <= t1)))
    return routes
