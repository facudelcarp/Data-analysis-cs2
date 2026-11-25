"""Tests de la lógica de dominio con datos sintéticos (no requieren demos)."""
import pandas as pd
import pytest

from cs2analysis.parser import _assign_teams, _build_damages, _build_kills, _RoundIndex, buy_type
from cs2analysis.stats import aggregate


def _snap(rounds_sides):
    rows = []
    for rnd, sides in rounds_sides.items():
        for side, players in sides.items():
            for p in players:
                rows.append({"round": rnd, "tick": rnd * 1000, "steamid": p, "name": p, "side": side,
                             "team_clan_name": "", "rank": 0, "comp_wins": 0, "crosshair_code": ""})
    return pd.DataFrame(rows)


def test_teams_survive_halftime_and_substitutes():
    a, b = ["a1", "a2", "a3"], ["b1", "b2", "b3"]
    snap = _snap({
        1: {"CT": a, "T": b},
        12: {"CT": a, "T": b},
        13: {"CT": b, "T": a},                      # cambio de lado
        14: {"CT": ["b1", "b2", "sub"], "T": a},     # b3 se desconecta, entra un suplente
    })
    rounds = pd.DataFrame({"round": [1, 12, 13, 14]})
    players, side_by_round = _assign_teams(snap, rounds)
    team = dict(zip(players["steamid"], players["team"]))
    assert {team[p] for p in a} == {"A"}
    assert {team[p] for p in b} == {"B"}
    assert team["sub"] == "B"
    assert side_by_round[1]["A"] == "CT" and side_by_round[13]["A"] == "T"
    assert side_by_round[14]["CT"] == "B"


def _kill(tick, att, att_side, vic, vic_side, rnd=1):
    return {"tick": tick, "round": rnd, "time_in_round": tick / 64, "attacker_steamid": att, "attacker_name": att,
            "attacker_team_num": 2 if att_side == "T" else 3, "user_steamid": vic, "user_name": vic,
            "user_team_num": 2 if vic_side == "T" else 3, "assister_steamid": None, "assister_name": None,
            "assister_team_num": None, "weapon": "ak47", "headshot": False, "assistedflash": False}


def test_trades_and_opening():
    df = pd.DataFrame([
        _kill(100, "t1", "T", "c1", "CT"),          # entry
        _kill(200, "c2", "CT", "t1", "T"),          # tradeo (< 5 s)
        _kill(2000, "t2", "T", "c2", "CT"),         # no es tradeo de nadie
        _kill(2100 + 64 * 6, "c3", "CT", "t2", "T"),  # venga a c2 pero fuera de la ventana
    ])
    k = _build_kills(df, {"t1": "B", "t2": "B", "c1": "A", "c2": "A", "c3": "A"})
    assert k["is_opening"].tolist() == [True, False, False, False]
    assert k["is_trade"].tolist() == [False, True, False, False]
    assert k["was_traded"].tolist() == [True, False, False, False]


def test_damage_is_capped_by_remaining_health():
    rows = [
        {"tick": 10, "round": 1, "attacker_steamid": "a", "user_steamid": "v", "attacker_team_num": 2,
         "user_team_num": 3, "weapon": "ak47", "dmg_health": 27, "health": 73, "dmg_armor": 3, "hitgroup": "chest"},
        {"tick": 20, "round": 1, "attacker_steamid": "a", "user_steamid": "v", "attacker_team_num": 2,
         "user_team_num": 3, "weapon": "awp", "dmg_health": 115, "health": 0, "dmg_armor": 0, "hitgroup": "chest"},
    ]
    d = _build_damages(pd.DataFrame(rows), {"a": "A", "v": "B"})
    assert d["dmg_health"].tolist() == [27, 73]
    assert d["dmg_health_raw"].tolist() == [27, 115]


def test_round_index_assigns_ticks():
    rounds = pd.DataFrame({"round": [1, 2], "start_tick": [0, 1000], "official_end_tick": [1000, 2000],
                           "freeze_end_tick": [64, 1064]})
    out = _RoundIndex(rounds).assign(pd.DataFrame({"tick": [0, 64, 1000, 1001, 2500]}))
    assert out["tick"].tolist() == [64, 1000, 1001]
    assert out["round"].tolist() == [1, 1, 2]
    assert out["time_in_round"].tolist() == [0.0, round((1000 - 64) / 64, 2), round((1001 - 1064) / 64, 2)]


def test_buy_type():
    assert buy_type(3000, pistol=True) == "Pistola"
    assert buy_type(3000, pistol=False) == "Eco"
    assert buy_type(12000, pistol=False) == "Force / semi-buy"
    assert buy_type(25000, pistol=False) == "Full buy"


def test_rating1_formula():
    # Jugador "promedio" según HLTV: 0.679 KPR, 0.317 supervivencia, 1.277 multikill -> rating 1.0
    pr = pd.DataFrame({
        "round": range(1000), "steamid": "x", "name": "x", "team": "A", "side": "CT", "equip_value": 0,
        "demo_id": "d",
        "kills": [1] * 679 + [0] * 321, "deaths": [0] * 317 + [1] * 683,
    })
    for c in ["assists", "hs_kills", "damage", "utility_damage", "team_damage", "flash_assists", "enemies_flashed",
              "blind_time", "opening_kills", "opening_deaths", "trade_kills", "traded_deaths", "awp_kills",
              "teamkills", "grenades_thrown"]:
        pr[c] = 0
    pr["kast"] = pr["survived"] = pr["deaths"] == 0
    pr["round_won"] = False
    pr["mvp"] = False
    s = aggregate(pr).iloc[0]
    # el término de multikills con sólo 1K = 0.679/1.277 ≈ 0.53, no 1: comprobamos la fórmula, no el 1.0 exacto
    expected = (0.679 / 0.679 + 0.7 * 0.317 / 0.317 + 0.679 / 1.277) / 2.7
    assert abs(s["rating1"] - round(expected, 2)) < 0.011


def test_throws_respect_fuse_time():
    """Dos flashes seguidas: cada detonación se empareja con su propio lanzamiento, no con el último."""
    from cs2analysis.parser import _attach_throws
    det = pd.DataFrame({"tick": [64 * 10, 64 * 11], "round": 1, "time_in_round": [10.0, 11.0],
                        "grenade": "Flash", "thrower_steamid": "p", "x": 0.0, "y": 0.0, "z": 0.0})
    shots = pd.DataFrame({"tick": [int(64 * 8.3), int(64 * 9.5)], "round": 1, "time_in_round": [8.3, 9.5],
                          "player_steamid": "p", "weapon": "flashbang", "player_x": [100.0, 200.0],
                          "player_y": 0.0, "player_z": 0.0, "player_place": ["A", "B"]})
    out = _attach_throws(det, shots)
    # la flash que explota en 10.0 no puede venir del lanzamiento de 9.5 (mecha ~1.7 s)
    assert out["throw_x"].tolist() == [100.0, 200.0]


def test_lineups_group_by_team_and_spot():
    from cs2analysis.tactics import lineups
    rows = []
    for rnd in range(1, 4):
        for team, tx in (("A", 0.0), ("B", 5000.0)):
            rows.append({"tick": rnd * 1000, "round": rnd, "grenade": "Humo", "thrower_side": "T", "thrower_team": team,
                         "thrower_name": f"p{team}", "x": 1000.0 + rnd, "y": 1000.0, "z": 0.0,
                         "throw_x": tx + rnd * 5, "throw_y": 0.0, "throw_z": 0.0, "throw_place": "Spawn",
                         "throw_time": 3.0, "enemies_blinded": 0})
    lu = lineups(pd.DataFrame(rows))
    assert sorted(lu["team"]) == ["A", "B"]
    assert (lu["veces"] == 3).all()


def test_cs2a_roundtrip_is_compact_and_lossless(tmp_path):
    import numpy as np

    from cs2analysis.parser import TABLES, DemoData
    from cs2analysis.storage import read_cs2a, read_index, write_cs2a
    rng = np.random.default_rng(0)
    n = 20_000
    walk = rng.normal(0, 8, size=(n, 3)).cumsum(axis=0)  # trayectoria continua, como un jugador
    pos = pd.DataFrame({"tick": np.arange(n) * 32, "round": 1, "time_in_round": np.arange(n) / 2,
                        "steamid": "s1", "name": "p", "side": "CT", "team": "A",
                        "x": walk[:, 0].astype("float32"), "y": walk[:, 1].astype("float32"),
                        "z": walk[:, 2].astype("float32"), "health": 100})
    tables = {t: pd.DataFrame() for t in TABLES}
    tables["positions"] = pos
    d = DemoData(meta={"demo_id": "abc", "map": "de_test", "score_a": 1, "score_b": 0}, **tables)
    path = write_cs2a(tmp_path / "t.cs2a", [d, DemoData(meta={**d.meta, "demo_id": "def"}, **tables)])
    assert [e["id"] for e in read_index(path)["demos"]] == ["abc", "def"]
    back = read_cs2a(path, ids=["def"])[0]
    assert back.meta["demo_id"] == "def"
    assert (back.positions["x"] - pos["x"]).abs().max() <= 0.5  # cuantización a 1 unidad
    # 2 demos × 20k posiciones × 3 coordenadas float32 = 480 KB crudos; un random walk es peor caso
    # (las trayectorias reales tienen muchos tramos quietos y comprimen ~2x mejor)
    assert path.stat().st_size < 0.5 * 2 * n * 3 * 4


def test_aim_errors_and_view_convention():
    from cs2analysis.micro import aim_errors
    # mirando al +x (yaw 0, pitch 0) con el objetivo justo enfrente: error 0
    e, ye, pe = aim_errors([0, 0, 64], 0.0, 0.0, [500, 0, 64])
    assert e < 1e-6 and ye < 1e-6 and abs(pe) < 1e-6
    # objetivo 45° a la izquierda (+y): error horizontal 45
    e, ye, pe = aim_errors([0, 0, 64], 0.0, 0.0, [500, 500, 64])
    assert abs(e - 45) < 1e-3 and abs(ye - 45) < 1e-3
    # pitch positivo = mira hacia abajo (convención Source): objetivo a la misma altura => error vertical +10
    e, ye, pe = aim_errors([0, 0, 64], 10.0, 0.0, [500, 0, 64])
    assert abs(pe - 10) < 1e-3


def test_visibility_mesh_wall():
    import numpy as np

    from cs2analysis.geometry import VisibilityMesh
    wall = VisibilityMesh(np.array([[0, -10, -10], [0, 10, -10], [0, 10, 10], [0, -10, 10]], np.float32),
                          np.array([[0, 1, 2], [0, 2, 3]]))
    assert not wall.is_visible([-5, 0, 0], [5, 0, 0])
    assert wall.is_visible([-5, 0, 0], [-5, 5, 0])
    assert wall.is_visible([-5, 20, 0], [5, 20, 0])  # pasa al costado de la pared
    vis = wall.visible_many([[-5, 0, 0], [-5, 20, 0]], [[5, 0, 0], [5, 20, 0]])
    assert vis.tolist() == [False, True]


def test_shot_enrichment_bursts_and_counter_strafe():
    from cs2analysis.micro import enrich_shots
    shots = pd.DataFrame({"tick": [100, 106, 112, 400], "round": 1, "player_steamid": "p", "weapon": "ak47"})
    # quieto en los primeros 3 disparos, corriendo a ~210 u/s en el último
    pos = {"p": pd.DataFrame({"X": [0.0, 0, 0, 0, 0, 0, 0, 6.6], "Y": 0.0},
                             index=[98, 100, 104, 106, 110, 112, 398, 400])}
    damages = pd.DataFrame({"tick": [106], "attacker_steamid": "p", "is_enemy": True, "weapon": "ak47", "hitgroup": "head"})
    s = enrich_shots(shots, damages, pos)
    assert s["burst_index"].tolist() == [1, 2, 3, 1]
    assert s["hit"].tolist() == [False, True, False, False]
    assert s["hit_head"].tolist() == [False, True, False, False]
    assert s["counter_strafed"].tolist() == [True, True, True, False]


def _team_demo(demo_id, name_a, roster_a, name_b, roster_b):
    from cs2analysis.parser import TABLES, DemoData
    players = pd.DataFrame({"steamid": roster_a + roster_b, "name": [f"p{s}" for s in roster_a + roster_b],
                            "team": ["A"] * len(roster_a) + ["B"] * len(roster_b)})
    tables = {t: pd.DataFrame() for t in TABLES}
    tables["players"] = players
    return DemoData(meta={"demo_id": demo_id, "team_a": name_a, "team_b": name_b, "map": "de_x"}, **tables)


def test_teams_are_identified_by_players_not_generic_names():
    from cs2analysis.identity import cluster_teams
    r1, r2, r3, r4 = list("abcde"), list("fghij"), list("klmno"), list("pqrst")
    demos = [
        _team_demo("d1", "Equipo A", r1, "Equipo B", r2),
        # mismo nombre "Equipo A" pero otros jugadores: NO es el mismo equipo
        _team_demo("d2", "Equipo A", r3, "Equipo B", r4),
        # el roster r1 con dos suplentes y del otro lado: SÍ es el mismo equipo
        _team_demo("d3", "Equipo A", r4, "Equipo B", r1[:3] + ["x", "y"]),
    ]
    groups = cluster_teams(demos)
    by_inst = {inst: g for g in groups for inst in g.instances}
    assert by_inst[("d1", "A")] is by_inst[("d3", "B")]
    assert by_inst[("d1", "A")] is not by_inst[("d2", "A")]
    assert by_inst[("d2", "B")] is by_inst[("d3", "A")]
    assert by_inst[("d1", "A")].name.startswith("Equipo de ")  # sin nombre real, se nombra por jugadores


def test_real_team_names_still_link_and_sides_never_merge():
    from cs2analysis.identity import cluster_teams
    demos = [
        _team_demo("d1", "BESTIA", list("abcde"), "Rival", list("fghij")),
        _team_demo("d2", "BESTIA Esports", list("klmno"), "Otro", list("pqrst")),
        # roster compartido 3 y 3 entre los dos lados de la misma partida: no se pueden unir entre sí
        _team_demo("d3", "X", list("abcxy"), "Y", list("fghzw")),
    ]
    groups = cluster_teams(demos)
    by_inst = {inst: g for g in groups for inst in g.instances}
    assert by_inst[("d1", "A")] is by_inst[("d2", "A")]          # mismo tag real
    assert by_inst[("d1", "A")].name == "BESTIA"
    for g in groups:
        demos_in = [d for d, _ in g.instances]
        assert len(demos_in) == len(set(demos_in))               # nunca los dos lados de una partida


def test_roles_require_volume_not_just_percentages():
    from cs2analysis.archetypes import calculate_player_scores, classify_t_role
    base = {"rounds": 12, "kills": 10, "deaths": 8, "awp_kills": 0, "trade_kills": 1, "clutches_won": 0,
            "opening_attempts": 1, "opening_kills": 1, "opening_success_pct": 100.0, "survived": 4, "kpr": 0.8,
            "kast_pct": 70.0, "adr": 80.0, "utility_adr": 2.0, "enemies_flashed": 2, "hs_pct": 50.0, "rating2": 1.0}
    one_lucky_opening = pd.Series(base)
    assert classify_t_role(calculate_player_scores(one_lucky_opening), one_lucky_opening)[0] != "Entry Fragger"
    entry = pd.Series({**base, "opening_attempts": 5, "opening_kills": 3, "opening_success_pct": 60.0})
    assert classify_t_role(calculate_player_scores(entry), entry)[0] == "Entry Fragger"
    awper = pd.Series({**base, "awp_kills": 6})
    assert "AWPer" in classify_t_role(calculate_player_scores(awper), awper)[0]


def test_swapped_clan_names_are_fixed_by_roster():
    from cs2analysis.identity import fix_swapped_names
    nz, fz = list("abcde"), list("fghij")
    demos = [_team_demo(f"d{i}", "9z", nz, "FaZe Clan", fz) for i in range(3)]
    demos.append(_team_demo("bad", "9z", fz, "FaZe Clan", nz))  # el juego dejó los tags cruzados
    assert fix_swapped_names(demos) == ["bad"]
    assert demos[-1].meta["team_a"] == "FaZe Clan" and demos[-1].meta["team_b"] == "9z"
    assert fix_swapped_names(demos) == []  # idempotente


def test_report_escapes_names_from_the_demo():
    """Los nicks vienen de la demo y el reporte es un HTML descargable: un nick no puede inyectar HTML."""
    from pathlib import Path

    from cs2analysis.report import generate_html_report
    from cs2analysis.storage import read_cs2a
    d = read_cs2a(Path(__file__).parent / "fixtures" / "pro_sample.cs2a")[0]
    d.economy["name"] = "<script>alert(1)</script>"
    d.meta["team_a"] = "<img src=x onerror=1>"
    html = generate_html_report(d)
    assert "<script>alert" not in html and "<img src=x" not in html
    assert "&lt;script&gt;" in html


def _round_demo(econ, kills, bomb, winner_side="T", end_tick=10_000):
    from cs2analysis.parser import TABLES, DemoData
    tables = {t: pd.DataFrame() for t in TABLES}
    tables["rounds"] = pd.DataFrame([{"round": 1, "ct_team": "A", "t_team": "B", "winner_side": winner_side,
                                      "end_tick": end_tick}])
    tables["economy"] = pd.DataFrame([{"round": 1, "steamid": s, "side": side} for s, side in econ])
    tables["kills"] = pd.DataFrame([{"tick": t, "round": 1, "time_in_round": t / 64, "victim_steamid": v,
                                     "victim_side": side, "is_enemy_kill": True} for t, v, side in kills])
    tables["bomb"] = pd.DataFrame([{"tick": t, "round": 1, "time_in_round": t / 64, "event_code": e,
                                    "site_letter": "A"} for t, e in bomb])
    return DemoData(meta={"demo_id": "x", "team_a": "A", "team_b": "B", "map": "de_x"}, **tables)


def test_retakes_count_who_actually_played_the_round():
    """Vivos al plantar según quién jugó la ronda, no 5v5 fijo; las kills de salida no cuentan."""
    from cs2analysis.retakes import analyze_retakes
    d = _round_demo(econ=[("c1", "CT"), ("c2", "CT"), ("t1", "T"), ("t2", "T")],
                    kills=[(640, "c1", "CT"), (3200, "c2", "CT"), (20_000, "t1", "T")],
                    bomb=[(1280, "bomb_planted")])
    r = analyze_retakes(d).iloc[0]
    assert r["situation"] == "1v2"
    assert r["outcome"] == "Eliminación" and r["outcome_seconds"] == round((3200 - 1280) / 64, 1)


def test_strategy_timing_wins_over_utility():
    from cs2analysis.tactics import classify_strategy
    nan = float("nan")
    assert classify_strategy(20, 10, "A", 5, 3)[0] == "Fast Rush A"
    assert classify_strategy(80, 30, "B", 6, 4)[0].startswith("Ataque tardío")  # antes salía "Execute"
    assert classify_strategy(50, 30, "A", 4, 2)[0] == "Execute coordinado A"
    assert classify_strategy(50, 30, "A", 1, 2)[0] == "Ataque con poca utilidad A"  # antes "Estrategia estándar"
    assert classify_strategy(nan, 12, "Sin planta", 0, 3)[0].startswith("Duelo temprano")
    assert classify_strategy(nan, nan, "Sin planta", 0, 0)[0] == "Sin contacto"


def test_replay_rounds_and_interpolation():
    """Cada ronda del fixture se arma para el replay; las cegueras sin time_in_round se calculan por tick."""
    from pathlib import Path

    import numpy as np

    from cs2analysis import replay, stats
    from cs2analysis.storage import read_cs2a
    d = read_cs2a(Path(__file__).parent / "fixtures" / "pro_sample.cs2a")[0]
    rt = replay.tag_round_buys(stats.round_timeline(d), {"A": "a", "B": "b"})
    opts = replay.filter_options(rt)
    assert next(iter(opts.values())) == rt["round"].tolist()
    assert all(set(r) <= set(rt["round"]) for r in opts.values())
    for r in rt["round"]:
        rr = replay.build_round(d, int(r))
        assert rr is not None and rr.tracks and rr.t_max > rr.t_min
        assert rr.blinds["t"].between(-20, 200).all()
    tr = replay.Track("x", "x", "CT", "A", np.array([0.0, 1.0]), np.array([0.0, 10.0]), np.array([0.0, 0.0]),
                      np.array([100.0, 50.0]))
    x, y, hp, ang, speed = tr.at(0.5)
    assert (x, y, hp) == (5.0, 0.0, 75.0) and speed == 10.0
    assert tr.at(-1)[:3] == (0.0, 0.0, 100.0) and tr.at(9)[:3] == (10.0, 0.0, 50.0)


def test_player_routes_cut_to_the_time_window():
    """Una ruta por ronda del lado pedido, recortada a la ventana de tiempo, con resultado y muerte."""
    from pathlib import Path

    from cs2analysis import routes
    from cs2analysis.storage import read_cs2a
    demos = read_cs2a(Path(__file__).parent / "fixtures" / "pro_sample.cs2a")
    d = demos[0]
    sid = d.players["steamid"].iloc[0]
    maps = routes.player_maps(demos, sid)
    assert maps == {d.meta["map"]: 1}
    rs = routes.player_routes(demos, sid, d.meta["map"], "T", 0, 20)
    t_rounds = set(d.positions.loc[(d.positions["steamid"] == sid) & (d.positions["side"] == "T"), "round"])
    assert rs and {r.round for r in rs} <= t_rounds
    assert all(r.t.min() >= 0 and r.t.max() <= 20 and len(r.x) == len(r.t) for r in rs)
    rounds = d.rounds.set_index("round")
    team = d.players.set_index("steamid")["team"][sid]
    assert all(r.won == (rounds.loc[r.round, "winner_team"] == team) for r in rs)
    # filtro de compra: solo rondas con esa compra del equipo del jugador
    full = routes.player_routes(demos, sid, d.meta["map"], "T", 0, 20, buy="Full buy")
    assert all(r.buy == "Full buy" for r in full) and len(full) <= len(rs)


def test_profile_percentiles_and_me_guess():
    from cs2analysis import prefs, profile
    lb = pd.DataFrame({"steamid": list("abcdef"), "rounds": [100] * 6, "rating2": [1.3, 1.1, 1.0, 0.9, 0.8, 0.7],
                       "dpr": [0.5, 0.6, 0.7, 0.8, 0.9, 1.0], "trade_kills": 10, "flash_assists": 5,
                       "traded_deaths": 10, "deaths": 60, "clutches": 0, "clutches_won": 0})
    pc = profile.percentiles(lb, "a").set_index("metric")
    assert pc.loc["rating2", "pct"] == 100 and pc.loc["dpr", "pct"] == 100  # menos muertes = mejor
    assert profile.percentiles(lb, "f").set_index("metric").loc["rating2", "pct"] == 0
    assert "clutch_pct" not in pc.index  # sin clutches suficientes no se compara

    players = pd.DataFrame({"steamid": ["me", "x", "y"], "demos": [9, 3, 3]})
    assert profile.likely_me(players, 10) == "me"
    assert profile.likely_me(players.assign(demos=[4, 3, 3]), 10) is None  # nadie está en casi todas
    assert profile.likely_me(players, 2) is None

    prefs.set_me("me")
    assert prefs.me() == "me"
    prefs.set_me(None)
    assert prefs.me() is None


def test_recent_form_orders_by_date():
    from cs2analysis import profile
    per = pd.DataFrame({"demo_id": list("abcdefgh"), "rounds": 24, "rating2": [0.8] * 3 + [1.2] * 5,
                        "adr": [60] * 3 + [90] * 5, "Resultado": ["Derrota"] * 3 + ["Victoria"] * 5})
    order = {d: f"2026-01-0{i + 1}" for i, d in enumerate("abcdefgh")}
    f = profile.recent_form(per, order)
    assert f["rating_last"] == pytest.approx(1.2) and f["rating_before"] == pytest.approx(0.8)
    assert f["wins_last"] == 5
    assert profile.recent_form(per.head(5), order) is None


def test_positions_assign_one_seat_each_and_roles():
    """Puestos por posición: con las plantillas del repo, cada equipo reparte sus 5 puestos sin repetir."""
    from pathlib import Path

    from cs2analysis import positions
    from cs2analysis.storage import read_cs2a
    if not positions.templates():
        pytest.skip("sin assets/positions/templates.npz")
    demos = [d for d in read_cs2a(Path(__file__).parent / "fixtures" / "pro_sample.cs2a")
             if positions.available(d.meta["map"])]
    if not demos:
        pytest.skip("el fixture no tiene mapas con plantillas")
    a = pd.concat([positions.assign_positions(d).assign(map=d.meta["map"]) for d in demos])
    for _, g in a.groupby(["map", "team", "side"]):
        if len(g) == 5:
            assert g["position"].is_unique
    assert set(a["position"]) <= {p for t in positions.templates().values() for s in t.labels.values() for p in s}
    roles = positions.player_roles(a)
    assert set(roles["role"]) <= {"AWPer", "Anchor", "Mixed", "Rotator", "Lurker", "Flex", "Spacetaker"}
    assert positions.role_name("CT", 0.1) == "Anchor" and positions.role_name("T", 0.9) == "Spacetaker"


def test_death_review_flags_and_order():
    from pathlib import Path

    from cs2analysis import deaths
    from cs2analysis.storage import read_cs2a
    d = read_cs2a(Path(__file__).parent / "fixtures" / "pro_sample.cs2a")[0]
    sid = d.kills["victim_steamid"].value_counts().index[0]
    x = deaths.player_deaths(d, sid)
    assert len(x) > 0 and x["priority"].is_monotonic_decreasing
    ends = d.rounds.set_index("round")["end_tick"]
    assert (x["tick"] <= x["round"].map(ends)).all()  # las muertes después del final de ronda no cuentan
    for _, r in x.iterrows():
        assert len(r["reasons"]) == sum(bool(r[c]) for c, _, _ in deaths.SIGNALS)
        assert not (r["opening_untraded"] and r["untraded"])
        assert r["in_advantage"] == (r["mates_alive"] > r["enemies_alive"])
    s = deaths.summary(x)
    assert all(0 <= v <= 100 for v in s.values())


def test_scouting_report_per_map():
    from pathlib import Path

    from cs2analysis import identity, scouting
    from cs2analysis.storage import read_cs2a
    demos = read_cs2a(Path(__file__).parent / "fixtures" / "pro_sample.cs2a")
    g = max(identity.cluster_teams(demos), key=lambda x: x.matches)
    reps = scouting.scout(demos, g.instances)
    assert 1 <= len(reps) <= g.matches
    for r in reps:
        (tw, tn), (cw, cn) = r.rounds_t, r.rounds_ct
        assert 0 <= tw <= tn and 0 <= cw <= cn and tn + cn > 0
        assert len(r.notes) >= 2 and (r.sites.empty or abs(r.sites["%"].sum() - 100) <= 2)
        assert len(r.players) >= 5
    html = scouting.to_html("<b>rival</b>", reps)
    assert "&lt;b&gt;rival&lt;/b&gt;" in html and "<b>rival</b>" not in html
