"""Offscreen artwork and main-window layout regressions."""
from importlib.util import find_spec
from pathlib import Path
from tempfile import TemporaryDirectory
import os
import unittest

from importlib.resources import files


@unittest.skipUnless(find_spec("PyQt6") is not None, "PyQt6 not installed")
class FantasyArtworkTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        from PyQt6.QtWidgets import QApplication
        from dndgm4.theme import apply_theme
        cls.app = QApplication.instance() or QApplication([])
        apply_theme(cls.app)

    def test_artwork_ships_inside_package_and_is_readable(self):
        from dndgm4.artwork import load_artwork, window_icon
        for name in ("app_banner.jpg", "dragon_crest.png", "name_genie_crest.png"):
            with self.subTest(name=name):
                self.assertTrue(files("dndgm4").joinpath("assets", name).is_file())
                image = load_artwork(name)
                self.assertFalse(image.isNull())
                self.assertGreater(image.width(), 100)
                self.assertGreater(image.height(), 100)
        self.assertTrue(files("dndgm4").joinpath("assets", "app_icon.ico").is_file())
        self.assertFalse(window_icon().isNull())

    def test_main_banner_and_sidebar_only_name_genie(self):
        from PyQt6.QtWidgets import QPushButton
        from dndgm4.storage import CreatureRepository
        from dndgm4.ui import MainWindow
        with TemporaryDirectory() as folder:
            window = MainWindow(CreatureRepository(Path(folder) / "empty.sqlite3"))
            window.show()
            self.app.processEvents()
            self.assertFalse(window.hero_banner.pixmap().isNull())
            # Responsive artwork height replaces the old fixed 166px crop.
            self.assertGreaterEqual(window.hero_banner.height(), 142)
            self.assertLessEqual(window.hero_banner.height(), 238)
            rendered = window.hero_banner.pixmap()
            self.assertLessEqual(rendered.width(), window.hero_banner.width())
            self.assertLessEqual(rendered.height(), window.hero_banner.height())
            self.assertFalse(window.windowIcon().isNull())
            buttons = [
                b for b in window.findChildren(QPushButton)
                if "Generate Names" in b.text()
            ]
            # No longer duplicated in the hero: the ONLY main-window control
            # is the explicit, keyboard-accessible sidebar button.
            self.assertEqual(len(buttons), 1)
            self.assertTrue(buttons[0].isEnabled())
            self.assertIn("RPG NAME GENIE", buttons[0].text())
            window.close()

    def test_naming_chamber_uses_dedicated_crest(self):
        from dndgm4.name_ui import NamePickerDialog
        dialog = NamePickerDialog(standalone=True)
        self.assertFalse(dialog.name_genie_art.pixmap().isNull())
        self.assertFalse(dialog.windowIcon().isNull())
        self.assertTrue(dialog.list_widget.count() > 0)
        dialog.close()


if __name__ == "__main__":
    unittest.main()
