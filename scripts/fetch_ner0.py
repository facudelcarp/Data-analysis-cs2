"""Descarga la base de posiciones de Harry "NER0" Richards (@NER0cs) y la guarda como Parquet.

Es la referencia pública más completa de qué posición juega cada profesional en cada mapa y lado, y qué rol
(Anchor / Rotator en CT, Lurker / Spacetaker en T, AWPer, IGL). La usamos para validar la clasificación de roles
por comportamiento: no se incluye en el repositorio (los datos son de su autor), se baja cuando se necesita.

    pip install tableauhyperapi      # solo para este script: lee el extracto de Tableau
    python scripts/fetch_ner0.py     # -> ~/.cache/cs2analysis/ner0/{players,positions}.parquet

Fuente: https://public.tableau.com/app/profile/harry.richards4213/viz/PositionsDatabaseNER0cs/PositionsDatabaseNER0cs
"""
from __future__ import annotations

import io
import re
import sys
import tempfile
import urllib.request
import zipfile
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from cs2analysis.ner0 import NER0_DIR  # noqa: E402

URL = "https://public.tableau.com/workbooks/PositionsDatabaseNER0cs.twb"
MAPS = ["Ancient", "Cache", "Mirage", "Anubis", "Inferno", "Nuke", "Dust2", "Overpass", "Train", "Vertigo"]


def read_extract(twbx: bytes) -> pd.DataFrame:
    from tableauhyperapi import Connection, HyperProcess, Telemetry
    with zipfile.ZipFile(io.BytesIO(twbx)) as z, tempfile.TemporaryDirectory() as tmp:
        name = next(n for n in z.namelist() if n.endswith(".hyper"))
        path = Path(tmp) / "db.hyper"
        path.write_bytes(z.read(name))
        with HyperProcess(Telemetry.DO_NOT_SEND_USAGE_DATA_TO_TABLEAU) as hp, Connection(hp.endpoint, str(path)) as c:
            table = next(t for s in c.catalog.get_schema_names() for t in c.catalog.get_table_names(s))
            cols = [col.name.unescaped for col in c.catalog.get_table_definition(table).columns]
            rows = c.execute_list_query(f"SELECT * FROM {table}")
    return pd.DataFrame(rows, columns=cols)


def tidy(raw: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    raw = raw[raw["Name"].notna()].copy()
    players = pd.DataFrame({
        "player_id": raw["playerID"].astype("Int64"), "name": raw["Name"], "team": raw["Team"],
        "country": raw["Country"], "age": raw["Age"], "igl": raw["IGL"].astype(bool),
        "role": raw["currentRole"], "ct_role": raw["CT Role"], "ct_role_score": raw["CT Score"],
        "t_role": raw["T Role"], "t_role_score": raw["T Score"], "last_update": raw["lastUpdate"],
    })
    rows = []
    maps = [m for m in MAPS if f"CT {m}" in raw.columns]
    for _, r in raw.iterrows():
        for m in maps:
            for side in ("CT", "T"):
                pos = r.get(f"{side} {m}")
                if pos is None or pd.isna(pos):
                    continue
                rating = pd.to_numeric(r.get(f"{side} {m} Last12"), errors="coerce")
                maps_played = pd.to_numeric(r.get(f"{side} {m} Last12 RP"), errors="coerce")
                rows.append({"player_id": r["playerID"], "name": r["Name"], "team": r["Team"],
                             "map": "de_" + m.lower(), "side": side, "position": str(pos),
                             "rating_last12": rating, "rounds_last12": maps_played})
    positions = pd.DataFrame(rows)
    positions["player_id"] = positions["player_id"].astype("Int64")
    return players, positions


def main() -> None:
    print("descargando la base de NER0…")
    data = urllib.request.urlopen(URL, timeout=60).read()
    players, positions = tidy(read_extract(data))
    NER0_DIR.mkdir(parents=True, exist_ok=True)
    players.to_parquet(NER0_DIR / "players.parquet", index=False)
    positions.to_parquet(NER0_DIR / "positions.parquet", index=False)
    upd = players["last_update"].dropna()
    print(f"{len(players)} jugadores, {len(positions)} posiciones (mapa x lado) -> {NER0_DIR}")
    print("última actualización de un jugador:", max(upd, key=lambda s: tuple(reversed(re.split(r'\D', s)))) if len(upd)
          else "?")


if __name__ == "__main__":
    main()
