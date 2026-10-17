"""Tests de integración contra demos reales: los totales calculados deben coincidir con el
scoreboard interno del juego (props *_total del último tick) y con los resultados oficiales.

Corre sobre cada .dem de tests/data/ (ver scripts/fetch_fixtures.py) y sobre CS2A_TEST_DEMO.
Si no hay demos, se saltea.
"""
import json
import os
from pathlib import Path

import pandas as pd
import pytest

DATA = Path(__file__).parent / "data"
DEMOS = sorted(DATA.glob("*.dem"))
if os.environ.get("CS2A_TEST_DEMO"):
    DEMOS.append(Path(os.environ["CS2A_TEST_DEMO"]))
MANIFEST = {}
if (DATA / "manifest.json").exists():
    MANIFEST = {f["asset"]: f for f in json.loads((DATA / "manifest.json").read_text())["fixtures"]}

# Demo de matchmaking con dos jugadores que matan a través de paredes y giran 60-80° en < 100 ms
SUSPECTS = {"valve-de_mirage-472514809.dem": ["organner.pl recruit", "darkness01"]}

pytestmark = pytest.mark.skipif(not DEMOS, reason="sin demos (scripts/fetch_fixtures.py o CS2A_TEST_DEMO)")


@pytest.fixture(scope="module", params=DEMOS or [None], ids=lambda p: p.name if p else "none")
def case(request):
    from demoparser2 import DemoParser

    from cs2analysis.parser import parse_demo
    from cs2analysis.stats import player_stats
    path = request.param
    d = parse_demo(path, position_step=0)
    p = DemoParser(str(path))
    last = int(d.rounds["official_end_tick"].max())
    sb = p.parse_ticks(["kills_total", "deaths_total", "assists_total", "damage_total", "headshot_kills_total",
                        "utility_damage_total"], ticks=[last])
    sb["steamid"] = sb["steamid"].astype(str)
    # Demos de broadcast a las que les faltan eventos (p. ej. sin player_blind): el daño no es recuperable
    complete = {"player_blind", "round_officially_ended"} <= set(p.list_game_events())
    return {"path": path, "demo": d, "stats": player_stats(d).set_index("steamid"),
            "scoreboard": sb.drop(columns=["name"]).set_index("steamid"), "complete": complete}


def test_counts_match_ingame_scoreboard(case):
    ps, sb = case["stats"], case["scoreboard"]
    assert set(ps.index) <= set(sb.index)
    j = ps.join(sb)
    for mine, game in [("kills", "kills_total"), ("deaths", "deaths_total"), ("assists", "assists_total"),
                       ("hs_kills", "headshot_kills_total")]:
        pd.testing.assert_series_equal(j[mine], j[game], check_names=False, check_dtype=False)


def test_damage_matches_ingame_scoreboard(case):
    j = case["stats"].join(case["scoreboard"])
    if case["complete"]:
        pd.testing.assert_series_equal(j["damage"], j["damage_total"], check_names=False, check_dtype=False)
        # fuego que coincide en el mismo tick con otro daño: diferencias de pocos puntos
        assert ((j["utility_damage"] - j["utility_damage_total"]).abs() <= 0.03 * j["utility_damage_total"] + 3).all()
    else:
        assert ((j["damage"] - j["damage_total"]).abs() <= 0.03 * j["damage_total"] + 5).all()


def test_score_and_teams(case):
    d = case["demo"]
    r = d.rounds
    assert r["round"].is_monotonic_increasing and r["round"].is_unique
    assert d.meta["score_a"] + d.meta["score_b"] == len(r)
    assert set(r["winner_side"]) <= {"CT", "T"}
    assert (r["ct_team"] != r["t_team"]).all()
    # cada equipo tiene un roster estable (sin coaches: siempre ≤ 5 jugadores con rondas)
    assert d.players.groupby("team").size().max() <= 6
    expected = MANIFEST.get(case["path"].name, {}).get("result")
    if expected:
        a, b = map(int, expected.split("-"))
        assert sorted([d.meta["score_a"], d.meta["score_b"]]) == sorted([a, b])


def test_reference_ground_truth(case):
    """Kills/muertes/HS/KAST contra csstats, FACEIT o HLTV (las definiciones de ADR y asistencias difieren)."""
    gt = MANIFEST.get(case["path"].name, {}).get("ground_truth", {}).get("players", [])
    if not gt:
        pytest.skip("sin ground truth para esta demo")
    ps = case["stats"].set_index("name")
    for g in gt:
        row = ps.loc[g["name"]]
        assert row["kills"] == g["kills"]
        if "deaths" in g:
            assert row["deaths"] == g["deaths"]
        if "headshots" in g:
            assert row["hs_kills"] == g["headshots"]
        if "kast" in g:
            assert abs(row["kast_pct"] - g["kast"]) < 0.15
        if "multikill_rounds" in g:
            assert row["multikill_rounds"] == g["multikill_rounds"]
        if "adr" in g:
            # cada sitio define el ADR a su manera (csstats llega a diferir ~9% del damage_total del juego)
            assert abs(row["adr"] - g["adr"]) < 0.10 * g["adr"]


def test_translated_tables_render(case):
    from cs2analysis import translate
    for name, fn in translate.TABLES.items():
        assert isinstance(fn(case["demo"]), pd.DataFrame), name


def test_cache_roundtrip(case, tmp_path):
    from cs2analysis.parser import DemoData
    d = case["demo"]
    d.save(tmp_path / "x")
    back = DemoData.load(tmp_path / "x")
    assert back.meta == d.meta
    pd.testing.assert_frame_equal(back.kills, d.kills, check_dtype=False)


def test_micro_is_physically_plausible(case):
    """Rangos humanos: si la convención de ángulos, alturas o la visibilidad estuvieran mal, esto se rompe."""
    du = case["demo"].duels
    if du is None or du.empty:
        pytest.skip("sin micro-game")
    k = case["demo"].kills
    firearm = k["is_enemy_kill"] & ~k["weapon"].isin(["hegrenade", "inferno", "molotov", "incgrenade", "knife", "world"])
    assert len(du) >= 0.8 * firearm.sum()
    valid = du[du["crosshair_deg"].notna()]
    # los wallbangs no tienen visión por definición (y en la demo de Valve hay dos sospechosos con decenas)
    legit = du[~du["penetrated"]]
    assert legit["crosshair_deg"].notna().mean() >= 0.6
    from cs2analysis.micro import player_micro
    pm = player_micro(du, case["demo"].shots).set_index("steamid")
    names = case["demo"].players.set_index("steamid")["name"]
    flagged = set(names.reindex(pm.index[pm["inhuman_snaps"].fillna(0) > 0]))
    expected = set(MANIFEST.get(case["path"].name, {}).get("cs2a_suspects", SUSPECTS.get(case["path"].name, [])))
    if expected:
        # demo con tramposos conocidos: el detector tiene que marcarlos
        assert expected <= flagged, (expected, flagged)
        return
    assert not flagged, flagged                              # en demos limpias, nadie
    assert 0.3 < valid["crosshair_deg"].median() < 10      # grados
    assert 100 < valid["ttd_ms"].median() < 1200            # ms
    assert 80 < valid["reaction_ms"].median() < 1000
    s = case["demo"].shots
    f = s[s["is_firearm"]]
    assert 0.03 < f["hit"].mean() < 0.6
    assert 0.3 < f["counter_strafed"].dropna().astype(bool).mean() < 1.0
