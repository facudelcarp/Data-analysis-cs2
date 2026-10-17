"""Línea de comandos.

    cs2a app [--demos CARPETA]          abre la app web
    cs2a stats partida.dem              scoreboard en la terminal
    cs2a export partida.dem -o salida   exporta todas las tablas (crudas + traducidas + stats) a CSV/Parquet
    cs2a export carpeta/ -o salida      idem para todas las demos de una carpeta (+ leaderboard agregado)
"""
from __future__ import annotations

import argparse
import subprocess
import unicodedata
import sys
from pathlib import Path

import pandas as pd


def _paths(target: str) -> list[Path]:
    p = Path(target).expanduser()
    if p.is_dir():
        from .multi import find_demos
        return find_demos(p)
    return [p]


def cmd_stats(args) -> int:
    from . import stats
    from .parser import DEFAULT_CACHE_DIR, load_demo
    from .ui.common import SCOREBOARD_COLS, STAT_LABELS
    cache = None if args.no_cache else (Path(args.cache) if args.cache else DEFAULT_CACHE_DIR)
    d = load_demo(args.demo, cache_dir=cache)
    m = d.meta
    print(f"{m['map']}  {m['team_a']} {m['score_a']} - {m['score_b']} {m['team_b']}  ({m['rounds']} rondas)")
    ps = stats.player_stats(d)
    cols = ["team_name"] + SCOREBOARD_COLS
    with pd.option_context("display.width", 250, "display.max_columns", 50):
        print(ps[cols].rename(columns=STAT_LABELS).to_string(index=False))
    return 0


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
    e.add_argument("target", help="archivo .dem o carpeta")
    e.add_argument("-o", "--out", default="exports")
    e.add_argument("-f", "--format", choices=["csv", "parquet", "both"], default="csv")
    e.add_argument("-w", "--workers", type=int, default=4)
    e.add_argument("--no-cache", action="store_true")
    e.set_defaults(fn=cmd_export)

    a = sub.add_parser("app", help="abrir la app web")
    a.add_argument("--demos", help="carpeta a precargar")
    a.set_defaults(fn=cmd_app)

    args = ap.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    raise SystemExit(main())
