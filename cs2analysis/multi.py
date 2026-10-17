"""Análisis sobre varias demos: biblioteca, leaderboard agregado, tendencias y mapas."""
from __future__ import annotations

from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable

import numpy as np
import pandas as pd

from . import stats
from .parser import DEFAULT_CACHE_DIR, DemoData, load_demo


def find_demos(folder: str | Path) -> list[Path]:
    """Demos (.dem) y archivos ya analizados (.cs2a) dentro de una carpeta, recursivo."""
    folder = Path(folder).expanduser()
    return sorted([*folder.rglob("*.dem"), *folder.rglob("*.cs2a")])


def _load(path: str, cache_dir: str | None) -> tuple[list[DemoData], str | None]:
    try:
        if path.endswith(".cs2a"):
            from .storage import read_cs2a
            return read_cs2a(path), None
        return [load_demo(path, cache_dir=Path(cache_dir) if cache_dir else None)], None
    except Exception as exc:  # una demo rota no debería tirar abajo toda la biblioteca
        return [], f"{Path(path).name}: {exc}"


def load_many(paths: Iterable[str | Path], cache_dir: Path | None = DEFAULT_CACHE_DIR, workers: int = 4,
              progress: Callable[[int, int], None] | None = None) -> tuple[list[DemoData], list[str]]:
    """Carga .dem (parseando o desde caché) y .cs2a. Una demo repetida (mismo id) se carga una vez."""
    paths = [str(p) for p in paths]
    found: dict[str, DemoData] = {}
    errors = []
    cache = str(cache_dir) if cache_dir else None

    def collect(result, i):
        ds, err = result
        for d in ds:
            found.setdefault(d.demo_id, d)
        if err:
            errors.append(err)
        if progress:
            progress(i, len(paths))

    if workers <= 1 or len(paths) <= 1:
        for i, p in enumerate(paths, 1):
            collect(_load(p, cache), i)
    else:
        with ProcessPoolExecutor(max_workers=workers) as pool:
            futs = [pool.submit(_load, p, cache) for p in paths]
            for i, f in enumerate(as_completed(futs), 1):
                collect(f.result(), i)
    return list(found.values()), errors


@dataclass
class Library:
    """Conjunto de demos con las tablas por ronda ya concatenadas."""
    demos: list[DemoData]

    def __post_init__(self):
        self.demos = sorted(self.demos, key=lambda d: d.meta["file_mtime"])
        self.by_id = {d.demo_id: d for d in self.demos}
        prs, cls, accs = [], [], []
        for d in self.demos:
            pr = stats.player_rounds(d)
            pr["date"] = d.meta["file_mtime"]
            prs.append(pr)
            cls.append(stats.clutches(d))
            acc = stats.shots_hits(d)
            acc["demo_id"] = d.demo_id
            accs.append(acc)
        self.player_rounds = pd.concat(prs, ignore_index=True) if prs else pd.DataFrame()
        self.clutches = pd.concat(cls, ignore_index=True) if cls else pd.DataFrame()
        self.accuracy = pd.concat(accs, ignore_index=True) if accs else pd.DataFrame()

    def __len__(self):
        return len(self.demos)

    def matches(self) -> pd.DataFrame:
        rows = []
        for d in self.demos:
            m = d.meta
            rows.append({"demo_id": m["demo_id"], "Fecha": m["file_mtime"][:16].replace("T", " "),
                         "Mapa": m["map"], "Equipo A": m["team_a"], "Equipo B": m["team_b"],
                         "Marcador": f"{m['score_a']} - {m['score_b']}", "Rondas": m["rounds"],
                         "Duración (min)": m["duration_min"], "Archivo": m["file_name"]})
        return pd.DataFrame(rows)

    def players(self) -> pd.DataFrame:
        """Todos los jugadores vistos, con el nombre más reciente y cantidad de demos."""
        pr = self.player_rounds
        if pr.empty:
            return pd.DataFrame(columns=["steamid", "name", "demos", "rounds"])
        last = pr.sort_values("date").groupby("steamid").last()["name"]
        out = pr.groupby("steamid").agg(demos=("demo_id", "nunique"), rounds=("round", "size"))
        out.insert(0, "name", last)
        return out.reset_index().sort_values(["demos", "rounds"], ascending=False)

    def leaderboard(self, min_rounds: int = 0, maps: list[str] | None = None) -> pd.DataFrame:
        pr, cl, acc = self.player_rounds, self.clutches, self.accuracy
        if maps:
            ids = {d.demo_id for d in self.demos if d.meta["map"] in maps}
            pr, cl, acc = pr[pr["demo_id"].isin(ids)], cl[cl["demo_id"].isin(ids)], acc[acc["demo_id"].isin(ids)]
        s = stats.aggregate(pr, cl, acc)
        if s.empty:
            return s
        s = s.drop(columns=["team"])
        last = pr.sort_values("date").groupby("steamid").last()["name"]
        s["name"] = s["steamid"].map(last)
        return s[s["rounds"] >= min_rounds].reset_index(drop=True)

    def per_demo(self, steamid: str) -> pd.DataFrame:
        """Línea de tiempo de un jugador: una fila por demo con sus métricas clave."""
        pr = self.player_rounds[self.player_rounds["steamid"] == steamid]
        if pr.empty:
            return pd.DataFrame()
        cl = self.clutches[self.clutches["steamid"] == steamid]
        acc = self.accuracy[self.accuracy["steamid"] == steamid]
        s = stats.aggregate(pr, cl, acc, by=["demo_id", "steamid"])
        meta = self.matches().set_index("demo_id")
        s = s.join(meta, on="demo_id")
        won = {}
        s["Marcador propio"] = ""
        for d in self.demos:
            team = d.players.set_index("steamid")["team"].get(steamid)
            if team is None:
                continue
            a, b = d.meta["score_a"], d.meta["score_b"]
            mine, theirs = (a, b) if team == "A" else (b, a)
            won[d.demo_id] = "Victoria" if mine > theirs else ("Derrota" if mine < theirs else "Empate")
            s.loc[s["demo_id"] == d.demo_id, "Marcador propio"] = f"{mine} - {theirs}"
        s["Resultado"] = s["demo_id"].map(won)
        return s.sort_values("Fecha").reset_index(drop=True)

    def map_summary(self, steamid: str | None = None) -> pd.DataFrame:
        """Partidas y winrate por mapa (del jugador foco si se indica, si no: conteo general)."""
        rows = []
        for d in self.demos:
            row = {"Mapa": d.meta["map"], "Rondas": d.meta["rounds"]}
            if steamid:
                team = d.players.set_index("steamid")["team"].get(steamid)
                if team is None:
                    continue
                a, b = d.meta["score_a"], d.meta["score_b"]
                mine, theirs = (a, b) if team == "A" else (b, a)
                row.update({"Victoria": int(mine > theirs), "Rondas ganadas": mine, "Rondas perdidas": theirs})
                side = d.rounds
                row["Rondas CT ganadas"] = int(((side["ct_team"] == team) & (side["winner_team"] == team)).sum())
                row["Rondas CT"] = int((side["ct_team"] == team).sum())
                row["Rondas T ganadas"] = int(((side["t_team"] == team) & (side["winner_team"] == team)).sum())
                row["Rondas T"] = int((side["t_team"] == team).sum())
            rows.append(row)
        df = pd.DataFrame(rows)
        if df.empty:
            return df
        g = df.groupby("Mapa")
        out = g.size().rename("Partidas").to_frame()
        if steamid:
            sums = g.sum(numeric_only=True)
            out["Victorias"] = sums["Victoria"]
            out["Winrate %"] = (100 * sums["Victoria"] / out["Partidas"]).round(1)
            out["% rondas CT"] = (100 * sums["Rondas CT ganadas"] / sums["Rondas CT"].replace(0, np.nan)).round(1)
            out["% rondas T"] = (100 * sums["Rondas T ganadas"] / sums["Rondas T"].replace(0, np.nan)).round(1)
        else:
            out["Rondas promedio"] = g["Rondas"].mean().round(1)
        return out.reset_index().sort_values("Partidas", ascending=False)

    def concat(self, table: str) -> pd.DataFrame:
        """Concatena una tabla cruda de todas las demos agregando demo_id y mapa."""
        frames = []
        for d in self.demos:
            t = getattr(d, table).copy()
            t.insert(0, "demo_id", d.demo_id)
            t.insert(1, "map", d.meta["map"])
            frames.append(t)
        return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
