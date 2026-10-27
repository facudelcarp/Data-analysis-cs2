"""Análisis de errores críticos y momentos clave (lowlights / throws / fallas de tradeo)."""
from __future__ import annotations

import pandas as pd
from .parser import DemoData
from .stats import round_timeline


def _round_list(df: pd.DataFrame) -> str:
    """Evidencia: en qué rondas pasó ("3, 7, 12")."""
    return ", ".join(str(int(r)) for r in sorted(df["round"].unique()))


def detect_mistakes(d: DemoData) -> pd.DataFrame:
    """Detecta jugadas críticas y errores que suelen costar partidos:
    - anti_eco_throw: perder contra un rival en eco/semi-eco teniendo ventaja de compra.
    - man_advantage_throw: perder una ronda habiendo alcanzado ventaja numérica de +2 o más (ej: 5v3, 4v2, 3v1).
    - isolated_deaths: jugadores que mueren sin tradeo bastante más seguido que el resto de la partida.
    - opening_deaths: jugadores que mueren primero bastante más que el promedio y pierden sus aperturas.

    Cada error trae en "round" las rondas en las que pasó, para poder revisarlas.
    """
    rt = round_timeline(d)
    k = d.kills[d.kills["is_enemy_kill"]].copy() if not d.kills.empty else pd.DataFrame()
    teams = {"A": d.meta["team_a"], "B": d.meta["team_b"]}
    
    mistakes = []

    # 1. Pérdida contra Eco / Semi-eco teniendo Full buy o Force
    for _, r in rt.iterrows():
        winner = r["winner_team"]
        loser = "B" if winner == "A" else "A"
        winner_buy = r[f"buy_{winner.lower()}"]
        loser_buy = r[f"buy_{loser.lower()}"]
        winner_equip = r[f"equip_{winner.lower()}"]
        loser_equip = r[f"equip_{loser.lower()}"]
        
        # El perdedor tenía compra fuerte (Full buy o Force >= 15k) y el ganador estaba en Eco / Semi-eco (< 10k)
        if loser_equip >= 14_000 and winner_equip <= 9_000:
            mistakes.append({
                "round": r["round"],
                "type": "anti_eco_loss",
                "severity": "ALTA",
                "team": loser,
                "team_name": teams.get(loser, loser),
                "title": f"Ronda perdida contra {winner_buy}",
                "detail": (f"{teams.get(loser, loser)} jugó con ${loser_equip:,.0f} ({loser_buy}) contra "
                           f"${winner_equip:,.0f} ({winner_buy}) de {teams.get(winner, winner)} y perdió la ronda.")
            })

    # 2. Pérdidas con Ventaja Numérica (Man Advantage Throws: 5v3, 4v2, 3v1, etc.)
    # Simulamos el estado vivo tick a tick en cada ronda
    roster = d.economy.groupby(["round", "team"]).size() if not d.economy.empty else pd.Series(dtype=int)
    if not k.empty:
        for rnd, kr in k.groupby("round"):
            r_info = rt[rt["round"] == rnd]
            if r_info.empty:
                continue
            winner = r_info.iloc[0]["winner_team"]
            # Solo lo que pasó con la ronda en juego: las kills de salida (después del final) no cuentan
            kr = kr[kr["tick"] <= r_info.iloc[0]["end_tick"]]

            # Vivos al empezar según quién jugó la ronda (desconexiones, wingman), no 5v5 fijo
            alive = {t: int(roster.get((rnd, t), 5)) for t in ("A", "B")}
            reached_at = {"A": None, "B": None}
            max_advantage = {"A": 0, "B": 0}  # máxima ventaja de vivos (vivos_propio - vivos_rival)
            advantage_state = {"A": "", "B": ""}
            
            for _, kill in kr.sort_values("tick").iterrows():
                vic_team = kill["victim_team"]
                if vic_team in alive:
                    alive[vic_team] = max(0, alive[vic_team] - 1)
                
                # Revisar ventaja para A
                adv_a = alive["A"] - alive["B"]
                if adv_a > max_advantage["A"]:
                    max_advantage["A"] = adv_a
                    advantage_state["A"] = f"{alive['A']}v{alive['B']}"
                    reached_at["A"] = kill.get("time_in_round")

                # Revisar ventaja para B
                adv_b = alive["B"] - alive["A"]
                if adv_b > max_advantage["B"]:
                    max_advantage["B"] = adv_b
                    advantage_state["B"] = f"{alive['B']}v{alive['A']}"
                    reached_at["B"] = kill.get("time_in_round")
            
            # Si el equipo perdedor tuvo ventaja de +2 o más vivos durante la ronda
            loser = "B" if winner == "A" else "A"
            if max_advantage[loser] >= 2:
                state_str = advantage_state[loser]
                mistakes.append({
                    "round": rnd,
                    "type": "advantage_throw",
                    "severity": "CRÍTICA" if max_advantage[loser] >= 3 else "ALTA",
                    "team": loser,
                    "team_name": teams.get(loser, loser),
                    "title": f"Ventaja {state_str} desperdiciada",
                    "detail": (f"{teams.get(loser, loser)} llegó a estar en situación {state_str} favorable"
                               + (f" (segundo {reached_at[loser]:.0f} de la ronda)" if reached_at[loser] is not None
                                  and pd.notna(reached_at[loser]) else "")
                               + f", pero {teams.get(winner, winner)} remontó y se llevó la ronda.")
                })

    # 3 y 4: comparación contra el resto de la partida. En CS la mayoría de las muertes no se tradean y en una
    # partida larga cualquiera muere primero varias veces: un umbral fijo marcaría a todos (y no diría nada).
    if not k.empty:
        later = k[~k["is_opening"]]
        per = later.groupby(["victim_steamid", "victim_name", "victim_team"]).agg(
            deaths=("round", "size"), untraded=("was_traded", lambda s: int((~s.astype(bool)).sum())))
        if len(per):
            per["share"] = per["untraded"] / per["deaths"]
            median_share = float(per["share"].median())
            for (sid, name, team), row in per.iterrows():
                if row["untraded"] >= 6 and row["share"] >= median_share + 0.15:
                    rounds = _round_list(later[(later["victim_steamid"] == sid) & ~later["was_traded"].astype(bool)])
                    mistakes.append({
                        "round": rounds,
                        "type": "isolated_deaths",
                        "severity": "MEDIA",
                        "team": team,
                        "team_name": teams.get(team, team),
                        "title": f"Bajas aisladas: {name}",
                        "detail": (f"{name} no fue tradeado en el {100 * row['share']:.0f}% de sus muertes "
                                   f"({int(row['untraded'])} de {int(row['deaths'])}), contra el {100 * median_share:.0f}% "
                                   f"típico de esta partida: suele morir lejos de sus compañeros (rondas {rounds}).")
                    })

        openings = k[k["is_opening"]]
        if len(openings):
            n_players = max(d.players["steamid"].nunique(), 1)
            avg_first = len(openings) / n_players
            first_deaths = openings.groupby(["victim_steamid", "victim_name", "victim_team"]).size()
            first_kills = openings.groupby("attacker_steamid").size()
            for (sid, name, team), count in first_deaths.items():
                won = int(first_kills.get(sid, 0))
                if count >= max(4, 1.5 * avg_first) and won <= 0.7 * count:
                    rounds = _round_list(openings[openings["victim_steamid"] == sid])
                    mistakes.append({
                        "round": rounds,
                        "type": "opening_deaths",
                        "severity": "MEDIA",
                        "team": team,
                        "team_name": teams.get(team, team),
                        "title": f"Primer caído recurrente: {name}",
                        "detail": (f"{name} murió primero en {count} rondas ({rounds}) y ganó {won} apertura{'' if won == 1 else 's'}, "
                                   f"cuando lo típico en esta partida es morir primero ~{avg_first:.1f} veces: su "
                                   f"equipo arrancó 4v5 seguido.")
                    })

    return pd.DataFrame(mistakes)
