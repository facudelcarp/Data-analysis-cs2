"""Piezas reutilizables: tabla sobre un DataFrame, tarjetas, banner del partido y gráficos."""
from __future__ import annotations

from html import escape

import numpy as np
import pandas as pd
import pyqtgraph as pg
from PySide6.QtCore import QAbstractTableModel, QModelIndex, Qt
from PySide6.QtWidgets import (QAbstractItemView, QFrame, QHBoxLayout, QHeaderView, QLabel, QTableView,
                               QVBoxLayout, QWidget)

from ..palette import BORDER, MUTED, SERIES, SURFACE, TEAM_COLORS, TEXT

pg.setConfigOptions(antialias=True, background=SURFACE, foreground=MUTED)


class DataFrameModel(QAbstractTableModel):
    """Modelo de solo lectura sobre un DataFrame.

    Qt consulta cada celda muchas veces (un llamado por rol, y más al medir columnas), así que `data()` no toca
    pandas: el texto de cada columna se formatea una sola vez, la primera vez que se ve. La vista pide solo
    las celdas visibles, así que una tabla de millones de filas abre al instante.
    El orden se hace con numpy sobre la columna entera (no comparando celda a celda en Python)."""

    def __init__(self, df: pd.DataFrame, decimals: int = 2):
        super().__init__()
        self._df = df.reset_index(drop=True)
        self._decimals = decimals
        self._order = np.arange(len(self._df))
        self._headers = [str(c) for c in self._df.columns]
        self._numeric = [pd.api.types.is_numeric_dtype(self._df[c]) and not pd.api.types.is_bool_dtype(self._df[c])
                         for c in self._df.columns]
        self._align = [int((Qt.AlignRight if n else Qt.AlignLeft) | Qt.AlignVCenter) for n in self._numeric]
        self._text: list[list[str] | None] = [None] * len(self._headers)
        self._col_decimals = [self._decimals_for(self._df[c]) for c in self._df.columns]

    def _decimals_for(self, s: pd.Series) -> int:
        """Los decimales que la columna necesita, hasta `decimals`: ADR 54.3 y no 54.30, rating 1.07."""
        if not pd.api.types.is_float_dtype(s):
            return self._decimals
        v = s.dropna().to_numpy(dtype=float)[:5000]
        for k in range(self._decimals):
            if np.allclose(v, np.round(v, k)):
                return k
        return self._decimals

    @property
    def frame(self) -> pd.DataFrame:
        """El DataFrame en el orden en que se ve."""
        return self._df.iloc[self._order]

    def rowCount(self, parent=QModelIndex()) -> int:  # noqa: N802 (API de Qt)
        return 0 if parent.isValid() else len(self._df)

    def columnCount(self, parent=QModelIndex()) -> int:  # noqa: N802
        return 0 if parent.isValid() else len(self._headers)

    def data(self, index, role=Qt.DisplayRole):
        if role == Qt.DisplayRole:
            col = index.column()
            text = self._text[col]
            if text is None:
                dec = self._col_decimals[col]
                text = self._text[col] = [self._fmt(v, dec) for v in self._df.iloc[:, col].to_numpy(dtype=object)]
            return text[self._order[index.row()]]
        if role == Qt.TextAlignmentRole:
            return self._align[index.column()]
        return None

    @staticmethod
    def _fmt(value, decimals: int) -> str:
        if value is None or value is pd.NA or (isinstance(value, float) and np.isnan(value)):
            return "—"
        if isinstance(value, (bool, np.bool_)):
            return "Sí" if value else "No"
        if isinstance(value, (float, np.floating)):
            return f"{value:.{decimals}f}"
        return str(value)

    def headerData(self, section, orientation, role=Qt.DisplayRole):  # noqa: N802
        if orientation != Qt.Horizontal:
            return None
        if role == Qt.DisplayRole:
            return self._headers[section]
        if role == Qt.TextAlignmentRole:  # el encabezado se alinea como sus datos (números a la derecha)
            return self._align[section]
        return None

    def sort(self, column: int, order=Qt.AscendingOrder) -> None:
        if column < 0:  # Qt pide sort(-1) al habilitar el orden sin columna elegida: se deja el orden original
            return
        self.layoutAboutToBeChanged.emit()
        s = self._df.iloc[:, column]
        keys = s.to_numpy(dtype=float, na_value=np.nan) if self._numeric[column] else s.astype(str).str.lower().to_numpy()
        idx = np.argsort(keys, kind="stable")
        if order == Qt.DescendingOrder:
            # descendente con los vacíos al final, igual que en ascendente
            if self._numeric[column]:
                nan = np.isnan(keys[idx])
                idx = np.concatenate([idx[~nan][::-1], idx[nan]])
            else:
                idx = idx[::-1]
        self._order = idx
        self.layoutChanged.emit()


class DataTable(QTableView):
    """Tabla ordenable por cualquier columna. Con fit_rows=True crece para mostrar todas las filas
    (para tablas cortas dentro de una página con scroll)."""

    def __init__(self, df: pd.DataFrame, fit_rows: bool = False, decimals: int = 2, parent=None):
        super().__init__(parent)
        self.setModel(DataFrameModel(df, decimals))
        # Sin indicador previo: al habilitar el orden, Qt ordena enseguida por la columna 0 (descendente) y se
        # pierde el orden que trae la tabla (p. ej. scoreboard por rating). Se ordena recién al hacer clic.
        self.horizontalHeader().setSortIndicator(-1, Qt.AscendingOrder)
        self.setSortingEnabled(True)
        self.setAlternatingRowColors(True)
        self.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.verticalHeader().setVisible(False)
        self.verticalHeader().setDefaultSectionSize(26)
        self.setShowGrid(False)
        hh = self.horizontalHeader()
        # Ancho de columnas medido una sola vez (con una muestra de filas). En modo ResizeToContents Qt vuelve a
        # medir todas las celdas en cada relayout: eran ~40.000 consultas para una tabla de 10 filas.
        hh.setResizeContentsPrecision(300)
        self.resizeColumnsToContents()
        hh.setSectionResizeMode(QHeaderView.Interactive)
        hh.setStretchLastSection(self.model().columnCount() <= 8)  # en tablas anchas la última no se estira
        self.setContextMenuPolicy(Qt.CustomContextMenu)
        self.customContextMenuRequested.connect(self._menu)
        if fit_rows:
            self.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
            rows = self.model().rowCount()
            # se suma la barra horizontal: con muchas columnas aparece y taparía la última fila
            self.setFixedHeight(hh.sizeHint().height() + 26 * rows + 2 * self.frameWidth() + 2
                                + self.horizontalScrollBar().sizeHint().height())


    def _menu(self, pos) -> None:
        from PySide6.QtWidgets import QMenu
        m = QMenu(self)
        m.addAction("Copiar tabla", self.copy_all)
        m.addAction("Exportar CSV…", lambda: self.export("csv"))
        m.addAction("Exportar Parquet…", lambda: self.export("parquet"))
        m.exec(self.viewport().mapToGlobal(pos))

    def copy_all(self) -> None:
        from PySide6.QtWidgets import QApplication
        QApplication.clipboard().setText(self.model().frame.to_csv(index=False, sep="\t"))

    def export(self, fmt: str) -> None:
        from PySide6.QtWidgets import QFileDialog, QMessageBox
        path, _ = QFileDialog.getSaveFileName(self, "Exportar tabla", f"tabla.{fmt}",
                                              "CSV (*.csv)" if fmt == "csv" else "Parquet (*.parquet)")
        if not path:
            return
        df = self.model().frame
        try:
            df.to_csv(path, index=False) if fmt == "csv" else df.to_parquet(path, index=False)
        except Exception as exc:  # disco lleno, permisos…
            QMessageBox.warning(self, "No se pudo exportar", str(exc))


_EMOJI = __import__("re").compile("[\U0001F000-\U0001FAFF\u2600-\u27BF\u2B00-\u2BFF\u23E9-\u23FA\uFE0F]+\\s*")


def plain(text: str) -> str:
    """Saca los emojis de un título: cambian según el sistema y no respetan el color del tema (ver icons.py)."""
    return _EMOJI.sub("", str(text)).strip()


def label(text: str, name: str | None = None, wrap: bool = False) -> QLabel:
    w = QLabel(text)
    if name:
        w.setObjectName(name)
    w.setWordWrap(wrap)
    w.setTextInteractionFlags(Qt.TextSelectableByMouse)
    return w


def card(title: str, value: str, detail: str = "") -> QFrame:
    """Tarjeta de métrica. Los textos van como texto plano: un nick nunca se interpreta como HTML."""
    f = QFrame()
    f.setObjectName("Card")
    lay = QVBoxLayout(f)
    lay.setContentsMargins(14, 10, 14, 10)
    lay.setSpacing(2)
    for text, name in ((plain(title).upper(), "CardLabel"), (value, "CardValue"), (detail, "Muted")):
        if text:
            w = label(text, name, wrap=True)
            w.setTextFormat(Qt.PlainText)
            lay.addWidget(w)
    return f


def card_row(items: list[tuple[str, str, str]]) -> QWidget:
    w = QWidget()
    lay = QHBoxLayout(w)
    lay.setContentsMargins(0, 0, 0, 0)
    lay.setSpacing(10)
    for item in items:
        lay.addWidget(card(*item), 1)
    return w


def match_banner(meta: dict, map_label: str) -> QFrame:
    """Marcador: equipos con su color, resultado grande y datos de la partida."""
    a, b = int(meta["score_a"]), int(meta["score_b"])
    start_a = meta.get("start_side_a", "?")
    start_b = "T" if start_a == "CT" else "CT"
    f = QFrame()
    f.setObjectName("Banner")
    outer = QVBoxLayout(f)
    outer.setContentsMargins(18, 12, 18, 12)
    row = QHBoxLayout()

    def team(name: str, color: str, start: str, won: bool, align) -> QWidget:
        box = QWidget()
        v = QVBoxLayout(box)
        v.setContentsMargins(0, 0, 0, 0)
        n = QLabel(str(name))
        n.setTextFormat(Qt.PlainText)
        n.setStyleSheet(f"color:{color}; font-size:15pt; font-weight:800;")
        sub = QLabel(f"empezó de {start}" + ("   ·   GANADOR" if won else ""))
        sub.setObjectName("Muted")
        for w in (n, sub):
            w.setAlignment(align)
            v.addWidget(w)
        return box

    row.addWidget(team(meta["team_a"], TEAM_COLORS["A"], start_a, a > b, Qt.AlignLeft), 1)
    score = QLabel(f"<span style='color:{TEXT if a >= b else MUTED}'>{a}</span>"
                   f"<span style='color:{MUTED}'> : </span>"
                   f"<span style='color:{TEXT if b >= a else MUTED}'>{b}</span>")
    score.setObjectName("Score")
    score.setAlignment(Qt.AlignCenter)
    row.addWidget(score)
    row.addWidget(team(meta["team_b"], TEAM_COLORS["B"], start_b, b > a, Qt.AlignRight), 1)
    outer.addLayout(row)
    chips = QHBoxLayout()
    chips.addStretch()
    for k, v in (("Mapa", map_label), ("Rondas", meta.get("rounds")), ("Duración", f"{meta.get('duration_min')} min")):
        c = QLabel(f"{k}  <b style='color:{TEXT}'>{escape(str(v))}</b>")  # el mapa viene de la demo
        c.setObjectName("Chip")
        chips.addWidget(c)
    chips.addStretch()
    outer.addLayout(chips)
    return f


def ranking_bars(df: pd.DataFrame, value: str, label_col: str, color_col: str | None = None,
                 colors: dict | None = None, fmt: str = "{:.2f}", ref: float | None = None, ref_label: str = "",
                 title: str = "") -> pg.PlotWidget:
    """Barras horizontales ordenadas (lo mejor arriba), con el valor escrito y una línea de referencia."""
    d = df.dropna(subset=[value]).sort_values(value)
    vals = d[value].to_numpy(dtype=float)
    ys = np.arange(len(d))
    brushes = [pg.mkBrush(colors.get(c, SERIES[0])) for c in d[color_col]] if color_col and colors \
        else [pg.mkBrush(SERIES[0])] * len(d)
    w = pg.PlotWidget(title=f"<span style='color:{TEXT};font-size:11pt'>{title}</span>" if title else None)
    w.setMenuEnabled(False)
    w.setMouseEnabled(x=False, y=False)
    w.hideButtons()
    w.getPlotItem().getViewBox().setBorder(pg.mkPen(BORDER))
    w.addItem(pg.BarGraphItem(x0=0, y=ys, height=0.7, width=vals, brushes=brushes, pen=pg.mkPen(None)))
    top = float(vals.max()) if len(vals) else 1.0
    for y, v in zip(ys, vals, strict=True):
        t = pg.TextItem(fmt.format(v), color="#ffffff", anchor=(1.05, 0.5))
        t.setPos(v, y)
        w.addItem(t)
    if ref is not None and np.isfinite(ref):
        w.addItem(pg.InfiniteLine(pos=ref, angle=90, pen=pg.mkPen(MUTED, style=Qt.DotLine)))
        if ref_label:
            t = pg.TextItem(ref_label, color=MUTED, anchor=(0.5, 0.5))
            t.setPos(ref, len(d) - 0.05)  # en la fila libre de arriba
            w.addItem(t)
    left = w.getAxis("left")
    left.setTicks([[(int(y), str(n)) for y, n in zip(ys, d[label_col], strict=True)]])
    left.setTextPen(pg.mkPen(TEXT))
    w.hideAxis("bottom")
    w.setXRange(0, top * 1.08, padding=0)
    w.setYRange(-0.6, len(d) + (0.5 if ref_label else -0.4), padding=0)  # fila libre arriba para la etiqueta
    w.setFixedHeight(70 + 24 * len(d))
    return w


def team_legend(names: dict[str, str]) -> QLabel:
    w = QLabel(" · ".join(f"<span style='color:{TEAM_COLORS[t]}'>■</span> {escape(str(names[t]))}" for t in ("A", "B")))
    w.setObjectName("Muted")
    return w


def hline() -> QFrame:
    f = QFrame()
    f.setFrameShape(QFrame.HLine)
    f.setStyleSheet(f"color:{BORDER}")
    return f
