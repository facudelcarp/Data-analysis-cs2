"""Informe de rival: lo que un equipo hace en cada mapa, sacado de sus partidas (sin interfaz).

Junta en una hoja por mapa lo que hoy está repartido en varias vistas, pensado para preparar un partido:
resultado por lado, pistolas y qué compra después, cómo ataca (sitio, timing, estrategias), cómo defiende
(agresiones tempranas, retakes), quién juega cada puesto, dónde juega el AWP, sus granadas repetidas y quiénes
son los jugadores que más pesan. Un equipo se identifica por partida y lado (`instances`, ver identity.py), así
que funciona igual con nombres genéricos de matchmaking o FACEIT.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from . import positions, retakes, stats, strategy, tactics
from .parser import DemoData

EARLY_S = 20  # una kill CT antes de esto es una agresión / un pick temprano


@dataclass
class MapReport:
    map: str
    matches: int
    wins: int
    rounds_t: tuple[int, int]            # (ganadas, jugadas)
    rounds_ct: tuple[int, int]
    pistols: pd.DataFrame                # partida, lado, ganó, sitio, compra siguiente
    t_plan: pd.DataFrame                 # plan T (strategy.py), rondas, % ganadas
    ct_setups: pd.DataFrame              # setup CT (A-Mid-B, stack), rondas, % ganadas, agresión, rotación
    sites: pd.DataFrame                  # sitio, rondas, %, plante mediano (s)
    t_entry: dict                        # % rondas T con primera kill a favor, segundo mediano
    ct_aggression: dict                  # % rondas CT con kill propia antes de EARLY_S y zonas
    retake: tuple[int, int]              # (ganados, jugados) como CT
    seats: pd.DataFrame                  # jugador, puesto CT, puesto T (con frecuencia)
    awp: list[dict]                      # por lado: AWPer y zonas de sus kills
    lineups: pd.DataFrame                # granadas repetidas (ambos lados)
    players: pd.DataFrame                # rating, ADR, aperturas en este mapa
    notes: list[str] = field(default_factory=list)  # lo más saliente, en una línea cada cosa
    rounds: pd.DataFrame = field(default_factory=pd.DataFrame)  # lectura de cada ronda (strategy.py) + demo_id, mine_t


def _rate(won: int, n: int) -> str:
    return f"{won}/{n} ({100 * won / n:.0f} %)" if n else "—"


def _mode_share(s: pd.Series) -> str:
    """'B Anchor (3/4)': el valor más común y en cuántas de las veces."""
    s = s.dropna()
    if s.empty:
        return ""
    vc = s.value_counts()
    return f"{vc.index[0]} ({vc.iloc[0]}/{len(s)})" if len(s) > 1 else str(vc.index[0])


def scout(demos: list[DemoData], instances: list[tuple[str, str]]) -> list[MapReport]:
    """Una hoja por mapa (de más a menos partidas) del equipo que juega como `instances` [(demo_id, "A"/"B")]."""
    by_id = {d.demo_id: d for d in demos}
    per_map: dict[str, list[tuple[DemoData, str]]] = {}
    for demo_id, letter in instances:
        d = by_id.get(demo_id)
        if d is not None:
            per_map.setdefault(d.meta["map"], []).append((d, letter))
    out = [_map_report(mp, inst) for mp, inst in per_map.items()]
    return sorted(out, key=lambda r: -r.matches)


def _map_report(map_name: str, inst: list[tuple[DemoData, str]]) -> MapReport:
    wins = 0
    t_won = t_n = ct_won = ct_n = 0
    pistols, strat_rows, t_rounds, ct_rows, seats, awp_k, gren, places, player_rows = [], [], [], [], [], [], [], [], []
    ret_won = ret_n = 0
    for d, L in inst:
        m = d.meta
        mine, theirs = (m["score_a"], m["score_b"]) if L == "A" else (m["score_b"], m["score_a"])
        wins += int(mine > theirs)
        r = d.rounds
        is_t = r["t_team"] == L
        t_n += int(is_t.sum())
        t_won += int((is_t & (r["winner_team"] == L)).sum())
        ct_n += int((~is_t).sum())
        ct_won += int((~is_t & (r["winner_team"] == L)).sum())
        label = f"{m['team_a'] if L == 'B' else m['team_b']} ({mine}-{theirs})"

        # pistolas y la compra de la ronda siguiente
        for _, pr in r[(r["t_buy"] == "Pistola") & (r["ct_buy"] == "Pistola")].iterrows():
            side = "T" if pr["t_team"] == L else "CT"
            nxt = r[r["round"] == pr["round"] + 1]
            nxt_buy = (nxt["t_buy"] if side == "T" else nxt["ct_buy"]).iloc[0] if len(nxt) else ""
            pistols.append({"Rival": label, "Ronda": int(pr["round"]), "Lado": side,
                            "Ganó": pr["winner_team"] == L,
                            "Sitio": pr["bomb_site"] if side == "T" and pr["bomb_site"] else "—",
                            "Compra siguiente": nxt_buy})

        # ataque
        st = strategy.round_strategies(d)
        if len(st):
            strat_rows.append(st.assign(mine_t=st["t_team"] == L, demo_id=d.demo_id, letter=L))
        rt = tactics.round_tactics(d)
        t_rounds.append(rt[rt["t_team"] == L])

        # defensa: agresiones y retakes
        k = d.kills[d.kills["is_enemy_kill"]] if len(d.kills) else d.kills
        ct_rounds = r.loc[~is_t, "round"]
        early = k[(k["round"].isin(ct_rounds)) & (k["attacker_team"] == L) & (k["time_in_round"] <= EARLY_S)]
        ct_rows.append({"rounds": len(ct_rounds), "early_rounds": early["round"].nunique(),
                        "places": early["victim_place"].tolist()})
        ret = retakes.analyze_retakes(d)
        if len(ret):
            mine_ct = ret[ret["round"].isin(ct_rounds)]
            ret_n += len(mine_ct)
            ret_won += int(mine_ct["retake_won"].sum())

        # puestos y AWP
        a = positions.assign_positions(d)
        if len(a):
            seats.append(a[a["team"] == L])
        aw = k[(k["attacker_team"] == L) & k["weapon"].astype(str).str.contains("awp")]
        awp_k.append(aw[["attacker_name", "attacker_side", "victim_place", "time_in_round"]])

        # granadas
        g = d.grenades[d.grenades["thrower_team"] == L] if len(d.grenades) else d.grenades
        if len(g):
            gren.append(g.assign(demo_id=d.demo_id, team_name="rival"))
        places.append(tactics.place_reference(d))

        # jugadores
        ps = stats.player_stats(d)
        player_rows.append(ps[ps["team"] == L])

    st = pd.concat(strat_rows, ignore_index=True) if strat_rows else pd.DataFrame()
    t_plan, ct_setups = pd.DataFrame(), pd.DataFrame()
    if len(st):
        ts, cs = st[st["mine_t"]], st[~st["mine_t"]]
        if len(ts):
            t_plan = strategy.summary_tables(ts, ts["winner_side"] == "T", ts["winner_side"] == "CT")[0]
        if len(cs):
            ct_setups = strategy.summary_tables(cs, cs["winner_side"] == "T", cs["winner_side"] == "CT")[1]
    rt = pd.concat(t_rounds, ignore_index=True) if t_rounds else pd.DataFrame()
    sites = pd.DataFrame()
    entry = {"pct": np.nan, "median_s": np.nan}
    if len(rt):
        sites = rt.groupby("site").agg(Rondas=("round", "size"), plante=("plant_time", "median")).reset_index()
        sites["%"] = (100 * sites["Rondas"] / len(rt)).round(0)
        sites = sites.rename(columns={"site": "Sitio", "plante": "Plante mediano (s)"}).sort_values(
            "Rondas", ascending=False)
        fk = rt[rt["first_kill_side"] != ""]
        entry = {"pct": 100 * (fk["first_kill_side"] == "T").mean() if len(fk) else np.nan,
                 "median_s": float(fk["first_kill_time"].median()) if len(fk) else np.nan}
    ctr = sum(c["rounds"] for c in ct_rows)
    early_n = sum(c["early_rounds"] for c in ct_rows)
    early_places = pd.Series([p for c in ct_rows for p in c["places"] if p]).value_counts().head(3)
    ct_aggr = {"pct": 100 * early_n / ctr if ctr else np.nan, "places": list(early_places.index)}

    seat_df = pd.concat(seats, ignore_index=True) if seats else pd.DataFrame()
    seat_table = pd.DataFrame()
    if len(seat_df):
        rows = []
        for sid, g in seat_df.groupby("steamid"):
            rows.append({"Jugador": g["name"].iloc[-1],
                         "Puesto CT": _mode_share(g.loc[g["side"] == "CT", "position"]),
                         "Puesto T": _mode_share(g.loc[g["side"] == "T", "position"])})
        seat_table = pd.DataFrame(rows).sort_values("Jugador")

    awp = []
    ak = pd.concat(awp_k, ignore_index=True) if awp_k else pd.DataFrame()
    for side in ("CT", "T"):
        s = ak[ak["attacker_side"] == side] if len(ak) else ak
        if len(s):
            who = s["attacker_name"].value_counts()
            awp.append({"side": side, "player": who.index[0], "kills": int(who.iloc[0]),
                        "places": list(s["victim_place"].replace("", np.nan).dropna().value_counts().head(3).index)})

    lu = pd.DataFrame()
    if gren:
        g = pd.concat(gren, ignore_index=True)
        ref = pd.concat(places, ignore_index=True) if places else None
        lu = tactics.lineups(g, min_count=2, places=ref, team_col="team_name")
        if len(lu):
            lu = lu.head(12)

    pl = pd.concat(player_rows, ignore_index=True) if player_rows else pd.DataFrame()
    players = pd.DataFrame()
    if len(pl):
        g = pl.groupby("steamid")
        players = pd.DataFrame({
            "Jugador": g["name"].last(), "Rondas": g["rounds"].sum(),
            "Rating*": g.apply(lambda x: np.average(x["rating2"], weights=x["rounds"]), include_groups=False),
            "ADR": g.apply(lambda x: np.average(x["adr"], weights=x["rounds"]), include_groups=False),
            "Aperturas": g["opening_kills"].sum().astype(int).astype(str) + "-" + g["opening_deaths"].sum()
            .astype(int).astype(str),
            "AWP kills": g["awp_kills"].sum(),
        }).sort_values("Rating*", ascending=False).reset_index(drop=True)

    rep = MapReport(map_name, len(inst), wins, (t_won, t_n), (ct_won, ct_n), pd.DataFrame(pistols), t_plan, ct_setups,
                    sites,
                    entry, ct_aggr, (ret_won, ret_n), seat_table, awp, lu, players)
    rep.notes = _notes(rep)
    rep.rounds = st
    return rep


def _notes(r: MapReport) -> list[str]:
    """Lo que un coach anotaría primero: tendencias claras, con su número."""
    out = []
    (tw, tn), (cw, cn) = r.rounds_t, r.rounds_ct
    if tn and cn:
        better = "T" if tw / tn > cw / cn else "CT"
        out.append(f"Más fuerte de {better}: T {_rate(tw, tn)}, CT {_rate(cw, cn)}.")
    if len(r.sites):
        planted = r.sites[r.sites["Sitio"] != "Sin planta"]
        if len(planted):
            top = planted.iloc[0]
            share = 100 * top["Rondas"] / planted["Rondas"].sum()
            out.append(f"Cuando planta, va al {top['Sitio']} en el {share:.0f} % de las rondas (plante mediano a los "
                       f"{top['Plante mediano (s)']:.0f} s); planta en {planted['Rondas'].sum()} de "
                       f"{r.sites['Rondas'].sum()} rondas T.")
    plans = r.t_plan[r.t_plan["Plan T"].str.contains("Execute|Rush|Golpe")] if len(r.t_plan) else r.t_plan
    if len(plans):  # solo rondas con golpe: las otras no tienen un plan que leer
        top = plans.iloc[0]
        out.append(f"Plan T más usado: {top['Plan T']} ({int(top['Rondas'])} rondas, gana {top['% ganadas']:.0f} %, "
                   f"golpe a los {top['Golpe (s, mediana)']:.0f} s).")
    if len(r.ct_setups):
        top = r.ct_setups.iloc[0]
        total = r.ct_setups["Rondas"].sum()
        out.append(f"Setup CT más usado: {top['Setup CT (A-Mid-B)']} ({int(top['Rondas'])} de {total} rondas, gana "
                   f"{top['% ganadas']:.0f} %).")
    if np.isfinite(r.ct_aggression.get("pct", np.nan)):
        pl = r.ct_aggression["places"]
        out.append(f"De CT consigue una kill antes de los {EARLY_S} s en el {r.ct_aggression['pct']:.0f} % de las "
                   f"rondas" + (f", sobre todo en {', '.join(pl)}." if pl else "."))
    if r.retake[1]:
        out.append(f"Retakes: {_rate(*r.retake)}.")
    if len(r.pistols):
        won = int(r.pistols["Ganó"].sum())
        out.append(f"Pistolas: {_rate(won, len(r.pistols))}.")
        lost = r.pistols[~r.pistols["Ganó"]]
        if len(lost):
            buys = lost["Compra siguiente"].value_counts()
            out.append(f"Después de perder la pistola: {buys.index[0].lower()} ({buys.iloc[0]} de {len(lost)}).")
    for a in r.awp:
        if a["places"]:
            out.append(f"AWP de {a['side']}: {a['player']} ({a['kills']} kills), en {', '.join(a['places'])}.")
    return out


# --------------------------------------------------------------------------------------------
# Exportar (HTML para pasar al equipo o imprimir)
# --------------------------------------------------------------------------------------------

def _table_html(df: pd.DataFrame, decimals: int = 1) -> str:
    from html import escape
    if df is None or df.empty:
        return "<p class='muted'>Sin datos.</p>"

    def fmt(v):
        if isinstance(v, (bool, np.bool_)):
            return "Sí" if v else "No"
        if isinstance(v, (float, np.floating)):
            return "—" if np.isnan(v) else f"{v:.{decimals}f}"
        return escape(str(v))

    head = "".join(f"<th>{escape(str(c))}</th>" for c in df.columns)
    rows = "".join("<tr>" + "".join(f"<td>{fmt(v)}</td>" for v in r) + "</tr>" for r in df.itertuples(index=False))
    return f"<table><thead><tr>{head}</tr></thead><tbody>{rows}</tbody></table>"


LINEUP_COLS = {"grenade": "Granada", "thrower_side": "Lado", "veces": "Veces", "desde": "Desde", "hacia": "Hacia",
               "tiempo_medio": "Segundo", "jugadores": "Quién"}


def to_html(team: str, reports: list[MapReport], source: str = "") -> str:
    from html import escape

    from .maps import pretty_map
    parts = []
    for r in reports:
        (tw, tn), (cw, cn) = r.rounds_t, r.rounds_ct
        lu = r.lineups[[c for c in LINEUP_COLS if c in r.lineups]].rename(columns=LINEUP_COLS) if len(r.lineups) else r.lineups
        parts.append(f"""
<section>
  <h2>{escape(pretty_map(r.map))} <span class='muted'>· {r.matches} partida(s), ganó {r.wins} · T {_rate(tw, tn)} ·
  CT {_rate(cw, cn)}</span></h2>
  <ul class='notes'>{''.join(f'<li>{escape(n)}</li>' for n in r.notes)}</ul>
  <div class='grid'>
    <div><h3>Puestos</h3>{_table_html(r.seats)}</div>
    <div><h3>Jugadores en este mapa</h3>{_table_html(r.players, 2)}</div>
    <div><h3>Sitios atacados (T)</h3>{_table_html(r.sites, 0)}</div>
    <div><h3>Planes de T</h3>{_table_html(r.t_plan, 0)}</div>
    <div><h3>Setups de CT</h3>{_table_html(r.ct_setups, 0)}</div>
  </div>
  <h3>Pistolas</h3>{_table_html(r.pistols)}
  <h3>Granadas repetidas</h3>{_table_html(lu)}
</section>""")
    return f"""<!doctype html><html lang='es'><head><meta charset='utf-8'>
<title>Informe de rival: {escape(team)}</title>
<style>
body {{ font-family: Segoe UI, system-ui, sans-serif; margin: 32px auto; max-width: 1100px; color: #1d2128;
       background: #fff; font-size: 13px; }}
h1 {{ margin: 0 0 4px; }} h2 {{ margin: 28px 0 8px; border-bottom: 2px solid #f0a33d; padding-bottom: 4px; }}
h3 {{ margin: 16px 0 6px; font-size: 13px; text-transform: uppercase; letter-spacing: .04em; color: #555; }}
.muted {{ color: #777; font-weight: normal; font-size: 13px; }}
.notes {{ background: #fff7ea; border-left: 4px solid #f0a33d; padding: 10px 10px 10px 28px; margin: 8px 0; }}
.notes li {{ margin: 3px 0; }}
.grid {{ display: grid; grid-template-columns: 1fr 1fr; gap: 0 24px; }}
table {{ border-collapse: collapse; width: 100%; font-variant-numeric: tabular-nums; }}
th, td {{ text-align: left; padding: 4px 8px; border-bottom: 1px solid #e6e6e6; }}
th {{ background: #f5f5f5; font-size: 12px; }}
section {{ break-inside: avoid-page; }}
@media print {{ body {{ margin: 0; }} h2 {{ break-before: page; }} section:first-of-type h2 {{ break-before: avoid; }} }}
</style></head><body>
<h1>Informe de rival: {escape(team)}</h1>
<p class='muted'>{escape(source)} Generado por CS2 Data Analysis (offline). Puestos según plantillas aprendidas con la
base de posiciones de Harry "NER0" Richards.</p>
{''.join(parts) or "<p>Sin partidas.</p>"}
</body></html>"""
