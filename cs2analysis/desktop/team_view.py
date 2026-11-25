"""Análisis de equipos: cómo juega un equipo en todas sus partidas (roles, tradeos, ventajas, utilidad, mapas)."""
from __future__ import annotations

import pandas as pd
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFrame, QLabel, QVBoxLayout, QWidget

from .. import identity, team_analysis
from ..labels import RATING_NOTE, SCOREBOARD_COLS, stat_table
from ..maps import pretty_map
from . import charts
from . import widgets as w
from .library_views import LibraryView, MultiPick
from .page import AsyncSlot, Combo, LazyTabs, Page, Segmented, Slot, kpi_row
from .single_tabs import _identity


class TeamView(LibraryView):
    title = "Análisis de equipos"
    subtitle = "Cómo juega un equipo en todas sus partidas: roles, tradeos, ventajas y mapas."

    def build(self) -> QWidget:
        demos = list(self.demos.values())
        p = Page()
        scope_items = [("all", "Toda la biblioteca")]
        if len(demos) > 1:
            scope_items += [(d.demo_id, f"Demo #{i}: {d.meta.get('file_name', '')[:25]} ({pretty_map(d.meta['map'])})")
                            for i, d in enumerate(demos, 1)]
        self.scope = Combo("Alcance", scope_items)
        p.add(self.scope)
        body = p.add(Slot(self._for_scope))
        self.scope.changed.connect(body.refresh)
        p.stretch()
        return p

    def _for_scope(self) -> QWidget:
        demos = list(self.demos.values())
        selected = demos if self.scope.value == "all" else [self.demos[self.scope.value]]
        p = Page(margins=(0, 0, 0, 0))
        groups = identity.cluster_teams(selected)
        if not groups:
            p.info("No se encontraron equipos en las demos seleccionadas.")
            return p
        by_key = {g.key: g for g in groups}
        team = Combo("Equipo a analizar", [(k, f"{g.name} ({g.matches} partida{'s' if g.matches != 1 else ''})")
                                           for k, g in by_key.items()], min_width=300)
        p.add(team)
        slot = p.add(Slot(lambda: self._for_team(selected, by_key[team.value], demos)))
        team.changed.connect(slot.refresh)
        return p

    def _for_team(self, selected, group, all_demos) -> QWidget:
        p = Page(margins=(0, 0, 0, 0))
        pos = {d.demo_id: i for i, d in enumerate(all_demos, 1)}
        meta = {d.demo_id: d.meta for d in selected}

        def inst_label(inst: tuple[str, str]) -> str:
            demo_id, letter = inst
            m = meta[demo_id]
            own, rival = (m["team_a"], m["team_b"]) if letter == "A" else (m["team_b"], m["team_a"])
            return f"Partida #{pos.get(demo_id, '?')} · {pretty_map(m['map'])} · como «{own}» vs {rival}"

        pick = None
        if group.matches > 1:
            how = "jugadores en común" if group.linked_by == "jugadores" else "nombre de equipo"
            p.info(f"💡 {group.matches} partidas unidas por {how}. Núcleo del equipo: "
                   f"{', '.join(group.core_players[:5])}. Si alguna partida no corresponde, destildala.", "ok")
            pick = MultiPick([(i, inst_label(i)) for i in group.instances], list(group.instances),
                             max_checked=len(group.instances))
            p.add(pick)
        maps = sorted({meta[d]["map"] for d, _ in group.instances if meta[d].get("map")})
        mp = Combo("Mapa", [("Todos los mapas", "Todos los mapas"), *[(m, pretty_map(m)) for m in maps]])
        p.add(mp)

        def job():
            included = pick.values if pick else list(group.instances)  # widgets: se leen en el hilo de la ventana
            map_name = mp.value

            def compute():
                if not included:
                    return included, None
                return included, team_analysis.analyze_team(selected, target_team=group.raw_names or [group.name],
                                                            map_name=map_name, display_name=group.name,
                                                            instances=set(included))
            return compute

        def report(result) -> QWidget:
            included, ts = result
            out = Page(margins=(0, 0, 0, 0))
            if not included:
                out.info("Elegí al menos una partida para analizar.", "warn")
                return out
            if not ts or ts.get("total_rounds", 0) == 0:
                out.info(f"No hay suficientes rondas registradas para {group.name} con los filtros seleccionados.", "warn")
                return out
            names = sorted({(meta[d]["team_a"] if lt == "A" else meta[d]["team_b"]) for d, lt in included})
            out.add(_banner(group.name, ts, mp.value, names))
            out.add(kpi_row([
                ("Partidas", f"{ts['matches_won']}/{ts['matches_played']}", f"{ts['match_winrate']:.0f}% winrate"),
                ("Rondas ganadas", f"{ts['total_rounds_won']}/{ts['total_rounds']}", f"{ts['round_winrate']:.1f}% winrate"),
                ("Lado T (ataque)", f"{ts['t_winrate']:.1f}%", f"{ts['rounds_t_won']}/{ts['rounds_t_played']} rondas"),
                ("Lado CT (defensa)", f"{ts['ct_winrate']:.1f}%", f"{ts['rounds_ct_won']}/{ts['rounds_ct_played']} rondas"),
                ("Kills de equipo", f"{ts['team_kills']:,}", f"{ts['team_deaths']:,} muertes"),
                ("Diferencia K-D", f"{ts['team_kills'] - ts['team_deaths']:+d}", None),
            ]))
            tabs = LazyTabs()
            tabs.setMinimumHeight(900)
            for title, fn in (("📊 Scoreboard", _scoreboard), ("🎭 Roles (T y CT)", _roles), ("⚡ Tradeos", _trades),
                              ("🎯 Ventajas", _advantages), ("💣 Utilidad", _utility), ("🗺️ Map pool", _map_pool)):
                tabs.add_lazy(lambda f=fn: f(ts, group.name), title)
            out.add(tabs, 1)
            return out

        slot = p.add(AsyncSlot(job, report))
        mp.changed.connect(slot.refresh)
        if pick:
            pick.changed.connect(slot.refresh)
        return p


def _banner(name: str, ts: dict, map_value: str, names: list[str]) -> QFrame:
    f = QFrame()
    f.setObjectName("TeamBanner")
    f.setStyleSheet("QFrame#TeamBanner { background: rgba(25,158,112,0.08); border: 1px solid rgba(25,158,112,0.3);"
                    "border-radius: 10px; } QFrame#TeamBanner QLabel { border: none; background: transparent; }")
    v = QVBoxLayout(f)
    v.setContentsMargins(16, 10, 16, 10)
    tag = QLabel("INFORME DE EQUIPO")
    tag.setStyleSheet("color:#06d6a0; font-weight:700; font-size:8pt;")
    v.addWidget(tag)
    t = QLabel(name)
    t.setTextFormat(Qt.PlainText)
    t.setStyleSheet("font-size:17pt; font-weight:800;")
    v.addWidget(t)
    sub = (f"Filtro: {pretty_map(map_value) if map_value != 'Todos los mapas' else 'Todos los mapas'} · "
           f"{ts['matches_played']} partida(s) · {ts['matches_won']}V - {ts['matches_lost']}D · "
           f"winrate de rondas {ts['round_winrate']:.1f}%")
    if len(names) > 1:
        sub += f" · Jugó como: {', '.join(names)}"
    s = QLabel(sub)
    s.setTextFormat(Qt.PlainText)
    s.setObjectName("Muted")
    s.setWordWrap(True)
    v.addWidget(s)
    return f


def _scoreboard(ts: dict, team_name: str) -> QWidget:
    p = Page()
    ps = ts.get("team_players_df", pd.DataFrame())
    if ps.empty:
        p.info("Sin estadísticas detalladas de jugadores registradas en las demos seleccionadas.")
        return p

    def best(col, asc=False):
        x = ps.dropna(subset=[col])
        return x.sort_values(col, ascending=asc).iloc[0] if len(x) else None

    items = []
    if (r := best("rating2")) is not None:
        items.append(("⭐ MVP del equipo", r["name"], f"Rating {r['rating2']:.2f} · {int(r['kills'])}-{int(r['deaths'])}"))
    if (r := best("adr")) is not None:
        items.append(("💥 Más daño (ADR)", r["name"], f"{r['adr']:.1f} de daño por ronda"))
    if (r := best("opening_kills")) is not None and r["opening_kills"] > 0:
        items.append(("🚪 Aperturas ganadas", r["name"],
                      f"{int(r['opening_kills'])} opening kills ({r.get('opening_success_pct', 0.0):.0f}%)"))
    if (r := best("clutches_won")) is not None and r["clutches_won"] > 0:
        items.append(("🧊 Clutcher del equipo", r["name"], f"{int(r['clutches_won'])} clutches ganados"))
    if (r := best("trade_kills")) is not None and r["trade_kills"] > 0:
        items.append(("⚡ Más tradeos", r["name"], f"{int(r['trade_kills'])} trade kills"))
    if (r := best("awp_kills")) is not None and r["awp_kills"] >= 3:
        items.append(("🎯 Sniper principal", r["name"], f"{int(r['awp_kills'])} bajas con AWP"))
    if items:
        p.add(w.card_row(items))
    p.add(charts.ranking_bars(ps, "rating2", "name", ref=1.0, ref_label="1.00 = promedio",
                              title=f"¿Quién rindió más en {team_name}? (rating 2.0 por jugador)"))
    p.note("cada barra es el rating del jugador en este conjunto de partidas. Más de 1.00 es rendimiento positivo.")
    p.add(w.DataTable(stat_table(ps, SCOREBOARD_COLS), fit_rows=True))
    p.caption(RATING_NOTE)
    p.stretch()
    return p


def _roles(ts: dict, _name: str) -> QWidget:
    p = Page()
    p.caption("En CS2 competitivo los roles dependen del bando: en T se juega Entry, Refrag o Lurk; en CT se juega "
              "Anchor de bombsite o Rotador.")
    ps = ts.get("team_players_df", pd.DataFrame())
    archs = ts.get("player_archetypes", {})
    avg = ts.get("team_avg_scores", {})
    if ps.empty or not archs:
        p.info("Sin datos suficientes de jugadores para clasificar roles.")
        return p
    rows = []
    for _, r in ps.iterrows():
        a = archs.get(r["steamid"])
        if a:
            rows.append({"Jugador": r["name"], "Identidad táctica": a["dual_badge"],
                         "Rol lado T": f"{a['t']['icon']} {a['t']['role']}",
                         "Rol lado CT": f"{a['ct']['icon']} {a['ct']['role']}", "Rating 2.0": r["rating2"],
                         "ADR": r["adr"], "KAST %": r["kast_pct"],
                         "Entry W-L": f"{int(r['opening_kills'])}-{int(r['opening_deaths'])}"})
    if rows:
        p.sub("Matriz táctica del plantel")
        p.add(w.DataTable(pd.DataFrame(rows), fit_rows=True))
    names = dict(zip(ps["steamid"], ps["name"], strict=True))
    pl = Combo("Ver perfil táctico y radar de", list(names.items()))
    p.add(pl)

    def profile() -> QWidget:
        out = Page(margins=(0, 0, 0, 0))
        sid = pl.value
        a = archs.get(sid)
        r = ps[ps["steamid"] == sid].iloc[0]
        if not a:
            out.caption("Sin arquetipo para este jugador.")
            return out
        out.add(_identity(a))
        out.add(kpi_row([
            ("Rating 2.0*", f"{r['rating2']:.2f}", RATING_NOTE),
            ("K / D / A", f"{int(r['kills'])} / {int(r['deaths'])} / {int(r['assists'])}", None),
            ("ADR", f"{r['adr']:.1f}", "Daño real por ronda"),
            ("KAST", f"{r['kast_pct']:.0f}%", "% rondas con contribución directa"),
            ("HS %", f"{r['hs_pct']:.0f}%", None),
            ("Entry W-L", f"{int(r['opening_kills'])}-{int(r['opening_deaths'])}", "Duelos de apertura ganados-perdidos"),
        ]))
        mode = Segmented(["T vs CT", "General vs promedio", "Solo T", "Solo CT"], label="Radar")
        out.add(mode)

        def radar() -> QWidget:
            m = mode.value
            if m == "T vs CT":
                return charts.player_archetype_radar(a["t"]["scores"], player_name="Lado T", player_color="#d95926",
                                                     compare_scores=a["ct"]["scores"], compare_name="Lado CT",
                                                     compare_color="#3987e5", title=f"Perfil táctico de {r['name']}: T vs CT")
            if m == "Solo T":
                return charts.player_archetype_radar(a["t"]["scores"], avg, f"{r['name']} (T)", "#d95926",
                                                     title="Perfil en ataque (T) vs promedio del equipo")
            if m == "Solo CT":
                return charts.player_archetype_radar(a["ct"]["scores"], avg, f"{r['name']} (CT)", "#3987e5",
                                                     title="Perfil en defensa (CT) vs promedio del equipo")
            return charts.player_archetype_radar(a["overall"]["scores"], avg, str(r["name"]), "#ffd166",
                                                 title="Dimensiones globales vs promedio del equipo")

        rs = Slot(radar)
        mode.changed.connect(rs.refresh)
        axes = list(a["overall"]["scores"])
        scores = pd.DataFrame({"Eje táctico": axes, "Lado T": [a["t"]["scores"].get(k, 0) for k in axes],
                               "Lado CT": [a["ct"]["scores"].get(k, 0) for k in axes],
                               "Global": [a["overall"]["scores"].get(k, 0) for k in axes],
                               "Promedio": [avg.get(k, 50.0) for k in axes]})
        out.row(rs, w.DataTable(scores, fit_rows=True, decimals=0), stretches=[3, 2])
        out.note("compara las 6 dimensiones tácticas de este jugador entre cuando ataca (T) y cuando defiende (CT).")
        return out

    slot = p.add(Slot(profile))
    pl.changed.connect(slot.refresh)
    p.stretch()
    return p


def _trades(ts: dict, _name: str) -> QWidget:
    p = Page()
    p.add(kpi_row([
        ("Tasa de tradeo", f"{ts['trade_pct']:.1f}%", f"{ts['traded_deaths']}/{ts['team_deaths']} muertes vengadas"),
        ("Trade kills", f"{ts['team_trades']}", f"{ts['trade_kills_per_round']:.2f} por ronda"),
        ("Reacción media del refrag", f"{ts['avg_trade_delay']:.2f} s", "Tiempo promedio para vengar al compañero"),
        ("Muertes no tradeadas", f"{ts['untraded_deaths']}", "Bajas aisladas sin refrag"),
        ("Winrate con tradeo", f"{ts['trade_round_winrate']:.1f}%", f"{ts['rounds_with_trade']} rondas con ≥1 tradeo"),
        ("Lift de victoria", f"{ts['trade_win_lift']:+.1f}%", "Aumento de winrate al conseguir un tradeo"),
    ]))
    pairs = ts.get("trade_pairs", pd.DataFrame())
    right = Page(margins=(0, 0, 0, 0))
    right.sub("Química de refrags: ¿quién refraggea a quién?")
    if pairs.empty:
        right.caption("Sin suficientes situaciones de refrag registradas.")
    else:
        right.add(w.DataTable(pairs.head(8).rename(columns={"refragger": "Cobró el refrag", "avenged": "Compañero vengado",
                                                            "trades": "Refrags", "avg_delay_s": "Tiempo medio (s)"}),
                              fit_rows=True))
    right.stretch()
    p.row(charts.trade_impact_bars(ts["trade_round_winrate"], ts["no_trade_round_winrate"], ts["trade_win_lift"]), right)
    p.note("compara el porcentaje de victoria en rondas donde el equipo consiguió al menos un refrag vs rondas donde no "
           "intercambió. Un lift alto indica que el equipo gana casi siempre que juega agrupado. La tabla muestra las "
           "parejas que más se apoyan y con qué velocidad reaccionan.")
    p.stretch()
    return p


def _advantages(ts: dict, _name: str) -> QWidget:
    p = Page()
    p.add(kpi_row([
        ("Conversión 5v4", f"{ts['conversion_5v4']:.1f}%", f"Ganó {ts['rounds_5v4_won']}/{ts['rounds_5v4_total']} aperturas"),
        ("Recuperación 4v5", f"{ts['recovery_4v5']:.1f}%",
         f"Remontó {ts['rounds_4v5_won']}/{ts['rounds_4v5_total']} aperturas rivales"),
        ("Rondas de pistola", f"{ts['pistol_winrate']:.1f}%", f"Ganó {ts['pistols_won']}/{ts['pistols_played']} pistolas"),
        ("Conversión 2ª ronda", f"{ts['followup_conv']:.1f}%",
         f"Ganó {ts['pistol_followups_won']}/{ts['pistol_followups_played']} tras ganar la pistola"),
        ("Lado T (ataque)", f"{ts['t_winrate']:.1f}%", f"{ts['rounds_t_won']}/{ts['rounds_t_played']} rondas"),
        ("Lado CT (defensa)", f"{ts['ct_winrate']:.1f}%", f"{ts['rounds_ct_won']}/{ts['rounds_ct_played']} rondas"),
    ]))
    p.row(charts.advantage_conversion_bars(ts["conversion_5v4"], ts["recovery_4v5"]),
          charts.team_side_winrates_bar(ts["t_winrate"], ts["ct_winrate"]))
    p.note("la conversión 5v4 mide la disciplina para cerrar rondas con ventaja (ref. pro: ~75 %); la recuperación 4v5, "
           "la capacidad de remontar tras recibir el primer golpe (ref. pro: ~25-30 %). A la derecha, atacar vs "
           "defender: una diferencia mayor a 15 % evidencia un sesgo táctico marcado.")
    p.stretch()
    return p


def _utility(ts: dict, _name: str) -> QWidget:
    p = Page()
    en, tm = ts["flashes_enemies"], ts["flashes_teammates"]
    p.add(kpi_row([
        ("Util ADR colectivo", f"{ts['util_adr']:.1f}", "Daño colectivo de utilidades por ronda"),
        ("Daño de utilidad total", f"{int(ts['util_damage_total']):,}", "Puntos de vida infligidos con HE/molotovs"),
        ("Enemigos cegados", f"{en}", "Flashes exitosos sobre rivales"),
        ("Team flashes", f"{tm}", "Flashes que impactaron a compañeros"),
        ("Ratio de ceguera (E/T)", f"{round(en / max(1, tm), 1)}", "Enemigos cegados por cada compañero flasheado"),
    ]))
    u = ts.get("team_utility_df", pd.DataFrame())
    if u.empty:
        p.caption("Sin datos de utilidad registrados.")
    else:
        p.sub("Desglose de utilidad por jugador")
        p.add(w.DataTable(u[["Jugador", "Rondas", "Util ADR", "Daño Utilidad", "Granadas", "Enemigos cegados",
                             "Tiempo ceguera (s)", "Team Flashes", "Flashes / Ronda"]], fit_rows=True))
        p.note("un Util ADR alto (>5.0) refleja buen control de mapa con daño de HE y molotovs. Pocos team flashes "
               "indican coordinación.")
    p.stretch()
    return p


def _map_pool(ts: dict, _name: str) -> QWidget:
    p = Page()
    m = ts.get("map_pool", pd.DataFrame())
    if m.empty:
        p.caption("Sin datos de mapas suficientes.")
    else:
        p.add(w.DataTable(m[["Mapa", "Partidas", "Winrate Partidas %", "Winrate Rondas %", "Rondas T %", "Rondas CT %",
                             "Trade %", "Conversión 5v4 %", "Util ADR"]], fit_rows=True, decimals=1))
        p.note("desglose de rendimiento por mapa: winrates por lado, tasa de tradeo y conversión 5v4.")
    p.stretch()
    return p
