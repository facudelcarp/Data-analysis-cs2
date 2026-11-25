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
    yield a
    # Al terminar: cerrar y destruir todas las ventanas que dejaron los tests mientras Qt sigue vivo. Si quedan
    # para el final del intérprete, Python las destruye en cualquier orden después de la QApplication y el
    # proceso se cae al salir (malloc_consolidate). La app real no tiene el problema: cierra su única ventana.
    import gc

    from cs2analysis.desktop import icons
    from cs2analysis.desktop.loader import wait_all
    wait_all()
    for widget in a.topLevelWidgets():
        widget.close()  # sin deleteLater: varias son de Python y borrarlas desde Qt las libera dos veces
    a.processEvents()
    icons.clear_cache()
    gc.collect()  # libera lo que ya no se usa mientras la QApplication sigue viva


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

    from cs2analysis.desktop.page import AsyncSlot, Slot, settle
    from cs2analysis.desktop.window import MainWindow
    win = MainWindow()
    win.show()
    win.add_paths([FIXTURE])
    assert win.loader.wait()
    for row in range(1, win.nav.count()):
        win.nav.setCurrentRow(row)
        view = win.stack.currentWidget()
        name = win.nav.item(row).text()
        settle(view, build_tabs=True)
        assert view.findChildren(Slot) or view.findChildren(AsyncSlot), name
        combos = [c for c in view.findChildren(QComboBox) if c.count() > 1][:3]
        for combo in combos:
            combo.setCurrentIndex(combo.count() - 1)
            for slot in view.findChildren(Slot):
                slot.refresh_now()
            settle(view, build_tabs=True)
    win.close()


def test_smoke_test_mode_passes(app):
    """El mismo recorrido que el CI le hace al .exe de Windows."""
    from cs2analysis.desktop.app import main
    assert main(["--smoke-test", str(FIXTURE)]) == 0


def test_async_slot_discards_stale_results(app):
    """Si se pide otro cálculo antes de que termine el anterior, solo se muestra el último."""
    from PySide6.QtWidgets import QLabel

    from cs2analysis.desktop.page import AsyncSlot
    calls = []

    def compute():
        calls.append(1)
        QtCore.QThread.msleep(80)
        return len(calls)

    main = QtCore.QThread.currentThread()
    built_in = []

    def render(n):
        built_in.append(QtCore.QThread.currentThread())
        return QLabel(f"resultado {n}")

    slot = AsyncSlot(lambda: compute, render)
    slot.refresh_now()  # pisa al primero mientras corre
    assert slot.wait()
    assert slot.content.text() == f"resultado {len(calls)}"
    assert built_in and all(t == main for t in built_in)  # los widgets se arman en el hilo de la ventana

    # destruir el panel con un cálculo en curso no puede tirar la app (el hilo sigue vivo hasta terminar)
    slot.refresh_now()
    slot.deleteLater()
    app.processEvents()
    from cs2analysis.desktop.loader import wait_all
    wait_all()
    app.processEvents()


def test_clicks_jump_to_the_replay(app):
    """Doble clic en una ronda, un kill o un duelo (o clic en una ruta) abre el replay en ese momento."""
    from cs2analysis.desktop.nav import goto_replay, goto_tick, open_demo
    from cs2analysis.desktop.replay_view import ReplayPanel
    from cs2analysis.desktop.window import MainWindow
    win = MainWindow()
    win.show()
    win.add_paths([FIXTURE])
    assert win.loader.wait()
    a, b = list(win.demos)
    win.nav.setCurrentRow(2)
    rnd = int(win.demos[b].rounds["round"].iloc[5])
    goto_replay(b, rnd, 12.0)
    assert win.stack.currentIndex() == 0 and win.single.picker.currentData() == b
    app.processEvents()  # la pestaña recién armada se muestra en la próxima vuelta del event loop
    panel = win.single.body.currentWidget().findChild(ReplayPanel)
    assert panel.isVisible() and panel.rr.round == rnd and abs(panel.canvas.t - 12.0) < 1e-6

    k = win.demos[a].kills.iloc[10]
    goto_tick(a, int(k["round"]), int(k["tick"]))  # 3 s antes del kill
    panel = win.single.body.currentWidget().findChild(ReplayPanel)
    assert panel.rr.round == k["round"] and abs(panel.canvas.t - (k["time_in_round"] - 3)) < 0.05

    # la tabla de ronda a ronda, reordenada: el doble clic va a la ronda de la fila que se ve
    page = win.single.body.currentWidget()
    page.tabs.setCurrentIndex(2)
    table = page.tabs.widget(2).findChildren(DataTable)[0]
    table.sortByColumn(0, QtCore.Qt.DescendingOrder)
    table.activated.emit(table.model().index(0, 0))
    assert page.tabs.currentIndex() == 1 and panel.rr.round == win.demos[a].rounds["round"].max()

    win.single.picker.setCurrentIndex(win.single.picker.findData(b))
    win.nav.setCurrentRow(1)
    open_demo(a)
    assert win.stack.currentIndex() == 0 and win.single.picker.currentData() == a
    win.close()


def test_dashboard_remembers_me(app):
    from PySide6.QtWidgets import QPushButton

    from cs2analysis import prefs
    from cs2analysis.desktop.page import Combo, settle
    from cs2analysis.desktop.window import MainWindow
    prefs.set_me(None)
    win = MainWindow()
    win.show()
    win.add_paths([FIXTURE])
    assert win.loader.wait()
    win.nav.setCurrentRow(3)
    view = win.stack.currentWidget()
    settle(view)
    focus = next(c for c in view.findChildren(Combo) if "foco" in c.findChild(QLabel).text())
    focus.box.setCurrentIndex(1)
    mark = next(b for b in view.findChildren(QPushButton) if b.text() == "Este soy yo")
    sid = focus.value
    mark.click()
    assert prefs.me() == sid
    settle(view)
    # la vista se rearmó: la anterior queda para borrar más tarde, así que el combo nuevo es el último
    focus = [c for c in view.findChildren(Combo) if "foco" in c.findChild(QLabel).text()][-1]
    assert focus.value == sid and focus.box.currentText().endswith("— yo")  # vuelve a abrir en "yo"
    texts = " ".join(lbl.text() for lbl in focus.parentWidget().parentWidget().findChildren(QLabel))
    assert "Fuerte y a trabajar" in texts
    prefs.set_me(None)
    win.close()


def test_death_review_playlist(app):
    from cs2analysis import deaths
    from cs2analysis.desktop.nav import start_review
    from cs2analysis.desktop.replay_view import ReplayPanel
    from cs2analysis.desktop.window import MainWindow
    win = MainWindow()
    win.show()
    win.add_paths([FIXTURE])
    assert win.loader.wait()
    d = next(iter(win.demos.values()))
    sid = d.kills["victim_steamid"].value_counts().index[0]
    x = deaths.player_deaths(d, sid)
    items = [(d.demo_id, int(r.round), max(0.0, r.time_in_round - 5), "x") for r in x.head(3).itertuples()]
    win.nav.setCurrentRow(3)
    start_review(items, "Muertes")
    app.processEvents()
    bar = win.single.review_bar
    assert win.stack.currentIndex() == 0 and bar.isVisible() and "1 de 3" in win.single.review_text.text()
    panel = win.single.body.currentWidget().findChild(ReplayPanel)
    assert panel.rr.round == items[0][1]
    win.single.review_next.click()
    assert "2 de 3" in win.single.review_text.text() and panel.rr.round == items[1][1]
    win.single.review_close.click()
    assert not bar.isVisible()
    win.close()


def test_label_dialog_saves(app):
    from cs2analysis import labels_store
    from cs2analysis.desktop.label_dialog import LabelDialog
    dlg = LabelDialog("demo-x", 7)
    dlg.boxes["t_kind"].setCurrentIndex(dlg.boxes["t_kind"].findData("Execute"))
    dlg.boxes["ct_stack"].setCurrentIndex(dlg.boxes["ct_stack"].findData("B"))
    dlg._save()
    assert labels_store.get("demo-x", 7) == {"t_kind": "Execute", "ct_stack": "B"}
    again = LabelDialog("demo-x", 7)
    assert again.values()["t_kind"] == "Execute"
    labels_store.put("demo-x", 7, {})
    dlg.close()
    again.close()
