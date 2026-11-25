"""Preferencias del usuario que sobreviven entre sesiones (por ahora: quién es "yo").

Un JSON chico en la carpeta de configuración del usuario; CS2A_PREFS permite elegir otro archivo (tests)."""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path


def prefs_path() -> Path:
    if os.environ.get("CS2A_PREFS"):
        return Path(os.environ["CS2A_PREFS"])
    if sys.platform == "win32" and os.environ.get("APPDATA"):
        return Path(os.environ["APPDATA"]) / "cs2analysis" / "prefs.json"
    return Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "cs2analysis" / "prefs.json"


def load() -> dict:
    try:
        return json.loads(prefs_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def save(data: dict) -> None:
    path = prefs_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    except OSError:  # carpeta de solo lectura: la preferencia vale solo esta sesión
        pass


def me() -> str | None:
    """steamid del usuario de la app, si lo marcó."""
    return load().get("me") or None


def set_me(steamid: str | None) -> None:
    data = load()
    if steamid:
        data["me"] = str(steamid)
    else:
        data.pop("me", None)
    save(data)
