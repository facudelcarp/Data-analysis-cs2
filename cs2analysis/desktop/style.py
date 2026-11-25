"""Tema oscuro de la app nativa.

Reglas (inspiradas en la guía ui-ux-pro-max, adaptadas a escritorio):
- Espaciado en escala de 4 px (SP), la misma en márgenes, separaciones y rellenos.
- Jerarquía por tamaño y peso, no solo por color: título 700, sección 600, etiqueta 500, cuerpo 400.
- Dígitos tabulares en toda la app: en tablas y KPIs los números no "bailan" al cambiar.
- Contraste: texto principal ~13:1 y secundario ~6:1 sobre el fondo (AA pide 4.5:1).
- Íconos propios (icons.py), no emojis; el color nunca es la única señal (siempre hay texto).
"""
from __future__ import annotations

import sys

from PySide6.QtGui import QColor, QFont, QPalette
from PySide6.QtWidgets import QApplication

from ..palette import ACCENT, BACKGROUND, BORDER, MUTED, SIDEBAR, SURFACE, SURFACE_2, TEXT

SP = 4                       # unidad de espaciado
RADIUS = 8
HOVER = "#202734"            # superficie bajo el mouse
SELECT = "rgba(240,163,61,.14)"

QSS = f"""
QWidget {{ color: {TEXT}; }}
QMainWindow, QScrollArea, QScrollArea > QWidget > QWidget, QStackedWidget {{ background: {BACKGROUND}; }}
QToolTip {{ background: {SURFACE_2}; color: {TEXT}; border: 1px solid {BORDER}; padding: {SP}px {2 * SP}px;
            border-radius: 6px; }}

/* Barra lateral */
#Sidebar {{ background: {SIDEBAR}; border-right: 1px solid {BORDER}; }}
#Brand {{ font-size: 14pt; font-weight: 700; padding: {4 * SP}px {4 * SP}px 0 {4 * SP}px; }}
#BrandTag {{ color: {MUTED}; padding: {SP}px {4 * SP}px {4 * SP}px {4 * SP}px; }}
#NavLabel {{ color: #6b7280; font-size: 8pt; font-weight: 600; letter-spacing: 1px;
             padding: {2 * SP}px {5 * SP}px {SP}px {5 * SP}px; }}
#Nav {{ background: transparent; border: none; outline: none; }}
#Nav::item {{ padding: {2 * SP}px {3 * SP}px; margin: 1px {2 * SP}px; border-radius: 6px; color: {MUTED};
              border-left: 3px solid transparent; }}
#Nav::item:hover {{ background: {HOVER}; color: {TEXT}; }}
#Nav::item:selected {{ background: {SELECT}; color: {TEXT}; border-left: 3px solid {ACCENT}; font-weight: 600; }}
#SideCount {{ color: {MUTED}; font-size: 9pt; padding-top: {SP}px; }}

/* Tipografía de página */
#PageTitle {{ font-size: 17pt; font-weight: 700; }}
#PageSubtitle, #Muted {{ color: {MUTED}; }}
#Section {{ font-size: 12pt; font-weight: 600; padding-top: {3 * SP}px; }}
#Note {{ color: {MUTED}; }}
#ReadNote {{ color: {MUTED}; border-left: 2px solid {BORDER}; padding: {SP}px 0 {SP}px {3 * SP}px; }}

/* Tarjetas */
#Card {{ background: {SURFACE}; border: 1px solid {BORDER}; border-radius: {RADIUS + 2}px; }}
#CardLabel {{ color: {MUTED}; font-size: 8.5pt; font-weight: 500; }}
#CardValue {{ font-size: 14pt; font-weight: 700; }}
#Banner {{ background: {SURFACE}; border: 1px solid {BORDER}; border-radius: {RADIUS + 4}px; }}
#Score {{ font-size: 30pt; font-weight: 800; }}
#Chip {{ background: {SURFACE_2}; border: 1px solid {BORDER}; border-radius: 10px; padding: 2px {3 * SP}px;
         color: {MUTED}; }}

/* Estado vacío y de carga */
#Empty {{ color: {MUTED}; font-size: 11pt; }}
#EmptyTitle {{ font-size: 15pt; font-weight: 600; }}
#Loading {{ color: {MUTED}; }}

/* Controles */
QPushButton {{ background: {SURFACE_2}; border: 1px solid {BORDER}; border-radius: 6px;
               padding: {int(1.5 * SP)}px {3 * SP}px; }}
QPushButton:hover {{ background: {HOVER}; border-color: #3a4352; }}
QPushButton:pressed {{ background: {SURFACE}; }}
QPushButton:focus {{ border-color: {ACCENT}; }}
QPushButton:disabled {{ color: #5b6270; border-color: {BORDER}; }}
QPushButton#Primary {{ background: {ACCENT}; color: #14110c; font-weight: 600; border: none; }}
QPushButton#Primary:hover {{ background: #f5b45c; }}
QComboBox, QSpinBox, QLineEdit {{ background: {SURFACE}; border: 1px solid {BORDER}; border-radius: 6px;
                                  padding: {SP}px {2 * SP}px; min-height: 18px; }}
QComboBox:hover, QSpinBox:hover, QLineEdit:hover {{ border-color: #3a4352; }}
QComboBox:focus, QSpinBox:focus, QLineEdit:focus {{ border-color: {ACCENT}; }}
QComboBox QAbstractItemView {{ background: {SURFACE}; border: 1px solid {BORDER}; selection-background-color: {SELECT};
                               outline: none; padding: {SP}px; }}
QCheckBox {{ spacing: {2 * SP}px; }}
QSlider::groove:horizontal {{ height: 4px; background: {BORDER}; border-radius: 2px; }}
QSlider::sub-page:horizontal {{ background: {ACCENT}; border-radius: 2px; }}
QSlider::handle:horizontal {{ background: {TEXT}; width: 14px; height: 14px; margin: -5px 0; border-radius: 7px; }}

/* Pestañas */
QTabWidget::pane {{ border: none; border-top: 1px solid {BORDER}; }}
QTabBar::tab {{ background: transparent; padding: {2 * SP}px {4 * SP}px; color: {MUTED}; font-weight: 500;
                border-bottom: 2px solid transparent; margin-right: {SP}px; }}
QTabBar::tab:hover {{ color: {TEXT}; }}
QTabBar::tab:selected {{ color: {TEXT}; border-bottom: 2px solid {ACCENT}; font-weight: 600; }}

/* Tablas */
QTableView {{ background: {SURFACE}; alternate-background-color: #171d26; border: 1px solid {BORDER};
              border-radius: {RADIUS}px; gridline-color: transparent; selection-background-color: {SELECT};
              selection-color: {TEXT}; }}
QTableView::item {{ padding: 0 {2 * SP}px; }}
QTableView::item:hover {{ background: {HOVER}; }}
QHeaderView::section {{ background: {SURFACE_2}; color: {MUTED}; border: none; border-bottom: 1px solid {BORDER};
                        padding: {int(1.5 * SP)}px {2 * SP}px; font-weight: 600; font-size: 8.5pt; }}
QHeaderView::section:hover {{ color: {TEXT}; }}
QListWidget {{ background: {SURFACE}; border: 1px solid {BORDER}; border-radius: {RADIUS}px; outline: none; }}
QListWidget::item {{ padding: {SP}px {2 * SP}px; }}
QListWidget::item:hover {{ background: {HOVER}; }}
QListWidget::item:selected {{ background: {SELECT}; color: {TEXT}; }}
QPlainTextEdit {{ background: {SURFACE}; border: 1px solid {BORDER}; border-radius: {RADIUS}px; padding: {2 * SP}px; }}

/* Barras de scroll finas */
QScrollBar:vertical {{ background: transparent; width: 10px; margin: 2px; }}
QScrollBar:horizontal {{ background: transparent; height: 10px; margin: 2px; }}
QScrollBar::handle {{ background: #2e3542; border-radius: 3px; min-height: 32px; min-width: 32px; }}
QScrollBar::handle:hover {{ background: #3d4655; }}
QScrollBar::add-line, QScrollBar::sub-line, QScrollBar::add-page, QScrollBar::sub-page {{ background: none;
    border: none; width: 0; height: 0; }}

/* Barra de estado y progreso */
QStatusBar {{ color: {MUTED}; border-top: 1px solid {BORDER}; }}
QProgressBar {{ background: {SURFACE}; border: none; border-radius: 2px; max-height: 4px; text-align: center; }}
QProgressBar::chunk {{ background: {ACCENT}; border-radius: 2px; }}
QMenuBar {{ background: {SIDEBAR}; border-bottom: 1px solid {BORDER}; }}
QMenuBar::item {{ padding: {SP}px {3 * SP}px; background: transparent; }}
QMenuBar::item:selected {{ background: {HOVER}; }}
QMenu {{ background: {SURFACE}; border: 1px solid {BORDER}; padding: {SP}px; }}
QMenu::item {{ padding: {int(1.5 * SP)}px {6 * SP}px {int(1.5 * SP)}px {3 * SP}px; border-radius: 4px; }}
QMenu::item:selected {{ background: {SELECT}; }}
QMenu::separator {{ height: 1px; background: {BORDER}; margin: {SP}px {2 * SP}px; }}
"""


def app_font() -> QFont:
    """Fuente del sistema (Segoe UI en Windows) a 10 pt, con dígitos tabulares."""
    f = QFont("Segoe UI" if sys.platform == "win32" else QApplication.font().family())
    f.setPointSizeF(10)
    try:  # Qt >= 6.7: OpenType "tnum"
        f.setFeature(QFont.Tag("tnum"), 1)
    except (AttributeError, TypeError):
        pass
    return f


def apply(app: QApplication) -> None:
    app.setStyle("Fusion")
    app.setFont(app_font())
    pal = QPalette()
    for role, color in [(QPalette.Window, BACKGROUND), (QPalette.Base, SURFACE), (QPalette.AlternateBase, SURFACE_2),
                        (QPalette.Text, TEXT), (QPalette.WindowText, TEXT), (QPalette.Button, SURFACE_2),
                        (QPalette.ButtonText, TEXT), (QPalette.Highlight, ACCENT), (QPalette.ToolTipBase, SURFACE_2),
                        (QPalette.ToolTipText, TEXT), (QPalette.PlaceholderText, MUTED)]:
        pal.setColor(role, QColor(color))
    app.setPalette(pal)
    app.setStyleSheet(QSS)
    from . import icons
    app.aboutToQuit.connect(icons.clear_cache)  # al cerrar la ventana, antes de destruir la QApplication
