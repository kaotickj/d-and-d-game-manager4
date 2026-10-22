"""The real Grimoire dialog saves reviewed choices without inference."""
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
try:
    from PyQt6.QtWidgets import QApplication
    from dndgm4.spell_progression_ui import SpellProgressionDialog
except ImportError:
    QApplication = None

from dndgm4.models import Creature
from dndgm4.storage import CreatureRepository


@unittest.skipIf(QApplication is None, "Qt is optional")
class SpellProgressionUITests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_save_requires_ack_and_keeps_unsaved_edit_on_stale_record(self):
        with TemporaryDirectory() as temporary:
            repo = CreatureRepository(Path(temporary) / "library.sqlite3")
            creature = repo.save(Creature(name="Aria", character_class="Wizard", level=5, intelligence=18,
                                         sheet_json=json.dumps({"background": "Keep"})))
            dialog = SpellProgressionDialog(repo, creature.id)
            dialog.level_choice.setCurrentIndex(1)
            dialog.editors["spellbook"].setPlainText("Magic Missile")
            dialog.editors["prepared"].setPlainText("Magic Missile")
            dialog.save_reviewed()
            self.assertIsNone(dialog.saved_creature)
            self.assertIn("Review", dialog.status.text())
            dialog.review.setChecked(True)
            dialog.save_reviewed()
            self.assertIsNotNone(dialog.saved_creature)
            self.assertEqual(json.loads(repo.get(creature.id).sheet_json)["background"], "Keep")
            with repo._connection() as db:
                db.execute("UPDATE creatures SET notes='changed elsewhere' WHERE id=?", (creature.id,))
            dialog.editors["prepared"].setPlainText("Magic Missile\nMagic Missile")
            dialog.review.setChecked(True)
            dialog.save_reviewed()
            self.assertIn("changed after", dialog.status.text())
            self.assertEqual(dialog.editors["prepared"].toPlainText(), "Magic Missile\nMagic Missile")
            dialog.close()

    def test_switching_levels_preserves_draft_and_disables_wrong_groups(self):
        with TemporaryDirectory() as temporary:
            repo = CreatureRepository(Path(temporary) / "library.sqlite3")
            creature = repo.save(Creature(name="Song", character_class="Bard", level=2, charisma=16))
            dialog = SpellProgressionDialog(repo, creature.id)
            dialog.editors["known"].setPlainText("Light")
            dialog.level_choice.setCurrentIndex(1)
            dialog.level_choice.setCurrentIndex(0)
            self.assertEqual(dialog.editors["known"].toPlainText(), "Light")
            self.assertFalse(dialog.tabs.isTabEnabled(1))
            self.assertTrue(dialog.tabs.isTabEnabled(0))
            dialog.close()
