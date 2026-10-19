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
