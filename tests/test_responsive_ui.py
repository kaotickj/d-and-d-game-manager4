"""Regression tests: classic banner restored; ability scores remain responsive."""
from importlib.util import find_spec
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest


@unittest.skipUnless(find_spec("PyQt6") is not None, "PyQt6 unavailable")
class ResponsiveLayoutTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        from PyQt6.QtWidgets import QApplication
        from dndgm4.theme import apply_theme
        cls.app = QApplication.instance() or QApplication([])
        apply_theme(cls.app)

    def test_classic_banner_fills_its_original_fixed_height(self):
        from dndgm4.artwork import CoverArtLabel
        banner = CoverArtLabel("app_banner.jpg", height=166)
        self.assertFalse(banner.source.isNull())
        for width in (470, 850, 1200, 1600, 2100):
            with self.subTest(width=width):
                banner.resize(width, 166)
                self.app.processEvents()
                banner.update_picture()
                rendered = banner.pixmap()
                self.assertFalse(rendered.isNull())
                self.assertEqual(banner.height(), 166)
                self.assertEqual(rendered.size(), banner.size())
        banner.close()

    def test_preview_stacks_without_changing_original_dashboard_art(self):
        from PyQt6.QtCore import Qt
        from PyQt6.QtWidgets import QScrollArea, QPushButton
        from dndgm4.ui import MainWindow
        from dndgm4.models import Creature
        from dndgm4.storage import CreatureRepository
        with TemporaryDirectory() as folder:
            repo = CreatureRepository(Path(folder) / "test.sqlite3")
            hero = repo.save(Creature(
                name="Six Abilities", kind="pc", strength=18,
                dexterity=16, constitution=14, intelligence=12,
                wisdom=10, charisma=8,
            ))
            window = MainWindow(repo)
            window.resize(895, 640)
            window.show()
            self.app.processEvents()
            self.assertEqual(window.library_splitter.orientation(), Qt.Orientation.Vertical)
            self.assertIsInstance(window.workspace_scroll, QScrollArea)
            self.assertEqual(window.hero_banner.height(), 166)
            self.assertFalse(any(
                b.text() in ("Hide banner", "Show banner", "View full artwork")
                for b in window.findChildren(QPushButton)
            ))
            self.assertFalse(window.hero_banner.pixmap().isNull())
            for row in range(window.table.rowCount()):
                if window.table.item(row, 0).data(Qt.ItemDataRole.UserRole) == hero.id:
                    window.table.selectRow(row)
                    break
            self.app.processEvents()
            expected = {
                "strength": "18", "dexterity": "16",
                "constitution": "14", "intelligence": "12",
                "wisdom": "10", "charisma": "8",
            }
            self.assertEqual({a: w.text() for a, w in window.stat_values.items()}, expected)
            window.resize(1490, 920)
            self.app.processEvents()
            self.assertEqual(window.library_splitter.orientation(), Qt.Orientation.Horizontal)
            self.assertEqual(window.hero_banner.height(), 166)
            self.assertEqual({a: w.text() for a, w in window.stat_values.items()}, expected)
            self.assertEqual(window.table.columnCount(), 6)
            window.close()


if __name__ == "__main__":
    unittest.main()
