"""Posición y rol de cada jugador, por comportamiento: dónde se para y cuándo, no cuánto mata.

Cada mapa y lado tiene cinco puestos (en Mirage CT: AWPer, A Anchor, A Connector, B Short, B Anchor). Un puesto se
define por la zona del mapa que ocupa el jugador en cada momento de la ronda. Las plantillas de cada puesto se
aprendieron de partidas profesionales etiquetadas con la base pública de Harry "NER0" Richards (@NER0cs), y en una
partida nueva se reparte a los cinco jugadores de un equipo entre los cinco puestos (uno cada uno) eligiendo el
reparto que mejor encaja. Validado dejando cada equipo afuera del entrenamiento: ~80 % de acierto en el puesto exacto
(al azar sería 20 %).

El rol sale de los puestos, como en la base de NER0: cada puesto tiene un peso entre 0 y 1 (en CT, 0 = ancla un
sitio y 1 = rota; en T, 0 = lurkea un extremo y 1 = toma espacio con el equipo). El rol es el promedio de los pesos
de los puestos que jugó en cada mapa: un jugador es lurker porque en sus mapas juega los puestos de lurk.

Las plantillas viven en assets/positions/templates.npz (scripts/build_position_templates.py las regenera)."""
from __future__ import annotations

import itertools
import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import numpy as np
import pandas as pd

from .parser import DemoData

TEMPLATES = Path(__file__).resolve().parent.parent / "assets" / "positions" / "templates.npz"
BINS = 28
SIGMA = 1.2
# Ventanas de la ronda (segundos): primero el setup / la salida, después la rotación o el desarrollo
WINDOWS = {"CT": [(5, 20), (20, 40)], "T": [(5, 25), (25, 50)]}
AWP_MIN_SHARE, AWP_MIN_KILLS = 0.25, 3

# Umbrales de NER0 para pasar del promedio de pesos al nombre del rol
CT_ROLES = [(0.3, "Anchor"), (0.5, "Mixed"), (1.01, "Rotator")]
T_ROLES = [(0.34, "Lurker"), (0.63, "Flex"), (1.01, "Spacetaker")]
ROLE_ES = {"Anchor": "Ancla", "Mixed": "Mixto", "Rotator": "Rotador", "Lurker": "Lurker", "Flex": "Flex",
           "Spacetaker": "Toma espacio", "AWPer": "AWPer"}


# --------------------------------------------------------------------------------------------
# Ocupación del mapa
# --------------------------------------------------------------------------------------------

def _blur(h: np.ndarray, sigma: float = SIGMA) -> np.ndarray:
    k = np.exp(-0.5 * (np.arange(-3, 4) / sigma) ** 2)
    k /= k.sum()
    for ax in (0, 1):
        h = np.apply_along_axis(lambda v: np.convolve(v, k, mode="same"), ax, h)
    return h


def occupancy(x, y, z, t, side: str, grid: dict) -> np.ndarray:
    """Vector de ocupación: un mapa de calor (suavizado, normalizado) por ventana de tiempo, pegados.

    Se usa la raíz: así una zona donde pasa poco tiempo pero siempre (un jiggle en mid) pesa algo y no solo
    donde se queda quieto."""
    x, y, z, t = (np.asarray(a, dtype=float) for a in (x, y, z, t))
    zb = 2 if grid.get("z_split") is not None else 1
    zr = (-1e9, grid["z_split"], 1e9) if zb == 2 else (-1e9, 1e9)
    parts = []
    for a, b in WINDOWS[side]:
        m = (t >= a) & (t < b)
        h, *_ = np.histogramdd(np.c_[x[m], y[m], z[m]], bins=(BINS, BINS, np.array(zr)),
                               range=[grid["x"], grid["y"], (zr[0], zr[-1])])
        h = _blur(h)
        parts.append((h / max(h.sum(), 1e-9)).ravel())
    v = np.sqrt(np.concatenate(parts))
    return v / max(np.linalg.norm(v), 1e-12)


def _awp_share(d: DemoData) -> pd.DataFrame:
    """Por jugador y lado: kills con AWP y qué parte de sus kills son con AWP."""
    k = d.kills[d.kills["is_enemy_kill"]] if len(d.kills) else d.kills
    if k.empty:
        return pd.DataFrame(columns=["steamid", "side", "awp", "share"])
    g = k.assign(awp=k["weapon"].astype(str).str.contains("awp")).groupby(["attacker_steamid", "attacker_side"])
    out = g["awp"].agg(["sum", "size"]).reset_index()
    out.columns = ["steamid", "side", "awp", "kills"]
    out["share"] = out["awp"] / out["kills"].clip(lower=1)
    return out


def player_vectors(d: DemoData, grid: dict) -> pd.DataFrame:
    """Un vector de ocupación por jugador y lado en esta partida (todas las rondas)."""
    p = d.positions
    if p.empty:
        return pd.DataFrame()
    rows = []
    names = d.players.set_index("steamid")
    for (sid, side), g in p.groupby(["steamid", "side"]):
        if side not in WINDOWS or sid not in names.index:
            continue
        rows.append({"steamid": sid, "side": side, "name": names.loc[sid, "name"], "team": names.loc[sid, "team"],
                     "rounds": g["round"].nunique(),
                     "v": occupancy(g["x"], g["y"], g["z"], g["time_in_round"], side, grid)})
    out = pd.DataFrame(rows)
    if out.empty:
        return out
    awp = _awp_share(d)
    return out.merge(awp[["steamid", "side", "awp", "share"]], on=["steamid", "side"], how="left").fillna(
        {"awp": 0, "share": 0.0})


# --------------------------------------------------------------------------------------------
# Plantillas
# --------------------------------------------------------------------------------------------

@dataclass
class MapTemplates:
    grid: dict                      # {"x": (x0, x1), "y": (y0, y1), "z_split": float | None}
    labels: dict[str, list[str]]    # lado -> puestos
    vectors: dict[str, np.ndarray]  # lado -> (puestos, dim)
    weights: dict[str, dict[str, float]]  # lado -> puesto -> peso de rotación / toma de espacio
    support: dict[str, list[int]]   # lado -> ejemplos de entrenamiento por puesto


@lru_cache(maxsize=1)
def templates(path: str = str(TEMPLATES)) -> dict[str, MapTemplates]:
    p = Path(path)
    if not p.exists():
        return {}
    z = np.load(p, allow_pickle=False)
    meta = json.loads(str(z["meta"]))
    out = {}
    for mp, m in meta["maps"].items():
        out[mp] = MapTemplates(
            grid={"x": tuple(m["grid"]["x"]), "y": tuple(m["grid"]["y"]), "z_split": m["grid"]["z_split"]},
            labels=m["labels"], vectors={s: z[f"{mp}|{s}"] for s in m["labels"]},
            weights=m["weights"], support=m["support"])
    return out


def available(map_name: str) -> bool:
    return map_name in templates()


def save_templates(maps: dict[str, MapTemplates], path: Path = TEMPLATES, source: str = "") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    arrays = {f"{mp}|{s}": t.vectors[s].astype(np.float32) for mp, t in maps.items() for s in t.labels}
    meta = {"source": source, "bins": BINS, "windows": WINDOWS,
            "maps": {mp: {"grid": {"x": list(t.grid["x"]), "y": list(t.grid["y"]), "z_split": t.grid["z_split"]},
                          "labels": t.labels, "weights": t.weights, "support": t.support} for mp, t in maps.items()}}
    np.savez_compressed(path, meta=json.dumps(meta), **arrays)
    templates.cache_clear()


# --------------------------------------------------------------------------------------------
# Asignación de puestos
# --------------------------------------------------------------------------------------------

def _best_assignment(s: np.ndarray) -> np.ndarray:
    """Reparto uno a uno que maximiza la similitud total (5 jugadores x 5 puestos: 120 opciones)."""
    n, m = s.shape
    if m < n:
        return s.argmax(axis=1)
    best, pick = -np.inf, None
    rows = np.arange(n)
    for perm in itertools.permutations(range(m), n):
        v = s[rows, perm].sum()
        if v > best:
            best, pick = v, perm
    return np.asarray(pick)


def similarity(vecs: np.ndarray, temp: np.ndarray, labels: list[str], awp: np.ndarray | None = None,
               awp_kills: np.ndarray | None = None) -> np.ndarray:
    s = vecs @ temp.T
    if awp is not None and "AWPer" in labels and len(awp):
        j = labels.index("AWPer")
        i = int(np.argmax(awp))
        # El AWPer se reconoce mejor por el arma que por la zona: el que más mata con AWP (si la usa de verdad)
        # va a ese puesto y nadie más
        if awp[i] >= AWP_MIN_SHARE and (awp_kills is None or awp_kills[i] >= AWP_MIN_KILLS):
            s[:, j] -= 1.0
            s[i, j] += 2.0
    return s


def assign_positions(d: DemoData) -> pd.DataFrame:
    """Puesto de cada jugador en cada lado de esta partida.

    Columnas: steamid, name, team, side, position, weight (0-1: rota / toma espacio), match (similitud con la
    plantilla de su puesto, 0-1) y second (el segundo puesto más parecido)."""
    t = templates().get(d.meta.get("map", ""))
    cols = ["steamid", "name", "team", "side", "rounds", "position", "weight", "match", "second"]
    if t is None:
        return pd.DataFrame(columns=cols)
    pv = player_vectors(d, t.grid)
    rows = []
    for (team, side), g in pv.groupby(["team", "side"]) if len(pv) else []:
        if side not in t.labels:
            continue
        labels = t.labels[side]
        s = similarity(np.stack(g["v"]), t.vectors[side], labels, g["share"].to_numpy(), g["awp"].to_numpy())
        pick = _best_assignment(s)
        raw = np.stack(g["v"]) @ t.vectors[side].T
        for i, (_, r) in enumerate(g.iterrows()):
            j = int(pick[i])
            order = np.argsort(-raw[i])
            second = next((labels[k] for k in order if k != j), "")
            rows.append({"steamid": r["steamid"], "name": r["name"], "team": team, "side": side,
                         "rounds": r["rounds"], "position": labels[j],
                         "weight": t.weights[side].get(labels[j], np.nan), "match": float(raw[i, j]),
                         "second": second})
    return pd.DataFrame(rows, columns=cols)


# --------------------------------------------------------------------------------------------
# Rol a lo largo de varias partidas
# --------------------------------------------------------------------------------------------

def role_name(side: str, score: float) -> str:
    for limit, name in (CT_ROLES if side == "CT" else T_ROLES):
        if score < limit:
            return name
    return ""


def player_roles(assignments: pd.DataFrame) -> pd.DataFrame:
    """Rol por jugador y lado a partir de los puestos de todas sus partidas (`assignments` = assign_positions de
    cada demo concatenados, con columna map).

    Como en NER0: AWPer si su puesto más común es AWPer; si no, el promedio de pesos de sus puestos (cada mapa
    cuenta una vez, con el puesto que más jugó ahí) da Ancla / Mixto / Rotador o Lurker / Flex / Toma espacio."""
    if assignments.empty:
        return pd.DataFrame(columns=["steamid", "side", "role", "score", "maps", "detail"])
    rows = []
    for (sid, side), g in assignments.groupby(["steamid", "side"]):
        per_map = (g.groupby(["map", "position"])["rounds"].sum().reset_index()
                   .sort_values("rounds", ascending=False).drop_duplicates("map"))
        n_awp = (per_map["position"] == "AWPer").sum()
        rifle = per_map[per_map["position"] != "AWPer"]
        if n_awp > len(rifle):
            role, score = "AWPer", np.nan
        else:
            w = g.drop_duplicates(["map", "position"]).set_index(["map", "position"])["weight"]
            score = float(np.mean([w[(m, p)] for m, p in zip(rifle["map"], rifle["position"], strict=True)]))
            role = role_name(side, score)
        detail = ", ".join(f"{m.removeprefix('de_').capitalize()}: {p}" for m, p in
                           zip(per_map["map"], per_map["position"], strict=True))
        rows.append({"steamid": sid, "side": side, "role": role, "score": score, "maps": len(per_map),
                     "detail": detail})
    return pd.DataFrame(rows)


ROLE_WHY = {
    "Anchor": "se queda en un sitio y lo sostiene hasta que llega la rotación",
    "Rotator": "juega en el medio o entre sitios y se mueve hacia donde va la ronda",
    "Mixed": "alterna puestos de ancla y de rotación según el mapa",
    "Lurker": "juega lejos del resto, por un extremo, para cortar rotaciones o castigar por la espalda",
    "Spacetaker": "va al frente con el equipo y gana zonas del mapa para la ejecución",
    "Flex": "alterna puestos de lurk y de toma de espacio según el mapa",
    "AWPer": "juega con el AWP en la mayoría de sus mapas",
}
