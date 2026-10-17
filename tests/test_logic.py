"""Tests de la lógica de dominio con datos sintéticos (no requieren demos)."""
import pandas as pd

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
