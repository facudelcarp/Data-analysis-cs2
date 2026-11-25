"""Arranque de la app nativa."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from PySide6.QtWidgets import QApplication

from ..multi import find_demos
from . import style
from .window import MainWindow


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="cs2a-desktop", description="CS2 Data Analysis (app nativa)")
    ap.add_argument("files", nargs="*", help="demos (.dem) o análisis (.cs2a) para abrir al iniciar")
    ap.add_argument("--demos", help="carpeta para precargar")
    args = ap.parse_args(sys.argv[1:] if argv is None else argv)

    app = QApplication.instance() or QApplication(sys.argv[:1])
    app.setApplicationName("CS2 Data Analysis")
    style.apply(app)
    win = MainWindow()
    paths = [Path(f) for f in args.files] + (find_demos(args.demos) if args.demos else [])
    if paths:
        win.add_paths(paths)
    win.show()
    return app.exec()
