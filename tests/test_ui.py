"""Headless Qt integration checks. Skip on storage-only CI without PyQt6."""
from importlib.util import find_spec
from pathlib import Path
from tempfile import TemporaryDirectory
import os
import unittest


@unittest.skipUnless(find_spec("PyQt6") is not None, "PyQt6 is not installed")
class UiSmokeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        from PyQt6.QtWidgets import QApplication
        from dndgm4.theme import apply_theme
        cls.app = QApplication.instance() or QApplication([])
        apply_theme(cls.app)

    def setUp(self):
        from dndgm4.storage import CreatureRepository
        from dndgm4.ui import MainWindow
        self.tmp = TemporaryDirectory()
        self.repo = CreatureRepository(Path(self.tmp.name) / "library.sqlite3")
        self.window = MainWindow(self.repo)

    def tearDown(self):
        self.window.close()
        self.tmp.cleanup()

    def test_library_preview_filter_and_archive(self):
        from dndgm4.models import Creature
        self.assertFalse(self.window.edit_button.isEnabled())
        record = self.repo.save(Creature(name="Sir Rowan", kind="pc", strength=17))
        self.window.refresh()
        self.assertEqual(self.window.table.rowCount(), 1)
        self.assertFalse(self.window.edit_button.isEnabled())
        self.window.table.selectRow(0)
        self.assertTrue(self.window.edit_button.isEnabled())
        self.assertEqual(self.window.preview_title.text(), "Sir Rowan")
        self.assertEqual(self.window.stat_values["strength"].text(), "17")
        self.window.toggle_archive()
        self.assertEqual(self.window.table.rowCount(), 0)
        self.window.show_archived.setChecked(True)
        self.assertEqual(self.window.table.rowCount(), 1)
        self.window.table.selectRow(0)
        self.assertEqual(self.window.archive_button.text(), "Restore")
        self.window.toggle_archive()
        self.assertFalse(self.repo.get(record.id).archived)
        self.window.change_section("monster")
        self.assertEqual(self.window.table.rowCount(), 0)

    def test_editor_retains_fields(self):
        from dndgm4.models import Creature
        from dndgm4.ui import CreatureEditor
        dialog = CreatureEditor(Creature(name="Goblin", kind="monster", strength=8))
        dialog.name.setText("Goblin Warlord")
        dialog.abilities["strength"].setValue(15)
        dialog.save()
        self.assertEqual(dialog.result_creature.name, "Goblin Warlord")
        self.assertEqual(dialog.result_creature.strength, 15)
        self.assertEqual(dialog.result_creature.kind, "monster")
        dialog.close()


if __name__ == "__main__":
    unittest.main()
