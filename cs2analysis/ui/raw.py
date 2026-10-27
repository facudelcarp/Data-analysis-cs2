"""Vistas: datos crudos traducidos y datos crudos (tal cual los entrega demoparser2)."""
from __future__ import annotations

from pathlib import Path

import pandas as pd
import streamlit as st
from demoparser2 import DemoParser

from .. import translate
from ..parser import TABLES
from . import common as ui
from . import theme

TICK_PROPS = [
    "X", "Y", "Z", "pitch", "yaw", "velocity_X", "velocity_Y", "velocity_Z", "health", "armor_value",
    "is_alive", "team_num", "last_place_name", "active_weapon_name", "inventory", "balance",
    "current_equip_value", "has_helmet", "has_defuser", "is_scoped", "is_walking", "ducking", "flash_duration",
    "kills_total", "deaths_total", "assists_total", "damage_total", "headshot_kills_total",
    "utility_damage_total", "enemies_flashed_total", "mvps", "score", "spotted", "rank", "crosshair_code",
]


@st.cache_resource(show_spinner=False, max_entries=8)
def _parser(path: str) -> DemoParser:
    return DemoParser(path)


def _filter(df: pd.DataFrame, key: str) -> pd.DataFrame:
    """Filtro genérico: ronda (si existe) + texto libre sobre todas las columnas de texto."""
    c1, c2 = st.columns([1, 2])
    rcol = next((c for c in ("round", "Ronda") if c in df.columns), None)
    if rcol and df[rcol].notna().any():
        rounds = sorted(df[rcol].dropna().unique().tolist())
        sel = c1.multiselect("Rondas", rounds, key=f"{key}_r", placeholder="Elegí…")
        if sel:
            df = df[df[rcol].isin(sel)]
    q = c2.text_input("Buscar (jugador, arma, zona…)", key=f"{key}_q")
    if q:
        text_cols = [c for c in df.columns if df[c].dtype == object or pd.api.types.is_string_dtype(df[c])]
        mask = pd.Series(False, index=df.index)
        for c in text_cols:
            mask |= df[c].astype(str).str.contains(q, case=False, na=False, regex=False)
        df = df[mask]
    return df


def render_translated() -> None:
    theme.page_header("Datos traducidos", "Cada evento de la demo, en español y con valores legibles. Filtrá y descargá.", "Datos")
    d = ui.pick_demo("tr_demo")
    if d is None:
        ui.empty_state()
        return
    table = st.radio("Tabla", list(translate.TABLES), horizontal=True, key="tr_table")
    df = translate.TABLES[table](d)
    df = _filter(df, "tr")
    st.caption(f"{len(df):,} filas")
    st.dataframe(df, hide_index=True, width="stretch", height=560)
    ui.download_buttons(df, f"{d.meta['map']}_{table.split()[0].lower()}_traducido", "tr_dl")


def render_raw() -> None:
    theme.page_header("Datos crudos", "Eventos y ticks tal como salen de la demo, sin procesar, para análisis propios.", "Datos")
    d = ui.pick_demo("raw_demo")
    if d is None:
        ui.empty_state()
        return
    mode = st.radio("Fuente", ["Tablas normalizadas (sin traducir)", "Eventos del juego (demoparser2)",
                               "Ticks (estado por jugador)", "Header"], horizontal=True, key="raw_mode")

    if mode.startswith("Tablas"):
        st.caption("Tablas tal como las guarda la caché (parquet), con los nombres de columna originales.")
        table = st.radio("Tabla", list(TABLES), horizontal=True, key="raw_table")
        df = _filter(getattr(d, table), "raw")
        st.caption(f"{len(df):,} filas · {len(df.columns)} columnas")
        st.dataframe(df, hide_index=True, width="stretch", height=560)
        ui.download_buttons(df, f"{d.meta['map']}_{table}", "raw_dl")
        with st.expander("meta.json"):
            st.json(d.meta)
        return

    path = d.meta.get("source_path", "")
    if not path or not Path(path).exists():
        st.warning("El archivo .dem original ya no está disponible (solo queda la caché). "
                   "Volvé a cargarlo para explorar eventos y ticks crudos.")
        return
    parser = _parser(path)

    if mode == "Header":
        st.json(parser.parse_header())
    elif mode.startswith("Eventos"):
        events = sorted(parser.list_game_events())
        ev = st.selectbox("Evento", events, index=events.index("player_death") if "player_death" in events else 0)
        c1, c2 = st.columns(2)
        pprops = c1.multiselect("Props de jugador extra", TICK_PROPS, default=[], key="ev_pp",
                                help="Se agregan con prefijo user_/attacker_ según corresponda", placeholder="Elegí…")
        oprops = c2.multiselect("Props de partida", ["total_rounds_played", "is_warmup_period", "game_time",
                                                     "is_bomb_planted", "round_start_time"], default=[], key="ev_op", placeholder="Elegí…")
        df = parser.parse_event(ev, player=pprops or None, other=oprops or None)
        df = _filter(df, "ev")
        st.caption(f"{len(df):,} filas · {len(df.columns)} columnas")
        st.dataframe(df, hide_index=True, width="stretch", height=560)
        ui.download_buttons(df, f"{d.meta['map']}_{ev}", "ev_dl")
    else:
        rounds = d.rounds
        c1, c2, c3 = st.columns(3)
        rnd = c1.selectbox("Ronda", rounds["round"].tolist(), key="tk_round")
        step = c2.number_input("Cada N ticks", 1, 640, 64, help="64 = 1 muestra por segundo")
        names = {"": "Todos", **dict(zip(d.players["steamid"], d.players["name"]))}
        who = c3.selectbox("Jugador", list(names), format_func=names.get, key="tk_player")
        props = st.multiselect("Props", TICK_PROPS, default=["X", "Y", "Z", "health", "active_weapon_name", "last_place_name"], placeholder="Elegí…")
        r = rounds[rounds["round"] == rnd].iloc[0]
        ticks = list(range(int(r["freeze_end_tick"]), int(r["end_tick"]) + 1, int(step)))
        if not props:
            st.info("Elegí al menos una prop.")
            return
        with st.spinner("Leyendo ticks…"):
            df = parser.parse_ticks(props, ticks=ticks)
        if who:
            df = df[df["steamid"].astype(str) == who]
        st.caption(f"{len(df):,} filas")
        st.dataframe(df, hide_index=True, width="stretch", height=560)
        ui.download_buttons(df, f"{d.meta['map']}_r{rnd}_ticks", "tk_dl")
