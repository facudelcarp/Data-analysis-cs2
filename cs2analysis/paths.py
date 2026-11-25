"""Dónde viven los assets descargables (radares y mallas de colisión).

Desde el código fuente: `assets/` del repositorio, como siempre. Empaquetada (.exe de PyInstaller), la carpeta del
programa es de solo lectura, así que van a la carpeta del usuario. CS2A_ASSETS permite elegir otra."""
from __future__ import annotations

import os
import sys
from pathlib import Path


def assets_dir() -> Path:
    if os.environ.get("CS2A_ASSETS"):
        return Path(os.environ["CS2A_ASSETS"])
    if getattr(sys, "frozen", False):
        return Path.home() / ".cache" / "cs2analysis" / "assets"
    return Path(__file__).resolve().parent.parent / "assets"


ASSETS_DIR = assets_dir()
