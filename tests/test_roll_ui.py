"""Offscreen Qt tests for the Dice Eliminator and Character Forge."""
from importlib.util import find_spec
from pathlib import Path
from tempfile import TemporaryDirectory
import os
import unittest


@unittest.skipUnless(find_spec("PyQt6") is not None, "PyQt6 not installed")
class RollingUiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        from PyQt6.QtWidgets import QApplication
        from dndgm4.theme import apply_theme
        cls.app = QApplication.instance() or QApplication([])
        apply_theme(cls.app)

    def test_dice_tray_and_custom_expression(self):
        from dndgm4.roll_ui import DiceDialog
        dialog = DiceDialog()
        dialog.expression.setText("4d6kh3")
        dialog.roll_custom()
        self.assertIn("4d6kh3", dialog.history.toPlainText())
        self.assertTrue(dialog.last_result.text().startswith("Result:"))
        dialog.clear_history()
        self.assertFalse(dialog.history.toPlainText())
        dialog.close()

    def test_character_creator_saves_rolls_to_library(self):
        from dndgm4.roll_ui import CharacterCreatorDialog
        from dndgm4.storage import CreatureRepository
        dialog = CharacterCreatorDialog()
        self.assertFalse(dialog.score_inputs["strength"].isEnabled())
        dialog.name.setText("Arden")
        dialog.race.setCurrentText("Elf")
        dialog.character_class.setCurrentText("Ranger")
        dialog.roll_all()
        dialog.save_character()
        created = dialog.result_creature
        self.assertEqual(created.name, "Arden")
        self.assertEqual(created.race_type, "Elf")
        self.assertEqual(created.kind, "pc")
        self.assertIn("4d6kh3", created.notes)
        with TemporaryDirectory() as temp:
            repo = CreatureRepository(Path(temp) / "test.sqlite3")
            saved = repo.save(created)
            self.assertEqual(repo.get(saved.id).race_type, "Elf")
        dialog.close()

    def test_manual_scores_and_navigator(self):
        from dndgm4.roll_ui import CharacterCreatorDialog
        from dndgm4.storage import CreatureRepository
        from dndgm4.ui import MainWindow
        from dndgm4.models import Creature
        dialog = CharacterCreatorDialog()
        dialog.method.setCurrentIndex(2)
        self.assertTrue(dialog.score_inputs["strength"].isEnabled())
        dialog.score_inputs["strength"].setValue(18)
        dialog.name.setText("Sage")
        dialog.save_character()
        self.assertEqual(dialog.result_creature.strength, 18)
        dialog.close()
        with TemporaryDirectory() as temp:
            repo = CreatureRepository(Path(temp) / "test.sqlite3")
            window = MainWindow(repo)
            # Integration hooks must be present and functional after UI refresh.
            self.assertTrue(callable(window.open_dice))
            self.assertTrue(callable(window.create))
            window.close()


if __name__ == "__main__":
    unittest.main()
