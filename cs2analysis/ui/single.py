"""Vista: análisis de una demo."""
from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from .. import stats
from ..constants import BUY_ORDER
from ..maps import pretty_map
from ..translate import place_name, weapon_name
from . import common as ui
from . import theme
from .. import micro, archetypes
from . import charts, micro_view, replay_view, tactics_view


def render() -> None:
    theme.page_header("Demo individual", "Una partida a fondo: quién rindió, cómo se dio cada ronda y por qué.", "Partida")
    d = ui.pick_demo("single_demo")
    if d is None:
        ui.empty_state()
        return
    m = d.meta
    ps = stats.player_stats(d)

    theme.match_banner(m, pretty_map(m["map"]))
    c_meta, c_rep = st.columns([3, 1])
    c_meta.caption(f"{m['server']} · {m['file_name']}")
    with c_rep:
        from .. import report
        report_html = report.generate_html_report(d)
        st.download_button("📄 Match Report (HTML)", report_html, file_name=f"report_{m['file_name']}.html",
                           mime="text/html", width="stretch")

    tabs = st.tabs(["Scoreboard", "🎬 Replay 2D", "Ronda a ronda", "Economía", "Jugador", "Duelos", "Aim / micro", "Utilidad",
                    "Tácticas", "Mapa"])
    with tabs[0]:
        _scoreboard(d, ps)
    with tabs[1]:
        replay_view.render(d)
    with tabs[2]:
        _rounds(d)
    with tabs[3]:
        _economy(d)
    with tabs[4]:
        _player(d, ps)
    with tabs[5]:
        _duels(d)
    with tabs[6]:
        micro_view.render(d.duels, d.shots, dict(zip(d.players["steamid"], d.players["name"])),
                          d.meta.get("visibility", ""), key="single_micro",
                          team_of=dict(zip(d.players["steamid"], d.players["team"])))
    with tabs[7]:
        _utility(d, ps)
    with tabs[8]:
        _tactics(d)
    with tabs[9]:
        _map(d)


def _scoreboard(d, ps: pd.DataFrame) -> None:
    names = {"A": d.meta["team_a"], "B": d.meta["team_b"]}
    _highlights(d, ps)

    fig = charts.ranking_bars(ps.assign(team_name=ps["team"].map(names)), "rating2", "name", color_col="team",
                              colors=ui.TEAM_COLORS, ref=1.0, ref_label="1.00 = promedio",
                              title="¿Quién rindió más? (rating por jugador)")
    st.plotly_chart(fig, width="stretch")
    st.markdown(charts.team_legend(names), unsafe_allow_html=True)
    charts.explain("cada barra es el rating del jugador en esta partida. Más de 1.00 es una buena partida y menos de "
                   "0.85, una floja. El rating combina kills, muertes, daño y KAST.")

    for team in ("A", "B"):
        t = ps[ps["team"] == team].sort_values("rating2", ascending=False)
        score = d.meta["score_a"] if team == "A" else d.meta["score_b"]
        st.subheader(f"{names[team]} — {score}")
        st.dataframe(ui.stat_table(t, ui.SCOREBOARD_COLS), hide_index=True, width="stretch")
    st.caption(ui.RATING_NOTE)

    ts = stats.team_stats(d)
    st.subheader("Por lado")
    st.dataframe(ts.rename(columns={"team_name": "Equipo", "side": "Lado", "rounds": "Rondas", "won": "Ganadas",
                                    "win_pct": "% victoria", "pistols_won": "Pistolas ganadas",
                                    "pistols": "Pistolas", "plants": "Plantas"}).drop(columns=["team"]),
                 hide_index=True, width="stretch")


def _highlights(d, ps: pd.DataFrame) -> None:
    """Tarjetas con lo más destacado del partido, para leer en 5 segundos."""
    def best(col, asc=False):
        x = ps.dropna(subset=[col])
        return x.sort_values(col, ascending=asc).iloc[0] if len(x) else None
    items = []
    if (r := best("rating2")) is not None:
        items.append(("⭐ Mejor del partido", r["name"], f"rating {r['rating2']:.2f} · {int(r['kills'])}-{int(r['deaths'])}"))
    if (r := best("adr")) is not None:
        items.append(("💥 Más daño", r["name"], f"{r['adr']:.0f} de daño por ronda"))
    if (r := best("opening_kills")) is not None and r["opening_kills"] > 0:
        items.append(("🚪 Más aperturas ganadas", r["name"], f"{int(r['opening_kills'])} primeras kills"))
    if (r := best("clutches_won")) is not None and r["clutches_won"] > 0:
        items.append(("🧊 Clutches", r["name"], f"{int(r['clutches_won'])} ganados de {int(r['clutches'])}"))
    if d.duels is not None and len(d.duels):
        pm = micro.player_micro(d.duels, d.shots)
        pm = pm[pm["duels_won"].fillna(0) >= 3].dropna(subset=["crosshair_deg"]) if len(pm) else pm
        if len(pm):
            r = pm.sort_values("crosshair_deg").iloc[0]
            items.append(("🎯 Mejor mira", dict(zip(d.players["steamid"], d.players["name"])).get(r["steamid"], "?"),
                          f"{r['crosshair_deg']:.1f}° del rival al verlo"))
    if items:
        charts.highlight_cards(items)
        st.write("")


def _rounds(d) -> None:
    rt = stats.round_timeline(d)
    teams = {"A": d.meta["team_a"], "B": d.meta["team_b"]}
    st.plotly_chart(charts.score_progression(rt, teams), width="stretch")
    charts.explain("cada línea sube un escalón cuando ese equipo gana una ronda. Si las líneas se separan, un equipo "
                   "se está escapando. La línea punteada vertical marca el cambio de lado.")
    st.plotly_chart(charts.round_strip(rt, teams), width="stretch")
    charts.explain(f"una celda por ronda, del color del equipo que la ganó. {charts.ROUND_ICON_LEGEND}.")

    show = rt[["round", "score_a", "score_b", "winner_team", "winner_side", "reason", "duration_s", "first_kill",
               "kills_a", "kills_b", "buy_a", "buy_b", "equip_a", "equip_b", "bomb_site"]].copy()
    show["winner_team"] = show["winner_team"].map(teams)
    st.dataframe(show.rename(columns={
        "round": "Ronda", "score_a": teams["A"], "score_b": teams["B"], "winner_team": "Ganador",
        "winner_side": "Lado", "reason": "Motivo", "duration_s": "Duración (s)", "first_kill": "Entry",
        "kills_a": f"Kills {teams['A']}", "kills_b": f"Kills {teams['B']}", "buy_a": f"Compra {teams['A']}",
        "buy_b": f"Compra {teams['B']}", "equip_a": f"Equipo {teams['A']} $", "equip_b": f"Equipo {teams['B']} $",
        "bomb_site": "Sitio bomba"}), hide_index=True, width="stretch")

    st.subheader("Kill feed")
    rnd = st.select_slider("Ronda", options=list(rt["round"]), key="feed_round")
    k = d.kills[d.kills["round"] == rnd]
    feed = pd.DataFrame({
        "t (s)": k["time_in_round"],
        "Atacante": k["attacker_name"].replace("", "Mundo") + " (" + k["attacker_side"] + ")",
        "Arma": k["weapon"].map(weapon_name) + k["headshot"].map({True: " 🎯", False: ""}),
        "Víctima": k["victim_name"] + " (" + k["victim_side"] + ")",
        "Zona": k["victim_place"].map(place_name),
        "Notas": (k["is_opening"].map({True: "entry ", False: ""}) + k["is_trade"].map({True: "tradeo ", False: ""})
                  + k["thrusmoke"].map({True: "humo ", False: ""}) + k["penetrated"].astype(bool).map({True: "wallbang ", False: ""})
                  + k["noscope"].map({True: "noscope", False: ""})),
    })
    st.dataframe(feed, hide_index=True, width="stretch")


def _economy(d) -> None:
    rt = stats.round_timeline(d)
    teams = {"A": d.meta["team_a"], "B": d.meta["team_b"]}
    st.plotly_chart(charts.economy_lines(rt, teams), width="stretch")
    charts.explain("la altura es cuánto valía el equipo de los 5 jugadores juntos (armas, armadura, granadas). Las franjas "
                   "indican qué tipo de compra es: debajo de $5k es eco y arriba de $20k, full buy. "
                   "Punto lleno = ganó esa ronda; punto vacío = la perdió.")
    st.plotly_chart(charts.buy_win_bars(stats.buy_performance(d), teams, BUY_ORDER), width="stretch")
    charts.explain("para cada tipo de compra, qué porcentaje de esas rondas ganó cada equipo. '3 de 5' = jugó 5 rondas "
                   "con esa compra y ganó 3. Ganar rondas en eco o force es muy bueno; perder full buys, muy caro.")
    with st.expander("Detalle por jugador (valor de equipo en cada ronda)"):
        piv = d.economy.pivot_table(index="name", columns="round", values="equip_value", aggfunc="sum")
        st.dataframe(piv.rename_axis(index="Jugador", columns="Ronda").style.format("${:,.0f}"), width="stretch")


def _player(d, ps: pd.DataFrame) -> None:
    names = dict(zip(ps["steamid"], ps["name"]))
    sid = st.selectbox("Jugador", list(names), format_func=names.get, key="single_player")
    row = ps.set_index("steamid").loc[sid]

    # Arquetipo y roles diferenciados por lado (T vs CT)
    info = archetypes.get_player_side_archetypes(d, sid)
    avg_scores = archetypes.compute_match_average_scores(ps)

    if info:
        st.markdown(
            f"<div style='background:rgba(255,209,102,0.06); border:1px solid rgba(255,209,102,0.25); border-radius:10px; padding:14px 18px; margin-bottom:14px;'>"
            f"<div style='display:flex; justify-content:space-between; align-items:center; margin-bottom:10px; flex-wrap:wrap; gap:8px;'>"
            f"<div><span style='font-size:0.75rem; text-transform:uppercase; letter-spacing:1px; color:#ffd166; font-weight:700;'>Identidad Táctica</span>"
            f"<div style='font-size:1.3rem; font-weight:700; color:#f0efec;'>{info['dual_title']}</div></div>"
            f"<div style='font-size:1rem; background:rgba(255,209,102,0.12); border:1px solid #ffd166; padding:4px 12px; border-radius:20px; font-weight:600; color:#ffd166;'>{info['dual_badge']}</div>"
            f"</div>"
            f"<div style='display:grid; grid-template-columns:1fr 1fr; gap:14px; border-top:1px solid rgba(255,255,255,0.08); padding-top:10px;'>"
            f"<div><div style='color:#d95926; font-weight:700; font-size:0.95rem;'>{info['t']['icon']} Lado T: {info['t']['role']}</div>"
            f"<div style='color:#bbb; font-size:0.8rem; margin-top:2px;'>{info['t']['desc']}</div></div>"
            f"<div><div style='color:#3987e5; font-weight:700; font-size:0.95rem;'>{info['ct']['icon']} Lado CT: {info['ct']['role']}</div>"
            f"<div style='color:#bbb; font-size:0.8rem; margin-top:2px;'>{info['ct']['desc']}</div></div>"
            f"</div>"
            f"</div>",
            unsafe_allow_html=True
        )

    ui.kpi_row([
        ("Rating 2.0*", f"{row['rating2']:.2f}", ui.RATING_NOTE),
        ("K / D / A", f"{int(row['kills'])} / {int(row['deaths'])} / {int(row['assists'])}", None),
        ("ADR", f"{row['adr']:.1f}", "Daño real a rivales por ronda"),
        ("KAST", f"{row['kast_pct']:.0f}%", "Rondas con kill, asistencia, supervivencia o muerte tradeada"),
        ("HS", f"{row['hs_pct']:.0f}%", None),
        ("Entry", f"{int(row['opening_kills'])}-{int(row['opening_deaths'])}", "Duelos de apertura ganados-perdidos"),
    ])

    col_dmg, col_radar = st.columns([1, 1])
    pr = stats.player_rounds(d)
    pr = pr[pr["steamid"] == sid]
    with col_dmg:
        st.plotly_chart(charts.damage_by_round(pr, float(row["adr"])), width="stretch")
        charts.explain("cada barra es el daño que hizo en esa ronda (100 equivale a una kill entera). Arriba de la barra van "
                       "sus kills (2K = dos kills) y 💀 si murió. La línea punteada es su promedio (ADR). El color indica el lado.")
    with col_radar:
        if info:
            mode = st.radio("Vista del radar", ["T vs CT", "General", "Solo T", "Solo CT"], horizontal=True, key=f"radar_mode_{sid}")
            if mode == "T vs CT":
                fig_radar = charts.player_archetype_radar(
                    scores=info["t"]["scores"], player_name="Lado T", player_color="#d95926",
                    compare_scores=info["ct"]["scores"], compare_name="Lado CT", compare_color="#3987e5",
                    title=f"Perfil táctico: T (Ataque) vs CT (Defensa)"
                )
            elif mode == "Solo T":
                fig_radar = charts.player_archetype_radar(
                    scores=info["t"]["scores"], avg_scores=avg_scores, player_name=f"{row['name']} (T)", player_color="#d95926"
                )
            elif mode == "Solo CT":
                fig_radar = charts.player_archetype_radar(
                    scores=info["ct"]["scores"], avg_scores=avg_scores, player_name=f"{row['name']} (CT)", player_color="#3987e5"
                )
            else:
                fig_radar = charts.player_archetype_radar(
                    scores=info["overall"]["scores"], avg_scores=avg_scores, player_name=row["name"], player_color="#ffd166"
                )
            st.plotly_chart(fig_radar, width="stretch")
            charts.explain("6 dimensiones (0-100). En 'T vs CT' compara el cambio de estilo atacando vs defendiendo.")

    c1, c2 = st.columns(2)
    with c1:
        st.markdown("**Armas**")
        ws = stats.weapon_stats(d, sid)
        ws["weapon"] = ws["weapon"].map(weapon_name)
        st.dataframe(ws.rename(columns={"weapon": "Arma", "kills": "Kills", "hs_kills": "HS", "damage": "Daño",
                                        "hits": "Impactos", "shots": "Disparos", "hs_pct": "HS %",
                                        "accuracy_pct": "Precisión %", "class": "Tipo"}),
                     hide_index=True, width="stretch")
    with c2:
        st.markdown("**Clutches**")
        cl = stats.clutches(d)
        cl = cl[cl["steamid"] == sid]
        if cl.empty:
            st.caption("Sin situaciones 1vX.")
        else:
            st.dataframe(pd.DataFrame({"Ronda": cl["round"], "Situación": "1v" + cl["vs"].astype(str),
                                       "Lado": cl["side"], "Resultado": cl["won"].map({True: "✅ Ganado", False: "❌ Perdido"})}),
                         hide_index=True, width="stretch")
        st.markdown("**Contra quién**")
        k = d.kills[d.kills["is_enemy_kill"]]
        vs = pd.concat([k[k["attacker_steamid"] == sid].groupby("victim_name").size().rename("Kills"),
                        k[k["victim_steamid"] == sid].groupby("attacker_name").size().rename("Muertes")], axis=1).fillna(0).astype(int)
        st.dataframe(vs.rename_axis("Rival"), width="stretch")

    st.markdown("**Dónde mata y dónde muere**")
    lower = ui.level_selector(d.meta["map"], "player_level")
    k = d.kills
    kk = ui.on_level(k[(k["attacker_steamid"] == sid) & k["is_enemy_kill"]], "attacker_z", d.meta["map"], lower)
    dd = ui.on_level(k[k["victim_steamid"] == sid], "victim_z", d.meta["map"], lower)
    fig, tf = ui.map_figure(d.meta["map"], height=560, backdrop=d.positions, lower=lower)
    for df, label, color, xcol, ycol in [(kk, "Desde dónde mató", ui.TEAM_COLORS["A"], "attacker_x", "attacker_y"),
                                         (dd, "Dónde murió", ui.SIDE_COLORS["T"], "victim_x", "victim_y")]:
        x, y = tf(df[xcol], df[ycol])
        fig.add_scatter(x=x, y=y, mode="markers", name=label, marker=dict(size=10, color=color, line=dict(width=2, color="#1a1a19")),
                        customdata=df[["round", "weapon", "victim_name", "attacker_name"]],
                        hovertemplate="Ronda %{customdata[0]} · %{customdata[1]}<br>%{customdata[3]} → %{customdata[2]}<extra></extra>")
    st.plotly_chart(fig, width="stretch")
    charts.explain("verde = desde dónde mató el jugador; naranja = dónde murió. Muestra sus posiciones fuertes y "
                   "dónde lo suelen agarrar.")
    ui.radar_hint(d.meta["map"], "radar_dl_player")


def _duels(d) -> None:
    teams = {"A": d.meta["team_a"], "B": d.meta["team_b"]}
    fig = charts.head_to_head(d.kills, d.players, teams)
    if fig is None:
        st.info("Sin kills en la demo.")
        return
    st.plotly_chart(fig, width="stretch")
    charts.explain(f"cada celda es un cruce entre dos rivales. '4-2' = el de la fila mató 4 veces al de la columna y murió "
                   f"2 veces contra él. Color {teams['A']} = gana el de la fila; color {teams['B']} = gana el de la columna; "
                   "gris = parejo.")

    st.plotly_chart(charts.opening_bars(d.kills, d.players), width="stretch")
    charts.explain("la primera kill de cada ronda suele definirla. A la derecha, cuántas veces el jugador hizo la "
                   "primera kill; a la izquierda, cuántas veces fue el primero en morir.")
    o = stats.opening_duels(d)
    if len(o):
        conv = o.groupby("attacker_team").agg(n=("round", "size"), w=("round_won_by_opener", "sum"))
        st.markdown(" · ".join(f"**{teams[t]}** convirtió en victoria {int(r.w)} de sus {int(r.n)} aperturas "
                               f"({100 * r.w / r.n:.0f}%)" for t, r in conv.iterrows() if t in teams))

    st.subheader("Tradeos")
    k = d.kills[d.kills["is_enemy_kill"]]
    tr = k.groupby("victim_team").agg(Muertes=("round", "size"), Tradeadas=("was_traded", "sum"))
    tr.index = tr.index.map(teams)
    tr["% tradeadas"] = (100 * tr["Tradeadas"] / tr["Muertes"]).round(1)
    st.dataframe(tr.rename_axis("Equipo"), width="stretch")
    st.caption("Una muerte está tradeada si un compañero mata al asesino dentro de 5 s.")


def _utility(d, ps: pd.DataFrame) -> None:
    g = d.grenades
    if g.empty:
        st.info("Sin granadas registradas.")
        return
    per = g.groupby(["thrower_name", "grenade"]).size().unstack(fill_value=0)
    flashes = g[g["grenade"] == "Flash"].groupby("thrower_name").agg(
        enemigos=("enemies_blinded", "sum"), ceguera=("blind_time_enemies", "sum"), aliados=("teammates_blinded", "sum"))
    util = ps.set_index("name")[["utility_damage", "flash_assists"]]
    table = per.join(flashes, how="left").join(util, how="left").fillna(0)
    table["ceguera"] = table["ceguera"].round(1)
    team_of = dict(zip(d.players["name"], d.players["team"]))
    chart_df = table.reset_index().rename(columns={"thrower_name": "name"})
    chart_df["team"] = chart_df["name"].map(team_of)
    c1, c2 = st.columns(2)
    c1.plotly_chart(charts.ranking_bars(chart_df, "utility_damage", "name", color_col="team", colors=ui.TEAM_COLORS,
                                        fmt="{:.0f}", title="¿Quién hizo más daño con granadas?"), width="stretch")
    c2.plotly_chart(charts.ranking_bars(chart_df, "enemigos", "name", color_col="team", colors=ui.TEAM_COLORS,
                                        fmt="{:.0f}", title="¿Quién cegó más rivales con flashes?"), width="stretch")
    charts.explain("izquierda: daño total de HE y molotovs/incendiarias. Derecha: cuántas veces una flash del jugador "
                   "cegó a un rival. Color = equipo. La tabla de abajo tiene el detalle, incluidos los aliados cegados.")
    st.dataframe(table.rename_axis("Jugador").rename(columns={
        "enemigos": "Enemigos cegados", "ceguera": "Ceguera a enemigos (s)", "aliados": "Aliados cegados",
        "utility_damage": "Daño de utilidad", "flash_assists": "Asist. flash"}).astype({"Daño de utilidad": int}),
        width="stretch")

    kinds = sorted(g["grenade"].unique())
    sel = st.multiselect("Tipos de granada en el mapa", kinds, default=[k for k in kinds if k in ("Humo", "Fuego")] or kinds, placeholder="Elegí…")
    c1, c2 = st.columns(2)
    side = c1.radio("Lado", ["Ambos", "CT", "T"], horizontal=True, key="util_side")
    with c2:
        lower = ui.level_selector(d.meta["map"], "util_level")
    gg = ui.on_level(g[g["grenade"].isin(sel)], "z", d.meta["map"], lower)
    if side != "Ambos":
        gg = gg[gg["thrower_side"] == side]
    fig, tf = ui.map_figure(d.meta["map"], height=600, backdrop=d.positions, lower=lower)
    for i, kind in enumerate(sel):
        sub = gg[gg["grenade"] == kind]
        x, y = tf(sub["x"], sub["y"])
        fig.add_scatter(x=x, y=y, mode="markers", name=kind,
                        marker=dict(size=11, color=ui.GRENADE_COLORS.get(kind, ui.SERIES[i % len(ui.SERIES)]),
                                    line=dict(width=2, color="#1a1a19")),
                        customdata=sub[["thrower_name", "round", "time_in_round"]],
                        hovertemplate="%{customdata[0]} · ronda %{customdata[1]} · %{customdata[2]:.0f}s<extra>" + kind + "</extra>")
    st.plotly_chart(fig, width="stretch")
    charts.explain("cada punto es dónde cayó una granada (gris = humo, naranja = fuego, amarillo = flash, verde = HE). "
                   "Pasá el mouse para ver quién la tiró y en qué segundo de la ronda.")
    ui.radar_hint(d.meta["map"], "radar_dl_util")


def _tactics(d) -> None:
    from .. import mistakes, tactics
    names = tactics.team_names(d)
    rt = tactics.round_tactics(d)

    # Bloque: Errores críticos y momentos clave
    st.subheader("⚠️ Errores críticos y momentos clave")
    errs = mistakes.detect_mistakes(d)
    if errs.empty:
        st.success("No se detectaron errores críticos evidentes (sin throws notorios de ventaja ni derrotas contra eco).")
    else:
        # Tarjetas de resumen por severidad
        c1, c2, c3 = st.columns(3)
        crit = int((errs["severity"] == "CRÍTICA").sum())
        alta = int((errs["severity"] == "ALTA").sum())
        med = int((errs["severity"] == "MEDIA").sum())
        c1.metric("🔴 Críticos (remontadas 4v2 / 5v3)", crit)
        c2.metric("🟠 Graves (caídas vs eco)", alta)
        c3.metric("🟡 Bajas aisladas / 1ª baja", med)

        for _, e in errs.iterrows():
            sev_color = "#ef476f" if e["severity"] == "CRÍTICA" else ("#ffd166" if e["severity"] == "ALTA" else "#118ab2")
            rnd_txt = f"Ronda {e['round']}" if e["round"] != "-" else "Partido completo"
            st.markdown(
                f"<div style='border:1px solid rgba(255,255,255,0.1);border-left:4px solid {sev_color};"
                f"background:#191918;border-radius:6px;padding:8px 12px;margin-bottom:8px;'>"
                f"<div style='display:flex;justify-content:space-between;align-items:center;'>"
                f"<span style='font-weight:700;font-size:1rem;color:#f0efec;'>{e['title']}</span>"
                f"<span style='font-size:0.8rem;background:rgba(255,255,255,0.08);padding:2px 8px;border-radius:4px;'>{rnd_txt} · {e['team_name']}</span>"
                f"</div>"
                f"<div style='font-size:0.88rem;color:#c3c2b7;margin-top:4px;'>{e['detail']}</div>"
                f"</div>",
                unsafe_allow_html=True
            )
        charts.explain("errores y situaciones determinantes que cambiaron la economía o el curso del partido. "
                       "Revisá esas rondas en la pestaña Replay 2D para ver cómo se posicionaron.")

    st.subheader("Sitios atacados")
    tactics_view.site_block(rt, names)

    # Bloque: Setups y Estrategia Global
    st.subheader("🧠 Estrategias y Setups de Ronda")
    strat_df = tactics.round_strategies(d)
    if not strat_df.empty:
        # Frecuencia de estrategias
        strat_counts = strat_df.groupby("strategy").agg(
            rondas=("round", "size"),
            ganadas=("winner_side", lambda s: (s == "T").sum())
        ).reset_index()
        strat_counts["winrate"] = (100 * strat_counts["ganadas"] / strat_counts["rondas"]).round(0).astype(int)

        col_s1, col_s2 = st.columns([1, 1])
        with col_s1:
            st.markdown("**Estrategias T observadas**")
            st.dataframe(strat_counts.rename(columns={
                "strategy": "Estrategia", "rondas": "Rondas", "ganadas": "T ganó", "winrate": "% Victoria"
            }), hide_index=True, width="stretch")
        with col_s2:
            st.markdown("**Lectura de ronda a ronda**")
            show_strat = strat_df[["round", "strategy", "explanation", "winner_side"]].rename(columns={
                "round": "Ronda", "strategy": "Estrategia", "explanation": "Descripción", "winner_side": "Ganador"
            })
            st.dataframe(show_strat, hide_index=True, width="stretch")
        charts.explain("clasificación automática de la jugada del bando T combinando el timing de primera kill, "
                       "cantidad de utilidad previa y segundo del plantado de bomba.")

    st.subheader("Lineups repetidos")
    tactics_view.lineups_block(d.grenades, tactics.place_reference(d), d.meta["map"], "thrower_team", names,
                               key="single_lu", backdrop=d.positions)

    # Bloque: Post-plant y Retakes
    st.subheader("🎯 Post-plant y Retakes")
    from .. import retakes
    ret_df = retakes.analyze_retakes(d)
    if ret_df.empty:
        st.info("No hubo plantados de bomba en esta partida.")
    else:
        c_ret1, c_ret2 = st.columns(2)
        total_plants = len(ret_df)
        retakes_won = int(ret_df["retake_won"].sum())
        retake_pct = (100 * retakes_won / total_plants) if total_plants > 0 else 0
        c_ret1.metric("Bombas plantadas", total_plants)
        c_ret2.metric("Retakes logrados por CT", f"{retakes_won} ({retake_pct:.0f}%)", help="Rondas donde los CT recuperaron el sitio y ganaron la ronda")
        
        show_ret = ret_df[["round", "site", "situation", "plant_time", "outcome", "outcome_seconds", "retake_won"]].copy()
        show_ret["retake_won"] = show_ret["retake_won"].map({True: "✅ Éxito CT", False: "❌ Retención T"})
        st.dataframe(show_ret.rename(columns={
            "round": "Ronda", "site": "Sitio", "situation": "Situación al plantar (CT v T)",
            "plant_time": "Segundo plantado", "outcome": "Desenlace", "outcome_seconds": "Segundos post-planta",
            "retake_won": "Resultado retake"
        }), hide_index=True, width="stretch")
        charts.explain("muestra cuántos jugadores quedaban vivos de cada bando en el segundo exacto que se plantó el C4 "
                       "y si la defensa CT logró recuperar el sitio o el ataque T aseguró la detonación.")

    st.subheader("Ronda a ronda")
    tactics_view.rounds_block(rt, names)


def _map(d) -> None:
    pos = d.positions
    c1, c2, c3 = st.columns(3)
    layer = c1.radio("Capa", ["Mapa de calor de posiciones", "Kills", "Muertes"], key="map_layer")
    side = c2.radio("Lado", ["Ambos", "CT", "T"], horizontal=True, key="map_side")
    names = {"": "Todos", **dict(zip(d.players["steamid"], d.players["name"]))}
    player = c3.selectbox("Jugador", list(names), format_func=names.get, key="map_player")
    rmin, rmax = int(d.rounds["round"].min()), int(d.rounds["round"].max())
    rr = st.slider("Rondas", rmin, rmax, (rmin, rmax), key="map_rounds") if rmax > rmin else (rmin, rmax)
    tmax = st.slider("Primeros N segundos de la ronda", 5, 175, 175, step=5, key="map_t",
                     help="Útil para ver setups/defaults al inicio de ronda")

    lower = ui.level_selector(d.meta["map"], "map_level")
    fig, tf = ui.map_figure(d.meta["map"], height=680, backdrop=d.positions, lower=lower)
    if layer.startswith("Mapa"):
        p = pos[(pos["round"].between(*rr)) & (pos["time_in_round"] <= tmax)]
        p = ui.on_level(p, "z", d.meta["map"], lower)
        if side != "Ambos":
            p = p[p["side"] == side]
        if player:
            p = p[p["steamid"] == player]
        x, y = tf(p["x"], p["y"])
        # Escala transparente en lo bajo para que se vea el radar debajo; bins finos
        heat = [[0, "rgba(57,135,229,0)"], [0.05, "rgba(57,135,229,0.35)"], [0.35, "rgba(85,152,231,0.7)"],
                [1, "rgba(205,226,251,0.95)"]]
        fig.add_histogram2d(x=x, y=y, nbinsx=140, nbinsy=140, colorscale=heat, zmin=0,
                            showscale=False, hovertemplate="%{z} muestras<extra></extra>")
        charts.explain(f"las zonas más claras son donde más tiempo pasaron los jugadores (con los filtros elegidos). "
                       f"Sirve para ver posiciones habituales y por dónde rota cada lado. {len(p):,} muestras, una cada 0.5 s.")
    else:
        k = d.kills[d.kills["round"].between(*rr) & (d.kills["time_in_round"] <= tmax)]
        k = ui.on_level(k, "victim_z", d.meta["map"], lower)
        if layer == "Kills":
            if side != "Ambos":
                k = k[k["attacker_side"] == side]
            if player:
                k = k[k["attacker_steamid"] == player]
            k = k[k["is_enemy_kill"]]
        else:
            if side != "Ambos":
                k = k[k["victim_side"] == side]
            if player:
                k = k[k["victim_steamid"] == player]
        for s in ("CT", "T"):
            sub = k[(k["attacker_side"] if layer == "Kills" else k["victim_side"]) == s]
            ax, ay = tf(sub["attacker_x"], sub["attacker_y"])
            vx, vy = tf(sub["victim_x"], sub["victim_y"])
            lx, ly = [], []
            for a1, a2, v1, v2 in zip(ax, ay, vx, vy):
                lx += [a1, v1, None]
                ly += [a2, v2, None]
            fig.add_scatter(x=lx, y=ly, mode="lines", line=dict(color=ui.SIDE_COLORS[s], width=1), opacity=0.35,
                            showlegend=False, hoverinfo="skip")
            fig.add_scatter(x=vx, y=vy, mode="markers", name=f"Víctima ({'mató ' if layer == 'Kills' else ''}{s})",
                            marker=dict(size=10, symbol="x", color=ui.SIDE_COLORS[s]),
                            customdata=sub[["attacker_name", "victim_name", "weapon", "round"]],
                            hovertemplate="%{customdata[0]} → %{customdata[1]}<br>%{customdata[2]} · ronda %{customdata[3]}<extra></extra>")
        charts.explain("cada ✕ es dónde murió alguien y la línea va hasta donde estaba quien lo mató. El color es el lado. "
                       "Líneas largas = duelos a distancia; muchas ✕ juntas = una zona donde se pelea seguido.")
    st.plotly_chart(fig, width="stretch")
    ui.radar_hint(d.meta["map"], "radar_dl_map")
