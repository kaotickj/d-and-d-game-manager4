"""The Compendium's crimson, obsidian, and parchment visual system."""
from importlib.resources import files

from PyQt6.QtGui import QColor, QFont, QFontDatabase, QPalette
from PyQt6.QtWidgets import QApplication

DISPLAY_FONTS = (
    "Palatino Linotype", "Book Antiqua", "Georgia", "Garamond",
    "Bitstream Charter", "DejaVu Serif", "Liberation Serif", "Times New Roman",
)
BODY_FONTS = ("Segoe UI", "Aptos", "Noto Sans", "DejaVu Sans", "Arial")

# Shared with native Qt artwork framing so bundled illustrations and controls
# use the same inks. Warm text keeps long rules passages readable on black.
COLORS = {
    "window": "#09070a", "sidebar": "#110b10", "panel": "#1a1117",
    "raised": "#25131c", "input": "#0e0a0e", "alternate": "#22121b",
    "button": "#351620", "hover": "#511c2d", "pressed": "#250f18",
    "primary": "#ad2943", "primary_hover": "#c3354e",
    "selection": "#76243a", "border": "#69303f", "border_muted": "#45202e",
    "ember": "#ed6276", "text": "#f1e6d5", "title": "#f5dfbd",
    "muted": "#c3adb8", "accent": "#f0a0af", "selected_text": "#fff3e2",
    "focus": "#f5c985", "disabled": "#21151d", "disabled_text": "#aa929f",
    "tooltip": "#f1e1c7", "tooltip_text": "#27121c",
}


def _available_font(preferences):
    installed = {name.casefold(): name for name in QFontDatabase.families()}
    for name in preferences:
        if name.casefold() in installed:
            return installed[name.casefold()]
    return preferences[-1]


def apply_theme(app: QApplication) -> None:
    """Apply before creating any top-level windows or dialogs.

    A native palette also covers transient menus, message boxes, and controls
    that the platform or an extension creates outside the main stylesheet.
    """
    app.setStyle("Fusion")
    palette = QPalette()
    roles = {
        QPalette.ColorRole.Window: "window",
        QPalette.ColorRole.WindowText: "text",
        QPalette.ColorRole.Base: "input",
        QPalette.ColorRole.AlternateBase: "alternate",
        QPalette.ColorRole.Text: "text",
        QPalette.ColorRole.Button: "button",
        QPalette.ColorRole.ButtonText: "text",
        QPalette.ColorRole.BrightText: "ember",
        QPalette.ColorRole.Highlight: "selection",
        QPalette.ColorRole.HighlightedText: "selected_text",
        QPalette.ColorRole.PlaceholderText: "muted",
        QPalette.ColorRole.ToolTipBase: "tooltip",
        QPalette.ColorRole.ToolTipText: "tooltip_text",
        QPalette.ColorRole.Light: "border",
        QPalette.ColorRole.Mid: "border_muted",
        QPalette.ColorRole.Dark: "window",
        QPalette.ColorRole.Shadow: "window",
        QPalette.ColorRole.Link: "accent",
        QPalette.ColorRole.LinkVisited: "accent",
    }
    for role, color in roles.items():
        palette.setColor(role, QColor(COLORS[color]))
    for role in (QPalette.ColorRole.WindowText, QPalette.ColorRole.Text,
                 QPalette.ColorRole.ButtonText):
        palette.setColor(QPalette.ColorGroup.Disabled, role,
                         QColor(COLORS["disabled_text"]))
    palette.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.Button,
                     QColor(COLORS["disabled"]))
    app.setPalette(palette)
    body = _available_font(BODY_FONTS)
    display = _available_font(DISPLAY_FONTS)
    app.setFont(QFont(body, 10))
    stylesheet = STYLE.replace("__DISPLAY__", f'"{display}"').replace("__BODY__", f'"{body}"')
    for name, color in COLORS.items():
        stylesheet = stylesheet.replace(f"__{name.upper()}__", color)
    for asset in ("checkmark", "chevron_down", "chevron_up"):
        path = str(files("dndgm4").joinpath("assets", f"{asset}.svg")).replace("\\", "/")
        stylesheet = stylesheet.replace(f"__{asset.upper()}__", path)
    app.setStyleSheet(stylesheet)


STYLE = r"""
* { font-family: __BODY__; color: __TEXT__; }
QWidget { background: transparent; }
QMainWindow, QDialog { background-color: __WINDOW__; }
QToolTip { background-color: __TOOLTIP__; color: __TOOLTIP_TEXT__; border: 1px solid __FOCUS__; padding: 5px; }
QLabel { background: transparent; }
QLabel#eyebrow { color: __ACCENT__; font-size: 10px; font-weight: 700; }
QLabel#muted { color: __MUTED__; font-size: 11px; }
QLabel#sectionTitle { font-family: __DISPLAY__; font-size: 17px; font-weight: 700; color: __TITLE__; }
QLabel#pageTitle { font-family: __DISPLAY__; font-size: 30px; font-weight: 700; color: __TITLE__; }
QLabel#brandTitle { font-family: __DISPLAY__; font-size: 18px; font-weight: 700; color: __TITLE__; }
QLabel#detailTitle { font-family: __DISPLAY__; font-size: 21px; font-weight: 700; color: __TITLE__; }
QLabel#metricValue { font-family: __DISPLAY__; font-size: 25px; font-weight: 700; color: __TITLE__; }
QLabel#metricLabel { font-size: 10px; color: __MUTED__; font-weight: 700; }
QLabel#crest { font-family: __DISPLAY__; font-size: 22px; color: __TITLE__; background: __RAISED__; border: 1px solid __BORDER__; border-radius: 27px; }
QLabel#tag { font-size: 10px; font-weight: 700; color: __ACCENT__; background: __RAISED__; padding: 5px 9px; border-radius: 8px; }
QFrame#sidebar { background: __SIDEBAR__; border-right: 1px solid __BORDER__; }
QFrame#hero { background: __RAISED__; border: 1px solid __BORDER__; border-left: 3px solid __EMBER__; border-radius: 13px; }
QFrame#panel { background: __PANEL__; border: 1px solid __BORDER__; border-radius: 12px; }
QFrame#metric { background: __RAISED__; border: 1px solid __BORDER__; border-radius: 11px; }
QFrame#divider { background: __BORDER__; max-height: 1px; min-height: 1px; }
QFrame#statChip { background: __RAISED__; border: 1px solid __BORDER__; border-radius: 8px; }
QLabel#statName { font-size: 10px; font-weight: 700; color: __ACCENT__; }
QLabel#statValue { font-family: __DISPLAY__; font-size: 18px; font-weight: 700; color: __TITLE__; }
QPushButton, QToolButton { color: __TEXT__; background: __BUTTON__; border: 1px solid __BORDER__; border-radius: 8px; padding: 10px 15px; min-height: 19px; font-weight: 600; }
QPushButton:hover, QToolButton:hover { background: __HOVER__; border-color: __EMBER__; }
QPushButton:pressed, QToolButton:pressed { background: __PRESSED__; }
QPushButton:disabled, QToolButton:disabled { color: __DISABLED_TEXT__; background: __DISABLED__; border-color: __BORDER_MUTED__; }
QPushButton:focus, QToolButton:focus { border: 2px solid __FOCUS__; }
QPushButton#primaryButton { background: __PRIMARY__; color: __SELECTED_TEXT__; border: 1px solid __EMBER__; font-weight: 700; }
QPushButton#primaryButton:hover { background: __PRIMARY_HOVER__; }
QPushButton#primaryButton:disabled { background: __DISABLED__; color: __DISABLED_TEXT__; border-color: __BORDER_MUTED__; }
QPushButton#primaryButton:focus { border: 2px solid __FOCUS__; }
QPushButton#dangerButton { color: __ACCENT__; border: 1px solid __EMBER__; background: __BUTTON__; }
QPushButton#dangerButton:hover { background: __HOVER__; }
QPushButton#dangerButton:disabled { color: __DISABLED_TEXT__; border-color: __BORDER_MUTED__; background: __DISABLED__; }
QPushButton#dangerButton:focus { border: 2px solid __FOCUS__; }
QScrollArea#sidebarScroll { background: __SIDEBAR__; border-right: 1px solid __BORDER__; }
QScrollArea#workspaceScroll { background: __WINDOW__; border: none; }
QPushButton#navButton { background: transparent; text-align: left; border: 1px solid transparent; border-radius: 8px; color: __MUTED__; padding: 12px 14px; }
QPushButton#navButton:hover { background: __RAISED__; border-color: __BORDER__; }
QPushButton#navButton:checked { color: __SELECTED_TEXT__; background: __SELECTION__; border: 1px solid __EMBER__; border-left: 3px solid __EMBER__; }
QPushButton#navButton:focus { border: 2px solid __FOCUS__; }
QLineEdit, QTextEdit, QPlainTextEdit, QSpinBox, QComboBox, QDoubleSpinBox { background: __INPUT__; border: 1px solid __BORDER__; border-radius: 7px; selection-background-color: __SELECTION__; selection-color: __SELECTED_TEXT__; padding: 8px 10px; color: __TEXT__; }
QLineEdit { placeholder-text-color: __MUTED__; }
QLineEdit:focus, QTextEdit:focus, QPlainTextEdit:focus, QSpinBox:focus, QComboBox:focus, QDoubleSpinBox:focus { border: 2px solid __FOCUS__; }
QLineEdit:disabled, QTextEdit:disabled, QPlainTextEdit:disabled, QSpinBox:disabled, QComboBox:disabled, QDoubleSpinBox:disabled { color: __DISABLED_TEXT__; background: __DISABLED__; border-color: __BORDER_MUTED__; }
QComboBox::drop-down { border: none; width: 24px; }
QComboBox::down-arrow { image: url("__CHEVRON_DOWN__"); width: 12px; height: 8px; }
QSpinBox::up-arrow, QDoubleSpinBox::up-arrow { image: url("__CHEVRON_UP__"); width: 10px; height: 7px; }
QSpinBox::down-arrow, QDoubleSpinBox::down-arrow { image: url("__CHEVRON_DOWN__"); width: 10px; height: 7px; }
QComboBox QAbstractItemView { background: __PANEL__; color: __TEXT__; selection-background-color: __SELECTION__; selection-color: __SELECTED_TEXT__; border: 1px solid __BORDER__; }
QCheckBox, QRadioButton { color: __TEXT__; spacing: 8px; background: transparent; }
QCheckBox:disabled, QRadioButton:disabled { color: __DISABLED_TEXT__; }
QCheckBox:focus, QRadioButton:focus { color: __FOCUS__; }
QCheckBox::indicator { width: 17px; height: 17px; }
QCheckBox::indicator:unchecked { border: 1px solid __MUTED__; background: __INPUT__; border-radius: 3px; }
QCheckBox::indicator:checked { border: 1px solid __EMBER__; background: __PRIMARY__; border-radius: 3px; image: url("__CHECKMARK__"); }
QCheckBox::indicator:disabled { border-color: __BORDER_MUTED__; background: __DISABLED__; }
QCheckBox::indicator:focus { border: 2px solid __FOCUS__; }
QListWidget, QTreeWidget { background: __PANEL__; alternate-background-color: __ALTERNATE__; color: __TEXT__; border: 1px solid __BORDER_MUTED__; border-radius: 8px; padding: 5px; }
QListWidget::item { padding: 9px 12px; }
QListWidget::item:hover, QTreeWidget::item:hover { background: __HOVER__; }
QListWidget::item:selected, QTreeWidget::item:selected { background: __SELECTION__; color: __SELECTED_TEXT__; }
QListWidget:focus, QTreeWidget:focus { border-color: __FOCUS__; }
QTabWidget::pane { border: 1px solid __BORDER__; border-radius: 8px; background: __PANEL__; }
QTabBar::tab { background: __RAISED__; color: __TEXT__; border: 1px solid __BORDER__; padding: 10px 16px; margin-right: 3px; font-weight: 600; }
QTabBar::tab:selected { background: __PRIMARY__; color: __SELECTED_TEXT__; border-color: __EMBER__; }
QTabBar::tab:hover:!selected { background: __HOVER__; }
QTabBar::tab:disabled { background: __DISABLED__; color: __DISABLED_TEXT__; border-color: __BORDER_MUTED__; }
QTabBar:focus { border: 1px solid __FOCUS__; }
QTableWidget, QTableView { background: __PANEL__; alternate-background-color: __ALTERNATE__; color: __TEXT__; border: none; gridline-color: __BORDER_MUTED__; outline: none; selection-background-color: __SELECTION__; selection-color: __SELECTED_TEXT__; font-size: 11px; }
QTableWidget::item { padding: 8px 10px; border-bottom: 1px solid __BORDER_MUTED__; }
QTableWidget::item:selected, QTableView::item:selected { background: __SELECTION__; color: __SELECTED_TEXT__; }
QTableWidget::item:focus, QTableView::item:focus { border: 1px solid __FOCUS__; }
QHeaderView { background: __RAISED__; }
QHeaderView::section { background: __RAISED__; color: __ACCENT__; border: 0; border-bottom: 1px solid __BORDER__; padding: 11px 8px; font-weight: 700; font-size: 10px; }
QTableCornerButton::section { background: __RAISED__; border: none; }
QScrollBar:vertical { width: 11px; background: __SIDEBAR__; }
QScrollBar::handle:vertical { background: __BORDER__; border-radius: 4px; min-height: 28px; }
QScrollBar:horizontal { height: 11px; background: __SIDEBAR__; }
QScrollBar::handle:horizontal { background: __BORDER__; border-radius: 4px; min-width: 28px; }
QScrollBar::handle:hover { background: __EMBER__; }
QScrollBar::add-line, QScrollBar::sub-line { height: 0px; width: 0px; }
QScrollArea { background: transparent; border: none; }
QSplitter::handle { background: __WINDOW__; width: 10px; }
QSplitter::handle:hover { background: __BORDER__; }
QStatusBar { color: __MUTED__; background: __SIDEBAR__; border-top: 1px solid __BORDER_MUTED__; font-size: 10px; }
QStatusBar::item { border: none; }
QMessageBox { background: __PANEL__; }
QMenuBar { background: __SIDEBAR__; border-bottom: 1px solid __BORDER_MUTED__; }
QMenuBar::item { background: transparent; padding: 6px 10px; }
QMenuBar::item:selected { background: __SELECTION__; color: __SELECTED_TEXT__; }
QMenu { background: __PANEL__; border: 1px solid __BORDER__; padding: 4px; }
QMenu::item { padding: 7px 24px; }
QMenu::item:selected { background: __SELECTION__; color: __SELECTED_TEXT__; }
QMenu::item:disabled { color: __DISABLED_TEXT__; }
QMenu::separator { height: 1px; background: __BORDER_MUTED__; margin: 4px 8px; }
QGroupBox { background: __PANEL__; border: 1px solid __BORDER__; border-radius: 8px; margin-top: 12px; padding-top: 10px; }
QGroupBox::title { color: __ACCENT__; subcontrol-origin: margin; left: 10px; padding: 0 5px; }
QProgressBar { background: __INPUT__; border: 1px solid __BORDER__; border-radius: 5px; color: __TEXT__; text-align: center; }
QProgressBar::chunk { background: __PRIMARY__; border-radius: 4px; }
QLabel#artworkBanner { background-color: __SIDEBAR__; border: 1px solid __BORDER__; border-radius: 10px; }
QLabel#brandMark { background-color: transparent; border: none; }
QDialog QLineEdit, QDialog QComboBox, QDialog QListWidget { border-color: __BORDER__; }
QDialog QLineEdit:focus, QDialog QComboBox:focus, QDialog QListWidget:focus { border-color: __FOCUS__; }
"""
