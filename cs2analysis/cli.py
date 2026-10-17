"""Línea de comandos.

    cs2a app [--demos CARPETA]          abre la app web
    cs2a stats partida.dem              scoreboard en la terminal
    cs2a export partida.dem -o salida   exporta todas las tablas (crudas + traducidas + stats) a CSV/Parquet
    cs2a export carpeta/ -o salida      idem para todas las demos de una carpeta (+ leaderboard agregado)
    cs2a pack carpeta/ -o lib.cs2a      empaqueta demos analizadas en un único archivo compacto
    cs2a info lib.cs2a                  qué hay adentro de un .cs2a
    cs2a radars                         descarga las imágenes de radar a assets/radars/
    cs2a assets [mapas…]                radares + mallas de colisión (línea de visión para stats de aim)

Donde se acepta una demo también se acepta un .cs2a.
"""
from __future__ import annotations

import argparse
import subprocess
import unicodedata
import sys
from pathlib import Path

import pandas as pd


def _paths(*targets: str) -> list[Path]:
    from .multi import find_demos
    out = []
    for target in targets:
        p = Path(target).expanduser()
        out += find_demos(p) if p.is_dir() else [p]
    return out


def cmd_stats(args) -> int:
    from . import stats
    from .multi import load_many
    from .parser import DEFAULT_CACHE_DIR
    from .labels import SCOREBOARD_COLS, STAT_LABELS
    cache = None if args.no_cache else (Path(args.cache) if args.cache else DEFAULT_CACHE_DIR)
    demos, errors = load_many([args.demo], cache_dir=cache, workers=1)
    if errors:
        print("ERROR", errors[0], file=sys.stderr)
        return 1
    for d in demos:
        _print_scoreboard(d, stats, SCOREBOARD_COLS, STAT_LABELS)
    return 0


def _print_scoreboard(d, stats, cols_base, labels) -> None:
    m = d.meta
    print(f"{m['map']}  {m['team_a']} {m['score_a']} - {m['score_b']} {m['team_b']}  ({m['rounds']} rondas)")
    ps = stats.player_stats(d)
    cols = ["team_name"] + cols_base
    with pd.option_context("display.width", 250, "display.max_columns", 50):
        print(ps[cols].rename(columns=labels).to_string(index=False))


def _write(df: pd.DataFrame, path: Path, fmt: str) -> None:
    if fmt in ("csv", "both"):
        df.to_csv(path.with_suffix(".csv"), index=False)
    if fmt in ("parquet", "both"):
        df.to_parquet(path.with_suffix(".parquet"), index=False)


def cmd_export(args) -> int:
    from . import stats, translate
    from .multi import Library, load_many
    from .parser import DEFAULT_CACHE_DIR, TABLES
    paths = _paths(args.target)
    demos, errors = load_many(paths, cache_dir=None if args.no_cache else DEFAULT_CACHE_DIR, workers=args.workers)
    for e in errors:
        print("ERROR", e, file=sys.stderr)
    out = Path(args.out)
    for d in demos:
        base = out / f"{Path(d.meta['file_name']).stem}_{d.demo_id[:6]}"
        (base / "crudo").mkdir(parents=True, exist_ok=True)
        (base / "traducido").mkdir(parents=True, exist_ok=True)
        for t in TABLES:
            _write(getattr(d, t), base / "crudo" / t, args.format)
        for name, fn in translate.TABLES.items():
            slug = unicodedata.normalize("NFKD", name.split()[0].lower()).encode("ascii", "ignore").decode()
            _write(fn(d), base / "traducido" / slug, args.format)
        _write(stats.player_stats(d), base / "estadisticas_jugadores", args.format)
        _write(stats.weapon_stats(d), base / "estadisticas_armas", args.format)
        print(f"✔ {d.meta['file_name']} → {base}")
    if len(demos) > 1:
        lib = Library(demos)
        _write(lib.leaderboard(), out / "leaderboard", args.format)
        _write(lib.matches(), out / "partidas", args.format)
        print(f"✔ leaderboard agregado de {len(demos)} demos → {out}")
    return 1 if errors and not demos else 0


def cmd_pack(args) -> int:
    from .multi import load_many
    from .parser import DEFAULT_CACHE_DIR
    from .storage import compression_ratio, write_cs2a
    demos, errors = load_many(_paths(*args.targets), cache_dir=None if args.no_cache else DEFAULT_CACHE_DIR,
                              workers=args.workers)
    for e in errors:
        print("ERROR", e, file=sys.stderr)
    if not demos:
        return 1
    out = write_cs2a(args.out, demos)
    print(f"✔ {len(demos)} demo(s) → {out} ({out.stat().st_size / 1000:.0f} KB, {compression_ratio(out):.0f}x más chico)")
    return 0


def cmd_info(args) -> int:
    from .storage import read_index, summary
    idx = read_index(args.file)
    print(f"{args.file}: formato {idx['format']} v{idx['version']} · análisis v{idx.get('analysis_version')} · "
          f"creado {idx.get('created')}")
    with pd.option_context("display.width", 250, "display.max_columns", 20):
        print(summary(args.file).to_string(index=False))
    return 0


def cmd_radars(args) -> int:
    from .maps import RADAR_DIR, download_radars
    files = download_radars(Path(args.dest) if args.dest else RADAR_DIR)
    print(f"✔ {len(files)} radares en {files[0].parent if files else args.dest}")
    return 0


def cmd_assets(args) -> int:
    """Radares + mallas de colisión (para línea de visión en las stats de aim)."""
    from .geometry import MESH_DIR, download_geometry
    cmd_radars(argparse.Namespace(dest=None))
    meshes = download_geometry(MESH_DIR, maps=args.maps or None)
    print(f"✔ {len(meshes)} mallas en {MESH_DIR}. Las demos ya cacheadas sin malla se recalculan con `--no-cache` "
          "o borrando la caché.")
    return 0


def cmd_app(args) -> int:
    app = Path(__file__).resolve().parent.parent / "app.py"
    cmd = [sys.executable, "-m", "streamlit", "run", str(app)]
    if args.demos:
        cmd += ["--", "--demos", args.demos]
    return subprocess.call(cmd)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="cs2a", description="Data analysis de demos de CS2")
    sub = ap.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("stats", help="scoreboard de una demo")
    s.add_argument("demo")
    s.add_argument("--cache", default=None)
    s.add_argument("--no-cache", action="store_true")
    s.set_defaults(fn=cmd_stats)

    e = sub.add_parser("export", help="exportar tablas a CSV/Parquet")
    e.add_argument("target", help="archivo .dem / .cs2a o carpeta")
    e.add_argument("-o", "--out", default="exports")
    e.add_argument("-f", "--format", choices=["csv", "parquet", "both"], default="csv")
    e.add_argument("-w", "--workers", type=int, default=4)
    e.add_argument("--no-cache", action="store_true")
    e.set_defaults(fn=cmd_export)

    pk = sub.add_parser("pack", help="empaquetar demos en un .cs2a")
    pk.add_argument("targets", nargs="+", help=".dem, .cs2a o carpetas")
    pk.add_argument("-o", "--out", required=True)
    pk.add_argument("-w", "--workers", type=int, default=4)
    pk.add_argument("--no-cache", action="store_true")
    pk.set_defaults(fn=cmd_pack)

    inf = sub.add_parser("info", help="contenido de un .cs2a")
    inf.add_argument("file")
    inf.set_defaults(fn=cmd_info)

    r = sub.add_parser("radars", help="descargar imágenes de radar (awpy-data)")
    r.add_argument("--dest", default=None)
    r.set_defaults(fn=cmd_radars)

    asx = sub.add_parser("assets", help="descargar radares y mallas de colisión (awpy-data)")
    asx.add_argument("maps", nargs="*", help="solo estos mapas (p. ej. de_mirage de_inferno)")
    asx.set_defaults(fn=cmd_assets)

    a = sub.add_parser("app", help="abrir la app web")
    a.add_argument("--demos", help="carpeta a precargar")
    a.set_defaults(fn=cmd_app)

    args = ap.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    raise SystemExit(main())
