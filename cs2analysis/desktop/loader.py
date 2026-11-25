"""Carga de demos en segundo plano: la ventana nunca se congela mientras se parsea."""
from __future__ import annotations

import time
from pathlib import Path

import shiboken6
from PySide6.QtCore import QObject, Qt, QThread, Signal, Slot

from ..multi import load_many
from ..parser import is_demo


class _Worker(QObject):
    progress = Signal(int, int)
    finished = Signal(list, list, float)  # demos, errores, segundos

    def __init__(self, paths: list[Path]):
        super().__init__()
        self.paths = paths

    def run(self) -> None:
        t0 = time.perf_counter()
        # Muchas .dem: en paralelo con procesos (el parseo es CPU). .cs2a o pocas: en este hilo.
        workers = 4 if sum(1 for p in self.paths if is_demo(p)) > 2 else 1
        demos, errors = load_many(self.paths, workers=workers, progress=self.progress.emit)
        self.finished.emit(demos, errors, time.perf_counter() - t0)


class Loader(QObject):
    """Lanza una carga por vez; emite progress(i, n) y finished(demos, errores, segundos)."""
    progress = Signal(int, int)
    finished = Signal(list, list, float)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._thread: QThread | None = None

    @property
    def busy(self) -> bool:
        return self._thread is not None

    def start(self, paths: list[Path]) -> bool:
        if self.busy or not paths:
            return False
        self._thread = QThread()
        self._worker = _Worker(paths)
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.run)
        self._worker.progress.connect(self.progress)
        self._worker.finished.connect(self._thread.quit)  # el hilo se cierra solo al terminar
        self._worker.finished.connect(self._done)            # y la ventana se entera en su propio hilo
        self._thread.start()
        return True

    def _done(self, demos, errors, seconds) -> None:
        self._thread.wait()
        self._thread = None
        self.finished.emit(demos, errors, seconds)

    def wait(self, ms: int = 120_000) -> bool:
        """Para tests y scripts: espera a que termine la carga en curso y se entregue el resultado.

        Procesa eventos mientras espera: el resultado llega a la ventana por la cola de eventos."""
        from PySide6.QtCore import QCoreApplication, QDeadlineTimer
        deadline = QDeadlineTimer(ms)
        while self.busy and not deadline.hasExpired():
            QCoreApplication.processEvents()
            QThread.msleep(5)
        return not self.busy


class _FnWorker(QObject):
    done = Signal(object, str)  # resultado, error

    def __init__(self, fn):
        super().__init__()
        self.fn = fn

    def run(self) -> None:
        try:
            self.done.emit(self.fn(), "")
        except Exception as exc:  # sin red, permisos…
            self.done.emit(None, str(exc))


class _Relay(QObject):
    """Receptor que vive en el hilo de la ventana. Conectar una señal a una función suelta la ejecuta en el hilo
    que emite (el de fondo), y ahí no se pueden crear widgets ni diálogos."""

    def __init__(self, on_done, owner):
        super().__init__()
        self.on_done, self.owner = on_done, owner

    @Slot(object, str)
    def deliver(self, result, error) -> None:
        if shiboken6.isValid(self.owner):  # el panel que lo pidió puede haberse cerrado mientras tanto
            self.on_done(result, error)


# Hilos en curso. No son hijos del widget que los lanzó: si ese widget se destruye mientras calculan (cambió un
# filtro y se rearmó la página), Qt destruiría un hilo corriendo y la app se cierra. Viven acá hasta terminar.
_RUNNING: set = set()


def run_in_background(owner: QObject, fn, on_done) -> QThread:
    """Corre fn() en un hilo y llama on_done(resultado, error) en el hilo de la ventana, si `owner` sigue vivo."""
    thread = QThread()
    worker = _FnWorker(fn)
    worker.moveToThread(thread)
    relay = _Relay(on_done, owner)
    entry = (thread, worker, relay)
    _RUNNING.add(entry)
    thread.started.connect(worker.run)
    worker.done.connect(relay.deliver, Qt.QueuedConnection)
    # quit es seguro desde cualquier hilo: conexión directa. Encolada, necesitaría que el hilo de la ventana procese
    # eventos, y wait_all() justamente lo bloquea esperando: se trababa hasta el timeout.
    worker.done.connect(thread.quit, Qt.DirectConnection)
    thread.finished.connect(lambda: _RUNNING.discard(entry), Qt.DirectConnection)
    thread.start()
    return thread


def wait_all(ms: int = 60_000) -> None:
    """Espera a que terminen los hilos en curso (al cerrar la app o en tests)."""
    for thread, _, _ in list(_RUNNING):
        thread.wait(ms)
