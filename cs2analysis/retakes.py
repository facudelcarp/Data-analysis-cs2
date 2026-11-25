"""Análisis de situaciones de post-plant y retakes (recuperación de sitio por CTs)."""
from __future__ import annotations

import pandas as pd
from .parser import DemoData


def analyze_retakes(d: DemoData) -> pd.DataFrame:
    """Para cada ronda donde se plantó la bomba, analiza la situación al momento del plantado:
    - Vivos de cada bando (ej. 3v3, 2v4, 1v1).
    - Si el retake fue exitoso (CT defusó o eliminó a todos los T antes de la detonación).
    - Tiempo transcurrido desde el plantado hasta el defuse o última kill.
    """
    bomb = d.bomb
    if bomb.empty:
        return pd.DataFrame()

    planted = bomb[bomb["event_code"] == "bomb_planted"].copy()
    if planted.empty:
        return pd.DataFrame()

    kills = d.kills[d.kills["is_enemy_kill"]] if not d.kills.empty else pd.DataFrame()
    rounds = d.rounds.set_index("round")
    # Quién jugó cada ronda de cada lado (desconexiones, wingman): no se asume 5v5
    roster = (d.economy.groupby(["round", "side"])["steamid"].apply(lambda s: set(s.astype(str)))
              if not d.economy.empty else pd.Series(dtype=object))
    
    records = []
    for _, plant in planted.iterrows():
        rnd = plant["round"]
        t_plant = plant["time_in_round"]
        site = plant.get("site_letter", "") or "Desconocido"

        if rnd not in rounds.index:
            continue
        r_info = rounds.loc[rnd]
        ct_team = r_info["ct_team"]
        t_team = r_info["t_team"]
        winner_side = r_info["winner_side"]

        # Solo lo que pasó con la ronda en juego: las kills de salida (después del final) no cuentan
        kr = kills[(kills["round"] == rnd) & (kills["tick"] <= r_info["end_tick"])] if not kills.empty else kills
        pre_kills = kr[kr["time_in_round"] <= t_plant] if not kr.empty else kr

        def alive_at_plant(side: str) -> int:
            players = roster.get((rnd, side), set())
            dead = set(pre_kills.loc[pre_kills["victim_side"] == side, "victim_steamid"].astype(str)) \
                if not pre_kills.empty else set()
            if players:
                return len(players - dead)
            return max(0, 5 - len(dead))  # sin economía: único caso en que se asume 5

        ct_alive = alive_at_plant("CT")
        t_alive = alive_at_plant("T")
        situation = f"{ct_alive}v{t_alive}"

        # Éxito del retake: ganó el lado CT
        retake_won = (winner_side == "CT")

        # Tiempo del desenlace tras el plantado
        defused = bomb[(bomb["round"] == rnd) & (bomb["event_code"] == "bomb_defused")]
        exploded = bomb[(bomb["round"] == rnd) & (bomb["event_code"] == "bomb_exploded")]
        
        outcome_time = None
        if not defused.empty:
            outcome_time = defused.iloc[0]["time_in_round"] - t_plant
            outcome_type = "Defuse exitoso"
        elif not exploded.empty:
            outcome_time = exploded.iloc[0]["time_in_round"] - t_plant
            outcome_type = "Detonación"
        else:
            outcome_type = "Eliminación"
            post = kr[kr["time_in_round"] > t_plant] if not kr.empty else kr
            if not post.empty:
                outcome_time = post["time_in_round"].max() - t_plant

        records.append({
            "round": rnd,
            "site": site,
            "plant_time": round(float(t_plant), 1),
            "situation": situation,
            "ct_alive": ct_alive,
            "t_alive": t_alive,
            "ct_team": ct_team,
            "t_team": t_team,
            "retake_won": retake_won,
            "outcome": outcome_type,
            "outcome_seconds": round(float(outcome_time), 1) if outcome_time is not None else None
        })

    return pd.DataFrame(records)
