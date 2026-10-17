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

        # Kills ocurridas antes o en el momento del plantado
        pre_kills = kills[(kills["round"] == rnd) & (kills["time_in_round"] <= t_plant)] if not kills.empty else pd.DataFrame()
        ct_dead_at_plant = (pre_kills["victim_side"] == "CT").sum() if not pre_kills.empty else 0
        t_dead_at_plant = (pre_kills["victim_side"] == "T").sum() if not pre_kills.empty else 0

        ct_alive = max(0, 5 - ct_dead_at_plant)
        t_alive = max(0, 5 - t_dead_at_plant)
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
