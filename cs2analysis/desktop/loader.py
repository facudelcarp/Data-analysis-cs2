"""Carga de demos en segundo plano: la ventana nunca se congela mientras se parsea."""
from __future__ import annotations

import time
from pathlib import Path

from PySide6.QtCore import QObject, QThread, Signal

from ..multi import load_many


class _Worker(QObject):
    progress = Signal(int, int)
    finished = Signal(list, list, float)  # demos, errores, segundos

    def __init__(self, paths: list[Path]):
        super().__init__()
        self.paths = paths

    def run(self) -> None:
        t0 = time.perf_counter()
        # Muchas .dem: en paralelo con procesos (el parseo es CPU). .cs2a o pocas: en este hilo.
        workers = 4 if sum(1 for p in self.paths if str(p).endswith(".dem")) > 2 else 1
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
