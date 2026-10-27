"""Métricas derivadas. Todo se calcula a partir de la tabla `player_rounds` (una fila por
jugador y ronda) para que la misma agregación sirva para una demo o para cien.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from .constants import UTILITY_DAMAGE_WEAPONS, WEAPON_CLASS
from .parser import DemoData

def _per_demo_cache(fn):
    """Cachea el resultado por demo (una vez calculado, todas las vistas lo reutilizan).

    Devuelve una copia: así una vista que agrega columnas no altera lo que ven las demás. La clave incluye la
    versión de equipos de la demo, porque corregir nombres o lados invalida lo calculado."""
    import functools

    @functools.wraps(fn)
    def wrapper(d, *args, **kwargs):
        if args or kwargs:
            return fn(d, *args, **kwargs)
        cache = d.__dict__.setdefault("_stats_cache", {})
        key = (fn.__name__, d.meta.get("team_a"), d.meta.get("team_b"))
        if key not in cache:
            cache[key] = fn(d)
        return cache[key].copy()
    return wrapper


FIREARM_CLASSES = {"Rifle", "Francotirador", "SMG", "Escopeta", "Ametralladora", "Pistola"}


@_per_demo_cache
def player_rounds(d: DemoData) -> pd.DataFrame:
    """Una fila por (ronda, jugador) con todo lo necesario para KAST, rating, multikills, etc."""
    base = d.economy[["round", "steamid", "name", "side", "team", "equip_value"]].copy()
    if base.empty:
        return base
    k, dmg, bl, gr = d.kills, d.damages, d.blinds, d.grenades
    ek = k[k["is_enemy_kill"]] if len(k) else k

    empty_idx = pd.MultiIndex.from_arrays([[], []], names=["round", "steamid"])

    def count(df, key, name):
        if df.empty:
            return pd.Series(dtype="int64", name=name, index=empty_idx)
        return df.groupby(["round", key]).size().rename(name).rename_axis(["round", "steamid"])

    def total(df, key, col, name):
        if df.empty:
            return pd.Series(dtype="float64", name=name, index=empty_idx)
        return df.groupby(["round", key])[col].sum().rename(name).rename_axis(["round", "steamid"])

    edmg = dmg[dmg["is_enemy"]] if len(dmg) else dmg
    udmg = edmg[edmg["weapon"].isin(UTILITY_DAMAGE_WEAPONS)] if len(edmg) else edmg
    ebl = bl[bl["is_enemy"]] if len(bl) else bl
    parts = [
        count(ek, "attacker_steamid", "kills"),
        count(ek[ek["headshot"]] if len(ek) else ek, "attacker_steamid", "hs_kills"),
        count(k, "victim_steamid", "deaths"),
        count(k[k["assist_valid"]] if len(k) else k, "assister_steamid", "assists"),
        count(k[k["assist_valid"] & k["assistedflash"]] if len(k) else k, "assister_steamid", "flash_assists"),
        count(ek[ek["is_opening"]] if len(ek) else ek, "attacker_steamid", "opening_kills"),
        count(ek[ek["is_opening"]] if len(ek) else ek, "victim_steamid", "opening_deaths"),
        count(ek[ek["is_trade"]] if len(ek) else ek, "attacker_steamid", "trade_kills"),
        count(k[k["was_traded"]] if len(k) else k, "victim_steamid", "traded_deaths"),
        count(ek[ek["weapon"] == "awp"] if len(ek) else ek, "attacker_steamid", "awp_kills"),
        count(k[k["is_teamkill"]] if len(k) else k, "attacker_steamid", "teamkills"),
        total(edmg, "attacker_steamid", "dmg_health", "damage"),
        total(udmg, "attacker_steamid", "dmg_health", "utility_damage"),
        total(dmg[dmg["is_team_damage"]] if len(dmg) else dmg, "attacker_steamid", "dmg_health", "team_damage"),
        count(ebl, "attacker_steamid", "enemies_flashed"),
        total(ebl, "attacker_steamid", "blind_duration", "blind_time"),
        count(gr, "thrower_steamid", "grenades_thrown"),
    ]
    pr = base.set_index(["round", "steamid"]).join(pd.concat(parts, axis=1), how="left")
    num_cols = [p.name for p in parts]
    pr[num_cols] = pr[num_cols].fillna(0)
    pr = pr.reset_index()
    pr["survived"] = pr["deaths"] == 0
    pr["kast"] = (pr["kills"] > 0) | (pr["assists"] > 0) | pr["survived"] | (pr["traded_deaths"] > 0)
    winners = d.rounds.set_index("round")["winner_team"]
    pr["round_won"] = pr["round"].map(winners) == pr["team"]
    mvp = d.rounds.set_index("round")["mvp_steamid"]
    pr["mvp"] = pr["round"].map(mvp) == pr["steamid"]
    pr["demo_id"] = d.demo_id
    pr["map"] = d.meta["map"]
    return pr


@_per_demo_cache
def clutches(d: DemoData) -> pd.DataFrame:
    """Situaciones 1vX: el primer momento de la ronda en que un lado queda con un solo jugador."""
    rows = []
    roster = d.economy.groupby(["round", "side"])["steamid"].apply(set)
    winners = d.rounds.set_index("round")["winner_side"]
    deaths = d.kills.sort_values("tick") if len(d.kills) else d.kills
    for rnd in d.rounds["round"]:
        alive = {s: set(roster.get((rnd, s), set())) for s in ("CT", "T")}
        if not alive["CT"] or not alive["T"]:
            continue
        done = set()
        for k in deaths[deaths["round"] == rnd].itertuples():
            for s in alive:
                alive[s].discard(k.victim_steamid)
            for s, other in (("CT", "T"), ("T", "CT")):
                if s not in done and len(alive[s]) == 1 and len(alive[other]) >= 1:
                    done.add(s)
                    rows.append({"round": rnd, "steamid": next(iter(alive[s])), "side": s,
                                 "vs": len(alive[other]), "won": winners.get(rnd) == s,
                                 "tick": k.tick})
    out = pd.DataFrame(rows, columns=["round", "steamid", "side", "vs", "won", "tick"])
    out["demo_id"] = d.demo_id
    return out


@_per_demo_cache
def shots_hits(d: DemoData) -> pd.DataFrame:
    """Disparos y aciertos con armas de fuego por jugador (precisión aproximada)."""
    if d.shots.empty:
        return pd.DataFrame(columns=["steamid", "shots", "hits"])
    s = d.shots[d.shots["weapon"].map(WEAPON_CLASS).isin(FIREARM_CLASSES)]
    h = d.damages[d.damages["weapon"].map(WEAPON_CLASS).isin(FIREARM_CLASSES) & d.damages["is_enemy"]]
    out = pd.concat([s.groupby("player_steamid").size().rename("shots"),
                     h.groupby("attacker_steamid").size().rename("hits")], axis=1).fillna(0)
    return out.rename_axis("steamid").reset_index()


def aggregate(pr: pd.DataFrame, cl: pd.DataFrame | None = None, acc: pd.DataFrame | None = None,
              by: list[str] | None = None) -> pd.DataFrame:
    """Agrega `player_rounds` (de una o varias demos) en la tabla de estadísticas por jugador."""
    by = by or ["steamid"]
    if pr.empty:
        return pd.DataFrame()
    g = pr.groupby(by)
    s = g.agg(
        rounds=("round", "size"),
        kills=("kills", "sum"), deaths=("deaths", "sum"), assists=("assists", "sum"),
        hs_kills=("hs_kills", "sum"), damage=("damage", "sum"), utility_damage=("utility_damage", "sum"),
        team_damage=("team_damage", "sum"), flash_assists=("flash_assists", "sum"),
        enemies_flashed=("enemies_flashed", "sum"), blind_time=("blind_time", "sum"),
        opening_kills=("opening_kills", "sum"), opening_deaths=("opening_deaths", "sum"),
        trade_kills=("trade_kills", "sum"), traded_deaths=("traded_deaths", "sum"),
        awp_kills=("awp_kills", "sum"), teamkills=("teamkills", "sum"),
        grenades_thrown=("grenades_thrown", "sum"),
        kast_rounds=("kast", "sum"), survived=("survived", "sum"), rounds_won=("round_won", "sum"),
        mvps=("mvp", "sum"), avg_equip=("equip_value", "mean"),
        k1=("kills", lambda x: (x == 1).sum()), k2=("kills", lambda x: (x == 2).sum()),
        k3=("kills", lambda x: (x == 3).sum()), k4=("kills", lambda x: (x == 4).sum()),
        k5=("kills", lambda x: (x >= 5).sum()),
        demos=("demo_id", "nunique"),
    )
    count_cols = [c for c in s.columns if c not in ("avg_equip", "blind_time")]
    s[count_cols] = s[count_cols].astype(int)
    s["avg_equip"] = s["avg_equip"].round(0)
    s["blind_time"] = s["blind_time"].round(1)
    last = pr.sort_values("round").groupby(by).last()
    s.insert(0, "name", last["name"])
    s.insert(1, "team", last["team"])

    r = s["rounds"].replace(0, np.nan)
    s["kd"] = (s["kills"] / s["deaths"].replace(0, np.nan)).fillna(s["kills"]).round(2)
    s["kd_diff"] = s["kills"] - s["deaths"]
    s["adr"] = (s["damage"] / r).round(1)
    s["hs_pct"] = (100 * s["hs_kills"] / s["kills"].replace(0, np.nan)).fillna(0).round(1)
    s["kast_pct"] = (100 * s["kast_rounds"] / r).round(1)
    s["kpr"] = (s["kills"] / r).round(3)
    s["dpr"] = (s["deaths"] / r).round(3)
    s["apr"] = (s["assists"] / r).round(3)
    s["opening_attempts"] = s["opening_kills"] + s["opening_deaths"]
    s["opening_success_pct"] = (100 * s["opening_kills"] / s["opening_attempts"].replace(0, np.nan)).fillna(0).round(1)
    s["utility_adr"] = (s["utility_damage"] / r).round(1)
    s["multikill_rounds"] = s[["k2", "k3", "k4", "k5"]].sum(axis=1)

    # HLTV Rating 1.0 (fórmula pública)
    s["rating1"] = ((s["kpr"] / 0.679 + 0.7 * (r - s["deaths"]) / r / 0.317
                     + (s["k1"] + 4 * s["k2"] + 9 * s["k3"] + 16 * s["k4"] + 25 * s["k5"]) / r / 1.277) / 2.7).round(2)
    # Rating 2.0: aproximación por regresión de la comunidad (HLTV no publica la fórmula)
    s["impact"] = (2.13 * s["kpr"] + 0.42 * s["apr"] - 0.41).round(2)
    s["rating2"] = (0.0073 * s["kast_pct"] + 0.3591 * s["kpr"] - 0.5329 * s["dpr"]
                    + 0.2372 * s["impact"] + 0.0032 * s["adr"] + 0.1587).round(2)

    if cl is not None and len(cl):
        c = cl.groupby([x for x in by if x in cl.columns] or ["steamid"]).agg(
            clutches=("won", "size"), clutches_won=("won", "sum"),
            clutch_1v1=("vs", lambda v: (v == 1).sum()),
            clutch_1v1_won=("won", lambda w: (w & (cl.loc[w.index, "vs"] == 1)).sum()))
        s = s.join(c)
    for col in ["clutches", "clutches_won", "clutch_1v1", "clutch_1v1_won"]:
        s[col] = s[col].fillna(0).astype(int) if col in s else 0
    if acc is not None and len(acc):
        s = s.join(acc.groupby([x for x in by if x in acc.columns] or ["steamid"])[["shots", "hits"]].sum())
        s["accuracy_pct"] = (100 * s["hits"] / s["shots"].replace(0, np.nan)).round(1)
    return s.reset_index().sort_values("rating2", ascending=False).reset_index(drop=True)


def player_stats(d: DemoData) -> pd.DataFrame:
    s = aggregate(player_rounds(d), clutches(d), shots_hits(d))
    if len(s):
        s["team_name"] = s["team"].map({"A": d.meta["team_a"], "B": d.meta["team_b"]})
    return s


def weapon_stats(d: DemoData, steamid: str | None = None) -> pd.DataFrame:
    k = d.kills[d.kills["is_enemy_kill"]]
    dmg = d.damages[d.damages["is_enemy"]]
    sh = d.shots
    if steamid:
        k, dmg, sh = (k[k["attacker_steamid"] == steamid], dmg[dmg["attacker_steamid"] == steamid],
                      sh[sh["player_steamid"] == steamid])
    out = pd.concat([
        k.groupby("weapon").size().rename("kills"),
        k[k["headshot"]].groupby("weapon").size().rename("hs_kills"),
        dmg.groupby("weapon")["dmg_health"].sum().rename("damage"),
        dmg.groupby("weapon").size().rename("hits"),
        sh.groupby("weapon").size().rename("shots"),
    ], axis=1).fillna(0)
    out = out[(out["kills"] > 0) | (out["damage"] > 0)]
    out["hs_pct"] = (100 * out["hs_kills"] / out["kills"].replace(0, np.nan)).fillna(0).round(1)
    firearm = out.index.map(lambda w: WEAPON_CLASS.get(w) in FIREARM_CLASSES)
    out["accuracy_pct"] = np.where(firearm & (out["shots"] > 0),
                                   (100 * out["hits"] / out["shots"].replace(0, np.nan)).round(1), np.nan)
    out["class"] = out.index.map(lambda w: WEAPON_CLASS.get(w, "Otro"))
    return out.rename_axis("weapon").reset_index().sort_values("kills", ascending=False)


def team_stats(d: DemoData) -> pd.DataFrame:
    """Resumen por equipo y lado: rondas ganadas, pistolas, plantas, rendimiento por tipo de compra."""
    r = d.rounds
    rows = []
    for team in ("A", "B"):
        for side in ("CT", "T"):
            mine = r[r[f"{side.lower()}_team"] == team]
            if mine.empty:
                continue
            won = mine["winner_team"] == team
            pist = mine[mine[f"{side.lower()}_buy"] == "Pistola"]
            rows.append({
                "team": team, "side": side, "rounds": len(mine), "won": int(won.sum()),
                "win_pct": round(100 * won.mean(), 1),
                "pistols_won": int((pist["winner_team"] == team).sum()), "pistols": len(pist),
                "plants": int(mine["bomb_planted"].sum()) if side == "T" else None,
            })
    out = pd.DataFrame(rows)
    out["team_name"] = out["team"].map({"A": d.meta["team_a"], "B": d.meta["team_b"]})
    return out


def buy_performance(d: DemoData) -> pd.DataFrame:
    """Win rate de cada equipo según su tipo de compra (independiente del lado)."""
    rows = []
    for side in ("ct", "t"):
        x = d.rounds[["round", f"{side}_team", f"{side}_buy", f"{side}_equip", "winner_team"]].copy()
        x.columns = ["round", "team", "buy", "equip", "winner_team"]
        x["side"] = side.upper()
        rows.append(x)
    x = pd.concat(rows)
    x["won"] = x["team"] == x["winner_team"]
    return x


def opening_duels(d: DemoData) -> pd.DataFrame:
    k = d.kills
    o = k[k["is_opening"]].copy()
    winners = d.rounds.set_index("round")["winner_team"]
    o["round_won_by_opener"] = o["round"].map(winners) == o["attacker_team"]
    return o


def duel_matrix(d: DemoData) -> pd.DataFrame:
    """Kills de cada jugador (filas) sobre cada rival (columnas)."""
    k = d.kills[d.kills["is_enemy_kill"]]
    if k.empty:
        return pd.DataFrame()
    return pd.crosstab(k["attacker_name"], k["victim_name"])


@_per_demo_cache
def round_timeline(d: DemoData) -> pd.DataFrame:
    """Rondas con resumen de kills y diferencia de equipo, para la vista ronda a ronda."""
    r = d.rounds.copy()
    k = d.kills
    if len(k):
        first = k[k["is_opening"]].set_index("round")
        r["first_kill"] = r["round"].map(first["attacker_name"] + " → " + first["victim_name"]).fillna("")
        r["first_kill_team"] = r["round"].map(first["attacker_team"]).fillna("")
        r["kills_a"] = r["round"].map(k[k["is_enemy_kill"] & (k["attacker_team"] == "A")].groupby("round").size()).fillna(0).astype(int)
        r["kills_b"] = r["round"].map(k[k["is_enemy_kill"] & (k["attacker_team"] == "B")].groupby("round").size()).fillna(0).astype(int)
    r["equip_a"] = np.where(r["ct_team"] == "A", r["ct_equip"], r["t_equip"])
    r["equip_b"] = np.where(r["ct_team"] == "B", r["ct_equip"], r["t_equip"])
    r["buy_a"] = np.where(r["ct_team"] == "A", r["ct_buy"], r["t_buy"])
    r["buy_b"] = np.where(r["ct_team"] == "B", r["ct_buy"], r["t_buy"])
    return r
