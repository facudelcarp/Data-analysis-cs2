"""Vista: dashboard ejecutivo (de un jugador foco o de toda la biblioteca)."""
from __future__ import annotations

import pandas as pd
import streamlit as st

from .. import stats
from ..maps import pretty_map
from ..translate import weapon_name
from . import charts, common as ui

MIN_ROUNDS_BASELINE = 30
REASON_SHORT = {
    "T eliminaron a los CT": "💀 T eliminaron a los CT", "CT eliminaron a los T": "💀 CT eliminaron a los T",
    "Bomba detonada": "💣 Bomba detonada", "Bomba desactivada": "✂️ Bomba desactivada",
    "Se agotó el tiempo": "⏱ Se agotó el tiempo", "Rendición de los T": "🏳 Rendición de los T",
    "Rendición de los CT": "🏳 Rendición de los CT",
}


def render() -> None:
    st.header("📊 Dashboard")
    lib = ui.library()
    if len(lib) == 0:
        ui.empty_state()
        return
    players = lib.players()
    names = dict(zip(players["steamid"], players["name"] + " (" + players["demos"].astype(str) + " demos)"))
    saved = st.session_state.get("focus_player", "")
    options = [""] + list(names)
    focus = st.selectbox("Jugador foco", options, index=options.index(saved) if saved in options else 0,
                         format_func=lambda s: names.get(s, "— Biblioteca completa —"))
    st.session_state["focus_player"] = focus
    if focus:
        _player_dashboard(lib, focus, names[focus].rsplit(" (", 1)[0])
    else:
        _library_dashboard(lib)


# --------------------------------------------------------------------------------------------
# Biblioteca completa
# --------------------------------------------------------------------------------------------

def _library_dashboard(lib) -> None:
    m = lib.matches()
    pr = lib.player_rounds
    k = lib.concat("kills")
    ek = k[k["is_enemy_kill"]] if len(k) else k
    r = lib.concat("rounds")
    ui.kpi_row([
        ("Partidas", f"{len(m)}", None),
        ("Rondas", f"{int(m['Rondas'].sum()):,}", None),
        ("Jugadores", f"{pr['steamid'].nunique()}", "Jugadores distintos en todas las demos"),
        ("Kills", f"{len(ek):,}", None),
        ("Headshots", f"{100 * ek['headshot'].mean():.0f}%" if len(ek) else "—", "De todas las kills, cuántas fueron a la cabeza"),
        ("Horas de juego", f"{m['Duración (min)'].sum() / 60:.1f}", None),
    ])

    lb, note = _qualified(lib)
    top = lb.sort_values("rating2", ascending=False).head(10).copy()
    top["label"] = top["name"] + " (" + top["rounds"].astype(int).astype(str) + " r)"
    st.plotly_chart(charts.ranking_bars(top, "rating2", "label", ref=1.0, ref_label="1.00 = promedio",
                                        title="¿Quiénes son los mejores de la biblioteca?"), width="stretch")
    charts.explain(f"top 10 por rating sumando todas sus partidas ({note}); entre paréntesis, cuántas rondas jugó. "
                   "Más de 1.00 es bueno. Con pocas rondas el número es menos confiable.")

    c1, c2 = st.columns(2)
    by_map = m.groupby("Mapa").size()
    c1.plotly_chart(charts.count_bars([pretty_map(x) for x in by_map.index], by_map.values,
                                      "¿Qué mapas se jugaron?", total=len(m)), width="stretch")
    side = r.groupby("winner_side").size().reindex(["CT", "T"]).fillna(0)
    side_df = pd.DataFrame({"side": side.index, "pct": 100 * side.values / max(side.sum(), 1),
                            "n": [f"{int(v)} rondas" for v in side.values]})
    c2.plotly_chart(charts.side_split(side_df, "pct", "¿Qué lado gana más rondas?", fmt="{:.0f}%", extra="n"),
                    width="stretch")
    with c1:
        charts.explain("cuántas partidas hay de cada mapa, y qué porcentaje del total representan.")
    with c2:
        charts.explain("de todas las rondas, qué porcentaje ganó cada lado. Si un lado gana bastante más del 50%, "
                       "esos mapas o partidas vienen cargados hacia ese lado.")

    c1, c2 = st.columns(2)
    if len(ek):
        w = ek.groupby("weapon").size().sort_values(ascending=False).head(8)
        c1.plotly_chart(charts.count_bars([weapon_name(x) for x in w.index], w.values, "¿Con qué armas se mata más?",
                                          total=len(ek)), width="stretch")
        with c1:
            charts.explain("las 8 armas con más kills y qué parte del total de kills representa cada una.")
    reasons = r.groupby("reason").size()
    c2.plotly_chart(charts.count_bars([REASON_SHORT.get(x, x) for x in reasons.index], reasons.values,
                                      "¿Cómo terminan las rondas?", total=len(r)), width="stretch")
    with c2:
        charts.explain("de qué manera terminó cada ronda. Muchas rondas por bomba (💣/✂️) indican partidas "
                       "de ejecuciones; muchas eliminaciones (💀), de duelos abiertos.")

    with st.expander("Tabla de jugadores"):
        st.dataframe(ui.stat_table(lb.sort_values("rating2", ascending=False),
                                   ["name", "demos", "rounds", "kd", "adr", "kast_pct", "hs_pct", "rating2"]),
                     hide_index=True, width="stretch")
        st.caption(ui.RATING_NOTE)


# --------------------------------------------------------------------------------------------
# Jugador foco
# --------------------------------------------------------------------------------------------

def _qualified(lib) -> tuple[pd.DataFrame, str]:
    """Jugadores con muestra suficiente para compararse.

    El mínimo es la mitad de las rondas del jugador típico de la biblioteca (tope 30): con un umbral fijo,
    en una biblioteca de pocas partidas solo pasarían los de la partida más larga."""
    rounds = lib.players()["rounds"]
    threshold = int(min(MIN_ROUNDS_BASELINE, 0.5 * rounds.median())) if len(rounds) else 0
    lb = lib.leaderboard(min_rounds=threshold)
    return lb, f"jugadores con al menos {threshold} rondas"


def _baseline(lib) -> pd.Series:
    """Mediana de cada métrica entre los jugadores de referencia de la biblioteca."""
    return _qualified(lib)[0].median(numeric_only=True)


def _delta(value, base, digits: int = 1, unit: str = "") -> str | None:
    if value is None or base is None or pd.isna(value) or pd.isna(base):
        return None
    d = value - base
    if round(d, digits) == 0:
        return "≈ igual a la mediana"
    return f"{d:+.{digits}f}{unit} vs mediana"


def _player_dashboard(lib, sid: str, name: str) -> None:
    pr = lib.player_rounds[lib.player_rounds["steamid"] == sid]
    cl = lib.clutches[lib.clutches["steamid"] == sid]
    acc = lib.accuracy[lib.accuracy["steamid"] == sid]
    agg = stats.aggregate(pr, cl, acc).iloc[0]
    per = lib.per_demo(sid)
    base = _baseline(lib)
    wins = int((per["Resultado"] == "Victoria").sum())
    st.subheader(name)
    st.caption(f"{len(per)} partidas · {int(agg['rounds'])} rondas. Las flechas comparan con la mediana de los "
               f"jugadores de la biblioteca (verde = mejor que la mediana).")

    st.markdown("**Resultado e impacto**")
    ui.kpi_row([
        ("Winrate", f"{100 * wins / max(len(per), 1):.0f}%", f"{wins} victorias de {len(per)}"),
        ("Rating 2.0*", f"{agg['rating2']:.2f}", ui.RATING_NOTE, _delta(agg["rating2"], base.get("rating2"), 2)),
        ("ADR", f"{agg['adr']:.0f}", "Daño a rivales por ronda", _delta(agg["adr"], base.get("adr"), 0)),
        ("KAST", f"{agg['kast_pct']:.0f}%", "Rondas con kill, asistencia, supervivencia o muerte tradeada",
         _delta(agg["kast_pct"], base.get("kast_pct"), 0, " pp")),
        ("K/D", f"{agg['kd']:.2f}", None, _delta(agg["kd"], base.get("kd"), 2)),
        ("HS", f"{agg['hs_pct']:.0f}%", "Kills a la cabeza", _delta(agg["hs_pct"], base.get("hs_pct"), 0, " pp")),
    ])
    ui.kpi_row([
        ("Aperturas", f"{int(agg['opening_kills'])}-{int(agg['opening_deaths'])}",
         "Primeras kills de la ronda ganadas-perdidas",
         _delta(agg["opening_success_pct"], base.get("opening_success_pct"), 0, " pp")),
        ("Clutches", f"{int(agg['clutches_won'])}/{int(agg['clutches'])}", "Ganados / jugados (1vX)"),
        ("Rondas con 3+ kills", f"{int(agg['k3'] + agg['k4'] + agg['k5'])}",
         f"3K: {int(agg['k3'])} · 4K: {int(agg['k4'])} · ACE: {int(agg['k5'])}"),
        ("Tradeos", f"{int(agg['trade_kills'])}", "Kills que vengaron a un compañero en < 5 s"),
        ("Daño de utilidad", f"{agg['utility_adr']:.1f}", "Por ronda, con HE y molotovs",
         _delta(agg["utility_adr"], base.get("utility_adr"), 1)),
        ("Precisión", f"{agg['accuracy_pct']:.0f}%" if pd.notna(agg.get("accuracy_pct")) else "—",
         "Impactos / disparos con armas de fuego", _delta(agg.get("accuracy_pct"), base.get("accuracy_pct"), 0, " pp")),
    ])

    mi = lib.micro(sid)
    if len(mi):
        mrow = mi.iloc[0]

        def fmt(col, unit, digits=0):
            v = mrow.get(col)
            return "—" if v is None or pd.isna(v) else f"{v:.{digits}f}{unit}"
        st.markdown("**Aim**")
        ui.kpi_row([
            ("Mira al ver al rival", fmt("crosshair_deg", "°", 1), "Mediana del ángulo mira→cabeza cuando aparece "
             "el rival. Menos es mejor.", _delta(mrow.get("crosshair_deg"), base.get("crosshair_deg"), 1, "°"), True),
            ("Reacción", fmt("reaction_ms", " ms"), "De ver al rival a disparar. Menos es mejor.",
             _delta(mrow.get("reaction_ms"), base.get("reaction_ms"), 0, " ms"), True),
            ("TTD", fmt("ttd_ms", " ms"), "De ver al rival al primer daño. Menos es mejor.",
             _delta(mrow.get("ttd_ms"), base.get("ttd_ms"), 0, " ms"), True),
            ("Pre-aim", fmt("preaim_pct", "%"), "Duelos ganados con la mira ya sobre el rival (≤ 3°)",
             _delta(mrow.get("preaim_pct"), base.get("preaim_pct"), 0, " pp")),
            ("Counter-strafe", fmt("counter_strafe_pct", "%"), "Disparos hechos frenado",
             _delta(mrow.get("counter_strafe_pct"), base.get("counter_strafe_pct"), 0, " pp")),
            ("Precisión 1ª bala", fmt("first_bullet_acc_pct", "%"), "Impactos de la primera bala de cada ráfaga",
             _delta(mrow.get("first_bullet_acc_pct"), base.get("first_bullet_acc_pct"), 0, " pp")),
        ])

    if len(per) >= 2:
        st.plotly_chart(charts.results_timeline(per), width="stretch")
        charts.explain("cada punto es una partida, con su rating escrito arriba. Punto lleno = ganó; punto vacío = "
                       "perdió. Arriba de la línea punteada (1.00) fue una buena partida.")
    else:
        st.caption("Con una sola partida no hay evolución para mostrar: cargá más demos de este jugador.")

    c1, c2 = st.columns(2)
    ms = lib.map_summary(sid)
    if not ms.empty:
        ms = ms.copy()
        ms["label"] = ms["Mapa"].map(pretty_map) + " (" + ms["Partidas"].astype(str) + ")"
        c1.plotly_chart(charts.ranking_bars(ms, "Winrate %", "label", fmt="{:.0f}%", ref=50, ref_label="50%",
                                            title="¿En qué mapas gana más?"), width="stretch")
        with c1:
            charts.explain("porcentaje de partidas ganadas en cada mapa; entre paréntesis, cuántas jugó. "
                           "Con 1 o 2 partidas no alcanza para sacar conclusiones.")
    sides = stats.aggregate(pr, by=["steamid", "side"])
    if not sides.empty:
        sides["extra"] = "rating " + sides["rating2"].map("{:.2f}".format) + " · " + sides["rounds"].astype(str) + " r"
        c2.plotly_chart(charts.side_split(sides, "adr", "¿Rinde más de CT o de T?", fmt="ADR {:.0f}", extra="extra"),
                        width="stretch")
        with c2:
            charts.explain("daño por ronda jugando de cada lado, con su rating y la cantidad de rondas debajo.")

    c1, c2 = st.columns(2)
    k = lib.concat("kills")
    mine = k[(k["attacker_steamid"] == sid) & k["is_enemy_kill"]] if len(k) else k
    if len(mine):
        w = mine.groupby("weapon").size().sort_values(ascending=False).head(8)
        c1.plotly_chart(charts.count_bars([weapon_name(x) for x in w.index], w.values, "¿Con qué armas mata?",
                                          total=len(mine)), width="stretch")
        with c1:
            charts.explain("sus 8 armas con más kills y qué parte de sus kills hizo con cada una.")
    rounds = int(agg["rounds"])
    mk = {"Ninguna kill": rounds - int(agg["k1"] + agg["k2"] + agg["k3"] + agg["k4"] + agg["k5"]),
          "1 kill": int(agg["k1"]), "2 kills": int(agg["k2"]), "3 kills": int(agg["k3"]),
          "4 kills": int(agg["k4"]), "ACE (5)": int(agg["k5"])}
    labels = list(mk)
    fig = charts.count_bars(labels, list(mk.values()), "¿Cuántas kills hace por ronda?", total=rounds)
    fig.update_yaxes(categoryorder="array", categoryarray=labels[::-1])
    c2.plotly_chart(fig, width="stretch")
    with c2:
        charts.explain("en cuántas rondas hizo 0, 1, 2… kills, y qué porcentaje de sus rondas es. Las rondas con "
                       "2 o más kills son las que más pesan en el rating.")

    with st.expander("Tabla de partidas"):
        cols = ["Partida", "Mapa", "Marcador propio", "Resultado", "kills", "deaths", "assists", "adr", "kast_pct",
                "hs_pct", "rating2"]
        show = per[cols].copy()
        show["Mapa"] = show["Mapa"].map(pretty_map)
        st.dataframe(ui.stat_table(show, cols), hide_index=True, width="stretch")
