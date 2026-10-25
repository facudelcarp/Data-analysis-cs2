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

    # 2. Selector de Equipos disponibles en el conjunto (agrupados por palabras no genéricas)
    grouped_teams = team_analysis.get_grouped_teams(selected_demos)
    if not grouped_teams:
        st.info("No se encontraron nombres de equipo en las demos seleccionadas.")
        return

    groups_by_name = {g["canonical_name"]: g for g in grouped_teams}
    group_options = list(groups_by_name.keys())

    target_canonical = c_team.selectbox(
        "Equipo a analizar",
        group_options,
        format_func=lambda name: (
            f"{name} ({groups_by_name[name]['matches']} partida{'s' if groups_by_name[name]['matches'] != 1 else ''}"
            + (f" · {len(groups_by_name[name]['raw_names'])} variantes)" if len(groups_by_name[name]['raw_names']) > 1 else ")")
        ),
        key="team_target_sel"
    )

    selected_group = groups_by_name[target_canonical]
    raw_variants = selected_group["raw_names"]

    # Si hay múltiples variantes agrupadas, permitimos desmarcar / sacar si alguna está bug o es distinta
    if len(raw_variants) > 1:
        st.markdown(
            f"<div style='background:rgba(255, 255, 255, 0.03); border-left:3px solid #06d6a0; padding:8px 12px; border-radius:4px; margin-bottom:10px; font-size:0.83rem; color:#dcdad5;'>"
            f"💡 <b>Variantes agrupadas automáticamente:</b> Se detectaron {len(raw_variants)} variantes para este equipo en las demos cargadas. "
            f"Si alguna variante no corresponde o está bug, puedes desmarcarla a continuación para excluirla del análisis."
            f"</div>",
            unsafe_allow_html=True
        )
        included_names = st.multiselect(
            "Variantes de nombre incluidas en el análisis:",
            options=raw_variants,
            default=raw_variants,
            key=f"team_variants_{target_canonical}",
            help="Desmarca una variante para sacarla si fue agrupada por error o tiene datos bugeados."
        )
        if not included_names:
            st.warning("⚠️ Debes seleccionar al menos una variante de nombre para realizar el análisis.")
            return
    else:
        included_names = raw_variants

    # 3. Filtro de Mapa basado en las variantes activas
    maps_in_demos = sorted(list({
        d.meta.get("map", "") for d in selected_demos
        if (d.meta.get("team_a") in included_names or d.meta.get("team_b") in included_names)
    }))
    map_options = ["Todos los mapas"] + [m for m in maps_in_demos if m]
    selected_map = c_map.selectbox(
        "Filtro de mapa",
        map_options,
        format_func=lambda m: "Todos los mapas" if m == "Todos los mapas" else pretty_map(m),
        key="team_map_sel"
    )

    # Calcular estadísticas del equipo
    t_stats = team_analysis.analyze_team(
        selected_demos,
        target_team=included_names,
        map_name=selected_map,
        display_name=target_canonical,
    )
    if not t_stats or t_stats.get("total_rounds", 0) == 0:
        st.warning(f"No hay suficientes rondas registradas para **{target_canonical}** con los filtros seleccionados.")
        return

    # Subtítulo informativo si hay variantes
    variants_subtitle = ""
    if len(included_names) > 1:
        variants_subtitle = f" · Variantes agrupadas: {', '.join(included_names)}"
    elif len(raw_variants) > 1 and len(included_names) == 1:
        variants_subtitle = f" · Variante aislada manualmente: {included_names[0]}"

    # Banner del equipo
    st.markdown(
        f"<div style='background:rgba(25, 158, 112, 0.08); border:1px solid rgba(25, 158, 112, 0.3); "
        f"border-radius:10px; padding:14px 18px; margin-bottom:14px; display:flex; justify-content:space-between; align-items:center; flex-wrap:wrap; gap:10px;'>"
        f"<div>"
        f"<div style='font-size:0.75rem; text-transform:uppercase; letter-spacing:1px; color:#06d6a0; font-weight:700;'>Informe de Equipo</div>"
        f"<div style='font-size:1.6rem; font-weight:700; color:#ffffff;'>{target_canonical}</div>"
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
