"""A high-contrast fantasy-tabletop visual system with system font fallbacks."""
from PyQt6.QtGui import QFont, QFontDatabase
from PyQt6.QtWidgets import QApplication

DISPLAY_FONTS = ("Palatino Linotype", "Book Antiqua", "Georgia", "Garamond", "Times New Roman")
BODY_FONTS = ("Segoe UI", "Aptos", "Noto Sans", "DejaVu Sans", "Arial")

def _available_font(preferences):
    installed = {name.casefold(): name for name in QFontDatabase.families()}
    for name in preferences:
        if name.casefold() in installed:
            return installed[name.casefold()]
    return preferences[-1]

def apply_theme(app: QApplication) -> None:
    """Apply before creating any top-level windows or dialogs."""
    app.setStyle("Fusion")
    body = _available_font(BODY_FONTS)
    display = _available_font(DISPLAY_FONTS)
    app.setFont(QFont(body, 10))
    app.setStyleSheet(STYLE.replace("__DISPLAY__", f'"{display}"').replace("__BODY__", f'"{body}"'))

STYLE = r"""
* { font-family: __BODY__; color: #ece3d2; }
QWidget { background: transparent; }
QMainWindow, QDialog { background-color: #101719; }
QToolTip { background-color: #ede0c5; color: #18201f; border: 1px solid #b2945c; padding: 5px; }
QLabel { background: transparent; }
QLabel#eyebrow { color: #bd9d68; font-size: 10px; font-weight: 700; }
QLabel#muted { color: #a9b3b0; font-size: 11px; }
QLabel#sectionTitle { font-family: __DISPLAY__; font-size: 17px; font-weight: 700; color: #f0dfbb; }
QLabel#pageTitle { font-family: __DISPLAY__; font-size: 30px; font-weight: 700; color: #f3e2c2; }
QLabel#brandTitle { font-family: __DISPLAY__; font-size: 18px; font-weight: 700; color: #f3dfbb; }
QLabel#detailTitle { font-family: __DISPLAY__; font-size: 21px; font-weight: 700; color: #f3e2c2; }
QLabel#metricValue { font-family: __DISPLAY__; font-size: 25px; font-weight: 700; color: #f3e4c6; }
QLabel#metricLabel { font-size: 10px; color: #b7bbae; font-weight: 700; }
QLabel#crest { font-family: __DISPLAY__; font-size: 22px; color: #dec18e; background: #293431; border: 1px solid #88704a; border-radius: 27px; }
QLabel#tag { font-size: 10px; font-weight: 700; color: #d7be8e; background: #2b352f; padding: 5px 9px; border-radius: 8px; }
QFrame#sidebar { background: #17201f; border-right: 1px solid #3a443d; }
QFrame#hero { background: #202b29; border: 1px solid #4b5548; border-left: 3px solid #c49a62; border-radius: 13px; }
QFrame#panel { background: #1a2323; border: 1px solid #3b4945; border-radius: 12px; }
QFrame#metric { background: #1d2927; border: 1px solid #3c4d43; border-radius: 11px; }
QFrame#divider { background: #4c4a3c; max-height: 1px; min-height: 1px; }
QFrame#statChip { background: #26332f; border: 1px solid #42524a; border-radius: 8px; }
QLabel#statName { font-size: 10px; font-weight: 700; color: #c2aa7e; }
QLabel#statValue { font-family: __DISPLAY__; font-size: 18px; font-weight: 700; color: #f5e4c3; }
QPushButton { color: #ede6d6; background: #2a3835; border: 1px solid #536056; border-radius: 8px; padding: 10px 15px; min-height: 19px; font-weight: 600; }
QPushButton:hover { background: #384b44; border-color: #b49866; }
QPushButton:pressed { background: #24302b; }
QPushButton:disabled { color: #798780; background: #242d2c; border-color: #394340; }
QPushButton:focus { border: 2px solid #e2be77; }
QPushButton#primaryButton { background: #ad814a; color: #121a18; border: 1px solid #e2bc7a; font-weight: 700; }
QPushButton#primaryButton:hover { background: #c79c60; }
QPushButton#primaryButton:disabled { background: #685a42; color: #a69a82; border-color: #6d614c; }
QPushButton#dangerButton { color: #edc3ae; border: 1px solid #8a625b; background: #372925; }
QPushButton#dangerButton:hover { background: #583730; }
QPushButton#navButton { background: transparent; text-align: left; border: 1px solid transparent; border-radius: 8px; color: #c5cebf; padding: 12px 14px; }
QPushButton#navButton:hover { background: #293932; border-color: #43584d; }
QPushButton#navButton:checked { color: #f7e4c1; background: #34443a; border: 1px solid #8d7850; border-left: 3px solid #dfb675; }
QLineEdit, QTextEdit, QPlainTextEdit, QSpinBox, QComboBox { background: #101a1b; border: 1px solid #55635b; border-radius: 7px; selection-background-color: #886d4c; selection-color: #ffffff; padding: 8px 10px; color: #f3ebdd; }
QLineEdit:focus, QTextEdit:focus, QPlainTextEdit:focus, QSpinBox:focus, QComboBox:focus { border: 2px solid #d9b478; }
QLineEdit::placeholder { color: #8f9f98; }
QComboBox::drop-down { border: none; width: 24px; }
QComboBox QAbstractItemView { background: #1c2927; color: #f5e6cd; selection-background-color: #4b5a4b; }
QCheckBox { color: #c8d0c6; spacing: 8px; background: transparent; }
QCheckBox::indicator { width: 17px; height: 17px; }
QCheckBox::indicator:unchecked { border: 1px solid #8e987f; background: #172321; border-radius: 3px; }
QCheckBox::indicator:checked { border: 1px solid #e0b875; background: #ba9256; border-radius: 3px; }
QListWidget { background: #1a2323; alternate-background-color: #202d2a; color: #efe8d8; border: 1px solid #3b4945; border-radius: 8px; padding: 5px; }
QListWidget::item { padding: 9px 12px; }
QListWidget::item:selected { background: #3b5044; color: #ffedca; }
QTableWidget { background: #1a2323; alternate-background-color: #202d2a; color: #efe8d8; border: none; gridline-color: #384741; outline: none; selection-background-color: #3c5046; selection-color: #fff2d6; font-size: 11px; }
QTableWidget::item { padding: 8px 10px; border-bottom: 1px solid #37443e; }
QTableWidget::item:selected { background: #3b5044; color: #ffedca; }
QHeaderView { background: #25332e; }
QHeaderView::section { background: #25332e; color: #cbb98f; border: 0; border-bottom: 1px solid #5c614f; padding: 11px 8px; font-weight: 700; font-size: 10px; }
QTableCornerButton::section { background: #25332e; border: none; }
QScrollBar:vertical { width: 11px; background: #1b2523; }
QScrollBar::handle:vertical { background: #536156; border-radius: 4px; min-height: 28px; }
QScrollBar:horizontal { height: 11px; background: #1b2523; }
QScrollBar::handle:horizontal { background: #536156; border-radius: 4px; min-width: 28px; }
QScrollBar::add-line, QScrollBar::sub-line { height: 0px; width: 0px; }
QScrollArea { background: transparent; border: none; }
QSplitter::handle { background: #101719; width: 10px; }
QStatusBar { color: #a6b4aa; background: #17201e; border-top: 1px solid #3e4b40; font-size: 10px; }
QStatusBar::item { border: none; }
QMessageBox { background: #1a2323; }
"""
