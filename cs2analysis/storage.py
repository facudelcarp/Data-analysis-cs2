"""Formato de archivo `.cs2a`: una o varias demos ya analizadas en un solo archivo compacto.

Una demo de 500 MB queda en ~300 KB, y la app la puede abrir sin el .dem original.

Estructura (versión 1)::

    biblioteca.cs2a            ZIP sin recompresión (los miembros ya vienen comprimidos)
    ├── cs2a.json              índice: formato, versión, demos (meta + filas por tabla)
    └── demos/<demo_id>/<tabla>.parquet

No es un formato binario propio a propósito: cualquier herramienta abre un .cs2a
(`unzip`, y después pandas/polars/DuckDB/Spark leen los Parquet). Lo compacto sale de:

- Parquet + zstd nivel 19, con codificación por diccionario para los textos (nombres, armas, zonas).
- Tipos reducidos: enteros al ancho mínimo (int8 a int32) y floats a float32.
- Posiciones cuantizadas a int16 (1 unidad del juego, unos 2.5 cm), ordenadas por jugador y tick,
  con DELTA_BINARY_PACKED: las trayectorias son continuas, así que las diferencias son chicas.
  Esto solo baja la tabla más pesada de ~720 KB a ~135 KB.
"""
from __future__ import annotations

import io
import json
import zipfile
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

FORMAT = "cs2a"
FORMAT_VERSION = 1
INDEX = "cs2a.json"
ZSTD_LEVEL = 19
QUANTIZED = {"positions": ["x", "y", "z"]}
SORT_KEYS = {"positions": ["steamid", "tick"]}
DELTA_COLUMNS = {"tick", "x", "y", "z", "throw_tick"}


def _downcast(df: pd.DataFrame, table: str) -> pd.DataFrame:
    df = df.copy()
    for c in QUANTIZED.get(table, []):
        if c in df:
            df[c] = df[c].round().clip(-32768, 32767).astype("int16")
    for c in df.columns:
        s = df[c]
        if pd.api.types.is_bool_dtype(s):
            continue
        if pd.api.types.is_integer_dtype(s) and not isinstance(s.dtype, pd.CategoricalDtype):
            if s.isna().any():
                continue
            df[c] = pd.to_numeric(s, downcast="integer")
        elif pd.api.types.is_float_dtype(s):
            df[c] = s.astype("float32")
    keys = [k for k in SORT_KEYS.get(table, []) if k in df]
    if keys:
        df = df.sort_values(keys, kind="stable").reset_index(drop=True)
    return df


def _parquet_bytes(df: pd.DataFrame) -> bytes:
    table = pa.Table.from_pandas(df, preserve_index=False)
    delta = {}
    for f in table.schema:
        if f.name in DELTA_COLUMNS and pa.types.is_integer(f.type):
            delta[f.name] = "DELTA_BINARY_PACKED"
    buf = io.BytesIO()
    pq.write_table(table, buf, compression="zstd", compression_level=ZSTD_LEVEL,
                   use_dictionary=[f.name for f in table.schema if f.name not in delta],
                   column_encoding=delta or None)
    return buf.getvalue()


def _restore(df: pd.DataFrame, table: str) -> pd.DataFrame:
    for c in QUANTIZED.get(table, []):
        if c in df:
            df[c] = df[c].astype("float32")
    if table in SORT_KEYS and "tick" in df:
        df = df.sort_values(["tick", "steamid"], kind="stable").reset_index(drop=True)
    return df


def write_cs2a(path: str | Path, demos: list) -> Path:
    """Guarda una lista de DemoData en un único .cs2a."""
    from .parser import CACHE_VERSION, TABLES
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    index = {"format": FORMAT, "version": FORMAT_VERSION, "analysis_version": CACHE_VERSION,
             "created": datetime.now(timezone.utc).isoformat(timespec="seconds"), "demos": []}
    tmp = path.with_suffix(path.suffix + ".tmp")
    with zipfile.ZipFile(tmp, "w", compression=zipfile.ZIP_STORED) as z:
        for d in demos:
            entry = {"id": d.demo_id, "meta": d.meta, "tables": {}}
            for t in TABLES:
                df = getattr(d, t)
                data = _parquet_bytes(_downcast(df, t))
                z.writestr(f"demos/{d.demo_id}/{t}.parquet", data)
                entry["tables"][t] = {"rows": int(len(df)), "bytes": len(data)}
            index["demos"].append(entry)
        z.writestr(INDEX, json.dumps(index, ensure_ascii=False, indent=1, default=str))
    tmp.replace(path)  # escritura atómica: nunca queda un .cs2a a medio escribir
    return path


def read_index(path: str | Path) -> dict:
    with zipfile.ZipFile(path) as z:
        index = json.loads(z.read(INDEX))
    if index.get("format") != FORMAT:
        raise ValueError(f"{path}: no es un archivo .cs2a")
    if index.get("version", 0) > FORMAT_VERSION:
        raise ValueError(f"{path}: versión {index['version']} del formato, esta herramienta lee hasta {FORMAT_VERSION}")
    return index


def read_cs2a(path: str | Path, ids: list[str] | None = None) -> list:
    """Lee las demos de un .cs2a (todas, o solo las de `ids`)."""
    from .parser import TABLES, DemoData
    index = read_index(path)
    out = []
    with zipfile.ZipFile(path) as z:
        names = set(z.namelist())
        for entry in index["demos"]:
            if ids and entry["id"] not in ids:
                continue
            tables = {}
            for t in TABLES:
                member = f"demos/{entry['id']}/{t}.parquet"
                if member in names:
                    tables[t] = _restore(pq.read_table(io.BytesIO(z.read(member))).to_pandas(), t)
                else:  # tablas agregadas en versiones posteriores del análisis
                    tables[t] = pd.DataFrame()
            out.append(DemoData(meta=dict(entry["meta"]), **tables))
    return out


def summary(path: str | Path) -> pd.DataFrame:
    """Contenido de un .cs2a sin cargar las tablas."""
    index = read_index(path)
    rows = []
    for e in index["demos"]:
        m = e["meta"]
        rows.append({"demo_id": e["id"], "mapa": m.get("map"), "marcador": f"{m.get('score_a')}-{m.get('score_b')}",
                     "equipos": f"{m.get('team_a')} vs {m.get('team_b')}", "rondas": m.get("rounds"),
                     "archivo original": m.get("file_name"), "MB originales": m.get("file_size_mb"),
                     "KB en .cs2a": round(sum(t["bytes"] for t in e["tables"].values()) / 1000, 1)})
    return pd.DataFrame(rows)


def compression_ratio(path: str | Path) -> float:
    s = summary(path)
    if s.empty:
        return float("nan")
    return float(np.nansum(s["MB originales"]) * 1000 / max(s["KB en .cs2a"].sum(), 1e-9))
