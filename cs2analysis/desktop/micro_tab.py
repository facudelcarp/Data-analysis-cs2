"""Micro-game (aim, reacción, movimiento) para una demo o una biblioteca."""
from __future__ import annotations

import pandas as pd
from PySide6.QtWidgets import QWidget

from .. import micro
from ..labels import MICRO_COLS, MICRO_LABELS, MICRO_NOTE
from ..palette import SERIES, TEAM_COLORS
from ..translate import weapon_name
from . import charts
from .nav import goto_tick
from .page import Combo, Page, Slot
from .widgets import DataTable

AIM_TYPES = ["pre-aim", "ajuste", "flick", "prefire"]
AIM_COLORS = dict(zip(AIM_TYPES, SERIES[:4], strict=True))


def table(duels: pd.DataFrame, shots: pd.DataFrame, names: dict[str, str]) -> pd.DataFrame:
    pm = micro.player_micro(duels, shots)
    if pm.empty:
        return pm
    pm.insert(1, "name", pm["steamid"].map(names))
    return pm.sort_values("crosshair_deg").reset_index(drop=True)


def build(duels: pd.DataFrame, shots: pd.DataFrame, names: dict[str, str], vis_method: str,
          team_of: dict[str, str] | None = None) -> QWidget:
    p = Page()
    if duels is None or duels.empty:
        p.info("Esta demo no tiene datos de micro-game (caché de una versión anterior): volvé a cargar el .dem.")
        p.stretch()
        return p
    if vis_method != "malla":
        p.info("Visibilidad aproximada (radar del juego): bajá las mallas con `cs2a assets` y volvé a cargar la demo "
               "para TTD/crosshair placement con línea de visión real.", "warn")
    pm = table(duels, shots, names)
    _simple(p, pm, duels, names, team_of or {})
    p.sub("Todas las métricas")
    p.add(DataTable(pm[[c for c in MICRO_COLS if c in pm]].rename(columns=MICRO_LABELS), fit_rows=True))
    p.caption(MICRO_NOTE)
    _review_flags(p, pm)
    _advanced(p, pm, duels, shots, names)
    p.stretch()
    return p


def _simple(p: Page, pm: pd.DataFrame, duels: pd.DataFrame, names: dict[str, str], team_of: dict[str, str]) -> None:
    """Tres gráficos que se entienden sin saber qué es cada métrica."""
    df = pm[pm["duels_won"].fillna(0) >= 3].copy()
    if df.empty:
        return
    df["team"] = df["steamid"].map(team_of)
    df["name"] = df["name"] + " (" + df["duels_won"].astype(int).astype(str) + ")"
    p.row(charts.ranking_bars(df, "crosshair_deg", "name", color_col="team", colors=TEAM_COLORS, fmt="{:.1f}°",
                              lower_is_better=True, ref=float(duels["crosshair_deg"].median()), ref_label="partido",
                              title="¿Quién tiene la mira mejor puesta?"),
          charts.ranking_bars(df, "reaction_ms", "name", color_col="team", colors=TEAM_COLORS, fmt="{:.0f} ms",
                              lower_is_better=True, ref=float(duels["reaction_ms"].median()), ref_label="partido",
                              title="¿Quién dispara más rápido al ver al rival?"))
    p.note("izquierda: cuántos grados tuvo que mover la mira hasta la cabeza del rival cuando apareció. "
           "Derecha: cuánto tardó en disparar desde que lo vio. En los dos, menos es mejor (arriba = mejor). "
           "La línea punteada es la mediana del partido. Entre paréntesis, la cantidad de duelos ganados: con pocos, "
           "el número es menos confiable. Solo aparecen jugadores con 3 o más.")
    p.add(charts.aim_type_bars(duels[duels["attacker_steamid"].isin(df["steamid"])], names))
    p.note("de los duelos que ganó cada jugador (entre paréntesis, cuántos): **pre-aim** = ya tenía la mira "
           "encima del rival; **ajuste** = la corrigió un poco; **flick** = tuvo que mover la mira rápido más de "
           "10°; **prefire** = disparó antes de verlo. Mucho pre-aim = buen posicionamiento de mira.")


def _review_flags(p: Page, pm: pd.DataFrame) -> None:
    """Jugadores con patrones que conviene revisar en la demo (no es un anticheat)."""
    if pm.empty or "inhuman_snaps" not in pm:
        return
    blind = (pm["no_los_kill_pct"].fillna(0) >= 50) & (pm["wallbang_kills"].fillna(0) >= 5)
    flagged = pm[(pm["inhuman_snaps"].fillna(0) > 0) | blind]
    if flagged.empty:
        return
    p.section(f"⚠️ Indicadores a revisar ({len(flagged)} jugador/es)")
    p.add(DataTable(flagged[["name", "inhuman_snaps", "no_los_kill_pct", "wallbang_kills", "crosshair_deg",
                             "reaction_ms"]].rename(columns=MICRO_LABELS), fit_rows=True))
    p.caption(f"Snap inhumano: mira a ≥ {micro.SNAP_DEG:.0f}° del rival al aparecer y disparo en ≤ {micro.SNAP_MAX_MS:.0f} ms "
              "(un humano tarda ≥ 150 ms solo en reaccionar). Kills sin visión + wallbangs: mata a través de paredes sin "
              "haber visto al rival. Son señales para mirar esas rondas, no una prueba.")


def _advanced(p: Page, pm: pd.DataFrame, duels: pd.DataFrame, shots: pd.DataFrame, names: dict[str, str]) -> None:
    p.section("Detalle avanzado: distribuciones, duelo por duelo, spray y movimiento")
    valid = duels[duels["crosshair_deg"].notna()].copy()
    valid["name"] = valid["attacker_steamid"].map(names)
    order = pm.dropna(subset=["crosshair_deg"])["name"].tolist()
    p.row(charts.strip_box([(n, valid.loc[valid["name"] == n, "crosshair_deg"].clip(upper=40).to_numpy(dtype=float))
                            for n in order], SERIES[0], "Crosshair placement al ver al rival (° · recortado a 40)", "°"),
          charts.strip_box([(n, valid.loc[valid["name"] == n, "ttd_ms"].clip(upper=1500).to_numpy(dtype=float))
                            for n in order], SERIES[1], "TTD: de ver al rival al primer daño (ms · recortado a 1.5 s)", " ms"))

    players = [("", "Todos"), *sorted(((sid, names.get(sid, sid)) for sid in duels["attacker_steamid"].unique()),
                                      key=lambda x: str(x[1]).lower())]
    who = Combo("Jugador", players)
    p.add(who)
    slot = p.add(Slot(lambda: _duels_detail(who.value, duels, shots)))
    who.changed.connect(slot.refresh)


def _open_duel(show: pd.DataFrame):
    if "demo_id" not in show or "tick" not in show:
        return None
    ids, rounds, ticks = show["demo_id"].to_numpy(), show["round"].to_numpy(), show["tick"].to_numpy()
    return lambda i: goto_tick(ids[i], int(rounds[i]), int(ticks[i]))


def _duels_detail(who: str, duels: pd.DataFrame, shots: pd.DataFrame) -> QWidget:
    p = Page(margins=(0, 0, 0, 0))
    dd = duels if not who else duels[duels["attacker_steamid"] == who]
    groups = []
    for t in AIM_TYPES:
        sub = dd[dd["aim_type"] == t]
        if sub.empty:
            continue
        tips = [f"{a} → {v} ({w}, ronda {r})\nerror {c:.1f}° · reacción {rm:.0f} ms · TTD {ttd:.0f} ms"
                for a, v, w, r, c, rm, ttd in zip(sub["attacker_name"], sub["victim_name"], sub["weapon"], sub["round"],
                                                  sub["crosshair_deg"], sub["reaction_ms"], sub["ttd_ms"], strict=True)]
        groups.append((t, sub["crosshair_deg"].clip(upper=60).to_numpy(dtype=float),
                       sub["reaction_ms"].clip(upper=1500).to_numpy(dtype=float), tips))
    p.add(charts.scatter_groups(groups, AIM_COLORS, "Cada duelo ganado: qué tan lejos estaba la mira vs. cuánto tardó "
                                "en disparar", "crosshair placement (°, escala log)", "reacción (ms)", log_x=True))
    p.caption(f"Pre-aim ≤ {micro.PREAIM_DEG:.0f}° · flick ≥ {micro.FLICK_DEG:.0f}° y disparo en ≤ {micro.FLICK_MAX_MS:.0f} ms · "
              "prefire = disparó antes de tener visión.")
    show = dd.copy()
    show["weapon"] = show["weapon"].map(weapon_name)
    p.add(DataTable(show[["round", "attacker_name", "victim_name", "weapon", "aim_type", "crosshair_deg", "ttd_ms",
                          "reaction_ms", "ttk_ms", "shots_in_duel", "distance", "victim_shot_back"]].rename(columns={
        "round": "Ronda", "attacker_name": "Atacante", "victim_name": "Víctima", "weapon": "Arma", "aim_type": "Tipo",
        "crosshair_deg": "Error (°)", "ttd_ms": "TTD (ms)", "reaction_ms": "Reacción (ms)", "ttk_ms": "TTK (ms)",
        "shots_in_duel": "Disparos", "distance": "Distancia (m)", "victim_shot_back": "Rival disparó"}), decimals=1,
        on_activate=_open_duel(show))
    ).setMinimumHeight(320)
    p.caption("Doble clic en un duelo para verlo en el replay.")

    if len(shots) and "burst_index" in shots:
        f = shots[shots["is_firearm"] & shots["weapon"].isin(["ak47", "m4a1", "m4a1_silencer", "famas", "galilar"])]
        if who:
            f = f[f["player_steamid"] == who]
        if len(f):
            p.sub("Spray y movimiento")
            by = f.assign(b=f["burst_index"].clip(upper=15)).groupby("b").agg(acc=("hit", "mean"), n=("hit", "size"))
            p.row(charts.vbars([str(int(b)) for b in by.index], 100 * by["acc"], SERIES[0],
                               [f"{v:.0f}%" for v in 100 * by["acc"]],
                               title="Rifles: % de impacto según el número de bala en la ráfaga (15 = 15 o más)"),
                  charts.histogram(f["speed"].clip(upper=260).to_numpy(dtype=float), 26,
                                   "Velocidad horizontal al disparar (u/s)", ref=micro.COUNTER_STRAFE_RATIO * 215,
                                   ref_label="umbral AK"))
    return p

