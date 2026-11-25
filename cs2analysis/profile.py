"""Perfil de un jugador frente al resto de la biblioteca: dónde está fuerte, qué trabajar y su forma reciente.

Pensado para el uso propio (FACEIT): la biblioteca son tus partidas, así que el resto de los jugadores son rivales y
compañeros de tu mismo nivel y la comparación es contra gente de tu nivel, no contra profesionales."""
from __future__ import annotations

import numpy as np
import pandas as pd

# (columna, nombre, más alto es mejor, formato del valor)
METRICS = [
    ("rating2", "Rating", True, "{:.2f}"),
    ("adr", "ADR", True, "{:.0f}"),
    ("kast_pct", "KAST", True, "{:.0f}%"),
    ("kpr", "Kills por ronda", True, "{:.2f}"),
    ("dpr", "Muertes por ronda", False, "{:.2f}"),
    ("hs_pct", "Headshots", True, "{:.0f}%"),
    ("opening_success_pct", "Duelos de apertura ganados", True, "{:.0f}%"),
    ("trade_kills_pr", "Tradeos por ronda", True, "{:.2f}"),
    ("traded_deaths_pct", "Muertes tradeadas", True, "{:.0f}%"),
    ("utility_adr", "Daño de utilidad", True, "{:.1f}"),
    ("flash_assists_pr", "Asistencias de flash por ronda", True, "{:.2f}"),
    ("clutch_pct", "Clutches ganados", True, "{:.0f}%"),
    ("crosshair_deg", "Mira al ver al rival", False, "{:.1f}°"),
    ("reaction_ms", "Reacción", False, "{:.0f} ms"),
    ("counter_strafe_pct", "Counter-strafe", True, "{:.0f}%"),
    ("first_bullet_acc_pct", "Precisión 1ª bala", True, "{:.0f}%"),
]


def _derived(lb: pd.DataFrame) -> pd.DataFrame:
    lb = lb.copy()
    r = lb["rounds"].replace(0, np.nan)
    lb["trade_kills_pr"] = lb["trade_kills"] / r
    lb["flash_assists_pr"] = lb["flash_assists"] / r
    lb["traded_deaths_pct"] = 100 * lb["traded_deaths"] / lb["deaths"].replace(0, np.nan)
    lb["clutch_pct"] = np.where(lb["clutches"] >= 3, 100 * lb["clutches_won"] / lb["clutches"].replace(0, np.nan),
                                np.nan)  # con menos de 3 clutches el % es ruido
    return lb


def percentiles(lb: pd.DataFrame, steamid: str) -> pd.DataFrame:
    """Para cada métrica, en qué percentil está el jugador entre los de la biblioteca (100 = el mejor).

    `lb` es la tabla de jugadores con muestra suficiente (debe incluir al jugador)."""
    lb = _derived(lb)
    if steamid not in set(lb["steamid"]):
        return pd.DataFrame(columns=["metric", "label", "value", "text", "median", "pct", "n"])
    me = lb[lb["steamid"] == steamid].iloc[0]
    rows = []
    for col, label, higher, fmt in METRICS:
        if col not in lb:
            continue
        vals = lb[col].dropna()
        v = me.get(col)
        if len(vals) < 5 or v is None or pd.isna(v):  # con menos de 5 jugadores para comparar no dice nada
            continue
        below = (vals < v).sum() + 0.5 * (vals == v).sum() - 0.5  # sin contarse a sí mismo
        pct = 100 * below / max(len(vals) - 1, 1)
        rows.append({"metric": col, "label": label, "value": float(v), "text": fmt.format(v),
                     "median": float(vals.median()),
                     "pct": float(pct if higher else 100 - pct), "n": len(vals)})
    return pd.DataFrame(rows)


def likely_me(players: pd.DataFrame, n_demos: int) -> str | None:
    """Si la biblioteca son las partidas de una persona, es el que aparece en casi todas: lo proponemos como "yo"."""
    if n_demos < 3 or players.empty:
        return None
    top = players.sort_values("demos", ascending=False)
    best = top.iloc[0]
    second = top.iloc[1]["demos"] if len(top) > 1 else 0
    if best["demos"] >= 0.6 * n_demos and best["demos"] > second:
        return str(best["steamid"])
    return None


def recent_form(per: pd.DataFrame, order: dict[str, str], n: int = 5) -> dict | None:
    """Rating y ADR de las últimas `n` partidas contra el resto. `order`: demo_id -> fecha (ISO) para ordenar."""
    if len(per) < n + 2:
        return None
    per = per.assign(_when=per["demo_id"].map(order).fillna("")).sort_values("_when")
    last, before = per.tail(n), per.iloc[:-n]

    def avg(df, col):  # promedio ponderado por rondas: una partida de 30 rondas pesa más que una de 16
        return float(np.average(df[col], weights=df["rounds"])) if len(df) else np.nan

    return {"n": n, "rating_last": avg(last, "rating2"), "rating_before": avg(before, "rating2"),
            "adr_last": avg(last, "adr"), "adr_before": avg(before, "adr"),
            "wins_last": int((last["Resultado"] == "Victoria").sum())}
