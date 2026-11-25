"""Tema oscuro de la app nativa, con la misma identidad visual que la web (palette.py)."""
from __future__ import annotations

from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QApplication

from ..palette import ACCENT, BACKGROUND, BORDER, MUTED, SIDEBAR, SURFACE, SURFACE_2, TEXT

QSS = f"""
QWidget {{ color: {TEXT}; font-size: 10pt; }}
QMainWindow, QScrollArea, QScrollArea > QWidget > QWidget {{ background: {BACKGROUND}; }}
#Sidebar {{ background: {SIDEBAR}; border-right: 1px solid {BORDER}; }}
#Brand {{ font-size: 14pt; font-weight: 800; padding: 14px 14px 2px 14px; }}
#BrandTag {{ color: {MUTED}; padding: 0 14px 12px 14px; }}
#Nav {{ background: transparent; border: none; outline: none; }}
#Nav::item {{ padding: 8px 12px; border-radius: 8px; margin: 1px 8px; }}
#Nav::item:selected {{ background: rgba(240,163,61,.14); color: {ACCENT}; }}
#Nav::item:disabled {{ color: #5b6270; }}
#PageTitle {{ font-size: 18pt; font-weight: 800; }}
#PageSubtitle, #Muted, #Note {{ color: {MUTED}; }}
#Section {{ font-size: 12.5pt; font-weight: 700; padding-top: 10px; }}
#Card {{ background: {SURFACE}; border: 1px solid {BORDER}; border-radius: 10px; }}
#CardLabel {{ color: {MUTED}; font-size: 9pt; }}
#CardValue {{ font-size: 13pt; font-weight: 700; }}
#Banner {{ background: {SURFACE}; border: 1px solid {BORDER}; border-radius: 12px; }}
#Score {{ font-size: 30pt; font-weight: 800; }}
#Chip {{ background: {SURFACE_2}; border: 1px solid {BORDER}; border-radius: 9px; padding: 3px 9px; color: {MUTED}; }}
#Empty {{ color: {MUTED}; font-size: 12pt; }}
QPushButton {{ background: {SURFACE_2}; border: 1px solid {BORDER}; border-radius: 8px; padding: 6px 12px; }}
QPushButton:hover {{ border-color: {ACCENT}; }}
QPushButton#Primary {{ background: {ACCENT}; color: #14110c; font-weight: 700; border: none; }}
QComboBox {{ background: {SURFACE}; border: 1px solid {BORDER}; border-radius: 8px; padding: 5px 10px; }}
QTabWidget::pane {{ border: none; border-top: 1px solid {BORDER}; }}
QTabBar::tab {{ background: transparent; padding: 7px 13px; border-radius: 8px 8px 0 0; color: {MUTED};
                font-weight: 600; }}
QTabBar::tab:selected {{ color: {TEXT}; background: rgba(240,163,61,.10); border-bottom: 2px solid {ACCENT}; }}
QTableView {{ background: {SURFACE}; alternate-background-color: #171d26; border: 1px solid {BORDER};
              border-radius: 8px; gridline-color: transparent; selection-background-color: rgba(240,163,61,.25); }}
QHeaderView::section {{ background: {SURFACE_2}; color: {MUTED}; border: none; border-bottom: 1px solid {BORDER};
                        padding: 5px 6px; font-weight: 600; }}
QStatusBar {{ color: {MUTED}; }}
QProgressBar {{ background: {SURFACE}; border: 1px solid {BORDER}; border-radius: 6px; text-align: center; }}
QProgressBar::chunk {{ background: {ACCENT}; border-radius: 6px; }}
"""


def apply(app: QApplication) -> None:
    app.setStyle("Fusion")
    pal = QPalette()
    for role, color in [(QPalette.Window, BACKGROUND), (QPalette.Base, SURFACE), (QPalette.AlternateBase, SURFACE_2),
                        (QPalette.Text, TEXT), (QPalette.WindowText, TEXT), (QPalette.Button, SURFACE_2),
                        (QPalette.ButtonText, TEXT), (QPalette.Highlight, ACCENT), (QPalette.ToolTipBase, SURFACE),
                        (QPalette.ToolTipText, TEXT), (QPalette.PlaceholderText, MUTED)]:
        pal.setColor(role, QColor(color))
    app.setPalette(pal)
    app.setStyleSheet(QSS)
