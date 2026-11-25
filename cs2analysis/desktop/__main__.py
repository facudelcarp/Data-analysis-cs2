"""python -m cs2analysis.desktop [--demos CARPETA] [ARCHIVOS...]"""
import multiprocessing

from .app import main

if __name__ == "__main__":
    multiprocessing.freeze_support()  # el .exe empaquetado carga demos en paralelo con procesos
    raise SystemExit(main())
