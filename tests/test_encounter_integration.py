"""Reviewed encounter handoffs preserve templates and existing combat state."""
from importlib.util import find_spec
from pathlib import Path
import os
import random
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch


@unittest.skipUnless(find_spec("PyQt6") is not None, "PyQt6 is not installed")
class EncounterIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        from PyQt6.QtWidgets import QApplication
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        from dndgm4.encounter_generator import generate_encounter
        from dndgm4.models import Creature
        from dndgm4.storage import CreatureRepository
        from dndgm4.ui import MainWindow
        self.tmp = TemporaryDirectory()
        self.repo = CreatureRepository(Path(self.tmp.name) / "library.sqlite3")
        self.pc = self.repo.save(Creature(name="Rowan", character_class="Fighter", max_hit_points=14))
        self.enemy = self.repo.save(Creature(name="Lookout", kind="npc", max_hit_points=8, armor_class=13))
        self.draft = generate_encounter([self.enemy], quantity="2", roll_initiative=True,
                                        rng=random.Random(42))
        self.window = MainWindow(self.repo)

    def tearDown(self):
        tracker = self.window._battle_window
        if tracker is not None:
            tracker.close()
        self.window.close()
        self.tmp.cleanup()

    def handoff(self, action):
        from PyQt6.QtWidgets import QDialog
        with patch("dndgm4.encounter_ui.EncounterGeneratorDialog") as factory:
            factory.return_value.exec.return_value = QDialog.DialogCode.Accepted
            factory.return_value.result_action = action
            factory.return_value.result_draft = self.draft
            self.window.open_encounter_generator()

    def test_scene_handoff_preserves_party_and_campaign_notes(self):
        self.window.scene["record_ids"] = [self.pc.id]
        self.window.scene["campaign_notes"] = "Find the missing archivist."
        self.handoff("scene")
        restored = self.window.scene_store.load()
        self.assertEqual(restored["record_ids"], [self.pc.id, self.enemy.id])
        self.assertIn("Find the missing archivist.", restored["campaign_notes"])
        self.assertIn(self.draft.hook, restored["campaign_notes"])
        self.assertIn("Lookout #2", restored["campaign_notes"])
        self.assertEqual(self.repo.get(self.enemy.id), self.enemy)
        self.assertEqual(len(self.repo.list()), 2)

    def test_battle_handoff_appends_independent_fighters_and_preserves_current_hp(self):
        from dndgm4.battle_advanced import AdvancedBattleStore
        tracker = self.window.open_battle_trakker()
        tracker._run(lambda: tracker._add_records([self.pc]))
        tracker.battle.fighters[0].hp = 5
        tracker.save()
        uid = tracker.battle.fighters[0].uid
        self.handoff("battle")
        restored = AdvancedBattleStore(self.repo.path).load()
        self.assertEqual(len(restored.fighters), 3)
        self.assertEqual(restored.get(uid).hp, 5)
        self.assertEqual(restored.phase, "setup")
        self.assertEqual(len({fighter.uid for fighter in restored.fighters}), 3)
        self.assertEqual(self.repo.get(self.pc.id).max_hit_points, 14)
        self.assertEqual(self.repo.get(self.enemy.id), self.enemy)
        tracker.battle.fighters[1].hp = 1
        self.assertEqual(tracker.battle.fighters[2].hp, 8)
        self.assertEqual(self.draft.fighters[0].hp, 8)

    def test_battle_save_failure_preserves_in_memory_encounter(self):
        tracker = self.window.open_battle_trakker()
        tracker._run(lambda: tracker._add_records([self.pc]))
        before = tracker.battle.snapshot()
        with patch.object(tracker.store, "save", side_effect=OSError("Disk unavailable")), \
                patch("dndgm4.ui.QMessageBox.warning") as warning:
            self.handoff("battle")
        warning.assert_called_once()
        self.assertEqual(tracker.battle.snapshot(), before)

    def test_scribe_handoff_is_explicit_and_does_not_apply_scene_or_battle(self):
        before = dict(self.window.scene)
        with patch.object(self.window, "_open_scribe_with_context") as open_scribe:
            self.handoff("scribe")
        context = open_scribe.call_args.args[0]
        self.assertIn(self.draft.location, context)
        self.assertIn(self.draft.motive, context)
        self.assertEqual(open_scribe.call_args.kwargs["task"], "session_plan")
        self.assertEqual(self.window.scene, before)
        self.assertIsNone(self.window._battle_window)

    def test_cancel_has_no_side_effects(self):
        from PyQt6.QtWidgets import QDialog
        with patch("dndgm4.encounter_ui.EncounterGeneratorDialog") as factory:
            factory.return_value.exec.return_value = QDialog.DialogCode.Rejected
            self.window.open_encounter_generator()
        self.assertIsNone(self.window._battle_window)
        self.assertFalse(self.window.scene_store.path.exists())
        self.assertEqual(self.repo.get(self.enemy.id), self.enemy)

    def test_reopening_keeps_last_roll_for_subsequent_handoff(self):
        from PyQt6.QtWidgets import QDialog
        with patch("dndgm4.encounter_ui.EncounterGeneratorDialog.exec",
                   return_value=QDialog.DialogCode.Rejected):
            self.window.open_encounter_generator()
            dialog = self.window._encounter_generator_dialog
            dialog.quantity.setText("2")
            dialog.roll_encounter()
            first = dialog.draft
            dialog.title.setText("Reviewed encounter")
            self.window.open_encounter_generator()
        self.assertIs(self.window._encounter_generator_dialog, dialog)
        self.assertIs(dialog.draft, first)
        self.assertEqual(dialog.title.text(), "Reviewed encounter")
