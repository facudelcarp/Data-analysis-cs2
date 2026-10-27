"""Piezas compartidas de la UI: carga de demos, estado, estilo de gráficos y mapas."""
from __future__ import annotations

import base64
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from ..maps import RADAR_SIZE, download_radars, has_levels, level_mask, map_info, pretty_map, radar_image
from ..multi import Library, find_demos, load_many
from ..parser import DEFAULT_CACHE_DIR, DemoData, load_demo

# Paleta (validada para fondo oscuro): lados con los colores clásicos del juego, equipos con
# dos tonos distintos para que nunca se confundan con el lado en que juegan.
SIDE_COLORS = {"CT": "#3987e5", "T": "#d95926"}
TEAM_COLORS = {"A": "#199e70", "B": "#9085e9"}
GRENADE_COLORS = {"Humo": "#c3c2b7", "Fuego": "#d95926", "Flash": "#c98500", "Granada HE": "#199e70",
                  "Señuelo": "#9085e9"}
SEQ_SCALE = ["#104281", "#1c5cab", "#2a78d6", "#5598e7", "#86b6ef", "#cde2fb"]
SERIES = ["#3987e5", "#d95926", "#199e70", "#c98500", "#d55181", "#008300", "#9085e9", "#e66767"]
TEXT_MUTED = "#c3c2b7"
GRID = "rgba(255,255,255,0.08)"

UPLOAD_DIR = DEFAULT_CACHE_DIR / "uploads"

from ..labels import RATING_NOTE, SCOREBOARD_COLS, STAT_LABELS  # noqa: E402,F401  (re-export)


# --------------------------------------------------------------------------------------------
# Carga / estado
# --------------------------------------------------------------------------------------------

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
    progress = st.progress(0.0, text="Cargando…")
    seen = st.session_state.setdefault("loaded_paths", set())
    new = [p for p in paths if str(p) not in seen]
    # Muchas demos: en paralelo. Pocas: en este proceso, aprovechando la caché de Streamlit.
    workers = 4 if sum(1 for p in new if str(p).endswith(".dem")) > 2 else 1
    loaded, errors = load_many(new, workers=workers,
                               progress=lambda i, n: progress.progress(i / n, text=f"Cargando {i}/{n}…"))
    for d in loaded:
        demos()[d.demo_id] = d
    seen.update(str(p) for p in new)
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
        files = st.file_uploader("Subir demos (.dem) o análisis guardados (.cs2a)", type=["dem", "cs2a"],
                                 accept_multiple_files=True)
        if files and st.button("Procesar subidas", width="stretch"):
            add_paths([save_upload(f) for f in files])
        folder = st.text_input("…o carpeta local (.dem / .cs2a)", placeholder="~/demos o C:\\demos")
        if folder and st.button("Escanear carpeta", width="stretch"):
            found = find_demos(folder)
            if not found:
                st.warning("No se encontraron archivos .dem ni .cs2a")
            else:
                add_paths(found)
    if demos():
        st.sidebar.caption(f"📚 {len(demos())} demo(s) en la sesión")
        st.sidebar.download_button(
            "💾 Guardar sesión (.cs2a)", data=_session_bytes(tuple(sorted(demos()))), file_name="biblioteca.cs2a",
            mime="application/zip", width="stretch",
            help="Todas las demos analizadas en un archivo compacto (~300 KB por partida). "
                 "Se puede volver a abrir sin los .dem originales.")
        if st.sidebar.button("Vaciar sesión", width="stretch"):
            st.session_state["demos"] = {}
            st.session_state["loaded_paths"] = set()
            st.rerun()


@st.cache_data(show_spinner="Empaquetando…", max_entries=4)
def _session_bytes(ids: tuple[str, ...]) -> bytes:
    import tempfile
    from ..storage import write_cs2a
    with tempfile.TemporaryDirectory() as tmp:
        path = write_cs2a(Path(tmp) / "biblioteca.cs2a", [demos()[i] for i in ids])
        return path.read_bytes()


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
    from .theme import onboarding
    onboarding()


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
                       key=f"{key}_csv", width="stretch")
    try:
        import io
        buf = io.BytesIO()
        df.to_parquet(buf, index=False)
        c2.download_button("⬇️ Parquet", buf.getvalue(), f"{name}.parquet", "application/octet-stream",
                           key=f"{key}_pq", width="stretch")
    except Exception:
        pass


# --------------------------------------------------------------------------------------------
# Gráficos
# --------------------------------------------------------------------------------------------

def style(fig: go.Figure, height: int = 360, legend: bool = True) -> go.Figure:
    # respeta márgenes más grandes que un gráfico haya pedido antes (etiquetas al costado, títulos largos)
    cur = fig.layout.margin
    base = {"l": 10, "r": 10, "t": 80 if legend else 40, "b": 10}
    margin = {k: max(v, getattr(cur, k) or 0) for k, v in base.items()}
    fig.update_layout(
        template="plotly_dark", height=height, margin=margin,
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)", legend_title_text="",
        font=dict(color=TEXT_MUTED, size=12, family="Inter, sans-serif"), showlegend=legend,
        title_font=dict(color="#e8e6e3", size=15),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="left", x=0),
        hoverlabel=dict(bgcolor="#1a1a19", font_color="#f0efec"), bargap=0.25,
    )
    fig.update_traces(selector=dict(type="bar"), textangle=0, cliponaxis=False,
                      marker_line_width=0, textfont_color="#f0efec")
    fig.update_xaxes(gridcolor=GRID, zeroline=False)
    fig.update_yaxes(gridcolor=GRID, zeroline=False)
    return fig


def map_figure(map_name: str, height: int = 620, backdrop: pd.DataFrame | None = None,
               lower: bool = False) -> tuple[go.Figure, callable]:
    """Figura base para dibujar sobre el mapa. Devuelve la figura y una función que transforma
    coordenadas del juego a las del gráfico (píxeles de radar si hay imagen, si no, unidades).

    Sin imagen de radar, `backdrop` (posiciones de jugadores) dibuja la silueta del mapa en gris.
    `lower` elige el radar del nivel inferior en mapas de dos pisos."""
    info = map_info(map_name)
    img = radar_image(map_name, lower=lower) or (radar_image(map_name) if not lower else None)
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
            bd = backdrop[level_mask(map_name, backdrop["z"], lower)]
            bd = bd.iloc[:: max(1, len(bd) // 15000)]
            fig.add_scattergl(x=bd["x"], y=bd["y"], mode="markers", hoverinfo="skip", showlegend=False,
                              marker=dict(size=4, color="rgba(195,194,183,0.10)"))
    style(fig, height=height)
    fig.update_layout(margin=dict(l=0, r=0, t=30, b=0))
    return fig, tf


def level_selector(map_name: str, key: str) -> bool:
    """Radio Superior/Inferior para mapas de dos pisos. Devuelve True si se eligió el inferior."""
    if not has_levels(map_name):
        return False
    return st.radio("Nivel", ["Superior", "Inferior"], horizontal=True, key=key) == "Inferior"


def on_level(df: pd.DataFrame, zcol: str, map_name: str, lower: bool) -> pd.DataFrame:
    if df.empty or zcol not in df:
        return df
    return df[level_mask(map_name, df[zcol], lower)]


def radar_hint(map_name: str, key: str) -> None:
    if has_radar(map_name):
        return
    c1, c2 = st.columns([3, 1])
    c1.caption("Sin imagen de radar: se dibuja en coordenadas del juego sobre la silueta de posiciones.")
    if c2.button("Descargar radares", key=key, width="stretch"):
        with st.spinner("Descargando radares…"):
            try:
                n = len(download_radars())
                st.success(f"{n} imágenes descargadas en assets/radars/")
                st.rerun()
            except Exception as exc:
                st.error(f"No se pudieron descargar: {exc}")


def has_radar(map_name: str) -> bool:
    return bool(map_info(map_name) and radar_image(map_name))


def kpi_row(items: list[tuple]) -> None:
    """Fila de métricas. Cada item: (label, valor, ayuda) o (label, valor, ayuda, delta, menos_es_mejor).

    El delta se muestra con flecha y color (verde = mejor). Con menos_es_mejor=True (ms, grados) se invierte."""
    cols = st.columns(len(items))
    for col, item in zip(cols, items):
        label, value, help_ = item[:3]
        delta = item[3] if len(item) > 3 else None
        inverse = item[4] if len(item) > 4 else False
        color = "off" if isinstance(delta, str) and delta.startswith("≈") else ("inverse" if inverse else "normal")
        col.metric(label, value, delta=delta, delta_color=color, help=help_)
