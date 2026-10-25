"""Run Session uses the real workspace and live combat controller safely."""
from importlib.util import find_spec
from pathlib import Path
from tempfile import TemporaryDirectory
import os
import sqlite3
import unittest
from unittest.mock import patch


@unittest.skipUnless(find_spec("PyQt6") is not None, "PyQt6 unavailable")
class RunSessionIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        from PyQt6.QtWidgets import QApplication
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        from dndgm4.campaigns import ActiveWorkspace
        from dndgm4.models import Creature
        from dndgm4.storage import CreatureRepository
        from dndgm4.ui import MainWindow
        self.tmp = TemporaryDirectory()
        self.library = CreatureRepository(Path(self.tmp.name) / "library.sqlite3")
        self.pc = self.library.save(Creature(name="Rowan", max_hit_points=18))
        self.window = MainWindow(self.library)
        self.repo = self.window.campaigns
        self.campaign = self.repo.create_campaign("Glass Road")
        self.session = self.repo.create_session(self.campaign.id, "The bridge")
        self.repo.set_party(self.campaign.id, [self.pc.id])
        self.window.switch_workspace(ActiveWorkspace(self.campaign.id, self.session.id))

    def tearDown(self):
        if self.window._session_window is not None:
            self.window._session_window.note_input.clear()
            self.window._session_window.hide()
        self.window.close()
        self.tmp.cleanup()

    def populate(self):
        self.window.scene["record_ids"] = [self.pc.id]
        self.window._run_session_action("add_scene")
        return self.window._battle_window.battle.fighters[0].uid

    def test_open_and_roll_do_not_create_encounter_or_change_campaign(self):
        before = self.repo.get_session(self.session.id)
        first = self.window.open_run_session()
        self.assertIs(first, self.window.open_run_session())
        self.assertEqual(first.party.rowCount(), 1)
        self.assertEqual(self.repo.list_encounters(self.session.id), [])
        self.assertIsNone(self.window._battle_window)
        result = self.window._run_session_action("roll", expression="1d20+3")
        self.assertIn("1d20+3:", result)
        self.assertEqual(self.repo.list_encounters(self.session.id), [])
        self.assertEqual(self.repo.get_session(self.session.id), before)

    def test_dashboard_and_tracker_share_live_instances_and_save_only_encounter_hp(self):
        uid = self.populate()
        tracker = self.window._battle_window
        self.assertFalse(tracker.isVisible())
        self.window._run_session_action("add_scene")
        self.assertEqual(len(tracker.battle.fighters), 1)
        self.window._run_session_action("damage", combatant_id=uid, amount=5)
        self.assertIs(self.window.open_battle_trakker(), tracker)
        self.assertEqual(self.window._run_session_snapshot()["fighters"][0]["hp"], 13)
        self.assertEqual(self.repo.load_battle(self.window.workspace.encounter_id).get(uid).hp, 13)
        tracker.battle.get(uid).hp = 11
        self.assertEqual(self.window._run_session_snapshot()["fighters"][0]["hp"], 11)
        self.assertEqual(self.library.get(self.pc.id), self.pc)

    def test_failed_combat_save_rolls_back_live_hp_history_and_saved_encounter(self):
        uid = self.populate()
        tracker = self.window._battle_window
        before, history = tracker.battle.snapshot(), list(tracker.battle._history)
        with patch.object(tracker.store, "save", side_effect=sqlite3.OperationalError("Disk full")):
            with self.assertRaises(sqlite3.OperationalError):
                self.window._run_session_action("damage", combatant_id=uid, amount=7)
        self.assertEqual(tracker.battle.snapshot(), before)
        self.assertEqual(tracker.battle._history, history)
        self.assertEqual(self.repo.load_battle(self.window.workspace.encounter_id).snapshot(), before)
        self.assertEqual(self.library.get(self.pc.id), self.pc)

    def test_cancelled_workspace_change_retains_note_and_active_session(self):
        from dndgm4.campaigns import ActiveWorkspace
        from PyQt6.QtWidgets import QMessageBox
        dashboard = self.window.open_run_session()
        dashboard.note_input.setPlainText("The party rescued the courier.")
        second = self.repo.create_session(self.campaign.id, "Marsh trail")
        before = self.window.workspace
        with patch("dndgm4.run_session_ui.QMessageBox.question", return_value=QMessageBox.StandardButton.Cancel):
            self.assertFalse(self.window.switch_workspace(ActiveWorkspace(self.campaign.id, second.id)))
        self.assertEqual(self.window.workspace, before)
        self.assertEqual(self.repo.get_workspace(), before)
        self.assertEqual(dashboard.note_input.toPlainText(), "The party rescued the courier.")
        self.assertEqual(self.repo.get_session(self.session.id).notes, "")

    def test_note_save_targets_active_session_and_does_not_change_recap(self):
        from dataclasses import replace
        self.repo.save_session(replace(self.session, recap="Confirmed events"))
        self.window._run_session_action("save_note", session_id=self.session.id,
                                        note="Courier rescued", expected_notes="")
        saved = self.repo.get_session(self.session.id)
        self.assertEqual(saved.notes, "Courier rescued")
        self.assertEqual(saved.recap, "Confirmed events")
        second = self.repo.create_session(self.campaign.id, "Another session")
        with self.assertRaisesRegex(ValueError, "different session"):
            self.window._run_session_action("save_note", session_id=second.id,
                                            note="Wrong target", expected_notes="")
        self.assertEqual(self.repo.get_session(second.id).notes, "")

    def test_unreadable_destination_preserves_dirty_note_without_prompting_discard(self):
        from dndgm4.campaigns import ActiveWorkspace
        dashboard = self.window.open_run_session()
        dashboard.note_input.setPlainText("The courier is safe.")
        second = self.repo.create_session(self.campaign.id, "Bad scene")
        with self.repo._connection() as db:
            db.execute("UPDATE sessions SET scene_json=? WHERE id=?", ("{bad", second.id))
        before = self.window.workspace
        with patch.object(dashboard, "prepare_workspace_change") as guard:
            with self.assertRaises(ValueError):
                self.window.switch_workspace(ActiveWorkspace(self.campaign.id, second.id))
        guard.assert_not_called()
        self.assertEqual(self.window.workspace, before)
        self.assertEqual(dashboard.note_input.toPlainText(), "The courier is safe.")

    def test_closing_main_window_can_be_cancelled_without_losing_note(self):
        from PyQt6.QtGui import QCloseEvent
        dashboard = self.window.open_run_session()
        dashboard.note_input.setPlainText("Keep this draft")
        event = QCloseEvent()
        with patch.object(dashboard, "prepare_workspace_change", return_value=False):
            self.window.closeEvent(event)
        self.assertFalse(event.isAccepted())
        self.assertEqual(dashboard.note_input.toPlainText(), "Keep this draft")
