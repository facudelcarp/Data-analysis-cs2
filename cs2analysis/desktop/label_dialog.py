"""Diálogo para etiquetar a mano la estrategia de una ronda (ver labels_store.py)."""
from __future__ import annotations

from PySide6.QtWidgets import QComboBox, QDialog, QDialogButtonBox, QFormLayout, QLabel, QVBoxLayout

from .. import labels_store


class LabelDialog(QDialog):
    """No muestra lo que dice la app: la etiqueta tiene que ser independiente para que el acuerdo signifique algo."""

    def __init__(self, demo_id: str, rnd: int, parent=None):
        super().__init__(parent)
        self.demo_id, self.rnd = demo_id, rnd
        self.setWindowTitle(f"Etiquetar ronda {rnd}")
        v = QVBoxLayout(self)
        intro = QLabel("Lo que viste en el replay. Dejá «—» lo que no tengas claro: no cuenta. La app no te muestra "
                       "su lectura para no influirte; el acuerdo se ve en Herramientas → Acuerdo con mis etiquetas.")
        intro.setWordWrap(True)
        v.addWidget(intro)
        form = QFormLayout()
        current = labels_store.get(demo_id, rnd)
        self.boxes: dict[str, QComboBox] = {}
        for field, (question, options) in labels_store.FIELDS.items():
            box = QComboBox()
            box.addItem("—", "")
            for o in options:
                box.addItem(o, o)
            i = box.findData(current.get(field, ""))
            box.setCurrentIndex(max(0, i))
            self.boxes[field] = box
            form.addRow(question, box)
        v.addLayout(form)
        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self._save)
        buttons.rejected.connect(self.reject)
        v.addWidget(buttons)

    def values(self) -> dict:
        return {f: b.currentData() for f, b in self.boxes.items()}

    def _save(self) -> None:
        labels_store.put(self.demo_id, self.rnd, self.values())
        self.accept()
