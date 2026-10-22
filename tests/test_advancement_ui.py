"""Explicit HP rolls, editable class defaults, review, and cancelled drafts."""
from dataclasses import replace
from importlib.util import find_spec
import json
import os
import unittest
from unittest.mock import patch


@unittest.skipUnless(find_spec("PyQt6") is not None, "PyQt6 is not installed")
class AdvancementUiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        from PyQt6.QtWidgets import QApplication
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        from dndgm4.models import Creature
        self.original = Creature(
            id="rowan", name="Rowan", race_type="Human", character_class="Fighter",
            strength=16, dexterity=14, constitution=14, intelligence=12,
            max_hit_points=12, notes="A trusted party defender.",
            sheet_json=json.dumps({"version": 1, "class": "Fighter",
                                   "skills_half_ranks": {"Climb": 8, "Jump": 8, "Ride": 8},
                                   "feats": ["Power Attack", "Cleave", "Improved Initiative"],
                                   "background": "A village defender.", "custom_lore": {"ally": "Élara"}}))
        self.dialogs = []

    def tearDown(self):
        for dialog in self.dialogs:
            dialog.close()

    def dialog(self, creature=None, **kwargs):
        from dndgm4.advancement_ui import LevelUpDialog
        dialog = LevelUpDialog(creature or self.original, **kwargs)
        self.dialogs.append(dialog)
        return dialog

    def ready_fighter(self):
        dialog = self.dialog()
        dialog.apply_defaults()
        dialog.hp_roll.setValue(7)
        dialog.review_ack.setChecked(True)
        return dialog

    def test_opening_preview_and_defaults_never_roll_or_save(self):
        with patch("dndgm4.advancement_ui.roll_expression") as roll:
            dialog = self.dialog()
            dialog.apply_defaults()
            dialog.update_preview()
            dialog.mode.setCurrentIndex(dialog.mode.findData("default"))
        roll.assert_not_called()
        self.assertEqual(dialog.hp_roll.value(), 0)
        self.assertFalse(dialog.save_button.isEnabled())
        self.assertIsNone(dialog.result_creature)
        self.assertEqual(self.original.level, 1)

    def test_roll_button_rolls_once_and_records_visible_die_detail(self):
        from dndgm4.dice import DiceResult
        dialog = self.dialog()
        dialog.apply_defaults()
        result = DiceResult(1, 10, (7,), (0,))
        with patch("dndgm4.advancement_ui.roll_expression", return_value=result) as roll:
            dialog.roll_button.click()
            dialog.update_preview()
            dialog.update_preview()
        roll.assert_called_once_with("1d10")
        self.assertEqual(dialog.hp_roll.value(), 7)
        self.assertIn("[7]", dialog.hp_detail.text())
        self.assertIn("[7]", dialog.choices()["hp_roll_detail"])
        dialog.review_ack.setChecked(True)
        self.assertTrue(dialog.save_button.isEnabled(), dialog.status.text())

    def test_entered_tabletop_roll_replaces_previous_roll_audit(self):
        from dndgm4.dice import DiceResult
        dialog = self.dialog()
        with patch("dndgm4.advancement_ui.roll_expression", return_value=DiceResult(1, 10, (7,), (0,))):
            dialog.roll_button.click()
        dialog.hp_roll.setValue(4)
        self.assertIn("Entered d10 result: 4", dialog.choices()["hp_roll_detail"])
        self.assertNotIn("[7]", dialog.choices()["hp_roll_detail"])

    def test_save_only_publishes_reviewed_draft_and_preserves_other_fields(self):
        from PyQt6.QtWidgets import QDialog
        dialog = self.ready_fighter()
        self.assertTrue(dialog.save_button.isEnabled(), dialog.status.text())
        self.assertIsNone(dialog.result_creature)
        dialog.save_button.click()
        self.assertEqual(dialog.result(), QDialog.DialogCode.Accepted)
        result = dialog.result_creature
        self.assertEqual(result.level, 2)
        self.assertEqual(result.max_hit_points, 21)
        self.assertEqual(result.id, self.original.id)
        self.assertEqual(result.notes, self.original.notes)
        data = json.loads(result.sheet_json)
        self.assertEqual(data["custom_lore"], {"ally": "Élara"})
        self.assertEqual(self.original.level, 1)

    def test_cancel_discards_completed_draft(self):
        dialog = self.ready_fighter()
        self.assertTrue(dialog.save_button.isEnabled(), dialog.status.text())
        dialog.reject()
        self.assertIsNone(dialog.result_creature)
        self.assertEqual(self.original.level, 1)
        self.assertEqual(self.original.max_hit_points, 12)

    def test_invalid_skill_choices_disable_save_until_corrected(self):
        dialog = self.ready_fighter()
        self.assertTrue(dialog.save_button.isEnabled(), dialog.status.text())
        # Buying several unrelated cross-class skills exceeds the new level's
        # point budget even though every individual rank cap remains legal.
        for name in ("Appraise", "Balance", "Bluff", "Concentration"):
            dialog.skill_fields[name].setValue(1)
        self.assertFalse(dialog.save_button.isEnabled())
        dialog.apply_defaults()
        dialog.review_ack.setChecked(True)
        self.assertTrue(dialog.save_button.isEnabled(), dialog.status.text())

    def test_fourth_level_gathers_required_ability_choice(self):
        dialog = self.dialog(replace(self.original, level=3, max_hit_points=30))
        self.assertTrue(dialog.requirements["ability_due"])
        dialog.apply_defaults()
        dialog.hp_roll.setValue(5)
        dialog.review_ack.setChecked(True)
        self.assertTrue(dialog.save_button.isEnabled(), dialog.status.text())
        dialog.ability.setCurrentIndex(0)
        self.assertFalse(dialog.save_button.isEnabled())
        dialog.ability.setCurrentIndex(dialog.ability.findData("strength"))
        self.assertTrue(dialog.save_button.isEnabled(), dialog.status.text())
        self.assertIn("Strength: 16 → 17", dialog.preview.toPlainText())

    def test_caster_defaults_gather_spell_choices_and_review(self):
        wizard = replace(self.original, character_class="Wizard", max_hit_points=6,
                         sheet_json=json.dumps({"class": "Wizard", "skills_half_ranks": {},
                                                "feats": ["Improved Initiative", "Alertness"]}))
        dialog = self.dialog(wizard)
        dialog.apply_defaults()
        dialog.hp_roll.setValue(3)
        self.assertTrue(dialog.requirements["spell_review_required"])
        self.assertFalse(dialog.save_button.isEnabled())
        dialog.spell_notes.setPlainText("Added Magic Missile and Shield to the spellbook; slots reviewed.")
        dialog.review_ack.setChecked(True)
        self.assertTrue(dialog.save_button.isEnabled(), dialog.status.text())

    def test_custom_class_profile_requires_progression_and_acknowledgement(self):
        from dndgm4.advancement_ui import ProgressionProfileDialog
        custom = replace(self.original, character_class="Rune Knight",
                         sheet_json=json.dumps({"class": "Rune Knight", "custom_hd": 10,
                                                "custom_skill_points": 4,
                                                "custom_class_skills": ["Spellcraft"]}))
        dialog = ProgressionProfileDialog(custom)
        self.dialogs.append(dialog)
        dialog.continue_button.click()
        self.assertIsNone(dialog.result_profile)
        self.assertIn("base attack", dialog.status.text())
        dialog.bab.setCurrentIndex(dialog.bab.findData("full"))
        dialog.continue_button.click()
        self.assertIsNone(dialog.result_profile)
        dialog.good_saves["fort"].setChecked(True)
        dialog.review_ack.setChecked(True)
        dialog.continue_button.click()
        self.assertEqual(dialog.result_profile["bab_progression"], "full")
        self.assertEqual(dialog.result_profile["good_saves"], ["fort"])
        self.assertEqual(dialog.result_profile["hit_die"], 10)
        self.assertIn("Spellcraft", dialog.result_profile["class_skills"])

    def test_weapon_focus_gathers_weapon_choice_and_saves_parameter(self):
        dialog = self.ready_fighter()
        dialog.feats.setPlainText("Weapon Focus")
        self.assertFalse(dialog.save_button.isEnabled())
        self.assertFalse(dialog.feat_detail_rows["Weapon Focus"].isHidden())
        dialog.feat_details["Weapon Focus"].setText("longsword")
        self.assertTrue(dialog.save_button.isEnabled(), dialog.status.text())
        dialog.save_button.click()
        data = json.loads(dialog.result_creature.sheet_json)
        self.assertIn("Weapon Focus (longsword)", data["feats"])
        self.assertEqual(data["advancement_history"][-1]["feat_details"],
                         {"Weapon Focus": "longsword"})

    def test_class_adjustment_notes_are_retained_in_level_history(self):
        dialog = self.ready_fighter()
        dialog.class_notes.setPlainText("DM-approved training with the town guard.")
        self.assertTrue(dialog.save_button.isEnabled(), dialog.status.text())
        dialog.save_button.click()
        data = json.loads(dialog.result_creature.sheet_json)
        self.assertEqual(data["advancement_history"][-1]["class_notes"],
                         "DM-approved training with the town guard.")
        self.assertIn("Level 2: DM-approved training with the town guard.", data["class_features"])


if __name__ == "__main__":
    unittest.main()
