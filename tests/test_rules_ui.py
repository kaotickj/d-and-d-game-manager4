"""Rules search and source handoff are explicit, offline by default."""
from importlib.util import find_spec
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch


@unittest.skipUnless(find_spec("PyQt6") is not None, "PyQt6 is not installed")
class RulesUiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        from PyQt6.QtWidgets import QApplication
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        from dndgm4.rules_reference import RulesRepository
        self.tmp = TemporaryDirectory()
        self.repo = RulesRepository(Path(self.tmp.name) / "rules.sqlite3")
        self.widgets = []

    def tearDown(self):
        for widget in self.widgets:
            widget.close()
        self.tmp.cleanup()

    def dialog(self):
        from dndgm4.rules_ui import RulesReferenceDialog
        dialog = RulesReferenceDialog(self.repo)
        self.widgets.append(dialog)
        return dialog

    def test_open_search_and_selection_do_not_fetch_or_invoke_scribe(self):
        with patch.object(self.repo, "fetch_source") as fetch:
            dialog = self.dialog()
            self.assertFalse(dialog.scribe_button.isEnabled())
            self.assertFalse(dialog.source_button.isEnabled())
            self.assertIn("authored summaries", dialog.status.text())
            contexts = []
            dialog.context_requested.connect(contexts.append)
            dialog.query.setText("critical hits")
            dialog.search_button.click()
        fetch.assert_not_called()
        self.assertGreater(dialog.results.count(), 0)
        self.assertIn("confirmation", dialog.passage.toPlainText())
        self.assertIn("Authored reference summary", dialog.passage_kind.text())
        self.assertIn("SHA-256", dialog.source_info.toPlainText())
        self.assertFalse(contexts)
        self.assertIsNone(dialog.result_context)
        dialog.scribe_button.click()
        from PyQt6.QtWidgets import QDialog
        self.assertEqual(dialog.result(), QDialog.DialogCode.Accepted)
        self.assertEqual(contexts, [dialog.result_context])
        self.assertIn("[R1]", contexts[0])
        self.assertIn("critical hits", contexts[0])

    def test_source_opening_requires_button_and_uses_selected_url(self):
        dialog = self.dialog()
        with patch("dndgm4.rules_ui.QDesktopServices.openUrl", return_value=True) as open_url:
            dialog.query.setText("cover")
            dialog.search()
            open_url.assert_not_called()
            dialog.source_button.click()
        open_url.assert_called_once()
        self.assertEqual(open_url.call_args.args[0].toString(), dialog.selected_hit().source_url)

    def test_local_source_has_no_browser_link_and_can_show_entire_document(self):
        text = "Specialrule: start here.\n\n" + "Additional complete information. " * 120
        document_id = self.repo.import_document("Local reference", text)
        dialog = self.dialog()
        dialog.query.setText("specialrule")
        dialog.search()
        self.assertFalse(dialog.source_button.isEnabled())
        self.assertIn("Imported source passage", dialog.passage_kind.text())
        passage = dialog.passage.toPlainText()
        dialog.document_button.click()
        self.assertEqual(dialog.passage.toPlainText(), self.repo.get_document(document_id).text)
        self.assertEqual(dialog.document_button.text(), "Return to Passage")
        dialog.document_button.click()
        self.assertEqual(dialog.passage.toPlainText(), passage)

    def test_no_results_clears_previous_passage_and_disables_actions(self):
        dialog = self.dialog()
        dialog.query.setText("cover")
        dialog.search()
        dialog.query.setText("nonexistentunicornrule")
        dialog.search()
        self.assertEqual(dialog.results.count(), 0)
        self.assertFalse(dialog.scribe_button.isEnabled())
        self.assertFalse(dialog.source_button.isEnabled())
        self.assertFalse(dialog.document_button.isEnabled())
        self.assertIn("No matching passages", dialog.status.text())

    def test_local_import_is_previewed_and_cancel_does_not_write(self):
        from dndgm4.rules_ui import ImportRulesDialog
        path = Path(self.tmp.name) / "new-rule.txt"
        path.write_text("An imported specialrule.", encoding="utf-8")
        before = len(self.repo.list_documents())
        dialog = ImportRulesDialog(self.repo, str(path))
        self.widgets.append(dialog)
        self.assertIsNone(dialog.document_id)
        self.assertEqual(len(self.repo.list_documents()), before)
        dialog.reject()
        self.assertEqual(len(self.repo.list_documents()), before)
        dialog.import_button.click()
        self.assertIsNotNone(dialog.document_id)
        self.assertEqual(len(self.repo.list_documents()), before + 1)
        self.assertTrue(self.repo.search("specialrule"))

    def test_invalid_import_shows_error_and_leaves_library_unchanged(self):
        from dndgm4.rules_ui import ImportRulesDialog
        path = Path(self.tmp.name) / "invalid.txt"
        path.write_text("", encoding="utf-8")
        before = len(self.repo.list_documents())
        dialog = ImportRulesDialog(self.repo, str(path))
        self.widgets.append(dialog)
        with patch("dndgm4.rules_ui.QMessageBox.warning") as warning:
            dialog.import_button.click()
        warning.assert_called_once()
        self.assertIsNone(dialog.document_id)
        self.assertEqual(len(self.repo.list_documents()), before)

    def test_file_picker_cancel_does_not_open_import_dialog(self):
        dialog = self.dialog()
        with patch("dndgm4.rules_ui.QFileDialog.getOpenFileName", return_value=("", "")), \
                patch("dndgm4.rules_ui.ImportRulesDialog") as preview:
            dialog.import_button.click()
        preview.assert_not_called()

    def test_download_runs_only_on_explicit_click_and_restores_controls(self):
        dialog = self.dialog()
        with patch.object(self.repo, "fetch_source", return_value="fixture-document") as fetch, \
                patch("dndgm4.rules_ui.QThreadPool") as pool:
            pool.globalInstance.return_value.start.side_effect = lambda worker: worker.run()
            fetch.assert_not_called()
            dialog.fetch_button.click()
        fetch.assert_called_once_with("basics")
        self.assertIsNone(dialog.fetch_worker)
        self.assertTrue(dialog.fetch_button.isEnabled())
        self.assertIn("saved for offline search", dialog.status.text())

    def test_download_failure_keeps_offline_search_available(self):
        dialog = self.dialog()
        with patch.object(self.repo, "fetch_source", side_effect=OSError("Offline")), \
                patch("dndgm4.rules_ui.QThreadPool") as pool, \
                patch("dndgm4.rules_ui.QMessageBox.warning") as warning:
            pool.globalInstance.return_value.start.side_effect = lambda worker: worker.run()
            dialog.fetch_button.click()
        warning.assert_called_once()
        self.assertIn("Offline", dialog.status.text())
        self.assertTrue(dialog.fetch_button.isEnabled())
        dialog.query.setText("cover")
        dialog.search()
        self.assertGreater(dialog.results.count(), 0)


if __name__ == "__main__":
    unittest.main()
