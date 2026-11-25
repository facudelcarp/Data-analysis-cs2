"""Etiquetas de estrategia puestas a mano (en el replay), para medir qué tan bien acierta strategy.py.

Un JSON en la carpeta de configuración del usuario (al lado de prefs.json): {demo_id: {ronda: {campo: valor}}}.
Los campos son los mismos que calcula strategy.py, así la comparación es directa."""
from __future__ import annotations

import json

import pandas as pd

from .prefs import prefs_path

# campo -> (pregunta, opciones). '' = no sé / no aplica (no cuenta para el acuerdo)
FIELDS = {
    "t_opening": ("Apertura T", ["Default", "Agrupados A", "Agrupados Mid", "Agrupados B", "Control A", "Control Mid",
                                 "Control B", "Lento"]),
    "t_kind": ("Golpe T", ["Rush", "Execute", "Golpe con poca utilidad", "Sin golpe", "Pick temprano, sin golpe",
                           "Cayó en la apertura", "Guardó", "Eco / guardado"]),
    "t_site": ("Sitio del golpe", ["A", "B"]),
    "t_split": ("Split", ["Sí", "No"]),
    "t_fake": ("Fake previo", ["Sí", "No"]),
    "ct_stack": ("Stack CT", ["A", "B", "No"]),
    "ct_aggression": ("Agresión CT temprana", ["Sí", "No"]),
    "ct_retake": ("CT al plante", ["Retake", "Defendieron dentro", "No hubo plante"]),
}


def _path():
    return prefs_path().with_name("strategy_labels.json")


def load() -> dict:
    try:
        return json.loads(_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def get(demo_id: str, rnd: int) -> dict:
    return load().get(demo_id, {}).get(str(rnd), {})


def put(demo_id: str, rnd: int, values: dict) -> None:
    data = load()
    clean = {k: v for k, v in values.items() if v}
    rounds = data.setdefault(demo_id, {})
    if clean:
        rounds[str(rnd)] = clean
    else:
        rounds.pop(str(rnd), None)
    path = _path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")


def predicted_value(field: str, row: pd.Series) -> str:
    """El valor de strategy.py en el mismo formato que la etiqueta."""
    if field in ("t_split",):
        return "Sí" if bool(row.get(field)) else "No"
    if field == "t_fake":
        return "Sí" if row.get("t_fake") else "No"
    if field == "ct_stack":
        return row.get("ct_stack") or "No"
    if field == "ct_aggression":
        return "Sí" if row.get("ct_aggression") else "No"
    if field == "ct_retake":
        resp = str(row.get("ct_response", ""))
        return "Retake" if "retake" in resp else "Defendieron dentro" if "defendieron" in resp else "No hubo plante"
    return str(row.get(field) or "")


def agreement(strategies: dict[str, pd.DataFrame]) -> pd.DataFrame:
    """Acuerdo por campo entre las etiquetas y strategy.py. `strategies`: demo_id -> round_strategies(d)."""
    labels = load()
    rows = []
    for demo_id, rounds in labels.items():
        s = strategies.get(demo_id)
        if s is None or s.empty:
            continue
        s = s.set_index("round")
        for rnd, lab in rounds.items():
            if int(rnd) not in s.index:
                continue
            row = s.loc[int(rnd)]
            for f, v in lab.items():
                if f in FIELDS and v:
                    rows.append({"field": f, "label": v, "pred": predicted_value(f, row)})
    df = pd.DataFrame(rows, columns=["field", "label", "pred"])
    if df.empty:
        return pd.DataFrame(columns=["Campo", "Rondas", "Acuerdo %"])
    df["ok"] = df["label"] == df["pred"]
    out = df.groupby("field").agg(Rondas=("ok", "size"), acuerdo=("ok", "mean")).reset_index()
    out["Campo"] = out["field"].map(lambda f: FIELDS[f][0])
    out["Acuerdo %"] = (100 * out["acuerdo"]).round(0)
    return out[["Campo", "Rondas", "Acuerdo %"]]
