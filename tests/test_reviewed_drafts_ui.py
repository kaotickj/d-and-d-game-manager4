"""Explicit local Scribe handoff, complete review, and failure retention."""
from contextlib import closing
from dataclasses import replace
from importlib.util import find_spec
import os
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch


@unittest.skipUnless(find_spec("PyQt6") is not None, "PyQt6 is not installed")
class ReviewedDraftUiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        from PyQt6.QtWidgets import QApplication
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        from dndgm4.campaigns import CampaignRepository
        from dndgm4.world import WorldRepository
        self.temp = TemporaryDirectory()
        self.path = Path(self.temp.name) / "library.sqlite3"
        self.campaigns = CampaignRepository(self.path)
        self.campaign = self.campaigns.create_campaign("Ash Road")
        self.session = self.campaigns.create_session(self.campaign.id, "The crossing")
        self.session = self.campaigns.save_session(replace(self.session, notes="The courier was rescued."))
        self.world = WorldRepository(self.path)
        self.handout = self.world.create(self.campaign.id, "handout", "SECRET ambush title",
                                         dm_notes="SECRET spy identity", details={"player_text": "Meet at the bridge."})
        self.dialogs = []

    def tearDown(self):
        for dialog in self.dialogs:
            dialog._dirty = False
            dialog.close()
            if dialog._writer is not None:
                dialog._writer.hide()
                dialog._writer.deleteLater()
            dialog.deleteLater()
        self.app.processEvents()
        self.temp.cleanup()

    def dialog(self):
        from dndgm4.reviewed_drafts_ui import ReviewedDraftsDialog
        dialog = ReviewedDraftsDialog(self.path, self.campaign.id)
        self.dialogs.append(dialog)
        return dialog

    def select_world(self, dialog):
        row = next(index for index in range(dialog.targets.count())
                   if dialog.targets.itemData(index) == ("world", self.handout.id))
        dialog.targets.setCurrentIndex(row)

    def test_paste_prepare_and_apply_are_separate_and_only_save_selected_field(self):
        dialog = self.dialog()
        self.assertEqual(dialog.field.currentData(), "notes")
        dialog.draft.setPlainText("Propose a return visit to the bridge.")
        self.assertTrue(dialog.prepare_review())
        self.assertEqual(self.campaigns.get_session(self.session.id), self.session)
        self.assertIn("Propose a return", dialog.after.toPlainText())
        self.assertEqual(dialog.before.toPlainText(), self.session.notes)
        dialog.review_field.setChecked(False)
        self.assertFalse(dialog.apply_review())
        dialog.review_field.setChecked(True)
        self.assertTrue(dialog.apply_review())
        saved = self.campaigns.get_session(self.session.id)
        self.assertIn("Propose a return", saved.notes)
        self.assertEqual(saved.recap, "")
        self.assertEqual(saved.status, self.session.status)
        self.assertFalse(dialog.apply_button.isEnabled())

    def test_handoff_preselects_recap_and_requires_explicit_source_review(self):
        from PyQt6.QtCore import Qt
        dialog = self.dialog()
        self.assertTrue(dialog.load_scribe_draft("The courier was rescued.", task="recap", session_id=self.session.id))
        self.assertEqual(dialog.field.currentData(), "recap")
        self.assertFalse(dialog.recorded_confirm.isChecked())
        self.assertFalse(dialog.apply_button.isEnabled())
        self.assertFalse(dialog.prepare_review())
        self.assertEqual(self.campaigns.get_session(self.session.id).recap, "")
        dialog.evidence.item(0).setCheckState(Qt.CheckState.Checked)
        dialog.recorded_confirm.setChecked(True)
        source = dialog.selected_evidence()[0]
        dialog.draft.setPlainText("The courier was rescued. " + source.citation)
        self.assertTrue(dialog.prepare_review())
        self.assertIn(source.text, dialog.after.toPlainText())
        self.assertTrue(dialog.apply_review())
        self.assertIn(source.citation, self.campaigns.get_session(self.session.id).recap)

    def test_foreign_session_handoff_is_rejected_without_losing_draft(self):
        other = self.campaigns.create_campaign("Other road")
        foreign = self.campaigns.create_session(other.id, "Foreign session")
        dialog = self.dialog()
        dialog.draft.setPlainText("Keep this editable proposal")
        self.assertFalse(dialog.load_scribe_draft("Foreign prose", session_id=foreign.id))
        self.assertEqual(dialog.draft.toPlainText(), "Keep this editable proposal")
        self.assertEqual(dialog._baseline.target_id, self.session.id)

    def test_public_review_is_separate_and_open_scribe_excludes_secrets(self):
        dialog = self.dialog()
        self.select_world(dialog)
        self.assertEqual(dialog.field.currentData(), "dm_notes")
        dialog.field.setCurrentIndex(dialog.field.findData("player_text"))
        with patch("dndgm4.local_ai.text_generate") as generate:
            self.assertTrue(dialog.open_scribe())
            generate.assert_not_called()
            context = dialog._writer.context.toPlainText()
            self.assertNotIn("SECRET", context)
            dialog._writer.result.setPlainText("A public invitation.")
            self.assertTrue(dialog.retrieve_scribe())
        self.assertTrue(dialog.prepare_review())
        self.assertFalse(dialog.apply_button.isEnabled())
        self.assertFalse(dialog.apply_review())
        self.assertEqual(self.world.get(self.handout.id), self.handout)
        dialog.public_review.setChecked(True)
        self.assertTrue(dialog.apply_button.isEnabled())
        self.assertTrue(dialog.apply_review())
        self.assertEqual(self.world.get(self.handout.id).details["player_text"], "A public invitation.")
        self.assertEqual(self.world.get(self.handout.id).dm_notes, "SECRET spy identity")

    def test_stale_target_and_sql_failure_preserve_editable_draft(self):
        dialog = self.dialog()
        dialog.draft.setPlainText("A proposed scene")
        self.assertTrue(dialog.prepare_review())
        newer = self.campaigns.save_session(replace(self.session, title="Corrected crossing"))
        self.assertFalse(dialog.apply_review())
        self.assertIn("changed", dialog.message.text())
        self.assertEqual(dialog.draft.toPlainText(), "A proposed scene")
        self.assertEqual(self.campaigns.get_session(self.session.id), newer)
        dialog.reload_target()
        self.assertEqual(dialog.draft.toPlainText(), "A proposed scene")
        self.assertTrue(dialog.prepare_review())
        with closing(sqlite3.connect(self.path)) as db:
            db.execute("CREATE TRIGGER fail_review BEFORE UPDATE ON sessions BEGIN SELECT RAISE(ABORT, 'Write failed'); END")
            db.commit()
        self.assertFalse(dialog.apply_review())
        self.assertEqual(dialog.draft.toPlainText(), "A proposed scene")
        self.assertEqual(self.campaigns.get_session(self.session.id), newer)

    def test_cancel_field_switch_keeps_private_draft_and_discard_clears_it(self):
        from PyQt6.QtWidgets import QMessageBox
        dialog = self.dialog()
        self.select_world(dialog)
        dialog.draft.setPlainText("PRIVATE proposed motive")
        with patch("dndgm4.reviewed_drafts_ui.QMessageBox.question", return_value=QMessageBox.StandardButton.Cancel):
            dialog.field.setCurrentIndex(dialog.field.findData("player_text"))
        self.assertEqual(dialog.field.currentData(), "dm_notes")
        self.assertEqual(dialog.draft.toPlainText(), "PRIVATE proposed motive")
        with patch("dndgm4.reviewed_drafts_ui.QMessageBox.question", return_value=QMessageBox.StandardButton.Discard):
            dialog.field.setCurrentIndex(dialog.field.findData("player_text"))
        self.assertEqual(dialog.draft.toPlainText(), "")
        self.assertEqual(dialog.field.currentData(), "player_text")

    def test_failed_reload_retains_baseline_and_draft(self):
        dialog = self.dialog()
        baseline = dialog._baseline
        dialog.draft.setPlainText("Keep this draft")
        with patch.object(dialog.repository, "snapshot", side_effect=ValueError("Unreadable target")):
            dialog.reload_target()
        self.assertEqual(dialog._baseline, baseline)
        self.assertEqual(dialog.draft.toPlainText(), "Keep this draft")
        self.assertIn("Unreadable", dialog.message.text())


if __name__ == "__main__":
    unittest.main()
