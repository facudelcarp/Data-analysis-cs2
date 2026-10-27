"""Módulo de análisis integral de equipos para CS2.

Calcula estadísticas y métricas clave orientadas al rendimiento colectivo:
- Trade Analytics: Kills tradeadas, Trade% en muertes, Winrate de rondas con tradeo (Trade% -> Round Win),
  tiempo promedio de refrag y química de parejas de tradeo (quién refraggea a quién).
- Man Advantage: Tasa de conversión 5v4 y tasa de recuperación 4v5.
- Lados T vs CT: Rondas ganadas, sesgo de lado y efectividad atacando vs defendiendo.
- Pistolas y Follow-ups: Winrate en rondas de pistola (1 y 13) y conversión de segunda ronda.
- Map Pool Stats: Rendimiento desagregado por mapa (partidas, rondas, winrates, trades y 5v4).
- Utilidad colectiva: Daño de utilidad por ronda, flashes a rivales y team flashes.
"""
from __future__ import annotations

import re
from typing import Any
import numpy as np
import pandas as pd

from .parser import DemoData, TICKRATE, TRADE_WINDOW_S
from .maps import pretty_map
from . import stats, archetypes


TEAM_STOPWORDS = {
    "team", "gaming", "esports", "esport", "e-sports", "club", "clan",
    "gg", "cs", "cs2", "org", "co", "the", "official", "hq", "corp",
    "inc", "organization", "academy", "talent", "rising", "fe", "pro",
    "de", "del", "el", "la", "los", "las", "in", "of", "and", "en",
}


def extract_team_keywords(name: str) -> set[str]:
    """Extrae palabras clave significativas ignorando palabras genericas como team, gaming, esports, etc."""
    tokens = re.findall(r"[a-z0-9]+", name.lower())
    kw = {t for t in tokens if len(t) >= 2 and t not in TEAM_STOPWORDS}
    if not kw:
        clean = re.sub(r"[^a-z0-9]", "", name.lower())
        if clean:
            kw = {clean}
    return kw


def get_grouped_teams(demos: list[DemoData]) -> list[dict[str, Any]]:
    """Agrupa nombres de equipos que compartan palabras clave no genericas (ej. BESTIA y BESTIA Esports).

    Devuelve lista de grupos con nombre canonico, variantes exactas y cantidad de partidas.
    """
    raw_counts: dict[str, int] = {}
    for d in demos:
        for t_key in ("team_a", "team_b"):
            name = d.meta.get(t_key, "").strip()
            if name:
                raw_counts[name] = raw_counts.get(name, 0) + 1

    unique_names = list(raw_counts.keys())
    if not unique_names:
        return []

    name_keywords = {name: extract_team_keywords(name) for name in unique_names}

    parent = {name: name for name in unique_names}

    def find(i: str) -> str:
        curr = i
        path = []
        while parent[curr] != curr:
            path.append(curr)
            curr = parent[curr]
        for node in path:
            parent[node] = curr
        return curr

    def union(i: str, j: str) -> None:
        ri, rj = find(i), find(j)
        if ri != rj:
            parent[ri] = rj

    n = len(unique_names)
    for i in range(n):
        for j in range(i + 1, n):
            n1 = unique_names[i]
            n2 = unique_names[j]
            kw1 = name_keywords[n1]
            kw2 = name_keywords[n2]
            if kw1 and kw2 and (kw1 & kw2):
                union(n1, n2)

    groups_dict: dict[str, list[str]] = {}
    for name in unique_names:
        r = find(name)
        groups_dict.setdefault(r, []).append(name)

    result = []
    for root, members in groups_dict.items():
        # Ordenar variantes: mas jugadas primero, luego menor longitud
        members_sorted = sorted(members, key=lambda m: (-raw_counts.get(m, 0), len(m), m))
        canonical = members_sorted[0]

        member_set = set(members)
        matches_played = 0
        for d in demos:
            ta = d.meta.get("team_a", "").strip()
            tb = d.meta.get("team_b", "").strip()
            if ta in member_set or tb in member_set:
                matches_played += 1

        result.append({
            "canonical_name": canonical,
            "raw_names": members_sorted,
            "matches": matches_played,
            "raw_counts": {m: raw_counts.get(m, 0) for m in members_sorted},
        })

    result.sort(key=lambda g: (-g["matches"], g["canonical_name"].lower()))
    return result


def get_available_teams(demos: list[DemoData]) -> list[tuple[str, int]]:
    """Devuelve la lista de equipos unicos disponibles en las demos cargadas y cuantas veces jugaron."""
    grouped = get_grouped_teams(demos)
    return [(g["canonical_name"], g["matches"]) for g in grouped]


def analyze_team(
    demos: list[DemoData],
    target_team: str | list[str] | set[str],
    map_name: str | None = None,
    display_name: str | None = None,
    instances: set[tuple[str, str]] | None = None,
) -> dict[str, Any]:
    """Calcula el analisis completo de un equipo (o grupo de variantes de nombre) a lo largo de demos.

    Con `instances` ({(demo_id, "A"|"B")}, ver identity.cluster_teams) el equipo se identifica por partida y
    lado, sin depender del nombre: es lo correcto cuando los nombres son genéricos ("Equipo A")."""
    trade_window_ticks = int(TRADE_WINDOW_S * TICKRATE)

    if isinstance(target_team, str):
        target_team_set = {target_team.strip()}
        default_name = target_team.strip()
    else:
        target_team_set = {t.strip() for t in target_team if t and t.strip()}
        default_name = list(target_team)[0] if target_team else ""

    team_display = display_name if display_name else default_name

    # Filtrar demos donde jugo alguna de las variantes del equipo
    side_of = dict(instances) if instances else {}
    relevant_demos = []
    for d in demos:
        ta = d.meta.get("team_a", "").strip()
        tb = d.meta.get("team_b", "").strip()
        if (d.demo_id in side_of) if instances else (ta in target_team_set or tb in target_team_set):
            if map_name and map_name != "Todos los mapas" and d.meta.get("map") != map_name:
                continue
            relevant_demos.append(d)

    if not relevant_demos:
        return {}

    # Acumuladores
    matches_played = len(relevant_demos)
    matches_won = 0
    matches_lost = 0
    matches_tied = 0

    total_rounds = 0
    total_rounds_won = 0

    rounds_t_played = 0
    rounds_t_won = 0
    rounds_ct_played = 0
    rounds_ct_won = 0

    rounds_5v4_total = 0
    rounds_5v4_won = 0
    rounds_4v5_total = 0
    rounds_4v5_won = 0

    pistols_played = 0
    pistols_won = 0
    pistol_followups_played = 0
    pistol_followups_won = 0

    team_kills_count = 0
    team_deaths_count = 0
    team_trades_count = 0
    team_traded_deaths_count = 0

    rounds_with_trade_count = 0
    rounds_won_with_trade_count = 0
    rounds_no_trade_count = 0
    rounds_won_no_trade_count = 0

    trade_delays: list[float] = []
    trade_pairs_counts: dict[tuple[str, str], list[float]] = {}  # (refragger, avenged) -> [delays]

    # Recolectores de datos de jugadores del equipo
    team_pr_list: list[pd.DataFrame] = []
    team_clutches_list: list[pd.DataFrame] = []
    team_shots_list: list[pd.DataFrame] = []
    player_team_blinds: dict[str, int] = {}

    util_damage_total = 0.0
    flashes_enemies_total = 0
    flashes_teammates_total = 0

    # Desglose por mapa
    map_stats: dict[str, dict[str, Any]] = {}

    for d in relevant_demos:
        m = d.meta
        cur_map = m.get("map", "")
        ta = m.get("team_a", "").strip()
        tb = m.get("team_b", "").strip()
        is_team_a = ta in target_team_set
        is_team_b = tb in target_team_set

        if instances:
            my_code = side_of[d.demo_id]
        elif is_team_a and not is_team_b:
            my_code = "A"
        elif is_team_b and not is_team_a:
            my_code = "B"
        else:
            my_code = "A"
        opp_code = "B" if my_code == "A" else "A"

        score_my = int(m.get("score_a", 0) if my_code == "A" else m.get("score_b", 0))
        score_opp = int(m.get("score_b", 0) if my_code == "A" else m.get("score_a", 0))

        if score_my > score_opp:
            matches_won += 1
        elif score_my < score_opp:
            matches_lost += 1
        else:
            matches_tied += 1

        # Inicializar mapa si no existe
        if cur_map not in map_stats:
            map_stats[cur_map] = {
                "map": cur_map,
                "matches": 0, "matches_won": 0,
                "rounds": 0, "rounds_won": 0,
                "rounds_t": 0, "rounds_t_won": 0,
                "rounds_ct": 0, "rounds_ct_won": 0,
                "trades": 0, "deaths": 0, "traded_deaths": 0,
                "rounds_5v4": 0, "rounds_5v4_won": 0,
                "util_damage": 0.0,
            }
        ms = map_stats[cur_map]
        ms["matches"] += 1
        if score_my > score_opp:
            ms["matches_won"] += 1

        # Rondas de la demo
        r_df = d.rounds
        k_df = d.kills
        dmg_df = d.damages

        # Daño de utilidad
        if not dmg_df.empty:
            my_steamids = set(d.players[d.players["team"] == my_code]["steamid"])
            u_dmg = dmg_df[dmg_df["attacker_steamid"].isin(my_steamids) & dmg_df["is_enemy"]]
            u_dmg_val = float(u_dmg[u_dmg["weapon"].isin(["hegrenade", "molotov", "incgrenade"])]["dmg_health"].sum())
            util_damage_total += u_dmg_val
            ms["util_damage"] += u_dmg_val

        # Granadas / Flashes
        if not d.grenades.empty:
            my_gr = d.grenades[d.grenades["thrower_team"] == my_code]
            flashes_enemies_total += int(my_gr.get("enemies_blinded", pd.Series(dtype=int)).sum())
            flashes_teammates_total += int(my_gr.get("teammates_blinded", pd.Series(dtype=int)).sum())

        # Recolectar datos por jugador para análisis individual del equipo
        my_steamids = set(d.players[d.players["team"] == my_code]["steamid"]) if not d.players.empty else set()
        try:
            pr = stats.player_rounds(d)
            if not pr.empty and my_steamids:
                pr_mine = pr[pr["steamid"].isin(my_steamids)].copy()
                if not pr_mine.empty:
                    team_pr_list.append(pr_mine)
        except Exception:
            pass

        try:
            cl = stats.clutches(d)
            if cl is not None and not cl.empty and my_steamids:
                cl_mine = cl[cl["steamid"].isin(my_steamids)]
                if not cl_mine.empty:
                    team_clutches_list.append(cl_mine)
        except Exception:
            pass

        try:
            sh = stats.shots_hits(d)
            if sh is not None and not sh.empty and my_steamids:
                sh_mine = sh[sh["steamid"].isin(my_steamids)]
                if not sh_mine.empty:
                    team_shots_list.append(sh_mine)
        except Exception:
            pass

        if not d.blinds.empty and my_steamids:
            bl_tm = d.blinds[d.blinds["attacker_steamid"].isin(my_steamids) & (~d.blinds["is_enemy"])]
            for sid, count in bl_tm.groupby("attacker_steamid").size().items():
                player_team_blinds[sid] = player_team_blinds.get(sid, 0) + int(count)

        # Kills y Refrags detallados de la demo. Agrupar una vez por partida: filtrar la tabla entera en cada
        # ronda hacía que analizar un equipo con 80 partidas tardara ~25 s.
        kills_by_round = {int(r): g for r, g in k_df.groupby("round")} if not k_df.empty else {}
        winner_by_round = dict(zip(r_df["round"].astype(int), r_df["winner_team"])) if not r_df.empty else {}
        for rnd_num, r_row in r_df.iterrows():
            total_rounds += 1
            ms["rounds"] += 1

            winner = r_row.get("winner_team")
            won_round = (winner == my_code)
            if won_round:
                total_rounds_won += 1
                ms["rounds_won"] += 1

            # Lados
            my_side = "CT" if r_row.get("ct_team") == my_code else "T"
            if my_side == "T":
                rounds_t_played += 1
                ms["rounds_t"] += 1
                if won_round:
                    rounds_t_won += 1
                    ms["rounds_t_won"] += 1
            else:
                rounds_ct_played += 1
                ms["rounds_ct"] += 1
                if won_round:
                    rounds_ct_won += 1
                    ms["rounds_ct_won"] += 1

            # Rondas de pistola (1 y 13 en MR12)
            rnd_idx = int(r_row.get("round", 0))
            is_pistol = (rnd_idx in (1, 13))
            if is_pistol:
                pistols_played += 1
                if won_round:
                    pistols_won += 1

            # Conversión de segunda ronda tras ganar pistola
            if rnd_idx in (2, 14):
                prev_rnd = rnd_idx - 1
                if winner_by_round.get(prev_rnd) == my_code:
                    pistol_followups_played += 1
                    if won_round:
                        pistol_followups_won += 1

            # Kills de la ronda
            rnd_kills = kills_by_round.get(rnd_idx)
            if rnd_kills is None or rnd_kills.empty:
                continue

            enemy_kills = rnd_kills[rnd_kills["is_enemy_kill"]]
            if not enemy_kills.empty:
                first_k = enemy_kills.iloc[0]
                first_k_team = first_k.get("attacker_team")
                if first_k_team == my_code:
                    rounds_5v4_total += 1
                    ms["rounds_5v4"] += 1
                    if won_round:
                        rounds_5v4_won += 1
                        ms["rounds_5v4_won"] += 1
                else:
                    rounds_4v5_total += 1
                    if won_round:
                        rounds_4v5_won += 1

            # Conteo de kills y muertes del equipo en la ronda
            my_kills = enemy_kills[enemy_kills["attacker_team"] == my_code]
            my_deaths = enemy_kills[enemy_kills["victim_team"] == my_code]

            team_kills_count += len(my_kills)
            team_deaths_count += len(my_deaths)
            ms["deaths"] += len(my_deaths)

            # Trades de la ronda
            trades_in_round = int(my_kills["is_trade"].sum())
            traded_deaths_in_round = int(my_deaths["was_traded"].sum())

            team_trades_count += trades_in_round
            team_traded_deaths_count += traded_deaths_in_round
            ms["trades"] += trades_in_round
            ms["traded_deaths"] += traded_deaths_in_round

            if trades_in_round > 0:
                rounds_with_trade_count += 1
                if won_round:
                    rounds_won_with_trade_count += 1
            else:
                rounds_no_trade_count += 1
                if won_round:
                    rounds_won_no_trade_count += 1

            # Reconstruir parejas exactas de refrag (quién vengó a quién)
            for i, k in my_kills[my_kills["is_trade"]].iterrows():
                k_tick = k["tick"]
                k_victim = k["victim_steamid"]
                # Buscar a qué compañero mató esta víctima en los últimos TRADE_WINDOW_S segundos
                prev_kills = enemy_kills[
                    (enemy_kills["tick"] <= k_tick)
                    & (enemy_kills["tick"] >= k_tick - trade_window_ticks)
                    & (enemy_kills["attacker_steamid"] == k_victim)
                    & (enemy_kills["victim_team"] == my_code)
                ]
                if not prev_kills.empty:
                    avenged_k = prev_kills.iloc[-1]
                    refragger_name = str(k.get("attacker_name", "Desconocido"))
                    avenged_name = str(avenged_k.get("victim_name", "Desconocido"))
                    delay_s = max(0.1, (k_tick - avenged_k["tick"]) / TICKRATE)
                    trade_delays.append(delay_s)

                    pair = (refragger_name, avenged_name)
                    trade_pairs_counts.setdefault(pair, []).append(delay_s)

    # Cálculos derivados
    round_winrate = round(100.0 * total_rounds_won / max(1, total_rounds), 1)
    match_winrate = round(100.0 * matches_won / max(1, matches_played), 1)

    t_winrate = round(100.0 * rounds_t_won / max(1, rounds_t_played), 1) if rounds_t_played else 0.0
    ct_winrate = round(100.0 * rounds_ct_won / max(1, rounds_ct_played), 1) if rounds_ct_played else 0.0

    trade_pct = round(100.0 * team_traded_deaths_count / max(1, team_deaths_count), 1)
    trade_kills_per_round = round(team_trades_count / max(1, total_rounds), 2)
    untraded_deaths = max(0, team_deaths_count - team_traded_deaths_count)

    trade_round_winrate = round(100.0 * rounds_won_with_trade_count / max(1, rounds_with_trade_count), 1) if rounds_with_trade_count else 0.0
    no_trade_round_winrate = round(100.0 * rounds_won_no_trade_count / max(1, rounds_no_trade_count), 1) if rounds_no_trade_count else 0.0
    trade_win_lift = round(trade_round_winrate - no_trade_round_winrate, 1)

    conv_5v4 = round(100.0 * rounds_5v4_won / max(1, rounds_5v4_total), 1) if rounds_5v4_total else 0.0
    rec_4v5 = round(100.0 * rounds_4v5_won / max(1, rounds_4v5_total), 1) if rounds_4v5_total else 0.0

    pistol_winrate = round(100.0 * pistols_won / max(1, pistols_played), 1) if pistols_played else 0.0
    followup_conv = round(100.0 * pistol_followups_won / max(1, pistol_followups_played), 1) if pistol_followups_played else 0.0

    avg_trade_delay = round(float(np.mean(trade_delays)), 2) if trade_delays else 0.0

    # Top parejas de tradeo
    pairs_list = []
    for (refragger, avenged), delays in trade_pairs_counts.items():
        pairs_list.append({
            "refragger": refragger,
            "avenged": avenged,
            "trades": len(delays),
            "avg_delay_s": round(float(np.mean(delays)), 2),
        })
    pairs_df = pd.DataFrame(pairs_list)
    if not pairs_df.empty:
        pairs_df = pairs_df.sort_values(["trades", "avg_delay_s"], ascending=[False, True]).reset_index(drop=True)

    # Tabla de Map Pool
    map_rows = []
    for cur_m, d_m in map_stats.items():
        m_r_total = d_m["rounds"]
        m_m_total = d_m["matches"]
        m_win = round(100.0 * d_m["matches_won"] / max(1, m_m_total), 1)
        r_win = round(100.0 * d_m["rounds_won"] / max(1, m_r_total), 1)
        t_win = round(100.0 * d_m["rounds_t_won"] / max(1, d_m["rounds_t"]), 1) if d_m["rounds_t"] else 0.0
        ct_win = round(100.0 * d_m["rounds_ct_won"] / max(1, d_m["rounds_ct"]), 1) if d_m["rounds_ct"] else 0.0
        t_rate = round(100.0 * d_m["traded_deaths"] / max(1, d_m["deaths"]), 1) if d_m["deaths"] else 0.0
        c_5v4 = round(100.0 * d_m["rounds_5v4_won"] / max(1, d_m["rounds_5v4"]), 1) if d_m["rounds_5v4"] else 0.0
        u_adr = round(d_m["util_damage"] / max(1, m_r_total), 1)

        map_rows.append({
            "map_raw": cur_m,
            "Mapa": pretty_map(cur_m),
            "Partidas": f"{d_m['matches_won']}/{m_m_total} ({m_win:.0f}%)",
            "Winrate Partidas %": m_win,
            "Winrate Rondas %": r_win,
            "Rondas T %": t_win,
            "Rondas CT %": ct_win,
            "Trade %": t_rate,
            "Conversión 5v4 %": c_5v4,
            "Util ADR": u_adr,
            "_played": m_m_total,
        })
    map_pool_df = pd.DataFrame(map_rows)
    if not map_pool_df.empty:
        map_pool_df = map_pool_df.sort_values(["_played", "Winrate Partidas %"], ascending=[False, False]).reset_index(drop=True)

    # -------------------------------------------------------------------------
    # Jugadores del equipo y Roles por lado (estilo demo individual)
    # -------------------------------------------------------------------------
    team_players_df = pd.DataFrame()
    player_archetypes = {}
    team_avg_scores = {}
    team_utility_df = pd.DataFrame()
    combined_pr = pd.DataFrame()

    if team_pr_list:
        combined_pr = pd.concat(team_pr_list, ignore_index=True)
        combined_clutches = pd.concat(team_clutches_list, ignore_index=True) if team_clutches_list else None
        combined_shots = pd.concat(team_shots_list, ignore_index=True) if team_shots_list else None

        team_players_df = stats.aggregate(combined_pr, cl=combined_clutches, acc=combined_shots)
        if not team_players_df.empty:
            for sid in team_players_df["steamid"].unique():
                p_pr = combined_pr[combined_pr["steamid"] == sid]
                p_cl = combined_clutches[combined_clutches["steamid"] == sid] if combined_clutches is not None and not combined_clutches.empty else None
                p_sh = combined_shots[combined_shots["steamid"] == sid] if combined_shots is not None and not combined_shots.empty else None
                arch = archetypes.compute_player_side_archetypes_from_pr(p_pr, p_cl, p_sh)
                if arch:
                    player_archetypes[sid] = arch

            team_avg_scores = archetypes.compute_match_average_scores(team_players_df)

            # Construir tabla de utilidad por jugador
            util_rows = []
            for _, prow in team_players_df.iterrows():
                sid = prow["steamid"]
                rounds_p = max(1, int(prow.get("rounds", 1)))
                u_dmg = float(prow.get("utility_damage", 0.0))
                gr_thrown = int(prow.get("grenades_thrown", 0))
                en_flashed = int(prow.get("enemies_flashed", 0))
                p_sub = combined_pr[combined_pr["steamid"] == sid]
                bl_time = float(p_sub["blind_time"].sum()) if "blind_time" in p_sub.columns else 0.0
                tm_flashed = player_team_blinds.get(sid, 0)

                util_rows.append({
                    "steamid": sid,
                    "Jugador": prow.get("name", sid),
                    "Rondas": rounds_p,
                    "Util ADR": round(u_dmg / rounds_p, 1),
                    "Daño Utilidad": int(round(u_dmg)),
                    "Granadas": gr_thrown,
                    "Enemigos cegados": en_flashed,
                    "Tiempo ceguera (s)": round(bl_time, 1),
                    "Team Flashes": tm_flashed,
                    "Flashes / Ronda": round(en_flashed / rounds_p, 2),
                })
            team_utility_df = pd.DataFrame(util_rows).sort_values("Util ADR", ascending=False).reset_index(drop=True)

    return {
        "team_name": team_display,
        "included_variants": list(target_team_set),
        "matches_played": matches_played,
        "matches_won": matches_won,
        "matches_lost": matches_lost,
        "matches_tied": matches_tied,
        "match_winrate": match_winrate,
        "total_rounds": total_rounds,
        "total_rounds_won": total_rounds_won,
        "round_winrate": round_winrate,
        # Lados
        "rounds_t_played": rounds_t_played,
        "rounds_t_won": rounds_t_won,
        "t_winrate": t_winrate,
        "rounds_ct_played": rounds_ct_played,
        "rounds_ct_won": rounds_ct_won,
        "ct_winrate": ct_winrate,
        # Trades
        "team_kills": team_kills_count,
        "team_deaths": team_deaths_count,
        "team_trades": team_trades_count,
        "trade_kills_per_round": trade_kills_per_round,
        "traded_deaths": team_traded_deaths_count,
        "untraded_deaths": untraded_deaths,
        "trade_pct": trade_pct,
        "trade_round_winrate": trade_round_winrate,
        "no_trade_round_winrate": no_trade_round_winrate,
        "trade_win_lift": trade_win_lift,
        "rounds_with_trade": rounds_with_trade_count,
        "rounds_no_trade": rounds_no_trade_count,
        "avg_trade_delay": avg_trade_delay,
        "trade_pairs": pairs_df,
        # Ventaja numérica
        "rounds_5v4_total": rounds_5v4_total,
        "rounds_5v4_won": rounds_5v4_won,
        "conversion_5v4": conv_5v4,
        "rounds_4v5_total": rounds_4v5_total,
        "rounds_4v5_won": rounds_4v5_won,
        "recovery_4v5": rec_4v5,
        # Pistolas
        "pistols_played": pistols_played,
        "pistols_won": pistols_won,
        "pistol_winrate": pistol_winrate,
        "pistol_followups_played": pistol_followups_played,
        "pistol_followups_won": pistol_followups_won,
        "followup_conv": followup_conv,
        # Utilidad
        "util_damage_total": util_damage_total,
        "util_adr": round(util_damage_total / max(1, total_rounds), 1),
        "flashes_enemies": flashes_enemies_total,
        "flashes_teammates": flashes_teammates_total,
        # Map Pool
        "map_pool": map_pool_df,
        # Jugadores y Roles por Side
        "team_players_df": team_players_df,
        "player_archetypes": player_archetypes,
        "team_avg_scores": team_avg_scores,
        "team_utility_df": team_utility_df,
        "combined_pr": combined_pr,
    }
