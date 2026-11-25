"""Replay 2D nativo: la ronda animada sobre el radar, dibujada con QPainter.

- Jugadores con dirección de movimiento, vida, ceguera y nombre; muertes marcadas con ✕.
- Humos, fuegos, flashes, HE y señuelos con su duración real; trazo del disparo en cada kill.
- Bomba plantada con cuenta regresiva, defuse y detonación.
- Seguir a un jugador (clic sobre él o desde la lista) con su estela.
- Rueda = zoom en el cursor, arrastrar = mover, doble clic = encuadre inicial.
- Espacio = play/pausa, ← / → = 5 s atrás/adelante, clic en el kill feed = saltar a esa kill.
"""
from __future__ import annotations

import math

import numpy as np
from PySide6.QtCore import QElapsedTimer, QPointF, QRectF, Qt, QTimer
from PySide6.QtGui import QColor, QFont, QKeySequence, QPainter, QPainterPath, QPen, QPixmap, QShortcut, QTransform
from PySide6.QtWidgets import (QCheckBox, QFrame, QHBoxLayout, QLabel, QListWidget, QListWidgetItem, QPushButton,
                               QSizePolicy, QSlider, QVBoxLayout, QWidget)

from .. import replay, stats
from ..maps import RADAR_SIZE, radar_image
from ..palette import BORDER, MUTED, SIDE_COLORS, SURFACE, TEXT
from ..parser import DemoData
from . import icons
from .page import Combo, Segmented, level_selector
from .widgets import plain as w_plain

GOLD = "#ffd166"
SPEEDS = {"0.5x": 0.5, "1x": 1.0, "2x": 2.0, "4x": 4.0}


def _c(hex_or_rgb, alpha: float | None = None) -> QColor:
    c = QColor(hex_or_rgb) if isinstance(hex_or_rgb, str) else QColor(*hex_or_rgb)
    if alpha is not None:
        c.setAlphaF(max(0.0, min(1.0, alpha)))
    return c


def fmt_time(s: float) -> str:
    sign = "-" if s < 0 else ""
    s = abs(s)
    return f"{sign}{int(s // 60)}:{int(s % 60):02d}"


class ReplayCanvas(QWidget):
    """Lienzo del replay. Dibuja `self.rr` en el segundo `self.t`."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumSize(360, 340)  # con ventanas bajas (o la barra de revisión) no pisa los controles
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.setMouseTracking(True)
        self.rr: replay.RoundReplay | None = None
        self.t = 0.0
        self.radar: QPixmap | None = None
        self.zoom, self.pan = 1.0, QPointF(0, 0)
        self.selected: str | None = None
        self.follow = False
        self.show_util = self.show_names = self.show_trail = True
        self._drag: QPointF | None = None
        self.on_select = None  # callback(steamid | None)

    # ------------------------------------------------------------------ estado
    def set_round(self, rr: replay.RoundReplay, map_name: str, lower: bool) -> None:
        self.rr = rr
        self.t = rr.t_min
        # Todo lo que no depende del segundo se calcula una vez por ronda (en el cuadro solo se interpola)
        self.dead = rr.death_time()
        g = rr.grenades
        self.g_arr = list(zip(g["t"].to_numpy(float), g["type"].tolist(), g["x"].to_numpy(float),
                              g["y"].to_numpy(float), strict=True))
        k = rr.kills
        self.k_arr = list(zip(*(k[c].to_numpy(float) for c in ("t", "vx", "vy", "ax", "ay")), k["victim_side"].tolist(),
                              strict=True))
        b = rr.bomb
        planted = b[b["event"] == "bomb_planted"]
        self.plant = (float(planted["t"].iloc[0]), float(planted["x"].iloc[0]), float(planted["y"].iloc[0])) \
            if len(planted) and np.isfinite(planted["x"].iloc[0]) else None
        self.defuse_t = float(b.loc[b["event"] == "bomb_defused", "t"].min()) if len(b) else math.nan
        self.explode_t = float(b.loc[b["event"] == "bomb_exploded", "t"].min()) if len(b) else math.nan
        self.blind = {sid: (grp["t"].to_numpy(float), (grp["t"] + grp["dur"]).to_numpy(float))
                      for sid, grp in rr.blinds.groupby("sid")} if len(rr.blinds) else {}
        img = radar_image(map_name, lower=lower) or radar_image(map_name)
        self.radar = QPixmap(str(img)) if img else None
        if self.selected and not any(tr.steamid == self.selected for tr in rr.tracks):
            self.selected = None
        self.update()

    def reset_view(self) -> None:
        self.zoom, self.pan = 1.0, QPointF(0, 0)
        self.update()

    def _base(self) -> tuple[float, QPointF]:
        s = min(self.width(), self.height()) / RADAR_SIZE
        return s, QPointF((self.width() - RADAR_SIZE * s) / 2, (self.height() - RADAR_SIZE * s) / 2)

    def transform(self) -> QTransform:
        s, off = self._base()
        if self.follow and self.selected and self.rr:
            tr = next((x for x in self.rr.tracks if x.steamid == self.selected), None)
            if tr is not None:
                x, y, *_ = tr.at(self.t)
                k = s * self.zoom
                return QTransform(k, 0, 0, k, self.width() / 2 - x * k, self.height() / 2 - y * k)
        k = s * self.zoom  # el zoom con la rueda corrige `pan` para dejar fijo el punto bajo el cursor
        return QTransform(k, 0, 0, k, off.x() + self.pan.x(), off.y() + self.pan.y())

    # ------------------------------------------------------------------ mouse
    def wheelEvent(self, e):  # noqa: N802 (API de Qt)
        factor = 1.15 if e.angleDelta().y() > 0 else 1 / 1.15
        new = max(1.0, min(6.0, self.zoom * factor))
        if new == self.zoom:
            return
        # zoom manteniendo fijo el punto bajo el cursor
        inv, _ = self.transform().inverted()
        world = inv.map(e.position())
        self.zoom = new
        after = self.transform().map(world)
        self.pan += e.position() - after
        self.update()

    def mousePressEvent(self, e):  # noqa: N802
        if e.button() == Qt.LeftButton:
            self._drag = e.position()
            self._press = e.position()

    def mouseMoveEvent(self, e):  # noqa: N802
        if self._drag is not None and not self.follow:
            self.pan += e.position() - self._drag
            self._drag = e.position()
            self.update()

    def mouseReleaseEvent(self, e):  # noqa: N802
        moved = self._drag is not None and (e.position() - self._press).manhattanLength() > 4
        self._drag = None
        if moved or not self.rr:
            return
        inv, _ = self.transform().inverted()
        w = inv.map(e.position())
        best, dist = None, 22.0
        dead = self.dead
        for tr in self.rr.tracks:
            if dead.get(tr.steamid, math.inf) <= self.t:
                continue
            x, y, *_ = tr.at(self.t)
            dd = math.hypot(w.x() - x, w.y() - y)
            if dd < dist:
                best, dist = tr.steamid, dd
        self.selected = best if best != self.selected else None
        if self.on_select:
            self.on_select(self.selected)
        self.update()

    def mouseDoubleClickEvent(self, e):  # noqa: N802
        self.reset_view()

    # ------------------------------------------------------------------ dibujo
    def paintEvent(self, _):  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.fillRect(self.rect(), _c("#10100f"))
        if not self.rr:
            p.setPen(_c(MUTED))
            p.drawText(self.rect(), Qt.AlignCenter, "Sin datos de posiciones para esta ronda.")
            return
        p.setTransform(self.transform())
        if self.radar:
            p.drawPixmap(QRectF(0, 0, RADAR_SIZE, RADAR_SIZE), self.radar, QRectF(self.radar.rect()))
        else:
            p.setPen(QPen(_c((255, 255, 255, 13)), 1))
            for i in range(64, RADAR_SIZE, 64):
                p.drawLine(i, 0, i, RADAR_SIZE)
                p.drawLine(0, i, RADAR_SIZE, i)
        t = self.t
        rr = self.rr
        # En coordenadas del mapa: lo que tiene tamaño físico (humos, fuegos) y la estela
        if self.show_util:
            self._grenades(p, t)
        if self.selected and self.show_trail:
            self._trail(p, t)
        # En píxeles de pantalla: marcas, bomba y jugadores mantienen su tamaño con cualquier zoom
        self._tf = p.transform()
        p.resetTransform()
        self._deaths(p, t)
        self._bomb(p, t)
        self._players(p, t)
        self._hud(p, t, rr)
        p.end()

    def _sp(self, x: float, y: float) -> tuple[float, float]:
        q = self._tf.map(QPointF(x, y))
        return q.x(), q.y()

    def _circle(self, p: QPainter, x, y, r, fill: QColor | None, pen: QPen | None) -> None:
        p.setBrush(fill if fill is not None else Qt.NoBrush)
        p.setPen(pen if pen is not None else Qt.NoPen)
        p.drawEllipse(QPointF(x, y), r, r)

    def _emoji(self, p: QPainter, x, y, s: str, size: int = 11) -> None:
        f = p.font()
        f.setPointSizeF(size * 0.75)
        p.setFont(f)
        p.setPen(_c("#ffffff"))
        p.drawText(QRectF(x - 12, y - 10, 24, 20), Qt.AlignCenter, s)

    def _grenades(self, p: QPainter, t: float) -> None:
        for gt, kind, x, y in self.g_arr:
            e = t - gt
            if not np.isfinite(x) or e < 0:
                continue
            if kind == "Humo" and e <= replay.SMOKE_S:
                a = (e / 1.5 if e < 1.5 else ((replay.SMOKE_S - e) / 2 if e > replay.SMOKE_S - 2 else 1)) * 0.75
                self._circle(p, x, y, 45, _c((180, 185, 190), a), QPen(_c((230, 235, 240), 0.4), 2))
            elif kind == "Fuego" and e <= replay.FIRE_S:
                a = (e / 0.6 if e < 0.6 else (replay.FIRE_S - e if e > replay.FIRE_S - 1 else 1)) * 0.7
                self._circle(p, x, y, 36, _c((225, 65, 15), a * 0.75), QPen(_c((255, 175, 30), a * 0.9), 2.5))
                self._circle(p, x, y, 18, _c((255, 195, 45), a * 0.5), None)
            elif kind == "Granada HE" and e <= replay.HE_S:
                k = e / replay.HE_S
                self._circle(p, x, y, 10 + k * 38, _c((230, 75, 20), (1 - k) * 0.35), QPen(_c((255, 215, 75), 1 - k), 3))
            elif kind == "Flash" and e <= replay.FLASH_S:
                k = e / replay.FLASH_S
                self._circle(p, x, y, 12 + k * 45, _c((255, 255, 220), (1 - k) * 0.35),
                             QPen(_c((255, 255, 240), (1 - k) * 0.95), 3.5))
            elif kind == "Señuelo" and e <= replay.DECOY_S:
                a = (replay.DECOY_S - e) / 2 if e > replay.DECOY_S - 2 else 0.7
                self._circle(p, x, y, 14, _c((144, 133, 233), a * 0.4), QPen(_c((144, 133, 233), a), 2))

    def _deaths(self, p: QPainter, t: float) -> None:
        for kt, vx, vy, ax, ay, side in self.k_arr:
            if kt > t or not np.isfinite(vx):
                continue
            vx, vy = self._sp(vx, vy)
            if np.isfinite(ax):
                ax, ay = self._sp(ax, ay)
            p.setPen(QPen(_c(SIDE_COLORS.get(side, MUTED), 0.6), 2.5))
            p.drawLine(QPointF(vx - 7, vy - 7), QPointF(vx + 7, vy + 7))
            p.drawLine(QPointF(vx + 7, vy - 7), QPointF(vx - 7, vy + 7))
            e = t - kt
            if e < 0.7 and np.isfinite(ax):
                pen = QPen(_c((255, 215, 0), 1 - e / 0.7), 2.5)
                pen.setDashPattern([3, 3])
                p.setPen(pen)
                p.drawLine(QPointF(ax, ay), QPointF(vx, vy))

    def _bomb(self, p: QPainter, t: float) -> None:
        if self.plant is None or self.plant[0] > t:
            return
        pt, x, y = self.plant
        x, y = self._sp(x, y)
        defused = self.defuse_t <= t
        exploded = self.explode_t <= t
        pulse = 1 + 0.15 * math.sin(t * 8)
        fill = _c((57, 135, 229), 0.6) if defused else (_c((255, 60, 0), 0.8) if exploded else _c((255, 50, 50), 0.7))
        self._circle(p, x, y, 14 * pulse, fill, QPen(_c("#ffffff"), 2))
        label = "DEFUSED" if defused else ("EXPLOTÓ" if exploded else f"C4 {max(0, replay.BOMB_TIMER_S - (t - pt)):.0f}s")
        f = QFont(p.font())
        f.setBold(True)
        f.setPointSizeF(8.5)
        p.setFont(f)
        p.setPen(_c("#ffffff"))
        p.drawText(QRectF(x - 50, y - 36, 100, 16), Qt.AlignCenter, label)

    def _trail(self, p: QPainter, t: float) -> None:
        tr = next((x for x in self.rr.tracks if x.steamid == self.selected), None)
        if tr is None:
            return
        m = tr.t <= t
        if m.sum() < 2:
            return
        path = QPainterPath(QPointF(tr.x[m][0], tr.y[m][0]))
        for x, y in zip(tr.x[m][1:], tr.y[m][1:], strict=True):
            path.lineTo(x, y)
        pen = QPen(_c(SIDE_COLORS.get(tr.side, GOLD), 0.75), 3.5)
        pen.setDashPattern([2, 2])
        p.setPen(pen)
        p.setBrush(Qt.NoBrush)
        p.drawPath(path)

    def _players(self, p: QPainter, t: float) -> None:
        rr = self.rr
        dead = self.dead
        f = QFont(p.font())
        for tr in rr.tracks:
            if dead.get(tr.steamid, math.inf) <= t:
                continue
            x, y, hp, ang, speed = tr.at(t)
            x, y = self._sp(x, y)
            sel = tr.steamid == self.selected
            color = _c(SIDE_COLORS.get(tr.side, MUTED))
            if sel:
                self._circle(p, x, y, 18, _c(GOLD, 0.25), QPen(_c(GOLD), 2.5))
            if speed > 0.4:
                ln = 24 if sel else 18
                pen = QPen(_c(GOLD) if sel else _c((255, 255, 255), 0.8), 4 if sel else 3)
                pen.setCapStyle(Qt.RoundCap)
                p.setPen(pen)
                p.drawLine(QPointF(x, y), QPointF(x + math.cos(ang) * ln, y + math.sin(ang) * ln))
            self._circle(p, x, y, 11, color, QPen(_c(GOLD) if sel else _c("#ffffff"), 3 if sel else 2))
            if 0 < hp < 100:
                c = "#06d6a0" if hp > 50 else (GOLD if hp > 25 else "#ef476f")
                p.setPen(QPen(_c(c), 2.5))
                p.setBrush(Qt.NoBrush)
                p.drawArc(QRectF(x - 14, y - 14, 28, 28), 90 * 16, int(-360 * 16 * hp / 100))
            if tr.steamid in self.blind:
                starts, ends = self.blind[tr.steamid]
                m = (starts <= t) & (t <= ends)
                if m.any():
                    end = float(ends[m].max())
                    a = min(1.0, (end - t) / 1.2)
                    self._circle(p, x, y, 16, _c((255, 255, 255), a * 0.45), QPen(_c((255, 255, 240), a * 0.9), 2.5))
            if self.show_names or sel:
                f.setPointSizeF(9 if sel else 8)
                f.setBold(True)
                p.setFont(f)
                fm = p.fontMetrics()
                tw = fm.horizontalAdvance(tr.name) + 8
                r = QRectF(x - tw / 2, y + 15, tw, fm.height() + 2)
                p.setPen(Qt.NoPen)
                p.setBrush(_c((0, 0, 0), 0.6))
                p.drawRoundedRect(r, 3, 3)
                p.setPen(_c(GOLD) if sel else _c("#ffffff"))
                p.drawText(r, Qt.AlignCenter, tr.name)

    def _hud(self, p: QPainter, t: float, rr: replay.RoundReplay) -> None:
        dead = self.dead
        alive = {"CT": 0, "T": 0}
        for tr in rr.tracks:
            if dead.get(tr.steamid, math.inf) > t:
                alive[tr.side] = alive.get(tr.side, 0) + 1
        f = QFont(p.font())
        f.setBold(True)
        f.setPointSizeF(12)
        p.setFont(f)
        box = QRectF(10, 10, 250, 30)
        p.setPen(Qt.NoPen)
        p.setBrush(_c((0, 0, 0), 0.55))
        p.drawRoundedRect(box, 6, 6)
        p.setPen(_c("#ffffff"))
        p.drawText(box.adjusted(10, 0, 0, 0), Qt.AlignVCenter | Qt.AlignLeft, f"Ronda {rr.round} · {fmt_time(t)}")
        p.setPen(_c(SIDE_COLORS["CT"]))
        p.drawText(box.adjusted(0, 0, -50, 0), Qt.AlignVCenter | Qt.AlignRight, f"{alive.get('CT', 0)}")
        p.setPen(_c(MUTED))
        p.drawText(box.adjusted(0, 0, -36, 0), Qt.AlignVCenter | Qt.AlignRight, "v")
        p.setPen(_c(SIDE_COLORS["T"]))
        p.drawText(box.adjusted(0, 0, -12, 0), Qt.AlignVCenter | Qt.AlignRight, f"{alive.get('T', 0)}")


class RosterWidget(QWidget):
    """Vivos de cada lado con su barra de vida, dibujado a mano (más liviano que texto enriquecido)."""

    ROW = 19

    def __init__(self, parent=None):
        super().__init__(parent)
        self.groups: list[tuple[str, str, list[tuple[str, int, bool]]]] = []
        self.setFixedWidth(290)

    def set_groups(self, groups) -> None:
        self.groups = groups
        rows = sum(1 + len(g[2]) for g in groups)
        self.setFixedHeight(16 + rows * self.ROW + 8 * len(groups))
        self.update()

    def paintEvent(self, _):  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setPen(QPen(_c(BORDER), 1))
        p.setBrush(_c(SURFACE))
        p.drawRoundedRect(QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5), 8, 8)
        y = 8.0
        f = QFont(p.font())
        w = self.width()
        for title, color, rows in self.groups:
            f.setBold(True)
            p.setFont(f)
            p.setPen(_c(color))
            p.drawText(QRectF(10, y, w - 20, self.ROW), Qt.AlignVCenter | Qt.AlignLeft, title)
            y += self.ROW
            f.setBold(False)
            p.setFont(f)
            for name, hp, dead in rows:
                r = QRectF(10, y, 130, self.ROW)
                f.setStrikeOut(dead)
                p.setFont(f)
                p.setPen(_c(MUTED if dead else TEXT))
                p.drawText(r, Qt.AlignVCenter | Qt.AlignLeft, p.fontMetrics().elidedText(name, Qt.ElideRight, 128))
                f.setStrikeOut(False)
                p.setFont(f)
                bar = QRectF(146, y + 6, w - 196, self.ROW - 12)
                p.setPen(Qt.NoPen)
                p.setBrush(_c(BORDER))
                p.drawRoundedRect(bar, 3, 3)
                if hp > 0:
                    c = "#06d6a0" if hp > 50 else (GOLD if hp > 25 else "#ef476f")
                    p.setBrush(_c(c))
                    p.drawRoundedRect(QRectF(bar.x(), bar.y(), bar.width() * hp / 100, bar.height()), 3, 3)
                p.setPen(_c(MUTED))
                p.drawText(QRectF(w - 44, y, 34, self.ROW), Qt.AlignVCenter | Qt.AlignRight, "✕" if dead else str(hp))
                y += self.ROW
            y += 8
        p.end()


class ReplayPanel(QWidget):
    """Reproductor completo: filtros de ronda, lienzo, controles, roster y kill feed."""

    FRAME_MS = 16  # ~60 FPS

    def __init__(self, d: DemoData, parent=None):
        super().__init__(parent)
        self.d = d
        self.teams = {"A": d.meta["team_a"], "B": d.meta["team_b"]}
        self.rt = replay.tag_round_buys(stats.round_timeline(d), self.teams)
        self.filters = replay.filter_options(self.rt)
        self.speed = 1.0
        self.playing = False
        self._clock = QElapsedTimer()
        self._timer = QTimer(self)
        self._timer.setTimerType(Qt.PreciseTimer)
        self._timer.timeout.connect(self._tick)
        self._side_sig = None

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 10, 0, 6)
        lay.setSpacing(8)
        if d.positions.empty or self.rt.empty:
            msg = QLabel("Esta demo no tiene posiciones registradas (se cargó sin muestreo de ticks).")
            msg.setObjectName("Muted")
            lay.addWidget(msg)
            lay.addStretch()
            return

        top = QHBoxLayout()
        self.filter = Combo("Compras", [(k, k) for k in self.filters], min_width=260)
        self.round_box = Combo("Ronda", [], min_width=320)
        self.prev_btn, self.next_btn = QPushButton("◀ Anterior"), QPushButton("Siguiente ▶")
        top.addWidget(self.filter, 2)
        top.addWidget(self.prev_btn)
        top.addWidget(self.round_box, 3)
        top.addWidget(self.next_btn)
        self.level = level_selector(d.meta["map"])
        if self.level:
            top.addWidget(self.level)
            self.level.changed.connect(lambda _: self._load_round())
        lay.addLayout(top)

        self.banner = QHBoxLayout()
        lay.addLayout(self.banner)

        mid = QHBoxLayout()
        self.canvas = ReplayCanvas()
        self.canvas.on_select = self._on_canvas_select
        mid.addWidget(self.canvas, 1)
        side = QVBoxLayout()
        self.roster = RosterWidget()
        side.addWidget(self.roster)
        feed_title = QLabel("Kill feed (clic = ir a esa kill)")
        feed_title.setObjectName("Muted")
        side.addWidget(feed_title)
        self.feed = QListWidget()
        self.feed.setFixedWidth(290)
        self.feed.itemClicked.connect(self._jump_to_kill)
        side.addWidget(self.feed, 1)
        mid.addLayout(side)
        lay.addLayout(mid, 1)

        ctrl = QHBoxLayout()
        self.play_btn = QPushButton(icons.icon("play", "#14110c"), "  Play")
        self.play_btn.setObjectName("Primary")
        self.play_btn.setFixedWidth(96)
        self.play_btn.clicked.connect(self.toggle)
        ctrl.addWidget(self.play_btn)
        self.speeds = Segmented(list(SPEEDS), value="1x")
        self.speeds.changed.connect(lambda v: setattr(self, "speed", SPEEDS[v]))
        ctrl.addWidget(self.speeds)
        self.scrub = QSlider(Qt.Horizontal)
        self.scrub.setRange(0, 10_000)
        self.scrub.valueChanged.connect(self._on_scrub)
        ctrl.addWidget(self.scrub, 1)
        self.time_lbl = QLabel("0:00 / 0:00")
        self.time_lbl.setMinimumWidth(90)
        ctrl.addWidget(self.time_lbl)
        lay.addLayout(ctrl)

        opts = QHBoxLayout()
        for text, attr in (("Utilidad", "show_util"), ("Nombres", "show_names"), ("Estela del seguido", "show_trail")):
            cb = QCheckBox(text)
            cb.setChecked(True)
            cb.toggled.connect(lambda on, a=attr: (setattr(self.canvas, a, on), self.canvas.update()))
            opts.addWidget(cb)
        self.follow_box = Combo("Seguir a", [(None, "Nadie")], min_width=180)
        self.follow_box.changed.connect(self._on_follow_pick)
        opts.addWidget(self.follow_box)
        self.follow_cam = QCheckBox("Cámara sobre el seguido")
        self.follow_cam.toggled.connect(lambda on: (setattr(self.canvas, "follow", on), self.canvas.update()))
        opts.addWidget(self.follow_cam)
        reset = QPushButton("Encuadre inicial")
        reset.clicked.connect(self.canvas.reset_view)
        opts.addWidget(reset)
        tag = QPushButton("Etiquetar ronda…")
        tag.setToolTip("Anotar la estrategia que viste (T y CT) para medir qué tan bien la lee la app")
        tag.clicked.connect(self._label_round)
        opts.addWidget(tag)
        opts.addStretch()
        hint = QLabel("Espacio = play/pausa · ← → = 5 s · rueda = zoom · clic en un jugador = seguirlo")
        hint.setObjectName("Muted")
        opts.addWidget(hint)
        lay.addLayout(opts)

        for seq, fn in ((Qt.Key_Space, self.toggle), (Qt.Key_Left, lambda: self.seek(self.canvas.t - 5)),
                        (Qt.Key_Right, lambda: self.seek(self.canvas.t + 5))):
            sc = QShortcut(QKeySequence(seq), self)
            sc.setContext(Qt.WidgetWithChildrenShortcut)
            sc.activated.connect(fn)

        self.filter.changed.connect(self._fill_rounds)
        self.round_box.changed.connect(lambda _: self._load_round())
        self.prev_btn.clicked.connect(lambda: self._step_round(-1))
        self.next_btn.clicked.connect(lambda: self._step_round(1))
        self._fill_rounds()

    # ------------------------------------------------------------------ rondas
    def _round_label(self, r: int) -> str:
        row = self.rt[self.rt["round"] == r].iloc[0]
        return (f"Ronda {r} · Gana {self.teams.get(row['winner_team'], row['winner_team'])} "
                f"({row['score_a']}-{row['score_b']}) — {row['matchup_simp']}")

    def _fill_rounds(self, *_) -> None:
        rounds = self.filters[self.filter.value]
        box = self.round_box.box
        box.blockSignals(True)
        box.clear()
        for r in rounds:
            box.addItem(self._round_label(r), r)
        box.blockSignals(False)
        self._load_round()

    def goto(self, rnd: int, t: float | None = None) -> bool:
        """Muestra la ronda `rnd` desde el segundo `t` (llamado desde otras vistas)."""
        if rnd not in self.filters[self.filter.value]:
            self.filter.box.setCurrentIndex(0)  # "Todas las rondas": rearma la lista
        box = self.round_box.box
        i = box.findData(rnd)
        if i < 0:
            return False
        if i != box.currentIndex():
            box.setCurrentIndex(i)  # carga la ronda
        rr = getattr(self, "rr", None)
        if rr is not None:
            self.seek(rr.t_min if t is None else t)
        # recién armada, la pestaña se muestra en la próxima vuelta del event loop: el foco (para las teclas), después
        QTimer.singleShot(0, self.canvas.setFocus)
        return True

    def _label_round(self) -> None:
        from .label_dialog import LabelDialog
        r = self.round_box.value
        if r is not None:
            LabelDialog(self.d.demo_id, int(r), self).exec()

    def follow(self, steamid: str | None) -> None:
        """Seleccionar a un jugador (resaltado, con estela) como si se hubiera hecho clic en él."""
        i = self.follow_box.box.findData(steamid)
        if i >= 0:
            self.follow_box.box.setCurrentIndex(i)
            self._on_follow_pick(steamid)

    def _step_round(self, delta: int) -> None:
        box = self.round_box.box
        box.setCurrentIndex(max(0, min(box.count() - 1, box.currentIndex() + delta)))

    def _load_round(self) -> None:
        r = self.round_box.value
        if r is None:
            return
        self.pause()
        info = self.rt[self.rt["round"] == r].iloc[0]
        self.rr = replay.build_round(self.d, int(r), info)
        box = self.round_box.box
        self.prev_btn.setEnabled(box.currentIndex() > 0)
        self.next_btn.setEnabled(box.currentIndex() < box.count() - 1)
        self._fill_banner(info)
        if self.rr is None:
            self.canvas.rr = None
            self.canvas.update()
            return
        self.canvas.set_round(self.rr, self.d.meta["map"], bool(self.level and self.level.value == "Inferior"))
        fb = self.follow_box.box
        keep = fb.currentData()
        fb.blockSignals(True)
        fb.clear()
        fb.addItem("Nadie", None)
        for tr in self.rr.tracks:
            fb.addItem(f"{tr.name} ({tr.side})", tr.steamid)
        fb.setCurrentIndex(max(0, fb.findData(keep)))
        fb.blockSignals(False)
        self.canvas.selected = fb.currentData()
        self.feed.clear()
        for k in self.rr.kills.itertuples():
            item = QListWidgetItem(f"{fmt_time(k.t)}  {k.attacker} ✕ {k.victim}  ·  {k.weapon}{' (HS)' if k.headshot else ''}")
            item.setData(Qt.UserRole, float(k.t))
            item.setForeground(QColor(SIDE_COLORS.get(k.attacker_side, TEXT)))
            self.feed.addItem(item)
        self._side_sig = None
        self.seek(self.rr.t_min)

    def _fill_banner(self, row) -> None:
        while self.banner.count():
            it = self.banner.takeAt(0)
            if it.widget():
                it.widget().hide()  # fuera de la vista ya: el borrado real llega después
                it.widget().deleteLater()
        ct_team = self.teams.get(str(row["ct_team"]), "CT")
        t_team = self.teams.get(str(row["t_team"]), "T")

        def card(title: str, value: str, color: str) -> QFrame:
            f = QFrame()
            f.setObjectName("Card")
            f.setStyleSheet(f"QFrame#Card {{ border-left: 3px solid {color}; }}")
            v = QVBoxLayout(f)
            v.setContentsMargins(10, 5, 10, 5)
            a = QLabel(title)
            a.setTextFormat(Qt.PlainText)
            a.setStyleSheet(f"color:{color}; font-weight:700; font-size:8pt; border:none;")
            b = QLabel(value)
            b.setTextFormat(Qt.PlainText)
            b.setStyleSheet("font-weight:700; border:none;")
            v.addWidget(a)
            v.addWidget(b)
            return f

        self.banner.addWidget(card(f"CT · {ct_team}", f"{row['ct_buy']} · ${int(row['ct_equip']):,}", SIDE_COLORS["CT"]), 1)
        self.banner.addWidget(card(f"T · {t_team}", f"{row['t_buy']} · ${int(row['t_equip']):,}", SIDE_COLORS["T"]), 1)
        context = w_plain(replay.economy_context(row["ct_equip"], row["t_equip"], row["matchup_simp"]))
        self.banner.addWidget(card("SITUACIÓN", context, MUTED), 1)

    # ------------------------------------------------------------------ reproducción
    def toggle(self) -> None:
        self.pause() if self.playing else self.play()

    def play(self) -> None:
        if not getattr(self, "rr", None):
            return
        if self.canvas.t >= self.rr.t_max:
            self.seek(self.rr.t_min)
        self.playing = True
        self.play_btn.setText("  Pausa")
        self.play_btn.setIcon(icons.icon("pause", "#14110c"))
        self._clock.start()
        self._timer.start(self.FRAME_MS)

    def pause(self) -> None:
        self.playing = False
        if hasattr(self, "play_btn"):
            self.play_btn.setText("  Play")
            self.play_btn.setIcon(icons.icon("play", "#14110c"))
        self._timer.stop()

    def _tick(self) -> None:
        dt = self._clock.restart() / 1000.0
        t = self.canvas.t + dt * self.speed
        if t >= self.rr.t_max:
            t = self.rr.t_max
            self.pause()
        self.seek(t)

    def seek(self, t: float) -> None:
        rr = getattr(self, "rr", None)
        if rr is None:
            return
        t = max(rr.t_min, min(rr.t_max, float(t)))
        self.canvas.t = t
        span = rr.t_max - rr.t_min
        self.scrub.blockSignals(True)
        self.scrub.setValue(int(10_000 * (t - rr.t_min) / span))
        self.scrub.blockSignals(False)
        self.time_lbl.setText(f"{fmt_time(t)} / {fmt_time(rr.t_max)}")
        self.canvas.update()
        self._update_side(t)

    def _on_scrub(self, v: int) -> None:
        rr = self.rr
        self.seek(rr.t_min + (rr.t_max - rr.t_min) * v / 10_000)

    def _jump_to_kill(self, item: QListWidgetItem) -> None:
        self.seek(item.data(Qt.UserRole) - 2.0)

    def _on_canvas_select(self, sid) -> None:
        fb = self.follow_box.box
        fb.blockSignals(True)
        fb.setCurrentIndex(max(0, fb.findData(sid)))
        fb.blockSignals(False)

    def _on_follow_pick(self, sid) -> None:
        self.canvas.selected = sid
        self.canvas.update()

    def _update_side(self, t: float) -> None:
        """Roster con vida y kill feed hasta el segundo t (solo se redibuja si algo cambió)."""
        rr = self.rr
        dead = self.canvas.dead
        state = []
        for tr in rr.tracks:
            is_dead = dead.get(tr.steamid, math.inf) <= t
            hp = 0 if is_dead else int(round(tr.at(t)[2]))
            state.append((tr.steamid, is_dead, hp // 5))
        n_kills = sum(1 for k in self.canvas.k_arr if k[0] <= t)
        sig = (tuple(state), n_kills)
        if sig == self._side_sig:
            return
        self._side_sig = sig
        groups = []
        for side, team_col in (("CT", "ct_team"), ("T", "t_team")):
            name = self.teams.get(str(rr.info.get(team_col, "")), side)
            rows = []
            for tr in [x for x in rr.tracks if x.side == side]:
                is_dead = dead.get(tr.steamid, math.inf) <= t
                rows.append((tr.name, 0 if is_dead else int(round(tr.at(t)[2])), is_dead))
            groups.append((f"{side} · {name}", SIDE_COLORS[side], rows))
        self.roster.set_groups(groups)
        for i in range(self.feed.count()):
            it = self.feed.item(i)
            it.setHidden(False)
            f = it.font()
            f.setBold(it.data(Qt.UserRole) <= t)
            it.setFont(f)
            c = it.foreground().color()
            c.setAlpha(255 if it.data(Qt.UserRole) <= t else 90)
            it.setForeground(c)

    def hideEvent(self, e):  # noqa: N802
        # al cambiar de pestaña no sigue reproduciendo en segundo plano (y al cerrar la app, los botones
        # pueden ya no existir)
        self._timer.stop()
        self.playing = False
        super().hideEvent(e)


def build(d: DemoData) -> QWidget:
    return ReplayPanel(d)

