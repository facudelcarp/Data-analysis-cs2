"""CS2 Data Analysis — punto de entrada de la app.

    streamlit run app.py
"""
import sys

import streamlit as st

st.set_page_config(page_title="CS2 Data Analysis", page_icon="🎯", layout="wide")

from cs2analysis.multi import find_demos  # noqa: E402
from cs2analysis.ui import common, dashboard, multi_view, raw, single  # noqa: E402

VIEWS = {
    "🎯 Demo individual": single.render,
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

st.sidebar.title("CS2 Data Analysis")
view = st.sidebar.radio("Vista", list(VIEWS), key="view")
common.sidebar_sources()
VIEWS[view]()
