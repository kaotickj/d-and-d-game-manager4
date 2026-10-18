"""Name Genie is visible and usable even without any saved characters."""
from importlib.util import find_spec
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
import os
import unittest


@unittest.skipUnless(find_spec("PyQt6") is not None, "PyQt6 not installed")
class NameGenieSmokeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        from PyQt6.QtWidgets import QApplication
        from dndgm4.theme import apply_theme
        cls.app = QApplication.instance() or QApplication([])
        apply_theme(cls.app)

    def test_standalone_namegen_works_without_records(self):
        from PyQt6.QtWidgets import QApplication
        from dndgm4.roll_ui import CharacterCreatorDialog
        from dndgm4.name_ui import NamePickerDialog
        from dndgm4.namegen import NameEngine
        import random
        dialog = NamePickerDialog(
            race="Lizardfolk", monster=True, standalone=True,
            engine=NameEngine("/nonexistent/v24.sqlite", random.Random(5))
        )
        self.assertEqual(dialog.use_button.text(), "Copy Selected Name")
        self.assertTrue(dialog.list_widget.count() > 0)
        selected = dialog.list_widget.currentItem().text()
        dialog.accept_name()
        self.assertEqual(QApplication.clipboard().text(), selected)
        self.assertEqual(dialog.selected_name, selected)
        dialog.character_class.setCurrentText("Ranger")
        dialog.culture.setCurrentText("Nordic")
        dialog.tone.setCurrentText("Gritty")
        dialog.generate()
        self.assertTrue(dialog.list_widget.count() > 0)
        dialog.close()

    def test_main_screen_has_visible_namegen_actions(self):
        from PyQt6.QtWidgets import QPushButton
        from dndgm4.storage import CreatureRepository
        from dndgm4.ui import MainWindow
        with TemporaryDirectory() as folder:
            window = MainWindow(CreatureRepository(Path(folder) / "empty.sqlite3"))
            self.assertEqual(window.table.rowCount(), 0)
            buttons = [b for b in window.findChildren(QPushButton)
                       if "Generate Names" in b.text()]
            # The only Generate Names action is in the sidebar, not the hero.
            self.assertEqual(len(buttons), 1)
            self.assertIn("RPG NAME GENIE", buttons[0].text())
            self.assertTrue(all(button.isEnabled() for button in buttons))
            with patch("dndgm4.ui.NamePickerDialog") as picker:
                window.open_names()
                picker.assert_called_once_with(race="Human", standalone=True, parent=window)
                picker.return_value.exec.assert_called_once_with()
            window.close()


if __name__ == "__main__":
    unittest.main()
