"""Vistas sobre la biblioteca completa: Multi-demo y Dashboard."""
from __future__ import annotations

import threading

import pandas as pd
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QListWidget, QListWidgetItem, QSpinBox, QVBoxLayout, QWidget

from .. import stats, tactics
from ..labels import RATING_NOTE, stat_table
from ..maps import pretty_map
from ..multi import Library
from ..palette import SERIES
from ..parser import DemoData
from ..translate import weapon_name
from . import charts, micro_tab, routes_tab, tactics_tab
from . import widgets as w
from .nav import open_demo
from .page import empty_state
from .page import AsyncSlot, Combo, LazyTabs, Page, Segmented, Slot, kpi_row, scrollable


_SHARED: dict = {"key": None, "lib": None}
_SHARED_LOCK = threading.Lock()


def shared_library(demos: dict[str, DemoData]) -> Library:
    """Una sola Library para todas las vistas. Armarla calcula las estadísticas de todas las demos (81 partidas:
    ~7 s la primera vez), así que se arma una vez, en segundo plano, y con candado para que dos vistas no la armen
    a la vez."""
    key = tuple(sorted(demos))
    with _SHARED_LOCK:
        if _SHARED["key"] != key:
            _SHARED["lib"] = Library(list(demos.values()))
            _SHARED["key"] = key
        return _SHARED["lib"]


class LibraryView(QWidget):
    """Vista que depende de todas las demos cargadas. Se rearma solo si está visible y algo cambió."""
    title = ""
    subtitle = ""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.demos: dict[str, DemoData] = {}
        self._dirty = True
        self._lib: Library | None = None
        lay = QVBoxLayout(self)
        lay.setContentsMargins(24, 16, 24, 0)
        lay.setSpacing(4)
        lay.addWidget(w.label(self.title, "PageTitle"))
        lay.addWidget(w.label(self.subtitle, "PageSubtitle", wrap=True))
        self.holder = QVBoxLayout()
        lay.addLayout(self.holder, 1)

    def set_demos(self, demos: dict[str, DemoData]) -> None:
        self.demos = demos
        self._lib = None
        self._dirty = True
        if self.isVisible():
            self.rebuild()

    @property
    def lib(self) -> Library:
        if self._lib is None:
            self._lib = shared_library(self.demos)
        return self._lib

    def showEvent(self, e):  # noqa: N802 (API de Qt)
        if self._dirty:
            self.rebuild()
        super().showEvent(e)

    def rebuild(self) -> None:
        self._dirty = False
        while self.holder.count():
            item = self.holder.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        if not self.demos:
            self.holder.addWidget(empty_state(self), 1)
            return
        demos = dict(self.demos)

        def job():
            return lambda: shared_library(demos)  # lo pesado: en otro hilo

        def render(lib) -> QWidget:
            self._lib = lib
            return scrollable(self.build())

        self.holder.addWidget(AsyncSlot(job, render), 1)

    def build(self) -> QWidget:  # pragma: no cover - lo implementa cada vista
        raise NotImplementedError


class MultiPick(QWidget):
    """Lista con casillas, con un máximo de elegidos."""
    changed = Signal()

    def __init__(self, items: list[tuple[str, str]], checked: list[str], max_checked: int = 4, parent=None):
        super().__init__(parent)
        self.max = max_checked
        self.list = QListWidget()
        self.list.setFixedHeight(150)
        for v, t in items:
            it = QListWidgetItem(str(t))
            it.setData(Qt.UserRole, v)
            it.setFlags(it.flags() | Qt.ItemIsUserCheckable)
            it.setCheckState(Qt.Checked if v in checked else Qt.Unchecked)
            self.list.addItem(it)
        self.list.itemChanged.connect(self._on)
        QVBoxLayout(self).addWidget(self.list)
        self.layout().setContentsMargins(0, 0, 0, 0)

    def _on(self, item: QListWidgetItem) -> None:
        if item.checkState() == Qt.Checked and len(self.values) > self.max:
            self.list.blockSignals(True)
            item.setCheckState(Qt.Unchecked)
            self.list.blockSignals(False)
            return
        self.changed.emit()

    @property
    def values(self) -> list[str]:
        return [self.list.item(i).data(Qt.UserRole) for i in range(self.list.count())
                if self.list.item(i).checkState() == Qt.Checked]


# --------------------------------------------------------------------------------------------
# Multi-demo
# --------------------------------------------------------------------------------------------

LB_COLS = ["name", "demos", "rounds", "kills", "deaths", "kd", "adr", "hs_pct", "kast_pct", "opening_success_pct",
           "opening_kills", "trade_kills", "clutches_won", "clutches", "k3", "k4", "k5", "utility_adr",
           "enemies_flashed", "accuracy_pct", "rating1", "rating2", "ttd_ms", "reaction_ms", "crosshair_deg",
           "preaim_pct", "counter_strafe_pct", "first_bullet_acc_pct"]
COMPARE_PANEL = [
    ("rating2", "Rating", "{:.2f}", False), ("adr", "Daño por ronda (ADR)", "{:.0f}", False),
    ("kast_pct", "KAST", "{:.0f}%", False), ("hs_pct", "Headshots", "{:.0f}%", False),
    ("opening_success_pct", "Aperturas ganadas", "{:.0f}%", False), ("utility_adr", "Daño de utilidad", "{:.1f}", False),
    ("crosshair_deg", "Mira al ver al rival", "{:.1f}°", True), ("reaction_ms", "Reacción", "{:.0f} ms", True),
    ("preaim_pct", "Pre-aim", "{:.0f}%", False),
]
COMPARE_METRICS = {"rating2": "Rating 2.0*", "adr": "ADR", "kast_pct": "KAST %", "hs_pct": "HS %",
                   "kd": "K/D", "opening_success_pct": "Entry %", "utility_adr": "ADR utilidad",
                   "accuracy_pct": "Precisión %", "ttd_ms": "TTD (ms)", "crosshair_deg": "Crosshair (°)",
                   "preaim_pct": "Pre-aim %", "counter_strafe_pct": "Counter-strafe %"}
TREND_REF = {"rating2": 1.0, "kd": 1.0, "kast_pct": 70, "hs_pct": 50, "opening_success_pct": 50}


class MultiDemoView(LibraryView):
    title = "Multi-demo"
    subtitle = "Todas las partidas juntas: quién rinde mejor, cómo evoluciona cada uno y en qué mapas."

    def build(self) -> QWidget:
        lib_all = self.lib
        p = Page()
        maps = sorted(lib_all.matches()["Mapa"].unique())
        self.maps = Segmented([pretty_map(m) for m in maps], label="Mapas", multi=True,
                              values=[pretty_map(m) for m in maps])
        self._map_codes = dict(zip([pretty_map(m) for m in maps], maps, strict=True))
        self.min_rounds = QSpinBox()
        self.min_rounds.setRange(0, 10_000)
        self.min_rounds.setSingleStep(10)
        self.min_rounds.setPrefix("Mínimo de rondas por jugador: ")
        p.row(self.maps, self.min_rounds, stretches=[3, 1])
        body = p.add(AsyncSlot(self._job, self._body))
        self.maps.changed.connect(body.refresh)
        self.min_rounds.valueChanged.connect(body.refresh)
        p.stretch()
        return p

    def _filtered(self) -> Library:
        sel = [self._map_codes[m] for m in self.maps.values]
        matches = self.lib.matches()
        ids = matches.loc[matches["Mapa"].isin(sel), "demo_id"].tolist()
        return self.lib if len(ids) == len(self.lib) else Library([self.lib.by_id[i] for i in ids])

    def _job(self):
        """Lee los filtros acá (hilo de la ventana) y devuelve el cálculo pesado para otro hilo."""
        lib = self._filtered()
        min_rounds = self.min_rounds.value()

        def compute():
            if len(lib) == 0:
                return lib, None, None, None
            return lib, lib.leaderboard(min_rounds=min_rounds), lib.matches(), lib.micro()
        return compute

    def _body(self, result) -> QWidget:
        lib, lb, matches, _micro = result
        p = Page(margins=(0, 0, 0, 0))
        if len(lib) == 0:
            p.info("Ningún mapa seleccionado.", "warn")
            return p
        p.section(f"Partidas ({len(lib)})")
        ids = matches["demo_id"].to_numpy()
        p.add(w.DataTable(matches.drop(columns=["demo_id"]).assign(Mapa=lambda x: x["Mapa"].map(pretty_map)),
                          decimals=1, on_activate=lambda i: open_demo(ids[i]), hint="abrir la partida")
              ).setMinimumHeight(min(80 + 26 * len(lib), 320))
        p.caption("Doble clic en una partida para abrirla en Demo individual.")
        self._highlights(p, lb, _micro)
        if lb.empty:
            p.info("Ningún jugador llega al mínimo de rondas.")
            return p
        tabs = LazyTabs()
        tabs.setMinimumHeight(1100)
        tabs.add_lazy(lambda: self._leaderboard(lib, lb), "🏆 Leaderboard")
        tabs.add_lazy(lambda: self._compare(lib, lb), "⚖️ Comparar jugadores")
        if len(lib.duels):
            tabs.add_lazy(lambda: self._aim(lib, lb), "🎯 Aim / micro-game")
        tabs.add_lazy(lambda: self._maps(lib, lb), "🗺️ Mapas")
        tabs.add_lazy(lambda: routes_tab.build(lib), "Rutas de un jugador")
        tabs.add_lazy(lambda: self._tactics(lib), "🧠 Tácticas por equipo")
        p.add(tabs, 1)
        return p

    def _leaderboard(self, lib: Library, lb: pd.DataFrame) -> QWidget:
        p = Page()
        top = lb.sort_values("rating2", ascending=False).head(15).copy()
        top["label"] = (top["name"] + " (" + top["demos"].astype(int).astype(str) + " p · "
                        + top["rounds"].astype(int).astype(str) + " r)")
        p.add(charts.ranking_bars(top, "rating2", "label", ref=1.0, ref_label="1.00 = promedio",
                                  title="¿Quién rindió mejor en el total de partidas?"))
        p.note("rating de cada jugador sumando todas sus rondas (top 15); entre paréntesis, partidas (p) y "
               "rondas (r) jugadas. Más de 1.00 es bueno y menos de 0.85, flojo. Con pocas rondas el número es "
               "menos confiable: subí el mínimo de rondas de arriba para filtrar. La tabla tiene a todos.")
        p.add(w.DataTable(stat_table(lb, LB_COLS))).setMinimumHeight(360)
        p.caption("Las métricas se recalculan sobre el total de rondas (no es un promedio de promedios). "
                  + RATING_NOTE + " Clic derecho en cualquier tabla = copiar o exportar a CSV/Parquet.")
        p.stretch()
        return p

    def _compare(self, lib: Library, lb: pd.DataFrame) -> QWidget:
        p = Page()
        names = dict(zip(lb["steamid"], lb["name"], strict=True))
        pick = MultiPick(list(names.items()), list(lb.sort_values("rating2", ascending=False)["steamid"].head(2)))
        metric = Combo("Métrica de la evolución", list(COMPARE_METRICS.items()))
        p.row(pick, metric, stretches=[2, 1])

        def compare() -> QWidget:
            out = Page(margins=(0, 0, 0, 0))
            chosen = pick.values
            if not chosen:
                out.caption("Elegí hasta 4 jugadores en la lista.")
                return out
            sub = lb[lb["steamid"].isin(chosen)].set_index("steamid").loc[chosen].reset_index()
            out.add(charts.compare_players(sub, COMPARE_PANEL))
            out.note("un mini gráfico por métrica, calculada sobre todas las rondas de cada jugador. La barra azul "
                     "con ★ es el mejor en esa métrica. En las métricas en ms y grados, menos es mejor.")
            m = metric.value
            series, labels = [], None
            per_all = {s: lib.per_demo(s) for s in chosen}
            order = sorted({x for pdm in per_all.values() if not pdm.empty for x in pdm["Partida"]})
            for i, s in enumerate(chosen):
                pdm = per_all[s]
                if pdm.empty or m not in pdm:
                    continue
                y = pdm.set_index("Partida")[m].reindex(order).to_numpy(dtype=float)
                series.append((names[s], y, SERIES[i]))
                labels = order
            if series:
                ch = charts.line_by_category(labels, series, f"¿Cómo evoluciona el {COMPARE_METRICS[m]} partida a partida?")
                if m in TREND_REF:
                    charts.hline(ch, TREND_REF[m])
                out.add(ch)
                out.note("cada punto es una partida, en orden cronológico. Sirve para ver si un jugador está mejorando, "
                         "empeorando o se mantiene estable.")
            return out

        cs = p.add(Slot(compare))
        pick.changed.connect(cs.refresh)
        metric.changed.connect(cs.refresh)
        p.stretch()
        return p

    def _aim(self, lib: Library, lb: pd.DataFrame) -> QWidget:
        all_names = dict(zip(lb["steamid"], lb["name"], strict=True))
        for d in lib.demos:  # completar con jugadores que no llegaron al leaderboard
            for sid, nm in zip(d.players["steamid"], d.players["name"], strict=True):
                all_names.setdefault(sid, nm)
        return micro_tab.build(lib.duels, lib.shots, all_names, "malla")

    def _maps(self, lib: Library, lb: pd.DataFrame) -> QWidget:
        p = Page()
        names = dict(zip(lb["steamid"], lb["name"], strict=True))
        focus = Combo("Perspectiva", [("", "General (todas las partidas)"), *names.items()])
        p.add(focus)

        def maps_block() -> QWidget:
            out = Page(margins=(0, 0, 0, 0))
            f = focus.value or None
            ms = lib.map_summary(f)
            if ms.empty:
                out.caption("Sin partidas de este jugador.")
                return out
            ms["Mapa"] = ms["Mapa"].map(pretty_map)
            ycol = "Winrate %" if f else "Partidas"
            texts = [f"{v:.0f}% ({n} p)" if f else f"{v:.0f}" for v, n in zip(ms[ycol], ms["Partidas"], strict=True)]
            out.row(w.DataTable(ms, fit_rows=True, decimals=1),
                    charts.vbars(ms["Mapa"].tolist(), ms[ycol], SERIES[0], texts,
                                 title="¿En qué mapas gana más?" if f else "¿En qué mapas se juega más?"))
            out.note("cada barra es el winrate del jugador en ese mapa. Los mapas con una sola partida no son "
                     "representativos: necesitás al menos 5-10 para ver una tendencia." if f else
                     "cada barra es la cantidad de partidas jugadas en ese mapa. Los mapas más jugados son los que "
                     "más datos aportan al leaderboard.")
            return out

        mb = p.add(Slot(maps_block))
        focus.changed.connect(mb.refresh)
        p.stretch()
        return p

    def _tactics(self, lib: Library) -> QWidget:
        p = Page()
        present = sorted({d.meta["map"] for d in lib.demos})
        tmap = Combo("Mapa", [(m, pretty_map(m)) for m in present])
        p.add(tmap)

        def tactics_block() -> QWidget:
            out = Page(margins=(0, 0, 0, 0))
            same = [d for d in lib.demos if d.meta["map"] == tmap.value]
            rt, gr, refs = tactics.library_tactics(same)
            out.caption(f"{len(same)} demo(s) en {pretty_map(tmap.value)}. Los equipos se identifican por nombre: en "
                        "matchmaking todos se llaman 'Equipo A/B', así que mezcla partidas distintas.")
            tactics_tab.site_block(out, rt, {}, team_col="t_team_name")
            tactics_tab.lineups_block(out, gr, refs, tmap.value, "team_name", {})
            return out

        tb = p.add(Slot(tactics_block))
        tmap.changed.connect(tb.refresh)
        p.stretch()
        return p

    @staticmethod
    def _highlights(p: Page, lb: pd.DataFrame, mi: pd.DataFrame) -> None:
        if lb.empty:
            return

        def best(col, asc=False):
            x = lb.dropna(subset=[col])
            return x.sort_values(col, ascending=asc).iloc[0] if len(x) else None

        items = []
        if (r := best("rating2")) is not None:
            items.append(("⭐ Mejor rating", r["name"], f"rating {r['rating2']:.2f} · {int(r['rounds'])} rondas"))
        if (r := best("adr")) is not None:
            items.append(("💥 Más daño", r["name"], f"{r['adr']:.0f} ADR · {int(r['rounds'])} rondas"))
        if (r := best("opening_kills")) is not None and r["opening_kills"] > 0:
            items.append(("🚪 Más aperturas", r["name"], f"{int(r['opening_kills'])} primeras kills"))
        if (r := best("clutches_won")) is not None and r["clutches_won"] > 0:
            items.append(("🧊 Clutches", r["name"], f"{int(r['clutches_won'])} ganados de {int(r['clutches'])}"))
        if mi is not None and len(mi):
            mi = mi[mi["duels_won"].fillna(0) >= 5].dropna(subset=["crosshair_deg"])
            if len(mi):
                r = mi.sort_values("crosshair_deg").iloc[0]
                items.append(("🎯 Mejor mira", lb.set_index("steamid")["name"].get(r["steamid"], "?"),
                              f"{r['crosshair_deg']:.1f}° del rival al verlo"))
        if items:
            p.add(w.card_row(items))


# --------------------------------------------------------------------------------------------
# Dashboard
# --------------------------------------------------------------------------------------------

MIN_ROUNDS_BASELINE = 30
REASON_SHORT = {
    "T eliminaron a los CT": "T eliminaron a los CT", "CT eliminaron a los T": "CT eliminaron a los T",
    "Bomba detonada": "Bomba detonada", "Bomba desactivada": "Bomba desactivada",
    "Se agotó el tiempo": "Se agotó el tiempo", "Rendición de los T": "Rendición de los T",
    "Rendición de los CT": "Rendición de los CT",
}


def qualified(lib: Library) -> tuple[pd.DataFrame, str]:
    """Jugadores con muestra suficiente para compararse.

    El mínimo es la mitad de las rondas del jugador típico de la biblioteca (tope 30): con un umbral fijo,
    en una biblioteca de pocas partidas solo pasarían los de la partida más larga."""
    rounds = lib.players()["rounds"]
    threshold = int(min(MIN_ROUNDS_BASELINE, 0.5 * rounds.median())) if len(rounds) else 0
    return lib.leaderboard(min_rounds=threshold), f"jugadores con al menos {threshold} rondas"


def delta(value, base, digits: int = 1, unit: str = "") -> str | None:
    if value is None or base is None or pd.isna(value) or pd.isna(base):
        return None
    d = value - base
    if round(d, digits) == 0:
        return "≈ igual a la mediana"
    return f"{d:+.{digits}f}{unit} vs mediana"


class DashboardView(LibraryView):
    title = "Dashboard"
    subtitle = "El resumen de un jugador comparado con el resto, o de toda la biblioteca."

    def build(self) -> QWidget:
        lib = self.lib
        players = lib.players()
        names = dict(zip(players["steamid"], players["name"] + " (" + players["demos"].astype(str) + " demos)",
                         strict=True))
        p = Page()
        focus = Combo("Jugador foco", [("", "— Biblioteca completa —"),
                                       *sorted(names.items(), key=lambda x: x[1].lower())], min_width=320)
        p.add(focus)
        def job():
            sid = focus.value  # widget: se lee en el hilo de la ventana

            def warm():
                # Llena la caché de la biblioteca con todo lo que el tablero va a pedir; después armarlo es leer
                qualified(lib)
                lib.matches()
                lib.concat("kills")
                lib.concat("rounds")
                if sid:
                    lib.per_demo(sid)
                    lib.micro(sid)
                    lib.map_summary(sid)
                return sid
            return warm

        body = p.add(AsyncSlot(job, lambda sid: self._player(lib, sid, names[sid].rsplit(" (", 1)[0]) if sid
                                else self._library(lib)))
        focus.changed.connect(body.refresh)
        p.stretch()
        return p

    def _library(self, lib: Library) -> QWidget:
        p = Page(margins=(0, 0, 0, 0))
        m = lib.matches()
        pr = lib.player_rounds
        k = lib.concat("kills")
        ek = k[k["is_enemy_kill"]] if len(k) else k
        r = lib.concat("rounds")
        p.add(kpi_row([
            ("Partidas", f"{len(m)}", None),
            ("Rondas", f"{int(m['Rondas'].sum()):,}", None),
            ("Jugadores", f"{pr['steamid'].nunique()}", "Jugadores distintos en todas las demos"),
            ("Kills", f"{len(ek):,}", None),
            ("Headshots", f"{100 * ek['headshot'].mean():.0f}%" if len(ek) else "—",
             "De todas las kills, cuántas fueron a la cabeza"),
            ("Horas de juego", f"{m['Duración (min)'].sum() / 60:.1f}", None),
        ]))
        lb, note = qualified(lib)
        top = lb.sort_values("rating2", ascending=False).head(10).copy()
        top["label"] = top["name"] + " (" + top["rounds"].astype(int).astype(str) + " r)"
        p.add(charts.ranking_bars(top, "rating2", "label", ref=1.0, ref_label="1.00 = promedio",
                                  title="¿Quiénes son los mejores de la biblioteca?"))
        p.note(f"top 10 por rating sumando todas sus partidas ({note}); entre paréntesis, cuántas rondas jugó. "
               "Más de 1.00 es bueno. Con pocas rondas el número es menos confiable.")
        by_map = m.groupby("Mapa").size()
        side = r.groupby("winner_side").size().reindex(["CT", "T"]).fillna(0)
        side_df = pd.DataFrame({"side": side.index, "pct": 100 * side.values / max(side.sum(), 1),
                                "n": [f"{int(v)} rondas" for v in side.values]})
        p.row(charts.count_bars([pretty_map(x) for x in by_map.index], by_map.values, "¿Qué mapas se jugaron?",
                                total=len(m)),
              charts.side_split(side_df, "pct", "¿Qué lado gana más rondas?", fmt="{:.0f}%", extra="n"))
        p.note("izquierda: cuántas partidas hay de cada mapa. Derecha: de todas las rondas, qué porcentaje ganó cada "
               "lado; si uno gana bastante más del 50 %, esos mapas o partidas vienen cargados hacia ese lado.")
        plots = []
        if len(ek):
            wpn = ek.groupby("weapon").size().sort_values(ascending=False).head(8)
            plots.append(charts.count_bars([weapon_name(x) for x in wpn.index], wpn.values,
                                           "¿Con qué armas se mata más?", total=len(ek)))
        reasons = r.groupby("reason").size()
        plots.append(charts.count_bars([REASON_SHORT.get(x, x) for x in reasons.index], reasons.values,
                                       "¿Cómo terminan las rondas?", total=len(r)))
        p.row(*plots)
        p.note("las 8 armas con más kills, y de qué manera terminó cada ronda: muchas rondas por bomba (detonada o "
               "desactivada) indican partidas de ejecuciones; muchas eliminaciones, de duelos abiertos.")
        p.section("Tabla de jugadores")
        p.add(w.DataTable(stat_table(lb.sort_values("rating2", ascending=False),
                                     ["name", "demos", "rounds", "kd", "adr", "kast_pct", "hs_pct", "rating2"])
                          )).setMinimumHeight(320)
        p.caption(RATING_NOTE)
        return p

    def _player(self, lib: Library, sid: str, name: str) -> QWidget:
        p = Page(margins=(0, 0, 0, 0))
        pr = lib.player_rounds[lib.player_rounds["steamid"] == sid]
        cl = lib.clutches[lib.clutches["steamid"] == sid]
        acc = lib.accuracy[lib.accuracy["steamid"] == sid]
        agg = stats.aggregate(pr, cl, acc).iloc[0]
        per = lib.per_demo(sid)
        base = qualified(lib)[0].median(numeric_only=True)
        wins = int((per["Resultado"] == "Victoria").sum())
        p.section(name)
        p.caption(f"{len(per)} partidas · {int(agg['rounds'])} rondas. Las flechas comparan con la mediana de los "
                  "jugadores de la biblioteca (verde = mejor que la mediana).")
        p.sub("Resultado e impacto")
        p.add(kpi_row([
            ("Winrate", f"{100 * wins / max(len(per), 1):.0f}%", f"{wins} victorias de {len(per)}"),
            ("Rating 2.0*", f"{agg['rating2']:.2f}", RATING_NOTE, delta(agg["rating2"], base.get("rating2"), 2)),
            ("ADR", f"{agg['adr']:.0f}", "Daño a rivales por ronda", delta(agg["adr"], base.get("adr"), 0)),
            ("KAST", f"{agg['kast_pct']:.0f}%", "Rondas con kill, asistencia, supervivencia o muerte tradeada",
             delta(agg["kast_pct"], base.get("kast_pct"), 0, " pp")),
            ("K/D", f"{agg['kd']:.2f}", None, delta(agg["kd"], base.get("kd"), 2)),
            ("HS", f"{agg['hs_pct']:.0f}%", "Kills a la cabeza", delta(agg["hs_pct"], base.get("hs_pct"), 0, " pp")),
        ]))
        p.add(kpi_row([
            ("Aperturas", f"{int(agg['opening_kills'])}-{int(agg['opening_deaths'])}",
             "Primeras kills de la ronda ganadas-perdidas",
             delta(agg["opening_success_pct"], base.get("opening_success_pct"), 0, " pp")),
            ("Clutches", f"{int(agg['clutches_won'])}/{int(agg['clutches'])}", "Ganados / jugados (1vX)"),
            ("Rondas con 3+ kills", f"{int(agg['k3'] + agg['k4'] + agg['k5'])}",
             f"3K: {int(agg['k3'])} · 4K: {int(agg['k4'])} · ACE: {int(agg['k5'])}"),
            ("Tradeos", f"{int(agg['trade_kills'])}", "Kills que vengaron a un compañero en < 5 s"),
            ("Daño de utilidad", f"{agg['utility_adr']:.1f}", "Por ronda, con HE y molotovs",
             delta(agg["utility_adr"], base.get("utility_adr"), 1)),
            ("Precisión", f"{agg['accuracy_pct']:.0f}%" if pd.notna(agg.get("accuracy_pct")) else "—",
             "Impactos / disparos con armas de fuego", delta(agg.get("accuracy_pct"), base.get("accuracy_pct"), 0, " pp")),
        ]))
        mi = lib.micro(sid)
        if len(mi):
            mrow = mi.iloc[0]

            def fmt(col, unit, digits=0):
                v = mrow.get(col)
                return "—" if v is None or pd.isna(v) else f"{v:.{digits}f}{unit}"

            p.sub("Aim")
            p.add(kpi_row([
                ("Mira al ver al rival", fmt("crosshair_deg", "°", 1), "Mediana del ángulo mira→cabeza cuando aparece "
                 "el rival. Menos es mejor.", delta(mrow.get("crosshair_deg"), base.get("crosshair_deg"), 1, "°"), True),
                ("Reacción", fmt("reaction_ms", " ms"), "De ver al rival a disparar. Menos es mejor.",
                 delta(mrow.get("reaction_ms"), base.get("reaction_ms"), 0, " ms"), True),
                ("TTD", fmt("ttd_ms", " ms"), "De ver al rival al primer daño. Menos es mejor.",
                 delta(mrow.get("ttd_ms"), base.get("ttd_ms"), 0, " ms"), True),
                ("Pre-aim", fmt("preaim_pct", "%"), "Duelos ganados con la mira ya sobre el rival (≤ 3°)",
                 delta(mrow.get("preaim_pct"), base.get("preaim_pct"), 0, " pp")),
                ("Counter-strafe", fmt("counter_strafe_pct", "%"), "Disparos hechos frenado",
                 delta(mrow.get("counter_strafe_pct"), base.get("counter_strafe_pct"), 0, " pp")),
                ("Precisión 1ª bala", fmt("first_bullet_acc_pct", "%"), "Impactos de la primera bala de cada ráfaga",
                 delta(mrow.get("first_bullet_acc_pct"), base.get("first_bullet_acc_pct"), 0, " pp")),
            ]))
        if len(per) >= 2:
            p.add(charts.results_timeline(per))
            p.note("cada punto es una partida, con su rating escrito arriba. Punto lleno = ganó; punto vacío = "
                   "perdió. Arriba de la línea punteada (1.00) fue una buena partida.")
        else:
            p.caption("Con una sola partida no hay evolución para mostrar: cargá más demos de este jugador.")
        plots = []
        ms = lib.map_summary(sid)
        if not ms.empty:
            ms = ms.copy()
            ms["label"] = ms["Mapa"].map(pretty_map) + " (" + ms["Partidas"].astype(str) + ")"
            plots.append(charts.ranking_bars(ms, "Winrate %", "label", fmt="{:.0f}%", ref=50, ref_label="50%",
                                             title="¿En qué mapas gana más?"))
        sides = stats.aggregate(pr, by=["steamid", "side"])
        if not sides.empty:
            sides["extra"] = "rating " + sides["rating2"].map("{:.2f}".format) + " · " + sides["rounds"].astype(str) + " r"
            plots.append(charts.side_split(sides, "adr", "¿Rinde más de CT o de T?", fmt="ADR {:.0f}", extra="extra"))
        if plots:
            p.row(*plots)
            p.note("izquierda: porcentaje de partidas ganadas en cada mapa (entre paréntesis, cuántas jugó; con 1 o 2 "
                   "no alcanza para sacar conclusiones). Derecha: daño por ronda de cada lado, con rating y rondas.")
        plots = []
        k = lib.concat("kills")
        mine = k[(k["attacker_steamid"] == sid) & k["is_enemy_kill"]] if len(k) else k
        if len(mine):
            wpn = mine.groupby("weapon").size().sort_values(ascending=False).head(8)
            plots.append(charts.count_bars([weapon_name(x) for x in wpn.index], wpn.values, "¿Con qué armas mata?",
                                           total=len(mine)))
        rounds = int(agg["rounds"])
        mk = {"Ninguna kill": rounds - int(agg["k1"] + agg["k2"] + agg["k3"] + agg["k4"] + agg["k5"]),
              "1 kill": int(agg["k1"]), "2 kills": int(agg["k2"]), "3 kills": int(agg["k3"]),
              "4 kills": int(agg["k4"]), "ACE (5)": int(agg["k5"])}
        plots.append(charts.count_bars(list(mk), list(mk.values()), "¿Cuántas kills hace por ronda?", total=rounds,
                                       keep_order=True))
        p.row(*plots)
        p.note("sus 8 armas con más kills, y en cuántas rondas hizo 0, 1, 2… kills. Las rondas con 2 o más kills son "
               "las que más pesan en el rating.")
        p.section("Tabla de partidas")
        cols = ["Partida", "Mapa", "Marcador propio", "Resultado", "kills", "deaths", "assists", "adr", "kast_pct",
                "hs_pct", "rating2"]
        show = per[cols].copy()
        show["Mapa"] = show["Mapa"].map(pretty_map)
        p.add(w.DataTable(stat_table(show, cols), fit_rows=True))
        return p
