"""Punto de entrada del ejecutable (PyInstaller no arranca paquetes con -m)."""
import multiprocessing
import sys

from cs2analysis.desktop.app import main

if __name__ == "__main__":
    multiprocessing.freeze_support()  # la carga en paralelo usa procesos: sin esto el .exe se relanza a sí mismo
    sys.exit(main())
