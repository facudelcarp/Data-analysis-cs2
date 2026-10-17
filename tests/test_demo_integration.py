"""Test de integración contra una demo real: los totales calculados deben coincidir con el
scoreboard interno del juego (props *_total del último tick).

Se salta si no hay demo. Para correrlo: CS2A_TEST_DEMO=/ruta/a/partida.dem pytest
(la demo de test de demoparser2 sirve: https://github.com/LaihoE/demoparser/blob/main/src/parser/test_demo.dem)
"""
import os
from pathlib import Path

import pandas as pd
import pytest

DEMO = os.environ.get("CS2A_TEST_DEMO") or next(iter(sorted(Path(__file__).parent.glob("data/*.dem"))), None)
pytestmark = pytest.mark.skipif(not DEMO, reason="sin demo de test (CS2A_TEST_DEMO)")


@pytest.fixture(scope="module")
def demo():
    from cs2analysis.parser import parse_demo
    return parse_demo(DEMO, position_step=0)


@pytest.fixture(scope="module")
def scoreboard(demo):
    from demoparser2 import DemoParser
    p = DemoParser(str(DEMO))
    last = int(demo.rounds["official_end_tick"].max())
    sb = p.parse_ticks(["kills_total", "deaths_total", "assists_total", "damage_total", "headshot_kills_total",
                        "utility_damage_total"], ticks=[last])
    sb["steamid"] = sb["steamid"].astype(str)
    return sb.set_index("steamid")


def test_matches_ingame_scoreboard(demo, scoreboard):
    from cs2analysis.stats import player_stats
    ps = player_stats(demo).set_index("steamid")
    joined = scoreboard.drop(columns=["name"]).join(ps, how="inner")
    assert len(joined) == len(scoreboard)
    pd.testing.assert_series_equal(joined["kills"], joined["kills_total"], check_names=False, check_dtype=False)
    pd.testing.assert_series_equal(joined["deaths"], joined["deaths_total"], check_names=False, check_dtype=False)
    pd.testing.assert_series_equal(joined["assists"], joined["assists_total"], check_names=False, check_dtype=False)
    pd.testing.assert_series_equal(joined["damage"], joined["damage_total"], check_names=False, check_dtype=False)
    pd.testing.assert_series_equal(joined["hs_kills"], joined["headshot_kills_total"], check_names=False, check_dtype=False)
    pd.testing.assert_series_equal(joined["utility_damage"], joined["utility_damage_total"], check_names=False,
                                   check_dtype=False)


def test_score_and_rounds(demo):
    r = demo.rounds
    assert r["round"].is_monotonic_increasing
    assert demo.meta["score_a"] + demo.meta["score_b"] == len(r)
    assert set(r["winner_side"]) <= {"CT", "T"}


def test_translated_tables_render(demo):
    from cs2analysis import translate
    for name, fn in translate.TABLES.items():
        df = fn(demo)
        assert isinstance(df, pd.DataFrame), name


def test_cache_roundtrip(demo, tmp_path):
    from cs2analysis.parser import DemoData
    demo.save(tmp_path / "x")
    back = DemoData.load(tmp_path / "x")
    assert back.meta == demo.meta
    pd.testing.assert_frame_equal(back.kills, demo.kills, check_dtype=False)
