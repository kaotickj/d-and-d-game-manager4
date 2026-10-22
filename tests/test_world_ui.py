"""World editing preserves drafts and exports only explicit player text."""
from importlib.util import find_spec
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch


@unittest.skipUnless(find_spec("PyQt6") is not None, "PyQt6 is not installed")
class WorldUiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        from PyQt6.QtWidgets import QApplication
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        from dndgm4.models import Creature
        from dndgm4.world import WorldRepository
        self.temp = TemporaryDirectory()
        self.repo = WorldRepository(Path(self.temp.name) / "library.sqlite3")
        self.campaign = self.repo.campaigns.create_campaign("The Ash Road")
        self.hero = self.repo.library.save(Creature(name="Élara", kind="pc"))
        self.first = self.repo.create(self.campaign.id, "quest", "A missing courier",
                                      details={"assigned_ids": [self.hero.id]})
        self.second = self.repo.create(self.campaign.id, "location", "Bridge")
        self.dialogs = []

    def tearDown(self):
        for dialog in self.dialogs:
            dialog._dirty = False
            dialog.close()
        self.temp.cleanup()

    def dialog(self):
        from dndgm4.world_ui import WorldManagerDialog
        dialog = WorldManagerDialog(self.repo, self.campaign.id)
        self.dialogs.append(dialog)
        return dialog

    def test_open_and_new_draft_do_not_change_workspace_or_saved_records(self):
        from dndgm4.campaigns import ActiveWorkspace
        from PyQt6.QtWidgets import QMessageBox
        dialog = self.dialog()
        dialog.new_kind.setCurrentIndex(dialog.new_kind.findData("item"))
        dialog.new_record()
        dialog.name.setText("Unsaved treasure")
        dialog._detail_widgets["quantity"].setValue(4)
        self.assertEqual(len(self.repo.list(self.campaign.id)), 2)
        with patch("dndgm4.world_ui.QMessageBox.question", return_value=QMessageBox.StandardButton.Cancel):
            dialog.reject()
        self.assertTrue(dialog._dirty)
        self.assertEqual(dialog.name.text(), "Unsaved treasure")
        self.assertEqual(self.repo.campaigns.get_workspace(), ActiveWorkspace())
        self.assertEqual(self.repo.library.get(self.hero.id), self.hero)

    def test_explicit_typed_save_creates_inventory_without_changing_character(self):
        dialog = self.dialog()
        dialog.new_kind.setCurrentIndex(dialog.new_kind.findData("item"))
        dialog.new_record()
        dialog.name.setText("Silver dust")
        dialog._detail_widgets["quantity"].setValue(3)
        dialog._detail_widgets["unit_value_gp"].setText("25.50")
        dialog._detail_widgets["container"].setText("Party pouch")
        self.assertTrue(dialog.save_changes())
        saved = self.repo.get(dialog._record.id)
        self.assertEqual(saved.kind, "item")
        self.assertEqual(saved.details["quantity"], 3)
        self.assertEqual(saved.details["unit_value_gp"], "25.5")
        self.assertEqual(saved.details["container"], "Party pouch")
        self.assertFalse(dialog._dirty)
        self.assertEqual(self.repo.library.get(self.hero.id), self.hero)

    def test_invalid_typed_save_keeps_draft_and_existing_records(self):
        dialog = self.dialog()
        dialog.new_kind.setCurrentIndex(dialog.new_kind.findData("reward"))
        dialog.new_record()
        dialog.name.setText("Courier reward")
        dialog._detail_widgets["gp"].setText("0.001")
        dialog._detail_widgets["xp"].setValue(250)
        self.assertFalse(dialog.save_changes())
        self.assertTrue(dialog._dirty)
        self.assertEqual(dialog._detail_widgets["gp"].text(), "0.001")
        self.assertIn("decimal places", dialog.message.text())
        self.assertEqual(len(self.repo.list(self.campaign.id)), 2)

    def test_cancel_selection_and_filter_changes_keep_original_draft(self):
        from PyQt6.QtWidgets import QMessageBox
        dialog = self.dialog()
        dialog.dm_notes.setPlainText("An unsaved secret")
        with patch("dndgm4.world_ui.QMessageBox.question", return_value=QMessageBox.StandardButton.Cancel):
            dialog._select_id(self.second.id)
        self.assertEqual(dialog._record.id, self.first.id)
        self.assertEqual(dialog._item_id(dialog.entries.currentItem()), self.first.id)
        self.assertEqual(dialog.dm_notes.toPlainText(), "An unsaved secret")
        with patch("dndgm4.world_ui.QMessageBox.question", return_value=QMessageBox.StandardButton.Cancel):
            dialog.kind_filter.setCurrentIndex(dialog.kind_filter.findData("location"))
        self.assertIsNone(dialog.kind_filter.currentData())
        self.assertEqual(dialog.dm_notes.toPlainText(), "An unsaved secret")
        self.assertEqual(self.repo.get(self.first.id).dm_notes, "")

    def test_save_or_discard_when_navigating_applies_to_original_record(self):
        from PyQt6.QtWidgets import QMessageBox
        dialog = self.dialog()
        dialog.name.setText("A rescued courier")
        with patch("dndgm4.world_ui.QMessageBox.question", return_value=QMessageBox.StandardButton.Save):
            dialog._select_id(self.second.id)
        self.assertEqual(self.repo.get(self.first.id).name, "A rescued courier")
        self.assertEqual(dialog._record.id, self.second.id)
        dialog.dm_notes.setPlainText("Discard this")
        with patch("dndgm4.world_ui.QMessageBox.question", return_value=QMessageBox.StandardButton.Discard):
            dialog._select_id(self.first.id)
        self.assertEqual(self.repo.get(self.second.id).dm_notes, "")
        self.assertEqual(dialog.dm_notes.toPlainText(), "")
        self.assertFalse(dialog._dirty)

    def test_failed_discard_read_preserves_unsaved_draft(self):
        from PyQt6.QtWidgets import QMessageBox
        dialog = self.dialog()
        dialog.dm_notes.setPlainText("Keep this draft")
        with patch("dndgm4.world_ui.QMessageBox.question", return_value=QMessageBox.StandardButton.Discard), \
                patch.object(self.repo, "get", side_effect=ValueError("Unreadable stored entry")):
            dialog._select_id(self.second.id)
        self.assertTrue(dialog._dirty)
        self.assertEqual(dialog._record.id, self.first.id)
        self.assertEqual(dialog.dm_notes.toPlainText(), "Keep this draft")
        self.assertEqual(dialog._item_id(dialog.entries.currentItem()), self.first.id)

    def test_search_type_status_and_archive_are_usable_in_dialog(self):
        dialog = self.dialog()
        dialog.search.setText("courier")
        self.assertEqual(dialog.entries.count(), 1)
        self.assertEqual(dialog._record.id, self.first.id)
        dialog.search.clear()
        dialog.kind_filter.setCurrentIndex(dialog.kind_filter.findData("quest"))
        dialog.status_filter.setCurrentIndex(dialog.status_filter.findData("planned"))
        self.assertEqual(dialog.entries.count(), 1)
        dialog.toggle_archive()
        self.assertEqual(dialog.entries.count(), 0)
        dialog.show_archived.setChecked(True)
        self.assertEqual(dialog.entries.count(), 1)
        self.assertTrue(dialog._record.archived)
        dialog.toggle_archive()
        self.assertFalse(self.repo.get(self.first.id).archived)

    def test_player_preview_export_and_discard_never_leak_private_fields(self):
        from PyQt6.QtWidgets import QMessageBox, QPlainTextEdit
        handout = self.repo.create(self.campaign.id, "handout", "Secret ambush title",
                                   summary="Private editorial summary", dm_notes="The courier is a spy",
                                   details={"player_text": "Come to the bridge."})
        dialog = self.dialog()
        dialog._select_id(handout.id)
        dialog.preview_handout()
        preview = dialog._handout_previews[-1].findChild(QPlainTextEdit)
        self.assertEqual(preview.toPlainText(), "Come to the bridge.")
        target = Path(self.temp.name) / "players.txt"
        with patch("dndgm4.world_ui.QFileDialog.getSaveFileName", return_value=(str(target), "")):
            dialog.export_handout()
        self.assertEqual(target.read_text(encoding="utf-8"), "Come to the bridge.")
        dialog.dm_notes.setPlainText("Discarded secret")
        with patch("dndgm4.world_ui.QMessageBox.question", return_value=QMessageBox.StandardButton.Discard), \
                patch("dndgm4.world_ui.QFileDialog.getSaveFileName", return_value=("", "")):
            dialog.export_handout()
        self.assertEqual(dialog.dm_notes.toPlainText(), "The courier is a spy")
        dialog.summary.setPlainText("Only this new edit")
        self.assertTrue(dialog.save_changes())
        self.assertEqual(self.repo.get(handout.id).dm_notes, "The courier is a spy")

    def test_selected_saved_context_emits_without_running_ai_or_changing_workspace(self):
        from dndgm4.campaigns import ActiveWorkspace
        from PyQt6.QtWidgets import QDialog
        dialog = self.dialog()
        emitted = []
        dialog.context_requested.connect(emitted.append)
        dialog.load_context()
        self.assertEqual(len(emitted), 1)
        self.assertIn("A missing courier", emitted[0])
        self.assertIn("DM-only", emitted[0])
        self.assertEqual(dialog.result(), QDialog.DialogCode.Accepted)
        self.assertEqual(self.repo.campaigns.get_workspace(), ActiveWorkspace())
        self.assertEqual(self.repo.library.get(self.hero.id), self.hero)

    def test_relationship_removal_after_discard_uses_stable_saved_identity(self):
        from PyQt6.QtWidgets import QMessageBox
        self.repo.create_link(self.campaign.id, self.first.id, self.second.id, "leads to", "Private clue")
        dialog = self.dialog()
        dialog.relationships.setCurrentRow(0)
        dialog.dm_notes.setPlainText("Discard this unrelated edit")
        with patch("dndgm4.world_ui.QMessageBox.question", return_value=QMessageBox.StandardButton.Discard):
            dialog.remove_relationship()
        self.assertEqual(self.repo.list_links(self.campaign.id), [])
        self.assertEqual(self.repo.get(self.first.id).dm_notes, "")


if __name__ == "__main__":
    unittest.main()
