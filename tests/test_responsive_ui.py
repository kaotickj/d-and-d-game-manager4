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

    def test_default_window_ten_percent_larger_and_sidebar_wider(self):
        from PyQt6.QtWidgets import QScrollArea, QPushButton, QFrame
        from dndgm4.storage import CreatureRepository
        from dndgm4.ui import MainWindow
        with TemporaryDirectory() as folder:
            window = MainWindow(CreatureRepository(Path(folder) / "sidebar.sqlite3"))
            window.show()
            self.app.processEvents()
            # Exactly 10% larger than the 1410 x 840 v0.7.2 default.
            self.assertEqual(window.width(), 1551)
            self.assertEqual(window.height(), 924)
            # Keep the previously supported compact window sizes.
            self.assertEqual(window.minimumWidth(), 830)
            self.assertEqual(window.minimumHeight(), 540)
            sidebar = window.findChild(QScrollArea, "sidebarScroll")
            self.assertIsNotNone(sidebar)
            self.assertEqual(sidebar.width(), 326)
            self.assertEqual(window.width() - sidebar.width(), 1225)
            # The navigation stays visible alongside the expanded DM assistant.
            button_labels = {widget.text() for widget in
                             sidebar.findChildren(QPushButton)}
            for label in ("Nonplayer Characters",
                          "RPG NAME GENIE  /  Generate Names",
                          "The Scribe  /  DM Assistant", "+  New Monster"):
                self.assertIn(label, button_labels)
            self.assertEqual(window.hero_banner.height(), 166)
            # The 10% enlargement is of the outer window only; artwork,
            # fonts, and existing navigation/button dimensions must not scale.
            self.assertEqual(
                sidebar.findChildren(QPushButton, "navButton")[0].font().pointSize(),
                window.nav[None].font().pointSize())
            tiles = window.findChildren(QFrame, "statChip")
            self.assertEqual(len(tiles), 6)
            for tile in tiles:
                self.assertEqual(tile.width(), tile.height())
            window.close()

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

    def test_six_ability_tiles_stay_square_and_legible_when_resized(self):
        from PyQt6.QtWidgets import QFrame, QLabel, QScrollArea
        from PyQt6.QtCore import Qt
        from dndgm4.models import Creature
        from dndgm4.storage import CreatureRepository
        from dndgm4.ui import MainWindow
        with TemporaryDirectory() as folder:
            library = CreatureRepository(Path(folder) / "scores.sqlite3")
            record = library.save(Creature(
                name="Square Score Test", kind="pc",
                strength=18, dexterity=16, constitution=14,
                intelligence=12, wisdom=10, charisma=8,
            ))
            window = MainWindow(library)
            for width, height in ((895, 640), (1200, 780), (1380, 840),
                                  (1490, 920), (800, 540)):
                with self.subTest(width=width, height=height):
                    window.resize(width, height)
                    window.show()
                    self.app.processEvents()
                    for row in range(window.table.rowCount()):
                        if (window.table.item(row, 0).data(
                                Qt.ItemDataRole.UserRole
                            ) == record.id):
                            window.table.selectRow(row)
                            break
                    self.app.processEvents()
                    tiles = window.findChildren(QFrame, "statChip")
                    self.assertEqual(len(tiles), 6)
                    self.assertIsInstance(window.preview_scroll, QScrollArea)
                    self.assertEqual(window.preview_scroll.objectName(),
                                     "recordPreviewScroll")
                    grid = window.ability_score_grid
                    self.assertEqual(grid.height(), 2 * grid._edge + grid.GAP)
                    self.assertGreaterEqual(grid._edge, 80)
                    self.assertLessEqual(grid._edge, 112)
                    for tile in tiles:
                        self.assertEqual(tile.width(), tile.height())
                        self.assertEqual(tile.size().width(), grid._edge)
                        captions = tile.findChildren(QLabel)
                        self.assertEqual(len(captions), 2)
                        for label in captions:
                            self.assertGreater(label.height(), 0)
                            self.assertGreaterEqual(label.y(), 0)
                            self.assertLessEqual(label.y() + label.height(), tile.height())
                            self.assertGreaterEqual(label.width(),
                                label.fontMetrics().horizontalAdvance(label.text()))
                    self.assertEqual(window.hero_banner.height(), 166)
            self.assertEqual(
                {k: v.text() for k, v in window.stat_values.items()},
                {"strength": "18", "dexterity": "16", "constitution": "14",
                 "intelligence": "12", "wisdom": "10", "charisma": "8"},
            )
            window.close()

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
