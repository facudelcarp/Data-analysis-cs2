"""Parseo de demos de CS2 a tablas normalizadas (pandas), con caché en disco.

Toda la lógica "de dominio" (rondas, equipos, tradeos, daño real) se resuelve acá una sola vez;
las capas de estadísticas y UI consumen las tablas ya limpias de `DemoData`.
"""
from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass, field, fields
from pathlib import Path

import numpy as np
import pandas as pd
from demoparser2 import DemoParser

from .constants import (
    BOMB_EVENTS,
    GRENADE_EVENTS,
    ROUND_END_REASONS,
    SIDE_CT,
    SIDE_T,
    TICKRATE,
    TRADE_WINDOW_S,
)

CACHE_VERSION = 1
DEFAULT_CACHE_DIR = Path(os.environ.get("CS2A_CACHE", Path.home() / ".cache" / "cs2analysis"))

PLAYER_PROPS = ["X", "Y", "Z", "team_num", "last_place_name"]
OTHER_PROPS = ["total_rounds_played", "is_warmup_period"]
EVENTS = [
    "begin_new_match", "round_start", "round_freeze_end", "buytime_ended", "round_end",
    "round_officially_ended", "cs_win_panel_match", "round_mvp",
    "player_death", "player_hurt", "player_blind", "weapon_fire",
    *GRENADE_EVENTS, *BOMB_EVENTS,
]
SNAPSHOT_PROPS = [
    "team_num", "team_clan_name", "current_equip_value", "balance", "cash_spent_this_round",
    "armor_value", "has_helmet", "has_defuser", "rank", "comp_wins", "crosshair_code",
]

TABLES = ["players", "rounds", "kills", "damages", "grenades", "blinds", "bomb", "economy",
          "shots", "positions"]


@dataclass
class DemoData:
    meta: dict
    players: pd.DataFrame
    rounds: pd.DataFrame
    kills: pd.DataFrame
    damages: pd.DataFrame
    grenades: pd.DataFrame
    blinds: pd.DataFrame
    bomb: pd.DataFrame
    economy: pd.DataFrame
    shots: pd.DataFrame
    positions: pd.DataFrame = field(default_factory=pd.DataFrame)

    @property
    def demo_id(self) -> str:
        return self.meta["demo_id"]

    @property
    def label(self) -> str:
        m = self.meta
        return f"{m['map']} · {m['score_a']}-{m['score_b']} · {m['file_name']}"

    def save(self, directory: Path) -> None:
        directory.mkdir(parents=True, exist_ok=True)
        for name in TABLES:
            getattr(self, name).to_parquet(directory / f"{name}.parquet", index=False)
        (directory / "meta.json").write_text(json.dumps(self.meta, ensure_ascii=False, indent=2))

    @classmethod
    def load(cls, directory: Path) -> "DemoData":
        meta = json.loads((directory / "meta.json").read_text())
        tables = {n: pd.read_parquet(directory / f"{n}.parquet") for n in TABLES}
        return cls(meta=meta, **tables)


# --------------------------------------------------------------------------------------------
# Caché
# --------------------------------------------------------------------------------------------

def file_hash(path: str | Path, chunk: int = 8 << 20) -> str:
    h = hashlib.sha1()
    with open(path, "rb") as f:
        while block := f.read(chunk):
            h.update(block)
    return h.hexdigest()[:16]


def load_demo(path: str | Path, cache_dir: Path | None = DEFAULT_CACHE_DIR,
              position_step: int = 32) -> DemoData:
    """Parsea `path` o lo levanta de la caché si ya fue procesado con la misma versión."""
    path = Path(path)
    demo_id = file_hash(path)
    if cache_dir is not None:
        target = Path(cache_dir) / f"v{CACHE_VERSION}" / demo_id
        if (target / "meta.json").exists():
            data = DemoData.load(target)
            data.meta["source_path"] = str(path)
            data.meta["file_name"] = path.name
            return data
    data = parse_demo(path, demo_id=demo_id, position_step=position_step)
    if cache_dir is not None:
        data.save(target)
    return data


# --------------------------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------------------------

def _sid(series: pd.Series) -> pd.Series:
    """Normaliza steamids a string ('' cuando no hay jugador: mundo, bomba, etc.)."""
    s = series.astype("string").fillna("")
    return s.str.replace(r"\.0$", "", regex=True).replace({"0": "", "<NA>": "", "nan": ""})


def _side(series: pd.Series) -> pd.Series:
    num = pd.to_numeric(series, errors="coerce")
    return num.map({SIDE_T: "T", SIDE_CT: "CT"}).fillna("")


def _rename_actor(df: pd.DataFrame, src: str, dst: str) -> pd.DataFrame:
    mapping = {
        f"{src}_name": f"{dst}_name", f"{src}_steamid": f"{dst}_steamid",
        f"{src}_team_num": f"{dst}_side", f"{src}_last_place_name": f"{dst}_place",
        f"{src}_X": f"{dst}_x", f"{src}_Y": f"{dst}_y", f"{src}_Z": f"{dst}_z",
    }
    df = df.rename(columns={k: v for k, v in mapping.items() if k in df.columns})
    if f"{dst}_steamid" in df:
        df[f"{dst}_steamid"] = _sid(df[f"{dst}_steamid"])
    if f"{dst}_side" in df:
        df[f"{dst}_side"] = _side(df[f"{dst}_side"])
    if f"{dst}_name" in df:
        df[f"{dst}_name"] = df[f"{dst}_name"].astype("string").fillna("")
    if f"{dst}_place" in df:
        df[f"{dst}_place"] = df[f"{dst}_place"].astype("string").fillna("")
    return df


class _RoundIndex:
    """Ventanas (start, end] de cada ronda para asignar ticks a rondas."""

    def __init__(self, rounds: pd.DataFrame):
        self.starts = rounds["start_tick"].to_numpy()
        self.ends = rounds["official_end_tick"].to_numpy()
        self.numbers = rounds["round"].to_numpy()
        self.freeze = rounds["freeze_end_tick"].to_numpy()

    def assign(self, df: pd.DataFrame) -> pd.DataFrame:
        if df.empty:
            df = df.copy()
            df["round"] = pd.Series(dtype="int64")
            df["time_in_round"] = pd.Series(dtype="float64")
            return df
        ticks = df["tick"].to_numpy()
        idx = np.searchsorted(self.ends, ticks, side="left")
        ok = idx < len(self.ends)
        idx_c = np.clip(idx, 0, max(len(self.ends) - 1, 0))
        ok &= ticks > self.starts[idx_c]
        out = df.loc[ok].copy()
        out["round"] = self.numbers[idx_c[ok]].astype("int64")
        out["time_in_round"] = ((ticks[ok] - self.freeze[idx_c[ok]]) / TICKRATE).round(2)
        return out.reset_index(drop=True)


# --------------------------------------------------------------------------------------------
# Parseo principal
# --------------------------------------------------------------------------------------------

def parse_demo(path: str | Path, demo_id: str | None = None, position_step: int = 32) -> DemoData:
    path = Path(path)
    parser = DemoParser(str(path))
    header = parser.parse_header()
    ev = {name: df for name, df in parser.parse_events(EVENTS, player=PLAYER_PROPS, other=OTHER_PROPS)}

    def event(name: str) -> pd.DataFrame:
        df = ev.get(name)
        if df is None or not isinstance(df, pd.DataFrame):
            return pd.DataFrame(columns=["tick"])
        if "is_warmup_period" in df:
            df = df[~df["is_warmup_period"].fillna(False).astype(bool)]
        return df.sort_values("tick", kind="stable").reset_index(drop=True)

    match_start = int(event("begin_new_match")["tick"].max()) if len(event("begin_new_match")) else 0

    rounds = _build_rounds(event, match_start)
    if rounds.empty:
        raise ValueError(f"{path.name}: no se encontraron rondas jugadas (¿demo de warmup o corrupta?)")
    ridx = _RoundIndex(rounds)

    snapshots = _snapshots(parser, event, rounds)
    players, side_by_round = _assign_teams(snapshots, rounds)
    team_of = dict(zip(players["steamid"], players["team"]))

    rounds["ct_team"] = rounds["round"].map(lambda r: side_by_round[r]["CT"])
    rounds["t_team"] = rounds["round"].map(lambda r: side_by_round[r]["T"])
    rounds["winner_team"] = np.where(rounds["winner_side"] == "CT", rounds["ct_team"], rounds["t_team"])
    rounds["score_a"] = (rounds["winner_team"] == "A").cumsum()
    rounds["score_b"] = (rounds["winner_team"] == "B").cumsum()

    kills = _build_kills(ridx.assign(event("player_death")), team_of)
    damages = _build_damages(ridx.assign(event("player_hurt")), team_of)
    blinds = _build_blinds(ridx.assign(event("player_blind")), team_of)
    grenades = _build_grenades(event, ridx, blinds)
    bomb = _build_bomb(event, ridx)
    rounds = _attach_bomb(rounds, bomb)
    economy, rounds = _build_economy(snapshots, rounds, team_of)
    shots = _build_shots(ridx.assign(event("weapon_fire")))
    damages = _resolve_weapon_variants(damages, shots)
    positions = _build_positions(parser, rounds, ridx, position_step, team_of)

    mvps = event("round_mvp")
    if len(mvps):
        mvps = ridx.assign(_rename_actor(mvps, "user", "player"))
        rounds = rounds.merge(
            mvps.groupby("round").last()[["player_steamid"]].rename(columns={"player_steamid": "mvp_steamid"}),
            on="round", how="left")
    else:
        rounds["mvp_steamid"] = ""
    rounds["mvp_steamid"] = rounds["mvp_steamid"].fillna("")

    names = {"A": "Equipo A", "B": "Equipo B"}
    for t in ("A", "B"):
        clan = players.loc[players["team"] == t, "team_clan_name"]
        clan = clan[clan.astype(str).str.len() > 0]
        if len(clan):
            names[t] = str(clan.mode().iloc[0])
    players["team_name"] = players["team"].map(names)

    last = rounds.iloc[-1]
    stat = path.stat()
    meta = {
        "demo_id": demo_id or file_hash(path),
        "file_name": path.name,
        "source_path": str(path),
        "file_size_mb": round(stat.st_size / 1e6, 1),
        "file_mtime": pd.Timestamp(stat.st_mtime, unit="s").isoformat(),
        "map": header.get("map_name", "desconocido"),
        "server": header.get("server_name", ""),
        "client": header.get("client_name", ""),
        "patch_version": header.get("patch_version", ""),
        "tickrate": TICKRATE,
        "match_start_tick": match_start,
        "rounds": int(len(rounds)),
        "duration_min": round((last["official_end_tick"] - match_start) / TICKRATE / 60, 1),
        "score_a": int(last["score_a"]),
        "score_b": int(last["score_b"]),
        "team_a": names["A"],
        "team_b": names["B"],
        "start_side_a": side_by_round[int(rounds["round"].iloc[0])]["A"],
        "winner": "A" if last["score_a"] > last["score_b"] else ("B" if last["score_b"] > last["score_a"] else "empate"),
        "cache_version": CACHE_VERSION,
    }
    return DemoData(meta=meta, players=players, rounds=rounds, kills=kills, damages=damages,
                    grenades=grenades, blinds=blinds, bomb=bomb, economy=economy, shots=shots,
                    positions=positions)


def _build_rounds(event, match_start: int) -> pd.DataFrame:
    ends = event("round_end")
    ends = ends[(ends["tick"] > match_start)]
    if "reason" in ends:
        ends = ends[pd.to_numeric(ends["reason"], errors="coerce") != 16]  # "Game commencing"
    if ends.empty:
        return pd.DataFrame()
    ends = ends.drop_duplicates("total_rounds_played", keep="last").sort_values("tick").reset_index(drop=True)

    official = event("round_officially_ended")["tick"].to_numpy()
    freeze = event("round_freeze_end")["tick"].to_numpy()
    win_panel = event("cs_win_panel_match")["tick"]
    end_ticks = ends["tick"].to_numpy()

    rows, prev_end = [], match_start
    for i, r in ends.iterrows():
        end = int(r["tick"])
        nxt = end_ticks[i + 1] if i + 1 < len(end_ticks) else np.inf
        cand = official[(official > end) & (official < nxt)]
        if len(cand):
            off = int(cand[0])
        elif i + 1 == len(end_ticks) and len(win_panel):
            off = int(max(win_panel.max(), end))
        else:
            off = int(min(end + 5 * TICKRATE, nxt - 1))
        fz = freeze[(freeze > prev_end) & (freeze <= end)]
        fz_tick = int(fz[-1]) if len(fz) else prev_end
        winner = pd.to_numeric(r.get("winner"), errors="coerce")
        reason = int(pd.to_numeric(r.get("reason"), errors="coerce") or 0)
        rows.append({
            "round": int(r["total_rounds_played"]) + 1,
            "start_tick": int(prev_end),
            "freeze_end_tick": fz_tick,
            "end_tick": end,
            "official_end_tick": off,
            "duration_s": round((end - fz_tick) / TICKRATE, 1),
            "winner_side": {SIDE_T: "T", SIDE_CT: "CT"}.get(winner, ""),
            "reason_code": reason,
            "reason": ROUND_END_REASONS.get(reason, str(r.get("message", reason))),
        })
        prev_end = off
    out = pd.DataFrame(rows)
    # Si la demo empieza a mitad de partido los números de ronda igual quedan consecutivos
    return out.drop_duplicates("round", keep="last").reset_index(drop=True)


def _snapshots(parser: DemoParser, event, rounds: pd.DataFrame) -> pd.DataFrame:
    """Estado de cada jugador al final del freeze time y al final del tiempo de compra."""
    buy_end = event("buytime_ended")["tick"].to_numpy()
    fz, buy = [], []
    for r in rounds.itertuples():
        fz.append(r.freeze_end_tick)
        cand = buy_end[(buy_end > r.freeze_end_tick) & (buy_end <= r.end_tick)]
        buy.append(int(cand[0]) if len(cand) else min(r.freeze_end_tick + 20 * TICKRATE, r.end_tick))
    ticks = sorted(set(fz) | set(buy))
    snap = parser.parse_ticks(SNAPSHOT_PROPS, ticks=ticks)
    if snap.empty:
        return snap
    snap["steamid"] = _sid(snap["steamid"])
    snap = snap[snap["steamid"] != ""]
    snap = snap[pd.to_numeric(snap["team_num"], errors="coerce").isin([SIDE_T, SIDE_CT])]
    tick_to_round = {t: r for t, r in zip(fz, rounds["round"])}
    at_fz = snap[snap["tick"].isin(fz)].copy()
    at_fz["round"] = at_fz["tick"].map(tick_to_round)
    buy_to_round = {t: r for t, r in zip(buy, rounds["round"])}
    at_buy = snap[snap["tick"].isin(buy)].copy()
    at_buy["round"] = at_buy["tick"].map(buy_to_round)
    # El valor de equipo puede subir después del freeze (aún hay tiempo de compra): nos quedamos
    # con el máximo de ambos snapshots; el resto de los campos sale del freeze end.
    best = (pd.concat([at_fz, at_buy]).groupby(["round", "steamid"])
            [["current_equip_value", "armor_value"]].max().reset_index())
    at_fz = at_fz.drop(columns=["current_equip_value", "armor_value"]).merge(best, on=["round", "steamid"])
    at_fz["side"] = _side(at_fz["team_num"])
    return at_fz.reset_index(drop=True)


def _assign_teams(snap: pd.DataFrame, rounds: pd.DataFrame):
    """Identidad de equipo estable (A/B) a través de los cambios de lado.

    El equipo A es el que arranca CT. En cada ronda se compara el roster de cada lado con los
    rosters acumulados: así funciona con halftime, overtime, reconexiones y jugadores nuevos.
    """
    rosters = {"A": set(), "B": set()}
    side_by_round: dict[int, dict[str, str]] = {}
    team_of: dict[str, str] = {}
    for rnd in rounds["round"]:
        cur = snap[snap["round"] == rnd]
        ct = set(cur.loc[cur["side"] == "CT", "steamid"])
        t = set(cur.loc[cur["side"] == "T", "steamid"])
        if not rosters["A"] and not rosters["B"]:
            a_side = "CT"
        else:
            score_ct_a = len(ct & rosters["A"]) + len(t & rosters["B"])
            score_ct_b = len(ct & rosters["B"]) + len(t & rosters["A"])
            a_side = "CT" if score_ct_a >= score_ct_b else "T"
        b_side = "T" if a_side == "CT" else "CT"
        side_by_round[int(rnd)] = {"A": a_side, "B": b_side, a_side: "A", b_side: "B"}
        a_players, b_players = (ct, t) if a_side == "CT" else (t, ct)
        rosters["A"] |= a_players
        rosters["B"] |= b_players
        for s in a_players:
            team_of[s] = "A"
        for s in b_players:
            team_of[s] = "B"

    last = snap.sort_values("tick").groupby("steamid").last().reset_index()
    first_round = snap.groupby("steamid")["round"].min()
    players = pd.DataFrame({
        "steamid": last["steamid"],
        "name": last["name"].astype(str),
        "team": last["steamid"].map(team_of),
        "team_clan_name": last["team_clan_name"].fillna("").astype(str),
        "rank": pd.to_numeric(last["rank"], errors="coerce").fillna(0).astype(int),
        "comp_wins": pd.to_numeric(last["comp_wins"], errors="coerce").fillna(0).astype(int),
        "crosshair_code": last["crosshair_code"].fillna("").astype(str),
        "first_round": last["steamid"].map(first_round).astype(int),
        "rounds_played": last["steamid"].map(snap.groupby("steamid")["round"].nunique()).astype(int),
    })
    return players.sort_values(["team", "name"]).reset_index(drop=True), side_by_round


def _build_kills(df: pd.DataFrame, team_of: dict) -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame(columns=["tick", "round", "attacker_steamid", "victim_steamid"])
    df = _rename_actor(df, "attacker", "attacker")
    df = _rename_actor(df, "user", "victim")
    df = _rename_actor(df, "assister", "assister")
    for b in ["headshot", "penetrated", "thrusmoke", "noscope", "attackerblind", "assistedflash"]:
        if b in df:
            df[b] = pd.to_numeric(df[b], errors="coerce").fillna(0).astype(bool)
    df["weapon"] = df["weapon"].astype("string").fillna("").str.removeprefix("weapon_")
    df["is_suicide"] = (df["attacker_steamid"] == "") | (df["attacker_steamid"] == df["victim_steamid"])
    df["is_teamkill"] = ~df["is_suicide"] & (df["attacker_side"] == df["victim_side"])
    df["is_enemy_kill"] = ~df["is_suicide"] & ~df["is_teamkill"]
    df["assist_valid"] = (df["assister_steamid"] != "") & (df["assister_side"] != df["victim_side"])
    df["attacker_team"] = df["attacker_steamid"].map(team_of).fillna("")
    df["victim_team"] = df["victim_steamid"].map(team_of).fillna("")

    window = int(TRADE_WINDOW_S * TICKRATE)
    df["is_trade"] = False
    df["was_traded"] = False
    df["is_opening"] = False
    for _, g in df.groupby("round", sort=False):
        enemy = g[g["is_enemy_kill"]]
        if len(enemy):
            df.loc[enemy.index[0], "is_opening"] = True
        for i, k in enemy.iterrows():
            # k vengó a un compañero si en la ventana previa la víctima de k mató a alguien del lado de k
            prev = enemy[(enemy["tick"] <= k["tick"]) & (enemy["tick"] >= k["tick"] - window)
                         & (enemy.index != i) & (enemy["attacker_steamid"] == k["victim_steamid"])
                         & (enemy["victim_side"] == k["attacker_side"])]
            prev = prev[prev.index < i]
            if len(prev):
                df.loc[i, "is_trade"] = True
                df.loc[prev.index, "was_traded"] = True

    keep = ["tick", "round", "time_in_round",
            "attacker_steamid", "attacker_name", "attacker_side", "attacker_team", "attacker_place",
            "attacker_x", "attacker_y", "attacker_z",
            "victim_steamid", "victim_name", "victim_side", "victim_team", "victim_place",
            "victim_x", "victim_y", "victim_z",
            "assister_steamid", "assister_name", "assist_valid", "assistedflash",
            "weapon", "headshot", "hitgroup", "penetrated", "thrusmoke", "noscope", "attackerblind",
            "distance", "is_suicide", "is_teamkill", "is_enemy_kill", "is_opening", "is_trade", "was_traded"]
    return df[[c for c in keep if c in df.columns]].reset_index(drop=True)


def _build_damages(df: pd.DataFrame, team_of: dict) -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame(columns=["tick", "round", "attacker_steamid", "victim_steamid", "dmg_health"])
    df = _rename_actor(df, "attacker", "attacker")
    df = _rename_actor(df, "user", "victim")
    df["weapon"] = df["weapon"].astype("string").fillna("").str.removeprefix("weapon_")
    df["dmg_health_raw"] = pd.to_numeric(df["dmg_health"], errors="coerce").fillna(0).astype(int)
    df["health"] = pd.to_numeric(df["health"], errors="coerce").fillna(0).astype(int)
    df["dmg_armor"] = pd.to_numeric(df["dmg_armor"], errors="coerce").fillna(0).astype(int)

    # Daño real = vida antes del golpe - vida después. El campo dmg_health del evento es "bruto"
    # (un AWP al pecho informa 115 aunque a la víctima le queden 30) y además redondea distinto
    # que el motor en daños fraccionarios (fuego). Así coincide con el damage_total del scoreboard.
    df = df.sort_values(["round", "victim_steamid", "tick"], kind="stable")
    prev_hp = df.groupby(["round", "victim_steamid"])["health"].shift(1).fillna(100)
    df["dmg_health"] = (prev_hp - df["health"]).clip(lower=0).astype(int)
    df = df.sort_values("tick", kind="stable")

    df["is_self"] = (df["attacker_steamid"] == "") | (df["attacker_steamid"] == df["victim_steamid"])
    df["is_team_damage"] = ~df["is_self"] & (df["attacker_side"] == df["victim_side"])
    df["is_enemy"] = ~df["is_self"] & ~df["is_team_damage"]
    df["attacker_team"] = df["attacker_steamid"].map(team_of).fillna("")
    df["victim_team"] = df["victim_steamid"].map(team_of).fillna("")
    keep = ["tick", "round", "time_in_round", "attacker_steamid", "attacker_name", "attacker_side",
            "attacker_team", "attacker_x", "attacker_y", "victim_steamid", "victim_name", "victim_side",
            "victim_team", "victim_x", "victim_y", "victim_place", "weapon", "hitgroup", "dmg_health",
            "dmg_health_raw", "dmg_armor", "health", "is_self", "is_team_damage", "is_enemy"]
    return df[[c for c in keep if c in df.columns]].reset_index(drop=True)


# player_hurt no distingue variantes que comparten slot (M4A1-S se informa como "m4a1", USP-S como
# "hkp2000", etc.). weapon_fire sí: tomamos el último disparo del atacante para desambiguar.
WEAPON_VARIANTS = {
    "m4a1": {"m4a1", "m4a1_silencer", "m4a1_silencer_off"},
    "hkp2000": {"hkp2000", "usp_silencer", "usp_silencer_off"},
    "p250": {"p250", "cz75a"},
    "deagle": {"deagle", "revolver"},
    "mp7": {"mp7", "mp5sd"},
}


def _resolve_weapon_variants(damages: pd.DataFrame, shots: pd.DataFrame) -> pd.DataFrame:
    if damages.empty or shots.empty:
        return damages
    amb = damages["weapon"].isin(WEAPON_VARIANTS.keys())
    if not amb.any():
        return damages
    left = damages.loc[amb, ["tick", "attacker_steamid", "weapon"]].reset_index()
    left["tick"] = left["tick"].astype("int64")
    right = shots[["tick", "player_steamid", "weapon"]].rename(
        columns={"player_steamid": "attacker_steamid", "weapon": "fired"}).copy()
    right["tick"] = right["tick"].astype("int64")
    left["attacker_steamid"] = left["attacker_steamid"].astype(str)
    right["attacker_steamid"] = right["attacker_steamid"].astype(str)
    m = pd.merge_asof(left.sort_values("tick"), right.sort_values("tick"), on="tick",
                      by="attacker_steamid", direction="backward", tolerance=2 * TICKRATE)
    ok = [isinstance(f, str) and f in WEAPON_VARIANTS[w] for w, f in zip(m["weapon"], m["fired"])]
    m = m[ok]
    damages = damages.copy()
    damages.loc[m["index"].to_numpy(), "weapon"] = m["fired"].str.replace("_off", "", regex=False).to_numpy()
    return damages


def _build_blinds(df: pd.DataFrame, team_of: dict) -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame(columns=["tick", "round", "attacker_steamid", "victim_steamid",
                                     "blind_duration", "is_enemy", "entityid"])
    df = _rename_actor(df, "attacker", "attacker")
    df = _rename_actor(df, "user", "victim")
    df["blind_duration"] = pd.to_numeric(df["blind_duration"], errors="coerce").fillna(0).astype(float).round(2)
    df["is_self"] = df["attacker_steamid"] == df["victim_steamid"]
    df["is_enemy"] = ~df["is_self"] & (df["attacker_side"] != df["victim_side"])
    df["attacker_team"] = df["attacker_steamid"].map(team_of).fillna("")
    keep = ["tick", "round", "time_in_round", "entityid", "attacker_steamid", "attacker_name",
            "attacker_side", "attacker_team", "victim_steamid", "victim_name", "victim_side",
            "blind_duration", "is_self", "is_enemy"]
    return df[[c for c in keep if c in df.columns]].reset_index(drop=True)


def _build_grenades(event, ridx: _RoundIndex, blinds: pd.DataFrame) -> pd.DataFrame:
    frames = []
    for name, label in GRENADE_EVENTS.items():
        df = event(name)
        if df.empty:
            continue
        df = _rename_actor(df, "user", "thrower")
        df["grenade"] = label
        frames.append(df)
    if not frames:
        return pd.DataFrame(columns=["tick", "round", "grenade", "thrower_steamid", "x", "y", "z"])
    df = ridx.assign(pd.concat(frames, ignore_index=True).sort_values("tick"))
    df = df.rename(columns={"thrower_x": "thrower_px", "thrower_y": "thrower_py", "thrower_z": "thrower_pz"})
    # Para las flashes: cuántos enemigos cegó y por cuánto tiempo (match por entityid + ronda)
    df["enemies_blinded"] = 0
    df["blind_time_enemies"] = 0.0
    df["teammates_blinded"] = 0
    if len(blinds) and "entityid" in df:
        b = blinds[~blinds["is_self"]]
        agg = b.groupby(["round", "entityid"]).agg(
            enemies_blinded=("is_enemy", "sum"),
            blind_time_enemies=("blind_duration", lambda s: s[b.loc[s.index, "is_enemy"]].sum()),
            teammates_blinded=("is_enemy", lambda s: (~s).sum()),
        ).reset_index()
        flash = df["grenade"] == "Flash"
        merged = df.loc[flash, ["round", "entityid"]].merge(agg, on=["round", "entityid"], how="left")
        for c in ["enemies_blinded", "blind_time_enemies", "teammates_blinded"]:
            df.loc[flash, c] = merged[c].fillna(0).to_numpy()
    keep = ["tick", "round", "time_in_round", "grenade", "entityid", "thrower_steamid", "thrower_name",
            "thrower_side", "thrower_place", "x", "y", "z", "enemies_blinded", "blind_time_enemies",
            "teammates_blinded"]
    return df[[c for c in keep if c in df.columns]].reset_index(drop=True)


def _build_bomb(event, ridx: _RoundIndex) -> pd.DataFrame:
    frames = []
    for name, label in BOMB_EVENTS.items():
        df = event(name)
        if df.empty:
            continue
        df = _rename_actor(df, "user", "player")
        df["event"] = label
        df["event_code"] = name
        frames.append(df)
    if not frames:
        return pd.DataFrame(columns=["tick", "round", "event", "event_code", "site", "site_letter"])
    df = ridx.assign(pd.concat(frames, ignore_index=True).sort_values("tick"))
    if "site" not in df:
        df["site"] = np.nan
    # El evento trae el entity id del trigger del sitio; lo traducimos a A/B por la zona del plantador
    letters: dict[int, str] = {}
    planted = df[df["event_code"].isin(["bomb_planted", "bomb_beginplant"]) & df["site"].notna()]
    for site, g in planted.groupby("site"):
        places = " ".join(g["player_place"].astype(str)).lower()
        a, b = places.count("bombsitea"), places.count("bombsiteb")
        if a != b:
            letters[int(site)] = "A" if a > b else "B"
    known = set(letters.values())
    unknown = [int(s) for s in planted["site"].unique() if int(s) not in letters]
    if len(known) == 1 and len(unknown) == 1:
        letters[unknown[0]] = "B" if "A" in known else "A"
    df["site_letter"] = df["site"].map(lambda s: letters.get(int(s), f"#{int(s)}") if pd.notna(s) else "")
    keep = ["tick", "round", "time_in_round", "event", "event_code", "player_steamid", "player_name",
            "player_side", "player_place", "player_x", "player_y", "player_z", "site", "site_letter"]
    return df[[c for c in keep if c in df.columns]].reset_index(drop=True)


def _attach_bomb(rounds: pd.DataFrame, bomb: pd.DataFrame) -> pd.DataFrame:
    rounds = rounds.copy()
    planted = bomb[bomb["event_code"] == "bomb_planted"].groupby("round").last() if len(bomb) else pd.DataFrame()
    rounds["bomb_planted"] = rounds["round"].isin(planted.index)
    rounds["bomb_site"] = rounds["round"].map(planted["site_letter"] if len(planted) else {}).fillna("")
    return rounds


def buy_type(value: float, pistol: bool) -> str:
    from .constants import BUY_THRESHOLDS
    if pistol:
        return "Pistola"
    for limit, label in BUY_THRESHOLDS:
        if value < limit:
            return label
    return "Full buy"


def _pistol_rounds(rounds: pd.Series) -> set[int]:
    # MR12: rondas 1 y 13. El overtime no tiene pistol round.
    return {r for r in rounds if r in (1, 13)}


def _build_economy(snap: pd.DataFrame, rounds: pd.DataFrame, team_of: dict):
    eco = snap[["round", "steamid", "name", "side", "current_equip_value", "balance",
                "cash_spent_this_round", "armor_value", "has_helmet", "has_defuser"]].rename(
        columns={"current_equip_value": "equip_value", "cash_spent_this_round": "cash_spent"})
    eco["team"] = eco["steamid"].map(team_of)
    for c in ["equip_value", "balance", "cash_spent", "armor_value"]:
        eco[c] = pd.to_numeric(eco[c], errors="coerce").fillna(0).astype(int)
    pistols = _pistol_rounds(rounds["round"])
    team_eq = eco.groupby(["round", "side"]).agg(equip=("equip_value", "sum"), bank=("balance", "sum"))
    rounds = rounds.copy()
    for side in ("CT", "T"):
        s = side.lower()
        vals = team_eq.xs(side, level="side") if side in team_eq.index.get_level_values("side") else pd.DataFrame()
        rounds[f"{s}_equip"] = rounds["round"].map(vals["equip"] if len(vals) else {}).fillna(0).astype(int)
        rounds[f"{s}_bank"] = rounds["round"].map(vals["bank"] if len(vals) else {}).fillna(0).astype(int)
        rounds[f"{s}_buy"] = [buy_type(v, r in pistols) for v, r in zip(rounds[f"{s}_equip"], rounds["round"])]
    return eco.sort_values(["round", "team", "name"]).reset_index(drop=True), rounds


def _build_shots(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame(columns=["tick", "round", "player_steamid", "weapon"])
    df = _rename_actor(df, "user", "player")
    df["weapon"] = df["weapon"].astype("string").fillna("").str.removeprefix("weapon_")
    return df[["tick", "round", "time_in_round", "player_steamid", "player_name", "player_side", "weapon"]]


def _build_positions(parser: DemoParser, rounds: pd.DataFrame, ridx: _RoundIndex, step: int,
                     team_of: dict) -> pd.DataFrame:
    if step <= 0:
        return pd.DataFrame(columns=["tick", "round", "steamid", "x", "y", "z", "side"])
    ticks = np.concatenate([np.arange(r.freeze_end_tick, r.end_tick, step) for r in rounds.itertuples()])
    if len(ticks) == 0:
        return pd.DataFrame(columns=["tick", "round", "steamid", "x", "y", "z", "side"])
    pos = parser.parse_ticks(["X", "Y", "Z", "team_num", "is_alive", "health"], ticks=ticks.tolist())
    if pos.empty:
        return pd.DataFrame(columns=["tick", "round", "steamid", "x", "y", "z", "side"])
    pos = pos[pos["is_alive"].fillna(False).astype(bool)]
    pos["steamid"] = _sid(pos["steamid"])
    pos["side"] = _side(pos["team_num"])
    pos = pos[pos["side"] != ""]
    pos = ridx.assign(pos.rename(columns={"X": "x", "Y": "y", "Z": "z"}))
    pos["team"] = pos["steamid"].map(team_of).fillna("")
    for c in ["x", "y", "z"]:
        pos[c] = pos[c].astype("float32")
    pos["health"] = pd.to_numeric(pos["health"], errors="coerce").fillna(0).astype("int16")
    return pos[["tick", "round", "time_in_round", "steamid", "name", "side", "team", "x", "y", "z",
                "health"]].reset_index(drop=True)
