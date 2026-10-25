"""Cálculo de arquetipos y perfiles tácticos por lado (T vs CT) para CS2.

En Counter-Strike competitivo los roles dependen intrínsecamente del bando:
- En Terroristas (T): Entry Fragger, Refragger / 2nd In, Lurker, Support Táctico, T-AWPer.
- En Counter-Terroristas (CT): Anchor (ancla de sitio), Rotador / Playmaker, Agresor / Info-Taker, Soporte / Retaker, CT-AWPer.

Este módulo clasifica el rol del jugador en cada lado y calcula su identidad dual completa
(ej: 'Entry Fragger (T) · Anchor (CT)').
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from .parser import DemoData
from . import stats

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
    """Calcula los puntajes normalizados (0 a 100) en las 6 dimensiones para una fila de estadísticas."""
    rounds = max(1.0, float(row.get("rounds", 1)))
    kills = max(1.0, float(row.get("kills", 1)))

    # 1. Apertura: frecuencia de duelos de apertura y tasa de éxito
    opening_att = float(row.get("opening_attempts", 0))
    att_per_round = opening_att / rounds
    opening_pct = float(row.get("opening_success_pct", 0.0))
    entry_score = (att_per_round / 0.25) * 60.0 + (opening_pct / 100.0) * 40.0

    # 2. Letalidad: KPR y ADR
    kpr = float(row.get("kpr", row.get("kills", 0) / rounds))
    adr = float(row.get("adr", 0.0))
    fragging_score = (kpr / 0.90) * 50.0 + (adr / 90.0) * 50.0

    # 3. Utilidad: ADR de granadas, flashes y trade kills
    util_adr = float(row.get("utility_adr", 0.0))
    flashes_per_round = float(row.get("enemies_flashed", 0)) / rounds
    trade_kills_per_round = float(row.get("trade_kills", 0)) / rounds
    util_score = (
        (util_adr / 7.0) * 40.0
        + (flashes_per_round / 0.70) * 30.0
        + (trade_kills_per_round / 0.16) * 30.0
    )

    # 4. Francotirador: % de kills con AWP
    awp_kills = float(row.get("awp_kills", 0))
    awp_ratio = awp_kills / kills
    sniper_score = (awp_ratio / 0.40) * 100.0

    # 5. Supervivencia & Clutch: KAST, vivir rondas y 1vX
    kast = float(row.get("kast_pct", 65.0))
    survived = float(row.get("survived", 0))
    surv_pct = (survived / rounds) * 100.0
    clutches_won = float(row.get("clutches_won", 0))
    clutch_score = (
        ((kast - 50.0) / 28.0) * 45.0
        + (surv_pct / 38.0) * 40.0
        + min(15.0, clutches_won * 7.5)
    )

    # 6. Precisión: Headshot y precisión de tiro
    hs_pct = float(row.get("hs_pct", 0.0))
    accuracy = float(row.get("accuracy_pct", 20.0))
    precision_score = (hs_pct / 62.0) * 70.0 + (accuracy / 25.0) * 30.0

    return {
        "Apertura": round(_clamp(entry_score), 1),
        "Letalidad": round(_clamp(fragging_score), 1),
        "Utilidad": round(_clamp(util_score), 1),
        "Francotirador": round(_clamp(sniper_score), 1),
        "Supervivencia": round(_clamp(clutch_score), 1),
        "Precisión": round(_clamp(precision_score), 1),
    }


def classify_t_role(scores: dict[str, float], row: pd.Series) -> tuple[str, str, str]:
    """Clasifica el rol específico del jugador atacando como Terrorista (T)."""
    awp_kills = int(row.get("awp_kills", 0))
    rounds = max(1, int(row.get("rounds", 1)))
    opening_att = int(row.get("opening_attempts", 0))
    att_rate = opening_att / rounds
    trade_kills = int(row.get("trade_kills", 0))
    clutches_won = int(row.get("clutches_won", 0))

    if scores["Francotirador"] >= 50 and awp_kills >= 3:
        return (
            "T-AWPer / Francotirador",
            "🎯",
            "Busca picks iniciales a distancia, cubre flancos y sostiene ángulos largos al tomar bombsite.",
        )

    if scores["Apertura"] >= 65 or (att_rate >= 0.22 and scores["Apertura"] >= 50):
        return (
            "Entry Fragger",
            "⚡",
            "Punta de lanza; primer contacto al ejecutar el bombsite, toma los duelos de apertura y genera espacio.",
        )

    if (trade_kills / rounds >= 0.14) or (scores["Letalidad"] >= 65 and att_rate >= 0.12):
        return (
            "Refragger / 2nd In",
            "💥",
            "Segunda entrada; avanza pegado al entry para conseguir el refrag inmediato y asegurar el bombsite.",
        )

    if scores["Supervivencia"] >= 60 and (clutches_won >= 1 or att_rate <= 0.13):
        return (
            "Lurker / Acechador",
            "🧠",
            "Corta rotaciones de CT, presiona el mapa opuesto y define rondas en tiempos tardíos (1vX).",
        )

    if scores["Utilidad"] >= 58:
        return (
            "Support Táctico",
            "🛡️",
            "Tira los humos de execute, flashes de entrada y maximiza el daño de utilidades para el equipo.",
        )

    return (
        "Rifler Ofensivo",
        "⚔️",
        "Acompaña las ejecuciones y toma duelos directos según la necesidad de la ronda atacante.",
    )


def classify_ct_role(scores: dict[str, float], row: pd.Series) -> tuple[str, str, str]:
    """Clasifica el rol específico del jugador defendiendo como Counter-Terrorista (CT)."""
    awp_kills = int(row.get("awp_kills", 0))
    rounds = max(1, int(row.get("rounds", 1)))
    opening_att = int(row.get("opening_attempts", 0))
    att_rate = opening_att / rounds
    survived = int(row.get("survived", 0))
    surv_rate = survived / rounds

    if scores["Francotirador"] >= 50 and awp_kills >= 3:
        return (
            "CT-AWPer / Francotirador",
            "🎯",
            "Controla las líneas de visión defensivas principales (Medio, Rampa, Larga) y frena avances.",
        )

    # Agresor de CT: empuja adelante al inicio de la ronda para buscar duelos/información
    if att_rate >= 0.22 and scores["Apertura"] >= 55:
        return (
            "Agresor / Info-Taker",
            "⚡",
            "Empuja al inicio de ronda (Banana, Monster, Larga) para ganar información temprana o una primera baja clave.",
        )

    # Anchor de sitio: se queda aguantando el bombsite, no empuja, aguanta ejecuciones rivales
    if (att_rate <= 0.16 and scores["Supervivencia"] >= 50) or (surv_rate >= 0.38 and att_rate <= 0.18):
        return (
            "Anchor (Ancla de Sitio)",
            "🏰",
            "Guardián de bombsite cerrado; sostiene el site en solitario ante la ejecución rival y compra tiempo.",
        )

    # Rotador / Playmaker CT: juega en posiciones dinámicas (Conector/Ventana/Short), participa mucho
    if scores["Letalidad"] >= 65 or int(row.get("trade_kills", 0)) / rounds >= 0.13:
        return (
            "Rotador / Playmaker",
            "🔄",
            "Juega posiciones centrales o móviles; apoya al sitio bajo ataque de inmediato y busca el contraataque.",
        )

    if scores["Utilidad"] >= 58:
        return (
            "Soporte Defensivo",
            "🛡️",
            "Frena rushes con utilidades tempranas y prepara granadas para el retake conjunto del sitio.",
        )

    return (
        "Defensor Versátil",
        "⚔️",
        "Equilibrio entre aguante pasivo y rotación rápida según la llamada del equipo defensivo.",
    )


def classify_archetype(scores: dict[str, float], row: pd.Series, side: str | None = None) -> tuple[str, str, str]:
    """Clasifica el rol del jugador. Si side='T' usa roles de T, si side='CT' usa roles de CT."""
    if side == "T":
        return classify_t_role(scores, row)
    if side == "CT":
        return classify_ct_role(scores, row)

    # Rol global / integrado
    awp_kills = int(row.get("awp_kills", 0))
    rounds = max(1, int(row.get("rounds", 1)))
    att_rate = int(row.get("opening_attempts", 0)) / rounds

    if scores["Francotirador"] >= 55 and awp_kills >= 4:
        return ("AWPer / Francotirador", "🎯", "Especialista en control de ángulos a larga distancia con rifle de precisión.")
    if scores["Apertura"] >= 70 or (att_rate >= 0.22 and scores["Apertura"] >= 52):
        return ("Entry Fragger / Agresor", "⚡", "Jugador de primer contacto; abre rondas y genera espacio con duelos tempranos.")
    if scores["Letalidad"] >= 72 and float(row.get("rating2", 1.0)) >= 1.15:
        return ("Star Rifler / Playmaker", "💥", "Pilar ofensivo del equipo; alto volumen de daño, multi-kills e impacto constante.")
    if scores["Utilidad"] >= 62:
        return ("Support / Especialista Táctico", "🛡️", "Facilitador; crea ventajas con utilidades eficaces, flashes de apoyo y refrags.")
    if scores["Supervivencia"] >= 62 and (int(row.get("clutches_won", 0)) >= 1 or att_rate <= 0.12):
        return ("Lurker / Clutcher", "🧠", "Juega tiempos tardíos y rotaciones; define rondas en situaciones límite de 1vX.")
    if scores["Supervivencia"] >= 52 and att_rate <= 0.15:
        return ("Anchor / Defensor de Sitio", "🏰", "Guardián de bombsite; aguanta las ejecuciones rivales, compra tiempo y frena avances.")
    return ("Rifler Versátil", "⚔️", "Perfil equilibrado capaz de alternar entre apoyo y primer contacto según la ronda.")


def compute_player_side_archetypes_from_pr(
    pr_player: pd.DataFrame,
    clutches_df: pd.DataFrame | None = None,
    shots_df: pd.DataFrame | None = None,
) -> dict:
    """Devuelve el desglose completo del jugador: rol en T, rol en CT, rol global e identidad dual a partir de sus player_rounds."""
    if pr_player.empty:
        return {}

    # Stats globales
    ps_all = stats.aggregate(pr_player, clutches=clutches_df, acc=shots_df)
    row_all = ps_all.iloc[0] if not ps_all.empty else pr_player.iloc[0]
    scores_all = calculate_player_scores(row_all)
    all_role, all_icon, all_desc = classify_archetype(scores_all, row_all)

    # Stats T side
    pr_t = pr_player[pr_player["side"] == "T"]
    if not pr_t.empty:
        ps_t = stats.aggregate(pr_t, clutches=clutches_df, acc=shots_df)
        row_t = ps_t.iloc[0] if not ps_t.empty else pr_t.iloc[0]
        scores_t = calculate_player_scores(row_t)
        t_role, t_icon, t_desc = classify_t_role(scores_t, row_t)
    else:
        row_t = row_all
        scores_t = scores_all
        t_role, t_icon, t_desc = ("Sin datos T", "⚔️", "")

    # Stats CT side
    pr_ct = pr_player[pr_player["side"] == "CT"]
    if not pr_ct.empty:
        ps_ct = stats.aggregate(pr_ct, clutches=clutches_df, acc=shots_df)
        row_ct = ps_ct.iloc[0] if not ps_ct.empty else pr_ct.iloc[0]
        scores_ct = calculate_player_scores(row_ct)
        ct_role, ct_icon, ct_desc = classify_ct_role(scores_ct, row_ct)
    else:
        row_ct = row_all
        scores_ct = scores_all
        ct_role, ct_icon, ct_desc = ("Sin datos CT", "⚔️", "")

    # Identidad combinada
    if "AWPer" in t_role and "AWPer" in ct_role:
        dual_title = "AWPer Principal (T & CT)"
        dual_badge = "🎯 AWPer Principal"
    else:
        # Simplificar nombres para el badge
        short_t = t_role.split(" / ")[0]
        short_ct = ct_role.split(" (")[0].split(" / ")[0]
        dual_title = f"{short_t} (T) · {short_ct} (CT)"
        dual_badge = f"{t_icon} {short_t} · {ct_icon} {short_ct}"

    return {
        "name": row_all.get("name", ""),
        "dual_title": dual_title,
        "dual_badge": dual_badge,
        "overall": {"role": all_role, "icon": all_icon, "desc": all_desc, "scores": scores_all, "row": row_all},
        "t": {"role": t_role, "icon": t_icon, "desc": t_desc, "scores": scores_t, "row": row_t},
        "ct": {"role": ct_role, "icon": ct_icon, "desc": ct_desc, "scores": scores_ct, "row": row_ct},
    }


def get_player_side_archetypes(d: DemoData, steamid: str) -> dict:
    """Devuelve el desglose completo del jugador: rol en T, rol en CT, rol global e identidad dual."""
    pr = stats.player_rounds(d)
    pr_player = pr[pr["steamid"] == steamid]
    if pr_player.empty:
        return {}
    return compute_player_side_archetypes_from_pr(pr_player, stats.clutches(d), stats.shots_hits(d))


def compute_match_average_scores(ps: pd.DataFrame) -> dict[str, float]:
    """Calcula el promedio del partido en cada eje de radar para usar como referencia."""
    if ps.empty:
        return {axis: 50.0 for axis in RADAR_AXES}

    all_scores = [calculate_player_scores(row) for _, row in ps.iterrows()]
    avg = {}
    for axis in RADAR_AXES:
        avg[axis] = round(float(np.mean([s[axis] for s in all_scores])), 1)
    return avg
