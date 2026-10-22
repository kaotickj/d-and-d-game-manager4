"""Campaign journal editing and workspace selection do not activate implicitly."""
from dataclasses import replace
from importlib.util import find_spec
import os
import sqlite3
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch


@unittest.skipUnless(find_spec("PyQt6") is not None, "PyQt6 is not installed")
class CampaignUiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        from PyQt6.QtWidgets import QApplication
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        from dndgm4.campaigns import CampaignRepository
        from dndgm4.models import Creature
        from dndgm4.storage import CreatureRepository
        self.tmp = TemporaryDirectory()
        self.library = CreatureRepository(Path(self.tmp.name) / "library.sqlite3")
        self.repository = CampaignRepository(self.library.path)
        self.pc = self.library.save(Creature(name="Élara", kind="pc"))
        self.archived_pc = self.library.save(Creature(name="Retired Ally", kind="npc", archived=True))
        self.first = self.repository.create_campaign("Ash Road", description="A missing courier")
        self.second = self.repository.create_campaign("Glass Coast")
        self.session = self.repository.create_session(self.first.id, "The First Clue")
        self.second_session = self.repository.create_session(self.first.id, "Under the Bridge")
        self.encounter = self.repository.create_encounter(self.session.id, "Roadside Watch")
        self.dialogs = []

    def tearDown(self):
        for dialog in self.dialogs:
            dialog._campaign_dirty = dialog._session_dirty = False
            dialog.close()
        self.tmp.cleanup()

    def dialog(self):
        from dndgm4.campaign_ui import CampaignManagerDialog
        dialog = CampaignManagerDialog(self.repository, self.library)
        self.dialogs.append(dialog)
        return dialog

    def test_open_does_not_activate_and_returns_selected_workspace(self):
        from dndgm4.campaigns import ActiveWorkspace
        from PyQt6.QtWidgets import QDialog
        dialog = self.dialog()
        self.assertEqual(self.repository.get_workspace(), ActiveWorkspace())
        dialog.open_selected()
        self.assertEqual(dialog.result(), QDialog.DialogCode.Accepted)
        self.assertEqual(dialog.result_action, "open")
        self.assertEqual(dialog.result_workspace,
                         ActiveWorkspace(self.first.id, self.session.id, self.encounter.id))
        self.assertEqual(self.repository.get_workspace(), ActiveWorkspace())

    def test_explicit_save_preserves_campaign_party_and_session_journal(self):
        from PyQt6.QtCore import Qt
        dialog = self.dialog()
        dialog.campaign_name.setText("Ash Road: Revised")
        dialog.campaign_notes.setPlainText("The courier left by the south gate.")
        dialog.session_date.setText("2026-10-22")
        dialog.session_status.setCurrentIndex(dialog.session_status.findData("in_progress"))
        dialog.session_notes.setPlainText("The party followed the tracks.")
        dialog.session_recap.setPlainText("A clue was found.")
        for row in range(dialog.party.count()):
            item = dialog.party.item(row)
            if item.data(Qt.ItemDataRole.UserRole) in (self.pc.id, self.archived_pc.id):
                item.setCheckState(Qt.CheckState.Checked)
        self.assertTrue(dialog.save_button.isEnabled())
        self.assertTrue(dialog.save_changes())
        campaign = self.repository.get_campaign(self.first.id)
        session = self.repository.get_session(self.session.id)
        self.assertEqual(campaign.name, "Ash Road: Revised")
        self.assertEqual(session.session_date, "2026-10-22")
        self.assertEqual(session.status, "in_progress")
        self.assertEqual(session.notes, "The party followed the tracks.")
        self.assertEqual(session.recap, "A clue was found.")
        self.assertEqual({member.id for member in self.repository.party(self.first.id)},
                         {self.pc.id, self.archived_pc.id})
        self.assertEqual(self.library.get(self.pc.id), self.pc)
        self.assertEqual(self.library.get(self.archived_pc.id), self.archived_pc)
        self.assertFalse(dialog.save_button.isEnabled())

    def test_cancel_selection_change_retains_edits_and_original_selection(self):
        from PyQt6.QtWidgets import QMessageBox
        dialog = self.dialog()
        dialog.campaign_notes.setPlainText("Unsaved discovery")
        with patch("dndgm4.campaign_ui.QMessageBox.question", return_value=QMessageBox.StandardButton.Cancel):
            dialog._select_id(dialog.campaigns, self.second.id)
        self.assertEqual(dialog._campaign.id, self.first.id)
        self.assertEqual(dialog._id(dialog.campaigns.currentItem()), self.first.id)
        self.assertEqual(dialog.campaign_notes.toPlainText(), "Unsaved discovery")
        self.assertEqual(self.repository.get_campaign(self.first.id).notes, "")

    def test_saving_on_selection_change_updates_old_record_and_correct_list_label(self):
        from PyQt6.QtWidgets import QMessageBox
        dialog = self.dialog()
        dialog.campaign_name.setText("A Revised Campaign")
        dialog.session_title.setText("A Revised Session")
        with patch("dndgm4.campaign_ui.QMessageBox.question", return_value=QMessageBox.StandardButton.Save):
            dialog._select_id(dialog.campaigns, self.second.id)
        self.assertEqual(self.repository.get_campaign(self.first.id).name, "A Revised Campaign")
        self.assertEqual(self.repository.get_session(self.session.id).title, "A Revised Session")
        self.assertEqual(dialog._campaign.id, self.second.id)
        self.assertEqual(dialog.campaigns.currentItem().text(), "Glass Coast")
        self.assertEqual(dialog._item_by_id(dialog.campaigns, self.first.id).text(), "A Revised Campaign")

    def test_discard_does_not_save_and_session_switch_preserves_existing_state(self):
        from PyQt6.QtWidgets import QMessageBox
        dialog = self.dialog()
        dialog.session_notes.setPlainText("Discarded text")
        with patch("dndgm4.campaign_ui.QMessageBox.question", return_value=QMessageBox.StandardButton.Discard):
            dialog._select_id(dialog.sessions, self.second_session.id)
        self.assertEqual(dialog._session.id, self.second_session.id)
        self.assertEqual(self.repository.get_session(self.session.id).notes, "")
        self.assertFalse(dialog.save_button.isEnabled())

    def test_invalid_date_reports_error_and_preserves_unsaved_notes(self):
        from PyQt6.QtCore import Qt
        dialog = self.dialog()
        dialog.campaign_name.setText("Unsaved campaign name")
        dialog.campaign_notes.setPlainText("Unsaved campaign notes")
        for row in range(dialog.party.count()):
            if dialog._id(dialog.party.item(row)) == self.pc.id:
                dialog.party.item(row).setCheckState(Qt.CheckState.Checked)
        dialog.session_date.setText("2026-02-30")
        dialog.session_notes.setPlainText("Still here")
        with patch("dndgm4.campaign_ui.QMessageBox.warning") as warning:
            self.assertFalse(dialog.save_changes())
        warning.assert_called_once()
        self.assertEqual(dialog.session_notes.toPlainText(), "Still here")
        self.assertEqual(dialog.campaign_name.text(), "Unsaved campaign name")
        self.assertEqual(dialog.campaign_notes.toPlainText(), "Unsaved campaign notes")
        self.assertTrue(dialog._campaign_dirty)
        self.assertTrue(dialog._session_dirty)
        self.assertEqual(self.repository.get_campaign(self.first.id), self.first)
        self.assertEqual(self.repository.party_ids(self.first.id), [])
        self.assertEqual(dialog._campaign, self.first)
        self.assertEqual(dialog._session, self.session)
        self.assertEqual(self.repository.get_session(self.session.id).session_date, "")

    def test_creating_campaign_session_and_encounter_is_explicit(self):
        dialog = self.dialog()
        with patch("dndgm4.campaign_ui.QInputDialog.getText", return_value=("New Chronicle", True)):
            dialog.new_campaign()
        self.assertEqual(dialog._campaign.name, "New Chronicle")
        self.assertIsNone(dialog._session)
        with patch("dndgm4.campaign_ui.QInputDialog.getText", return_value=("Opening Night", True)):
            dialog.new_session()
        self.assertEqual(dialog._session.title, "Opening Night")
        with patch("dndgm4.campaign_ui.QInputDialog.getText", return_value=("Old Gate", True)):
            dialog.new_encounter()
        encounter_id = dialog._id(dialog.encounters.currentItem())
        self.assertEqual(self.repository.get_encounter(encounter_id).title, "Old Gate")
        self.assertEqual(self.repository.get_workspace().campaign_id, "")

    def test_rename_encounter_and_open_retains_selected_identity(self):
        dialog = self.dialog()
        with patch("dndgm4.campaign_ui.QInputDialog.getText", return_value=("Revised Watch", True)):
            dialog.rename_encounter()
        self.assertEqual(self.repository.get_encounter(self.encounter.id).title, "Revised Watch")
        dialog.open_selected()
        self.assertEqual(dialog.result_workspace.encounter_id, self.encounter.id)

    def test_archived_campaign_can_be_edited_but_cannot_be_opened(self):
        dialog = self.dialog()
        dialog.campaign_archived.setChecked(True)
        self.assertTrue(dialog.save_changes())
        self.assertFalse(dialog.open_button.isEnabled())
        dialog.open_selected()
        self.assertEqual(dialog.result_action, "")
        self.assertTrue(self.repository.get_campaign(self.first.id).archived)
        dialog.campaign_archived.setChecked(False)
        dialog.save_changes()
        self.assertTrue(dialog.open_button.isEnabled())

    def test_scribe_requests_return_context_identity_without_inference_or_activation(self):
        for task in ("campaign_plan", "session_plan", "recap"):
            with self.subTest(task=task):
                dialog = self.dialog()
                dialog.request_scribe(task)
                self.assertEqual(dialog.result_action, "scribe")
                self.assertEqual(dialog.result_task, task)
                self.assertEqual(dialog.result_session_id, self.session.id)
                self.assertEqual(dialog.result_workspace.campaign_id, self.first.id)
                self.assertEqual(self.repository.get_workspace().campaign_id, "")

    def test_standalone_and_legacy_import_are_explicit_parent_actions(self):
        dialog = self.dialog()
        dialog.import_legacy()
        self.assertEqual(dialog.result_action, "legacy_import")
        self.assertEqual(dialog.result_workspace.campaign_id, self.first.id)
        self.assertEqual(dialog.result_workspace.session_id, "")
        second = self.dialog()
        second.use_standalone()
        self.assertEqual(second.result_action, "standalone")
        self.assertEqual(second.result_workspace.campaign_id, "")
        self.assertEqual(len(self.repository.list_sessions(self.first.id)), 2)

    def test_bad_stored_workspace_does_not_prevent_opening_manager_or_clear_storage(self):
        with patch.object(self.repository, "get_workspace", side_effect=ValueError("Archived workspace")), \
                patch.object(self.repository, "clear_workspace") as clear:
            dialog = self.dialog()
        self.assertEqual(dialog._campaign.id, self.first.id)
        clear.assert_not_called()

    def test_close_cancel_retains_draft(self):
        from PyQt6.QtWidgets import QMessageBox, QDialog
        dialog = self.dialog()
        dialog.session_notes.setPlainText("Unsaved notes")
        with patch("dndgm4.campaign_ui.QMessageBox.question", return_value=QMessageBox.StandardButton.Cancel):
            dialog.reject()
        self.assertTrue(dialog._session_dirty)
        self.assertEqual(dialog.session_notes.toPlainText(), "Unsaved notes")
        self.assertEqual(dialog.result(), QDialog.DialogCode.Rejected)

    def test_failed_selection_read_reports_error_and_disables_edits(self):
        dialog = self.dialog()
        with patch.object(self.repository, "get_campaign", side_effect=sqlite3.OperationalError("Disk unavailable")), \
                patch("dndgm4.campaign_ui.QMessageBox.warning") as warning:
            dialog._select_id(dialog.campaigns, self.second.id)
        warning.assert_called_once()
        self.assertFalse(dialog.open_button.isEnabled())
        self.assertFalse(dialog.campaign_page.isEnabled())
        self.assertEqual(self.repository.get_campaign(self.first.id), self.first)
