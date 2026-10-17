"""Datos crudos traducidos: mismas filas que las tablas normalizadas, pero con columnas en
español, valores legibles (lados, armas, zonas, motivos) y sin columnas puramente técnicas."""
from __future__ import annotations

import re

import pandas as pd

from .constants import COLUMN_NAMES, HITGROUPS, WEAPON_CLASS, WEAPON_NAMES
from .parser import DemoData

YES_NO = {True: "Sí", False: "No"}
_CAMEL = re.compile(r"(?<=[a-z])(?=[A-Z])|(?<=[A-Za-z])(?=[0-9])")


def weapon_name(w: str) -> str:
    return WEAPON_NAMES.get(w, w.replace("_", " ").title() if w else "—")


def place_name(p: str) -> str:
    """'BombsiteA' -> 'Bombsite A', 'TopofMid' -> 'Topof Mid' (los nombres vienen del .nav)."""
    if not isinstance(p, str) or not p:
        return "—"
    return _CAMEL.sub(" ", p).replace("Bombsite ", "Sitio ")


def _team_label(d: DemoData):
    return {"A": d.meta["team_a"], "B": d.meta["team_b"], "": "—"}


def _finish(df: pd.DataFrame, drop: list[str] | None = None) -> pd.DataFrame:
    df = df.drop(columns=[c for c in (drop or []) if c in df.columns])
    for c in df.columns:
        if pd.api.types.is_bool_dtype(df[c]):
            df[c] = df[c].map(YES_NO)
    return df.rename(columns=lambda c: COLUMN_NAMES.get(c, c))


def kills(d: DemoData) -> pd.DataFrame:
    k = d.kills.copy()
    if k.empty:
        return k
    teams = _team_label(d)
    k["weapon_class"] = k["weapon"].map(lambda w: WEAPON_CLASS.get(w, "Otro"))
    k["weapon"] = k["weapon"].map(weapon_name)
    k["hitgroup"] = k["hitgroup"].map(lambda h: HITGROUPS.get(h, h))
    k["attacker_place"] = k["attacker_place"].map(place_name)
    k["victim_place"] = k["victim_place"].map(place_name)
    k["attacker_name"] = k["attacker_name"].replace("", "Mundo")
    k["attacker_team"] = k["attacker_team"].map(teams)
    k["victim_team"] = k["victim_team"].map(teams)
    k["distance"] = k["distance"].astype(float).round(1)
    k["assister_name"] = k["assister_name"].where(k["assist_valid"], "")
    cols = ["round", "time_in_round", "attacker_name", "attacker_side", "attacker_team", "attacker_place",
            "victim_name", "victim_side", "victim_team", "victim_place", "assister_name", "assistedflash",
            "weapon", "weapon_class", "headshot", "hitgroup", "distance", "penetrated", "thrusmoke",
            "noscope", "attackerblind", "is_opening", "is_trade", "was_traded", "is_teamkill", "is_suicide", "tick"]
    k = k[[c for c in cols if c in k.columns]]
    k["penetrated"] = k["penetrated"].map(YES_NO)
    return _finish(k.rename(columns={"attacker_team": "Equipo atacante", "victim_team": "Equipo víctima"}))


def damages(d: DemoData) -> pd.DataFrame:
    x = d.damages.copy()
    if x.empty:
        return x
    x["weapon"] = x["weapon"].map(weapon_name)
    x["hitgroup"] = x["hitgroup"].map(lambda h: HITGROUPS.get(h, h))
    x["victim_place"] = x["victim_place"].map(place_name)
    x["attacker_name"] = x["attacker_name"].replace("", "Mundo")
    x["tipo"] = x.apply(lambda r: "Propio/mundo" if r["is_self"] else ("A compañero" if r["is_team_damage"] else "A rival"), axis=1)
    cols = ["round", "time_in_round", "attacker_name", "attacker_side", "victim_name", "victim_side",
            "victim_place", "weapon", "hitgroup", "dmg_health", "dmg_health_raw", "dmg_armor", "health",
            "tipo", "tick"]
    return _finish(x[cols].rename(columns={"tipo": "Tipo de daño"}))


def rounds(d: DemoData) -> pd.DataFrame:
    r = d.rounds.copy()
    teams = _team_label(d)
    r["winner_team"] = r["winner_team"].map(teams)
    r["ct_team"] = r["ct_team"].map(teams)
    r["t_team"] = r["t_team"].map(teams)
    mvp = d.players.set_index("steamid")["name"]
    r["MVP"] = r["mvp_steamid"].map(mvp).fillna("—")
    r["Marcador"] = r["score_a"].astype(str) + " - " + r["score_b"].astype(str)
    cols = ["round", "Marcador", "winner_side", "winner_team", "reason", "duration_s", "ct_team", "t_team",
            "ct_equip", "t_equip", "ct_buy", "t_buy", "bomb_planted", "bomb_site", "MVP",
            "start_tick", "freeze_end_tick", "end_tick"]
    return _finish(r[cols])


def grenades(d: DemoData) -> pd.DataFrame:
    g = d.grenades.copy()
    if g.empty:
        return g
    g["thrower_place"] = g["thrower_place"].map(place_name)
    g = g.rename(columns={"thrower_name": "Lanzador", "thrower_side": "Lado", "thrower_place": "Zona del lanzador",
                          "enemies_blinded": "Enemigos cegados", "blind_time_enemies": "Ceguera a enemigos (s)",
                          "teammates_blinded": "Compañeros cegados"})
    for c in ["x", "y", "z"]:
        g[c] = g[c].astype(float).round(0)
    g["Ceguera a enemigos (s)"] = g["Ceguera a enemigos (s)"].astype(float).round(2)
    return _finish(g, drop=["entityid", "thrower_steamid"])


def blinds(d: DemoData) -> pd.DataFrame:
    b = d.blinds.copy()
    if b.empty:
        return b
    b = b.rename(columns={"attacker_name": "Flasheó", "victim_name": "Cegado", "attacker_side": "Lado de quien flasheó",
                          "victim_side": "Lado del cegado", "is_self": "Autoflash"})
    return _finish(b, drop=["entityid", "attacker_steamid", "victim_steamid", "attacker_team"])


def bomb(d: DemoData) -> pd.DataFrame:
    b = d.bomb.copy()
    if b.empty:
        return b
    b["player_place"] = b["player_place"].map(place_name)
    b = b.rename(columns={"player_name": "Jugador", "player_side": "Lado", "player_place": "Zona",
                          "site_letter": "Sitio"})
    return _finish(b, drop=["event_code", "player_steamid", "site", "player_x", "player_y", "player_z"])


def economy(d: DemoData) -> pd.DataFrame:
    e = d.economy.copy()
    e["team"] = e["team"].map(_team_label(d))
    for c in ["has_helmet", "has_defuser"]:
        e[c] = e[c].fillna(False).astype(bool)
    return _finish(e, drop=["steamid"])


def players(d: DemoData) -> pd.DataFrame:
    p = d.players.copy()
    p = p.rename(columns={"team_name": "Equipo", "rank": "Premier / rango", "comp_wins": "Victorias competitivas",
                          "crosshair_code": "Código de mira", "first_round": "Primera ronda",
                          "rounds_played": "Rondas jugadas"})
    return _finish(p, drop=["team", "team_clan_name"])


TABLES = {
    "Kills": kills,
    "Daño": damages,
    "Rondas": rounds,
    "Economía": economy,
    "Granadas": grenades,
    "Cegueras (flashes)": blinds,
    "Bomba": bomb,
    "Jugadores": players,
}
