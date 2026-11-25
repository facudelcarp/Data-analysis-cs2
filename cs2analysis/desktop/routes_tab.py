"""Pestaña "Rutas": el recorrido de un jugador ronda por ronda, en varias partidas del mismo mapa."""
from __future__ import annotations

import numpy as np
import pandas as pd
from PySide6.QtWidgets import QWidget

from .. import routes
from ..maps import has_levels, level_mask, pretty_map
from ..multi import Library
from ..palette import SERIES
from .mapview import MapView
from .page import AsyncSlot, Combo, Page, Segmented, Slider, Slot, level_selector

WON, LOST, DIED = "#3fb68b", "#ef476f", "#ef476f"


def build(lib: Library) -> QWidget:
    p = Page()
    players = lib.players()
    pick = Combo("Jugador", [(s, f"{n} ({d} partidas)") for s, n, d in
                             zip(players["steamid"], players["name"], players["demos"], strict=True)], min_width=280)
    p.add(pick)
    body = p.add(Slot(lambda: _for_player(lib, pick.value)))
    pick.changed.connect(body.refresh)
    p.stretch()
    return p


def _for_player(lib: Library, steamid: str) -> QWidget:
    p = Page(margins=(0, 0, 0, 0))
    maps = routes.player_maps(lib.demos, steamid)
    if not maps:
        p.info("Este jugador no tiene posiciones registradas.")
        return p
    mp = Combo("Mapa", [(m, f"{pretty_map(m)} ({n})") for m, n in maps.items()], min_width=180)
    side = Segmented(["T", "CT"], label="Lado")
    buy = Segmented(list(routes.BUY_GROUPS), label="Compra")
    color = Segmented(["Resultado", "Partida"], label="Color")
    p.row(mp, side, buy, color, stretches=[2, 1, 3, 2])
    t0 = Slider("Desde", 0, 115, 0, step=5, suffix=" s")
    t1 = Slider("Hasta", 5, 175, 25, step=5, suffix=" s")
    p.row(t0, t1)
    def make_level() -> QWidget:
        sel = level_selector(mp.value)  # solo en mapas de dos pisos (Nuke, Vertigo, Train)
        if sel:
            sel.changed.connect(lambda _: slot.refresh())  # `slot` se define más abajo; se usa recién al cambiar
        return sel or QWidget()

    lvl_holder = p.add(Slot(make_level))

    def job():
        # filtros leídos acá (hilo de la ventana); el recorrido de las demos va en otro hilo
        a, b = sorted((t0.value, t1.value))
        args = (mp.value, side.value, a, max(b, a + 5), buy.value)
        lvl = lvl_holder.content if isinstance(lvl_holder.content, Segmented) else None
        lower = bool(lvl and lvl.value == "Inferior")
        by = color.value
        return lambda: (routes.player_routes(lib.demos, steamid, *args), args, lower, by)

    slot = p.add(AsyncSlot(job, _render))
    for x in (mp, side, buy, color, t0, t1):
        x.changed.connect(slot.refresh)
    mp.changed.connect(lvl_holder.refresh)
    p.note("cada línea es una ronda: por dónde se movió el jugador en esa ventana de tiempo. Donde se superponen "
           "muchas está su ruta habitual. El punto es dónde estaba al terminar la ventana y la ✕, dónde murió. "
           "Con 0-25 s se ve cómo sale a la ronda (su posición o su default); con 40-70 s, cómo rota. "
           "Pasá el mouse por los puntos para ver la partida y la ronda. Rueda = zoom.")
    return p


def _render(result) -> QWidget:
    rs, (map_name, side, a, b, buy), lower, by = result
    p = Page(margins=(0, 0, 0, 0))
    if not rs:
        p.info(f"Sin rondas de {side} con compra «{buy}» en {pretty_map(map_name)} entre los segundos {a} y {b}.")
        return p
    m = MapView(map_name, lower=lower, height=720)

    def on_level(r: routes.Route) -> tuple[np.ndarray, np.ndarray]:
        if not has_levels(map_name):
            return r.x, r.y
        keep = np.asarray(level_mask(map_name, pd.Series(r.z), lower))
        return np.where(keep, r.x, np.nan), np.where(keep, r.y, np.nan)  # se corta donde cambia de piso

    if by == "Resultado":
        groups = [("ronda ganada", WON, [r for r in rs if r.won]), ("ronda perdida", LOST, [r for r in rs if not r.won])]
    else:
        demos = list(dict.fromkeys(r.demo_id for r in rs))
        groups = [(next(r.match for r in rs if r.demo_id == d) if i < 8 else "", SERIES[i % len(SERIES)],
                   [r for r in rs if r.demo_id == d]) for i, d in enumerate(demos)]
    # Con muchas rondas, trazo más fino y transparente: así se ve la ruta habitual y ningún color tapa al otro
    many = len(rs)
    alpha, width = (170, 2.2) if many < 15 else (110, 2.0) if many < 60 else (80, 1.6)
    for name, col, group in sorted(groups, key=lambda g: -len(g[2])):  # el grupo más grande, abajo
        m.paths([on_level(r) for r in group], col, name=name if group else "", alpha=alpha, width=width)
    # final de cada ruta: punto si seguía vivo, ✕ si murió en la ventana
    small = many >= 60
    for died, sym, size in ((False, "o", 6 if small else 8), (True, "x", 10 if small else 12)):
        sel = [r for r in rs if r.died == died]
        if sel:
            xy = [on_level(r) for r in sel]
            m.points([x[-1] for x, _ in xy], [y[-1] for _, y in xy], DIED if died else "#e8e6e3", size=size,
                     symbol=sym, outline=not died, tips=[r.label for r in sel])
    p.add(m.finish())
    n_demos = len({r.demo_id for r in rs})
    won = sum(r.won for r in rs)
    p.caption(f"{len(rs)} rondas de {side} en {n_demos} partida(s) · segundos {a} a {b} · ganó {won} "
              f"({100 * won / len(rs):.0f} %) · murió dentro de la ventana en {sum(r.died for r in rs)}")
    return p

