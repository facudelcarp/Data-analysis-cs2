"""Estrategia de cada ronda por lo que se observa (no por cómo terminó), con nombre compuesto y evidencia.

Vocabulario de analistas y coaches (default, execute, rush, split, fake; setup, stack, agresión, rotación,
retake), traducido a reglas medibles sobre posiciones cada 0.5 s, granadas y bomba. Cada etiqueta guarda la
evidencia que la justifica ("split: 3 por TRamp y 2 por PalaceInterior a los 41 s"), y las piezas van en columnas
separadas para poder agrupar rondas después ("todas sus rondas de split a A").

T, por fases:
- apertura (a los 20 s, o antes si hubo contacto): cómo se reparten. Default = abiertos en 3 zonas (A, Mid, B);
  agrupados = 4 o más en una; si no, control de la zona con más jugadores;
- golpe: el primer momento en que 3 o más T (o todos los vivos, si quedan 2-3) están sobre un sitio. De ahí:
  rush (antes de los 25 s y con poca utilidad), execute (3+ granadas en el sitio alrededor del golpe) o golpe con
  poca utilidad; split si entran por dos accesos separados; fake si antes cargaron el otro sitio; cambio de sitio
  si plantan en el otro;
- tempo: temprano (< 30 s), medio (< 60 s) o tardío.
Sin golpe: se describe con hechos (pick temprano, cayó en la apertura, guardó, sin golpe).

CT:
- setup a los 15 s (o al primer contacto): jugadores en A, Mid y B ("2-1-2"); stack si 3+ en un sitio;
- agresión: CT del lado T del mapa antes de los 20 s, o kill CT temprana lejos de los sitios;
- respuesta al golpe: cuántos aguantan en el sitio, cuántos rotan y en cuánto llegan; con plante, si el sitio
  quedó vacío (retake) o se defendió dentro.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from . import zones
from .parser import DemoData

APERTURA_S = 20.0
SETUP_S = 15.0
STACK_N = 4             # stack: 4+ CT del mismo lado del mapa (con 3 es el reparto normal en varios mapas)
UTIL_SITE = 0.45        # granadas que caen a esta distancia del sitio cuentan para el golpe
UTIL_SITE_FACTOR = 2.0  # ...o hasta el doble del radio del sitio, lo que sea mayor
FAKE_NEAR = 1.5         # presencia en el otro sitio para el fake: hasta 1.5 veces su radio
UTIL_WINDOW = (20.0, 8.0)  # desde 20 s antes del golpe hasta 8 s después
RUSH_S, RUSH_UTIL = 25.0, 3  # un rush pro igual lleva un par de flashes
EXECUTE_UTIL = 3
FAKE_WINDOW = (25.0, 4.0)  # entre 25 y 4 s antes del golpe
AGGRO_S = 20.0
AGGRO_DEPTH = 0.75      # agresión: CT bastante más cerca del spawn T que del suyo (no el control normal de mid)
HOLD_LEAD_S = 5.0       # quiénes aguantaban el sitio: 5 s antes del golpe (en el golpe, los anclas ya cayeron)
TEMPO = ((30.0, "temprano"), (60.0, "medio"), (1e9, "tardío"))
REGION_ES = {"A": "A", "B": "B", "M": "Mid", "TS": "spawn"}


def _tempo(t: float) -> str:
    return next(name for limit, name in TEMPO if t < limit)


def _alive_at(p: pd.DataFrame, t: float) -> pd.DataFrame:
    """Última muestra de cada jugador vivo hasta el segundo t (las posiciones vienen cada 0.5 s)."""
    w = p[(p["time_in_round"] <= t) & (p["time_in_round"] > t - 1.0)]
    w = w.sort_values("time_in_round").groupby("steamid").tail(1)
    return w[w["health"] > 0]


def _counts(regions) -> dict[str, int]:
    s = pd.Series(regions).value_counts()
    return {k: int(s.get(k, 0)) for k in ("A", "M", "B", "TS")}


def round_strategies(d: DemoData, geo: zones.MapGeo | None = None) -> pd.DataFrame:
    """Una fila por ronda con la lectura de T y de CT (ver el docstring del módulo). Vacío si no hay geografía
    del mapa (ver zones.py)."""
    g = geo or zones.geo(d.meta["map"], [d])
    if g is None or d.positions.empty:
        return pd.DataFrame()
    pos = d.positions
    gren = d.grenades
    kills = d.kills[d.kills["is_enemy_kill"]] if len(d.kills) else d.kills
    dmg = d.damages
    plants = d.bomb[d.bomb["event_code"] == "bomb_planted"] if len(d.bomb) else d.bomb
    rows = []
    for r in d.rounds.itertuples():
        p = pos[pos["round"] == r.round]
        if p.empty:
            continue
        p = p.assign(region=g.region(p["x"], p["y"], p["z"]), place=g.place(p["x"], p["y"], p["z"]),
                     dA=g.dist_site(p["x"], p["y"], p["z"], "A"), dB=g.dist_site(p["x"], p["y"], p["z"], "B"))
        k = kills[kills["round"] == r.round] if len(kills) else kills
        dm = dmg[(dmg["round"] == r.round) & (dmg["attacker_side"] != dmg["victim_side"])] if len(dmg) else dmg
        first_contact = float(dm["time_in_round"].min()) if len(dm) else np.inf
        gr = gren[gren["round"] == r.round] if len(gren) else gren
        pl = plants[plants["round"] == r.round] if len(plants) else plants
        plant_t = float(pl["time_in_round"].iloc[0]) if len(pl) else np.nan
        plant_site = str(pl["site_letter"].iloc[0]) if len(pl) else ""
        p = p.assign(onA=p["dA"] < g.site_r["A"], onB=p["dB"] < g.site_r["B"],
                     holdA=p["region"] == "A", holdB=p["region"] == "B")
        t_row = _t_side(g, p[p["side"] == "T"], gr[gr["thrower_side"] == "T"] if len(gr) else gr, k, first_contact,
                        plant_t, plant_site, r)
        ct_row = _ct_side(g, p[p["side"] == "CT"], k, first_contact, t_row, plant_t)
        rows.append({"round": r.round, "t_team": r.t_team, "ct_team": r.ct_team, "t_buy": r.t_buy, "ct_buy": r.ct_buy,
                     "winner_side": r.winner_side, "plant_site": plant_site, "plant_time": plant_t, **t_row, **ct_row})
    return pd.DataFrame(rows)


# --------------------------------------------------------------------------------------------
# T
# --------------------------------------------------------------------------------------------

def _t_side(g, p, gr, k, first_contact, plant_t, plant_site, r) -> dict:
    out = {"t_opening": "", "t_formation": "", "t_kind": "", "t_site": "", "t_split": False, "t_entries": "",
           "t_fake": "", "t_switch": "", "t_tempo": "", "commit_s": np.nan, "t_util": 0, "t_failed": False,
           "t_name": "", "t_evidence": ""}
    if p.empty:
        return out
    # apertura
    t_open = max(8.0, min(APERTURA_S, first_contact - 0.5))
    a = _alive_at(p, t_open)
    c = _counts(a["region"])
    out["t_formation"] = " ".join(f"{REGION_ES[k]} {v}" for k, v in c.items() if v)
    lanes = sum(1 for k in ("A", "M", "B") if c[k])
    if lanes == 3:
        opening = "Default"
    elif max(c["A"], c["M"], c["B"]) >= 4:
        opening = f"Agrupados {REGION_ES[max(('A', 'M', 'B'), key=lambda x: c[x])]}"
    else:
        main = max(("A", "M", "B"), key=lambda x: c[x])
        opening = f"Control {REGION_ES[main]}" if c[main] else "Lento"
    out["t_opening"] = opening

    # golpe
    commit_t, site = _commit(p)
    if np.isfinite(plant_t) and np.isfinite(commit_t) and commit_t > plant_t:
        commit_t, site = np.nan, ""  # el golpe no puede ser después del plante: se busca alrededor del plante
    if np.isnan(commit_t) and plant_site:
        # plante sin tres juntos sobre el sitio (dos entran y el resto cubre accesos): el golpe es cuando llegan dos
        on = p[(p["health"] > 0) & p[f"on{plant_site}"] & (p["time_in_round"] >= plant_t - 20)
               & (p["time_in_round"] <= plant_t)]
        two = on.groupby((on["time_in_round"] * 2).round() / 2)["steamid"].nunique()
        two = two[two >= 2]
        commit_t, site = (float(two.index[0]) if len(two) else max(0.0, plant_t - 5.0)), plant_site
    evidence = [f"a los {t_open:.0f} s: {out['t_formation'] or 'sin datos'}"]
    failed = False
    if np.isnan(commit_t):
        # golpe frenado: 3+ T de un lado del mapa con granadas sobre el sitio, pero no llegaron a pisarlo
        commit_t, site = _attempt(g, p, gr, k)
        failed = np.isfinite(commit_t)
    if np.isnan(commit_t):
        out["t_kind"] = _no_commit(k, r, p)
        out["t_name"] = f"{opening} → {out['t_kind']}"
        out["t_evidence"] = "; ".join(evidence)
        return out
    out.update(t_site=site, commit_s=round(commit_t, 1), t_tempo=_tempo(commit_t))
    other = "B" if site == "A" else "A"
    if len(gr):
        dist = g.dist_site(gr["x"], gr["y"], gr["z"], site)
        util = gr[(dist < _util_r(g, site)) & (gr["time_in_round"] >= commit_t - UTIL_WINDOW[0])
                  & (gr["time_in_round"] <= commit_t + UTIL_WINDOW[1])]
        out["t_util"] = len(util)
        do = g.dist_site(gr["x"], gr["y"], gr["z"], other)
        fake_util = gr[(do < _util_r(g, other)) & (gr["time_in_round"] >= commit_t - FAKE_WINDOW[0])
                       & (gr["time_in_round"] <= commit_t - FAKE_WINDOW[1])]
    else:
        fake_util = gr
    if commit_t <= RUSH_S and out["t_util"] <= RUSH_UTIL:
        kind = "Rush"
    elif out["t_util"] >= EXECUTE_UTIL:
        kind = "Execute"
    else:
        kind = "Golpe con poca utilidad"
    out["t_kind"] = kind
    out["t_failed"] = failed
    evidence.append(f"{'golpe frenado' if failed else 'golpe'} a {site} a los {commit_t:.0f} s con {out['t_util']} "
                    "granadas en el sitio")

    # accesos: por dónde estaba cada uno 4 s antes de pisar el sitio
    entries = _entries(g, p, site, commit_t)
    if entries:
        out["t_entries"] = " + ".join(f"{n} {pl}" for pl, n in entries)
        out["t_split"] = len(entries) >= 2 and sum(n for _, n in entries) >= 3
        if out["t_split"]:
            evidence.append(f"entran por {out['t_entries']}")
        else:
            out["t_entries"] = out["t_entries"] if len(entries) == 1 else ""
    # fake: carga del otro sitio antes del golpe
    pre = p[(p["time_in_round"] >= commit_t - FAKE_WINDOW[0]) & (p["time_in_round"] <= commit_t - FAKE_WINDOW[1])]
    near_other = pre[pre[f"d{other}"] < FAKE_NEAR * g.site_r[other]]["steamid"].nunique() if len(pre) else 0
    # fake: granadas Y gente en el otro sitio (en un default se tira utilidad en los dos lados sin que sea un fake)
    if (len(fake_util) >= 2 and near_other >= 1) or len(fake_util) >= 4:
        out["t_fake"] = other
        evidence.append(f"antes cargaron {other} ({len(fake_util)} granadas, {near_other} jugadores)")
    if plant_site and plant_site != site:
        out["t_switch"] = plant_site
        evidence.append(f"terminaron plantando en {plant_site}")
    name = f"{opening} → {kind} {site}" + (" (frenado)" if failed else "")
    if out["t_split"]:
        name += f" (split {out['t_entries']})"
    if out["t_fake"]:
        name += f" · fake {out['t_fake']}"
    if out["t_switch"]:
        name += f" · cambio a {out['t_switch']}"
    out["t_name"] = f"{name} · {out['t_tempo']}"
    out["t_evidence"] = "; ".join(evidence)
    return out


def _util_r(g, site: str) -> float:
    """Granadas "sobre el sitio": en sitios grandes (Nuke) los humos de un execute caen lejos del centro."""
    return max(UTIL_SITE, UTIL_SITE_FACTOR * g.site_r[site])


def _attempt(g, p: pd.DataFrame, gr: pd.DataFrame, k: pd.DataFrame) -> tuple[float, str]:
    """Golpe que no llegó: 3+ T vivos del lado de un sitio, 3+ granadas T sobre ese sitio (±8 s) y 2+ T muertos en
    los 15 s siguientes (los frenaron)."""
    if gr is None or gr.empty or k is None or k.empty:
        return np.nan, ""
    t_deaths = k.loc[k["victim_side"] == "T", "time_in_round"].to_numpy()
    alive = p[(p["health"] > 0) & (p["time_in_round"] > 10)]
    b = (alive["time_in_round"].to_numpy() * 2).round() / 2
    per = alive.assign(b=b).groupby(["b", "steamid"])[["holdA", "holdB"]].any().groupby(level="b").sum()
    for t, row in per.iterrows():
        for site in ("A", "B"):
            if row[f"hold{site}"] >= 3:
                d = g.dist_site(gr["x"], gr["y"], gr["z"], site)
                n = ((d < _util_r(g, site)) & (gr["time_in_round"] - t).abs().le(8)).sum()
                if n >= 3 and ((t_deaths >= t) & (t_deaths <= t + 15)).sum() >= 2:
                    return float(t), site
    return np.nan, ""


def _commit(p: pd.DataFrame) -> tuple[float, str]:
    """Primer segundo con 3+ T vivos sobre un sitio (o todos los vivos si quedan 2 o 3). Vectorizado: una pasada."""
    alive = p[p["health"] > 0]
    if alive.empty:
        return np.nan, ""
    b = (alive["time_in_round"].to_numpy() * 2).round() / 2
    per = (alive.assign(b=b).groupby(["b", "steamid"], sort=True)[["onA", "onB"]].any()
           .groupby(level="b").agg(n=("onA", "size"), A=("onA", "sum"), B=("onB", "sum")))
    need = np.where(per["n"] > 3, 3, np.maximum(2, per["n"]))
    for site in ("A", "B"):
        per[f"hit{site}"] = per[site] >= need
    hit = per[per["hitA"] | per["hitB"]]
    if hit.empty:
        return np.nan, ""
    first = hit.iloc[0]
    return float(hit.index[0]), ("A" if first["hitA"] else "B")


def _entries(g, p, site: str, commit_t: float) -> list[tuple[str, int]]:
    """Accesos al sitio: la zona de cada T 4 s antes de pisarlo (cerca del golpe), agrupando zonas vecinas."""
    w = p[(p["time_in_round"] <= commit_t + 8) & (p["health"] > 0)]
    rows = []
    for sid, s in w.groupby("steamid"):
        s = s.sort_values("time_in_round")
        inside = s[s[f"on{site}"]]
        if inside.empty:
            continue
        t_in = inside["time_in_round"].iloc[0]
        if t_in < commit_t - 10:  # ya estaba ahí desde antes: no entró en el golpe
            continue
        before = s[(s["time_in_round"] <= t_in - 4.0) & ~s["place"].astype(str).str.startswith("Bombsite")]
        if before.empty:  # ya estaba en el sitio: no entró por ningún acceso
            continue
        b = before.iloc[-1]
        if b["place"]:
            rows.append((b["place"], b["x"], b["y"]))
    if not rows:
        return []
    df = pd.DataFrame(rows, columns=["place", "x", "y"])
    # mismo acceso si las zonas son contiguas (TRamp y Stairs); dos zonas que no se tocan son caminos distintos
    groups: list[list[str]] = []
    for pl in df["place"].value_counts().index:
        for grp in groups:
            if any(g.touching(pl, other) for other in grp):
                grp.append(pl)
                break
        else:
            groups.append([pl])
    out = []
    for grp in groups:
        sub = df[df["place"].isin(grp)]
        out.append((sub["place"].mode().iloc[0], len(sub)))
    return sorted(out, key=lambda x: -x[1])


def _no_commit(k: pd.DataFrame, r, p: pd.DataFrame) -> str:
    if str(r.t_buy) in ("Eco", "Semi-eco") and r.winner_side == "CT":
        return "Eco / guardado"
    t_first = k[k["attacker_side"] == "T"]["time_in_round"].min() if len(k) else np.nan
    end_alive = p[p["time_in_round"] >= p["time_in_round"].max() - 1]
    survivors = int((end_alive.groupby("steamid")["health"].last() > 0).sum())
    if r.winner_side == "CT" and survivors >= 2:  # perdieron sin golpear y quedaron vivos: guardaron
        return "Guardó"
    if np.isfinite(t_first) and t_first <= AGGRO_S:
        return "Pick temprano, sin golpe"
    if len(k) and k["time_in_round"].min() <= 30 and r.winner_side == "CT":
        return "Cayó en la apertura"
    return "Sin golpe"


# --------------------------------------------------------------------------------------------
# CT
# --------------------------------------------------------------------------------------------

def _ct_side(g, p, k, first_contact, t_row: dict, plant_t: float) -> dict:
    out = {"ct_setup": "", "ct_stack": "", "ct_aggression": "", "ct_holders": np.nan, "ct_rotators": np.nan,
           "ct_rotation_s": np.nan, "ct_response": "", "ct_name": "", "ct_evidence": ""}
    if p.empty:
        return out
    t_set = max(5.0, min(SETUP_S, first_contact - 0.5))
    a = _alive_at(p, t_set)
    c = _counts(a["region"])
    out["ct_setup"] = f"{c['A']}-{c['M'] + c['TS']}-{c['B']}"
    for site in ("A", "B"):
        if c[site] >= STACK_N:
            out["ct_stack"] = site
    evidence = [f"a los {t_set:.0f} s: A {c['A']}, Mid {c['M'] + c['TS']}, B {c['B']}"]
    # agresión: CT del lado T del mapa (más cerca del spawn T que del CT) antes de los 20 s
    early = p[(p["time_in_round"] <= AGGRO_S) & (p["health"] > 0)]
    dt = np.hypot(early["x"] - g.spawn["T"][0], early["y"] - g.spawn["T"][1])
    dc = np.hypot(early["x"] - g.spawn["CT"][0], early["y"] - g.spawn["CT"][1])
    aggro = early[dt < AGGRO_DEPTH * dc]
    ck = k[(k["attacker_side"] == "CT") & (k["time_in_round"] <= AGGRO_S)] if len(k) else k
    if len(ck):  # solo kills hechas desde el lado T del mapa (no un AWP que mata desde el sitio)
        kdt = np.hypot(ck["attacker_x"] - g.spawn["T"][0], ck["attacker_y"] - g.spawn["T"][1])
        kdc = np.hypot(ck["attacker_x"] - g.spawn["CT"][0], ck["attacker_y"] - g.spawn["CT"][1])
        ck = ck[kdt < AGGRO_DEPTH * kdc]
    places = list(dict.fromkeys([*aggro["place"].replace("", np.nan).dropna().value_counts().index[:2],
                                 *(ck["attacker_place"].replace("", np.nan).dropna().tolist() if len(ck) else [])]))[:2]
    if aggro["steamid"].nunique() or len(ck):
        out["ct_aggression"] = ", ".join(places) or "sí"
        evidence.append(f"agresión temprana: {out['ct_aggression']}")
    # respuesta al golpe
    site, tc = t_row.get("t_site"), t_row.get("commit_s")
    if site and np.isfinite(tc):
        at = _alive_at(p, max(0.0, tc - HOLD_LEAD_S))
        holders = at[at[f"hold{site}"]]
        rot = at[~at["steamid"].isin(holders["steamid"])]
        out["ct_holders"], out["ct_rotators"] = len(holders), len(rot)
        arrive = []
        for sid in rot["steamid"]:
            s = p[(p["steamid"] == sid) & (p["time_in_round"] > tc) & p[f"hold{site}"]]
            if len(s):
                arrive.append(float(s["time_in_round"].iloc[0]) - tc)
        if arrive:
            out["ct_rotation_s"] = round(float(np.median(arrive)), 1)
        resp = f"golpe {site}: aguantan {len(holders)}, rotan {len(rot)}"
        if arrive:
            resp += f" ({len(arrive)} llegan, {out['ct_rotation_s']:.0f} s)"
        if np.isfinite(plant_t):
            ap = _alive_at(p, plant_t)
            on = ap[ap[f"hold{site}"]]
            resp += " · retake" if on.empty else f" · defendieron dentro ({len(on)})"
        out["ct_response"] = resp
        evidence.append(resp)
    name = out["ct_setup"]
    if out["ct_stack"]:
        name += f" · stack {out['ct_stack']}"
    if out["ct_aggression"]:
        name += f" · agresión {out['ct_aggression']}"
    if out["ct_response"]:
        name += f" · {out['ct_response']}"
    out["ct_name"] = name
    out["ct_evidence"] = "; ".join(evidence)
    return out


# --------------------------------------------------------------------------------------------
# Resúmenes
# --------------------------------------------------------------------------------------------

def plan_of(s: pd.DataFrame) -> pd.Series:
    """El plan T sin el tempo, para agrupar rondas parecidas."""
    out = s["t_opening"] + " → " + s["t_kind"]
    has_site = s["t_site"] != ""
    out = out.where(~has_site, out + " " + s["t_site"])
    out = out.where(~s["t_split"].astype(bool), out + " split")
    return out.where(s["t_fake"] == "", out + " · fake " + s["t_fake"])


def summary_tables(s: pd.DataFrame, t_won: pd.Series, ct_won: pd.Series) -> tuple[pd.DataFrame, pd.DataFrame]:
    t = s.assign(plan=plan_of(s), won=t_won.to_numpy())
    tt = t.groupby("plan").agg(Rondas=("round", "size"), Ganadas=("won", "sum"),
                               golpe=("commit_s", "median")).reset_index()
    tt["% ganadas"] = (100 * tt["Ganadas"] / tt["Rondas"]).round(0)
    tt = tt.rename(columns={"plan": "Plan T", "golpe": "Golpe (s, mediana)"}).sort_values("Rondas", ascending=False)
    c = s.assign(won=ct_won.to_numpy(), setup=s["ct_setup"] + np.where(s["ct_stack"] != "", " · stack " + s["ct_stack"], ""))
    ct = c.groupby("setup").agg(Rondas=("round", "size"), Ganadas=("won", "sum"),
                                agresion=("ct_aggression", lambda x: 100 * (x != "").mean()),
                                rot=("ct_rotation_s", "median")).reset_index()
    ct["% ganadas"] = (100 * ct["Ganadas"] / ct["Rondas"]).round(0)
    ct = ct.rename(columns={"setup": "Setup CT (A-Mid-B)", "agresion": "% con agresión",
                            "rot": "Rotación (s, mediana)"}).sort_values("Rondas", ascending=False)
    return tt, ct
