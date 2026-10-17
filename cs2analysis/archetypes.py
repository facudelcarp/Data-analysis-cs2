"""Cálculo de arquetipos y perfiles tácticos de jugadores para CS2.

Evalúa a cada jugador en 6 dimensiones normalizadas (0-100) contra estándares
competitivos y clasifica su rol principal (Entry, AWPer, Star Rifler, Support, Lurker, Anchor).
"""
from __future__ import annotations

import numpy as np
import pandas as pd

RADAR_AXES = [
    "Apertura",
    "Letalidad",
    "Utilidad",
    "Francotirador",
    "Supervivencia",
    "Precisión",
]


def _clamp(val: float, low: float = 0.0, high: float = 100.0) -> float:
    return float(np.clip(val, low, high))


def calculate_player_scores(row: pd.Series) -> dict[str, float]:
    """Calcula los puntajes normalizados (0 a 100) en las 6 dimensiones para un jugador."""
    rounds = max(1.0, float(row.get("rounds", 1)))
    kills = max(1.0, float(row.get("kills", 1)))

    # 1. Apertura (Entry): frecuencia de duelos de apertura y tasa de éxito
    opening_att = float(row.get("opening_attempts", 0))
    att_per_round = opening_att / rounds
    opening_pct = float(row.get("opening_success_pct", 0.0))
    # Benchmark: 0.25 att/ronda = muy agresivo; winrate 50% = estándar
    entry_score = (att_per_round / 0.25) * 60.0 + (opening_pct / 100.0) * 40.0

    # 2. Letalidad (Fragging / ADR / KPR)
    kpr = float(row.get("kpr", row.get("kills", 0) / rounds))
    adr = float(row.get("adr", 0.0))
    # Benchmark: 0.90 KPR y 90 ADR = 100
    fragging_score = (kpr / 0.90) * 50.0 + (adr / 90.0) * 50.0

    # 3. Utilidad (Utility & Trade)
    util_adr = float(row.get("utility_adr", 0.0))
    flashes_per_round = float(row.get("enemies_flashed", 0)) / rounds
    trade_kills_per_round = float(row.get("trade_kills", 0)) / rounds
    # Benchmark: 7.0 util ADR, 0.70 enemigos cegados/ronda, 0.16 trade kills/ronda
    util_score = (
        (util_adr / 7.0) * 40.0
        + (flashes_per_round / 0.70) * 30.0
        + (trade_kills_per_round / 0.16) * 30.0
    )

    # 4. Francotirador (Sniper / AWP)
    awp_kills = float(row.get("awp_kills", 0))
    awp_ratio = awp_kills / kills
    # Benchmark: 40%+ de kills con AWP = francotirador principal
    sniper_score = (awp_ratio / 0.40) * 100.0

    # 5. Supervivencia & Clutch (KAST / Clutches / Vivir rondas)
    kast = float(row.get("kast_pct", 65.0))
    survived = float(row.get("survived", 0))
    surv_pct = (survived / rounds) * 100.0
    clutches_won = float(row.get("clutches_won", 0))
    # Benchmark: KAST 75%+, supervivencia 38%+, clutches
    clutch_score = (
        ((kast - 50.0) / 28.0) * 45.0
        + (surv_pct / 38.0) * 40.0
        + min(15.0, clutches_won * 7.5)
    )

    # 6. Precisión (Headshot & Puntería)
    hs_pct = float(row.get("hs_pct", 0.0))
    accuracy = float(row.get("accuracy_pct", 20.0))
    # Benchmark: 62% HS y 25% precisión
    precision_score = (hs_pct / 62.0) * 70.0 + (accuracy / 25.0) * 30.0

    return {
        "Apertura": round(_clamp(entry_score), 1),
        "Letalidad": round(_clamp(fragging_score), 1),
        "Utilidad": round(_clamp(util_score), 1),
        "Francotirador": round(_clamp(sniper_score), 1),
        "Supervivencia": round(_clamp(clutch_score), 1),
        "Precisión": round(_clamp(precision_score), 1),
    }


def classify_archetype(scores: dict[str, float], row: pd.Series) -> tuple[str, str, str]:
    """Clasifica el rol dominante del jugador a partir de sus estadísticas.

    Devuelve (título, icono_emoji, descripción).
    """
    awp_kills = int(row.get("awp_kills", 0))
    rounds = max(1, int(row.get("rounds", 1)))
    clutches_won = int(row.get("clutches_won", 0))
    rating2 = float(row.get("rating2", 1.0))
    opening_att = int(row.get("opening_attempts", 0))
    att_rate = opening_att / rounds

    # 1. AWPer / Francotirador
    if scores["Francotirador"] >= 55 and awp_kills >= 4:
        return (
            "AWPer / Francotirador",
            "🎯",
            "Especialista en control de ángulos a larga distancia y primer impacto con rifle de precisión.",
        )

    # 2. Entry Fragger / Punta de Lanza
    if scores["Apertura"] >= 70 or (att_rate >= 0.22 and scores["Apertura"] >= 52):
        return (
            "Entry Fragger / Punta de Lanza",
            "⚡",
            "Primer contacto agresivo; genera espacio y abre rondas tomando los duelos iniciales.",
        )

    # 3. Star Rifler / Playmaker
    if scores["Letalidad"] >= 72 and rating2 >= 1.15:
        return (
            "Star Rifler / Playmaker",
            "💥",
            "Pilar ofensivo del equipo; alto volumen de daño, multi-kills e impacto constante con rifles principales.",
        )

    # 4. Support / Especialista Táctico
    if scores["Utilidad"] >= 62:
        return (
            "Support / Especialista Táctico",
            "🛡️",
            "Facilitador del equipo; crea ventajas con utilidades eficaces, flashes de apoyo y refrags inmediatos.",
        )

    # 5. Lurker / Clutcher
    if scores["Supervivencia"] >= 62 and (clutches_won >= 1 or att_rate <= 0.12):
        return (
            "Lurker / Clutcher",
            "🧠",
            "Juega tiempos tardíos y rotaciones; define rondas en situaciones límite de 1vX y conserva ventaja.",
        )

    # 6. Anchor / Defensor de Sitio
    if scores["Supervivencia"] >= 52 and att_rate <= 0.15:
        return (
            "Anchor / Defensor de Sitio",
            "🏰",
            "Guardián de bombsite; aguanta las ejecuciones rivales, compra tiempo y frena avances.",
        )

    # 7. Rifler Versátil (Fallback equilibrado)
    return (
        "Rifler Versátil",
        "⚔️",
        "Perfil equilibrado capaz de alternar entre apoyo y primer contacto según la necesidad de la ronda.",
    )


def compute_match_archetypes(ps: pd.DataFrame) -> pd.DataFrame:
    """Calcula arquetipos y puntajes de radar para todos los jugadores del match."""
    if ps.empty:
        return pd.DataFrame()

    records = []
    for _, row in ps.iterrows():
        sc = calculate_player_scores(row)
        title, icon, desc = classify_archetype(sc, row)
        rec = {
            "steamid": row["steamid"],
            "name": row.get("name", ""),
            "team": row.get("team", ""),
            "archetype": title,
            "archetype_icon": icon,
            "archetype_desc": desc,
            **{f"score_{k.lower()}": v for k, v in sc.items()},
        }
        records.append(rec)

    return pd.DataFrame(records)


def compute_match_average_scores(ps: pd.DataFrame) -> dict[str, float]:
    """Calcula el promedio del partido en cada eje de radar para usar como referencia."""
    if ps.empty:
        return {axis: 50.0 for axis in RADAR_AXES}

    all_scores = [calculate_player_scores(row) for _, row in ps.iterrows()]
    avg = {}
    for axis in RADAR_AXES:
        avg[axis] = round(float(np.mean([s[axis] for s in all_scores])), 1)
    return avg
