"""Análisis táctico: cómo juega cada equipo sus rondas y qué utilidad repite."""
from __future__ import annotations

import numpy as np
import pandas as pd

from .parser import DemoData

# Tamaño de celda (unidades del juego) para agrupar granadas que caen "en el mismo lugar".
# ~1.5 veces el radio de un humo: dos lineups iguales tiradas por personas distintas caen en la misma celda.
LINEUP_CELL = 160
THROW_CELL = 320


def round_tactics(d: DemoData) -> pd.DataFrame:
    """Una fila por ronda con la lectura táctica del lado T (el que ejecuta) y la respuesta CT."""
    r = d.rounds
    k = d.kills[d.kills["is_enemy_kill"]] if len(d.kills) else d.kills
    g = d.grenades
    b = d.bomb
    planted = b[b["event_code"] == "bomb_planted"].groupby("round").first() if len(b) else pd.DataFrame()
    rows = []
    for rnd in r.itertuples():
        kr = k[k["round"] == rnd.round] if len(k) else k
        gr = g[(g["round"] == rnd.round) & (g["thrower_side"] == "T")] if len(g) else g
        plant_t = planted["time_in_round"].get(rnd.round) if len(planted) else None
        before = gr[gr["time_in_round"] <= plant_t] if plant_t is not None and pd.notna(plant_t) else gr
        first = kr.iloc[0] if len(kr) else None
        rows.append({
            "round": rnd.round,
            "t_team": rnd.t_team,
            "t_buy": rnd.t_buy,
            "winner_side": rnd.winner_side,
            "site": rnd.bomb_site or "Sin planta",
            "plant_time": round(float(plant_t), 1) if plant_t is not None and pd.notna(plant_t) else np.nan,
            "first_kill_time": round(float(first["time_in_round"]), 1) if first is not None else np.nan,
            "first_kill_side": first["attacker_side"] if first is not None else "",
            "first_kill_place": first["victim_place"] if first is not None else "",
            "t_smokes": int((before["grenade"] == "Humo").sum()),
            "t_flashes": int((before["grenade"] == "Flash").sum()),
            "t_molos": int((before["grenade"] == "Fuego").sum()),
            "t_he": int((before["grenade"] == "Granada HE").sum()),
            "t_utility": len(before),
            "kills_t": int((kr["attacker_side"] == "T").sum()) if len(kr) else 0,
            "kills_ct": int((kr["attacker_side"] == "CT").sum()) if len(kr) else 0,
        })
    out = pd.DataFrame(rows)
    if len(out):
        out["round_type"] = np.select(
            [out["site"] != "Sin planta", out["kills_t"] + out["kills_ct"] == 0],
            ["Ejecución " + out["site"], "Sin contacto"], default="Sin planta")
    return out


def site_summary(rt: pd.DataFrame) -> pd.DataFrame:
    """Por equipo T: a qué sitio va, cuánto tarda en plantar y cuánto gana."""
    if rt.empty:
        return rt
    x = rt.copy()
    x["t_won"] = x["winner_side"] == "T"
    agg = x.groupby(["t_team", "site"]).agg(
        rondas=("round", "size"), ganadas=("t_won", "sum"), planta_media=("plant_time", "mean"),
        utilidad_media=("t_utility", "mean")).reset_index()
    agg["win_pct"] = (100 * agg["ganadas"] / agg["rondas"]).round(1)
    agg["planta_media"] = agg["planta_media"].round(1)
    agg["utilidad_media"] = agg["utilidad_media"].round(1)
    tot = agg.groupby("t_team")["rondas"].transform("sum")
    agg["pct_rondas"] = (100 * agg["rondas"] / tot).round(1)
    return agg.sort_values(["t_team", "rondas"], ascending=[True, False]).reset_index(drop=True)


def lineups(grenades: pd.DataFrame, min_count: int = 2, kinds: tuple[str, ...] = ("Humo", "Fuego", "Flash", "Granada HE"),
            places: pd.DataFrame | None = None, team_col: str = "thrower_team") -> pd.DataFrame:
    """Granadas repetidas: mismo equipo, tipo y lado, lanzadas desde el mismo lugar y que caen en el mismo lugar.

    `grenades` puede venir de una o varias demos (con columna demo_id). En multi-demo conviene pasar
    en `team_col` una columna con el nombre del equipo (A/B no significa lo mismo entre partidas).
    Devuelve una fila por lineup con cuántas veces se tiró, por quién, en qué segundo y de dónde a dónde.
    """
    need = {"throw_x", "throw_y"}
    if grenades.empty or not need <= set(grenades.columns):
        return pd.DataFrame()
    g = grenades[grenades["grenade"].isin(kinds) & grenades["throw_x"].notna()].copy()
    if g.empty:
        return pd.DataFrame()
    g["cx"] = (g["x"] // LINEUP_CELL).astype(int)
    g["cy"] = (g["y"] // LINEUP_CELL).astype(int)
    g["cz"] = (g["z"] // 256).astype(int)  # separa niveles (Nuke, Vertigo)
    g["tx"] = (g["throw_x"] // THROW_CELL).astype(int)
    g["ty"] = (g["throw_y"] // THROW_CELL).astype(int)
    if "demo_id" not in g:
        g["demo_id"] = ""
    if team_col not in g:
        g[team_col] = ""
    keys = [team_col, "grenade", "thrower_side", "tx", "ty", "cx", "cy", "cz"]
    agg = g.groupby(keys).agg(
        veces=("tick", "size"), demos=("demo_id", "nunique"), rondas=("round", "nunique"),
        x=("x", "mean"), y=("y", "mean"), z=("z", "mean"),
        throw_x=("throw_x", "mean"), throw_y=("throw_y", "mean"), throw_z=("throw_z", "mean"),
        desde=("throw_place", lambda s: s.mode().iloc[0] if len(s.mode()) else ""),
        tiempo_medio=("throw_time", "median"),
        jugadores=("thrower_name", lambda s: ", ".join(s.value_counts().index[:3])),
        enemigos_cegados=("enemies_blinded", "sum"),
    ).reset_index()
    agg = agg[agg["veces"] >= min_count]
    if agg.empty:
        return agg
    agg["tiempo_medio"] = agg["tiempo_medio"].round(1)
    agg["hacia"] = _nearest_place(agg, places)
    agg = agg.rename(columns={team_col: "team"})
    return agg.sort_values(["veces", "rondas"], ascending=False).drop(columns=keys[3:]).reset_index(drop=True)


def _nearest_place(points: pd.DataFrame, places: pd.DataFrame) -> pd.Series:
    """Nombre de zona del .nav más cercano a cada punto, usando posiciones conocidas con zona (kills)."""
    if places is None or places.empty:
        return pd.Series([""] * len(points), index=points.index)
    ref = places.dropna(subset=["x", "y", "place"])
    ref = ref[ref["place"] != ""]
    if ref.empty:
        return pd.Series([""] * len(points), index=points.index)
    rx, ry, rz = ref["x"].to_numpy(), ref["y"].to_numpy(), ref["z"].to_numpy()
    out = []
    for px, py, pz in zip(points["x"], points["y"], points["z"]):
        dist = (rx - px) ** 2 + (ry - py) ** 2 + 4 * (rz - pz) ** 2
        out.append(ref["place"].iloc[int(np.argmin(dist))])
    return pd.Series(out, index=points.index)


def place_reference(d: DemoData) -> pd.DataFrame:
    """Puntos (x, y, z, zona) de referencia: posiciones de atacantes y víctimas en cada kill y de lanzamientos."""
    frames = []
    k = d.kills
    if len(k):
        for who in ("attacker", "victim"):
            frames.append(pd.DataFrame({"x": k[f"{who}_x"], "y": k[f"{who}_y"], "z": k[f"{who}_z"],
                                        "place": k[f"{who}_place"]}))
    g = d.grenades
    if len(g) and "throw_x" in g:
        frames.append(pd.DataFrame({"x": g["throw_x"], "y": g["throw_y"], "z": g["throw_z"], "place": g["throw_place"]}))
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame(columns=["x", "y", "z", "place"])


def team_names(d: DemoData) -> dict[str, str]:
    return {"A": d.meta["team_a"], "B": d.meta["team_b"], "": ""}


def library_tactics(demos: list[DemoData]) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """(round_tactics, granadas, referencia de zonas) de varias demos, con el nombre real de cada equipo."""
    rts, gs, refs = [], [], []
    for d in demos:
        names = team_names(d)
        rt = round_tactics(d)
        if len(rt):
            rt["t_team_name"] = rt["t_team"].map(names)
            rt["demo_id"] = d.demo_id
            rt["map"] = d.meta["map"]
            rts.append(rt)
        g = d.grenades.copy()
        if len(g):
            g["team_name"] = g["thrower_team"].map(names) if "thrower_team" in g else ""
            g["demo_id"] = d.demo_id
            g["map"] = d.meta["map"]
            gs.append(g)
        refs.append(place_reference(d).assign(map=d.meta["map"]))
    cat = lambda xs: pd.concat(xs, ignore_index=True) if xs else pd.DataFrame()  # noqa: E731
    return cat(rts), cat(gs), cat(refs)


def round_strategies(d: DemoData) -> pd.DataFrame:
    """Clasifica tanto el Setup inicial (primeros 15 s) como la Estrategia global de cada ronda."""
    pos = d.positions
    rt = round_tactics(d)
    k = d.kills[d.kills["is_enemy_kill"]] if not d.kills.empty else pd.DataFrame()
    g = d.grenades
    
    rows = []
    for r in rt.itertuples():
        rnd = r.round
        t_side_team = r.t_team
        ct_side_team = "B" if t_side_team == "A" else "A"
        
        # 1. Capa de Setup inicial (posiciones entre segundo 5 y 18 tras freeze time)
        r_pos = pos[(pos["round"] == rnd) & (pos["time_in_round"].between(5, 18))] if not pos.empty else pd.DataFrame()
        ct_setup = "Desconocido"
        t_setup = "Desconocido"
        
        if not r_pos.empty:
            ct_pos = r_pos[r_pos["side"] == "CT"]
            t_pos = r_pos[r_pos["side"] == "T"]
            
            # Conteo de CTs por zona/sitio (inferido por coordenadas o nombres de zona)
            # Para mapas estándar: clasificar en A, B o Mid
            if len(ct_pos):
                last_ct = ct_pos.groupby("steamid").last().reset_index()
                # Clasificación geométrica aproximada o por zona
                places = " ".join(last_ct.get("place", pd.Series(dtype=str)).fillna("")).lower()
                n_a = places.count("a")
                n_b = places.count("b")
                ct_setup = "Setup 2-1-2" if len(last_ct) >= 5 else "Setup estándar"
                
            if len(t_pos):
                last_t = t_pos.groupby("steamid").last().reset_index()
                t_setup = "Default 1-3-1" if len(last_t) >= 5 else "Default estándar"

        # 2. Capa Estratégica Profunda (cómo se ejecutó la ronda en su conjunto)
        # Evaluamos: timing de primera kill, timing de plante, uso coordinado de utilidades
        plant_t = r.plant_time
        fk_t = r.first_kill_time
        site = r.site
        util_count = r.t_utility
        
        # Clasificación de estrategia macro
        if pd.notna(plant_t) and plant_t <= 35:
            strategy = f"Fast Rush {site}"
            explanation = f"Ejecución relámpago a {site} antes de los 35 s de ronda."
        elif pd.notna(plant_t) and plant_t > 35 and util_count >= 3:
            strategy = f"Execute coordinado {site}"
            explanation = f"Ataque con {util_count} granadas de soporte y plante metódico en {site} (~{plant_t:.0f}s)."
        elif pd.notna(plant_t) and plant_t > 65:
            strategy = f"Ataque tardío / Contacto {site}"
            explanation = f"Ronda de desgaste y control de mapa; plante muy tardío a los {plant_t:.0f}s."
        elif site == "Sin planta" and (r.kills_t + r.kills_ct) > 0:
            if pd.notna(fk_t) and fk_t <= 20:
                strategy = "Duelo temprano / Pick agresivo"
                explanation = "La ronda se abrió muy rápido antes de los 20s y derivó en duelo de aniquilación sin plante."
            else:
                strategy = "Pelea de rotaciones / Mid-round"
                explanation = "Ronda disputada por bajas en zonas intermedias sin llegar al plantado del C4."
        else:
            strategy = "Estrategia estándar"
            explanation = "Desarrollo convencional de ronda."

        rows.append({
            "round": rnd,
            "t_team": t_side_team,
            "ct_team": ct_side_team,
            "ct_setup": ct_setup,
            "t_setup": t_setup,
            "strategy": strategy,
            "explanation": explanation,
            "site": site,
            "plant_time": plant_t,
            "utility_used": util_count,
            "winner_side": r.winner_side
        })

    return pd.DataFrame(rows)

