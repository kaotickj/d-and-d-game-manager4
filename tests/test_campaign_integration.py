"""Campaign workspace changes preserve scenes, combat, and library templates."""
from importlib.util import find_spec
from contextlib import closing
from pathlib import Path
import os
import sqlite3
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch


@unittest.skipUnless(find_spec("PyQt6") is not None, "PyQt6 is not installed")
class CampaignIntegrationTests(unittest.TestCase):
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
        self.pc = self.library.save(Creature(name="Rowan", character_class="Fighter", max_hit_points=18))
        self.enemy = self.library.save(Creature(name="Sentry", kind="monster", max_hit_points=9))
        self.window = MainWindow(self.library)
        self.repo = self.window.campaigns
        self.campaign = self.repo.create_campaign("The Glass Road", notes="The bridge is watched.")
        self.first = self.repo.create_session(self.campaign.id, "At the bridge")
        self.second = self.repo.create_session(self.campaign.id, "Beyond the marsh")
        self.encounter = self.repo.create_encounter(self.first.id, "Bridge sentries")
        self.other_encounter = self.repo.create_encounter(self.second.id, "Marsh trail")
        self.first_workspace = ActiveWorkspace(self.campaign.id, self.first.id, self.encounter.id)
        self.second_workspace = ActiveWorkspace(self.campaign.id, self.second.id, self.other_encounter.id)

    def tearDown(self):
        if self.window._battle_window is not None:
            self.window._battle_window.hide()
        self.window.close()
        self.tmp.cleanup()

    def test_switch_and_restart_resume_independent_encounters_and_scenes(self):
        from dndgm4.ui import MainWindow
        self.window.switch_workspace(self.first_workspace)
        self.window.scene["location"] = "Broken bridge"
        tracker = self.window.open_battle_trakker()
        tracker._run(lambda: tracker._add_records([self.pc, self.enemy]))
        uid = tracker.battle.fighters[0].uid
        tracker.battle.fighters[0].hp = 7
        tracker.encounter_title.setText("Sentries at dusk")
        self.window.switch_workspace(self.second_workspace)
        second = self.window.open_battle_trakker()
        self.assertEqual(second.battle.fighters, [])
        self.assertEqual(self.window.scene["location"], "")
        self.assertEqual(self.repo.get_encounter(self.encounter.id).title, "Sentries at dusk")
        self.window.scene["location"] = "Reed island"
        self.window.switch_workspace(self.first_workspace)
        restored = self.window.open_battle_trakker()
        self.assertEqual(restored.battle.get(uid).hp, 7)
        self.assertEqual(self.window.scene["location"], "Broken bridge")
        self.assertEqual(self.repo.load_scene(self.second.id)["location"], "Reed island")
        self.assertEqual(self.library.get(self.pc.id), self.pc)
        self.assertEqual(self.library.get(self.enemy.id), self.enemy)
        self.window.close()
        self.window = MainWindow(self.library)
        self.assertEqual(self.window.workspace, self.first_workspace)
        self.assertEqual(self.window.scene["location"], "Broken bridge")
        self.assertEqual(self.window.open_battle_trakker().battle.get(uid).hp, 7)

    def test_reopening_same_session_does_not_lose_pending_scene_changes(self):
        self.window.switch_workspace(self.first_workspace)
        self.window.scene["scenery"] = "Fresh marks in the mud"
        self.window.switch_workspace(self.first_workspace)
        self.assertEqual(self.window.scene["scenery"], "Fresh marks in the mud")
        self.assertEqual(self.repo.load_scene(self.first.id)["scenery"], "Fresh marks in the mud")

    def test_failed_current_battle_save_blocks_switch_without_losing_state(self):
        self.window.switch_workspace(self.first_workspace)
        tracker = self.window.open_battle_trakker()
        tracker._run(lambda: tracker._add_records([self.pc]))
        before = tracker.battle.snapshot()
        with patch.object(tracker.store, "save", side_effect=sqlite3.OperationalError("Database full")):
            with self.assertRaises(sqlite3.OperationalError):
                self.window.switch_workspace(self.second_workspace)
        self.assertEqual(self.window.workspace, self.first_workspace)
        self.assertEqual(self.repo.get_workspace(), self.first_workspace)
        self.assertIs(self.window._battle_window, tracker)
        self.assertEqual(tracker.battle.snapshot(), before)

    def test_invalid_destination_ownership_keeps_current_workspace(self):
        from dndgm4.campaigns import ActiveWorkspace
        self.window.switch_workspace(self.first_workspace)
        wrong = ActiveWorkspace(self.campaign.id, self.second.id, self.encounter.id)
        with self.assertRaises(ValueError):
            self.window.switch_workspace(wrong)
        self.assertEqual(self.window.workspace, self.first_workspace)
        self.assertEqual(self.repo.get_workspace(), self.first_workspace)

    def test_corrupt_target_scene_is_not_overwritten(self):
        self.window.switch_workspace(self.first_workspace)
        with closing(sqlite3.connect(self.library.path)) as db:
            db.execute("UPDATE sessions SET scene_json=? WHERE id=?", ("{broken", self.second.id))
            db.commit()
        with self.assertRaises(ValueError):
            self.window.switch_workspace(self.second_workspace)
        with closing(sqlite3.connect(self.library.path)) as db:
            self.assertEqual(db.execute("SELECT scene_json FROM sessions WHERE id=?",
                                        (self.second.id,)).fetchone()[0], "{broken")
        self.assertEqual(self.window.workspace, self.first_workspace)

    def test_party_load_is_explicit_and_archived_members_are_reported(self):
        self.repo.set_party(self.campaign.id, [self.pc.id])
        self.window.switch_workspace(self.first_workspace)
        self.assertEqual(self.window.scene["record_ids"], [])
        self.window.add_party_to_scene()
        self.assertEqual(self.repo.load_scene(self.first.id)["record_ids"], [self.pc.id])
        self.library.set_archived(self.pc.id, True)
        before = dict(self.window.scene)
        with patch("dndgm4.ui.QMessageBox.warning") as warning:
            self.window.add_party_to_scene()
        warning.assert_called_once()
        self.assertEqual(self.window.scene, before)

    def test_campaign_without_encounter_does_not_read_standalone_combat(self):
        from dndgm4.battle_advanced import AdvancedBattle, AdvancedBattleStore
        from dndgm4.battle_rules import fighter_from_record
        from dndgm4.campaigns import ActiveWorkspace
        standalone = AdvancedBattle(title="Standalone fight")
        standalone.add(fighter_from_record(self.enemy))
        AdvancedBattleStore(self.library.path).save(standalone)
        self.window.switch_workspace(ActiveWorkspace(self.campaign.id, self.first.id))
        with patch("dndgm4.ui.QMessageBox.warning") as warning, \
                patch.object(self.window, "_open_scribe_with_context") as writer:
            self.window.discuss_battle()
        warning.assert_called_once()
        writer.assert_not_called()
        self.assertEqual(AdvancedBattleStore(self.library.path).load().title, "Standalone fight")

    def test_scribe_uses_campaign_and_session_notes_without_starting_inference(self):
        from dataclasses import replace
        self.repo.save_session(replace(self.first, notes="The party negotiated safe passage."))
        self.repo.set_party(self.campaign.id, [self.pc.id])
        self.window.switch_workspace(self.first_workspace)
        context = self.window._scribe_scene_context("scene")
        self.assertIn("The Glass Road", context)
        self.assertIn("The party negotiated safe passage.", context)
        self.assertIn("Rowan", context)
        with patch.object(self.window, "_open_scribe_with_context") as writer:
            self.window.open_campaign_scribe(self.first.id, "recap")
        self.assertEqual(writer.call_args.kwargs["task"], "recap")

    def test_session_with_no_encounters_creates_independent_first_battle_on_request(self):
        from dndgm4.campaigns import ActiveWorkspace
        session = self.repo.create_session(self.campaign.id, "Session without combat")
        self.window.switch_workspace(ActiveWorkspace(self.campaign.id, session.id))
        self.assertEqual(self.repo.list_encounters(session.id), [])
        tracker = self.window.open_battle_trakker()
        self.assertEqual(tracker.battle.fighters, [])
        self.assertEqual(len(self.repo.list_encounters(session.id)), 1)
        self.assertEqual(self.window.workspace.encounter_id, self.repo.list_encounters(session.id)[0].id)

    def test_explicit_standalone_import_keeps_source_files_and_battle_instances(self):
        from PyQt6.QtWidgets import QDialog
        from dndgm4.campaigns import ActiveWorkspace
        from dndgm4.scene_context import SceneStore
        from dndgm4.battle_advanced import AdvancedBattleStore
        self.window.scene["location"] = "Old local camp"
        tracker = self.window.open_battle_trakker()
        tracker._run(lambda: tracker._add_records([self.pc]))
        tracker.battle.fighters[0].hp = 6
        tracker._save()
        self.window.scene_store.save(self.window.scene)
        scene_path = SceneStore(self.library.path).path
        battle_path = AdvancedBattleStore(self.library.path).path
        scene_before, battle_before = scene_path.read_bytes(), battle_path.read_bytes()
        with patch("dndgm4.campaign_ui.CampaignManagerDialog") as factory:
            dialog = factory.return_value
            dialog.exec.return_value = QDialog.DialogCode.Accepted
            dialog.result_action = "legacy_import"
            dialog.result_workspace = ActiveWorkspace(self.campaign.id)
            self.window.open_campaigns()
        self.assertNotEqual(self.window.workspace.session_id, self.first.id)
        self.assertEqual(self.window.scene["location"], "Old local camp")
        self.assertEqual(self.window.open_battle_trakker().battle.fighters[0].hp, 6)
        self.assertEqual(scene_path.read_bytes(), scene_before)
        self.assertEqual(battle_path.read_bytes(), battle_before)

    def test_campaign_planning_before_first_session_has_explicit_context(self):
        campaign = self.repo.create_campaign("Unwritten campaign", notes="A valley cut off by winter.")
        with patch.object(self.window, "_open_scribe_with_context") as writer:
            self.window.open_campaign_scribe("", "campaign_plan", campaign_id=campaign.id)
        self.assertIn("Unwritten campaign", writer.call_args.args[0])
        self.assertIn("A valley cut off by winter.", writer.call_args.args[0])
        self.assertEqual(writer.call_args.kwargs["task"], "campaign_plan")
        self.assertEqual(self.repo.list_sessions(campaign.id), [])
