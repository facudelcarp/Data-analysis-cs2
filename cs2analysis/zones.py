"""Geografía de cada mapa aprendida de las demos: dónde están los sitios y los spawns, y qué zona (callout) es cada
punto del mapa. Base de la lectura de estrategias (strategy.py).

Nada está escrito a mano por mapa:
- los centros de los sitios salen de dónde se planta la bomba;
- los spawns, de dónde está cada equipo al terminar el freeze time;
- la zona de cada punto, de los nombres que el juego ya pone en kills, granadas y plantes (callouts del .nav:
  TRamp, PalaceInterior, BombsiteA...). Se arma una grilla del mapa con la zona más vista en cada celda.

Así funciona en cualquier mapa con demos suficientes. Las geografías de mapas competitivos vienen armadas en
assets/zones/geo.npz (scripts/build_zones.py); para otros mapas se arma al vuelo con las demos cargadas."""
from __future__ import annotations

import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import numpy as np
import pandas as pd

from .parser import DemoData

GEO_FILE = Path(__file__).resolve().parent.parent / "assets" / "zones" / "geo.npz"
CELL = 48.0              # unidades por celda de la grilla de zonas (~0.9 m)
FILL_STEPS = 8           # celdas vacías: se completan con la zona vecina hasta esta distancia
Z_SPLIT = {"de_nuke": -495.0, "de_vertigo": 11700.0, "de_train": -50.0}
SIDE_RATIO = 0.6         # sin datos de la zona: es del lado A si está a menos de 0.6 veces la distancia a B
SIDE_MIN_SAMPLES = 40    # muestras de T antes de plantar para aprender el lado de una zona
SIDE_SHARE = 0.75        # una zona es de un lado si los T que pasan por ahí plantan en ese sitio el 75 %+
SITE_R_FACTOR = 1.3
NEAR_SITE = 0.42         # a menos de esta fracción de la distancia A-B del centro de un sitio: "en ese lado"
Z_WEIGHT = 3.0           # la altura pesa triple al medir distancias (pisos distintos = lejos)


@dataclass
class MapGeo:
    map: str
    site: dict[str, np.ndarray]     # "A"/"B" -> (x, y, z)
    spawn: dict[str, np.ndarray]    # "T"/"CT" -> (x, y)
    places: list[str]
    origin: tuple[float, float]
    grid: np.ndarray                # (niveles, nx, ny) índice de zona, -1 = desconocida
    z_split: float | None
    side_of: dict[str, str]         # zona -> "A" / "B" / "M", aprendido de hacia dónde van los T que pasan por ahí
    site_r: dict[str, float]        # "sobre el sitio": radio (fracción A-B) que ocupan los T al plantar, con margen

    def _dist(self, x, y, z, c) -> np.ndarray:
        """Distancia que cuenta la altura (x3): en Nuke A está encima de B, a 300 unidades en planta."""
        x, y = np.asarray(x, dtype=float), np.asarray(y, dtype=float)
        z = np.full(x.shape, c[2]) if z is None else np.asarray(z, dtype=float)
        return np.sqrt((x - c[0]) ** 2 + (y - c[1]) ** 2 + (Z_WEIGHT * (z - c[2])) ** 2)

    @property
    def d_ab(self) -> float:
        a, b = self.site["A"], self.site["B"]
        return float(self._dist(np.array([a[0]]), np.array([a[1]]), np.array([a[2]]), b)[0])

    # ------------------------------------------------------------------ consultas
    def place(self, x, y, z) -> np.ndarray:
        """Zona de cada punto ('' si no se sabe)."""
        x, y, z = (np.asarray(a, dtype=float) for a in (x, y, z))
        lvl = (z < self.z_split).astype(int) if self.z_split is not None and self.grid.shape[0] == 2 else 0
        ix = np.clip(((x - self.origin[0]) // CELL).astype(int), 0, self.grid.shape[1] - 1)
        iy = np.clip(((y - self.origin[1]) // CELL).astype(int), 0, self.grid.shape[2] - 1)
        idx = self.grid[lvl, ix, iy]
        names = np.array([*self.places, ""], dtype=object)
        return names[np.where(idx < 0, len(self.places), idx)]

    def dist_site(self, x, y, z, site: str) -> np.ndarray:
        """Distancia al centro del sitio, en fracciones de la distancia A-B."""
        return self._dist(x, y, z, self.site[site]) / self.d_ab

    def region(self, x, y, z) -> np.ndarray:
        """'A' / 'B' (el sitio y el lado del mapa que lleva a él), 'M' (mid, conectores, spawn CT) o 'TS' (spawn T).

        Por zona: el lado aprendido de los datos; para zonas sin datos, la distancia relativa a cada sitio."""
        x, y, z = (np.asarray(a, dtype=float) for a in (x, y, z))
        da, db = self.dist_site(x, y, z, "A"), self.dist_site(x, y, z, "B")
        ratio = da / np.maximum(db, 1e-9)
        out = np.where(ratio < SIDE_RATIO, "A", np.where(ratio > 1 / SIDE_RATIO, "B", "M")).astype(object)
        if self.side_of:
            pl = self.place(x, y, z)
            learned = np.array([self.side_of.get(p, "") for p in pl], dtype=object)
            out = np.where(learned != "", learned, out)
        dt = np.hypot(x - self.spawn["T"][0], y - self.spawn["T"][1]) / max(
            float(np.hypot(*(self.spawn["T"] - self.spawn["CT"]))), 1.0)
        out[dt < 0.2] = "TS"
        out[da < 0.12] = "A"  # sobre el sitio, siempre
        out[db < 0.12] = "B"
        return out

    def near(self, x, y, z, site: str, frac: float = NEAR_SITE) -> np.ndarray:
        return self.dist_site(x, y, z, site) < frac


# --------------------------------------------------------------------------------------------
# Construcción
# --------------------------------------------------------------------------------------------

def _refs(d: DemoData) -> pd.DataFrame:
    """Puntos con zona conocida de una demo: (x, y, z, place)."""
    parts = []
    k = d.kills
    if len(k):
        for who in ("attacker", "victim"):
            cols = [f"{who}_x", f"{who}_y", f"{who}_z", f"{who}_place"]
            if set(cols) <= set(k.columns):
                parts.append(k[cols].set_axis(["x", "y", "z", "place"], axis=1))
    g = d.grenades
    if len(g) and {"throw_x", "throw_place"} <= set(g.columns):
        parts.append(g[["throw_x", "throw_y", "throw_z", "throw_place"]].set_axis(["x", "y", "z", "place"], axis=1))
    b = d.bomb
    if len(b) and "player_place" in b:
        parts.append(b[["player_x", "player_y", "player_z", "player_place"]].set_axis(["x", "y", "z", "place"], axis=1))
    if not parts:
        return pd.DataFrame(columns=["x", "y", "z", "place"])
    r = pd.concat(parts, ignore_index=True).dropna()
    return r[r["place"].astype(str) != ""]


def build(demos: list[DemoData]) -> MapGeo | None:
    """Geografía de un mapa a partir de varias demos del mismo mapa (None si no alcanza: hacen falta plantes en
    los dos sitios)."""
    if not demos:
        return None
    mp = demos[0].meta["map"]
    plants = pd.concat([d.bomb[d.bomb["event_code"] == "bomb_planted"] for d in demos if len(d.bomb)] or
                       [pd.DataFrame()], ignore_index=True)
    if plants.empty or not {"A", "B"} <= set(plants["site_letter"]):
        return None
    site = {s: plants.loc[plants["site_letter"] == s, ["player_x", "player_y", "player_z"]].median().to_numpy(float)
            for s in ("A", "B")}
    spawn = {}
    for side in ("T", "CT"):
        p = pd.concat([d.positions[(d.positions["side"] == side) & (d.positions["time_in_round"] <= 1)]
                       for d in demos], ignore_index=True)
        if p.empty:
            return None
        spawn[side] = p[["x", "y"]].median().to_numpy(float)
    refs = pd.concat([_refs(d) for d in demos], ignore_index=True)
    allpos = pd.concat([d.positions[["x", "y"]] for d in demos], ignore_index=True)
    x0, y0 = float(min(allpos["x"].min(), refs["x"].min())) - CELL, float(min(allpos["y"].min(), refs["y"].min())) - CELL
    nx = int((max(allpos["x"].max(), refs["x"].max()) - x0) // CELL) + 2
    ny = int((max(allpos["y"].max(), refs["y"].max()) - y0) // CELL) + 2
    z_split = Z_SPLIT.get(mp)
    levels = 2 if z_split is not None else 1
    places = sorted(refs["place"].astype(str).unique())
    pid = {p: i for i, p in enumerate(places)}
    grid = np.full((levels, nx, ny), -1, dtype=np.int16)
    for lvl in range(levels):
        r = refs if levels == 1 else refs[(refs["z"] < z_split) == bool(lvl)]
        if r.empty:
            continue
        ix = ((r["x"].to_numpy() - x0) // CELL).astype(int)
        iy = ((r["y"].to_numpy() - y0) // CELL).astype(int)
        code = r["place"].map(pid).to_numpy()
        # la zona más vista en cada celda
        counts = pd.DataFrame({"ix": ix, "iy": iy, "c": code}).value_counts().reset_index(name="n")
        best = counts.sort_values("n", ascending=False).drop_duplicates(["ix", "iy"])
        grid[lvl, best["ix"].to_numpy(), best["iy"].to_numpy()] = best["c"].to_numpy()
        grid[lvl] = _fill(grid[lvl], FILL_STEPS)
    g = MapGeo(mp, site, spawn, places, (x0, y0), grid, z_split, {}, {})
    g.side_of = _learn_sides(g, demos)
    g.site_r = _learn_site_radius(g, demos)
    return g


def _learn_site_radius(g: MapGeo, demos: list[DemoData]) -> dict[str, float]:
    """Qué tan lejos del centro del sitio están los T vivos cuando se planta (mediana x 1.3): es "estar sobre el
    sitio" en ese mapa. En Nuke da el doble que en Mirage (los sitios son verticales y abiertos)."""
    dist: dict[str, list] = {"A": [], "B": []}
    for d in demos:
        pl = d.bomb[d.bomb["event_code"] == "bomb_planted"] if len(d.bomb) else d.bomb
        p = d.positions[(d.positions["side"] == "T") & (d.positions["health"] > 0)]
        for _, b in pl.iterrows():
            w = p[(p["round"] == b["round"]) & ((p["tick"] - b["tick"]).abs() <= 16)]
            if len(w) and b["site_letter"] in dist:
                dist[b["site_letter"]] += g.dist_site(w["x"], w["y"], w["z"], b["site_letter"]).tolist()
    return {k: round(float(np.clip(SITE_R_FACTOR * np.median(v), 0.15, 0.8)), 3) if len(v) >= 10 else NEAR_SITE
            for k, v in dist.items()}


def _learn_sides(g: MapGeo, demos: list[DemoData]) -> dict[str, str]:
    """Lado de cada zona según hacia dónde plantan los T que pasan por ella en los 20 s antes del plante."""
    rows = []
    for d in demos:
        pl = d.bomb[d.bomb["event_code"] == "bomb_planted"] if len(d.bomb) else d.bomb
        if pl.empty:
            continue
        p = d.positions[d.positions["side"] == "T"]
        for _, b in pl.iterrows():
            w = p[(p["round"] == b["round"]) & (p["tick"] <= b["tick"]) & (p["tick"] >= b["tick"] - 20 * 64)]
            if len(w):
                rows.append(pd.DataFrame({"place": g.place(w["x"], w["y"], w["z"]), "site": b["site_letter"]}))
    if not rows:
        return {}
    df = pd.concat(rows, ignore_index=True)
    df = df[df["place"] != ""]
    out = {}
    for place, grp in df.groupby("place"):
        if len(grp) < SIDE_MIN_SAMPLES:
            continue
        a = (grp["site"] == "A").mean()
        out[place] = "A" if a >= SIDE_SHARE else "B" if a <= 1 - SIDE_SHARE else "M"
    return out


def _fill(g: np.ndarray, steps: int) -> np.ndarray:
    """Celdas sin datos toman la zona de una vecina (crecimiento por pasos, sin pisar lo conocido)."""
    g = g.copy()
    for _ in range(steps):
        empty = g < 0
        if not empty.any():
            break
        for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            src = np.roll(np.roll(g, dx, axis=0), dy, axis=1)
            take = empty & (src >= 0)
            g[take] = src[take]
            empty &= ~take
    return g


# --------------------------------------------------------------------------------------------
# Guardar / cargar
# --------------------------------------------------------------------------------------------

def save(geos: dict[str, MapGeo], path: Path = GEO_FILE) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    meta = {mp: {"site": {k: v.tolist() for k, v in g.site.items()}, "spawn": {k: v.tolist() for k, v in g.spawn.items()},
                 "places": g.places, "origin": list(g.origin), "z_split": g.z_split, "side_of": g.side_of,
                 "site_r": g.site_r}
            for mp, g in geos.items()}
    np.savez_compressed(path, meta=json.dumps(meta), **{mp: g.grid for mp, g in geos.items()})
    _stored.cache_clear()


@lru_cache(maxsize=1)
def _stored(path: str = str(GEO_FILE)) -> dict[str, MapGeo]:
    p = Path(path)
    if not p.exists():
        return {}
    z = np.load(p, allow_pickle=False)
    meta = json.loads(str(z["meta"]))
    return {mp: MapGeo(mp, {k: np.array(v) for k, v in m["site"].items()}, {k: np.array(v) for k, v in m["spawn"].items()},
                       m["places"], tuple(m["origin"]), z[mp], m["z_split"], m.get("side_of", {}),
                       m.get("site_r", {"A": NEAR_SITE, "B": NEAR_SITE}))
            for mp, m in meta.items()}


_built: dict[tuple, MapGeo | None] = {}


def geo(map_name: str, demos: list[DemoData] | None = None) -> MapGeo | None:
    """La geografía guardada del mapa; si no hay, la arma con `demos` (las del mismo mapa) y la recuerda."""
    g = _stored().get(map_name)
    if g is not None or not demos:
        return g
    same = [d for d in demos if d.meta["map"] == map_name]
    key = (map_name, tuple(sorted(d.demo_id for d in same)))
    if key not in _built:
        _built[key] = build(same)
    return _built[key]
