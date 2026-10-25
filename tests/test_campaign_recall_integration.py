"""Saved private material cannot reach the player-narration inference path."""
from importlib.util import find_spec
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch


@unittest.skipUnless(find_spec("PyQt6") is not None, "PyQt6 unavailable")
class RecallIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        from PyQt6.QtWidgets import QApplication
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        from dndgm4.campaigns import ActiveWorkspace
        from dndgm4.storage import CreatureRepository
        from dndgm4.ui import MainWindow
        from dndgm4.world import WorldRepository
        self.tmp = TemporaryDirectory()
        self.path = Path(self.tmp.name) / "library.sqlite3"
        self.library = CreatureRepository(self.path)
        self.window = MainWindow(self.library)
        self.campaign = self.window.campaigns.create_campaign("Private campaign title", notes="PRIVATE-CIPHER conspiracy")
        self.session = self.window.campaigns.create_session(self.campaign.id, "Private session title")
        self.window.switch_workspace(ActiveWorkspace(self.campaign.id, self.session.id))
        self.world = WorldRepository(self.path, campaigns=self.window.campaigns)
        self.world.create(self.campaign.id, "quest", "Private quest title", summary="Find the bridge keeper.", dm_notes="PRIVATE-CIPHER is the keeper.")
        self.world.create(self.campaign.id, "handout", "Private handout title", summary="PRIVATE-CIPHER metadata",
                          details={"player_text": "The bridge toll is waived."})

    def tearDown(self):
        writer = getattr(self.window, "_narrator_dialog", None)
        if writer is not None:
            writer.worker = None
            writer.hide()
        self.window.close()
        self.tmp.cleanup()

    def private_writer(self):
        self.window._open_scribe_with_context("PRIVATE-CIPHER supplied DM facts", task="dm_advice")
        return self.window._narrator_dialog

    def test_private_loaded_sources_stay_blocked_after_task_switch_and_context_edits(self):
        writer = self.private_writer()
        writer.dm_task.setCurrentIndex(writer.dm_task.findData("dm"))
        writer.context.appendPlainText("Read this aloud")
        with patch("dndgm4.ai_ui.QThreadPool") as pool:
            writer.generate()
        pool.globalInstance.return_value.start.assert_not_called()
        self.assertIsNone(writer.worker)
        self.assertIn("Private saved sources", writer.status.text())
        self.assertIn("PRIVATE-CIPHER", writer.context.toPlainText())

    def test_public_recall_replaces_only_context_preserves_draft_and_never_generates(self):
        from PyQt6.QtCore import Qt
        writer = self.private_writer()
        writer.result.setPlainText("Existing editable private draft")
        writer.dm_request.setText("PRIVATE-CIPHER request from earlier planning")
        before = self.path.read_bytes()
        def review(dialog):
            self.assertTrue(dialog.search())
            for row in range(dialog.results.rowCount()):
                dialog.results.item(row, 0).setCheckState(Qt.CheckState.Checked)
            self.assertTrue(dialog.preview_context())
            dialog.accept()
            return dialog.result()
        with patch("dndgm4.campaign_recall_ui.CampaignRecallDialog.exec", new=review), patch("dndgm4.ai_ui.QThreadPool") as pool:
            self.window.open_campaign_recall(query="bridge", audience="player", writer=writer)
        pool.globalInstance.return_value.start.assert_not_called()
        self.assertEqual(writer.source_audience, "player")
        self.assertEqual(writer.dm_task.currentData(), "dm")
        self.assertIn("Find the bridge keeper.", writer.context.toPlainText())
        self.assertIn("The bridge toll is waived.", writer.context.toPlainText())
        self.assertNotIn("PRIVATE-CIPHER", writer.context.toPlainText())
        self.assertNotIn("Private quest title", writer.context.toPlainText())
        self.assertEqual(writer.dm_request.text(), "")
        self.assertEqual(writer.result.toPlainText(), "Existing editable private draft")
        self.assertIn("not been regenerated", writer.status.text())
        self.assertEqual(self.path.read_bytes(), before)
        self.assertFalse(self.path.with_name("rules.sqlite3").exists())

    def test_explicit_clear_removes_private_context_and_request_before_manual_narration(self):
        writer = self.private_writer()
        writer.dm_request.setText("PRIVATE-CIPHER request")
        writer.clear_source_context()
        self.assertEqual(writer.source_audience, "user")
        self.assertEqual(writer.context.toPlainText(), "")
        self.assertEqual(writer.dm_request.text(), "")
        writer.context.setPlainText("The public bridge is misty.")
        writer.dm_task.setCurrentIndex(writer.dm_task.findData("dm"))
        writer.backend.setCurrentIndex(writer.backend.findData("ollama"))
        with patch("dndgm4.ai_ui.QThreadPool") as pool:
            writer.generate()
        pool.globalInstance.return_value.start.assert_called_once()
        self.assertNotIn("PRIVATE-CIPHER", writer.worker.context)
        writer.generation_completed("A public narration draft.")
        self.assertIn("Player narration", writer.draft_audience.text())

    def test_busy_generation_cannot_be_rebound_to_other_source_audience(self):
        writer = self.private_writer()
        writer.worker = object()
        before = writer.context.toPlainText()
        with self.assertRaisesRegex(ValueError, "Wait"):
            writer.load_context("public bridge", audience="player")
        self.assertEqual(writer.context.toPlainText(), before)
        self.assertEqual(writer.source_audience, "dm")

    def test_private_request_cannot_follow_a_task_switch_into_public_generation(self):
        writer = self.private_writer()
        writer.load_context("The bridge is public.", audience="player")
        writer.dm_request.setText("PRIVATE-CIPHER planning request")
        writer.dm_task.setCurrentIndex(writer.dm_task.findData("dm"))
        with patch("dndgm4.ai_ui.QThreadPool") as pool:
            writer.generate()
        pool.globalInstance.return_value.start.assert_not_called()
        self.assertIn("private DM work", writer.status.text())

    def test_combat_desk_marks_saved_encounter_sources_private_and_rejects_truncation(self):
        host = self.window._ensure_battle_tracker()
        host.battle.scene = "PRIVATE-CIPHER lair"
        host.open_advanced()
        desk = host.advanced_desk
        desk.open_narrator()
        writer = desk.ai_dialog
        self.assertEqual(writer.source_audience, "dm")
        self.assertIn("PRIVATE-CIPHER", writer.context.toPlainText())
        writer.dm_task.setCurrentIndex(writer.dm_task.findData("dm"))
        with patch("dndgm4.ai_ui.QThreadPool") as pool:
            writer.generate()
        pool.globalInstance.return_value.start.assert_not_called()
        before = writer.context.toPlainText()
        host.battle.scene = "x" * 6001
        with patch("dndgm4.battle_desk_ui.QMessageBox.warning") as warning:
            desk.open_narrator()
        warning.assert_called_once()
        self.assertIs(desk.ai_dialog, writer)
        self.assertEqual(writer.context.toPlainText(), before)
        writer.hide(); desk.hide(); host.hide()

    def test_canceled_recall_preserves_context_and_does_not_seed_rules_or_write_library(self):
        from PyQt6.QtWidgets import QDialog
        writer = self.private_writer()
        before = self.path.read_bytes()
        with patch("dndgm4.campaign_recall_ui.CampaignRecallDialog.exec", return_value=QDialog.DialogCode.Rejected):
            self.window.open_campaign_recall(query="bridge", writer=writer)
        self.assertEqual(writer.context.toPlainText(), "PRIVATE-CIPHER supplied DM facts")
        self.assertEqual(writer.source_audience, "dm")
        self.assertEqual(self.path.read_bytes(), before)
        self.assertFalse(self.path.with_name("rules.sqlite3").exists())

    def test_private_scribe_reload_selects_dm_task_and_retains_original_draft(self):
        writer = self.private_writer()
        writer.result.setPlainText("Keep this draft")
        writer.dm_task.setCurrentIndex(writer.dm_task.findData("dm"))
        self.window._open_scribe_with_context("More private campaign evidence")
        self.assertEqual(writer.dm_task.currentData(), "dm_advice")
        self.assertEqual(writer.result.toPlainText(), "Keep this draft")
        self.assertEqual(writer.source_audience, "dm")
