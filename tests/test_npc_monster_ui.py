"""Offscreen NPC/Monster Forge tests: no network or model files needed."""
from importlib.util import find_spec
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
import json, os, unittest

@unittest.skipUnless(find_spec("PyQt6") is not None,"PyQt6 not installed")
class NPCCreatorUiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.environ.setdefault("QT_QPA_PLATFORM","offscreen")
        from PyQt6.QtWidgets import QApplication
        from dndgm4.theme import apply_theme
        cls.app=QApplication.instance() or QApplication([])
        apply_theme(cls.app)

    def test_npc_can_roll_or_manually_enter_goblin_warrior(self):
        from dndgm4.roll_ui import CharacterCreatorDialog
        from dndgm4.character_sheet import load_sheet
        d=CharacterCreatorDialog(kind="npc")
        self.assertEqual(d.kind,"npc")
        self.assertEqual(d.character_class.currentText(),"Warrior")
        self.assertGreater(len(d.race.count().__str__()),0)
        self.assertGreater(d.race.count(),20)
        d.name.setText("Murk the Scout")
        d.race.setCurrentText("Goblin")
        self.assertEqual(d.npc_mods["dexterity"].value(),2)
        self.assertEqual(d.npc_size.currentText(),"Small")
        d.method.setCurrentIndex(2)
        d.npc_cr.setText("1/3")
        d.save_character()
        self.assertIsNotNone(d.result_creature)
        self.assertEqual(d.result_creature.kind,"npc")
        self.assertEqual(d.result_creature.challenge_rating,"1/3")
        self.assertEqual(d.result_creature.dexterity,12)
        self.assertEqual(d.result_creature.armor_class,12)
        meta=load_sheet(d.result_creature)["npc_ancestry"]
        self.assertTrue(meta["verified_profile"])
        self.assertEqual(meta["size"],"Small")
        d.close()

    def test_custom_ancestry_requires_review(self):
        from dndgm4.roll_ui import CharacterCreatorDialog
        d=CharacterCreatorDialog(kind="npc")
        d.name.setText("The Stone Sage")
        d.race.setCurrentText("Custom Stonekin")
        d.method.setCurrentIndex(2)
        d.npc_mods["strength"].setValue(6)
        with patch("dndgm4.roll_ui.QMessageBox.warning") as warning:
            d.save_character()
            warning.assert_called_once()
        self.assertIsNone(d.result_creature)
        d.npc_manual_ack.setChecked(True)
        d.save_character()
        self.assertEqual(d.result_creature.kind,"npc")
        self.assertEqual(d.result_creature.strength,16)
        data=json.loads(d.result_creature.sheet_json)
        self.assertTrue(data["npc_ancestry"]["manual_review_required"])
        d.close()

    def test_npc_expert_class_skills_and_edit_roundtrip(self):
        from dndgm4.roll_ui import CharacterCreatorDialog
        from dndgm4.character_sheet import load_sheet
        d=CharacterCreatorDialog(kind="npc")
        d.name.setText("Village Blacksmith")
        d.character_class.setCurrentText("Expert")
        self.assertTrue(d.options.custom_skills.isEnabled())
        self.assertEqual(len([x for x in d.options.custom_skills.text().split(",") if x.strip()]),10)
        d.method.setCurrentIndex(2)
        d.options.apply_preset()
        d.save_character()
        self.assertEqual(d.result_creature.character_class,"Expert")
        record=d.result_creature
        d.close()
        other=CharacterCreatorDialog(creature=record)
        self.assertEqual(other.kind,"npc")
        self.assertEqual(other.character_class.currentText(),"Expert")
        other.options.background.setPlainText("Retired mercenary.")
        other.save_character()
        self.assertEqual(load_sheet(other.result_creature)["background"],"Retired mercenary.")
        other.close()

    def test_monster_creation_reopen_preserves_structured_type_stats(self):
        from dndgm4.monster_ui import MonsterCreatorDialog
        d=MonsterCreatorDialog()
        d.name.setText("Grave Sentinel")
        d.species.setCurrentText("Original Grave Sentinel")
        d.type.setCurrentText("Undead")
        d.size.setCurrentText("Large")
        d.hd.setValue(6)
        d.cr.setText("5")
        d.special_qualities.setPlainText("Darkvision 60 ft.")
        self.assertTrue(d.no_con.isChecked())
        self.assertFalse(d.ability_fields["constitution"].isEnabled())
        self.assertIn("6d12", d.preview.text())
        d.save_monster()
        m=d.result_creature
        self.assertIsNotNone(m)
        self.assertEqual(m.kind,"monster")
        self.assertEqual(m.challenge_rating,"5")
        self.assertEqual(m.constitution,0)
        d.close()
        reopened=MonsterCreatorDialog(creature=m)
        self.assertEqual(reopened.hd.value(),6)
        self.assertEqual(reopened.type.currentText(),"Undead")
        self.assertEqual(reopened.special_qualities.toPlainText(),"Darkvision 60 ft.")
        reopened.notes.setPlainText("Guarding the eastern gate.")
        reopened.save_monster()
        self.assertEqual(reopened.result_creature.id, m.id)
        self.assertEqual(reopened.result_creature.max_hit_points,m.max_hit_points)
        self.assertEqual(json.loads(reopened.result_creature.sheet_json)["notes"],
                         "Guarding the eastern gate.")
        reopened.close()


    def test_distinct_pc_and_npc_bios_use_local_scribe_and_preserve_scores(self):
        from PyQt6.QtWidgets import QDialog
        from dndgm4.roll_ui import CharacterCreatorDialog
        from dndgm4.character_sheet import load_sheet
        for kind, expected_mode in (("pc", "bio"), ("npc", "npc_bio")):
            with self.subTest(kind=kind):
                dialog = CharacterCreatorDialog(kind=kind)
                dialog.name.setText("Tarin of the Vale")
                if kind == "npc":
                    dialog.race.setCurrentText("Goblin")
                baseline = dialog.final_scores().copy()
                with patch("dndgm4.roll_ui.AIWritingDialog") as draft:
                    draft.return_value.exec.return_value = QDialog.DialogCode.Accepted
                    draft.return_value.generated_text = "An old enemy guards a secret."
                    dialog.write_biography()
                    self.assertEqual(draft.call_args.args[0], expected_mode)
                    self.assertIn("Tarin", draft.call_args.args[1])
                    self.assertIn("Race: ", draft.call_args.args[1])
                self.assertEqual(dialog.options.background.toPlainText(),
                                 "An old enemy guards a secret.")
                self.assertEqual(dialog.final_scores(), baseline)
                dialog.method.setCurrentIndex(2)
                dialog.save_character()
                self.assertEqual(
                    load_sheet(dialog.result_creature)["background"],
                    "An old enemy guards a secret.")
                dialog.close()

    def test_existing_biography_requires_confirmation_to_replace(self):
        from PyQt6.QtWidgets import QDialog, QMessageBox
        from dndgm4.roll_ui import CharacterCreatorDialog
        from dndgm4.monster_ui import MonsterCreatorDialog
        for kind in ("pc", "npc", "monster"):
            with self.subTest(kind=kind):
                d = (MonsterCreatorDialog() if kind == "monster" else
                     CharacterCreatorDialog(kind=kind))
                editor = d.biography if kind == "monster" else d.options.background
                editor.setPlainText("Existing manuscript.")
                path = ("dndgm4.monster_ui.AIWritingDialog" if kind == "monster"
                        else "dndgm4.roll_ui.AIWritingDialog")
                question = ("dndgm4.monster_ui.QMessageBox.question"
                            if kind == "monster" else
                            "dndgm4.roll_ui.QMessageBox.question")
                with patch(path) as draft, patch(question) as confirmation:
                    draft.return_value.exec.return_value = QDialog.DialogCode.Accepted
                    draft.return_value.generated_text = "New draft."
                    confirmation.return_value = QMessageBox.StandardButton.No
                    d.write_biography()
                    self.assertEqual(editor.toPlainText(), "Existing manuscript.")
                    confirmation.return_value = QMessageBox.StandardButton.Yes
                    d.write_biography()
                    self.assertEqual(editor.toPlainText(), "New draft.")
                    self.assertEqual(confirmation.call_count, 2)
                d.close()

    def test_monster_bio_generation_preserves_rules_and_round_trips(self):
        from PyQt6.QtWidgets import QDialog
        from dndgm4.monster_ui import MonsterCreatorDialog
        d = MonsterCreatorDialog()
        d.name.setText("Mire Wraith")
        d.species.setCurrentText("Original marsh wraith")
        d.type.setCurrentText("Undead")
        d.hd.setValue(4)
        d.notes.setPlainText("GM secret: bound to an old bell.")
        d.special_qualities.setPlainText("Darkvision")
        with patch("dndgm4.monster_ui.AIWritingDialog") as draft:
            draft.return_value.exec.return_value = QDialog.DialogCode.Accepted
            draft.return_value.generated_text = "Its lantern glows above the bog."
            d.write_biography()
            self.assertEqual(draft.call_args.args[0], "monster_bio")
            self.assertIn("Mindless" if d.no_int.isChecked() else "Intelligence:",
                          draft.call_args.args[1])
            self.assertIn("Type: Undead", draft.call_args.args[1])
            self.assertIn("\n", draft.call_args.args[1])
        self.assertEqual(d.biography.toPlainText(),
                         "Its lantern glows above the bog.")
        self.assertEqual(d.notes.toPlainText(),
                         "GM secret: bound to an old bell.")
        d.save_monster()
        first = d.result_creature
        data = json.loads(first.sheet_json)
        self.assertEqual(data["biography"], "Its lantern glows above the bog.")
        self.assertEqual(data["notes"], "GM secret: bound to an old bell.")
        self.assertEqual(first.kind, "monster")
        self.assertEqual(first.constitution, 0)
        original_hp = first.max_hit_points
        d.close()
        reopened = MonsterCreatorDialog(creature=first)
        self.assertEqual(reopened.biography.toPlainText(),
                         "Its lantern glows above the bog.")
        reopened.save_monster()
        self.assertEqual(reopened.result_creature.max_hit_points, original_hp)
        self.assertEqual(json.loads(reopened.result_creature.sheet_json)["biography"],
                         "Its lantern glows above the bog.")
        reopened.close()

    def test_biographies_appear_in_library_preview_without_erasing_notes(self):
        from PyQt6.QtCore import Qt
        from dndgm4.storage import CreatureRepository
        from dndgm4.ui import MainWindow
        from dndgm4.monster_rules import MonsterBlueprint, build_monster
        from dndgm4.creation import ABILITIES
        with TemporaryDirectory() as tmp:
            repo = CreatureRepository(Path(tmp) / "library.sqlite3")
            monster = build_monster(MonsterBlueprint(
                name="Ash Troll", species="Original Ash Troll",
                creature_type="Giant", hit_dice=3,
                abilities=dict.fromkeys(ABILITIES, 10),
                notes="Private DM note",
                biography="Lives below the burned bridge."
            ))
            saved = repo.save(monster)
            window = MainWindow(repo)
            window.change_section("monster")
            for row in range(window.table.rowCount()):
                item = window.table.item(row, 0)
                if item and item.data(Qt.ItemDataRole.UserRole) == saved.id:
                    window.table.selectRow(row)
                    break
            self.app.processEvents()
            shown = window.notes_preview.toPlainText()
            self.assertIn("BESTIARY BIOGRAPHY", shown)
            self.assertIn("Lives below the burned bridge.", shown)
            self.assertIn("Private DM note", shown)
            window.close()

    def test_main_create_routes_use_both_specialized_forges(self):
        from dndgm4.ui import MainWindow
        from dndgm4.storage import CreatureRepository
        from PyQt6.QtWidgets import QDialog
        with TemporaryDirectory() as folder:
            w=MainWindow(CreatureRepository(Path(folder)/"r.sqlite3"))
            with patch("dndgm4.ui.CharacterCreatorDialog") as npc, \
                 patch("dndgm4.ui.MonsterCreatorDialog") as monster:
                npc.return_value.exec.return_value=QDialog.DialogCode.Rejected
                monster.return_value.exec.return_value=QDialog.DialogCode.Rejected
                w.create("npc")
                npc.assert_called_once_with(w,kind="npc")
                w.create("monster")
                monster.assert_called_once_with(w)
            w.close()

if __name__=="__main__":
    unittest.main()
