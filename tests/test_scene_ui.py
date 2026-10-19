"""Offscreen tests for multi-selection, scene roster and Scribe integration."""
import json
import os
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from importlib.util import find_spec

@unittest.skipUnless(find_spec("PyQt6"), "PyQt6 not installed")
class SelectionIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.environ.setdefault("QT_QPA_PLATFORM","offscreen")
        from PyQt6.QtWidgets import QApplication
        from dndgm4.theme import apply_theme
        cls.app=QApplication.instance() or QApplication([])
        apply_theme(cls.app)

    @staticmethod
    def populate(repo):
        from dndgm4.models import Creature
        pc=repo.save(Creature(name="Eldrin",kind="pc",race_type="Elf",
            character_class="Wizard",intelligence=18,
            sheet_json=json.dumps({"feats":["Combat Casting"],
                                   "spell_notes":"Magic Missile"})))
        npc=repo.save(Creature(name="Marta",kind="npc",race_type="Human",
            character_class="Expert",sheet_json=json.dumps({
                "background":"Runs the Fox and Fiddle Inn."})))
        beast=repo.save(Creature(name="Bog Sentry",kind="monster",
            race_type="Original Bog Sentry",character_class="Plant",
            sheet_json=json.dumps({"monster_type":"Plant",
                                   "special_qualities":"Tremorsense",
                                   "computed":{"bab":3}})))
        return pc,npc,beast

    def test_ctrl_shift_multiselect_and_direct_scribe_loading(self):
        from PyQt6.QtCore import QItemSelectionModel,Qt
        from PyQt6.QtWidgets import QAbstractItemView
        from dndgm4.ui import MainWindow
        from dndgm4.storage import CreatureRepository
        with TemporaryDirectory() as d:
            repo=CreatureRepository(Path(d)/"db.sqlite3")
            records=self.populate(repo)
            window=MainWindow(repo)
            window.show()
            self.app.processEvents()
            self.assertEqual(window.table.selectionMode(),
                QAbstractItemView.SelectionMode.ExtendedSelection)
            self.assertEqual(window.table.selectionBehavior(),
                QAbstractItemView.SelectionBehavior.SelectRows)
            for row in range(window.table.rowCount()):
                window.table.selectionModel().select(
                    window.table.model().index(row,0),
                    QItemSelectionModel.SelectionFlag.Select |
                    QItemSelectionModel.SelectionFlag.Rows)
            self.app.processEvents()
            self.assertEqual(len(window.selected_records()),3)
            self.assertIsNone(window.selected())  # no ambiguous bulk edit
            self.assertFalse(window.edit_button.isEnabled())
            window.load_selection_to_scribe()
            self.app.processEvents()
            prompt=window._narrator_dialog.context.toPlainText()
            for word in ("Eldrin","Marta","Bog Sentry","Magic Missile",
                         "Tremorsense","Fox and Fiddle"):
                self.assertIn(word,prompt)
            self.assertIn("Explicitly loaded records: 3",prompt)
            window._narrator_dialog.use.click()
            self.app.processEvents()
            self.assertTrue(window.isVisible())
            window.close()

    def test_add_across_filtered_types_and_reopen_saved_scene(self):
        from dndgm4.ui import MainWindow
        from dndgm4.storage import CreatureRepository
        with TemporaryDirectory() as d:
            repo=CreatureRepository(Path(d)/"db.sqlite3")
            records=self.populate(repo)
            win=MainWindow(repo)
            win.change_section("pc")
            win.table.selectRow(0)
            win.add_selection_to_scene()
            win.change_section("npc")
            win.table.selectRow(0)
            win.add_selection_to_scene()
            win.change_section("monster")
            win.table.selectRow(0)
            win.add_selection_to_scene()
            self.assertEqual(len(win.scene["record_ids"]),3)
            win.scene["places"]="Fox and Fiddle Inn in Hollowford"
            win.scene_store.save(win.scene)
            win.close()
            second=MainWindow(repo)
            self.assertEqual(len(second.scene["record_ids"]),3)
            self.assertIn("Hollowford",second.scene["places"])
            second.show()
            second.load_scene_to_scribe()
            self.app.processEvents()
            prompt=second._narrator_dialog.context.toPlainText()
            self.assertIn("Fox and Fiddle Inn",prompt)
            for record in records:
                self.assertIn(record.name,prompt)
            second._narrator_dialog.use.click()
            second.close()

    def test_other_child_dialog_closures_keep_parent_open(self):
        from PyQt6.QtCore import Qt
        from dndgm4.ui import MainWindow,CreatureEditor
        from dndgm4.storage import CreatureRepository
        from dndgm4.models import Creature
        from dndgm4.roll_ui import DiceDialog,CharacterCreatorDialog
        from dndgm4.monster_ui import MonsterCreatorDialog
        from dndgm4.name_ui import NamePickerDialog
        from dndgm4.scene_ui import SceneDialog
        from dndgm4.scene_context import blank_scene
        with TemporaryDirectory() as d:
            win=MainWindow(CreatureRepository(Path(d)/"db.sqlite3"))
            win.show()
            self.app.processEvents()
            children=[
                DiceDialog(win),
                NamePickerDialog(parent=win,standalone=True),
                CreatureEditor(Creature(name="Sample"),win),
                CharacterCreatorDialog(win),
                MonsterCreatorDialog(win),
                SceneDialog(blank_scene(),[],win),
            ]
            for dialog in children:
                with self.subTest(kind=type(dialog).__name__):
                    self.assertFalse(dialog.testAttribute(
                        Qt.WidgetAttribute.WA_QuitOnClose))
                    dialog.show()
                    self.app.processEvents()
                    dialog.close()
                    self.app.processEvents()
                    self.assertTrue(win.isVisible())
            win.close()

if __name__=="__main__":
    unittest.main()
