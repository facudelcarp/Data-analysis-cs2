"""Arma assets/positions/templates.npz: las plantillas de cada puesto (mapa x lado) para cs2analysis.positions.

Necesita partidas profesionales (.dem / .cs2a) y la base de NER0 (scripts/fetch_ner0.py). Cada jugador de las
partidas se busca por nick en la base; su puesto ahí es la etiqueta. Antes de guardar, valida dejando cada equipo
afuera: arma las plantillas sin ese equipo y mide cuántos puestos de ese equipo acierta.

    python scripts/fetch_ner0.py
    python scripts/build_position_templates.py partidas_pro/ [más carpetas o archivos]
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from cs2analysis import ner0, positions  # noqa: E402
from cs2analysis.multi import find_demos, load_many  # noqa: E402

MIN_EXAMPLES = 40  # por mapa y lado: con menos, las plantillas no alcanzan
Z_SPLIT = {"de_nuke": -495.0, "de_vertigo": 11700.0, "de_train": -50.0}


def family(team: str) -> str:
    """"9z", "9Z", "9z Team" y "9z Globant" son el mismo equipo: se dejan afuera juntos al validar."""
    t = ner0.norm_name(team)
    for w in ("team", "globant", "gaming", "esports", "clan"):
        t = t.replace(w, "")
    return t


def grids(demos) -> dict[str, dict]:
    out = {}
    for d in demos:
        p = d.positions
        if p.empty:
            continue
        g = out.setdefault(d.meta["map"], [np.inf, -np.inf, np.inf, -np.inf])
        g[:] = [min(g[0], p.x.min()), max(g[1], p.x.max()), min(g[2], p.y.min()), max(g[3], p.y.max())]
    res = {}
    for mp, (x0, x1, y0, y1) in out.items():
        mx, my = 0.02 * (x1 - x0), 0.02 * (y1 - y0)
        res[mp] = {"x": (float(x0 - mx), float(x1 + mx)), "y": (float(y0 - my), float(y1 + my)),
                   "z_split": Z_SPLIT.get(mp)}
    return res


def role_weights(players: pd.DataFrame, pos: pd.DataFrame) -> dict[tuple[str, str], dict[str, float]]:
    """Peso de cada puesto, reconstruido de la base: el puntaje de rol de NER0 es el promedio de los pesos de los
    puestos de cada jugador (R² ~0.96 en CT y ~0.98 en T con un ajuste lineal)."""
    out = {}
    for side, col in (("CT", "ct_role_score"), ("T", "t_role_score")):
        p = pos[(pos["side"] == side) & (pos["position"] != "AWPer")]
        p = p.merge(players[["player_id", col]], on="player_id").dropna(subset=[col])
        x = pd.crosstab(p["player_id"], p["map"] + "|" + p["position"])
        x = x.div(x.sum(axis=1), axis=0)
        y = players.set_index("player_id").loc[x.index, col].to_numpy(float)
        w, *_ = np.linalg.lstsq(x.to_numpy(float), y, rcond=None)
        for key, v in zip(x.columns, w, strict=True):
            mp, position = key.split("|", 1)
            out.setdefault((mp, side), {})[position] = round(float(np.clip(v, 0, 1)), 2)
    return out


def main(targets: list[str]) -> None:
    paths = []
    for t in targets:
        p = Path(t)
        paths += find_demos(p) if p.is_dir() else [p]
    demos, errors = load_many(paths)
    print(f"{len(demos)} partidas", *errors, sep="\n")
    players, pos = ner0.load()
    if players.empty:
        sys.exit("Falta la base de NER0: python scripts/fetch_ner0.py")
    pos = pos.assign(key=pos["name"].map(ner0.norm_name))
    grid = grids(demos)
    rows = []
    for d in demos:
        mp = d.meta["map"]
        pv = positions.player_vectors(d, grid[mp])
        if pv.empty:
            continue
        teams = d.players.set_index("steamid")["team_name"]
        rows.append(pv.assign(map=mp, demo=d.demo_id, key=pv["name"].map(ner0.norm_name),
                              fam=pv["steamid"].map(teams).map(family)))
    df = pd.concat(rows, ignore_index=True)
    df = df.merge(pos[["key", "map", "side", "position"]].drop_duplicates(["key", "map", "side"]),
                  on=["key", "map", "side"], how="left")
    weights = role_weights(players, pos)

    # ---- validación: cada equipo afuera
    hits, preds = [], []
    for (mp, side), g in df.groupby(["map", "side"]):
        for fam in g["fam"].unique():
            train = g[(g["fam"] != fam) & g["position"].notna()]
            if train.empty:
                continue
            labels = sorted(train["position"].unique())
            temp = np.stack([_mean(train[train["position"] == k]["v"]) for k in labels])
            for _, tg in g[g["fam"] == fam].groupby(["demo", "team"]):
                if len(tg) != 5:
                    continue
                s = positions.similarity(np.stack(tg["v"]), temp, labels, tg["share"].to_numpy(), tg["awp"].to_numpy())
                pick = positions._best_assignment(s)
                for i, (true, sid, key, rounds) in enumerate(zip(tg["position"], tg["steamid"], tg["key"],
                                                                 tg["rounds"], strict=True)):
                    pred = labels[pick[i]]
                    preds.append({"steamid": sid, "key": key, "map": mp, "side": side, "position": pred,
                                  "rounds": rounds, "weight": weights.get((mp, side), {}).get(pred, 0.5)})
                    if isinstance(true, str):
                        hits.append({"map": mp, "side": side, "hit": pred == true})
    hits = pd.DataFrame(hits)
    print(f"\nValidación (cada equipo afuera): {hits['hit'].mean():.1%} de puestos exactos en {len(hits)} casos")
    print(hits.groupby(["map", "side"])["hit"].agg(["mean", "size"]).round(2).to_string())
    validate_roles(pd.DataFrame(preds), players)

    # ---- plantillas finales, con todo
    maps: dict[str, positions.MapTemplates] = {}
    for (mp, side), g in df[df["position"].notna()].groupby(["map", "side"]):
        if len(g) < MIN_EXAMPLES:
            print(f"{mp} {side}: {len(g)} ejemplos, no alcanza (mínimo {MIN_EXAMPLES})")
            continue
        labels = sorted(g["position"].unique())
        t = maps.setdefault(mp, positions.MapTemplates(grid[mp], {}, {}, {}, {}))
        t.labels[side] = labels
        t.vectors[side] = np.stack([_mean(g[g["position"] == k]["v"]) for k in labels])
        t.weights[side] = {k: weights.get((mp, side), {}).get(k, 0.5) for k in labels if k != "AWPer"}
        t.support[side] = [int((g["position"] == k).sum()) for k in labels]
    maps = {mp: t for mp, t in maps.items() if set(t.labels) == {"CT", "T"}}
    positions.save_templates(maps, source=f"{len(demos)} partidas profesionales; etiquetas: base de NER0 (@NER0cs)")
    print(f"\nPlantillas: {', '.join(sorted(maps))} -> {positions.TEMPLATES}")


def validate_roles(preds: pd.DataFrame, players: pd.DataFrame) -> None:
    """Rol que sale de los puestos predichos (sin ver al equipo) contra el rol de NER0, en jugadores con 3+ mapas."""
    roles = positions.player_roles(preds)
    keys = preds.drop_duplicates("steamid").set_index("steamid")["key"]
    ref = players.assign(key=players["name"].map(ner0.norm_name)).drop_duplicates("key").set_index("key")
    rows = []
    for _, r in roles[roles["maps"] >= 3].iterrows():
        k = keys.get(r["steamid"])
        if k not in ref.index:
            continue
        col, score = ("ct_role", "ct_role_score") if r["side"] == "CT" else ("t_role", "t_role_score")
        true = ref.loc[k, col]
        if isinstance(true, str):
            rows.append({"side": r["side"], "true": true, "pred": r["role"], "score": r["score"],
                         "true_score": ref.loc[k, score]})
    v = pd.DataFrame(rows)
    if v.empty:
        return
    for side, g in v.groupby("side"):
        rifle = g[(g["true"] != "AWPer") & g["score"].notna()]
        corr = rifle[["score", "true_score"]].corr().iloc[0, 1] if len(rifle) > 2 else float("nan")
        print(f"\nRol {side}: {(g['true'] == g['pred']).mean():.1%} igual que NER0 en {len(g)} jugadores; "
              f"correlación del puntaje (sin AWPers) {corr:.2f}")
        print(pd.crosstab(g["true"], g["pred"]).to_string())


def _mean(vs) -> np.ndarray:
    m = np.mean(np.stack(list(vs)), axis=0)
    return m / max(np.linalg.norm(m), 1e-12)


if __name__ == "__main__":
    main(sys.argv[1:])
