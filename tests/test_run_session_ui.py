"""Behavioral contracts for the dashboard's shared state and note guard."""
import copy
from importlib.util import find_spec
import os
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
if find_spec("PyQt6") is not None:
    from PyQt6.QtWidgets import QApplication, QMessageBox
    from dndgm4.run_session_ui import RunSessionDialog


def snapshot():
    return dict(workspace_key=("c", "s", "e"), campaign_name="Campaign",
                session_title="Session", session_status="active", session_id="s",
                encounter_title="Bridge", scene_title="Gate", scene_location="Hill",
                scene_text="<b>Literal scene</b>", session_notes="original", party=[],
                scene_roster=[], fighters=[dict(id="a", name="Same", initiative=20,
                    hp=10, max_hp=12, temp_hp=2, ac=15, conditions="", current=True,
                    active=True), dict(id="b", name="Same", initiative=10, hp=4,
                    max_hp=8, temp_hp=0, ac=12, conditions="", current=False, active=True)],
                phase="active", round=1, current_name="Same", combat_log=[])


@unittest.skipUnless(find_spec("PyQt6") is not None, "PyQt6 unavailable")
class RunSessionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.state = snapshot()
        self.calls = []
        self.fail = None
        self.provider_error = False
        def provider():
            if self.provider_error:
                raise RuntimeError("database unavailable")
            return copy.deepcopy(self.state)
        def handler(action, **kwargs):
            self.calls.append((action, kwargs))
            if self.fail:
                raise ValueError(self.fail)
            if action == "save_note":
                if kwargs["expected_notes"] != self.state["session_notes"]:
                    raise ValueError("Journal changed; review first")
                self.state["session_notes"] += "\n" + kwargs["note"]
            return "d20: 17"
        self.dialog = RunSessionDialog(provider, handler)

    def tearDown(self):
        self.dialog.note.clear()
        self.dialog.close()
        self.dialog.deleteLater()
        self.app.processEvents()

    def test_selected_identity_survives_reordering_and_actions_use_id(self):
        self.dialog.fighters.selectRow(1)
        self.state["fighters"].reverse()
        self.state["fighters"][0]["current"] = True
        self.dialog.refresh()
        self.assertEqual(self.dialog._selected_id(), "b")
        self.dialog.amount.setValue(3)
        self.dialog.damage_button.click()
        self.assertEqual(self.calls[-1], ("damage", {"combatant_id": "b", "amount": 3}))
        self.assertEqual(self.dialog.fighters.item(0, 0).text(), "▶ Current")
        self.state["fighters"] = [self.state["fighters"][1]]
        self.dialog.refresh()
        self.assertFalse(self.dialog.damage_button.isEnabled())

    def test_roll_outside_combat_and_plain_scene(self):
        self.state["fighters"] = []
        self.dialog.refresh()
        self.dialog.expression.setText("2d6+3")
        self.dialog._roll()
        self.assertEqual(self.calls[-1], ("roll", {"expression": "2d6+3"}))
        self.assertEqual(self.dialog.roll_result.text(), "d20: 17")
        self.assertIn("<b>Literal scene</b>", self.dialog.scene.toPlainText())

    def test_note_uses_original_baseline_and_failure_retains_draft(self):
        self.dialog.note.setPlainText("A clue")
        self.state["session_notes"] = "external edit"
        self.dialog.refresh()
        self.fail = "Journal changed; review first"
        self.assertFalse(self.dialog._save_note())
        self.assertEqual(self.dialog.note.toPlainText(), "A clue")
        self.assertEqual(self.calls[-1], ("save_note", dict(session_id="s", note="A clue", expected_notes="original")))
        self.assertIn("draft retained", self.dialog.message.text())
        self.dialog.refresh()
        self.assertIn("Journal changed", self.dialog.message.text())

    def test_explicit_review_rebases_stale_note_without_losing_draft(self):
        self.dialog.note.setPlainText("A clue")
        self.state["session_notes"] = "Another DM edit"
        self.assertFalse(self.dialog._save_note())
        self.dialog.refresh()
        self.assertEqual(self.dialog._note_baseline, "original")
        self.assertTrue(self.dialog.review_latest_notes())
        self.assertEqual(self.dialog.note.toPlainText(), "A clue")
        self.assertEqual(self.dialog.saved_notes.toPlainText(), "Another DM edit")
        self.assertTrue(self.dialog._save_note())
        self.assertEqual(self.state["session_notes"], "Another DM edit\nA clue")

    def test_successful_note_clears_draft_and_refreshes_saved_notes(self):
        self.dialog.note.setPlainText("A clue")
        self.assertTrue(self.dialog._save_note())
        self.assertEqual(self.dialog.note.toPlainText(), "")
        self.assertIn("A clue", self.dialog.saved_notes.toPlainText())
        self.assertFalse(self.dialog.save_button.isEnabled())

    def test_dirty_draft_does_not_follow_external_workspace_change(self):
        self.dialog.note.setPlainText("Original session clue")
        self.state.update(workspace_key=("c", "new", ""), session_id="new", session_title="New session", session_notes="new journal")
        self.dialog.refresh()
        self.assertEqual(self.dialog._note_session_id, "s")
        self.assertEqual(self.dialog.saved_notes.toPlainText(), "original")
        self.assertIn("original session", self.dialog.message.text())
        self.assertIn("Session", self.dialog.note_target.text())

    def test_provider_failure_preserves_view_and_disables_mutations(self):
        self.dialog.note.setPlainText("Keep me")
        old_scene = self.dialog.scene.toPlainText()
        self.provider_error = True
        self.dialog.refresh()
        self.assertEqual(self.dialog.scene.toPlainText(), old_scene)
        self.assertEqual(self.dialog.note.toPlainText(), "Keep me")
        self.assertTrue(all(not button.isEnabled() for button in self.dialog._buttons))
        self.dialog._roll()
        self.assertEqual(self.calls, [])
        self.provider_error = False
        self.dialog.refresh()
        self.assertTrue(self.dialog.save_button.isEnabled())

    def test_guard_cancel_discard_and_failed_save(self):
        self.dialog.note.setPlainText("Keep me")
        with patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.Cancel):
            self.assertFalse(self.dialog.prepare_workspace_change())
        self.fail = "Disk full"
        with patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.Save):
            self.assertFalse(self.dialog.prepare_workspace_change())
        self.assertEqual(self.dialog.note.toPlainText(), "Keep me")
        with patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.Discard):
            self.assertTrue(self.dialog.prepare_workspace_change())
        self.assertEqual(self.dialog.note.toPlainText(), "")

    def test_live_timer_only_while_visible_and_no_automatic_writes(self):
        self.assertFalse(self.dialog.timer.isActive())
        self.dialog.show()
        self.assertTrue(self.dialog.timer.isActive())
        self.dialog.hide()
        self.assertFalse(self.dialog.timer.isActive())
        self.assertEqual(self.calls, [])


if __name__ == "__main__":
    unittest.main()
