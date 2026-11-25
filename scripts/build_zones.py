"""Arma assets/zones/geo.npz: sitios, spawns y grilla de zonas de cada mapa (ver cs2analysis/zones.py).

    python scripts/build_zones.py carpeta_con_demos/ [más carpetas o archivos]
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from cs2analysis import zones  # noqa: E402
from cs2analysis.multi import find_demos, load_many  # noqa: E402


def main(targets: list[str]) -> None:
    paths = []
    for t in targets:
        p = Path(t)
        paths += find_demos(p) if p.is_dir() else [p]
    demos, errors = load_many(paths)
    print(f"{len(demos)} partidas", *errors, sep="\n")
    by_map: dict[str, list] = {}
    for d in demos:
        by_map.setdefault(d.meta["map"], []).append(d)
    geos = dict(zones._stored())  # se conservan los mapas que no vienen en esta tanda
    for mp, ds in sorted(by_map.items()):
        g = zones.build(ds)
        if g is None:
            print(f"{mp}: no alcanza (hacen falta plantes en A y en B)")
            continue
        known = (g.grid >= 0).mean()
        print(f"{mp}: {len(ds)} partidas, {len(g.places)} zonas, A-B {g.d_ab:.0f} u, grilla {g.grid.shape} "
              f"({known:.0%} de celdas con zona)")
        geos[mp] = g
    zones.save(geos)
    print("->", zones.GEO_FILE)


if __name__ == "__main__":
    main(sys.argv[1:])
