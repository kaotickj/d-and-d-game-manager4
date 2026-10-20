"""Offscreen PyQt smoke tests for Battle Trakker and Compendium integration."""
from importlib.util import find_spec
from pathlib import Path
from tempfile import TemporaryDirectory
import os
import unittest
from unittest.mock import patch


@unittest.skipUnless(find_spec("PyQt6") is not None,"PyQt6 unavailable")
class BattleTrackerGuiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.environ.setdefault("QT_QPA_PLATFORM","offscreen")
        from PyQt6.QtWidgets import QApplication
        from dndgm4.theme import apply_theme
        cls.app=QApplication.instance() or QApplication([])
        apply_theme(cls.app)

    @staticmethod
    def setup_library(folder):
        from dndgm4.models import Creature
        from dndgm4.storage import CreatureRepository
        repo=CreatureRepository(Path(folder)/"library.sqlite3")
        pc=repo.save(Creature(name="Lady Valor",kind="pc",level=3,
                             max_hit_points=20,dexterity=16))
        npc=repo.save(Creature(name="Borin Smith",kind="npc",
                              max_hit_points=15))
        mon=repo.save(Creature(name="Bog Slime",kind="monster",
                              max_hit_points=9,armor_class=11))
        return repo,pc,npc,mon

    def test_main_window_battle_trakker_modeless_and_safe_close(self):
        from dndgm4.ui import MainWindow
        from PyQt6.QtCore import Qt
        from PyQt6.QtWidgets import QApplication
        with TemporaryDirectory() as folder:
            repo,pc,npc,mon=self.setup_library(folder)
            window=MainWindow(repo)
            window.show()
            self.app.processEvents()
            self.assertTrue(window.isVisible())
            tracker=window.open_battle_trakker()
            self.assertIsNotNone(tracker)
            self.app.processEvents()
            self.assertTrue(tracker.isVisible())
            self.assertFalse(tracker.testAttribute(
                Qt.WidgetAttribute.WA_QuitOnClose))
            self.assertEqual(tracker.windowTitle(),
                             "Battle Trakker | D&D 3.5 Combat Manager")
            tracker.close()
            self.app.processEvents()
            self.assertTrue(window.isVisible())
            self.assertFalse(tracker.isVisible())
            self.assertIs(window.open_battle_trakker(),tracker)
            self.assertTrue(tracker.isVisible())
            tracker.close()
            window.close()

    def test_add_selected_records_and_resume_after_app_reopen(self):
        from dndgm4.ui import MainWindow
        from dndgm4.battle_rules import BattleStore
        from PyQt6.QtCore import QItemSelectionModel,Qt
        with TemporaryDirectory() as folder:
            repo,pc,npc,mon=self.setup_library(folder)
            win=MainWindow(repo)
            win.show()
            self.app.processEvents()
            for row in range(win.table.rowCount()):
                win.table.selectionModel().select(
                    win.table.model().index(row,0),
                    QItemSelectionModel.SelectionFlag.Select |
                    QItemSelectionModel.SelectionFlag.Rows)
            self.assertEqual(len(win.selected_records()),3)
            win.load_selection_to_battle()
            self.app.processEvents()
            tracker=win._battle_window
            self.assertEqual(len(tracker.battle.fighters),3)
            self.assertEqual(tracker.table.rowCount(),3)
            self.assertEqual({f.kind for f in tracker.battle.fighters},
                             {"pc","npc","monster"})
            # Manual initiative and buttons work without modifying library HP.
            uid=next(f.uid for f in tracker.battle.fighters if f.kind=="pc")
            for row in range(tracker.table.rowCount()):
                if tracker.table.item(row,1).data(Qt.ItemDataRole.UserRole)==uid:
                    tracker.table.selectRow(row)
                    break
            tracker.initiative_input.setValue(17)
            tracker.set_initiative()
            self.assertEqual(tracker.battle.get(uid).initiative,17)
            tracker.table.selectRow(0)
            tracker.hp_amount.setValue(5)
            tracker.damage()
            self.assertEqual(tracker.battle.get(uid).hp,15)
            self.assertEqual(repo.get(pc.id).max_hit_points,20)
            tracker.save()
            tracker.close()
            win.close()

            second=MainWindow(repo)
            second.show()
            restored=second.open_battle_trakker()
            self.app.processEvents()
            self.assertEqual(len(restored.battle.fighters),3)
            self.assertEqual(restored.battle.get(uid).hp,15)
            self.assertEqual(restored.battle.get(uid).initiative,17)
            self.assertFalse(restored.log_display.toPlainText()=="")
            restored.close()
            second.close()

    def test_add_scene_roster_and_independent_enemy_copies(self):
        from dndgm4.battle_ui import BattleTrakkerDialog
        from dndgm4.battle_rules import BattleStore
        with TemporaryDirectory() as folder:
            repo,pc,npc,mon=self.setup_library(folder)
            scene={"record_ids":[pc.id,mon.id],
                   "location":"Borin's Forge",
                   "time_conditions":"Storm outside",
                   "scenery":"Cobbled courtyard",
                   "campaign_notes":"Seeking the relic"}
            dialog=BattleTrakkerDialog(repo,scene=scene)
            dialog.show()
            self.app.processEvents()
            dialog.add_scene()
            self.assertEqual(len(dialog.battle.fighters),2)
            self.assertIn("Borin's Forge",dialog.battle.scene)
            dialog._run(lambda:dialog._add_records([mon],quantity=3))
            self.assertEqual(len(dialog.battle.fighters),5)
            copies=[f for f in dialog.battle.fighters if f.source_id==mon.id]
            self.assertEqual(len(copies),4)
            self.assertEqual(len({f.uid for f in copies}),4)
            dialog.roll_initiative()
            dialog.start()
            self.assertEqual(dialog.battle.round,1)
            dialog.advance()
            self.assertEqual(dialog.battle.phase,"combat")
            dialog.close()
            self.assertEqual(len(BattleStore(repo.path).load().fighters),5)

    def test_custom_combatant_and_condition_controls(self):
        from dndgm4.battle_ui import BattleTrakkerDialog,CustomCombatantDialog
        from PyQt6.QtWidgets import QDialog
        with TemporaryDirectory() as folder:
            repo, *_=self.setup_library(folder)
            tracker=BattleTrakkerDialog(repo)
            custom=CustomCombatantDialog(tracker)
            custom.name.setText("Falling Rocks")
            custom.hp.setValue(22)
            fighter=custom.fighter()
            tracker._run(lambda:tracker.battle.add(fighter))
            tracker.table.selectRow(0)
            tracker.condition.setCurrentText("Stunned")
            tracker.duration.setValue(2)
            tracker.apply_condition()
            self.assertEqual(tracker.battle.get(fighter.uid).conditions,
                             [{"name":"Stunned","rounds":2}])
            tracker.remove_condition()
            self.assertEqual(tracker.battle.get(fighter.uid).conditions,[])
            tracker.surprised.click()
            self.assertTrue(tracker.battle.get(fighter.uid).surprised)
            tracker.note_input.setText("DM: the ceiling shakes")
            tracker.add_log_note()
            self.assertIn("ceiling shakes",tracker.log_display.toPlainText())
            tracker.close()

    def test_missing_scene_member_never_changes_roster(self):
        from dndgm4.battle_ui import BattleTrakkerDialog
        with TemporaryDirectory() as folder:
            repo,*_=self.setup_library(folder)
            tracker=BattleTrakkerDialog(repo,scene={"record_ids":["missing"]})
            with patch("dndgm4.battle_ui.QMessageBox.warning") as popup:
                tracker.add_scene()
                popup.assert_called_once()
            self.assertEqual(tracker.battle.fighters,[])
            tracker.close()


if __name__ == "__main__":
    unittest.main()
