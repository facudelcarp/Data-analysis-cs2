"""Referencia de posiciones y roles de profesionales (base pública de Harry "NER0" Richards).

Se baja con scripts/fetch_ner0.py; si no está, todo lo que la usa sigue funcionando sin ella."""
from __future__ import annotations

import re
import unicodedata
from pathlib import Path

import pandas as pd

from .parser import DEFAULT_CACHE_DIR

NER0_DIR = Path(DEFAULT_CACHE_DIR) / "ner0"


def available() -> bool:
    return (NER0_DIR / "players.parquet").exists()


def load() -> tuple[pd.DataFrame, pd.DataFrame]:
    """(jugadores, posiciones por mapa y lado). Vacíos si no se bajó la base."""
    if not available():
        return pd.DataFrame(), pd.DataFrame()
    return pd.read_parquet(NER0_DIR / "players.parquet"), pd.read_parquet(NER0_DIR / "positions.parquet")


def norm_name(name: str) -> str:
    """Nick comparable entre la base y las demos: sin mayúsculas, acentos, ni símbolos ("ZywOo" == "zywoo")."""
    s = unicodedata.normalize("NFKD", str(name)).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]", "", s.lower())
