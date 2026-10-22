"""Launch Dungeons & Dragons Game Manager 4."""
import sys

from .storage import CreatureRepository, default_database_path


def open_startup_library(settings):
    """Let a missing or damaged selected library be recovered from the GUI."""
    from pathlib import Path
    from PyQt6.QtCore import Qt
    from PyQt6.QtWidgets import QFileDialog, QMessageBox
    selected = str(settings.value("library/path", "") or "")
    while True:
        try:
            if selected and not Path(selected).is_file():
                raise ValueError(f"Selected library is missing: {selected}")
            library = CreatureRepository(selected or default_database_path())
        except Exception as error:
            message = QMessageBox()
            message.setIcon(QMessageBox.Icon.Critical)
            message.setWindowTitle("Unable to Open Library")
            message.setTextFormat(Qt.TextFormat.PlainText)
            message.setText(str(error))
            message.setInformativeText("Choose another saved library to continue.")
            choose = message.addButton("Choose Library…", QMessageBox.ButtonRole.ActionRole)
            default = (message.addButton("Use Default Library", QMessageBox.ButtonRole.ActionRole)
                       if selected else None)
            message.addButton(QMessageBox.StandardButton.Cancel)
            message.exec()
            if message.clickedButton() is choose:
                selected, _ = QFileDialog.getOpenFileName(
                    None, "Choose Library", str(default_database_path().parent),
                    "SQLite library (*.sqlite3)")
                if not selected:
                    return None
            elif default is not None and message.clickedButton() is default:
                selected = ""
            else:
                return None
        else:
            if selected:
                settings.setValue("library/path", str(Path(selected).resolve()))
            else:
                settings.remove("library/path")
            return library


def main() -> int:
    from PyQt6.QtWidgets import QApplication, QMessageBox
    from PyQt6.QtCore import QSettings
    from .theme import apply_theme
    from .artwork import window_icon
    from .ui import MainWindow

    app = QApplication(sys.argv)
    # Character/NPC/Monster Forge uses nested child dialogs, including the
    # Scribe's Use Draft flow. Only an explicit main-window close may quit the
    # program. Qt's automatic last-window detection is unsafe in this stack.
    app.setQuitOnLastWindowClosed(False)
    app.setApplicationName("D&D Game Manager 4")
    app.setOrganizationName("Kaotick Jay")
    app.setWindowIcon(window_icon())
    apply_theme(app)
    if "--smoke-test" in sys.argv:
        import argparse
        from .packaged_smoke import run_packaged_smoke
        parser = argparse.ArgumentParser(description="Run isolated packaged application acceptance checks.")
        parser.add_argument("--smoke-test", required=True)
        args = parser.parse_args(sys.argv[1:])
        return run_packaged_smoke(args.smoke_test)
    library = open_startup_library(QSettings("Kaotick Jay", "DnDGameManager4"))
    if library is None:
        return 1
    window = MainWindow(library)
    window.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
