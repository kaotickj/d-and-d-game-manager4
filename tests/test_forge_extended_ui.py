"""Headless integration checks for complete Forge tabs and narrator access."""
from importlib.util import find_spec
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
import os, unittest


@unittest.skipUnless(find_spec("PyQt6") is not None, "PyQt6 not installed")
class ForgeUiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.environ.setdefault("QT_QPA_PLATFORM","offscreen")
        from PyQt6.QtWidgets import QApplication
        from dndgm4.theme import apply_theme
        cls.app = QApplication.instance() or QApplication([])
        apply_theme(cls.app)

    def test_core_preset_and_manual_overrides_save(self):
        from dndgm4.roll_ui import CharacterCreatorDialog
        from dndgm4.character_sheet import load_sheet
        dialog=CharacterCreatorDialog()
        dialog.name.setText("Ebon")
        dialog.race.setCurrentText("Human")
        dialog.character_class.setCurrentText("Fighter")
        dialog.method.setCurrentIndex(2)
        dialog.score_inputs["intelligence"].setValue(12)
        dialog.options.apply_preset()
        self.assertTrue(dialog.options.feats.toPlainText().strip())
        self.assertIn("Skill points:",dialog.options.skill_budget_label.text())
        dialog.options.feats.setPlainText("Power Attack\nToughness")
        dialog.options.alignment.setCurrentText("Chaotic Good")
        dialog.options.background.setPlainText("Village champion")
        dialog.save_character()
        self.assertIsNotNone(dialog.result_creature)
        sheet=load_sheet(dialog.result_creature)
        self.assertEqual(sheet["feats"],["Power Attack","Toughness"])
        self.assertEqual(sheet["background"],"Village champion")
        self.assertEqual(sheet["alignment"],"Chaotic Good")
        dialog.close()

    def test_special_and_homebrew_class_edit(self):
        from dndgm4.roll_ui import CharacterCreatorDialog
        from dndgm4.character_sheet import load_sheet
        dialog=CharacterCreatorDialog()
        dialog.name.setText("Kar")
        dialog.method.setCurrentIndex(2)
        dialog.character_class.setCurrentText("Warlock")
        self.assertTrue(dialog.options.spec().supplement)
        dialog.save_character()
        self.assertEqual(dialog.result_creature.character_class,"Warlock")
        dialog.close()
        other=CharacterCreatorDialog()
        other.name.setText("Oracle")
        other.method.setCurrentIndex(2)
        other.character_class.setCurrentIndex(other.character_class.count()-1)
        other.options.custom_class_name.setText("Oracle Knight")
        other.options.hit_die.setValue(12)
        other.options.sp_rate.setValue(5)
        other.save_character()
        self.assertEqual(other.result_creature.character_class,"Oracle Knight")
        self.assertEqual(other.result_creature.max_hit_points,12)
        other.close()

    def test_edit_existing_sheet_preserves_record_id(self):
        from dndgm4.roll_ui import CharacterCreatorDialog
        from dndgm4.storage import CreatureRepository
        from dndgm4.character_sheet import load_sheet
        with TemporaryDirectory() as tmp:
            repo=CreatureRepository(Path(tmp)/"x.sqlite3")
            first=CharacterCreatorDialog()
            first.name.setText("Kara")
            first.method.setCurrentIndex(2)
            first.save_character()
            original=repo.save(first.result_creature)
            first.close()
            editor=CharacterCreatorDialog(creature=original)
            editor.options.equipment.setPlainText("Spear\nTravel pack")
            editor.save_character()
            self.assertEqual(editor.result_creature.id,original.id)
            saved=repo.save(editor.result_creature)
            self.assertEqual(load_sheet(repo.get(saved.id))["equipment"],["Spear","Travel pack"])
            editor.close()

    def test_scribe_switches_qwen_gemma_for_each_biography(self):
        from dndgm4.ai_ui import AIWritingDialog
        from dndgm4.local_ai import GGUF_MODELS
        for kind in ("bio", "npc_bio", "monster_bio"):
            with self.subTest(kind=kind):
                dialog = AIWritingDialog(kind, "Original campaign")
                self.assertTrue(dialog.use.text() == "Use Draft")
                self.assertEqual(
                    dialog.model.text(),
                    str(GGUF_MODELS["Gemma The Writer 9B (GGUF)"]))
                dialog.preset.setCurrentIndex(0)
                self.assertEqual(
                    dialog.model.text(),
                    str(GGUF_MODELS["Qwen3 4B Instruct (GGUF)"]))
                dialog.close()

    def test_closing_narrator_keeps_main_window_open(self):
        from dndgm4.storage import CreatureRepository
        from dndgm4.ui import MainWindow
        from PyQt6.QtCore import Qt
        with TemporaryDirectory() as tmp:
            win = MainWindow(CreatureRepository(Path(tmp) / "library.sqlite3"))
            win.show()
            self.app.processEvents()
            self.assertTrue(win.isVisible())
            win.open_narrator()
            self.app.processEvents()
            narrator = win._narrator_dialog
            self.assertIsNotNone(narrator)
            self.assertTrue(narrator.isVisible())
            self.assertFalse(narrator.testAttribute(Qt.WidgetAttribute.WA_QuitOnClose))
            self.assertEqual(narrator.windowModality(), Qt.WindowModality.NonModal)
            win.open_narrator()
            self.assertIs(win._narrator_dialog, narrator)
            narrator.close()
            self.app.processEvents()
            self.assertTrue(win.isVisible())
            self.assertFalse(narrator.isVisible())
            self.assertIs(win._narrator_dialog, narrator)
            # The sidebar can reopen the same dialog; closing it a second
            # time must not end the compendium.
            win.open_narrator()
            self.app.processEvents()
            self.assertIs(win._narrator_dialog, narrator)
            self.assertTrue(narrator.isVisible())
            narrator.use.click()
            self.app.processEvents()
            self.assertTrue(win.isVisible())
            self.assertFalse(narrator.isVisible())
            win.close()

    def test_dm_sidebar_action_and_local_ai_no_auto_calls(self):
        from PyQt6.QtWidgets import QPushButton
        from dndgm4.ui import MainWindow
        from dndgm4.storage import CreatureRepository
        from dndgm4.ai_ui import AIWritingDialog
        with TemporaryDirectory() as tmp:
            win=MainWindow(CreatureRepository(Path(tmp)/"library.sqlite3"))
            self.assertTrue(any("DM Narration" in x.text()
                                for x in win.findChildren(QPushButton)))
            with patch("dndgm4.ui.AIWritingDialog") as dlg:
                win.open_narrator()
                dlg.assert_called_once()
            win.close()
        d=AIWritingDialog("bio","a human ranger")
        from dndgm4.local_ai import GGUF_MODELS, DEFAULT_OLLAMA_MODEL
        self.assertEqual(d.backend.currentData(), "gguf")
        self.assertEqual(d.model.text(), str(GGUF_MODELS["Gemma The Writer 9B (GGUF)"]))
        d.preset.setCurrentIndex(0)
        self.assertEqual(d.model.text(), str(GGUF_MODELS["Qwen3 4B Instruct (GGUF)"]))
        d.backend.setCurrentIndex(1)
        self.assertEqual(d.model.text(), DEFAULT_OLLAMA_MODEL)
        d.backend.setCurrentIndex(0)
        self.assertEqual(d.model.text(), str(GGUF_MODELS["Qwen3 4B Instruct (GGUF)"]))
        self.assertFalse(d.worker)
        d.close()


if __name__=="__main__":
    unittest.main()
