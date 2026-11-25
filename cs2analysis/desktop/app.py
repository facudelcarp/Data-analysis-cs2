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
    ap.add_argument("files", nargs="*", help="demos (.dem), análisis (.cs2a) o carpetas para abrir al iniciar")
    ap.add_argument("--demos", help="carpeta para precargar")
    ap.add_argument("--smoke-test", action="store_true",
                    help="abre los archivos, arma todas las vistas y pestañas y sale (código 1 si algo falla)")
    args = ap.parse_args(sys.argv[1:] if argv is None else argv)

    app = QApplication.instance() or QApplication(sys.argv[:1])
    app.setApplicationName("CS2 Data Analysis")
    style.apply(app)
    win = MainWindow()
    win.headless = args.smoke_test
    paths = []
    for f in [*args.files, *([args.demos] if args.demos else [])]:
        f = Path(f).expanduser()
        paths += find_demos(f) if f.is_dir() else [f]  # carpetas o archivos sueltos
    if paths:
        win.add_paths(paths)
    win.show()
    if args.smoke_test:
        return smoke_test(app, win, [str(x) for x in paths])
    return app.exec()


def smoke_test(app: QApplication, win: MainWindow, files: list[str]) -> int:
    """Recorre toda la app sin intervención: sirve para probar el ejecutable empaquetado."""
    import faulthandler
    import os
    import time
    import traceback

    from .page import settle
    # La consola de Windows usa cp1252 (sin emojis) y un .exe sin consola puede no tener stdout: los mensajes del
    # test no pueden ser lo que lo haga fallar
    for name in ("stdout", "stderr"):
        stream = getattr(sys, name)
        if stream is None:
            setattr(sys, name, open(os.devnull, "w", encoding="utf-8"))
        elif hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    faulthandler.dump_traceback_later(240, exit=True)  # si algo se cuelga: muestra dónde y sale (nunca se tilda el CI)
    print("smoke-test: cargando…", flush=True)
    errors = []
    old_hook = sys.excepthook
    sys.excepthook = lambda *exc: errors.append("".join(traceback.format_exception(*exc)))  # errores en slots de Qt
    try:
        ok = win.loader.wait(300_000)
        errors += [f"carga: {e}" for e in win.load_errors]
        if not ok or not win.demos:
            print("smoke-test: no se cargó ninguna demo", *errors, sep="\n", file=sys.stderr)
            return 1
        # Lo que una .dem real necesita y un .cs2a no ejercita: el parser (Rust) y la carga en paralelo, que en el
        # ejecutable relanza el .exe como subproceso (freeze_support)
        from demoparser2 import DemoParser  # noqa: F401
        from ..multi import load_many
        cs2a = [f for f in files if f.endswith(".cs2a")]
        if cs2a:
            t0 = time.perf_counter()
            _, errs = load_many([cs2a[0], cs2a[0]], cache_dir=None, workers=2)  # dos archivos => pool de procesos
            errors += [f"carga en paralelo: {e}" for e in errs]
            print(f"smoke-test: carga en paralelo {'OK' if not errs else 'FALLÓ'} "
                  f"({time.perf_counter() - t0:.1f} s)", flush=True)
        for row in range(win.nav.count()):
            print(f"smoke-test: {win.nav.item(row).text()}", flush=True)
            win.nav.setCurrentRow(row)
            app.processEvents()
            settle(win.stack.currentWidget(), build_tabs=True)  # incluye lo que se calcula en segundo plano
    except Exception:
        errors.append(traceback.format_exc())
    finally:
        sys.excepthook = old_hook
        faulthandler.cancel_dump_traceback_later()
    for e in errors:
        print(e, file=sys.stderr)
    print(f"smoke-test: {len(win.demos)} demo(s), {win.nav.count()} vistas, {len(errors)} error(es)")
    return 1 if errors else 0
