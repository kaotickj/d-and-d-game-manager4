"""The generator only rolls explicitly and hands off a reviewed draft."""
from importlib.util import find_spec
import os
from random import Random
import unittest
from unittest.mock import patch

from dndgm4.encounter_generator import generate_encounter


@unittest.skipUnless(find_spec("PyQt6") is not None, "PyQt6 is not installed")
class EncounterGeneratorUiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        from PyQt6.QtWidgets import QApplication
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        from dndgm4.encounter_ui import EncounterGeneratorDialog
        self.dialog = EncounterGeneratorDialog([])
        self.draft = generate_encounter([], source="original", quantity="2", rng=Random(4))

    def tearDown(self):
        self.dialog.close()
        self.dialog.deleteLater()
        self.app.processEvents()

    def roll(self):
        with patch("dndgm4.encounter_ui.generate_encounter", return_value=self.draft) as generate:
            self.dialog.roll_button.click()
        generate.assert_called_once()

    def test_empty_library_chooses_original_but_never_rolls_on_open_or_edit(self):
        self.assertEqual(self.dialog.source.currentData(), "original")
        self.assertIsNone(self.dialog.draft)
        self.assertFalse(self.dialog.scene_button.isEnabled())
        with patch("dndgm4.encounter_ui.generate_encounter") as generate:
            self.dialog.quantity.setText("2d6")
            self.dialog.environment.setCurrentText("Road")
            self.dialog.roll_initiative.setChecked(True)
            self.dialog.reject()
        generate.assert_not_called()
        self.assertIsNone(self.dialog.result_draft)
        self.assertEqual(self.dialog.result_action, "")

    def test_explicit_roll_populates_stats_and_audit_without_accepting(self):
        self.roll()
        self.assertIs(self.dialog.draft, self.draft)
        self.assertIsNone(self.dialog.result_draft)
        self.assertEqual(self.dialog.roster.rowCount(), 2)
        self.assertIn("Computed baseline:", self.dialog.details.toPlainText())
        self.assertIn("Attacks:", self.dialog.details.toPlainText())
        self.assertIn("HP dice", self.dialog.roll_log.toPlainText())
        self.assertTrue(self.dialog.scene_button.isEnabled())
        self.dialog.cancel_button.click()
        self.assertIsNone(self.dialog.result_draft)

    def test_scene_action_returns_edited_draft_only(self):
        from PyQt6.QtWidgets import QDialog
        self.roll()
        self.dialog.title.setText("The Reed Bridge")
        self.dialog.read_aloud.setPlainText("A lantern floats above the reeds.")
        self.dialog.dm_notes.setPlainText("DM secret: the lantern marks a safe path.")
        self.dialog.motive.setText("The group needs help finding shelter.")
        self.assertIn("The group needs help", self.dialog.details.toPlainText())
        self.dialog.scene_button.click()
        self.assertEqual(self.dialog.result(), QDialog.DialogCode.Accepted)
        self.assertEqual(self.dialog.result_action, "scene")
        self.assertEqual(self.dialog.result_draft.title, "The Reed Bridge")
        self.assertIn("safe path", self.dialog.result_draft.dm_notes)
        self.assertEqual(self.dialog.result_draft.read_aloud, "A lantern floats above the reeds.")

    def test_battle_action_preserves_fighter_instances_without_starting_combat(self):
        self.roll()
        self.dialog.battle_button.click()
        self.assertEqual(self.dialog.result_action, "battle")
        self.assertEqual(self.dialog.result_draft.fighters, self.draft.fighters)
        self.assertTrue(all(fighter.initiative is None for fighter in self.draft.fighters))
        self.assertIn("adds creatures", self.dialog.status.text())

    def test_scribe_handoff_rejects_oversize_context_and_keeps_preview_open(self):
        self.roll()
        self.dialog.dm_notes.setPlainText("x" * 6001)
        self.dialog.scribe_button.click()
        self.assertIsNone(self.dialog.result_draft)
        self.assertIn("No details were omitted", self.dialog.status.text())
        self.dialog.dm_notes.setPlainText("Prepare a social approach.")
        self.dialog.scribe_button.click()
        self.assertEqual(self.dialog.result_action, "scribe")

    def test_failed_roll_disables_handoff_without_partial_results(self):
        self.roll()
        with patch("dndgm4.encounter_ui.generate_encounter", side_effect=ValueError("Invalid count")):
            self.dialog.roll_button.click()
        self.assertIsNone(self.dialog.draft)
        self.assertFalse(self.dialog.scene_button.isEnabled())
        self.assertIsNone(self.dialog.result_draft)
        self.assertIn("Invalid count", self.dialog.status.text())


if __name__ == "__main__":
    unittest.main()
