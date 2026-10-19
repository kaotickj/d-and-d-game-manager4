"""Three-route Character Forge and structured spellbook GUI smoke tests."""
import json
import os
import unittest
from importlib.util import find_spec
from unittest.mock import patch

@unittest.skipUnless(find_spec("PyQt6") is not None,"PyQt6 unavailable")
class FullForgeFlowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.environ.setdefault("QT_QPA_PLATFORM","offscreen")
        from PyQt6.QtWidgets import QApplication
        from dndgm4.theme import apply_theme
        cls.app=QApplication.instance() or QApplication([])
        apply_theme(cls.app)

    def test_three_modes_and_guided_seven_steps(self):
        from dndgm4.roll_ui import CharacterCreatorDialog
        dialog=CharacterCreatorDialog()
        self.assertEqual(dialog.creation_mode.count(),3)
        self.assertEqual(dialog.creation_mode.currentData(),"default")
        self.assertEqual(dialog.options.build_mode.currentIndex(),0)
        for name in ("Spells & Spellbook","Inventory","Skills","Story"):
            self.assertTrue(any(name==dialog.options.tabs.tabText(i)
                                for i in range(dialog.options.tabs.count())))
        dialog.creation_mode.setCurrentIndex(2)
        self.assertEqual(dialog.creation_mode.currentData(),"guided")
        self.assertEqual(dialog.options.build_mode.currentIndex(),1)
        self.assertEqual(dialog.guide_step.count(),7)
        dialog.guide_step.setCurrentIndex(4)
        self.assertEqual(dialog.options.tabs.tabText(
            dialog.options.tabs.currentIndex()),"Spells & Spellbook")
        dialog.guide_step.setCurrentIndex(5)
        self.assertEqual(dialog.options.tabs.tabText(
            dialog.options.tabs.currentIndex()),"Inventory")
        dialog.close()

    def test_default_wizard_and_sorcerer_magic_and_inventory_roundtrip(self):
        from dndgm4.roll_ui import CharacterCreatorDialog
        from dndgm4.character_sheet import load_sheet
        for kind in ("Wizard","Sorcerer"):
            with self.subTest(class_name=kind):
                dialog=CharacterCreatorDialog()
                dialog.name.setText("Nara "+kind)
                dialog.character_class.setCurrentText(kind)
                dialog.method.setCurrentIndex(2)
                if kind=="Wizard":
                    dialog.score_inputs["intelligence"].setValue(16)
                else:
                    dialog.score_inputs["charisma"].setValue(16)
                dialog.options.apply_preset()
                dialog.options.inventory.setPlainText(
                    "3 x Torch\n2 x Rations\nSpell component pouch")
                dialog.save_character()
                self.assertIsNotNone(dialog.result_creature)
                data=load_sheet(dialog.result_creature)
                self.assertIn("spellbook",data)
                self.assertEqual(data["inventory"][0]["quantity"],3)
                if kind=="Wizard":
                    self.assertGreaterEqual(len(
                        data["spellbook"]["spellbook"]["1"]),3)
                else:
                    self.assertEqual(len(data["spellbook"]["known"]["0"]),4)
                reopened=CharacterCreatorDialog(creature=dialog.result_creature)
                self.assertIn("3 x Torch",
                    reopened.options.inventory.toPlainText())
                reopened.close()
                dialog.close()

    def test_ai_draft_applied_without_saving_until_review(self):
        from PyQt6.QtWidgets import QDialog
        from dndgm4.roll_ui import CharacterCreatorDialog
        from dndgm4.character_sheet import load_sheet
        payload={
            "kind":"pc","race":"Human","class":"Fighter","name":"Captain Reeve",
            "base_scores":{
                "strength":16,"dexterity":14,"constitution":14,
                "intelligence":12,"wisdom":11,"charisma":12},
            "alignment":"Lawful Good","feats":["Power Attack","Cleave"],
            "skills_half_ranks":{"Ride":8,"Climb":8},
            "equipment":["Longsword","Chainmail"],
            "inventory":"2 x Rations\nLongsword",
            "biography":"A stern watch captain with a hidden oath.",
            "languages":["Common"],"class_features":["Bonus fighter feat"]}
        d=CharacterCreatorDialog()
        d.race.setCurrentText("Human")
        d.character_class.setCurrentText("Fighter")
        d.creation_mode.setCurrentIndex(1)
        with patch("dndgm4.roll_ui.AIWritingDialog") as ai:
            ai.return_value.exec.return_value=QDialog.DialogCode.Accepted
            ai.return_value.generated_text=json.dumps(payload)
            d.generate_complete_character()
            self.assertEqual(ai.call_args.args[0],"character_build")
        self.assertTrue(d.ai_draft_applied)
        self.assertEqual(d.name.text(),"Captain Reeve")
        self.assertEqual(d.base_scores()["strength"],16)
        self.assertIn("hidden oath",d.options.background.toPlainText())
        self.assertEqual(d.method.currentData(),"manual")
        self.assertIsNone(d.result_creature)
        d.save_character()
        self.assertEqual(d.result_creature.name,"Captain Reeve")
        self.assertEqual(load_sheet(d.result_creature)["feats"],
                         ["Power Attack","Cleave"])
        d.close()

    def test_guided_invalid_feat_prevents_saving(self):
        from dndgm4.roll_ui import CharacterCreatorDialog
        d=CharacterCreatorDialog()
        d.name.setText("Low Strength Fighter")
        d.race.setCurrentText("Human")
        d.character_class.setCurrentText("Fighter")
        d.method.setCurrentIndex(2)
        d.creation_mode.setCurrentIndex(2)
        d.options.feats.setPlainText("Power Attack")
        with patch("dndgm4.roll_ui.QMessageBox.warning") as warning:
            d.save_character()
            warning.assert_called_once()
        self.assertIsNone(d.result_creature)
        d.close()

if __name__=="__main__":
    unittest.main()
