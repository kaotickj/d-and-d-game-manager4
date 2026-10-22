"""Multiclass UI requires explicit history, choices and exact-preview approval."""
from dataclasses import replace
from importlib.util import find_spec
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch


@unittest.skipUnless(find_spec("PyQt6") is not None, "PyQt6 is not installed")
class MulticlassUiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        from PyQt6.QtWidgets import QApplication
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        from dndgm4.models import Creature
        from dndgm4.storage import CreatureRepository
        self.temp = TemporaryDirectory()
        self.repo = CreatureRepository(Path(self.temp.name) / "library.sqlite3")
        self.hero = self.repo.save(Creature(name="Élara", character_class="Fighter", level=1,
            race_type="Elf", constitution=14, intelligence=10, strength=16, dexterity=14, max_hit_points=12,
            sheet_json=json.dumps({"class": "Fighter", "skills_half_ranks": {}, "feats": [],
                                   "inventory": [{"name": "Sword"}], "spellbook": {"keep": True}, "background": "A saved story"})))
        self.dialogs = []

    def tearDown(self):
        for dialog in self.dialogs:
            dialog.close()
            dialog.deleteLater()
        self.app.processEvents()
        self.temp.cleanup()

    def dialog(self, confirmed=False):
        from dndgm4.multiclass import establish_history
        from dndgm4.multiclass_ui import MulticlassDialog
        if confirmed:
            self.hero = self.repo.save(establish_history(self.hero, {"Fighter": 1}, review_ack=True,
                no_racial_hd_ack=True, review_notes="Existing class history and restrictions reviewed"))
        dialog = MulticlassDialog(self.repo, self.hero.id)
        self.dialogs.append(dialog)
        return dialog

    def fill_level(self, dialog, selected="Wizard"):
        dialog.selected_class.setCurrentText(selected)
        dialog.hp_roll.setValue(3)
        dialog.class_notes.setPlainText("Reviewed class features and interactions")
        dialog.spell_notes.setPlainText("Reviewed separate spell list and daily progression")
        dialog.restriction_notes.setText("DM confirms XP/milestone, alignment, prerequisites and class re-entry")
        dialog.advance_ack.setChecked(True)

    def test_history_requires_review_and_exact_preview_approval_before_saving(self):
        dialog = self.dialog()
        self.assertFalse(dialog.preview_history())
        self.assertEqual(self.repo.get(self.hero.id), self.hero)
        dialog.history_notes.setText("DM confirmed existing Fighter1 and no racial HD/LA")
        dialog.history_ack.setChecked(True)
        dialog.no_racial_ack.setChecked(True)
        self.assertTrue(dialog.preview_history())
        self.assertIn("Total character level: 1 → 1", dialog.preview_text.toPlainText())
        self.assertEqual(self.repo.get(self.hero.id), self.hero)
        self.assertFalse(dialog.save_reviewed())
        dialog.save_ack.setChecked(True)
        self.assertTrue(dialog.save_reviewed())
        saved = self.repo.get(self.hero.id)
        self.assertEqual(json.loads(saved.sheet_json)["class_levels"], {"Fighter": 1})
        self.assertEqual(saved.level, 1)
        self.assertEqual(saved.max_hit_points, 12)

    def test_level_preview_and_save_preserve_unrelated_data_and_emit_saved_record(self):
        dialog = self.dialog(confirmed=True)
        self.fill_level(dialog)
        records = []
        dialog.record_saved.connect(records.append)
        self.assertTrue(dialog.preview_level())
        self.assertEqual(self.repo.get(self.hero.id).level, 1)
        self.assertIn("Fighter 1 / Wizard 1", dialog.preview_text.toPlainText())
        self.assertIn("Scribe Scroll", dialog.preview_text.toPlainText())
        self.assertFalse(dialog.save_button.isEnabled())
        dialog.save_ack.setChecked(True)
        self.assertTrue(dialog.save_reviewed())
        saved = self.repo.get(self.hero.id)
        self.assertEqual(saved.level, 2)
        self.assertEqual(json.loads(saved.sheet_json)["inventory"], [{"name": "Sword"}])
        self.assertEqual(json.loads(saved.sheet_json)["spellbook"], {"keep": True})
        self.assertEqual(records, [saved])
        self.assertEqual(dialog.result_creature, saved)

    def test_input_edits_invalidate_previously_reviewed_preview(self):
        dialog = self.dialog(confirmed=True)
        self.fill_level(dialog)
        self.assertTrue(dialog.preview_level())
        dialog.save_ack.setChecked(True)
        self.assertTrue(dialog.save_button.isEnabled())
        dialog.hp_roll.setValue(2)
        self.assertFalse(dialog.save_button.isEnabled())
        self.assertIsNone(dialog._candidate)
        self.assertFalse(dialog.save_reviewed())
        self.assertEqual(self.repo.get(self.hero.id).level, 1)

    def test_stale_character_save_keeps_external_change_and_reports_reopen(self):
        dialog = self.dialog(confirmed=True)
        self.fill_level(dialog)
        self.assertTrue(dialog.preview_level())
        dialog.save_ack.setChecked(True)
        self.repo.save(replace(self.repo.get(self.hero.id), notes="Another editor saved this"))
        self.assertFalse(dialog.save_reviewed())
        self.assertIn("saved character changed", dialog.status.text())
        self.assertEqual(self.repo.get(self.hero.id).level, 1)
        self.assertEqual(self.repo.get(self.hero.id).notes, "Another editor saved this")

    def test_explicit_hp_roll_and_invalid_allocation_never_mutate_saved_character(self):
        from dndgm4.dice import DiceResult
        dialog = self.dialog(confirmed=True)
        self.fill_level(dialog)
        with patch("dndgm4.multiclass_ui.roll_expression", return_value=DiceResult(1, 4, (2,), (0,))):
            self.assertTrue(dialog.roll_hp())
        self.assertEqual(dialog.hp_roll.value(), 2)
        self.assertIn("1d4", dialog._hp_detail)
        for spin in dialog.skill_points.values():
            spin.setValue(0)
        self.assertFalse(dialog.preview_level())
        self.assertIn("Allocate exactly", dialog.status.text())
        self.assertEqual(self.repo.get(self.hero.id).level, 1)
        self.assertTrue(dialog.suggest_skills())
        self.assertTrue(dialog.preview_level())

    def test_expert_skills_require_explicit_reload_and_are_used_in_cost_table(self):
        from dndgm4.character_sheet import TEMPLATES
        dialog = self.dialog(confirmed=True)
        dialog.selected_class.setCurrentText("Expert")
        self.assertFalse(dialog.preview_level_button.isEnabled())
        dialog.advance_expert.setPlainText("\n".join(TEMPLATES["Expert"].class_skills))
        self.assertFalse(dialog.preview_level_button.isEnabled())
        self.assertTrue(dialog.load_requirements())
        self.assertTrue(dialog.preview_level_button.isEnabled())
        self.assertEqual(set(dialog._requirements["current_class_skills"]), set(TEMPLATES["Expert"].class_skills))

    def test_failed_save_preserves_database_and_explains_error(self):
        dialog = self.dialog(confirmed=True)
        self.fill_level(dialog)
        self.assertTrue(dialog.preview_level())
        dialog.save_ack.setChecked(True)
        import sqlite3
        with patch("dndgm4.multiclass_ui.save_multiclass_candidate", side_effect=sqlite3.OperationalError("Disk is full")):
            self.assertFalse(dialog.save_reviewed())
        self.assertEqual(dialog.status.text(), "Disk is full")
        self.assertEqual(self.repo.get(self.hero.id).level, 1)
