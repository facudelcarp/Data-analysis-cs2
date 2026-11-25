"""Íconos de línea propios (SVG de 24x24, trazo 2), coloreados con el tema. Reemplazan a los emojis, que cambian
de aspecto según el sistema operativo y no respetan el color de la interfaz."""
from __future__ import annotations

import atexit
from functools import lru_cache

from PySide6.QtCore import QByteArray, QRectF, Qt
from PySide6.QtGui import QIcon, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer

# Solo el contenido del <svg>: trazos simples dibujados para esta app
PATHS = {
    "demo": '<circle cx="12" cy="12" r="8"/><circle cx="12" cy="12" r="3"/><path d="M12 2v4M12 18v4M2 12h4M18 12h4"/>',
    "team": '<circle cx="9" cy="8" r="3.5"/><path d="M2.5 20c0-3.6 2.9-6 6.5-6s6.5 2.4 6.5 6"/>'
            '<circle cx="17" cy="9" r="2.5"/><path d="M17 14c2.6 0 4.5 1.8 4.5 4.5"/>',
    "library": '<rect x="3" y="4" width="18" height="5" rx="1.5"/><rect x="3" y="11" width="18" height="5" rx="1.5"/>'
               '<path d="M3 20h18"/>',
    "dashboard": '<rect x="3" y="3" width="8" height="10" rx="1.5"/><rect x="13" y="3" width="8" height="6" rx="1.5"/>'
                 '<rect x="13" y="11" width="8" height="10" rx="1.5"/><rect x="3" y="15" width="8" height="6" rx="1.5"/>',
    "translate": '<path d="M4 6h10M9 4v2M6 6c0 4 3 7 7 8M12 6c0 3-2.5 6-7 8"/><path d="M13 20l4-9 4 9M14.5 17h5"/>',
    "raw": '<path d="M8 6l-5 6 5 6M16 6l5 6-5 6M14 4l-4 16"/>',
    "open": '<path d="M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/><path d="M12 10v6M9 13h6"/>',
    "folder": '<path d="M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/>',
    "save": '<path d="M5 3h11l3 3v13a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2z"/><path d="M7 3v5h8V3M7 21v-7h10v7"/>',
    "trash": '<path d="M4 7h16M9 7V4h6v3M6 7l1 13h10l1-13"/>',
    "play": '<path d="M7 4.5v15l12-7.5z"/>',
    "pause": '<path d="M8 4v16M16 4v16"/>',
    "drop": '<path d="M12 3v12M7 10l5 5 5-5"/><path d="M4 17v2a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-2"/>',
}


def _svg(name: str, color: str) -> bytes:
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="{color}" '
            f'stroke-width="2" stroke-linecap="round" stroke-linejoin="round">{PATHS[name]}</svg>').encode()


@lru_cache(maxsize=128)
def pixmap(name: str, color: str, size: int = 18, dpr: float = 2.0) -> QPixmap:
    px = QPixmap(int(size * dpr), int(size * dpr))
    px.fill(Qt.transparent)
    p = QPainter(px)
    p.setRenderHint(QPainter.Antialiasing)
    QSvgRenderer(QByteArray(_svg(name, color))).render(p, QRectF(0, 0, px.width(), px.height()))
    p.end()
    px.setDevicePixelRatio(dpr)
    return px


def clear_cache() -> None:
    """Suelta los QPixmap cacheados. Tiene que pasar mientras Qt sigue vivo: si quedan para el final del intérprete
    se destruyen después de la QApplication y el proceso se cae al salir (malloc_consolidate en Linux)."""
    pixmap.cache_clear()


atexit.register(clear_cache)  # salida normal de Python (y de los tests), antes de que se destruya Qt


def icon(name: str, color: str, active: str | None = None, size: int = 18) -> QIcon:
    """Ícono con su color normal y, si se pasa, otro para el estado seleccionado."""
    ic = QIcon(pixmap(name, color, size))
    if active:
        ic.addPixmap(pixmap(name, active, size), QIcon.Normal, QIcon.On)
        ic.addPixmap(pixmap(name, active, size), QIcon.Selected, QIcon.Off)
        ic.addPixmap(pixmap(name, active, size), QIcon.Active, QIcon.Off)
    return ic
