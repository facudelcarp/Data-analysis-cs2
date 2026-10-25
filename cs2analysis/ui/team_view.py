"""Vista: Análisis integral de equipos para coaches y analistas tácticos."""
from __future__ import annotations

import pandas as pd
import streamlit as st

from . import common as ui
from . import charts
from .. import team_analysis
from ..maps import pretty_map


def render() -> None:
    st.header("👥 Análisis de Equipos")

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

    # 2. Selector de Equipos disponibles en el conjunto
    avail_teams = team_analysis.get_available_teams(selected_demos)
    if not avail_teams:
        st.info("No se encontraron nombres de equipo en las demos seleccionadas.")
        return

    team_names = [t[0] for t in avail_teams]
    target_team = c_team.selectbox(
        "Equipo a analizar",
        team_names,
        format_func=lambda name: f"{name} ({dict(avail_teams).get(name, 0)} partidas)",
        key="team_target_sel"
    )

    # 3. Filtro de Mapa
    maps_in_demos = sorted(list({d.meta.get("map", "") for d in selected_demos if d.meta.get("team_a") == target_team or d.meta.get("team_b") == target_team}))
    map_options = ["Todos los mapas"] + [m for m in maps_in_demos if m]
    selected_map = c_map.selectbox(
        "Filtro de mapa",
        map_options,
        format_func=lambda m: "Todos los mapas" if m == "Todos los mapas" else pretty_map(m),
        key="team_map_sel"
    )

    # Calcular estadísticas del equipo
    t_stats = team_analysis.analyze_team(selected_demos, target_team, map_name=selected_map)
    if not t_stats or t_stats.get("total_rounds", 0) == 0:
        st.warning(f"No hay suficientes rondas registradas para **{target_team}** con los filtros seleccionados.")
        return

    # Banner del equipo
    st.markdown(
        f"<div style='background:rgba(25, 158, 112, 0.08); border:1px solid rgba(25, 158, 112, 0.3); "
        f"border-radius:10px; padding:14px 18px; margin-bottom:14px; display:flex; justify-content:space-between; align-items:center; flex-wrap:wrap; gap:10px;'>"
        f"<div>"
        f"<div style='font-size:0.75rem; text-transform:uppercase; letter-spacing:1px; color:#06d6a0; font-weight:700;'>Informe de Equipo</div>"
        f"<div style='font-size:1.6rem; font-weight:700; color:#ffffff;'>{target_team}</div>"
        f"<div style='font-size:0.85rem; color:#c3c2b7;'>Filtro: {pretty_map(selected_map) if selected_map != 'Todos los mapas' else 'Todos los mapas'} · {t_stats['matches_played']} partida(s) analizada(s)</div>"
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
    # SECCIÓN 1: TRADE ANALYTICS & QUÍMICA DE REFRAGS
    # =========================================================================
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
            team_name=target_team
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

    st.write("")

    # =========================================================================
    # SECCIÓN 2: MAN ADVANTAGE Y LADOS
    # =========================================================================
    st.subheader("🎯 Ventaja Numérica y Rendimiento por Lado")

    ui.kpi_row([
        ("Conversión 5v4", f"{t_stats['conversion_5v4']:.1f}%", f"Ganó {t_stats['rounds_5v4_won']}/{t_stats['rounds_5v4_total']} aperturas"),
        ("Recuperación 4v5", f"{t_stats['recovery_4v5']:.1f}%", f"Remontó {t_stats['rounds_4v5_won']}/{t_stats['rounds_4v5_total']} aperturas rivales"),
        ("Rondas de pistola", f"{t_stats['pistol_winrate']:.1f}%", f"Ganó {t_stats['pistols_won']}/{t_stats['pistols_played']} pistolas"),
        ("Conversión 2ª ronda", f"{t_stats['followup_conv']:.1f}%", f"Ganó {t_stats['pistol_followups_won']}/{t_stats['pistol_followups_played']} tras ganar pistola"),
        ("Util ADR", f"{t_stats['util_adr']:.1f}", "Daño colectivo de utilidades por ronda"),
        ("Enemigos cegados", f"{t_stats['flashes_enemies']}", f"{t_stats['flashes_teammates']} a compañeros"),
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

    st.write("")

    # =========================================================================
    # SECCIÓN 3: MAP POOL STATS
    # =========================================================================
    st.subheader("🗺️ Estadísticas por Mapa (Map Pool)")

    map_df = t_stats.get("map_pool", pd.DataFrame())
    if not map_df.empty:
        cols_to_show = ["Mapa", "Partidas", "Winrate Rondas %", "Rondas T %", "Rondas CT %", "Trade %", "Conversión 5v4 %", "Util ADR"]
        st.dataframe(map_df[cols_to_show], hide_index=True, width="stretch")
        charts.explain("desglose completo de rendimiento por mapa: winrates por lado, tasa de tradeo colectiva y eficacia en conversión 5v4.")
    else:
        st.caption("Sin datos de mapas suficientes.")
