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


def test_table_keeps_the_given_order_until_clicked(app):
    """Habilitar el orden no puede reordenar la tabla (el scoreboard viene ordenado por rating)."""
    t = DataTable(pd.DataFrame({"name": ["b", "c", "a"], "rating": [1.5, 1.2, 0.9]}))
    assert t.model().frame["name"].tolist() == ["b", "c", "a"]
    t.sortByColumn(0, Qt.AscendingOrder)
    assert t.model().frame["name"].tolist() == ["a", "b", "c"]


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


def test_every_single_demo_tab_builds(app):
    """Smoke test: todas las pestañas de Demo individual, en las dos demos del fixture, y sus filtros."""
    from cs2analysis.desktop.page import Segmented, Slot
    from cs2analysis.desktop.single_view import SingleDemoView
    from cs2analysis.storage import read_cs2a
    view = SingleDemoView()
    view.set_demos({d.demo_id: d for d in read_cs2a(FIXTURE)})
    for i in range(view.picker.count()):
        view.picker.setCurrentIndex(i)
        page = view.body.currentWidget()
        page.tabs.build_all()
        if i:
            continue
        # cada filtro de tipo botón (en una demo): probar cada opción y redibujar
        for seg in page.findChildren(Segmented):
            for opt, b in seg.buttons.items():
                b.setChecked(True)
                for slot in page.findChildren(Slot):
                    slot.refresh_now()
    view.close()


def test_replay_plays_and_seeks(app):
    from cs2analysis.desktop.replay_view import ReplayPanel
    from cs2analysis.storage import read_cs2a
    d = read_cs2a(FIXTURE)[0]
    rp = ReplayPanel(d)
    rp.resize(1300, 900)
    rp.show()
    for i in range(rp.round_box.box.count()):
        rp.round_box.box.setCurrentIndex(i)
        rp.seek((rp.rr.t_min + rp.rr.t_max) / 2)
        rp.canvas.repaint()
    rp.play()
    assert rp.playing
    t0 = rp.canvas.t
    QtCore.QThread.msleep(50)
    rp._tick()
    assert rp.canvas.t > t0
    rp.seek(1e9)
    assert rp.canvas.t == rp.rr.t_max
    rp._step_round(-1)
    assert not rp.playing  # cambiar de ronda pausa
    rp.close()


def test_every_library_view_builds(app):
    """Equipos, Multi-demo, Dashboard y Datos crudos: cada pestaña, y un cambio en cada selector principal."""
    from PySide6.QtWidgets import QComboBox

    from cs2analysis.desktop.page import LazyTabs, Slot
    from cs2analysis.desktop.window import MainWindow
    win = MainWindow()
    win.show()
    win.add_paths([FIXTURE])
    assert win.loader.wait()
    for row in range(1, win.nav.count()):
        win.nav.setCurrentRow(row)
        view = win.stack.currentWidget()
        name = win.nav.item(row).text()
        assert view.findChildren(Slot), name
        for lt in view.findChildren(LazyTabs):
            lt.build_all()
        combos = [c for c in view.findChildren(QComboBox) if c.count() > 1][:3]
        for combo in combos:
            combo.setCurrentIndex(combo.count() - 1)
            for slot in view.findChildren(Slot):
                slot.refresh_now()
            app.processEvents()
    win.close()
