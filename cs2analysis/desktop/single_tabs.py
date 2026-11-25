"""Contenido de cada pestaña de Demo individual. Cada función arma su página la primera vez que se abre."""
from __future__ import annotations

import re
from html import escape

import pandas as pd
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFrame, QLabel, QVBoxLayout, QWidget

from .. import archetypes, prefs, stats
from ..constants import BUY_ORDER
from ..highlights import match_highlights
from ..labels import RATING_NOTE, SCOREBOARD_COLS, TEAM_SIDE_LABELS, stat_table
from ..palette import GRENADE_COLORS, MUTED, SERIES, SIDE_COLORS, TEAM_COLORS, TEXT
from ..parser import DemoData
from ..translate import place_name, weapon_name
from . import charts
from . import widgets as w
from .mapview import MapView, on_level
from .nav import goto_replay
from .page import Combo, IntRange, Page, Segmented, Slider, Slot, kpi_row, level_selector, severity_card
from .widgets import DataTable


def team_names(d: DemoData) -> dict[str, str]:
    return {"A": d.meta["team_a"], "B": d.meta["team_b"]}


# --------------------------------------------------------------------------------------------
# Scoreboard
# --------------------------------------------------------------------------------------------

def scoreboard(d: DemoData) -> QWidget:
    ps = stats.player_stats(d)
    names = team_names(d)
    p = Page()
    if items := match_highlights(d, ps):
        p.add(w.card_row(items))
    p.add(charts.ranking_bars(ps.assign(team_name=ps["team"].map(names)), "rating2", "name", color_col="team",
                              colors=TEAM_COLORS, ref=1.0, ref_label="1.00 = promedio",
                              title="¿Quién rindió más? (rating por jugador)"))
    p.add(w.team_legend(names))
    p.note("cada barra es el rating del jugador en esta partida. Más de 1.00 es una buena partida y menos de "
           "0.85, una floja. El rating combina kills, muertes, daño y KAST.")
    for team in ("A", "B"):
        t = ps[ps["team"] == team].sort_values("rating2", ascending=False)
        score = d.meta["score_a"] if team == "A" else d.meta["score_b"]
        title = w.label(f"{names[team]} — {score}", "Section")
        title.setTextFormat(Qt.PlainText)
        title.setStyleSheet(f"color:{TEAM_COLORS[team]}")
        p.add(title)
        p.add(DataTable(stat_table(t, SCOREBOARD_COLS), fit_rows=True))
    p.caption(RATING_NOTE)
    ts = stats.team_stats(d)
    ts = ts[["team_name", *[c for c in ts.columns if c not in ("team", "team_name")]]].sort_values(["team_name", "side"])
    p.section("Por lado")
    p.add(DataTable(ts.rename(columns=TEAM_SIDE_LABELS), fit_rows=True, decimals=1))
    p.stretch()
    return p


# --------------------------------------------------------------------------------------------
# Ronda a ronda
# --------------------------------------------------------------------------------------------

def rounds(d: DemoData) -> QWidget:
    rt = stats.round_timeline(d)
    teams = team_names(d)
    p = Page()
    p.add(charts.score_progression(rt, teams))
    p.note("cada línea sube un escalón cuando ese equipo gana una ronda. Si las líneas se separan, un equipo "
           "se está escapando. La línea punteada vertical marca el cambio de lado.")
    p.add(charts.round_strip(rt, teams))
    p.note(f"una celda por ronda, del color del equipo que la ganó. {charts.ROUND_ICON_LEGEND}.")
    show = rt[["round", "score_a", "score_b", "winner_team", "winner_side", "reason", "duration_s", "first_kill",
               "kills_a", "kills_b", "buy_a", "buy_b", "equip_a", "equip_b", "bomb_site"]].copy()
    show["winner_team"] = show["winner_team"].map(teams)
    p.add(DataTable(show.rename(columns={
        "round": "Ronda", "score_a": teams["A"], "score_b": teams["B"], "winner_team": "Ganador",
        "winner_side": "Lado", "reason": "Motivo", "duration_s": "Duración (s)", "first_kill": "Entry",
        "kills_a": f"Kills {teams['A']}", "kills_b": f"Kills {teams['B']}", "buy_a": f"Compra {teams['A']}",
        "buy_b": f"Compra {teams['B']}", "equip_a": f"Equipo {teams['A']} $", "equip_b": f"Equipo {teams['B']} $",
        "bomb_site": "Sitio bomba"}), decimals=1,
        on_activate=lambda i: goto_replay(d.demo_id, int(show["round"].iloc[i])))).setMinimumHeight(360)
    p.caption("Doble clic en una ronda para verla en el replay; en el kill feed, para ver ese kill.")

    p.section("Kill feed")
    rnd = Slider("Ronda", int(rt["round"].min()), int(rt["round"].max()), int(rt["round"].min()))
    p.add(rnd)

    def feed() -> QWidget:
        k = d.kills[d.kills["round"] == rnd.value]
        df = pd.DataFrame({
            "t (s)": k["time_in_round"],
            "Atacante": k["attacker_name"].replace("", "Mundo") + " (" + k["attacker_side"] + ")",
            "Arma": k["weapon"].map(weapon_name) + k["headshot"].map({True: " (HS)", False: ""}),
            "Víctima": k["victim_name"] + " (" + k["victim_side"] + ")",
            "Zona": k["victim_place"].map(place_name),
            "Notas": (k["is_opening"].map({True: "entry ", False: ""}) + k["is_trade"].map({True: "tradeo ", False: ""})
                      + k["thrusmoke"].map({True: "humo ", False: ""})
                      + k["penetrated"].astype(bool).map({True: "wallbang ", False: ""})
                      + k["noscope"].map({True: "noscope", False: ""})),
        })
        times = k["time_in_round"].to_numpy(float)
        return DataTable(df, fit_rows=True, decimals=1,
                         on_activate=lambda i: goto_replay(d.demo_id, rnd.value, times[i] - 3))

    slot = p.add(Slot(feed))
    rnd.changed.connect(slot.refresh)
    p.stretch()
    return p


# --------------------------------------------------------------------------------------------
# Economía
# --------------------------------------------------------------------------------------------

def economy(d: DemoData) -> QWidget:
    rt = stats.round_timeline(d)
    teams = team_names(d)
    p = Page()
    p.add(charts.economy_lines(rt, teams))
    p.note("la altura es cuánto valía el equipo de los 5 jugadores juntos (armas, armadura, granadas). Las franjas "
           "indican qué tipo de compra es: debajo de $5k es eco y arriba de $20k, full buy. "
           "Punto lleno = ganó esa ronda; punto vacío = la perdió.")
    p.add(charts.buy_win_bars(stats.buy_performance(d), teams, BUY_ORDER))
    p.note("para cada tipo de compra, qué porcentaje de esas rondas ganó cada equipo. '3 de 5' = jugó 5 rondas "
           "con esa compra y ganó 3. Ganar rondas en eco o force es muy bueno; perder full buys, muy caro.")
    p.section("Detalle por jugador (valor de equipo en cada ronda)")
    piv = d.economy.pivot_table(index="name", columns="round", values="equip_value", aggfunc="sum")
    piv.columns = [str(c) for c in piv.columns]
    p.add(DataTable(piv.reset_index().rename(columns={"name": "Jugador"}), fit_rows=True, decimals=0))
    p.stretch()
    return p


# --------------------------------------------------------------------------------------------
# Jugador
# --------------------------------------------------------------------------------------------

def _identity(info: dict) -> QFrame:
    f = QFrame()
    f.setObjectName("Identity")
    f.setStyleSheet("QFrame#Identity { background: rgba(255,209,102,0.06); border: 1px solid rgba(255,209,102,0.25);"
                    "border-radius: 10px; } QFrame#Identity QLabel { border: none; background: transparent; }")
    v = QVBoxLayout(f)
    v.setContentsMargins(16, 12, 16, 12)

    def lbl(html: str) -> QLabel:
        x = QLabel(html)
        x.setWordWrap(True)
        return x

    v.addWidget(lbl(f"<span style='color:#ffd166;font-size:8pt;font-weight:700'>IDENTIDAD TÁCTICA</span><br>"
                    f"<span style='font-size:13pt;font-weight:700;color:{TEXT}'>{escape(w.plain(info['dual_title']))}</span>"
                    f" &nbsp; <span style='color:#ffd166'>{escape(w.plain(info['dual_badge']))}</span>"))
    row = QWidget()
    from PySide6.QtWidgets import QHBoxLayout
    h = QHBoxLayout(row)
    h.setContentsMargins(0, 6, 0, 0)
    for side, color in (("t", SIDE_COLORS["T"]), ("ct", SIDE_COLORS["CT"])):
        s = info[side]
        h.addWidget(lbl(f"<span style='color:{color};font-weight:700'>Lado {side.upper()}: "
                        f"{escape(s['role'])}</span><br><span style='color:{MUTED}'>{escape(s['desc'])}</span><br>"
                        f"<span style='color:{TEXT}'>{escape(s.get('why', ''))}</span>"), 1)
    v.addWidget(row)
    return f


def player(d: DemoData) -> QWidget:
    ps = stats.player_stats(d)
    names = dict(zip(ps["steamid"], ps["name"], strict=True))
    p = Page()
    pick = Combo("Jugador", sorted(names.items(), key=lambda x: str(x[1]).lower()), value=prefs.me())
    p.add(pick)
    slot = p.add(Slot(lambda: _player_body(d, ps, pick.value)))
    pick.changed.connect(slot.refresh)
    p.stretch()
    return p


def _player_body(d: DemoData, ps: pd.DataFrame, sid: str) -> QWidget:
    p = Page(margins=(0, 0, 0, 0))
    row = ps.set_index("steamid").loc[sid]
    info = archetypes.get_player_side_archetypes(d, sid)
    avg_scores = archetypes.compute_match_average_scores(ps)
    if info:
        p.add(_identity(info))
    p.add(kpi_row([
        ("Rating 2.0*", f"{row['rating2']:.2f}", RATING_NOTE),
        ("K / D / A", f"{int(row['kills'])} / {int(row['deaths'])} / {int(row['assists'])}", None),
        ("ADR", f"{row['adr']:.1f}", "Daño real a rivales por ronda"),
        ("KAST", f"{row['kast_pct']:.0f}%", "Rondas con kill, asistencia, supervivencia o muerte tradeada"),
        ("HS", f"{row['hs_pct']:.0f}%", None),
        ("Entry", f"{int(row['opening_kills'])}-{int(row['opening_deaths'])}", "Duelos de apertura ganados-perdidos"),
    ]))
    pr = stats.player_rounds(d)
    pr = pr[pr["steamid"] == sid]
    left = Page(margins=(0, 0, 0, 0))
    left.add(charts.damage_by_round(pr, float(row["adr"])))
    left.note("cada barra es el daño que hizo en esa ronda (100 equivale a una kill entera). Arriba de la barra van "
              "sus kills (2K = dos kills) y abajo una ✕ si murió. La línea punteada es su promedio (ADR). El color indica el lado.")
    left.stretch()
    right = Page(margins=(0, 0, 0, 0))
    if info:
        mode = Segmented(["T vs CT", "General", "Solo T", "Solo CT"], label="Vista del radar")
        right.add(mode)

        def radar() -> QWidget:
            m = mode.value
            if m == "T vs CT":
                return charts.player_archetype_radar(info["t"]["scores"], player_name="Lado T", player_color="#d95926",
                                                     compare_scores=info["ct"]["scores"], compare_name="Lado CT",
                                                     compare_color="#3987e5",
                                                     title="Perfil táctico: T (Ataque) vs CT (Defensa)")
            if m == "Solo T":
                return charts.player_archetype_radar(info["t"]["scores"], avg_scores, f"{row['name']} (T)", "#d95926")
            if m == "Solo CT":
                return charts.player_archetype_radar(info["ct"]["scores"], avg_scores, f"{row['name']} (CT)", "#3987e5")
            return charts.player_archetype_radar(info["overall"]["scores"], avg_scores, str(row["name"]), "#ffd166")

        rs = right.add(Slot(radar))
        mode.changed.connect(rs.refresh)
        right.note("6 dimensiones (0-100). En 'T vs CT' compara el cambio de estilo atacando vs defendiendo.")
    right.stretch()
    p.row(left, right)

    ws = stats.weapon_stats(d, sid)
    ws["weapon"] = ws["weapon"].map(weapon_name)
    wcol = Page(margins=(0, 0, 0, 0))
    wcol.sub("Armas")
    wcol.add(DataTable(ws.rename(columns={"weapon": "Arma", "kills": "Kills", "hs_kills": "HS", "damage": "Daño",
                                          "hits": "Impactos", "shots": "Disparos", "hs_pct": "HS %",
                                          "accuracy_pct": "Precisión %", "class": "Tipo"}), fit_rows=True, decimals=1))
    wcol.stretch()
    ccol = Page(margins=(0, 0, 0, 0))
    ccol.sub("Clutches")
    cl = stats.clutches(d)
    cl = cl[cl["steamid"] == sid]
    if cl.empty:
        ccol.caption("Sin situaciones 1vX.")
    else:
        crounds = cl["round"].to_numpy()
        ccol.add(DataTable(pd.DataFrame({"Ronda": cl["round"], "Situación": "1v" + cl["vs"].astype(str),
                                         "Lado": cl["side"],
                                         "Resultado": cl["won"].map({True: "Ganado", False: "Perdido"})}),
                           fit_rows=True, on_activate=lambda i: goto_replay(d.demo_id, int(crounds[i]))))
    ccol.sub("Contra quién")
    k = d.kills[d.kills["is_enemy_kill"]]
    vs = pd.concat([k[k["attacker_steamid"] == sid].groupby("victim_name").size().rename("Kills"),
                    k[k["victim_steamid"] == sid].groupby("attacker_name").size().rename("Muertes")],
                   axis=1).fillna(0).astype(int)
    ccol.add(DataTable(vs.rename_axis("Rival").reset_index(), fit_rows=True))
    ccol.stretch()
    p.row(wcol, ccol)

    p.sub("Dónde mata y dónde muere")
    lvl = level_selector(d.meta["map"])
    if lvl:
        p.add(lvl)

    def where() -> QWidget:
        lower = bool(lvl and lvl.value == "Inferior")
        kk = on_level(k[k["attacker_steamid"] == sid], "attacker_z", d.meta["map"], lower)
        dd = on_level(d.kills[d.kills["victim_steamid"] == sid], "victim_z", d.meta["map"], lower)
        m = MapView(d.meta["map"], backdrop=d.positions, lower=lower, height=560)
        for df, label, color, xc, yc in [(kk, "Desde dónde mató", TEAM_COLORS["A"], "attacker_x", "attacker_y"),
                                         (dd, "Dónde murió", SIDE_COLORS["T"], "victim_x", "victim_y")]:
            tips = [f"Ronda {r} · {weapon_name(wp)}\n{a} → {v}" for r, wp, v, a in
                    zip(df["round"], df["weapon"], df["victim_name"], df["attacker_name"], strict=True)]
            m.points(df[xc], df[yc], color, label, tips=tips)
        return m.finish()

    ms = p.add(Slot(where))
    if lvl:
        lvl.changed.connect(ms.refresh)
    p.note("verde = desde dónde mató el jugador; naranja = dónde murió. Muestra sus posiciones fuertes y "
           "dónde lo suelen agarrar. Rueda del mouse = zoom.")
    return p


# --------------------------------------------------------------------------------------------
# Duelos
# --------------------------------------------------------------------------------------------

def duels(d: DemoData) -> QWidget:
    teams = team_names(d)
    p = Page()
    mat = charts.head_to_head(d.kills, d.players, teams)
    if mat is None:
        p.info("Sin kills en la demo.")
        p.stretch()
        return p
    p.add(mat)
    p.note(f"cada celda es un cruce entre dos rivales. '4-2' = el de la fila mató 4 veces al de la columna y murió "
           f"2 veces contra él. Color {teams['A']} = gana el de la fila; color {teams['B']} = gana el de la columna; "
           "gris = parejo.")
    p.add(charts.opening_bars(d.kills, d.players))
    p.note("la primera kill de cada ronda suele definirla. A la derecha, cuántas veces el jugador hizo la "
           "primera kill; a la izquierda, cuántas veces fue el primero en morir.")
    o = stats.opening_duels(d)
    if len(o):
        conv = o.groupby("attacker_team").agg(n=("round", "size"), w=("round_won_by_opener", "sum"))
        p.caption(" · ".join(f"{teams[t]} convirtió en victoria {int(r.w)} de sus {int(r.n)} aperturas "
                             f"({100 * r.w / r.n:.0f}%)" for t, r in conv.iterrows() if t in teams))
    p.section("Tradeos")
    k = d.kills[d.kills["is_enemy_kill"]]
    tr = k.groupby("victim_team").agg(Muertes=("round", "size"), Tradeadas=("was_traded", "sum"))
    tr.index = tr.index.map(teams)
    tr["% tradeadas"] = (100 * tr["Tradeadas"] / tr["Muertes"]).round(1)
    p.add(DataTable(tr.rename_axis("Equipo").reset_index(), fit_rows=True, decimals=1))
    p.caption("Una muerte está tradeada si un compañero mata al asesino dentro de 5 s.")
    p.stretch()
    return p


# --------------------------------------------------------------------------------------------
# Utilidad
# --------------------------------------------------------------------------------------------

def utility(d: DemoData) -> QWidget:
    ps = stats.player_stats(d)
    g = d.grenades
    p = Page()
    if g.empty:
        p.info("Sin granadas registradas.")
        p.stretch()
        return p
    per = g.groupby(["thrower_name", "grenade"]).size().unstack(fill_value=0)
    flashes = g[g["grenade"] == "Flash"].groupby("thrower_name").agg(
        enemigos=("enemies_blinded", "sum"), ceguera=("blind_time_enemies", "sum"), aliados=("teammates_blinded", "sum"))
    util = ps.set_index("name")[["utility_damage", "flash_assists"]]
    table = per.join(flashes, how="left").join(util, how="left").fillna(0)
    table["ceguera"] = table["ceguera"].round(1)
    team_of = dict(zip(d.players["name"], d.players["team"], strict=True))
    chart_df = table.reset_index().rename(columns={"thrower_name": "name"})
    chart_df["team"] = chart_df["name"].map(team_of)
    p.row(charts.ranking_bars(chart_df, "utility_damage", "name", color_col="team", colors=TEAM_COLORS, fmt="{:.0f}",
                              title="¿Quién hizo más daño con granadas?"),
          charts.ranking_bars(chart_df, "enemigos", "name", color_col="team", colors=TEAM_COLORS, fmt="{:.0f}",
                              title="¿Quién cegó más rivales con flashes?"))
    p.note("izquierda: daño total de HE y molotovs/incendiarias. Derecha: cuántas veces una flash del jugador "
           "cegó a un rival. Color = equipo. La tabla de abajo tiene el detalle, incluidos los aliados cegados.")
    p.add(DataTable(table.rename_axis("Jugador").reset_index().rename(columns={
        "enemigos": "Enemigos cegados", "ceguera": "Ceguera a enemigos (s)", "aliados": "Aliados cegados",
        "utility_damage": "Daño de utilidad", "flash_assists": "Asist. flash"}), fit_rows=True, decimals=1))

    kinds_all = sorted(g["grenade"].unique())
    kinds = Segmented(kinds_all, label="Granadas", multi=True,
                      values=[k for k in kinds_all if k in ("Humo", "Fuego")] or kinds_all)
    side = Segmented(["Ambos", "CT", "T"], label="Lado")
    lvl = level_selector(d.meta["map"])
    p.row(*[x for x in (kinds, side, lvl) if x])

    def grenade_map() -> QWidget:
        lower = bool(lvl and lvl.value == "Inferior")
        gg = on_level(g[g["grenade"].isin(kinds.values)], "z", d.meta["map"], lower)
        if side.value != "Ambos":
            gg = gg[gg["thrower_side"] == side.value]
        m = MapView(d.meta["map"], backdrop=d.positions, lower=lower, height=600)
        for i, kind in enumerate(kinds.values):
            sub = gg[gg["grenade"] == kind]
            tips = [f"{kind} · {n} · ronda {r} · {t:.0f}s" for n, r, t in
                    zip(sub["thrower_name"], sub["round"], sub["time_in_round"], strict=True)]
            m.points(sub["x"], sub["y"], GRENADE_COLORS.get(kind, SERIES[i % len(SERIES)]), kind, size=11, tips=tips)
        return m.finish()

    slot = p.add(Slot(grenade_map))
    for x in (kinds, side, lvl):
        if x:
            x.changed.connect(slot.refresh)
    p.note("cada punto es dónde cayó una granada (gris = humo, naranja = fuego, amarillo = flash, verde = HE). "
           "Pasá el mouse para ver quién la tiró y en qué segundo de la ronda.")
    p.stretch()
    return p


# --------------------------------------------------------------------------------------------
# Tácticas
# --------------------------------------------------------------------------------------------

SEVERITY_COLORS = {"CRÍTICA": "#ef476f", "ALTA": "#ffd166", "MEDIA": "#118ab2"}


def tactics_page(d: DemoData) -> QWidget:
    from .. import mistakes, retakes, tactics
    from . import tactics_tab
    names = tactics.team_names(d)
    rt = tactics.round_tactics(d)
    p = Page()

    p.section("⚠️ Errores críticos y momentos clave")
    errs = mistakes.detect_mistakes(d)
    if errs.empty:
        p.info("No se detectaron errores críticos evidentes (sin throws notorios de ventaja ni derrotas contra eco).", "ok")
    else:
        p.add(kpi_row([
            ("Críticos", str(int((errs["severity"] == "CRÍTICA").sum())),
             "Ventaja de 3 o más jugadores desperdiciada (5v2, 4v1…)"),
            ("Graves", str(int((errs["severity"] == "ALTA").sum())),
             "Ventaja de 2 jugadores desperdiciada (4v2, 3v1) o ronda perdida con full buy contra un rival en eco"),
            ("A revisar", str(int((errs["severity"] == "MEDIA").sum())),
             "Patrones de un jugador comparados con el resto de la partida: muere sin tradeo o muere primero "
             "bastante más que los demás"),
        ]))
        for _, e in errs.iterrows():
            rnd = str(e["round"])
            rnd_txt = "Partido completo" if rnd == "-" else (f"Rondas {rnd}" if "," in rnd else f"Ronda {rnd}")
            first = re.match(r"\d+", rnd)
            p.add(severity_card(str(e["title"]), f"{rnd_txt} · {e['team_name']}", str(e["detail"]),
                                SEVERITY_COLORS.get(e["severity"], "#118ab2"),
                                on_click=(lambda r=int(first.group()): goto_replay(d.demo_id, r)) if first else None))
        p.note("errores y situaciones determinantes que cambiaron la economía o el curso del partido. "
               "Clic en una tarjeta para ver esa ronda en el replay.")

    p.section("Sitios atacados")
    tactics_tab.site_block(p, rt, names)

    p.section("🧠 Estrategias de ronda (lado T)")
    strat = tactics.round_strategies(d)
    if not strat.empty:
        counts = strat.groupby("strategy").agg(rondas=("round", "size"),
                                               ganadas=("winner_side", lambda s: (s == "T").sum())).reset_index()
        counts["winrate"] = (100 * counts["ganadas"] / counts["rondas"]).round(0).astype(int)
        left = Page(margins=(0, 0, 0, 0))
        left.sub("Estrategias T observadas")
        left.add(DataTable(counts.rename(columns={"strategy": "Estrategia", "rondas": "Rondas", "ganadas": "T ganó",
                                                  "winrate": "% Victoria"}), fit_rows=True))
        left.stretch()
        right = Page(margins=(0, 0, 0, 0))
        right.sub("Lectura de ronda a ronda")
        srounds = strat["round"].to_numpy()
        right.add(DataTable(strat[["round", "strategy", "explanation", "winner_side"]].rename(columns={
            "round": "Ronda", "strategy": "Estrategia", "explanation": "Descripción", "winner_side": "Ganador"}),
            on_activate=lambda i: goto_replay(d.demo_id, int(srounds[i])))
        ).setMinimumHeight(300)
        p.row(left, right)
        p.note("clasificación automática de la jugada del bando T combinando el timing de primera kill, "
               "cantidad de utilidad previa y segundo del plantado de bomba.")

    p.section("Lineups repetidos")
    tactics_tab.lineups_block(p, d.grenades, tactics.place_reference(d), d.meta["map"], "thrower_team", names,
                              backdrop=d.positions)

    p.section("🎯 Post-plant y retakes")
    ret = retakes.analyze_retakes(d)
    if ret.empty:
        p.info("No hubo plantados de bomba en esta partida.")
    else:
        won = int(ret["retake_won"].sum())
        p.add(kpi_row([("Bombas plantadas", str(len(ret)), None),
                       ("Retakes logrados por CT", f"{won} ({100 * won / len(ret):.0f}%)",
                        "Rondas donde los CT recuperaron el sitio y ganaron la ronda")]))
        show = ret[["round", "site", "situation", "plant_time", "outcome", "outcome_seconds", "retake_won"]].copy()
        show["retake_won"] = show["retake_won"].map({True: "Retake CT", False: "Retención T"})
        p.add(DataTable(show.rename(columns={
            "round": "Ronda", "site": "Sitio", "situation": "Situación al plantar (CT v T)",
            "plant_time": "Segundo plantado", "outcome": "Desenlace", "outcome_seconds": "Segundos post-planta",
            "retake_won": "Resultado retake"}), fit_rows=True, decimals=1,
            on_activate=lambda i: goto_replay(d.demo_id, int(show["round"].iloc[i]),
                                              float(show["plant_time"].iloc[i]) - 5)))
        p.note("muestra cuántos jugadores quedaban vivos de cada bando en el segundo exacto que se plantó el C4 "
               "y si la defensa CT logró recuperar el sitio o el ataque T aseguró la detonación.")

    p.section("Ronda a ronda")
    tactics_tab.rounds_block(p, rt, names, demo_id=d.demo_id)
    p.stretch()
    return p


# --------------------------------------------------------------------------------------------
# Mapa
# --------------------------------------------------------------------------------------------

def map_page(d: DemoData) -> QWidget:
    pos = d.positions
    p = Page()
    layer = Segmented(["Mapa de calor de posiciones", "Kills", "Muertes"], label="Capa")
    side = Segmented(["Ambos", "CT", "T"], label="Lado")
    pl = Combo("Jugador", [("", "Todos"), *sorted(zip(d.players["steamid"], d.players["name"], strict=True),
                                                  key=lambda x: str(x[1]).lower())])
    p.row(layer, side, pl, stretches=[3, 2, 2])
    rmin, rmax = int(d.rounds["round"].min()), int(d.rounds["round"].max())
    rr = IntRange("Rondas", rmin, rmax)
    tmax = Slider("Primeros N segundos de la ronda", 5, 175, 175, step=5, suffix=" s")
    tmax.setToolTip("Útil para ver setups/defaults al inicio de ronda")
    lvl = level_selector(d.meta["map"])
    p.row(*[x for x in (rr, tmax, lvl) if x])
    caption = w.label("", "ReadNote", wrap=True)

    def render() -> QWidget:
        lower = bool(lvl and lvl.value == "Inferior")
        lo, hi = rr.value
        m = MapView(d.meta["map"], backdrop=pos, lower=lower, height=700)
        player_id = pl.value
        if layer.value.startswith("Mapa"):
            x = pos[(pos["round"].between(lo, hi)) & (pos["time_in_round"] <= tmax.value)]
            x = on_level(x, "z", d.meta["map"], lower)
            if side.value != "Ambos":
                x = x[x["side"] == side.value]
            if player_id:
                x = x[x["steamid"] == player_id]
            m.heat(x["x"], x["y"])
            caption.setText(f"Cómo leerlo. Las zonas más claras son donde más tiempo pasaron los jugadores (con los "
                            f"filtros elegidos). Sirve para ver posiciones habituales y por dónde rota cada lado. "
                            f"{len(x):,} muestras, una cada 0.5 s.")
        else:
            kills = layer.value == "Kills"
            k = d.kills[d.kills["round"].between(lo, hi) & (d.kills["time_in_round"] <= tmax.value)]
            k = on_level(k, "victim_z", d.meta["map"], lower)
            col_side = "attacker_side" if kills else "victim_side"
            if side.value != "Ambos":
                k = k[k[col_side] == side.value]
            if player_id:
                k = k[k["attacker_steamid" if kills else "victim_steamid"] == player_id]
            if kills:
                k = k[k["is_enemy_kill"]]
            for s in ("CT", "T"):
                sub = k[k[col_side] == s]
                m.segments(sub["attacker_x"], sub["attacker_y"], sub["victim_x"], sub["victim_y"], SIDE_COLORS[s], alpha=90)
                tips = [f"{a} → {v}\n{weapon_name(wp)} · ronda {r}" for a, v, wp, r in
                        zip(sub["attacker_name"], sub["victim_name"], sub["weapon"], sub["round"], strict=True)]
                m.points(sub["victim_x"], sub["victim_y"], SIDE_COLORS[s],
                         f"Víctima ({'mató ' if kills else ''}{s})", symbol="x", outline=False, tips=tips)
            caption.setText("Cómo leerlo. Cada ✕ es dónde murió alguien y la línea va hasta donde estaba quien lo "
                            "mató. El color es el lado. Líneas largas = duelos a distancia; muchas ✕ juntas = una zona "
                            "donde se pelea seguido.")
        return m.finish()

    slot = p.add(Slot(render))
    p.add(caption)
    for x in (layer, side, pl, rr, tmax, lvl):
        if x:
            x.changed.connect(slot.refresh)
    p.stretch()
    return p
