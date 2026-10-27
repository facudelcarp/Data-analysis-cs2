"""Vista: Análisis integral de equipos para coaches y analistas tácticos."""
from __future__ import annotations

from html import escape

import pandas as pd
import streamlit as st

from . import common as ui
from . import theme
from . import charts
from .. import identity, team_analysis
from ..maps import pretty_map


def render() -> None:
    theme.page_header("Análisis de equipos", "Cómo juega un equipo en todas sus partidas: roles, tradeos, ventajas y mapas.", "Equipo")

    # Obtener todas las demos cargadas
    lib = ui.library()
    demos_list = lib.demos if len(lib) > 0 else list(ui.demos().values())

    if not demos_list:
        ui.empty_state()
        return

    # 1. Selector de Alcance (Demo individual o Toda la biblioteca)
    c_scope, c_team, c_map = st.columns([1.5, 2, 1.5])

    scope_options = ["Toda la biblioteca"]
    if len(demos_list) > 1:
        for i, d in enumerate(demos_list, 1):
            m = d.meta
            scope_options.append(f"Demo #{i}: {m.get('file_name', '')[:25]} ({pretty_map(m.get('map', ''))})")

    scope_sel = c_scope.selectbox("Alcance del análisis", scope_options, key="team_scope_sel")

    # Filtrar conjunto de demos según el alcance
    if scope_sel == "Toda la biblioteca":
        selected_demos = demos_list
    else:
        demo_idx = scope_options.index(scope_sel) - 1
        selected_demos = [demos_list[demo_idx]]

    # 2. Equipos del conjunto, identificados por jugadores en común (ver identity.py)
    groups = identity.cluster_teams(selected_demos)
    if not groups:
        st.info("No se encontraron equipos en las demos seleccionadas.")
        return
    by_key = {g.key: g for g in groups}
    target_key = c_team.selectbox(
        "Equipo a analizar", list(by_key),
        format_func=lambda k: f"{by_key[k].name} ({by_key[k].matches} partida{'s' if by_key[k].matches != 1 else ''})",
        key="team_target_sel")
    group = by_key[target_key]
    target_canonical = group.name

    pos = {d.demo_id: i for i, d in enumerate(demos_list, 1)}
    meta = {d.demo_id: d.meta for d in selected_demos}

    def inst_label(inst: tuple[str, str]) -> str:
        demo_id, letter = inst
        m = meta[demo_id]
        own, rival = (m["team_a"], m["team_b"]) if letter == "A" else (m["team_b"], m["team_a"])
        return f"Partida #{pos.get(demo_id, '?')} · {pretty_map(m['map'])} · como «{own}» vs {rival}"

    included = group.instances
    if group.matches > 1:
        core = ", ".join(group.core_players[:5])
        how = "jugadores en común" if group.linked_by == "jugadores" else "nombre de equipo"
        st.markdown(
            f"<div style='background:rgba(255,255,255,0.03); border-left:3px solid #06d6a0; padding:8px 12px; "
            f"border-radius:4px; margin-bottom:10px; font-size:0.83rem; color:#dcdad5;'>"
            f"💡 <b>{group.matches} partidas unidas por {how}.</b> Núcleo del equipo: {escape(core)}. "
            f"Si alguna partida no corresponde, sacala abajo.</div>", unsafe_allow_html=True)
        included = st.multiselect("Partidas incluidas en el análisis", group.instances, default=group.instances,
                                  format_func=inst_label, key=f"team_inst_{target_key}", placeholder="Elegí…")
        if not included:
            st.warning("⚠️ Elegí al menos una partida para analizar.")
            return

    # 3. Filtro de mapa sobre las partidas incluidas
    maps_in_demos = sorted({meta[d]["map"] for d, _ in included if meta[d].get("map")})
    selected_map = c_map.selectbox(
        "Filtro de mapa", ["Todos los mapas"] + maps_in_demos,
        format_func=lambda m: "Todos los mapas" if m == "Todos los mapas" else pretty_map(m),
        key="team_map_sel")

    # Calcular estadísticas del equipo
    t_stats = team_analysis.analyze_team(
        selected_demos,
        target_team=group.raw_names or [group.name],
        map_name=selected_map,
        display_name=target_canonical,
        instances=set(included),
    )
    if not t_stats or t_stats.get("total_rounds", 0) == 0:
        st.warning(f"No hay suficientes rondas registradas para **{target_canonical}** con los filtros seleccionados.")
        return
    included_names = sorted({(meta[d]["team_a"] if l == "A" else meta[d]["team_b"]) for d, l in included})

    # Subtítulo: con qué nombres jugó (en pugs suele ser "Equipo A/B" o "team_<capitán>")
    variants_subtitle = ""
    if len(included_names) > 1:
        variants_subtitle = f" · Jugó como: {escape(', '.join(included_names))}"

    # Banner del equipo
    st.markdown(
        f"<div style='background:rgba(25, 158, 112, 0.08); border:1px solid rgba(25, 158, 112, 0.3); "
        f"border-radius:10px; padding:14px 18px; margin-bottom:14px; display:flex; justify-content:space-between; align-items:center; flex-wrap:wrap; gap:10px;'>"
        f"<div>"
        f"<div style='font-size:0.75rem; text-transform:uppercase; letter-spacing:1px; color:#06d6a0; font-weight:700;'>Informe de Equipo</div>"
        f"<div style='font-size:1.6rem; font-weight:700; color:#ffffff;'>{escape(target_canonical)}</div>"
        f"<div style='font-size:0.85rem; color:#c3c2b7;'>Filtro: {pretty_map(selected_map) if selected_map != 'Todos los mapas' else 'Todos los mapas'} · {t_stats['matches_played']} partida(s) analizada(s){variants_subtitle}</div>"
        f"</div>"
        f"<div style='display:flex; gap:16px;'>"
        f"<div style='text-align:right;'><span style='font-size:0.75rem; color:#aaa;'>Partidas</span><div style='font-size:1.25rem; font-weight:700;'>{t_stats['matches_won']}V - {t_stats['matches_lost']}D</div></div>"
        f"<div style='text-align:right;'><span style='font-size:0.75rem; color:#aaa;'>Winrate Rondas</span><div style='font-size:1.25rem; font-weight:700; color:#06d6a0;'>{t_stats['round_winrate']:.1f}%</div></div>"
        f"</div>"
        f"</div>",
        unsafe_allow_html=True
    )

    # --- KPIs Macro ---
    ui.kpi_row([
        ("Partidas", f"{t_stats['matches_won']}/{t_stats['matches_played']}", f"{t_stats['match_winrate']:.0f}% winrate"),
        ("Rondas ganadas", f"{t_stats['total_rounds_won']}/{t_stats['total_rounds']}", f"{t_stats['round_winrate']:.1f}% winrate"),
        ("Lado T (Ataque)", f"{t_stats['t_winrate']:.1f}%", f"{t_stats['rounds_t_won']}/{t_stats['rounds_t_played']} rondas"),
        ("Lado CT (Defensa)", f"{t_stats['ct_winrate']:.1f}%", f"{t_stats['rounds_ct_won']}/{t_stats['rounds_ct_played']} rondas"),
        ("Kills de equipo", f"{t_stats['team_kills']:,}", f"{t_stats['team_deaths']:,} muertes"),
        ("Diferencia K-D", f"{t_stats['team_kills'] - t_stats['team_deaths']:+d}", None),
    ])

    st.write("")

    # =========================================================================
    # PESTAÑAS ESTILO DEMO INDIVIDUAL (POR EQUIPO)
    # =========================================================================
    tabs = st.tabs([
        "📊 Scoreboard & Rendimiento",
        "🎭 Roles por Jugador (T & CT)",
        "⚡ Tradeos y Refrags",
        "🎯 Ventajas (5v4 / 4v5)",
        "💣 Utilidad del Equipo",
        "🗺️ Map Pool",
    ])

    with tabs[0]:
        _tab_scoreboard(t_stats, target_canonical)

    with tabs[1]:
        _tab_roles(t_stats)

    with tabs[2]:
        _tab_trades(t_stats, target_canonical)

    with tabs[3]:
        _tab_advantages(t_stats)

    with tabs[4]:
        _tab_utility(t_stats)

    with tabs[5]:
        _tab_map_pool(t_stats)


# =============================================================================
# TAB 1: SCOREBOARD Y DESEMPEÑO
# =============================================================================
def _tab_scoreboard(t_stats: dict, team_name: str) -> None:
    st.subheader(f"Scoreboard del Plantel — {team_name}")
    ps = t_stats.get("team_players_df", pd.DataFrame())
    if ps.empty:
        st.info("Sin estadísticas detalladas de jugadores registradas en las demos seleccionadas.")
        return

    # Highlights del equipo
    def best(col, asc=False):
        x = ps.dropna(subset=[col])
        return x.sort_values(col, ascending=asc).iloc[0] if len(x) else None

    items = []
    if (r := best("rating2")) is not None:
        items.append(("⭐ MVP del equipo", r["name"], f"Rating {r['rating2']:.2f} · {int(r['kills'])}-{int(r['deaths'])}"))
    if (r := best("adr")) is not None:
        items.append(("💥 Más daño (ADR)", r["name"], f"{r['adr']:.1f} de daño por ronda"))
    if (r := best("opening_kills")) is not None and r["opening_kills"] > 0:
        succ = r.get("opening_success_pct", 0.0)
        items.append(("🚪 Aperturas ganadas", r["name"], f"{int(r['opening_kills'])} opening kills ({succ:.0f}%)"))
    if (r := best("clutches_won")) is not None and r["clutches_won"] > 0:
        items.append(("🧊 Clutcher del equipo", r["name"], f"{int(r['clutches_won'])} clutches ganados"))
    if (r := best("trade_kills")) is not None and r["trade_kills"] > 0:
        items.append(("⚡ Más tradeos", r["name"], f"{int(r['trade_kills'])} trade kills"))
    if (r := best("awp_kills")) is not None and r["awp_kills"] >= 3:
        items.append(("🎯 Sniper principal", r["name"], f"{int(r['awp_kills'])} bajas con AWP"))

    if items:
        charts.highlight_cards(items)
        st.write("")

    # Ranking bars de rating
    fig_rating = charts.ranking_bars(
        ps, "rating2", "name",
        ref=1.0, ref_label="1.00 = promedio",
        title=f"¿Quién rindió más en {team_name}? (Rating 2.0 por jugador)"
    )
    st.plotly_chart(fig_rating, width="stretch")
    charts.explain("cada barra es el rating del jugador en este conjunto de partidas. Más de 1.00 es rendimiento positivo. Combina kills, muertes evitadas, daño y KAST.")

    # Tabla Scoreboard completa
    st.dataframe(ui.stat_table(ps, ui.SCOREBOARD_COLS), hide_index=True, width="stretch")
    st.caption(ui.RATING_NOTE)


# =============================================================================
# TAB 2: ROLES Y ARQUETIPOS POR LADO (T VS CT)
# =============================================================================
def _tab_roles(t_stats: dict) -> None:
    st.subheader("🎭 Arquetipos y Roles Tácticos por Lado")
    st.caption("En CS2 competitivo los roles dependen del bando: en T se juega Entry, Refrag o Lurk; en CT se juega Anchor de bombsite o Rotador.")

    ps = t_stats.get("team_players_df", pd.DataFrame())
    player_archs = t_stats.get("player_archetypes", {})
    team_avg_scores = t_stats.get("team_avg_scores", {})

    if ps.empty or not player_archs:
        st.info("Sin datos suficientes de jugadores para clasificar roles.")
        return

    # 1. Matriz de Cobertura de Roles del Equipo
    matrix_rows = []
    for _, prow in ps.iterrows():
        sid = prow["steamid"]
        arch = player_archs.get(sid)
        if not arch:
            continue
        matrix_rows.append({
            "Jugador": prow["name"],
            "Identidad Táctica Dual": arch["dual_badge"],
            "Rol Lado T (Ataque)": f"{arch['t']['icon']} {arch['t']['role']}",
            "Rol Lado CT (Defensa)": f"{arch['ct']['icon']} {arch['ct']['role']}",
            "Rating 2.0": f"{prow['rating2']:.2f}",
            "ADR": f"{prow['adr']:.1f}",
            "KAST %": f"{prow['kast_pct']:.0f}%",
            "Entry W-L": f"{int(prow['opening_kills'])}-{int(prow['opening_deaths'])}",
        })

    if matrix_rows:
        st.markdown("**Matriz Táctica del Plantel:**")
        st.dataframe(pd.DataFrame(matrix_rows), hide_index=True, width="stretch")
        st.write("")

    # 2. Análisis detallado de un jugador del equipo
    names_dict = dict(zip(ps["steamid"], ps["name"]))
    sid = st.selectbox(
        "Ver perfil táctico y radar del jugador:",
        list(names_dict.keys()),
        format_func=names_dict.get,
        key="team_view_player_sel"
    )

    p_arch = player_archs.get(sid)
    p_row = ps[ps["steamid"] == sid].iloc[0]

    if p_arch:
        st.markdown(
            f"<div style='background:rgba(255,209,102,0.06); border:1px solid rgba(255,209,102,0.25); border-radius:10px; padding:14px 18px; margin-bottom:14px;'>"
            f"<div style='display:flex; justify-content:space-between; align-items:center; margin-bottom:10px; flex-wrap:wrap; gap:8px;'>"
            f"<div><span style='font-size:0.75rem; text-transform:uppercase; letter-spacing:1px; color:#ffd166; font-weight:700;'>Identidad Táctica en el Equipo</span>"
            f"<div style='font-size:1.3rem; font-weight:700; color:#f0efec;'>{p_arch['dual_title']}</div></div>"
            f"<div style='font-size:1rem; background:rgba(255,209,102,0.12); border:1px solid #ffd166; padding:4px 12px; border-radius:20px; font-weight:600; color:#ffd166;'>{p_arch['dual_badge']}</div>"
            f"</div>"
            f"<div style='display:grid; grid-template-columns:1fr 1fr; gap:14px; border-top:1px solid rgba(255,255,255,0.08); padding-top:10px;'>"
            f"<div><div style='color:#d95926; font-weight:700; font-size:0.95rem;'>{p_arch['t']['icon']} Lado T (Ataque): {p_arch['t']['role']}</div>"
            f"<div style='color:#bbb; font-size:0.8rem; margin-top:2px;'>{p_arch['t']['desc']}</div></div>"
            f"<div><div style='color:#3987e5; font-weight:700; font-size:0.95rem;'>{p_arch['ct']['icon']} Lado CT (Defensa): {p_arch['ct']['role']}</div>"
            f"<div style='color:#bbb; font-size:0.8rem; margin-top:2px;'>{p_arch['ct']['desc']}</div></div>"
            f"</div>"
            f"</div>",
            unsafe_allow_html=True
        )

        ui.kpi_row([
            ("Rating 2.0*", f"{p_row['rating2']:.2f}", ui.RATING_NOTE),
            ("K / D / A", f"{int(p_row['kills'])} / {int(p_row['deaths'])} / {int(p_row['assists'])}", None),
            ("ADR", f"{p_row['adr']:.1f}", "Daño real por ronda"),
            ("KAST", f"{p_row['kast_pct']:.0f}%", "% rondas con contribución directa"),
            ("HS %", f"{p_row['hs_pct']:.0f}%", None),
            ("Entry W-L", f"{int(p_row['opening_kills'])}-{int(p_row['opening_deaths'])}", "Duelos de apertura ganados-perdidos"),
        ])

        col_radar, col_scores = st.columns([1.4, 1.0])
        with col_radar:
            mode = st.radio(
                "Comparativa del radar",
                ["T vs CT (Ataque vs Defensa)", "General vs Promedio Equipo", "Solo Lado T", "Solo Lado CT"],
                horizontal=True,
                key=f"team_radar_mode_{sid}"
            )
            if mode == "T vs CT (Ataque vs Defensa)":
                fig_rad = charts.player_archetype_radar(
                    scores=p_arch["t"]["scores"], player_name="Lado T (Ataque)", player_color="#d95926",
                    compare_scores=p_arch["ct"]["scores"], compare_name="Lado CT (Defensa)", compare_color="#3987e5",
                    title=f"Perfil táctico de {p_row['name']}: T vs CT"
                )
            elif mode == "Solo Lado T":
                fig_rad = charts.player_archetype_radar(
                    scores=p_arch["t"]["scores"], avg_scores=team_avg_scores,
                    player_name=f"{p_row['name']} (T)", player_color="#d95926",
                    title="Perfil en Ataque (T) vs Promedio Equipo"
                )
            elif mode == "Solo Lado CT":
                fig_rad = charts.player_archetype_radar(
                    scores=p_arch["ct"]["scores"], avg_scores=team_avg_scores,
                    player_name=f"{p_row['name']} (CT)", player_color="#3987e5",
                    title="Perfil en Defensa (CT) vs Promedio Equipo"
                )
            else:
                fig_rad = charts.player_archetype_radar(
                    scores=p_arch["overall"]["scores"], avg_scores=team_avg_scores,
                    player_name=p_row["name"], player_color="#ffd166",
                    title="Dimensiones globales vs Promedio Equipo"
                )
            st.plotly_chart(fig_rad, width="stretch")

        with col_scores:
            st.markdown("**Puntajes del jugador (0 - 100):**")
            scores_df = pd.DataFrame({
                "Eje táctico": list(p_arch["overall"]["scores"].keys()),
                "Lado T": [p_arch["t"]["scores"].get(k, 0) for k in p_arch["overall"]["scores"].keys()],
                "Lado CT": [p_arch["ct"]["scores"].get(k, 0) for k in p_arch["overall"]["scores"].keys()],
                "Global": [p_arch["overall"]["scores"].get(k, 0) for k in p_arch["overall"]["scores"].keys()],
                "Promedio": [team_avg_scores.get(k, 50.0) for k in p_arch["overall"]["scores"].keys()],
            })
            st.dataframe(scores_df, hide_index=True, width="stretch")
            charts.explain("compara las 6 dimensiones tácticas de este jugador entre cuando ataca (T) y cuando defiende (CT).")


# =============================================================================
# TAB 3: EFICIENCIA DE TRADEOS Y REFRAGS
# =============================================================================
def _tab_trades(t_stats: dict, target_canonical: str) -> None:
    st.subheader("⚡ Eficiencia de Tradeos y Refrags")

    ui.kpi_row([
        ("Tasa de Tradeo (Trade %)", f"{t_stats['trade_pct']:.1f}%", f"{t_stats['traded_deaths']}/{t_stats['team_deaths']} muertes vengadas"),
        ("Trade Kills", f"{t_stats['team_trades']}", f"{t_stats['trade_kills_per_round']:.2f} por ronda"),
        ("Reacción media refrag", f"{t_stats['avg_trade_delay']:.2f} s", "Tiempo promedio para vengar al compañero"),
        ("Muertes no tradeadas", f"{t_stats['untraded_deaths']}", "Bajas aisladas sin refrag"),
        ("Winrate con Trade", f"{t_stats['trade_round_winrate']:.1f}%", f"{t_stats['rounds_with_trade']} rondas con ≥1 trade"),
        ("Lift de victoria", f"{t_stats['trade_win_lift']:+.1f}%", "Aumento de winrate al conseguir trade"),
    ])

    c_trade_chart, c_pairs = st.columns([1.2, 1.8])

    with c_trade_chart:
        fig_trade = charts.trade_impact_bars(
            t_stats["trade_round_winrate"],
            t_stats["no_trade_round_winrate"],
            t_stats["trade_win_lift"],
            team_name=target_canonical
        )
        st.plotly_chart(fig_trade, width="stretch")
        charts.explain("compara el porcentaje de victoria en rondas donde el equipo consiguió al menos un refrag vs rondas donde no intercambió. "
                       "Un lift alto indica que el equipo gana casi siempre que juega agrupado y castiga los duelos.")

    with c_pairs:
        st.markdown("**Química de Refrags: ¿Quién refraggea a quién?**")
        pairs_df = t_stats.get("trade_pairs", pd.DataFrame())
        if not pairs_df.empty:
            show_pairs = pairs_df.head(8).rename(columns={
                "refragger": "Cobró el refrag",
                "avenged": "Compañero vengado",
                "trades": "Refrags",
                "avg_delay_s": "Tiempo medio (s)"
            })
            st.dataframe(show_pairs, hide_index=True, width="stretch")
            charts.explain("parejas de jugadores que más se apoyan entre sí en intercambios de bajas y con qué velocidad media reaccionan.")
        else:
            st.caption("Sin suficientes situaciones de refrag registradas.")


# =============================================================================
# TAB 4: VENTAJA NUMÉRICA Y LADOS
# =============================================================================
def _tab_advantages(t_stats: dict) -> None:
    st.subheader("🎯 Ventaja Numérica y Rendimiento por Lado")

    ui.kpi_row([
        ("Conversión 5v4", f"{t_stats['conversion_5v4']:.1f}%", f"Ganó {t_stats['rounds_5v4_won']}/{t_stats['rounds_5v4_total']} aperturas"),
        ("Recuperación 4v5", f"{t_stats['recovery_4v5']:.1f}%", f"Remontó {t_stats['rounds_4v5_won']}/{t_stats['rounds_4v5_total']} aperturas rivales"),
        ("Rondas de pistola", f"{t_stats['pistol_winrate']:.1f}%", f"Ganó {t_stats['pistols_won']}/{t_stats['pistols_played']} pistolas"),
        ("Conversión 2ª ronda", f"{t_stats['followup_conv']:.1f}%", f"Ganó {t_stats['pistol_followups_won']}/{t_stats['pistol_followups_played']} tras ganar pistola"),
        ("Lado T (Ataque)", f"{t_stats['t_winrate']:.1f}%", f"{t_stats['rounds_t_won']}/{t_stats['rounds_t_played']} rondas"),
        ("Lado CT (Defensa)", f"{t_stats['ct_winrate']:.1f}%", f"{t_stats['rounds_ct_won']}/{t_stats['rounds_ct_played']} rondas"),
    ])

    c_adv, c_sides = st.columns([1, 1])

    with c_adv:
        fig_adv = charts.advantage_conversion_bars(t_stats["conversion_5v4"], t_stats["recovery_4v5"])
        st.plotly_chart(fig_adv, width="stretch")
        charts.explain("la conversión 5v4 mide la disciplina para cerrar rondas con ventaja de hombres (ref. pro: ~75%). "
                       "La recuperación 4v5 mide la capacidad de clutch y adaptación al recibir el primer golpe (ref. pro: ~25-30%).")

    with c_sides:
        fig_sides = charts.team_side_winrates_bar(t_stats["t_winrate"], t_stats["ct_winrate"])
        st.plotly_chart(fig_sides, width="stretch")
        charts.explain("compara la solidez del equipo entre atacar y defender. Una diferencia mayor a 15% evidencia un sesgo táctico marcado.")


# =============================================================================
# TAB 5: UTILIDAD DEL EQUIPO
# =============================================================================
def _tab_utility(t_stats: dict) -> None:
    st.subheader("💣 Utilidad Colectiva y por Jugador")

    flashes_en = t_stats["flashes_enemies"]
    flashes_tm = t_stats["flashes_teammates"]
    ratio = round(flashes_en / max(1, flashes_tm), 1)

    ui.kpi_row([
        ("Util ADR colectivo", f"{t_stats['util_adr']:.1f}", "Daño colectivo de utilidades por ronda"),
        ("Daño utilidad total", f"{int(t_stats['util_damage_total']):,}", "Puntos de vida infligidos con HE/molotovs"),
        ("Enemigos cegados", f"{flashes_en}", "Flashes exitosos sobre rivales"),
        ("Team flashes", f"{flashes_tm}", "Flashes que impactaron a compañeros"),
        ("Ratio Ceguera (E / T)", f"{ratio}", "Enemigos cegados por cada compañero flasheado"),
    ])

    st.write("")
    u_df = t_stats.get("team_utility_df", pd.DataFrame())
    if not u_df.empty:
        st.markdown("**Desglose de Utilidad por Jugador del Plantel:**")
        cols_show = ["Jugador", "Rondas", "Util ADR", "Daño Utilidad", "Granadas", "Enemigos cegados", "Tiempo ceguera (s)", "Team Flashes", "Flashes / Ronda"]
        st.dataframe(u_df[cols_show], hide_index=True, width="stretch")
        charts.explain("un Util ADR alto (>5.0) refleja buen control de mapa con daño de HE y molotovs. Un ratio bajo de Team Flashes indica coordinación.")
    else:
        st.caption("Sin datos de utilidad registrados.")


# =============================================================================
# TAB 6: MAP POOL STATS
# =============================================================================
def _tab_map_pool(t_stats: dict) -> None:
    st.subheader("🗺️ Estadísticas por Mapa (Map Pool)")

    map_df = t_stats.get("map_pool", pd.DataFrame())
    if not map_df.empty:
        cols_to_show = ["Mapa", "Partidas", "Winrate Partidas %", "Winrate Rondas %", "Rondas T %", "Rondas CT %", "Trade %", "Conversión 5v4 %", "Util ADR"]
        st.dataframe(map_df[cols_to_show], hide_index=True, width="stretch")
        charts.explain("desglose completo de rendimiento por mapa: winrates por lado, tasa de tradeo colectiva y eficacia en conversión 5v4.")
    else:
        st.caption("Sin datos de mapas suficientes.")
