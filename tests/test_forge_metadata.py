"""Real first-level Forge edits retain independent character-sheet metadata."""
from dataclasses import replace
from importlib.util import find_spec
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch


@unittest.skipUnless(find_spec("PyQt6") is not None, "PyQt6 is not installed")
class ForgeMetadataTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        from PyQt6.QtWidgets import QApplication
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        from dndgm4.storage import CreatureRepository
        self.temp = TemporaryDirectory()
        self.repository = CreatureRepository(Path(self.temp.name) / "library.sqlite3")
        self.dialogs = []

    def tearDown(self):
        for dialog in self.dialogs:
            dialog.close()
            dialog.deleteLater()
        self.app.processEvents()
        self.temp.cleanup()

    def forge(self, creature=None):
        from dndgm4.roll_ui import CharacterCreatorDialog
        dialog = CharacterCreatorDialog(creature=creature)
        self.dialogs.append(dialog)
        return dialog

    def original(self, *, with_history=True):
        from dndgm4.multiclass import establish_history
        from dndgm4.spell_progression import GROUPS, build_spell_candidate, load_spell_plan
        creator = self.forge()
        creator.name.setText("Ayla")
        creator.race.setCurrentText("Human")
        creator.character_class.setCurrentText("Wizard")
        creator.method.setCurrentIndex(2)
        creator.score_inputs["intelligence"].setValue(16)
        creator.options.apply_preset()
        with patch("dndgm4.roll_ui.QMessageBox.warning") as warning:
            creator.save_character()
        self.assertIsNotNone(creator.result_creature, warning.call_args)
        saved = self.repository.save(creator.result_creature)
        if with_history:
            spell_plan = load_spell_plan(saved, "Wizard")
            saved = build_spell_candidate(saved, "Wizard", {group: spell_plan[group] for group in GROUPS}, review_ack=True)
            saved = establish_history(saved, {"Wizard": 1}, review_ack=True, no_racial_hd_ack=True,
                                      review_notes="DM confirmed existing Wizard history")
        data = json.loads(saved.sheet_json)
        data["experience_points"] = 450
        data["custom_campaign_metadata"] = {"labels": ["Courier", "Ash Road"],
                                             "nested": {"reviewed": True, "unknown": None}}
        return self.repository.save(replace(saved, sheet_json=json.dumps(data)))

    def test_edit_preserves_xp_spell_plan_class_history_and_unknown_metadata(self):
        from PyQt6.QtWidgets import QDialog
        original = self.original()
        before = json.loads(original.sheet_json)
        editor = self.forge(original)
        editor.name.setText("Ayla of the Ash Road")
        editor.options.background.setPlainText("A new biography written in the Forge.")
        editor.options.equipment.setPlainText("Staff\nTravel pack")
        editor.options.inventory.setPlainText("2 x Torch")
        with patch("dndgm4.roll_ui.QMessageBox.warning") as warning:
            editor.save_character()
        warning.assert_not_called()
        self.assertEqual(editor.result(), QDialog.DialogCode.Accepted)
        edited = editor.result_creature
        after = json.loads(edited.sheet_json)
        for key in ("experience_points", "spell_progression", "class_levels", "progression",
                    "multiclass_baseline", "multiclass_audit", "multiclass_class_skills",
                    "multiclass_choices", "custom_campaign_metadata"):
            self.assertEqual(after[key], before[key], key)
        self.assertEqual(after["background"], "A new biography written in the Forge.")
        self.assertEqual(after["equipment"], ["Staff", "Travel pack"])
        self.assertEqual(after["inventory"][0]["quantity"], 2)
        self.assertEqual(after["inventory"][0]["name"], "Torch")
        self.assertEqual((edited.id, edited.archived, edited.created_at, edited.updated_at),
                         (original.id, original.archived, original.created_at, original.updated_at))
        self.assertEqual(edited.name, "Ayla of the Ash Road")
        self.assertEqual(self.repository.get(original.id), original)  # Forge prepares; caller persists.

    def test_class_and_race_changes_with_history_reject_and_keep_draft(self):
        from PyQt6.QtWidgets import QDialog
        original = self.original()
        for field, changed in (("character_class", "Sorcerer"), ("race", "Elf")):
            with self.subTest(field=field):
                editor = self.forge(original)
                getattr(editor, field).setCurrentText(changed)
                editor.name.setText("Keep this proposed name")
                editor.options.background.setPlainText("Keep this unsaved biography")
                with patch("dndgm4.roll_ui.QMessageBox.warning") as warning:
                    editor.save_character()
                self.assertIsNone(editor.result_creature)
                self.assertNotEqual(editor.result(), QDialog.DialogCode.Accepted)
                self.assertIn("reconciliation", warning.call_args.args[-1])
                self.assertEqual(editor.name.text(), "Keep this proposed name")
                self.assertEqual(editor.options.background.toPlainText(), "Keep this unsaved biography")
                self.assertEqual(getattr(editor, field).currentText(), changed)
        self.assertEqual(self.repository.get(original.id), original)

    def test_class_change_with_only_xp_and_custom_data_keeps_unrelated_fields(self):
        from dndgm4.spell_rules import default_spellbook
        original = self.original(with_history=False)
        editor = self.forge(original)
        editor.character_class.setCurrentText("Sorcerer")
        editor.options.apply_preset()
        editor.options.fill_spellbook(default_spellbook("Sorcerer", editor.final_scores()))
        editor.options.background.setPlainText("A deliberately revised first-level build")
        with patch("dndgm4.roll_ui.QMessageBox.warning") as warning:
            editor.save_character()
        self.assertIsNotNone(editor.result_creature, warning.call_args)
        data = json.loads(editor.result_creature.sheet_json)
        self.assertEqual(data["class"], "Sorcerer")
        self.assertEqual(data["experience_points"], 450)
        self.assertEqual(data["custom_campaign_metadata"], json.loads(original.sheet_json)["custom_campaign_metadata"])

    def test_malformed_original_sheet_reports_error_and_never_falls_back_to_empty(self):
        original = self.original(with_history=False)
        invalid = ("{broken", "[]", '{"custom":1,"custom":2}', '{"custom":NaN}',
                   '{"custom":1e999}', '{"feats":42}',
                   '{"custom":' + "[" * 10000 + "0" + "]" * 10000 + "}")
        for text in invalid:
            with self.subTest(text=text[:35]):
                broken = replace(original, sheet_json=text)
                editor = self.forge(broken)
                self.assertIsNotNone(editor._original_sheet_error)
                self.assertIn("could not be loaded safely", editor.message.text())
                editor.name.setText("Retain the unsaved name")
                with patch("dndgm4.roll_ui.QMessageBox.warning") as warning:
                    editor.save_character()
                self.assertIsNone(editor.result_creature)
                self.assertIn("blocked", warning.call_args.args[-1])
                self.assertEqual(editor.original.sheet_json, text)
                self.assertEqual(editor.name.text(), "Retain the unsaved name")
        self.assertEqual(self.repository.get(original.id), original)

    def test_spell_plan_without_class_history_still_requires_reconciliation(self):
        original = self.original()
        data = json.loads(original.sheet_json)
        for key in ("class_levels", "progression", "multiclass_baseline", "multiclass_audit",
                    "multiclass_class_skills", "multiclass_choices"):
            data.pop(key, None)
        original = replace(original, sheet_json=json.dumps(data))
        self.assertIn("spell_progression", data)
        editor = self.forge(original)
        editor.race.setCurrentText("Elf")
        editor.options.background.setPlainText("Keep this proposed ancestry story")
        with patch("dndgm4.roll_ui.QMessageBox.warning") as warning:
            editor.save_character()
        self.assertIsNone(editor.result_creature)
        self.assertIn("reconciliation", warning.call_args.args[-1])
        self.assertEqual(editor.options.background.toPlainText(), "Keep this proposed ancestry story")

    def test_original_json_rechecked_at_save_and_higher_level_never_resets_to_one(self):
        original = self.original(with_history=False)
        editor = self.forge(original)
        editor.options.background.setPlainText("Keep this draft")
        editor.original = replace(original, sheet_json="{not json")
        with patch("dndgm4.roll_ui.QMessageBox.warning") as warning:
            editor.save_character()
        self.assertIsNone(editor.result_creature)
        self.assertIn("could not be read safely", warning.call_args.args[-1])
        self.assertEqual(editor.options.background.toPlainText(), "Keep this draft")
        advanced = self.forge(replace(original, level=2))
        with patch("dndgm4.roll_ui.QMessageBox.warning") as warning:
            advanced.save_character()
        self.assertIsNone(advanced.result_creature)
        self.assertIn("first-level", warning.call_args.args[-1])


if __name__ == "__main__":
    unittest.main()
