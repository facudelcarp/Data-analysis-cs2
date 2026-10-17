"""Piezas compartidas de la UI: carga de demos, estado, estilo de gráficos y mapas."""
from __future__ import annotations

import base64
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from ..maps import map_info, pretty_map, radar_image, RADAR_SIZE
from ..multi import Library, find_demos, load_many
from ..parser import DEFAULT_CACHE_DIR, DemoData, file_hash, load_demo

# Paleta (validada para fondo oscuro): lados con los colores clásicos del juego, equipos con
# dos tonos distintos para que nunca se confundan con el lado en que juegan.
SIDE_COLORS = {"CT": "#3987e5", "T": "#d95926"}
TEAM_COLORS = {"A": "#199e70", "B": "#9085e9"}
SEQ_SCALE = ["#104281", "#1c5cab", "#2a78d6", "#5598e7", "#86b6ef", "#cde2fb"]
SERIES = ["#3987e5", "#d95926", "#199e70", "#c98500", "#d55181", "#008300", "#9085e9", "#e66767"]
TEXT_MUTED = "#c3c2b7"
GRID = "rgba(255,255,255,0.08)"

UPLOAD_DIR = DEFAULT_CACHE_DIR / "uploads"

STAT_LABELS = {
    "name": "Jugador", "team_name": "Equipo", "rounds": "Rondas", "demos": "Demos",
    "kills": "K", "deaths": "D", "assists": "A", "kd": "K/D", "kd_diff": "+/-", "adr": "ADR",
    "hs_pct": "HS %", "kast_pct": "KAST %", "rating2": "Rating 2.0*", "rating1": "Rating 1.0",
    "impact": "Impacto*", "opening_kills": "Entry K", "opening_deaths": "Entry D",
    "opening_success_pct": "Entry %", "trade_kills": "Tradeos", "traded_deaths": "Muertes tradeadas",
    "k2": "2K", "k3": "3K", "k4": "4K", "k5": "5K", "clutches_won": "Clutches ganados",
    "clutches": "Clutches", "utility_damage": "Daño utilidad", "utility_adr": "ADR utilidad",
    "enemies_flashed": "Enemigos flasheados", "flash_assists": "Asist. flash", "awp_kills": "Kills AWP",
    "accuracy_pct": "Precisión %", "mvps": "MVPs", "avg_equip": "Equipo prom. $", "teamkills": "TK",
    "team_damage": "Daño a aliados", "rounds_won": "Rondas ganadas", "kpr": "KPR", "dpr": "DPR",
    "survived": "Rondas sobrevividas", "grenades_thrown": "Granadas", "blind_time": "Ceguera infligida (s)",
}
SCOREBOARD_COLS = ["name", "kills", "deaths", "assists", "kd_diff", "adr", "hs_pct", "kast_pct",
                   "opening_kills", "opening_deaths", "trade_kills", "k3", "k4", "k5", "clutches_won",
                   "utility_damage", "enemies_flashed", "accuracy_pct", "rating1", "rating2"]
RATING_NOTE = ("*Rating 2.0 e Impacto son la aproximación de la comunidad (HLTV no publica la fórmula). "
               "Rating 1.0 es la fórmula oficial publicada.")


# --------------------------------------------------------------------------------------------
# Carga / estado
# --------------------------------------------------------------------------------------------

@st.cache_resource(show_spinner=False, max_entries=64)
def _cached_demo(path: str, mtime: float) -> DemoData:
    return load_demo(path)


@st.cache_resource(show_spinner=False, max_entries=8)
def _cached_library(ids: tuple[str, ...], _demos: tuple[DemoData, ...]) -> Library:
    return Library(list(_demos))


def demos() -> dict[str, DemoData]:
    return st.session_state.setdefault("demos", {})


def library() -> Library:
    ds = demos()
    ids = tuple(sorted(ds))
    return _cached_library(ids, tuple(ds[i] for i in ids))


def add_paths(paths: list[Path]) -> None:
    progress = st.progress(0.0, text="Parseando demos…")
    new = [p for p in paths if str(p) not in st.session_state.setdefault("loaded_paths", set())]
    errors = []
    if len(new) > 2:
        # Para muchas demos: parseo en paralelo (la caché en disco hace que la próxima vez sea instantáneo)
        loaded, errors = load_many(new, workers=4,
                                   progress=lambda i, n: progress.progress(i / n, text=f"Parseando {i}/{n}…"))
    else:
        loaded = []
        for i, p in enumerate(new, 1):
            progress.progress((i - 0.5) / len(new), text=f"Parseando {p.name}…")
            try:
                loaded.append(_cached_demo(str(p), p.stat().st_mtime))
            except Exception as exc:
                errors.append(f"{p.name}: {exc}")
    for d in loaded:
        demos()[d.demo_id] = d
        st.session_state["loaded_paths"].add(d.meta["source_path"])
    progress.empty()
    if loaded:
        st.toast(f"{len(loaded)} demo(s) cargadas")
    for e in errors:
        st.error(e)


def save_upload(uploaded) -> Path:
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    target = UPLOAD_DIR / uploaded.name
    if not target.exists() or target.stat().st_size != uploaded.size:
        with open(target, "wb") as f:
            f.write(uploaded.getbuffer())
    return target


def sidebar_sources() -> None:
    with st.sidebar.expander("➕ Cargar demos", expanded=not demos()):
        files = st.file_uploader("Subir archivos .dem", type=["dem"], accept_multiple_files=True)
        if files and st.button("Procesar subidas", use_container_width=True):
            add_paths([save_upload(f) for f in files])
        folder = st.text_input("…o carpeta local con demos", placeholder="~/demos o C:\\demos")
        if folder and st.button("Escanear carpeta", use_container_width=True):
            found = find_demos(folder)
            if not found:
                st.warning("No se encontraron archivos .dem")
            else:
                add_paths(found)
    if demos():
        st.sidebar.caption(f"📚 {len(demos())} demo(s) en la sesión")
        if st.sidebar.button("Vaciar sesión", use_container_width=True):
            st.session_state["demos"] = {}
            st.session_state["loaded_paths"] = set()
            st.rerun()


def pick_demo(key: str, label: str = "Demo") -> DemoData | None:
    ds = sorted(demos().values(), key=lambda d: d.meta["file_mtime"], reverse=True)
    if not ds:
        return None
    labels = {d.demo_id: f"{pretty_map(d.meta['map'])} · {d.meta['score_a']}-{d.meta['score_b']} · "
                         f"{d.meta['file_mtime'][:10]} · {d.meta['file_name']}" for d in ds}
    default = st.session_state.get("current_demo")
    ids = list(labels)
    idx = ids.index(default) if default in ids else 0
    chosen = st.selectbox(label, ids, index=idx, format_func=labels.get, key=key)
    st.session_state["current_demo"] = chosen
    return demos()[chosen]


def empty_state() -> None:
    st.info("Cargá una o más demos desde la barra lateral (subida o carpeta local) para empezar.")
    st.markdown(
        "- **Demo individual**: scoreboard, ronda a ronda, economía, duelos, utilidad y mapas de calor.\n"
        "- **Multi-demo**: leaderboard agregado, comparación de jugadores, mapas y tendencias.\n"
        "- **Dashboard**: vista ejecutiva de un jugador (o de toda la biblioteca).\n"
        "- **Datos crudos traducidos**: las tablas del parser en español y con valores legibles.\n"
        "- **Datos crudos**: eventos y ticks tal cual los entrega demoparser2, sin procesar.")


# --------------------------------------------------------------------------------------------
# Tablas
# --------------------------------------------------------------------------------------------

def stat_table(df: pd.DataFrame, cols: list[str]) -> pd.DataFrame:
    cols = [c for c in cols if c in df.columns]
    out = df[cols].rename(columns=STAT_LABELS)
    for c in out.columns:
        if pd.api.types.is_float_dtype(out[c]) and (out[c].dropna() % 1 == 0).all():
            out[c] = out[c].astype("Int64")
    return out


def download_buttons(df: pd.DataFrame, name: str, key: str) -> None:
    c1, c2 = st.columns(2)
    c1.download_button("⬇️ CSV", df.to_csv(index=False).encode("utf-8"), f"{name}.csv", "text/csv",
                       key=f"{key}_csv", use_container_width=True)
    try:
        import io
        buf = io.BytesIO()
        df.to_parquet(buf, index=False)
        c2.download_button("⬇️ Parquet", buf.getvalue(), f"{name}.parquet", "application/octet-stream",
                           key=f"{key}_pq", use_container_width=True)
    except Exception:
        pass


# --------------------------------------------------------------------------------------------
# Gráficos
# --------------------------------------------------------------------------------------------

def style(fig: go.Figure, height: int = 360, legend: bool = True) -> go.Figure:
    fig.update_layout(
        template="plotly_dark", height=height, margin=dict(l=10, r=10, t=80 if legend else 40, b=10),
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)", legend_title_text="",
        font=dict(color=TEXT_MUTED, size=12), showlegend=legend,
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="left", x=0),
        hoverlabel=dict(bgcolor="#1a1a19", font_color="#f0efec"), bargap=0.25,
    )
    fig.update_traces(selector=dict(type="bar"), textangle=0, cliponaxis=False,
                      marker_line_width=0, textfont_color="#f0efec")
    fig.update_xaxes(gridcolor=GRID, zeroline=False)
    fig.update_yaxes(gridcolor=GRID, zeroline=False)
    return fig


def map_figure(map_name: str, height: int = 620, backdrop: pd.DataFrame | None = None) -> tuple[go.Figure, callable]:
    """Figura base para dibujar sobre el mapa. Devuelve la figura y una función que transforma
    coordenadas del juego a las del gráfico (píxeles de radar si hay imagen, si no, unidades).

    Sin imagen de radar, `backdrop` (posiciones de jugadores) dibuja la silueta del mapa en gris."""
    info = map_info(map_name)
    img = radar_image(map_name)
    fig = go.Figure()
    if info and img:
        encoded = base64.b64encode(Path(img).read_bytes()).decode()
        fig.add_layout_image(dict(source=f"data:image/png;base64,{encoded}", xref="x", yref="y", x=0, y=0,
                                  sizex=RADAR_SIZE, sizey=RADAR_SIZE, sizing="stretch", layer="below", opacity=0.9))
        fig.update_xaxes(range=[0, RADAR_SIZE], visible=False)
        fig.update_yaxes(range=[RADAR_SIZE, 0], visible=False, scaleanchor="x")

        def tf(x, y):
            return info.to_radar(x, y)
    else:
        fig.update_xaxes(visible=False)
        fig.update_yaxes(visible=False, scaleanchor="x")

        def tf(x, y):
            return x, y
        if backdrop is not None and len(backdrop):
            bd = backdrop.iloc[:: max(1, len(backdrop) // 15000)]
            fig.add_scattergl(x=bd["x"], y=bd["y"], mode="markers", hoverinfo="skip", showlegend=False,
                              marker=dict(size=4, color="rgba(195,194,183,0.10)"))
    style(fig, height=height)
    fig.update_layout(margin=dict(l=0, r=0, t=30, b=0))
    return fig, tf


def has_radar(map_name: str) -> bool:
    return bool(map_info(map_name) and radar_image(map_name))


def kpi_row(items: list[tuple[str, str, str | None]]) -> None:
    cols = st.columns(len(items))
    for col, (label, value, help_) in zip(cols, items):
        col.metric(label, value, help=help_)
