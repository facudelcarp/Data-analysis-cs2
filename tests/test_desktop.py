"""App nativa (Qt) sin pantalla: carga real del fixture, vista de una demo y el modelo de tablas."""
import os
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
QtCore = pytest.importorskip("PySide6.QtCore", exc_type=ImportError)
pytest.importorskip("pyqtgraph")
from PySide6.QtWidgets import QApplication, QLabel  # noqa: E402

from cs2analysis.desktop.widgets import DataFrameModel, DataTable, card  # noqa: E402

FIXTURE = Path(__file__).parent / "fixtures" / "pro_sample.cs2a"
Qt = QtCore.Qt


@pytest.fixture(scope="module")
def app():
    from cs2analysis.desktop import style
    a = QApplication.instance() or QApplication([])
    style.apply(a)
    return a


def _cell(model, row, col):
    return model.data(model.index(row, col), Qt.DisplayRole)


def test_model_formats_and_sorts(app):
    df = pd.DataFrame({"name": ["b", "a", "c"], "adr": [54.3, np.nan, 84.0], "rating": [1.071, 0.9, 1.2],
                       "ok": [True, False, True]})
    m = DataFrameModel(df)
    assert [_cell(m, 0, c) for c in range(4)] == ["b", "54.3", "1.07", "Sí"]  # 1 decimal si alcanza
    assert _cell(m, 1, 1) == "—"
    m.sort(1, Qt.DescendingOrder)
    assert [_cell(m, r, 0) for r in range(3)] == ["c", "b", "a"]  # vacíos al final también al revés
    m.sort(0, Qt.AscendingOrder)
    assert m.frame["name"].tolist() == ["a", "b", "c"]


def test_table_fits_all_rows(app):
    t = DataTable(pd.DataFrame({"x": range(7)}), fit_rows=True)
    assert t.height() >= t.horizontalHeader().sizeHint().height() + 7 * 26


def test_names_from_the_demo_are_plain_text(app):
    c = card("Mejor", "<b>nick</b>", "")
    labels = [lbl for lbl in c.findChildren(QLabel) if lbl.text() == "<b>nick</b>"]
    assert labels and labels[0].textFormat() == Qt.PlainText


def test_window_loads_demos_and_caches_views(app):
    from cs2analysis.desktop.window import MainWindow
    win = MainWindow()
    win.show()
    win.add_paths([FIXTURE])
    assert win.loader.wait()
    view = win.single
    assert len(win.demos) == view.picker.count() == 2
    first = view.body.currentWidget()
    tables = first.findChildren(DataTable)
    n_players = len(win.demos[view.picker.currentData()].players)
    assert sum(t.model().rowCount() for t in tables[:2]) == n_players  # un scoreboard por equipo

    view.picker.setCurrentIndex(1)
    second = view.body.currentWidget()
    assert second is not first
    view.picker.setCurrentIndex(0)
    assert view.body.currentWidget() is first  # la vista armada se reutiliza

    win.add_paths([FIXTURE])  # repetida: no se vuelve a cargar
    assert not win.loader.busy and len(win.demos) == 2
    win.clear_session()
    assert view.picker.count() == 0 and not view._pages
    win.close()
