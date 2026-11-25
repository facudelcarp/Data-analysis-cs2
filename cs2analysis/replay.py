"""Datos para el Replay 2D: rondas etiquetadas por compra y la ronda lista para dibujar (sin interfaz).

Todo queda en coordenadas de radar (0..1024, y hacia abajo) y en arrays de numpy por jugador, para que el
reproductor solo tenga que interpolar en cada cuadro."""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from .maps import map_info
from .parser import TICKRATE, DemoData
from .translate import weapon_name

# Duración en el mapa de cada granada (s) en CS2
SMOKE_S, FIRE_S, HE_S, FLASH_S, DECOY_S = 20.0, 7.0, 0.75, 0.7, 15.0
BOMB_TIMER_S = 40.0

_SIMPLE_RANK = {"Full buy": 4, "Force": 3, "Eco": 2, "Pistola": 1, "Sin dato": 0}
_EXACT_RANK = {"Full buy": 4, "Force / semi-buy": 3, "Semi-eco": 2, "Eco": 1, "Pistola": 0}


def simplify_buy(b) -> str:
    if b is None or (isinstance(b, float) and np.isnan(b)) or not str(b):
        return "Sin dato"
    s = str(b)
    if "Force" in s:
        return "Force"
    if "Eco" in s:
        return "Eco"
    return s


def tag_round_buys(rt: pd.DataFrame, teams: dict[str, str]) -> pd.DataFrame:
    """Agrega a cada ronda el enfrentamiento de compras: simplificado, exacto, por lado y por equipo."""
    df = rt.copy()
    simp, exact, side, team = [], [], [], []
    for r in df.itertuples():
        ct_b, t_b = str(getattr(r, "ct_buy", "Sin dato")), str(getattr(r, "t_buy", "Sin dato"))
        s_ct, s_t = simplify_buy(ct_b), simplify_buy(t_b)
        simp.append(f"{s_ct} vs {s_t}" if _SIMPLE_RANK.get(s_ct, 0) >= _SIMPLE_RANK.get(s_t, 0) else f"{s_t} vs {s_ct}")
        exact.append(f"{ct_b} vs {t_b}" if _EXACT_RANK.get(ct_b, 0) >= _EXACT_RANK.get(t_b, 0) else f"{t_b} vs {ct_b}")
        side.append(f"CT {s_ct} vs T {s_t}")
        name_ct = teams.get(str(r.ct_team), f"Equipo {r.ct_team}")
        name_t = teams.get(str(r.t_team), f"Equipo {r.t_team}")
        team.append(f"{name_ct} ({s_ct}) vs {name_t} ({s_t})")
    df["matchup_simp"], df["matchup_exact"], df["matchup_side"], df["matchup_team"] = simp, exact, side, team
    return df


def filter_options(df: pd.DataFrame) -> dict[str, list[int]]:
    """Filtros de rondas por compra que efectivamente ocurrieron: {etiqueta: [rondas]}."""
    out: dict[str, list[int]] = {f"Todas las rondas ({len(df)})": df["round"].tolist()}
    for key in ("Full buy vs Full buy", "Full buy vs Force", "Full buy vs Eco", "Force vs Force", "Force vs Eco",
                "Eco vs Eco", "Pistola vs Pistola"):
        rnds = df.loc[df["matchup_simp"] == key, "round"].tolist()
        if rnds:
            out[f"⚔️ {key} ({len(rnds)} rondas)"] = rnds
    for key, g in df.groupby("matchup_side"):
        out.setdefault(f"🛡️ {key} ({len(g)} rondas)", g["round"].tolist())
    for key, g in df.groupby("matchup_exact"):
        if "Semi-eco" in key:
            out.setdefault(f"💵 {key} ({len(g)} rondas)", g["round"].tolist())
    return out


def economy_context(ct_equip: float, t_equip: float, matchup: str) -> str:
    diff = ct_equip - t_equip
    if abs(diff) < 6_000 and "Full" in matchup:
        return "⚔️ Compras parejas (full buy vs full buy)"
    if diff > 8_000:
        return "📈 Ventaja de equipamiento para CT"
    if diff < -8_000:
        return "📉 Ventaja de equipamiento para T"
    return f"Duelo económico: {matchup}"


@dataclass
class Track:
    steamid: str
    name: str
    side: str
    team: str
    t: np.ndarray
    x: np.ndarray
    y: np.ndarray
    hp: np.ndarray

    def at(self, t: float) -> tuple[float, float, float, float, float]:
        """(x, y, hp, ángulo de movimiento, velocidad) interpolados en el segundo t."""
        n = len(self.t)
        if t <= self.t[0] or n == 1:
            return self.x[0], self.y[0], self.hp[0], 0.0, 0.0
        if t >= self.t[-1]:
            return self.x[-1], self.y[-1], self.hp[-1], 0.0, 0.0
        i = int(np.searchsorted(self.t, t, side="right")) - 1
        t0, t1 = self.t[i], self.t[i + 1]
        a = 0.0 if t1 == t0 else (t - t0) / (t1 - t0)
        dx, dy = self.x[i + 1] - self.x[i], self.y[i + 1] - self.y[i]
        return (self.x[i] + a * dx, self.y[i] + a * dy, self.hp[i] + a * (self.hp[i + 1] - self.hp[i]),
                float(np.arctan2(dy, dx)), float(np.hypot(dx, dy)))


@dataclass
class RoundReplay:
    round: int
    t_min: float
    t_max: float
    tracks: list[Track]
    kills: pd.DataFrame          # t, attacker, victim, sides, sids, weapon, headshot, ax, ay, vx, vy
    bomb: pd.DataFrame           # t, event, site, player, x, y
    grenades: pd.DataFrame       # t, type, thrower, side, x, y
    blinds: pd.DataFrame         # t, sid, dur
    info: dict = field(default_factory=dict)

    def death_time(self) -> dict[str, float]:
        k = self.kills.dropna(subset=["t"])
        return k.groupby("victim_sid")["t"].min().to_dict() if len(k) else {}


def _transform(d: DemoData):
    info = map_info(d.meta["map"])
    if info:
        return lambda x, y: info.to_radar(np.asarray(x, dtype=float), np.asarray(y, dtype=float))
    # Sin datos del mapa: se encaja el recorrido de toda la partida en el lienzo
    p = d.positions
    min_x, max_x, min_y, max_y = p["x"].min(), p["x"].max(), p["y"].min(), p["y"].max()
    dx, dy = max(max_x - min_x, 1), max(max_y - min_y, 1)
    return lambda x, y: (60 + 904 * (np.asarray(x, dtype=float) - min_x) / dx,
                         964 - 904 * (np.asarray(y, dtype=float) - min_y) / dy)


def build_round(d: DemoData, round_num: int, round_info: pd.Series | None = None) -> RoundReplay | None:
    pos = d.positions[d.positions["round"] == round_num]
    if pos.empty:
        return None
    tf = _transform(d)
    tracks = []
    for sid, g in pos.sort_values("time_in_round").groupby("steamid", sort=False):
        x, y = tf(g["x"], g["y"])
        first = g.iloc[0]
        tracks.append(Track(str(sid), str(first["name"]), str(first["side"]), str(first["team"]),
                            g["time_in_round"].to_numpy(dtype=float), np.asarray(x), np.asarray(y),
                            g["health"].to_numpy(dtype=float)))
    tracks.sort(key=lambda tr: (tr.side, tr.name.lower()))

    k = d.kills[d.kills["round"] == round_num] if len(d.kills) else d.kills
    ax, ay = tf(k["attacker_x"], k["attacker_y"]) if len(k) else ([], [])
    vx, vy = tf(k["victim_x"], k["victim_y"]) if len(k) else ([], [])
    kills = pd.DataFrame({
        "t": k["time_in_round"].to_numpy(dtype=float) if len(k) else [],
        "attacker": k["attacker_name"].astype(str).replace("", "Mundo").to_numpy() if len(k) else [],
        "attacker_side": k["attacker_side"].astype(str).to_numpy() if len(k) else [],
        "attacker_sid": k["attacker_steamid"].astype(str).to_numpy() if len(k) else [],
        "victim": k["victim_name"].astype(str).to_numpy() if len(k) else [],
        "victim_side": k["victim_side"].astype(str).to_numpy() if len(k) else [],
        "victim_sid": k["victim_steamid"].astype(str).to_numpy() if len(k) else [],
        "weapon": k["weapon"].astype(str).map(weapon_name).to_numpy() if len(k) else [],
        "headshot": k["headshot"].astype(bool).to_numpy() if len(k) else [],
        "ax": ax, "ay": ay, "vx": vx, "vy": vy,
    })

    b = d.bomb[d.bomb["round"] == round_num] if len(d.bomb) else d.bomb
    bx, by = tf(b["player_x"], b["player_y"]) if len(b) else ([], [])
    bomb = pd.DataFrame({"t": b["time_in_round"].to_numpy(dtype=float) if len(b) else [],
                         "event": b["event_code"].astype(str).to_numpy() if len(b) else [],
                         "site": b["site_letter"].astype(str).to_numpy() if len(b) and "site_letter" in b else
                         [""] * len(b),
                         "player": b["player_name"].astype(str).to_numpy() if len(b) else [],
                         "x": bx, "y": by})

    g = d.grenades[d.grenades["round"] == round_num] if len(d.grenades) else d.grenades
    gx, gy = tf(g["x"], g["y"]) if len(g) else ([], [])
    grenades = pd.DataFrame({"t": g["time_in_round"].to_numpy(dtype=float) if len(g) else [],
                             "type": g["grenade"].astype(str).to_numpy() if len(g) else [],
                             "thrower": g["thrower_name"].astype(str).to_numpy() if len(g) else [],
                             "side": g["thrower_side"].astype(str).to_numpy() if len(g) else [],
                             "x": gx, "y": gy})

    # Las cegueras no traen time_in_round en la caché: se calcula desde el tick y el fin del freeze time
    bl = d.blinds[d.blinds["round"] == round_num] if len(d.blinds) else d.blinds
    blinds = pd.DataFrame(columns=["t", "sid", "dur"])
    if len(bl):
        if "time_in_round" in bl:
            t_bl = bl["time_in_round"].to_numpy(dtype=float)
        else:
            freeze = d.rounds.set_index("round")["freeze_end_tick"].get(round_num, np.nan)
            t_bl = (bl["tick"].to_numpy(dtype=float) - float(freeze)) / TICKRATE
        blinds = pd.DataFrame({"t": t_bl, "sid": bl["victim_steamid"].astype(str).to_numpy(),
                               "dur": bl["blind_duration"].to_numpy(dtype=float)})

    t_min = float(pos["time_in_round"].min())
    t_max = max(float(pos["time_in_round"].max()), t_min + 1)
    info = {} if round_info is None else {k: round_info[k] for k in round_info.index}
    return RoundReplay(round_num, t_min, t_max, tracks, kills, bomb, grenades, blinds, info)
