"""Revisión de muertes: las muertes de un jugador ordenadas de la más evitable a la menos, para recorrerlas en el
replay una por una (ver deaths.py)."""
from __future__ import annotations

import pandas as pd
from PySide6.QtWidgets import QPushButton, QWidget

from .. import deaths, prefs, stats
from ..maps import pretty_map
from ..palette import SERIES
from ..parser import DemoData
from ..translate import place_name, weapon_name
from . import charts
from .nav import goto_replay, start_review
from .page import Combo, Page, Slot, kpi_row
from .widgets import DataTable

LEAD_S = 5.0  # el replay arranca unos segundos antes de la muerte: para ver cómo se llegó
UNIT_M = 0.01905  # una unidad del juego en metros

SHORT = {
    "opening_untraded": "Primera muerte sin tradeo", "untraded": "Sin tradeo", "isolated": "Aislado",
    "in_advantage": "En ventaja", "off_angle": "Fuera de ángulo", "blind": "Flasheado",
    "no_damage": "Sin hacer daño", "no_utility": "Sin tirar granadas", "round_lost": "Ronda perdida",
}

NOTE = ("cada muerte tiene señales que suelen indicar un error; la prioridad suma su peso (primera muerte sin "
        "tradeo pesa más que estar flasheado). No juzga la jugada: dice qué mirar. Con «Revisar en el replay» se "
        "abre la primera unos segundos antes y con Siguiente se pasa a la próxima. Aislado = el compañero vivo "
        "más cerca estaba a más de ~20 m; en ventaja = su equipo tenía más vivos que el rival; fuera de ángulo = "
        "el rival apareció a más de 60° de su mira.")


def single(d: DemoData) -> QWidget:
    ps = stats.player_stats(d)
    names = dict(zip(ps["steamid"], ps["name"], strict=True))
    p = Page()
    pick = Combo("Jugador", sorted(names.items(), key=lambda x: str(x[1]).lower()), value=prefs.me())
    p.add(pick)
    body = p.add(Slot(lambda: _single_body(d, pick.value, names.get(pick.value, ""))))
    pick.changed.connect(body.refresh)
    p.stretch()
    return p


def _single_body(d: DemoData, sid: str, name: str) -> QWidget:
    p = Page(margins=(0, 0, 0, 0))
    block(p, deaths.player_deaths(d, sid), name, {d.demo_id: ""}, sid)
    return p


def block(p: Page, df: pd.DataFrame, name: str, matches: dict[str, str], steamid: str = "",
          top: int | None = None) -> None:
    """KPIs, patrones y lista de muertes. `matches`: demo_id -> nombre corto de la partida ('' si es una sola)."""
    if df.empty:
        p.info(f"{name} no murió durante las rondas.", "ok")
        return
    n = len(df)
    s = deaths.summary(df)
    p.add(kpi_row([
        ("Muertes", f"{n}", "Durante las rondas (no cuenta las de después de terminada)"),
        ("Sin tradeo", f"{s['untraded'] + s['opening_untraded']:.0f}%", "Ningún compañero vengó la muerte en 5 s"),
        ("Primera muerte sin tradeo", f"{s['opening_untraded']:.0f}%", "Abrió la ronda muriendo y nadie lo compensó"),
        ("Aislado", f"{s['isolated']:.0f}%", "El compañero vivo más cerca estaba a más de ~20 m"),
        ("En ventaja", f"{s['in_advantage']:.0f}%", "Su equipo tenía más jugadores vivos"),
        ("Sin hacer daño", f"{s['no_damage']:.0f}%", "Murió sin dañar a nadie en la ronda"),
    ]))
    order = sorted((k for k in SHORT if k in s and k != "round_lost"), key=lambda k: -s[k])
    p.add(charts.hbars([SHORT[k] for k in order], [s[k] for k in order], [SERIES[0]] * len(order),
                       [f"{s[k]:.0f}%" for k in order], title=f"¿Cómo muere {name}? (% de sus {n} muertes)",
                       xmax=105, height=60 + 28 * len(order)))
    show = df if top is None else df.head(top)
    items = [(r.demo_id, int(r.round), max(0.0, r.time_in_round - LEAD_S),
              f"{matches.get(r.demo_id, '')}{' · ' if matches.get(r.demo_id) else ''}Ronda {r.round} "
              f"({r.time_in_round:.0f} s), lo mató {r.attacker}: {', '.join(r.reasons) or 'sin señales'}", steamid)
             for r in show.itertuples()]
    go = QPushButton(f"Revisar {'las ' + str(len(items)) + ' muertes' if len(items) > 1 else 'la muerte'} en el "
                     "replay, de la más evitable a la menos")
    go.setObjectName("Primary")
    go.clicked.connect(lambda: start_review(items, f"Muertes de {name}"))
    p.row(go, QWidget(), stretches=[2, 3])
    table = pd.DataFrame({
        **({"Partida": show["demo_id"].map(matches)} if len(matches) > 1 else {}),
        "Prioridad": show["priority"], "Ronda": show["round"], "Segundo": show["time_in_round"],
        "Lado": show["side"], "Lo mató": show["attacker"], "Arma": show["weapon"].map(weapon_name),
        "Zona": show["place"].map(place_name),
        "Vivos": show["mates_alive"].astype(str) + "v" + show["enemies_alive"].astype(str),
        "Compañero más cerca (m)": (show["nearest_mate"] * UNIT_M).round(0),
        "Señales": show["reasons"].map(", ".join),
    })
    p.add(DataTable(table, decimals=1, on_activate=lambda i: goto_replay(*items[i][:3]))).setMinimumHeight(
        min(90 + 26 * len(table), 460))
    p.note(NOTE)


def match_names(demos: list[DemoData]) -> dict[str, str]:
    return {d.demo_id: f"{pretty_map(d.meta['map'])} {d.meta['score_a']}-{d.meta['score_b']}" for d in demos}
