"""Revisión de muertes: cada muerte de un jugador con los motivos por los que pudo ser evitable (sin interfaz).

No juzga la jugada (eso lo hace quien mira el replay): marca señales objetivas que suelen indicar un error y ordena
las muertes para revisar primero las que más costaron. Las señales:

- sin tradeo: ningún compañero vengó la muerte en 5 s (nadie estaba cerca para cubrirlo);
- primera muerte de la ronda sin tradeo: el equipo queda 4v5 sin compensación;
- aislado: el compañero vivo más cercano estaba a más de ~20 m;
- en ventaja: su equipo tenía más jugadores vivos (un peek que no hacía falta);
- de espaldas / fuera de ángulo: el que lo mató estaba lejos de donde apuntaba (solo con datos de micro);
- ciego: murió con flash encima;
- sin daño: murió sin haberle hecho daño a nadie en la ronda;
- sin granadas: con compra completa, no tiró ninguna granada antes de morir;
- ronda perdida: su equipo perdió esa ronda.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from .constants import TICKRATE
from .parser import DemoData

ISOLATED_UNITS = 1100      # ~21 m: fuera del alcance de un tradeo
OFF_ANGLE_DEG = 60         # el rival apareció a más de 60° de su mira
FULL_BUY_EQUIP = 3500      # con esto ya compró rifle; si no tiró nada, probablemente murió con granadas encima

# (columna, peso en la prioridad, texto)
SIGNALS = [
    ("opening_untraded", 3.0, "primera muerte de la ronda sin tradeo"),
    ("untraded", 1.5, "nadie lo tradeó"),
    ("isolated", 1.5, "aislado del equipo"),
    ("in_advantage", 1.5, "murió con su equipo en ventaja"),
    ("off_angle", 1.0, "lo mataron desde donde no miraba"),
    ("blind", 0.5, "estaba flasheado"),
    ("no_damage", 1.0, "murió sin hacer daño en la ronda"),
    ("no_utility", 0.5, "con compra completa, no tiró ninguna granada"),
    ("round_lost", 0.5, "su equipo perdió la ronda"),
]
REASON = {c: t for c, _, t in SIGNALS}


def _alive_counts(d: DemoData, rnd: int, tick: int, side: str) -> tuple[int, int]:
    """(vivos de su equipo, vivos rivales) justo antes de `tick` en la ronda."""
    roster = d.economy[d.economy["round"] == rnd] if len(d.economy) else d.economy
    mine = int((roster["side"] == side).sum()) or 5
    theirs = int((roster["side"] != side).sum()) or 5
    k = d.kills[(d.kills["round"] == rnd) & (d.kills["tick"] < tick)]
    mine -= int((k["victim_side"] == side).sum())
    theirs -= int((k["victim_side"] != side).sum())
    return max(mine, 1), max(theirs, 0)


def _nearest_mate(d: DemoData, rnd: int, tick: int, sid: str, side: str) -> float:
    """Distancia (unidades del juego) al compañero vivo más cercano en la muestra de posiciones más próxima."""
    p = d.positions
    if p.empty:
        return np.nan
    p = p[(p["round"] == rnd) & (p["side"] == side) & (p["tick"] <= tick) & (p["tick"] > tick - TICKRATE)]
    if p.empty:
        return np.nan
    last = p.sort_values("tick").groupby("steamid").tail(1)
    me = last[last["steamid"] == sid]
    mates = last[(last["steamid"] != sid) & (last["health"] > 0)]
    if me.empty or mates.empty:
        return np.nan
    dx = mates["x"].to_numpy() - me["x"].iloc[0]
    dy = mates["y"].to_numpy() - me["y"].iloc[0]
    return float(np.sqrt(dx ** 2 + dy ** 2).min())


def player_deaths(d: DemoData, steamid: str) -> pd.DataFrame:
    """Muertes de `steamid` durante las rondas (no las de después de terminada), con señales y prioridad."""
    cols = ["demo_id", "round", "tick", "time_in_round", "side", "attacker", "weapon", "place", "mates_alive",
            "enemies_alive", "nearest_mate", *[c for c, _, _ in SIGNALS], "priority", "reasons"]
    k = d.kills
    if k.empty:
        return pd.DataFrame(columns=cols)
    ends = d.rounds.set_index("round")
    mine = k[(k["victim_steamid"] == steamid) & ~k["is_suicide"].astype(bool)]
    mine = mine[mine["tick"] <= mine["round"].map(ends["end_tick"]).fillna(np.inf)]
    if mine.empty:
        return pd.DataFrame(columns=cols)
    dmg = d.damages
    dmg = dmg[(dmg["attacker_steamid"] == steamid) & dmg["is_enemy"].astype(bool)] if len(dmg) else dmg
    gren = d.grenades[d.grenades["thrower_steamid"] == steamid] if len(d.grenades) else d.grenades
    blinds = d.blinds[(d.blinds["victim_steamid"] == steamid)] if len(d.blinds) else d.blinds
    equip = (d.economy[d.economy["steamid"] == steamid].set_index("round")["equip_value"]
             if len(d.economy) else pd.Series(dtype=float))
    duels = d.duels if len(getattr(d, "duels", pd.DataFrame())) else pd.DataFrame()
    rows = []
    for _, r in mine.iterrows():
        rnd, tick, side = int(r["round"]), int(r["tick"]), r["victim_side"]
        mates, enemies = _alive_counts(d, rnd, tick, side)
        near = _nearest_mate(d, rnd, tick, steamid, side)
        off = np.nan
        if len(duels) and "victim_crosshair_deg" in duels:
            m = duels[(duels["victim_steamid"] == steamid) & (duels["tick"] == tick)]
            off = float(m["victim_crosshair_deg"].iloc[0]) if len(m) else np.nan
        blind = bool(len(blinds) and ((blinds["tick"] <= tick)
                                      & (blinds["tick"] + blinds["blind_duration"] * TICKRATE >= tick)).any())
        did_dmg = bool(len(dmg) and ((dmg["round"] == rnd) & (dmg["tick"] <= tick)).any())
        threw = bool(len(gren) and ((gren["round"] == rnd) & (gren["tick"] <= tick)).any())
        winner = ends["winner_side"].get(rnd, "")
        sig = {
            "opening_untraded": bool(r["is_opening"]) and not bool(r["was_traded"]),
            "untraded": not bool(r["was_traded"]) and mates > 1,  # con el último vivo no hay a quién tradear
            "isolated": bool(np.isfinite(near) and near > ISOLATED_UNITS),
            "in_advantage": mates > enemies,
            "off_angle": bool(np.isfinite(off) and off > OFF_ANGLE_DEG),
            "blind": blind,
            "no_damage": not did_dmg,
            "no_utility": not threw and float(equip.get(rnd, 0)) >= FULL_BUY_EQUIP,
            "round_lost": bool(winner) and winner != side,
        }
        if sig["opening_untraded"]:
            sig["untraded"] = False  # ya lo dice la señal más fuerte
        prio = sum(w for c, w, _ in SIGNALS if sig[c])
        rows.append({"demo_id": d.demo_id, "round": rnd, "tick": tick, "time_in_round": float(r["time_in_round"]),
                     "side": side, "attacker": r["attacker_name"], "weapon": r["weapon"],
                     "place": r.get("victim_place", ""), "mates_alive": mates, "enemies_alive": enemies,
                     "nearest_mate": near, **sig, "priority": prio,
                     "reasons": [t for c, _, t in SIGNALS if sig[c]]})
    out = pd.DataFrame(rows, columns=cols)
    return out.sort_values(["priority", "round"], ascending=[False, True]).reset_index(drop=True)


def summary(deaths: pd.DataFrame) -> dict[str, float]:
    """Porcentaje de muertes con cada señal (para ver patrones: '60 % de tus muertes, sin tradeo')."""
    n = max(len(deaths), 1)
    return {c: 100 * deaths[c].sum() / n for c, _, _ in SIGNALS if c in deaths}

