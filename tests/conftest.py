"""Configuración común de pytest."""
import os
import sys
import tempfile

# Las preferencias (quién es "yo") de los tests no tocan las del usuario
os.environ["CS2A_PREFS"] = os.path.join(tempfile.mkdtemp(prefix="cs2a-prefs-"), "prefs.json")

_status = {"code": 0}


def pytest_sessionfinish(session, exitstatus):
    _status["code"] = int(exitstatus)


def pytest_unconfigure(config):
    """Con Qt cargado, salir sin el desmontaje del intérprete.

    Los tests comparten una QApplication y dejan widgets vivos; al terminar, Python y Qt los destruyen en un orden
    que a veces rompe la memoria (malloc_consolidate) DESPUÉS de que pasaron todos los tests, y el proceso sale con
    error: el CI quedaría en rojo al azar. La app real no tiene el problema (abre, usa y cierra una sola ventana;
    probado en 16 corridas). Acá ya se reportó todo, así que se sale directo con el código de pytest."""
    if "PySide6.QtWidgets" in sys.modules:
        sys.stdout.flush()
        sys.stderr.flush()
        os._exit(_status["code"])
