"""Armado de páginas y controles: secciones, notas "Cómo leerlo", filas, filtros y pestañas que se arman al abrirse."""
from __future__ import annotations

from html import escape
from typing import Callable

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import (QButtonGroup, QComboBox, QFrame, QGridLayout, QHBoxLayout, QLabel, QPushButton,
                               QScrollArea, QSlider, QSpinBox, QTabWidget, QVBoxLayout, QWidget)

from ..maps import has_levels
from ..palette import ACCENT, BORDER, MUTED, SURFACE, SURFACE_2
from . import widgets as w


class Page(QWidget):
    """Columna de bloques con márgenes y espaciado uniformes."""

    def __init__(self, parent=None, margins=(0, 12, 0, 12)):
        super().__init__(parent)
        self.lay = QVBoxLayout(self)
        self.lay.setContentsMargins(*margins)
        self.lay.setSpacing(10)

    def add(self, widget: QWidget, stretch: int = 0) -> QWidget:
        self.lay.addWidget(widget, stretch)
        return widget

    def section(self, title: str) -> None:
        lbl = w.label(title, "Section")
        lbl.setTextFormat(Qt.PlainText)
        self.add(lbl)

    def sub(self, title: str) -> None:
        lbl = w.label(title)
        lbl.setStyleSheet("font-weight:700")
        self.add(lbl)

    def note(self, text: str) -> None:
        """'Cómo leerlo' debajo de un gráfico. Acepta **negrita** como en la web."""
        html = escape(text)
        while "**" in html:
            html = html.replace("**", "<b>", 1).replace("**", "</b>", 1)
        lbl = QLabel(f"💡 <b>Cómo leerlo:</b> {html}")
        lbl.setObjectName("Note")
        lbl.setWordWrap(True)
        self.add(lbl)

    def caption(self, text: str) -> None:
        lbl = w.label(text, "Note", wrap=True)
        lbl.setTextFormat(Qt.PlainText)
        self.add(lbl)

    def info(self, text: str, kind: str = "info") -> None:
        colors = {"info": "#3987e5", "ok": "#199e70", "warn": "#c98500"}
        lbl = w.label(text, wrap=True)
        lbl.setTextFormat(Qt.PlainText)
        lbl.setStyleSheet(f"background:{SURFACE}; border:1px solid {BORDER}; border-left:4px solid {colors[kind]};"
                          "border-radius:8px; padding:10px 12px;")
        self.add(lbl)

    def row(self, *widgets: QWidget, stretches: list[int] | None = None) -> QWidget:
        box = QWidget()
        h = QHBoxLayout(box)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(10)
        for i, x in enumerate(widgets):
            h.addWidget(x, (stretches or [1] * len(widgets))[i], Qt.AlignTop)
        return self.add(box)

    def grid(self, widgets: list[QWidget], cols: int = 2) -> QWidget:
        box = QWidget()
        g = QGridLayout(box)
        g.setContentsMargins(0, 0, 0, 0)
        g.setSpacing(10)
        for i, x in enumerate(widgets):
            g.addWidget(x, i // cols, i % cols)
        return self.add(box)

    def stretch(self) -> None:
        self.lay.addStretch()


def column(*widgets: QWidget) -> QWidget:
    box = QWidget()
    v = QVBoxLayout(box)
    v.setContentsMargins(0, 0, 0, 0)
    v.setSpacing(8)
    for x in widgets:
        v.addWidget(x)
    return box


def scrollable(content: QWidget) -> QScrollArea:
    area = QScrollArea()
    area.setWidgetResizable(True)
    area.setFrameShape(QFrame.NoFrame)
    area.setWidget(content)
    return area


class Slot(QWidget):
    """Lugar de una página que se vuelve a dibujar cuando cambia un filtro (sin rearmar el resto).

    `refresh` agrupa cambios seguidos (arrastrar un slider) en un solo redibujo."""

    DEBOUNCE_MS = 90

    def __init__(self, render: Callable[[], QWidget], parent=None):
        super().__init__(parent)
        self._render = render
        self._lay = QVBoxLayout(self)
        self._lay.setContentsMargins(0, 0, 0, 0)
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self.refresh_now)
        self.refresh_now()

    def refresh(self, *_) -> None:
        self._timer.start(self.DEBOUNCE_MS)

    @property
    def content(self) -> QWidget | None:
        item = self._lay.itemAt(0)
        return item.widget() if item else None

    def refresh_now(self) -> None:
        self._timer.stop()
        while self._lay.count():
            item = self._lay.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self._lay.addWidget(self._render())


class LazyTabs(QTabWidget):
    """Pestañas que se arman la primera vez que se abren: abrir una demo no calcula las diez."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._factories: dict[int, Callable[[], QWidget]] = {}
        self.currentChanged.connect(self._ensure)

    def add_lazy(self, factory: Callable[[], QWidget], title: str, scroll: bool = True) -> int:
        holder = QWidget()
        QVBoxLayout(holder).setContentsMargins(0, 0, 0, 0)
        i = self.addTab(holder, title)
        self._factories[i] = (factory, scroll)
        if i == self.currentIndex():
            self._ensure(i)
        return i

    def _ensure(self, i: int) -> None:
        item = self._factories.pop(i, None)
        if item is None:
            return
        factory, scroll = item
        content = factory()
        self.widget(i).layout().addWidget(scrollable(content) if scroll else content)

    def build_all(self) -> None:
        """Para tests: arma todas las pestañas."""
        for i in list(self._factories):
            self._ensure(i)


# --------------------------------------------------------------------------------------------
# Controles
# --------------------------------------------------------------------------------------------

SEG_QSS = f"""
QPushButton {{ background:{SURFACE}; border:1px solid {BORDER}; border-radius:0; padding:5px 12px; color:{MUTED}; }}
QPushButton:checked {{ background:rgba(240,163,61,.16); color:{ACCENT}; border-color:{ACCENT}; }}
"""


class Segmented(QWidget):
    """Botones excluyentes en fila (equivale a un radio horizontal)."""
    changed = Signal(str)

    def __init__(self, options: list[str], value: str | None = None, label: str = "", multi: bool = False,
                 values: list[str] | None = None, parent=None):
        super().__init__(parent)
        h = QHBoxLayout(self)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(0)
        if label:
            lbl = QLabel(label)
            lbl.setObjectName("Muted")
            h.addWidget(lbl)
            h.addSpacing(8)
        self.group = QButtonGroup(self)
        self.group.setExclusive(not multi)
        self.buttons: dict[str, QPushButton] = {}
        selected = set(values or []) if multi else {value or options[0]}
        for opt in options:
            b = QPushButton(opt)
            b.setCheckable(True)
            b.setChecked(opt in selected)
            b.setStyleSheet(SEG_QSS)
            b.setCursor(Qt.PointingHandCursor)
            self.group.addButton(b)
            self.buttons[opt] = b
            h.addWidget(b)
            b.toggled.connect(lambda on, o=opt: (on or multi) and self.changed.emit(o))
        h.addStretch()

    @property
    def value(self) -> str:
        return next((o for o, b in self.buttons.items() if b.isChecked()), "")

    @property
    def values(self) -> list[str]:
        return [o for o, b in self.buttons.items() if b.isChecked()]


class Combo(QWidget):
    """Selector con etiqueta: items = [(valor, texto)]."""
    changed = Signal(object)

    def __init__(self, label: str, items: list[tuple[object, str]], value=None, min_width: int = 200, parent=None):
        super().__init__(parent)
        h = QHBoxLayout(self)
        h.setContentsMargins(0, 0, 0, 0)
        if label:
            lbl = QLabel(label)
            lbl.setObjectName("Muted")
            h.addWidget(lbl)
        self.box = QComboBox()
        self.box.setMinimumWidth(min_width)
        for v, t in items:
            self.box.addItem(str(t), v)
        if value is not None and (i := self.box.findData(value)) >= 0:
            self.box.setCurrentIndex(i)
        self.box.currentIndexChanged.connect(lambda _: self.changed.emit(self.value))
        h.addWidget(self.box, 1)

    @property
    def value(self):
        return self.box.currentData()


class IntRange(QWidget):
    """Rango entero desde-hasta (p. ej. rondas)."""
    changed = Signal()

    def __init__(self, label: str, lo: int, hi: int, parent=None):
        super().__init__(parent)
        h = QHBoxLayout(self)
        h.setContentsMargins(0, 0, 0, 0)
        lbl = QLabel(label)
        lbl.setObjectName("Muted")
        h.addWidget(lbl)
        self.a, self.b = QSpinBox(), QSpinBox()
        for s, v in ((self.a, lo), (self.b, hi)):
            s.setRange(lo, hi)
            s.setValue(v)
            s.valueChanged.connect(self._fix)
        h.addWidget(self.a)
        h.addWidget(QLabel("a"))
        h.addWidget(self.b)
        h.addStretch()

    def _fix(self, *_):
        if self.a.value() > self.b.value():
            sender = self.sender()
            (self.b if sender is self.a else self.a).setValue(sender.value())
        self.changed.emit()

    @property
    def value(self) -> tuple[int, int]:
        return self.a.value(), self.b.value()


class Slider(QWidget):
    changed = Signal(int)

    def __init__(self, label: str, lo: int, hi: int, value: int, step: int = 1, suffix: str = "", parent=None):
        super().__init__(parent)
        h = QHBoxLayout(self)
        h.setContentsMargins(0, 0, 0, 0)
        lbl = QLabel(label)
        lbl.setObjectName("Muted")
        h.addWidget(lbl)
        self.s = QSlider(Qt.Horizontal)
        self.s.setRange(lo, hi)
        self.s.setSingleStep(step)
        self.s.setPageStep(step)
        self.s.setValue(value)
        self.out = QLabel(f"{value}{suffix}")
        self.out.setMinimumWidth(48)
        self._suffix = suffix
        self._step = step
        self.s.valueChanged.connect(self._on)
        h.addWidget(self.s, 1)
        h.addWidget(self.out)

    def _on(self, v: int) -> None:
        snapped = round(v / self._step) * self._step
        if snapped != v:
            self.s.setValue(snapped)
            return
        self.out.setText(f"{v}{self._suffix}")
        self.changed.emit(v)

    @property
    def value(self) -> int:
        return self.s.value()


def level_selector(map_name: str) -> Segmented | None:
    """Superior/Inferior para mapas de dos pisos (None si el mapa tiene uno solo)."""
    return Segmented(["Superior", "Inferior"], label="Nivel") if has_levels(map_name) else None


def kpi_row(items: list[tuple]) -> QWidget:
    """Fila de métricas. Cada item: (etiqueta, valor, ayuda) o (etiqueta, valor, ayuda, delta, menos_es_mejor).

    El delta va debajo con flecha y color (verde = mejor). Con menos_es_mejor=True (ms, grados) se invierte."""
    box = QWidget()
    h = QHBoxLayout(box)
    h.setContentsMargins(0, 0, 0, 0)
    h.setSpacing(10)
    for item in items:
        label, value, help_ = item[:3]
        delta = item[3] if len(item) > 3 else None
        inverse = item[4] if len(item) > 4 else False
        c = w.card(label, value)
        if delta:
            d = QLabel(delta)
            neutral = delta.startswith("≈")
            better = (delta.startswith("+") != inverse) if not neutral else None
            color = MUTED if better is None else ("#06d6a0" if better else "#ef476f")
            arrow = "" if neutral else ("▲ " if delta.startswith("+") else "▼ ")
            d.setText(arrow + delta)
            d.setStyleSheet(f"color:{color}; font-size:8.5pt; border:none;")
            c.layout().addWidget(d)
        if help_:
            c.setToolTip(help_)
        h.addWidget(c, 1)
    return box


def severity_card(title: str, tag: str, detail: str, color: str) -> QFrame:
    f = QFrame()
    f.setStyleSheet(f"QFrame#Sev {{ background:{SURFACE_2}; border:1px solid {BORDER}; border-left:4px solid {color};"
                    f"border-radius:6px; }}")
    f.setObjectName("Sev")
    v = QVBoxLayout(f)
    v.setContentsMargins(12, 8, 12, 8)
    top = QHBoxLayout()
    t = QLabel(title)
    t.setTextFormat(Qt.PlainText)
    t.setStyleSheet("font-weight:700; border:none;")
    g = QLabel(tag)
    g.setTextFormat(Qt.PlainText)
    g.setObjectName("Muted")
    g.setStyleSheet("border:none;")
    top.addWidget(t, 1)
    top.addWidget(g)
    v.addLayout(top)
    d = QLabel(detail)
    d.setTextFormat(Qt.PlainText)
    d.setWordWrap(True)
    d.setObjectName("Muted")
    d.setStyleSheet("border:none;")
    v.addWidget(d)
    return f
