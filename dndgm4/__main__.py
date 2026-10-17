"""Launch Dungeons & Dragons Game Manager 4."""
import sys

from .storage import CreatureRepository, default_database_path


def main() -> int:
    from PyQt6.QtWidgets import QApplication, QMessageBox
    from .theme import apply_theme
    from .ui import MainWindow

    app = QApplication(sys.argv)
    app.setApplicationName("D&D Game Manager 4")
    app.setOrganizationName("Kaotick Jay")
    apply_theme(app)
    try:
        library = CreatureRepository(default_database_path())
    except Exception as error:
        QMessageBox.critical(None, "Unable to open library", str(error))
        return 1
    window = MainWindow(library)
    window.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
