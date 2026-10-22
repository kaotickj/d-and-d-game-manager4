"""Import preview behavior and main-window integration, offscreen when Qt exists."""
from dataclasses import replace
from importlib.util import find_spec
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
import os
import json
import sqlite3
import unittest


@unittest.skipUnless(find_spec("PyQt6") is not None, "PyQt6 is not installed")
class LibraryImportUiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        from PyQt6.QtWidgets import QApplication
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        from dndgm4.models import Creature
        from dndgm4.storage import CreatureRepository
        self.tmp = TemporaryDirectory()
        self.repo = CreatureRepository(Path(self.tmp.name) / "library.sqlite3")
        self.existing = self.repo.save(Creature(name="Rowan", notes="Keep original"))
        self.records = (replace(self.existing, notes="Imported notes"),
                        Creature(id="new-monster", name="Goblin", kind="monster"))
        self.widgets = []

    def tearDown(self):
        for widget in self.widgets:
            widget.close()
        self.tmp.cleanup()

    def dialog(self):
        from dndgm4.import_ui import ImportPreviewDialog
        dialog = ImportPreviewDialog(self.repo, self.records)
        self.widgets.append(dialog)
        return dialog

    def test_preview_defaults_to_skip_and_does_not_write(self):
        dialog = self.dialog()
        self.assertEqual(dialog.policy.currentData(), "skip")
        self.assertEqual(dialog.table.item(0, 2).text(), "Skip")
        self.assertEqual(dialog.table.item(1, 2).text(), "Add")
        self.assertIn("1 added", dialog.summary.text())
        self.assertIn("1 skipped", dialog.summary.text())
        dialog.reject()
        self.assertEqual(self.repo.list(), [self.existing])
        self.assertIsNone(dialog.result_summary)

    def test_policy_changes_update_actions_counts_and_warning(self):
        dialog = self.dialog()
        dialog.policy.setCurrentIndex(dialog.policy.findData("copy"))
        self.assertEqual(dialog.table.item(0, 2).text(), "Add separate copy")
        self.assertIn("1 copied", dialog.summary.text())
        self.assertTrue(dialog.warning.isHidden())
        dialog.policy.setCurrentIndex(dialog.policy.findData("replace"))
        self.assertEqual(dialog.table.item(0, 2).text(), "Replace")
        self.assertIn("1 replaced", dialog.summary.text())
        self.assertFalse(dialog.warning.isHidden())
        self.assertEqual(self.repo.get(self.existing.id).notes, "Keep original")

    def test_import_only_writes_on_explicit_import(self):
        from PyQt6.QtWidgets import QDialog
        dialog = self.dialog()
        dialog.import_button.click()
        self.assertEqual(dialog.result(), QDialog.DialogCode.Accepted)
        self.assertEqual(dialog.result_summary.added, 1)
        self.assertEqual(dialog.result_summary.skipped, 1)
        self.assertEqual(self.repo.get(self.existing.id).notes, "Keep original")
        self.assertEqual(self.repo.get("new-monster").name, "Goblin")

    def test_import_failure_keeps_preview_open_and_reports_error(self):
        from PyQt6.QtWidgets import QDialog
        dialog = self.dialog()
        with patch.object(self.repo, "import_records", side_effect=sqlite3.OperationalError("Disk full")), \
                patch("dndgm4.import_ui.QMessageBox.warning") as warning:
            dialog.import_button.click()
        self.assertEqual(dialog.result(), QDialog.DialogCode.Rejected)
        self.assertIsNone(dialog.result_summary)
        warning.assert_called_once()
        self.assertEqual(self.repo.list(), [self.existing])

    def test_empty_or_fully_skipped_import_is_disabled(self):
        from dndgm4.import_ui import ImportPreviewDialog
        for records in ((), (self.existing,)):
            dialog = ImportPreviewDialog(self.repo, records)
            self.widgets.append(dialog)
            self.assertFalse(dialog.import_button.isEnabled())

    def test_preview_read_failure_disables_import(self):
        dialog = self.dialog()
        with patch.object(self.repo, "preview_import", side_effect=sqlite3.OperationalError("Locked")):
            dialog.policy.setCurrentIndex(dialog.policy.findData("copy"))
        self.assertFalse(dialog.import_button.isEnabled())
        self.assertIn("Locked", dialog.summary.text())

    def test_main_window_cancel_and_invalid_file_leave_library_unchanged(self):
        from dndgm4.ui import MainWindow
        window = MainWindow(self.repo)
        self.widgets.append(window)
        with patch("dndgm4.ui.QFileDialog.getOpenFileName", return_value=("", "")), \
                patch("dndgm4.ui.read_library_export") as read:
            window.import_library()
        read.assert_not_called()
        with patch("dndgm4.ui.QFileDialog.getOpenFileName", return_value=("bad.json", "")), \
                patch("dndgm4.ui.read_library_export", side_effect=ValueError("Invalid export")), \
                patch("dndgm4.ui.QMessageBox.warning") as warning:
            window.import_library()
        warning.assert_called_once()
        self.assertEqual(self.repo.list(), [self.existing])

    def test_main_window_parses_once_then_refreshes_after_import(self):
        from dndgm4.ui import MainWindow
        window = MainWindow(self.repo)
        self.widgets.append(window)

        def confirm(dialog):
            dialog.import_button.click()
            return dialog.result()

        with patch("dndgm4.ui.QFileDialog.getOpenFileName", return_value=("export.json", "")), \
                patch("dndgm4.ui.read_library_export", return_value=self.records) as read, \
                patch("dndgm4.import_ui.ImportPreviewDialog.exec", confirm):
            window.import_library()
        read.assert_called_once_with("export.json")
        self.assertEqual(window.table.rowCount(), 2)
        self.assertIn("1 added", window.statusBar().currentMessage())
        self.assertEqual(self.repo.get(self.existing.id).notes, "Keep original")

    def test_imported_optional_sheet_metadata_is_safe_to_preview(self):
        from PyQt6.QtCore import Qt
        from dndgm4.library_transfer import read_library_export
        from dndgm4.ui import MainWindow
        cases = (
            ("pc", {"null_abilities": None}, "10", None),
            ("pc", {"null_abilities": [{}, [], "strength"]}, "—", None),
            ("monster", {"monster_type": "Dragon", "computed": None}, "10", "Fort +0"),
            ("monster", {"monster_type": "Dragon", "computed": {
                "fort": None, "ref": "unknown", "will": []}}, "10", "Fort —  /  Ref —  /  Will —"),
        )
        window = MainWindow(self.repo)
        self.widgets.append(window)
        for index, (kind, sheet, strength, saves) in enumerate(cases):
            with self.subTest(sheet=sheet):
                record_id = f"optional-sheet-{index}"
                sheet_json = json.dumps(sheet)
                path = Path(self.tmp.name) / "optional-sheet.json"
                path.write_text(json.dumps({
                    "format": "dndgm4-library", "version": 1, "creatures": [{
                        "id": record_id, "name": f"Imported {index}", "kind": kind,
                        "sheet_json": sheet_json}]}), encoding="utf-8")
                self.repo.import_records(read_library_export(path))
                window.refresh()
                row = next(row for row in range(window.table.rowCount())
                           if window.table.item(row, 0).data(Qt.ItemDataRole.UserRole) == record_id)
                window.table.selectRow(row)
                self.assertEqual(window.selected().id, record_id)
                self.assertEqual(window.stat_values["strength"].text(), strength)
                if saves is not None:
                    self.assertIn(saves, window.detail.text())
                self.assertEqual(self.repo.get(record_id).sheet_json, sheet_json)

    def test_editing_unrecognized_imported_sheet_reports_error_and_preserves_record(self):
        from dndgm4.ui import MainWindow
        imported = replace(self.existing, id="unrecognized-sheet", race_type="Human",
                           character_class="Fighter", sheet_json='{"feats": null}')
        self.repo.import_records((imported,))
        saved = self.repo.get(imported.id)
        window = MainWindow(self.repo)
        self.widgets.append(window)
        window.refresh(select_id=imported.id)
        with patch("dndgm4.ui.QMessageBox.warning") as warning:
            window.edit()
        warning.assert_called_once()
        self.assertIn("unrecognized structure", warning.call_args.args[2])
        self.assertEqual(self.repo.get(imported.id), saved)


if __name__ == "__main__":
    unittest.main()
