"""Regression tests for the banner's aspect ratio and responsive dashboard."""
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

    def test_no_cropping_at_fullscreen_and_small_widths(self):
        from dndgm4.artwork import CoverArtLabel
        banner=CoverArtLabel("app_banner.jpg",height=170)
        self.assertFalse(banner.source.isNull())
        for width,height in ((470,150),(850,170),(1600,200),(2100,238)):
            with self.subTest(width=width):
                banner.resize(width,height)
                self.app.processEvents()
                banner.update_picture()
                displayed=banner.pixmap()
                self.assertFalse(displayed.isNull())
                self.assertLessEqual(displayed.width(),width)
                self.assertLessEqual(displayed.height(),height)
                # The entire source is scaled, so aspect ratio is retained.
                ratio=displayed.width()/displayed.height()
                original=banner.source.width()/banner.source.height()
                self.assertAlmostEqual(ratio,original,delta=.08)
        banner.close()

    def test_compact_window_uses_stacked_preview_and_can_hide_art(self):
        from PyQt6.QtCore import Qt
        from PyQt6.QtWidgets import QScrollArea, QPushButton
        from dndgm4.ui import MainWindow
        from dndgm4.storage import CreatureRepository
        with TemporaryDirectory() as d:
            window=MainWindow(CreatureRepository(Path(d)/"test.sqlite3"))
            window.resize(895,640)
            window.show()
            self.app.processEvents()
            self.assertEqual(window.library_splitter.orientation(),
                             Qt.Orientation.Vertical)
            self.assertIsInstance(window.workspace_scroll,QScrollArea)
            self.assertIsNotNone(window.findChild(QScrollArea,"sidebarScroll"))
            self.assertTrue(window.hero_banner.isVisible())
            self.assertTrue(window.full_art_button.isEnabled())
            self.assertEqual(window.table.columnCount(),6)
            window.toggle_banner()
            self.app.processEvents()
            self.assertFalse(window.hero_banner.isVisible())
            self.assertEqual(window.collapse_art_button.text(),"Show banner")
            window.toggle_banner()
            self.assertTrue(window.hero_banner.isVisible())
            self.assertFalse(any(
                b.text()=="Generate Names"
                for b in window.findChildren(QPushButton)
            ))
            window.resize(1490,920)
            self.app.processEvents()
            self.assertEqual(window.library_splitter.orientation(),
                             Qt.Orientation.Horizontal)
            displayed=window.hero_banner.pixmap()
            self.assertLessEqual(displayed.width(),window.hero_banner.width())
            self.assertLessEqual(displayed.height(),window.hero_banner.height())
            window.close()


if __name__ == "__main__":
    unittest.main()
