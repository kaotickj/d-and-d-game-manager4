"""Gender and age fields round-trip across 3.5 PCs, NPCs and monsters."""
import json
import os
import unittest
from importlib.util import find_spec
from unittest.mock import patch

from dndgm4.creation import ABILITIES,build_character
from dndgm4.character_sheet import build_sheet,load_sheet
from dndgm4.monster_rules import MonsterBlueprint,build_monster
from dndgm4.ai_character import validate_draft
from dndgm4.identity_rules import identity_text

BASE=dict.fromkeys(ABILITIES,12)


class IdentityRulesTests(unittest.TestCase):
    def test_blank_and_descriptive_age_are_allowed(self):
        for age in ("", "24", "Ancient", "Ageless", "375 years", "Hatchling"):
            self.assertEqual(identity_text(age,"Age"),age)
        with self.assertRaises(ValueError):
            identity_text("A" * 81,"Age")
        with self.assertRaises(ValueError):
            identity_text("20\n30","Age")
        with self.assertRaises(ValueError):
            identity_text(None,"Age")

    def test_character_sheet_explicit_gender_age_no_notes_duplication(self):
        hero=build_character(name="Nira",race="Human",
                             character_class="Fighter",base=BASE,method="manual")
        sheet=build_sheet(character=hero,class_name="Fighter",
            ranks={},feats=["Improved Initiative"],
            equipment=["Longsword"],alignment="Lawful Good",deity="",
            languages=["Common"],appearance="",personality="",
            background="",gender="Nonbinary",age="27",
            extra_notes="Prefers the west road.")
        parsed=load_sheet(sheet)
        self.assertEqual(parsed["gender"],"Nonbinary")
        self.assertEqual(parsed["age"],"27")
        self.assertEqual(parsed["extra_notes"],"Prefers the west road.")
        self.assertNotIn("Age:",parsed["extra_notes"])

    def test_monster_blueprint_gender_and_life_stage_saved(self):
        for gender,age in (("Genderless","Ancient"),
                           ("Female","280 years"),("Unspecified","Hatchling")):
            with self.subTest(gender=gender,age=age):
                obj=build_monster(MonsterBlueprint(
                    name="Ash Drake",species="Ash Drake",creature_type="Dragon",
                    hit_dice=2,abilities=BASE,gender=gender,age=age))
                sheet=json.loads(obj.sheet_json)
                self.assertEqual(sheet["gender"],gender)
                self.assertEqual(sheet["age"],age)
                self.assertEqual(obj.kind,"monster")
        with self.assertRaisesRegex(ValueError,"Age"):
            build_monster(MonsterBlueprint(
                name="Bad",species="Bad",creature_type="Dragon",
                hit_dice=2,abilities=BASE,age="X"*100))


@unittest.skipUnless(find_spec("PyQt6") is not None,"PyQt6 missing")
class IdentityGuiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.environ.setdefault("QT_QPA_PLATFORM","offscreen")
        from PyQt6.QtWidgets import QApplication
        from dndgm4.theme import apply_theme
        cls.app=QApplication.instance() or QApplication([])
        apply_theme(cls.app)

    def test_pc_npc_identity_ui_and_save_reopen(self):
        from dndgm4.roll_ui import CharacterCreatorDialog
        for kind in ("pc","npc"):
            with self.subTest(kind=kind):
                d=CharacterCreatorDialog(kind=kind)
                d.name.setText("Tarin")
                d.method.setCurrentIndex(2)
                d.options.gender.setCurrentText("Female")
                d.options.age.setText("34")
                d.save_character()
                self.assertIsNotNone(d.result_creature)
                data=load_sheet(d.result_creature)
                self.assertEqual(data["gender"],"Female")
                self.assertEqual(data["age"],"34")
                reopened=CharacterCreatorDialog(creature=d.result_creature)
                self.assertEqual(reopened.options.gender.currentText(),"Female")
                self.assertEqual(reopened.options.age.text(),"34")
                reopened.close()
                d.close()

    def test_legacy_age_line_is_migrated_on_edit(self):
        from dataclasses import replace
        from dndgm4.roll_ui import CharacterCreatorDialog
        d=CharacterCreatorDialog()
        d.name.setText("Varyn")
        d.method.setCurrentIndex(2)
        d.save_character()
        data=load_sheet(d.result_creature)
        data.pop("age",None)
        data.pop("gender",None)
        data["extra_notes"]="Age: 86 years\nKeeps a brass key."
        prior=replace(d.result_creature,sheet_json=json.dumps(data))
        d.close()
        edit=CharacterCreatorDialog(creature=prior)
        self.assertEqual(edit.options.age.text(),"86 years")
        self.assertEqual(edit.options.other.toPlainText(),"Keeps a brass key.")
        edit.options.gender.setCurrentText("Male")
        edit.save_character()
        saved=load_sheet(edit.result_creature)
        self.assertEqual(saved["age"],"86 years")
        self.assertEqual(saved["gender"],"Male")
        self.assertEqual(saved["extra_notes"],"Keeps a brass key.")
        edit.close()

    def test_monster_controls_and_biography_context(self):
        from PyQt6.QtWidgets import QDialog
        from dndgm4.monster_ui import MonsterCreatorDialog
        d=MonsterCreatorDialog()
        d.name.setText("Hollow Watcher")
        d.species.setCurrentText("Hollow Watcher")
        d.gender.setCurrentText("Genderless")
        d.age.setText("Ageless")
        with patch("dndgm4.monster_ui.AIWritingDialog") as writer:
            writer.return_value.exec.return_value=QDialog.DialogCode.Rejected
            d.write_biography()
            prompt=writer.call_args.args[1]
            self.assertIn("Gender: Genderless",prompt)
            self.assertIn("Age / life stage: Ageless",prompt)
        d.save_monster()
        self.assertIsNotNone(d.result_creature)
        data=json.loads(d.result_creature.sheet_json)
        self.assertEqual(data["gender"],"Genderless")
        self.assertEqual(data["age"],"Ageless")
        reopened=MonsterCreatorDialog(creature=d.result_creature)
        self.assertEqual(reopened.gender.currentText(),"Genderless")
        self.assertEqual(reopened.age.text(),"Ageless")
        reopened.close()
        d.close()

    def test_pc_bio_uses_selected_gender_and_age(self):
        from PyQt6.QtWidgets import QDialog
        from dndgm4.roll_ui import CharacterCreatorDialog
        d=CharacterCreatorDialog()
        d.options.gender.setCurrentText("Nonbinary")
        d.options.age.setText("49")
        with patch("dndgm4.roll_ui.AIWritingDialog") as writer:
            writer.return_value.exec.return_value=QDialog.DialogCode.Rejected
            d.write_biography()
            prompt=writer.call_args.args[1]
            self.assertIn("Gender: Nonbinary",prompt)
            self.assertIn("Age / life stage: 49",prompt)
        d.close()


if __name__=="__main__":
    unittest.main()
