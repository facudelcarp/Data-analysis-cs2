"""Identidad visual de la app: estilo global, encabezados de página, banners y marca.

Los colores base (fondo, superficies, bordes, fuente) viven en .streamlit/config.toml; acá solo va lo
que el tema de Streamlit no cubre (tarjetas de métricas, pestañas, banners). Todo nombre que viene de
una demo se escapa: un jugador puede llamarse literalmente "<script>".
"""
from __future__ import annotations

from html import escape

import streamlit as st

from . import common as ui

ACCENT = "#f0a33d"       # ámbar CS2: acción principal, pestaña activa
SURFACE = "#151a22"      # tarjetas
BORDER = "#262c36"
MUTED = "#9aa0a8"
TEXT = "#e8e6e3"

CSS = f"""
<style>
/* Contenido: menos aire arriba (sin barra de Deploy) y ancho cómodo en pantallas grandes */
.block-container {{ padding-top: 2.2rem; max-width: 1500px; }}

/* Métricas como tarjetas */
[data-testid="stMetric"] {{
  background: {SURFACE}; border: 1px solid {BORDER}; border-radius: 10px; padding: 12px 14px;
}}
[data-testid="stMetricLabel"] p {{ color: {MUTED}; font-size: .82rem; }}
/* etiquetas largas: saltan de línea en vez de cortarse con "…" */
[data-testid="stMetricLabel"], [data-testid="stMetricLabel"] * {{
  white-space: normal !important; overflow: visible !important; text-overflow: clip !important; }}
[data-testid="stMetricValue"] {{ font-variant-numeric: tabular-nums; }}

/* Pestañas: más legibles, activa en ámbar */
[data-baseweb="tab-list"] {{ gap: 4px; border-bottom: 1px solid {BORDER}; }}
button[data-baseweb="tab"] {{ padding: 6px 12px; border-radius: 8px 8px 0 0; }}
button[data-baseweb="tab"] p {{ font-weight: 600; font-size: .92rem; }}
button[data-baseweb="tab"][aria-selected="true"] {{ background: rgba(240,163,61,.08); }}

/* Subtítulos de sección con aire arriba */
h3 {{ margin-top: .6rem; }}

/* Expanders y dataframes con el mismo borde que las tarjetas */
[data-testid="stExpander"] details {{ border-color: {BORDER}; border-radius: 10px; }}

/* Captions "Cómo leerlo" un poco más legibles */
[data-testid="stCaptionContainer"] {{ color: {MUTED}; }}

/* Componentes propios */
.cs2-header {{ margin: 0 0 1.1rem 0; }}
.cs2-header .eyebrow {{ color: {ACCENT}; font-size: .74rem; font-weight: 700; letter-spacing: .12em; text-transform: uppercase; }}
.cs2-header h1 {{ font-size: 1.9rem; font-weight: 700; margin: .1rem 0 .2rem 0; padding: 0; }}
.cs2-header .sub {{ color: {MUTED}; font-size: .95rem; }}

.cs2-banner {{ background: linear-gradient(180deg, {SURFACE}, #11151c); border: 1px solid {BORDER};
  border-radius: 14px; padding: 18px 22px; margin: .4rem 0 1rem 0; }}
.cs2-match {{ display: grid; grid-template-columns: 1fr auto 1fr; align-items: center; gap: 18px; }}
.cs2-team {{ display: flex; flex-direction: column; gap: 2px; min-width: 0; }}
.cs2-team.left {{ align-items: flex-end; text-align: right; }}
.cs2-team .name {{ font-size: 1.35rem; font-weight: 700; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; max-width: 100%; }}
.cs2-team .meta {{ color: {MUTED}; font-size: .82rem; }}
.cs2-score {{ font-size: 2.6rem; font-weight: 800; letter-spacing: .02em; font-variant-numeric: tabular-nums; white-space: nowrap; }}
.cs2-score .sep {{ color: {MUTED}; margin: 0 .35rem; font-weight: 400; }}
.cs2-score .lose {{ color: {MUTED}; }}
.cs2-chips {{ display: flex; flex-wrap: wrap; gap: 8px; justify-content: center; margin-top: 12px; }}
.cs2-chip {{ border: 1px solid {BORDER}; border-radius: 999px; padding: 2px 10px; font-size: .8rem; color: {MUTED}; }}
.cs2-chip b {{ color: {TEXT}; font-weight: 600; }}
.cs2-win {{ display: inline-block; font-size: .68rem; font-weight: 700; letter-spacing: .08em; color: #0c0f14;
  background: {ACCENT}; border-radius: 4px; padding: 1px 6px; margin-top: 4px; }}

.cs2-brand {{ padding: .2rem 0 .8rem 0; }}
.cs2-brand .logo {{ font-size: 1.25rem; font-weight: 800; letter-spacing: .02em; }}
.cs2-brand .logo span {{ color: {ACCENT}; }}
.cs2-brand .tag {{ color: {MUTED}; font-size: .78rem; }}

.cs2-empty {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); gap: 12px; margin-top: .8rem; }}
.cs2-empty .card {{ background: {SURFACE}; border: 1px solid {BORDER}; border-radius: 12px; padding: 14px 16px; }}
.cs2-empty .card .t {{ font-weight: 700; margin-bottom: 4px; }}
.cs2-empty .card .d {{ color: {MUTED}; font-size: .88rem; }}

@media (max-width: 700px) {{
  .cs2-match {{ grid-template-columns: 1fr; text-align: center; }}
  .cs2-team.left {{ align-items: center; text-align: center; }}
  .cs2-team {{ align-items: center; }}
}}
</style>
"""


def inject() -> None:
    st.markdown(CSS, unsafe_allow_html=True)


def page_header(title: str, subtitle: str = "", eyebrow: str = "") -> None:
    """Encabezado común de cada vista: categoría arriba, título y para qué sirve la vista."""
    st.markdown(
        f"<div class='cs2-header'>"
        + (f"<div class='eyebrow'>{escape(eyebrow)}</div>" if eyebrow else "")
        + f"<h1>{escape(title)}</h1>"
        + (f"<div class='sub'>{escape(subtitle)}</div>" if subtitle else "")
        + "</div>", unsafe_allow_html=True)


def match_banner(meta: dict, map_label: str) -> None:
    """Marcador de la partida: equipos con su color, resultado grande y datos de la partida en chips."""
    a, b = int(meta["score_a"]), int(meta["score_b"])
    start_b = "T" if meta.get("start_side_a") == "CT" else "CT"

    def team(name: str, color: str, start: str, won: bool, side: str) -> str:
        badge = f"<span class='cs2-win' style='visibility:{'visible' if won else 'hidden'}'>GANADOR</span>"
        return (f"<div class='cs2-team {side}'><div class='name' style='color:{color}'>{escape(str(name))}</div>"
                f"<div class='meta'>empezó de {start}</div>{badge}</div>")

    score = (f"<div class='cs2-score'><span class='{'' if a >= b else 'lose'}'>{a}</span>"
             f"<span class='sep'>:</span><span class='{'' if b >= a else 'lose'}'>{b}</span></div>")
    chips = [("Mapa", map_label), ("Rondas", meta.get("rounds")), ("Duración", f"{meta.get('duration_min')} min")]
    chip_html = "".join(f"<span class='cs2-chip'>{k} <b>{escape(str(v))}</b></span>" for k, v in chips)
    st.markdown(
        "<div class='cs2-banner'><div class='cs2-match'>"
        + team(meta["team_a"], ui.TEAM_COLORS["A"], meta.get("start_side_a", "?"), a > b, "left")
        + score
        + team(meta["team_b"], ui.TEAM_COLORS["B"], start_b, b > a, "right")
        + f"</div><div class='cs2-chips'>{chip_html}</div></div>", unsafe_allow_html=True)


def sidebar_brand() -> None:
    st.sidebar.markdown(
        "<div class='cs2-brand'><div class='logo'>CS2 <span>·</span> Data Analysis</div>"
        "<div class='tag'>Análisis de demos: partidas, jugadores y equipos</div></div>", unsafe_allow_html=True)


def onboarding() -> None:
    """Estado vacío: qué hacer primero y qué ofrece cada vista."""
    st.info("Cargá una o más demos (.dem) o un análisis guardado (.cs2a) desde **➕ Cargar demos** en la barra lateral.")
    cards = [
        ("🎯 Demo individual", "Una partida a fondo: marcador, rondas, economía, duelos, aim, utilidad, tácticas y replay 2D."),
        ("👥 Análisis de Equipos", "Un equipo en todas sus partidas: roles, tradeos, ventajas numéricas y map pool."),
        ("📚 Multi-demo", "Leaderboard sumando partidas, comparación de jugadores, evolución y mapas."),
        ("📊 Dashboard", "Resumen de un jugador comparado con el resto de la biblioteca, o de la biblioteca entera."),
        ("🈯 Datos traducidos", "Todas las tablas en español y legibles, filtrables y descargables."),
        ("🧾 Datos crudos", "Eventos y ticks tal como salen de la demo, para análisis propios."),
    ]
    st.markdown("<div class='cs2-empty'>" + "".join(
        f"<div class='card'><div class='t'>{t}</div><div class='d'>{d}</div></div>" for t, d in cards) + "</div>",
        unsafe_allow_html=True)
