"""Library advancement and live battle advice keep records and drafts distinct."""
from dataclasses import replace
from importlib.util import find_spec
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import patch


@unittest.skipUnless(find_spec("PyQt6") is not None, "PyQt6 is not installed")
class AdvancementIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        from PyQt6.QtWidgets import QApplication
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        from dndgm4.models import Creature
        from dndgm4.storage import CreatureRepository
        from dndgm4.ui import MainWindow
        self.temporary = TemporaryDirectory()
        self.repo = CreatureRepository(Path(self.temporary.name) / "library.sqlite3")
        self.pc = self.repo.save(Creature(
            name="Rowan", race_type="Human", character_class="Fighter", strength=16,
            constitution=14, max_hit_points=12, notes="Party defender"))
        self.window = MainWindow(self.repo)
        self.window.refresh(select_id=self.pc.id)

    def tearDown(self):
        self.window.close()
        self.temporary.cleanup()

    @staticmethod
    def accept_default_level(dialog):
        dialog.apply_defaults()
        dialog.hp_roll.setValue(1)
        dialog.review_ack.setChecked(True)
        if not dialog.save_button.isEnabled():
            raise AssertionError(dialog.status.text())
        dialog.save_button.click()
        return dialog.result()

    def test_level_up_saves_result_history_and_library_preview(self):
        self.assertTrue(self.window.level_up_button.isEnabled())
        with patch("dndgm4.advancement_ui.LevelUpDialog.exec", self.accept_default_level):
            self.window.level_up()
        result = self.repo.get(self.pc.id)
        self.assertEqual(result.level, 2)
        self.assertEqual(result.max_hit_points, 15)
        self.assertEqual(result.notes, self.pc.notes)
        history = json.loads(result.sheet_json)["advancement_history"]
        self.assertEqual(history[-1]["from_level"], 1)
        self.assertEqual(history[-1]["to_level"], 2)
        self.assertEqual(history[-1]["hp_roll"], 1)
        self.assertEqual(self.window.selected().id, self.pc.id)
        self.assertIn("Level: 2", self.window.detail.text())

    def test_cancelled_level_up_leaves_saved_record_unchanged(self):
        from PyQt6.QtWidgets import QDialog
        with patch("dndgm4.advancement_ui.LevelUpDialog.exec", return_value=QDialog.DialogCode.Rejected):
            self.window.level_up()
        self.assertEqual(self.repo.get(self.pc.id), self.pc)

    def test_monsters_archived_records_and_level_twenty_disable_action(self):
        from dndgm4.models import Creature
        self.window.show_archived.setChecked(True)
        records = (
            Creature(name="Wolf", kind="monster"),
            replace(self.pc, id="archived", name="Retired", archived=True),
            replace(self.pc, id="epic", name="Veteran", level=20),
        )
        for record in records:
            with self.subTest(record=record.name):
                saved = self.repo.save(record)
                self.window.refresh(select_id=saved.id)
                self.assertFalse(self.window.level_up_button.isEnabled())
        npc = self.repo.save(replace(self.pc, id="npc", name="Companion", kind="npc"))
        self.window.refresh(select_id=npc.id)
        self.assertTrue(self.window.level_up_button.isEnabled())

    def test_stale_level_up_draft_does_not_overwrite_new_library_changes(self):
        from PyQt6.QtWidgets import QDialog
        drafts = []
        def edit_then_accept(dialog):
            drafts.append(dialog)
            if len(drafts) > 1:
                self.assertIs(drafts[0], dialog)
                self.assertEqual(dialog.result_creature.level, 2)
                return QDialog.DialogCode.Rejected
            self.repo.save(replace(self.pc, notes="Edited while draft was open"))
            return self.accept_default_level(dialog)

        with patch("dndgm4.advancement_ui.LevelUpDialog.exec", edit_then_accept), \
                patch("dndgm4.ui.QMessageBox.critical") as warning:
            self.window.level_up()
        warning.assert_called_once()
        self.assertIn("changed while", warning.call_args.args[2])
        result = self.repo.get(self.pc.id)
        self.assertEqual(result.level, 1)
        self.assertEqual(result.notes, "Edited while draft was open")
        self.assertEqual(result.sheet_json, "")

    def make_battle(self):
        from dndgm4.battle_advanced import AdvancedBattle
        from dndgm4.battle_rules import fighter_from_record
        battle = AdvancedBattle(title="Bridge ambush")
        fighter = fighter_from_record(self.pc)
        fighter.hp = 4
        fighter.initiative = 17
        battle.add(fighter)
        battle.phase = "combat"
        battle.current_id = fighter.uid
        battle.round = 2
        battle.add_effect("Bless", target_id=fighter.uid, anchor_id=fighter.uid,
                          duration=3, notes="Cast by the party cleric")
        return battle

    def test_battle_discussion_uses_current_instance_hp_and_effects(self):
        battle = self.make_battle()
        self.window._battle_window = SimpleNamespace(battle=battle)
        before = battle.snapshot()
        with patch.object(self.window, "_open_scribe_with_context") as open_scribe:
            self.window.discuss_battle()
        open_scribe.assert_called_once()
        context = open_scribe.call_args.args[0]
        self.assertEqual(open_scribe.call_args.kwargs["task"], "dm_advice")
        self.assertIn('"hp": 4', context)
        self.assertIn('"initiative": 17', context)
        self.assertIn('"name": "Bless"', context)
        self.assertIn("Cast by the party cleric", context)
        self.assertEqual(battle.snapshot(), before)
        self.assertEqual(self.repo.get(self.pc.id), self.pc)
        self.window._battle_window = None

    def test_saved_battle_discussion_works_without_open_tracker(self):
        from dndgm4.battle_advanced import AdvancedBattleStore
        battle = self.make_battle()
        AdvancedBattleStore(self.repo.path).save(battle)
        with patch.object(self.window, "_open_scribe_with_context") as open_scribe:
            self.window.discuss_battle()
        self.assertIn('"hp": 4', open_scribe.call_args.args[0])
        self.assertEqual(open_scribe.call_args.kwargs["task"], "dm_advice")

    def test_missing_battle_reports_visible_message_without_opening_ai(self):
        with patch("dndgm4.ui.QMessageBox.warning") as warning, \
                patch.object(self.window, "_open_scribe_with_context") as open_scribe:
            self.window.discuss_battle()
        warning.assert_called_once()
        self.assertIn("Add combatants", warning.call_args.args[2])
        open_scribe.assert_not_called()

    def test_dm_assistant_reuses_draft_and_selects_advice_without_inference(self):
        with patch("dndgm4.ai_ui.AIWritingDialog.generate") as generate:
            self.window._open_scribe_with_context("First scene", task="session_plan")
            writer = self.window._narrator_dialog
            writer.result.setPlainText("Keep this editable draft.")
            self.window._open_scribe_with_context("Current battle", task="dm_advice")
        generate.assert_not_called()
        self.assertIs(self.window._narrator_dialog, writer)
        self.assertEqual(writer.dm_task.currentData(), "dm_advice")
        self.assertEqual(writer.context.toPlainText(), "Current battle")
        self.assertEqual(writer.result.toPlainText(), "Keep this editable draft.")
        writer.close()


if __name__ == "__main__":
    unittest.main()
