"""Smoke test de la app: abre cada vista con datos reales y falla ante cualquier excepción.

Usa tests/fixtures/pro_sample.cs2a (dos demos de HLTV ya analizadas, ~600 KB) para no depender de
descargar demos: corre igual en CI que en local. Si cambia el análisis (CACHE_VERSION), regenerarlo con
    cs2a pack hltv-de_inferno-2395492.dem hltv-de_mirage-2394170.dem -o tests/fixtures/pro_sample.cs2a
"""
from pathlib import Path

import pytest

st_testing = pytest.importorskip("streamlit.testing.v1")

ROOT = Path(__file__).resolve().parent.parent
FIXTURE = ROOT / "tests" / "fixtures" / "pro_sample.cs2a"
TIMEOUT = 180


@pytest.fixture(scope="module")
def demos():
    from cs2analysis.storage import read_cs2a
    return {d.demo_id: d for d in read_cs2a(FIXTURE)}


def _app(demos):
    at = st_testing.AppTest.from_file(str(ROOT / "app.py"), default_timeout=TIMEOUT)
    at.session_state["demos"] = dict(demos)
    at.session_state["loaded_paths"] = set()
    at.run()
    assert not at.exception, at.exception
    return at


def _errors(at) -> list[str]:
    return [e.value for e in at.exception]


def _views(demos) -> list[str]:
    return list(_app(demos).sidebar.radio(key="view").options)


def test_every_view_renders(demos):
    views = _views(demos)
    assert len(views) >= 5
    for view in views:
        at = _app(demos)
        at.sidebar.radio(key="view").set_value(view).run()
        assert not at.exception, f"{view}: {_errors(at)}"


def test_single_demo_every_demo(demos):
    """La vista individual ejecuta todas sus pestañas en cada corrida: probarla con cada demo."""
    for demo_id in demos:
        at = _app(demos)
        at.session_state["single_demo"] = demo_id
        at.sidebar.radio(key="view").set_value(at.sidebar.radio(key="view").options[0]).run()
        assert not at.exception, f"{demo_id}: {_errors(at)}"


def test_dashboard_focus_player(demos):
    d = next(iter(demos.values()))
    at = _app(demos)
    at.session_state["focus_player"] = d.players["steamid"].iloc[0]
    dash = next(v for v in at.sidebar.radio(key="view").options if "Dashboard" in v)
    at.sidebar.radio(key="view").set_value(dash).run()
    assert not at.exception, _errors(at)
    assert any("vs mediana" in str(m.delta) for m in at.metric), "faltan las comparaciones contra la mediana"
