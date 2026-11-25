"""Navegación entre vistas: desde cualquier gráfico o tabla se puede saltar al replay de una ronda en un segundo.

Las vistas no conocen a la ventana principal: emiten acá y la ventana, que está conectada, hace el salto."""
from __future__ import annotations

from PySide6.QtCore import QObject, Signal


class _Navigator(QObject):
    replay = Signal(str, int, object)  # demo_id, ronda, segundo de ronda (None = desde el principio)
    replay_tick = Signal(str, int, int)  # demo_id, ronda, tick (tablas que no traen el segundo de ronda)
    demo = Signal(str)  # abrir una partida en "Demo individual"
    review = Signal(object, str)  # [(demo_id, ronda, segundo, texto[, steamid a seguir])], título


_nav: _Navigator | None = None


def navigator() -> _Navigator:
    global _nav
    if _nav is None:
        _nav = _Navigator()
    return _nav


def goto_replay(demo_id: str, rnd: int, t: float | None = None) -> None:
    navigator().replay.emit(str(demo_id), int(rnd), None if t is None else float(t))


def goto_tick(demo_id: str, rnd: int, tick: int) -> None:
    navigator().replay_tick.emit(str(demo_id), int(rnd), int(tick))


def start_review(items: list[tuple[str, int, float, str]], title: str) -> None:
    if items:
        navigator().review.emit(list(items), title)


def open_demo(demo_id: str) -> None:
    navigator().demo.emit(str(demo_id))
