"""Review a validated library export before changing permanent records."""
from __future__ import annotations

import sqlite3

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QAbstractItemView, QComboBox, QDialog, QDialogButtonBox, QFormLayout,
    QHeaderView, QLabel, QMessageBox, QTableWidget, QTableWidgetItem, QVBoxLayout,
)

from .models import Creature, KIND_LABELS
from .storage import CreatureRepository


class ImportPreviewDialog(QDialog):
    """Choose how matching record IDs are handled, then import as one batch."""

    def __init__(self, library: CreatureRepository,
                 records: tuple[Creature, ...], parent=None):
        super().__init__(parent)
        self.library = library
        self.records = records
        self.result_summary = None
        self.setWindowTitle("Import Library — Review Records")
        self.resize(760, 540)
        layout = QVBoxLayout(self)
        explanation = QLabel(
            "Review these records before importing. Existing records are matched "
            "by ID; records with the same name and different IDs are added separately.")
        explanation.setWordWrap(True)
        layout.addWidget(explanation)
        options = QFormLayout()
        self.policy = QComboBox()
        self.policy.setAccessibleName("Matching record IDs")
        self.policy.addItem("Skip existing records", "skip")
        self.policy.addItem("Keep both as separate records", "copy")
        self.policy.addItem("Replace existing records", "replace")
        options.addRow("Matching record IDs:", self.policy)
        layout.addLayout(options)
        self.warning = QLabel(
            "Replacing records overwrites their saved fields, including notes, "
            "character sheets, and archived status. Back up the library first "
            "if you need to keep the current versions.")
        self.warning.setWordWrap(True)
        layout.addWidget(self.warning)
        self.table = QTableWidget(len(records), 3)
        self.table.setAccessibleName("Records to import")
        self.table.setHorizontalHeaderLabels(["Name", "Record type", "Import action"])
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        self.table.verticalHeader().hide()
        for row, record in enumerate(records):
            self.table.setItem(row, 0, QTableWidgetItem(record.name))
            self.table.setItem(row, 1, QTableWidgetItem(KIND_LABELS[record.kind]))
        layout.addWidget(self.table)
        self.summary = QLabel()
        self.summary.setTextFormat(Qt.TextFormat.PlainText)
        self.summary.setWordWrap(True)
        layout.addWidget(self.summary)
        self.buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel)
        self.import_button = self.buttons.addButton(
            "Import", QDialogButtonBox.ButtonRole.AcceptRole)
        self.buttons.rejected.connect(self.reject)
        self.import_button.clicked.connect(self.import_records)
        layout.addWidget(self.buttons)
        self.policy.currentIndexChanged.connect(self.update_preview)
        self.update_preview()

    def update_preview(self):
        policy = self.policy.currentData()
        try:
            summary = self.library.preview_import(self.records, duplicates=policy)
            existing_ids = {record.id for record in self.library.list(include_archived=True)}
        except (OSError, ValueError, sqlite3.Error) as exc:
            self.summary.setText(f"Unable to preview import: {exc}")
            self.import_button.setEnabled(False)
            self.warning.hide()
            return
        conflict_action = {"skip": "Skip", "copy": "Add separate copy", "replace": "Replace"}
        for row, record in enumerate(self.records):
            action = conflict_action[policy] if record.id in existing_ids else "Add"
            self.table.setItem(row, 2, QTableWidgetItem(action))
        self.warning.setVisible(policy == "replace" and summary.replaced > 0)
        self.summary.setText(
            f"{summary.total} records: {summary.added} added, {summary.copied} copied, "
            f"{summary.replaced} replaced, {summary.skipped} skipped.")
        self.import_button.setEnabled(summary.added + summary.copied + summary.replaced > 0)

    def import_records(self):
        try:
            summary = self.library.import_records(
                self.records, duplicates=self.policy.currentData())
        except (OSError, ValueError, sqlite3.Error) as exc:
            QMessageBox.warning(self, "Import Library", str(exc))
            return
        self.result_summary = summary
        self.accept()
