"""CS2 Data Analysis — punto de entrada de la app.

    streamlit run app.py
"""
import sys

import streamlit as st

st.set_page_config(page_title="CS2 Data Analysis", page_icon="🎯", layout="wide")

from cs2analysis.multi import find_demos  # noqa: E402
from cs2analysis.ui import common, dashboard, multi_view, raw, single, team_view, theme  # noqa: E402

VIEWS = {
    "🎯 Demo individual": single.render,
    "👥 Análisis de Equipos": team_view.render,
    "📚 Multi-demo": multi_view.render,
    "📊 Dashboard": dashboard.render,
    "🈯 Datos crudos traducidos": raw.render_translated,
    "🧾 Datos crudos": raw.render_raw,
}

# `streamlit run app.py -- --demos CARPETA` precarga una carpeta al abrir la sesión
if "--demos" in sys.argv and not st.session_state.get("preloaded"):
    st.session_state["preloaded"] = True
    folder = sys.argv[sys.argv.index("--demos") + 1]
    common.add_paths(find_demos(folder))

theme.inject()
theme.sidebar_brand()
view = st.sidebar.radio("Vista", list(VIEWS), key="view", label_visibility="collapsed")
common.sidebar_sources()
VIEWS[view]()
