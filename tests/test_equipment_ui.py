"""Equipment review preserves saved state and requires an unchanged reviewed draft."""
from dataclasses import replace
import importlib.util
import json
import os
import unittest

HAS_QT = importlib.util.find_spec("PyQt6") is not None
if HAS_QT:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PyQt6.QtWidgets import QApplication, QDialog
    from dndgm4.equipment_ui import EquipmentLoadoutDialog
    from dndgm4.models import Creature


@unittest.skipUnless(HAS_QT, "PyQt6 is not installed")
class EquipmentUITests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.sheet = dict(class_levels={"Fighter": 2}, feats=["Weapon Focus (longsword)", "Weapon Finesse"],
                          player_notes="Keep <b>literal</b>", spellbook={"custom": ["magic"]},
                          inventory=[{"item": "family sword", "count": 1}], custom={"unknown": True})
        self.creature = Creature("Hero", id="hero", character_class="Fighter", race_type="Human", level=2,
                                 armor_class=17, strength=16, dexterity=14, constitution=12,
                                 sheet_json=json.dumps(self.sheet))
        self.dialogs = []

    def dialog(self, creature=None):
        dialog = EquipmentLoadoutDialog(creature or self.creature)
        self.dialogs.append(dialog)
        return dialog

    def tearDown(self):
        for dialog in self.dialogs:
            dialog.reject()
            dialog.deleteLater()
        self.app.processEvents()

    def test_explicit_review_and_accept_preserve_metadata_and_manual_ac(self):
        dialog = self.dialog()
        self.assertIsNone(dialog.result_creature)
        self.assertFalse(dialog.save_button.isEnabled())
        self.assertFalse(dialog.proficiency.isChecked())
        dialog.armor.setCurrentText("Chain shirt")
        dialog.weapon.setCurrentText("Longsword")
        dialog.proficiency.setChecked(True)
        self.assertTrue(dialog.review_calculation(), dialog.status.text())
        self.assertIsNone(dialog.result_creature)
        self.assertIn("AC discrepancy", dialog.preview.toPlainText())
        self.assertIn("http", dialog.preview.toPlainText())
        dialog.accept()
        self.assertEqual(dialog.result(), QDialog.DialogCode.Accepted)
        candidate = dialog.result_creature
        self.assertEqual(candidate.armor_class, 17)
        self.assertEqual(candidate.id, self.creature.id)
        self.assertEqual(self.creature.sheet_json, json.dumps(self.sheet))
        saved = json.loads(candidate.sheet_json)
        profile = saved.pop("combat_loadout")
        self.assertEqual(saved, self.sheet)
        self.assertEqual(profile["armor"], "Chain shirt")
        self.assertEqual(profile["review_basis"], {"class": "Fighter", "race": "Human", "level": 2})

    def test_changed_draft_cannot_save_old_preview(self):
        dialog = self.dialog()
        self.assertTrue(dialog.review_calculation(), dialog.status.text())
        dialog.size.setCurrentText("Small")
        self.assertFalse(dialog.save_button.isEnabled())
        self.assertEqual(dialog.preview.toPlainText(), "")
        dialog.accept()
        self.assertIsNone(dialog.result_creature)
        self.assertNotEqual(dialog.result(), QDialog.DialogCode.Accepted)
        self.assertTrue(dialog.review_calculation(), dialog.status.text())
        dialog.accept()
        self.assertEqual(dialog.result_profile["size"], "Small")

    def test_reject_after_review_yields_no_candidate(self):
        dialog = self.dialog()
        self.assertTrue(dialog.review_calculation(), dialog.status.text())
        dialog.reject()
        self.assertIsNone(dialog.result_profile)
        self.assertIsNone(dialog.result_creature)

    def test_no_multiclass_inference_or_automatic_confirmation(self):
        creature = replace(self.creature, character_class="Fighter 1 / Rogue 1", sheet_json='{"feats": []}')
        dialog = self.dialog(creature)
        self.assertTrue(all(spin.value() == 0 for spin in dialog.class_levels.values()))
        self.assertFalse(dialog.review_calculation())
        self.assertFalse(dialog.save_button.isEnabled())
        self.assertFalse(dialog.weapon_focus.isEnabled())
        self.assertFalse(dialog.weapon_finesse.isEnabled())
        dialog.class_levels["Fighter"].setValue(1)
        dialog.class_levels["Rogue"].setValue(1)
        self.assertTrue(dialog.review_calculation(), dialog.status.text())
        self.assertFalse(dialog.proficiency.isChecked())

    def test_invalid_json_unknown_profiles_and_nonfinite_preserve_original(self):
        for raw in ('{"custom": 1, "custom": 2}', '{"custom":NaN}', '{"custom":1e999}',
                    '[]', '{broken', '{"combat_loadout":{"version":99}}'):
            with self.subTest(raw=raw):
                creature = replace(self.creature, sheet_json=raw)
                dialog = self.dialog(creature)
                self.assertFalse(dialog.review_button.isEnabled())
                self.assertFalse(dialog.review_calculation())
                dialog.accept()
                self.assertIsNone(dialog.result_creature)
                self.assertEqual(creature.sheet_json, raw)

    def test_owned_feat_controls_and_stale_basis_reconfirmation(self):
        original = self.dialog()
        original.weapon.setCurrentText("Longsword")
        original.proficiency.setChecked(True)
        self.assertEqual(original.weapon_focus.currentText(), "Longsword")
        self.assertTrue(original.review_calculation(), original.status.text())
        original.accept()
        changed = replace(original.result_creature, race_type="Elf")
        dialog = self.dialog(changed)
        self.assertFalse(dialog.proficiency.isChecked())
        self.assertFalse(dialog.monk_eligible.isChecked())
        self.assertIn("Reconfirm", dialog.status.text())
        self.assertTrue(dialog.review_calculation(), dialog.status.text())
        dialog.accept()
        self.assertEqual(dialog.result_profile["review_basis"]["race"], "Elf")


if __name__ == "__main__":
    unittest.main()
