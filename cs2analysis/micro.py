"""Micro-game: aim, reacción, flicks, TTK/TTD, counter-strafe y control de spray.

Dos tablas nuevas por demo:

- **duels**: una fila por kill con arma de fuego, reconstruida tick a tick en los 3 s anteriores.
- **shots** (enriquecida): cada disparo con velocidad del tirador, posición en la ráfaga y si pegó.

Definiciones (todas en milisegundos o grados):

- **visible**: hay línea de visión real desde el ojo del atacante hasta la cabeza o el pecho de la víctima.
  Se calcula contra la malla de colisión del mapa y cuenta los humos activos. Si no hay malla, se usa
  `approximate_spotted_by` del juego, que es menos preciso; la columna `vis_method` indica cuál se usó.
- **first_seen**: inicio del tramo continuo de visibilidad que termina en el primer daño (tolera un hueco de 1 muestra).
- **TTD (time to damage)**: first_seen → primer daño del atacante a esa víctima. Es la métrica de Leetify.
- **Reacción**: first_seen → primer disparo del atacante.
- **TTK (time to kill)**: primer daño → kill.
- **Tiempo hasta morir** (desde el lado de la víctima): primer daño recibido de ese atacante → muerte. Coincide
  con el TTK del duelo.
- **Crosshair placement**: ángulo entre hacia dónde mira el atacante y la cabeza de la víctima en first_seen.
  Se separa en error horizontal (yaw) y vertical (pitch).
- **Pre-aim**: error ≤ 3° en first_seen. **Flick**: error ≥ 10° y disparo en ≤ 500 ms. **Prefire**: disparó
  antes de tener visión.
- **Velocidad angular pico**: máximo giro de la mira entre muestras consecutivas (cada 2 ticks) entre first_seen y el
  disparo, en °/s.
- **Counter-strafe**: el disparo sale con velocidad horizontal ≤ 34% de la velocidad máxima del arma, el umbral a
  partir del cual la imprecisión por movimiento es mínima.
- **Snaps inhumanos**: duelos en los que la mira estaba a ≥ 30° del rival al aparecer y el disparo salió en ≤ 100 ms,
  sin venir disparando antes (spray/spam), con el impacto en ≤ 250 ms y a ≥ 5 m (a quemarropa los ángulos se disparan).
  Ningún humano reacciona en menos de ~150 ms, y menos girando 30°. En las demos de prueba de FACEIT y HLTV da 0;
  en la de matchmaking de Valve marca a los dos jugadores que además matan casi todo a través de paredes.
- **Kills sin línea de visión**: ni ojo→cabeza ni ojo→pecho visibles alrededor del primer impacto. En profesionales
  legítimos da 10-30% (humo, modelos asomados a medias, wallbangs). Valores muy altos junto con muchos wallbangs
  son un indicador para revisar la demo, no una prueba.
- **Precisión de primera bala**: impactos de la primera bala de cada ráfaga (≥ 400 ms sin disparar) sobre el total.
  **Spray**: impactos desde la 4.ª bala de la ráfaga en adelante.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from .constants import TICKRATE, WEAPON_CLASS

FIREARM = {"Rifle", "Francotirador", "SMG", "Escopeta", "Ametralladora", "Pistola"}
WINDOW_S = 3.0
STEP = 2  # ticks entre muestras (32 Hz)
EYE_STAND, DUCK_DROP = 64.0, 18.0
CHEST_OFFSET = 22.0  # debajo de los ojos
SMOKE_RADIUS = 144.0
SMOKE_DURATION_S = 18.0
BURST_GAP_S = 0.4
PREAIM_DEG, FLICK_DEG, FLICK_MAX_MS = 3.0, 10.0, 500.0
# Girar ≥ 30° y disparar en ≤ 100 ms desde que el rival aparece está por debajo del tiempo de reacción humano
# (~150 ms en el mejor caso, sin contar el giro)
SNAP_DEG, SNAP_MAX_MS = 30.0, 100.0
SNAP_MAX_TTD_MS, SNAP_MIN_DIST_M = 250.0, 5.0  # el impacto llega enseguida y no es un forcejeo a quemarropa


def is_inhuman_snap(df: pd.DataFrame) -> pd.Series:
    """Giro grande + disparo antes de lo humanamente posible, sin venir ya disparando (spray/spam)."""
    return ((df["crosshair_deg"] >= SNAP_DEG) & (df["reaction_ms"] <= SNAP_MAX_MS) & ~df["prefire"].astype(bool)
            & (df["ttd_ms"] <= SNAP_MAX_TTD_MS) & (df["distance"] >= SNAP_MIN_DIST_M))
COUNTER_STRAFE_RATIO = 0.34
TICK_PROPS = ["X", "Y", "Z", "pitch", "yaw", "duck_amount"]

MAX_SPEED = {
    "ak47": 215, "m4a1": 225, "m4a1_silencer": 225, "famas": 220, "galilar": 215, "aug": 220, "sg556": 210,
    "awp": 200, "ssg08": 230, "scar20": 215, "g3sg1": 215, "mp9": 240, "mac10": 240, "mp7": 220, "mp5sd": 235,
    "ump45": 230, "p90": 230, "bizon": 240, "nova": 220, "xm1014": 215, "mag7": 225, "sawedoff": 210,
    "m249": 195, "negev": 150, "deagle": 230, "revolver": 220,
}
DEFAULT_MAX_SPEED = 240  # pistolas


# --------------------------------------------------------------------------------------------
# Geometría auxiliar
# --------------------------------------------------------------------------------------------

def view_vectors(pitch, yaw) -> np.ndarray:
    p, y = np.radians(pitch), np.radians(yaw)
    return np.stack([np.cos(p) * np.cos(y), np.cos(p) * np.sin(y), -np.sin(p)], axis=-1)


def angle_deg(u: np.ndarray, v: np.ndarray) -> np.ndarray:
    u = u / np.linalg.norm(u, axis=-1, keepdims=True)
    v = v / np.linalg.norm(v, axis=-1, keepdims=True)
    return np.degrees(np.arccos(np.clip((u * v).sum(-1), -1, 1)))


def aim_errors(eye, pitch, yaw, target) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """(error total, error horizontal, error vertical) en grados entre la mira y el objetivo."""
    d = np.asarray(target, dtype=float) - np.asarray(eye, dtype=float)
    t_yaw = np.degrees(np.arctan2(d[..., 1], d[..., 0]))
    t_pitch = -np.degrees(np.arctan2(d[..., 2], np.hypot(d[..., 0], d[..., 1])))
    yaw_err = (np.asarray(yaw) - t_yaw + 180) % 360 - 180
    pitch_err = np.asarray(pitch) - t_pitch
    total = angle_deg(view_vectors(pitch, yaw), d)
    return total, np.abs(yaw_err), pitch_err


def _segment_hits_sphere(a: np.ndarray, b: np.ndarray, c: np.ndarray, r: float) -> np.ndarray:
    """a, b: (n, 3) segmentos; c: (m, 3) centros. True si el segmento i cruza alguna esfera."""
    if len(c) == 0:
        return np.zeros(len(a), dtype=bool)
    ab = (b - a)[:, None, :]
    ac = c[None, :, :] - a[:, None, :]
    t = np.clip((ac * ab).sum(-1) / np.maximum((ab * ab).sum(-1), 1e-6), 0, 1)
    closest = a[:, None, :] + t[..., None] * ab
    return (np.linalg.norm(closest - c[None], axis=-1) < r).any(axis=1)


# --------------------------------------------------------------------------------------------
# Cálculo
# --------------------------------------------------------------------------------------------

def _is_firearm(w: pd.Series) -> pd.Series:
    return w.map(WEAPON_CLASS).isin(FIREARM)


def needed_ticks(kills: pd.DataFrame, shots: pd.DataFrame) -> list[int]:
    ek = kills[kills["is_enemy_kill"] & _is_firearm(kills["weapon"])] if len(kills) else kills
    w = int(WINDOW_S * TICKRATE)
    ticks = set()
    for k in ek["tick"].astype(int):
        ticks.update(range(k - w - (k - w) % STEP, k + 1, STEP))
        ticks.add(k)
    if len(shots):
        st = shots["tick"].astype(int).to_numpy()
        ticks.update(st.tolist())
        ticks.update((st - STEP).tolist())
    return sorted(t for t in ticks if t >= 0)


def compute(parser, kills: pd.DataFrame, damages: pd.DataFrame, shots: pd.DataFrame, grenades: pd.DataFrame,
            mesh=None) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Devuelve (duels, shots enriquecido). `parser` es el DemoParser de la demo."""
    ticks = needed_ticks(kills, shots)
    if not ticks:
        return pd.DataFrame(), shots
    props = TICK_PROPS + ([] if mesh is not None else ["approximate_spotted_by"])
    td = parser.parse_ticks(props, ticks=ticks)
    if td.empty:
        return pd.DataFrame(), shots
    td["steamid"] = td["steamid"].astype(str)
    td["duck_amount"] = pd.to_numeric(td["duck_amount"], errors="coerce").fillna(0)
    td["eye_z"] = td["Z"] + EYE_STAND - DUCK_DROP * td["duck_amount"]
    by_player = {sid: g.set_index("tick").sort_index() for sid, g in td.groupby("steamid")}
    shots = enrich_shots(shots, damages, by_player)
    duels = _duels(kills, damages, shots, grenades, by_player, mesh)
    return duels, shots


def enrich_shots(shots: pd.DataFrame, damages: pd.DataFrame, by_player: dict) -> pd.DataFrame:
    if shots.empty:
        return shots
    s = shots.copy()
    s["is_firearm"] = _is_firearm(s["weapon"])
    pos = pd.concat([g[["X", "Y"]].assign(steamid=sid) for sid, g in by_player.items()]).reset_index()
    pos = pos.rename(columns={"index": "tick"}) if "tick" not in pos else pos
    now = s[["player_steamid", "tick"]].astype({"player_steamid": str, "tick": "int64"}).reset_index()
    pos["tick"] = pos["tick"].astype("int64")
    cur = now.merge(pos, left_on=["player_steamid", "tick"], right_on=["steamid", "tick"], how="left")
    prev = now.assign(tick=now["tick"] - STEP).merge(pos, left_on=["player_steamid", "tick"],
                                                    right_on=["steamid", "tick"], how="left")
    speed = (np.hypot(cur["X"].to_numpy() - prev["X"].to_numpy(), cur["Y"].to_numpy() - prev["Y"].to_numpy())
             * TICKRATE / STEP)
    s["speed"] = np.round(speed, 1).astype("float32")
    max_speed = s["weapon"].map(MAX_SPEED).fillna(DEFAULT_MAX_SPEED)
    s["counter_strafed"] = (s["speed"] <= COUNTER_STRAFE_RATIO * max_speed).astype("boolean")
    s.loc[s["speed"].isna(), "counter_strafed"] = pd.NA
    # Ráfagas: un disparo abre ráfaga si el jugador no disparaba hace ≥ 400 ms o cambió de arma
    s = s.sort_values(["player_steamid", "tick"], kind="stable")
    gap = s.groupby("player_steamid")["tick"].diff()
    new_burst = (gap.isna() | (gap > BURST_GAP_S * TICKRATE)
                 | (s["weapon"] != s.groupby("player_steamid")["weapon"].shift())).to_numpy(dtype=bool)
    burst_id = np.cumsum(new_burst)
    s["burst_index"] = s.groupby(burst_id).cumcount().astype("int16") + 1
    # Impacto: daño de ese jugador a un rival en el mismo tick del disparo (o el siguiente)
    hits = damages[damages["is_enemy"] & _is_firearm(damages["weapon"])] if len(damages) else damages
    hit_set = set(zip(hits["attacker_steamid"].astype(str), hits["tick"].astype(int))) if len(hits) else set()
    head_set = set(zip(hits.loc[hits["hitgroup"] == "head", "attacker_steamid"].astype(str),
                       hits.loc[hits["hitgroup"] == "head", "tick"].astype(int))) if len(hits) else set()
    sid, tk = s["player_steamid"].astype(str).to_numpy(), s["tick"].astype(int).to_numpy()
    s["hit"] = [(a, t) in hit_set or (a, t + 1) in hit_set for a, t in zip(sid, tk)]
    s["hit_head"] = [(a, t) in head_set or (a, t + 1) in head_set for a, t in zip(sid, tk)]
    s.loc[~s["is_firearm"], ["hit", "hit_head"]] = False
    return s.sort_values("tick", kind="stable").reset_index(drop=True)


def _mesh_visibility_backwards(mesh, eye, head, chest, times, first_hit, block: int = 8) -> np.ndarray:
    """Visibilidad muestra a muestra, solo desde poco después del primer impacto hacia atrás y solo
    hasta que se corta (2 muestras seguidas sin visión). Las muestras no evaluadas quedan en False."""
    n = len(times)
    vis = np.zeros(n, dtype=bool)
    top = min(n, int(np.searchsorted(times, first_hit, side="right")) + 2)
    hi = top
    seen_any = False
    while hi > 0:
        lo = max(0, hi - block)
        idx = np.arange(lo, hi)
        res = mesh.visible_many(np.concatenate([eye[idx], eye[idx]]), np.concatenate([head[idx], chest[idx]]))
        vis[idx] = res[:len(idx)] | res[len(idx):]
        seen_any |= vis[idx].any()
        # cortar si ya hubo visión y aparece un hueco de 2 muestras, o si cerca del impacto no hay nada
        block_vis = vis[lo:top]
        gap = np.flatnonzero(~block_vis[:-1] & ~block_vis[1:]) if len(block_vis) > 1 else []
        if seen_any and len(gap) and lo + gap[-1] < (np.flatnonzero(vis)[-1] if vis.any() else 0):
            break
        if not seen_any and top - lo >= 4:
            break
        hi = lo
    return vis


def _duels(kills, damages, shots, grenades, by_player, mesh) -> pd.DataFrame:
    if kills.empty:
        return pd.DataFrame()
    ek = kills[kills["is_enemy_kill"] & _is_firearm(kills["weapon"])]
    w = int(WINDOW_S * TICKRATE)
    dmg = damages[damages["is_enemy"]] if len(damages) else damages
    fire = shots[shots.get("is_firearm", True)] if len(shots) else shots
    smokes = grenades[grenades["grenade"] == "Humo"] if len(grenades) else grenades
    rows = []
    for k in ek.itertuples():
        A, V = str(k.attacker_steamid), str(k.victim_steamid)
        ga, gv = by_player.get(A), by_player.get(V)
        if ga is None or gv is None:
            continue
        K = int(k.tick)
        common = ga.index.intersection(gv.index)
        common = common[(common >= K - w) & (common <= K) & (common % STEP == 0)]
        if len(common) < 3:
            continue
        a, v = ga.loc[common], gv.loc[common]
        hits = dmg[(dmg["attacker_steamid"] == A) & (dmg["victim_steamid"] == V) & (dmg["tick"] > K - w) & (dmg["tick"] <= K)]
        first_hit = int(hits["tick"].min()) if len(hits) else K
        eye = np.stack([a["X"], a["Y"], a["eye_z"]], axis=1).astype(np.float32)
        head = np.stack([v["X"], v["Y"], v["eye_z"]], axis=1).astype(np.float32)
        chest = head - np.array([0, 0, CHEST_OFFSET], dtype=np.float32)
        if mesh is not None:
            vis = _mesh_visibility_backwards(mesh, eye, head, chest, np.asarray(common), first_hit)
            method = "malla"
        else:
            spotted = gv["approximate_spotted_by"].reindex(common)
            vis = np.array([isinstance(x, (list, np.ndarray)) and str(A) in {str(i) for i in x} for x in spotted])
            method = "spotted"
        active = smokes[(smokes["tick"] <= K) & (smokes["tick"] >= K - w - SMOKE_DURATION_S * TICKRATE)]
        if len(active):
            centers = np.stack([active["x"], active["y"], active["z"] + 48], axis=1).astype(np.float32)
            starts = active["tick"].to_numpy()
            for j, t in enumerate(common):
                live = (starts <= t) & (t <= starts + SMOKE_DURATION_S * TICKRATE)
                if live.any() and _segment_hits_sphere(eye[j:j + 1], head[j:j + 1], centers[live], SMOKE_RADIUS)[0]:
                    vis[j] = False
        times = np.asarray(common)
        hit_idx = int(np.searchsorted(times, first_hit, side="right") - 1)
        hit_idx = max(hit_idx, 0)
        # ¿Había visión alrededor del primer impacto? (±2 muestras: el impacto puede caer entre muestras)
        near = vis[max(0, hit_idx - 2):hit_idx + 2]
        seen_idx, censored = None, False
        if near.any():
            j = hit_idx
            while j > 0 and not vis[j]:
                j -= 1
            # retroceder mientras siga visible, tolerando un hueco de una muestra
            while j > 0:
                if vis[j - 1]:
                    j -= 1
                elif j > 1 and vis[j - 2]:
                    j -= 2
                else:
                    break
            seen_idx = j
            censored = j == 0  # visible desde el inicio de la ventana: no es una situación de reacción
        a_shots = fire[(fire["player_steamid"] == A) & (fire["tick"] > K - w) & (fire["tick"] <= K)]["tick"].astype(int)
        v_shots = fire[(fire["player_steamid"] == V) & (fire["tick"] > K - w) & (fire["tick"] <= K)]["tick"].astype(int)
        row = {
            "tick": K, "round": k.round, "attacker_steamid": A, "attacker_name": k.attacker_name,
            "victim_steamid": V, "victim_name": k.victim_name, "weapon": k.weapon, "headshot": k.headshot,
            "distance": round(float(k.distance), 1), "vis_method": method,
            "penetrated": bool(getattr(k, "penetrated", False)), "thrusmoke": bool(getattr(k, "thrusmoke", False)),
            "ttk_ms": round((K - first_hit) / TICKRATE * 1000, 1),
            "shots_in_duel": int(len(a_shots[a_shots >= first_hit - int(1.5 * TICKRATE)])),
            "visible_at_hit": bool(near.any()), "censored": censored,
        }
        if seen_idx is not None and not censored:
            t0 = int(times[seen_idx])
            err, yerr, perr = aim_errors(eye[seen_idx], a["pitch"].iloc[seen_idx], a["yaw"].iloc[seen_idx], head[seen_idx])
            verr, _, _ = aim_errors(head[seen_idx], v["pitch"].iloc[seen_idx], v["yaw"].iloc[seen_idx], eye[seen_idx])
            row.update({"seen_tick": t0, "ttd_ms": round((first_hit - t0) / TICKRATE * 1000, 1),
                        "crosshair_deg": round(float(err), 2), "crosshair_yaw_deg": round(float(yerr), 2),
                        "crosshair_pitch_deg": round(float(perr), 2), "victim_crosshair_deg": round(float(verr), 2)})
            after = a_shots[a_shots >= t0]
            before = a_shots[(a_shots < t0) & (a_shots >= t0 - int(0.5 * TICKRATE))]
            row["prefire"] = bool(len(before))
            if len(after):
                fs = int(after.min())
                row["reaction_ms"] = round((fs - t0) / TICKRATE * 1000, 1)
                seg = (times >= t0) & (times <= fs)
                views = view_vectors(a["pitch"].to_numpy()[seg], a["yaw"].to_numpy()[seg])
                if len(views) >= 2:
                    step_deg = angle_deg(views[1:], views[:-1])
                    row["flick_deg"] = round(float(angle_deg(views[-1], views[0])), 2)
                    row["peak_ang_speed"] = round(float(step_deg.max() * TICKRATE / STEP), 1)
                else:
                    row["flick_deg"], row["peak_ang_speed"] = 0.0, 0.0
            vs = v_shots[v_shots >= t0]
            row["victim_shot_back"] = bool(len(vs))
            if len(vs):
                row["victim_reaction_ms"] = round((int(vs.min()) - t0) / TICKRATE * 1000, 1)
        rows.append(row)
    out = pd.DataFrame(rows)
    if out.empty:
        return out
    for c in ["crosshair_deg", "reaction_ms", "ttd_ms", "flick_deg", "peak_ang_speed", "victim_reaction_ms",
              "victim_crosshair_deg", "crosshair_yaw_deg", "crosshair_pitch_deg", "seen_tick"]:
        if c not in out:
            out[c] = np.nan
    for c in ["prefire", "victim_shot_back"]:
        if c not in out:
            out[c] = False
        out[c] = out[c].fillna(False).astype(bool)
    out["aim_type"] = np.select(
        [out["crosshair_deg"].isna(), out["prefire"], out["crosshair_deg"] <= PREAIM_DEG,
         (out["crosshair_deg"] >= FLICK_DEG) & (out["reaction_ms"] <= FLICK_MAX_MS)],
        ["sin dato", "prefire", "pre-aim", "flick"], default="ajuste")
    return out


# --------------------------------------------------------------------------------------------
# Agregados por jugador
# --------------------------------------------------------------------------------------------

def player_micro(duels: pd.DataFrame, shots: pd.DataFrame) -> pd.DataFrame:
    """Estadísticas de micro-game por jugador (sirve para una o varias demos concatenadas)."""
    parts = []
    if len(duels):
        d = duels
        g = d.groupby("attacker_steamid")
        valid = d[d["crosshair_deg"].notna()]
        gv = valid.groupby("attacker_steamid")
        att = pd.DataFrame({
            "duels_won": g.size(),
            "ttd_ms": gv["ttd_ms"].median(),
            "reaction_ms": gv["reaction_ms"].median(),
            "ttk_ms": g["ttk_ms"].median(),
            "crosshair_deg": gv["crosshair_deg"].median(),
            "crosshair_pitch_deg": gv["crosshair_pitch_deg"].apply(lambda s: s.abs().median()),
            "preaim_pct": gv["aim_type"].apply(lambda s: 100 * (s == "pre-aim").mean()),
            "flick_pct": gv["aim_type"].apply(lambda s: 100 * (s == "flick").mean()),
            "prefire_pct": gv["aim_type"].apply(lambda s: 100 * (s == "prefire").mean()),
            "peak_ang_speed": gv["peak_ang_speed"].median(),
            "shots_per_kill": g["shots_in_duel"].mean(),
            # Indicadores a revisar (no son prueba de nada: humo, modelos parciales y wallbangs legítimos existen)
            "no_los_kill_pct": g["visible_at_hit"].apply(lambda s: 100 * (~s.astype(bool)).mean()),
            "wallbang_kills": g["penetrated"].sum() if "penetrated" in d else np.nan,
            "inhuman_snaps": is_inhuman_snap(d).groupby(d["attacker_steamid"]).sum(),
        })
        gd = d.groupby("victim_steamid")
        vd = d[d["victim_crosshair_deg"].notna()].groupby("victim_steamid")
        vic = pd.DataFrame({
            "duels_lost": gd.size(),
            "time_to_death_ms": gd["ttk_ms"].median(),
            "caught_off_angle_pct": vd["victim_crosshair_deg"].apply(lambda s: 100 * (s > 45).mean()),
            "shot_back_pct": vd["victim_shot_back"].apply(lambda s: 100 * s.mean()),
        })
        parts += [att, vic]
    if len(shots) and "hit" in shots:
        f = shots[shots["is_firearm"]]
        gs = f.groupby("player_steamid")
        first = f[f["burst_index"] == 1].groupby("player_steamid")
        spray = f[f["burst_index"] >= 4].groupby("player_steamid")
        cs = f[f["counter_strafed"].notna() & ~f["weapon"].map(WEAPON_CLASS).isin({"Escopeta", "Ametralladora"})]
        hits = f[f["hit"]].groupby("player_steamid")
        parts.append(pd.DataFrame({
            "shots": gs.size(),
            "shot_accuracy_pct": 100 * gs["hit"].mean(),
            "first_bullet_acc_pct": 100 * first["hit"].mean(),
            "spray_acc_pct": 100 * spray["hit"].mean(),
            "hs_per_hit_pct": 100 * hits["hit_head"].mean(),
            "counter_strafe_pct": 100 * cs.groupby("player_steamid")["counter_strafed"].apply(lambda s: s.astype(bool).mean()),
            "speed_at_shot": gs["speed"].median(),
        }))
    if not parts:
        return pd.DataFrame()
    out = pd.concat(parts, axis=1)
    out.index.name = "steamid"
    out = out.apply(lambda c: pd.to_numeric(c, errors="coerce")).astype("float64").round(1)
    return out.reset_index()
