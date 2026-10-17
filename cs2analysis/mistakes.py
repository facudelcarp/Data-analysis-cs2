"""Análisis de errores críticos y momentos clave (lowlights / throws / fallas de tradeo)."""
from __future__ import annotations

import pandas as pd
from .parser import DemoData
from .stats import round_timeline


def detect_mistakes(d: DemoData) -> pd.DataFrame:
    """Detecta jugadas críticas y errores que suelen costar partidos:
    - anti_eco_throw: perder contra un rival en eco/semi-eco teniendo ventaja de compra.
    - man_advantage_throw: perder una ronda habiendo alcanzado ventaja numérica de +2 o más (ej: 5v3, 4v2, 3v1).
    - untraded_deaths: muertes sin tradeo fuera de duelos de apertura.
    - repeat_opener_deaths: jugadores que mueren primero 3+ veces en la partida.
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
    if not k.empty:
        for rnd, kr in k.groupby("round"):
            r_info = rt[rt["round"] == rnd]
            if r_info.empty:
                continue
            winner = r_info.iloc[0]["winner_team"]
            
            alive = {"A": 5, "B": 5}
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

                # Revisar ventaja para B
                adv_b = alive["B"] - alive["A"]
                if adv_b > max_advantage["B"]:
                    max_advantage["B"] = adv_b
                    advantage_state["B"] = f"{alive['B']}v{alive['A']}"
            
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
                    "detail": (f"{teams.get(loser, loser)} llegó a estar en situación {state_str} favorable, "
                               f"pero {teams.get(winner, winner)} remontó y se llevó la ronda.")
                })

    # 3. Muertes aisladas sin tradeo repetidas por jugador
    if not k.empty:
        untraded = k[(~k["was_traded"]) & (~k["is_opening"])]
        if len(untraded):
            untraded_counts = untraded.groupby(["victim_steamid", "victim_name", "victim_team"]).size()
            for (sid, name, team), count in untraded_counts.items():
                if count >= 4:
                    mistakes.append({
                        "round": "-",
                        "type": "isolated_deaths",
                        "severity": "MEDIA",
                        "team": team,
                        "team_name": teams.get(team, team),
                        "title": f"Bajas aisladas: {name}",
                        "detail": f"{name} murió {count} veces a lo largo del partido sin que ningún compañero pudiera tradearlo en < 5 s."
                    })

    # 4. Primeras muertes consecutivas / recurrentes en aperturas
    if not k.empty:
        openings = k[k["is_opening"]]
        if len(openings):
            first_deaths = openings.groupby(["victim_steamid", "victim_name", "victim_team"]).size()
            for (sid, name, team), count in first_deaths.items():
                if count >= 4:
                    mistakes.append({
                        "round": "-",
                        "type": "opening_deaths",
                        "severity": "MEDIA",
                        "team": team,
                        "team_name": teams.get(team, team),
                        "title": f"Primer caído recurrente: {name}",
                        "detail": f"{name} murió primero en {count} rondas distintas dejando a su equipo en desventaja 4v5 temprana."
                    })

    return pd.DataFrame(mistakes)
