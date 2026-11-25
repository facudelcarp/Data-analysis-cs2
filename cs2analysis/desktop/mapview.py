"""Mapa de CS2 con la imagen de radar de fondo, para dibujar posiciones, kills y granadas.

Se puede hacer zoom con la rueda y arrastrar. Las coordenadas del juego se pasan por `tf` (a píxeles de radar
si hay imagen; si no, se usan las del juego y la silueta del mapa sale de las posiciones de los jugadores)."""
from __future__ import annotations

from functools import lru_cache
from html import escape

import numpy as np
import pandas as pd
import pyqtgraph as pg
from PySide6.QtCore import Qt
from PySide6.QtGui import QImage

from ..maps import RADAR_SIZE, level_mask, map_info, radar_image
from ..palette import BORDER, MUTED, SURFACE

OUTLINE = "#1a1a19"


@lru_cache(maxsize=16)
def _radar_array(path: str) -> np.ndarray:
    img = QImage(path).convertToFormat(QImage.Format_RGBA8888)
    arr = pg.functions.ndarray_from_qimage(img).copy()  # (alto, ancho, 4)
    return arr


class MapView(pg.PlotWidget):
    def __init__(self, map_name: str, backdrop: pd.DataFrame | None = None, lower: bool = False, height: int = 640):
        super().__init__(background=SURFACE)
        self.setMenuEnabled(False)
        self.hideButtons()
        self.hideAxis("left")
        self.hideAxis("bottom")
        self.setAspectLocked(True)
        self.getPlotItem().getViewBox().setBorder(pg.mkPen(BORDER))
        self.setFixedHeight(height)
        self._legend: list[tuple[str, str]] = []
        info = map_info(map_name)
        img = radar_image(map_name, lower=lower) or (radar_image(map_name) if not lower else None)
        self.has_radar = bool(info and img)
        if self.has_radar:
            arr = _radar_array(str(img))
            item = pg.ImageItem(arr, axisOrder="row-major")
            item.setRect(0, 0, RADAR_SIZE, RADAR_SIZE)
            item.setOpacity(0.9)
            item.setZValue(-10)
            self.addItem(item)
            self.getPlotItem().getViewBox().invertY(True)  # el radar tiene la y hacia abajo
            self.setRange(xRange=(0, RADAR_SIZE), yRange=(0, RADAR_SIZE), padding=0.01)
            self._info = info
        else:
            self._info = None
            if backdrop is not None and len(backdrop):
                bd = backdrop[level_mask(map_name, backdrop["z"], lower)]
                bd = bd.iloc[:: max(1, len(bd) // 15000)]
                s = pg.ScatterPlotItem(bd["x"].to_numpy(), bd["y"].to_numpy(), size=4, pen=pg.mkPen(None),
                                       brush=pg.mkBrush(195, 194, 183, 26))
                s.setZValue(-10)
                self.addItem(s)

    def tf(self, x, y):
        x = np.asarray(x, dtype=float)
        y = np.asarray(y, dtype=float)
        if self._info is None:
            return x, y
        return self._info.to_radar(x, y)

    # ------------------------------------------------------------------ capas
    def points(self, x, y, color: str, name: str = "", size=10, symbol: str = "o", tips: list[str] | None = None,
               outline: bool = True, filled: bool = True) -> None:
        px, py = self.tf(x, y)
        pen = pg.mkPen(OUTLINE, width=2) if outline and filled else pg.mkPen(color, width=2)
        brush = pg.mkBrush(color) if filled else pg.mkBrush(None)
        item = pg.ScatterPlotItem(px, py, size=size, symbol=symbol, pen=pen, brush=brush, data=tips,
                                  hoverable=tips is not None, tip=(lambda x, y, data: data) if tips is not None else None)
        self.addItem(item)
        if name:
            self._legend.append((name, color))

    def segments(self, x1, y1, x2, y2, color: str, width: float = 1, alpha: int = 90, dashed: bool = False) -> None:
        ax, ay = self.tf(x1, y1)
        bx, by = self.tf(x2, y2)
        if not len(ax):
            return
        xs = np.empty(2 * len(ax))
        ys = np.empty(2 * len(ay))
        xs[0::2], xs[1::2] = ax, bx
        ys[0::2], ys[1::2] = ay, by
        c = pg.mkColor(color)
        c.setAlpha(alpha)
        self.addItem(pg.PlotDataItem(xs, ys, connect="pairs", pen=pg.mkPen(c, width=width,
                                                                           style=Qt.DotLine if dashed else Qt.SolidLine)))

    def paths(self, routes: list[tuple[np.ndarray, np.ndarray]], color: str, name: str = "", width: float = 2,
              alpha: int = 110) -> None:
        """Muchas trayectorias del mismo color en un solo trazo (cortado entre una y otra): 500 rondas se dibujan
        igual de rápido que 5. Donde se superponen, la ruta habitual queda más marcada."""
        if not routes:
            return
        xs, ys = [], []
        for x, y in routes:
            px, py = self.tf(x, y)
            xs += [px, [np.nan]]
            ys += [py, [np.nan]]
        c = pg.mkColor(color)
        c.setAlpha(alpha)
        pen = pg.mkPen(c, width=width)
        pen.setCapStyle(Qt.RoundCap)
        pen.setJoinStyle(Qt.RoundJoin)
        self.addItem(pg.PlotDataItem(np.concatenate(xs), np.concatenate(ys), connect="finite", pen=pen))
        if name:
            self._legend.append((name, color))

    def heat(self, x, y, bins: int = 140) -> None:
        """Mapa de calor: transparente donde no hay muestras para que se vea el radar debajo."""
        px, py = self.tf(x, y)
        if not len(px):
            return
        if self.has_radar:
            xr = yr = (0, RADAR_SIZE)
        else:
            xr, yr = (np.nanmin(px), np.nanmax(px)), (np.nanmin(py), np.nanmax(py))
        h, xe, ye = np.histogram2d(px, py, bins=bins, range=[xr, yr])
        h = h.T  # filas = y
        # escala logarítmica: unas pocas zonas concentran muchísimas muestras (spawns, posiciones fijas)
        v = np.log1p(h) / np.log1p(h.max()) if h.max() > 0 else h
        v = v ** 1.6  # más contraste: lo poco transitado queda tenue
        rgba = np.zeros((*v.shape, 4), dtype=np.ubyte)
        # azul -> celeste claro, con alfa creciente (0 donde no hay nada)
        rgba[..., 0] = (57 + (205 - 57) * v).astype(np.ubyte)
        rgba[..., 1] = (135 + (226 - 135) * v).astype(np.ubyte)
        rgba[..., 2] = (229 + (251 - 229) * v).astype(np.ubyte)
        rgba[..., 3] = np.where(h > 0, 25 + 225 * v, 0).astype(np.ubyte)
        item = pg.ImageItem(rgba, axisOrder="row-major")
        item.setRect(xe[0], ye[0], xe[-1] - xe[0], ye[-1] - ye[0])
        self.addItem(item)

    def finish(self) -> "MapView":
        if self.has_radar:
            # El encuadre es siempre el radar: con autoajuste, algunas capas (rutas cortadas por piso en Nuke)
            # corrían la vista y el mapa quedaba descentrado
            self.getPlotItem().getViewBox().disableAutoRange()
            self.setRange(xRange=(0, RADAR_SIZE), yRange=(0, RADAR_SIZE), padding=0.01)
        if self._legend:
            html = " &nbsp; ".join(f"<span style='color:{c}'>●</span> <span style='color:{MUTED}'>{escape(n)}</span>"
                                   for n, c in self._legend)
            self.setTitle(f"<span style='font-size:9pt'>{html}</span>")
        return self


def on_level(df: pd.DataFrame, zcol: str, map_name: str, lower: bool) -> pd.DataFrame:
    if df.empty or zcol not in df:
        return df
    return df[level_mask(map_name, df[zcol], lower)]
