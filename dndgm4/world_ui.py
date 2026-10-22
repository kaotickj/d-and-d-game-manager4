"""A campaign's world desk: typed journals, references, and safe player handouts."""
from __future__ import annotations

from dataclasses import replace
import sqlite3

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFileDialog, QFormLayout,
    QHBoxLayout, QLabel, QLineEdit, QListWidget, QListWidgetItem, QMessageBox,
    QPlainTextEdit, QPushButton, QScrollArea, QSpinBox, QSplitter, QTabWidget,
    QVBoxLayout, QWidget,
)

from .world import (
    DETAIL_FIELDS, KIND_LABELS, STATUSES, WorldRecord,
    build_world_context, default_details, details_json,
)


def _label(text):
    widget = QLabel(text)
    widget.setWordWrap(True)
    widget.setTextFormat(Qt.TextFormat.PlainText)
    return widget


def _button(text, callback):
    widget = QPushButton(text)
    widget.clicked.connect(callback)
    return widget


def _status_label(status):
    return status.replace("_", " ").capitalize()


class RelationshipDialog(QDialog):
    def __init__(self, records, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Add Campaign Relationship")
        layout = QVBoxLayout(self)
        layout.addWidget(_label("Record a directed relationship from the selected entry. Relationship notes are DM-only."))
        form = QFormLayout()
        self.target = QComboBox()
        for record in records:
            self.target.addItem(f"{record.name} · {KIND_LABELS[record.kind]}", record.id)
        form.addRow("Related entry", self.target)
        self.relation = QLineEdit()
        self.relation.setMaxLength(120)
        self.relation.setPlaceholderText("for example: based in, opposes, rewards")
        form.addRow("Relationship", self.relation)
        self.notes = QPlainTextEdit()
        form.addRow("DM-only notes", self.notes)
        layout.addLayout(form)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self.resize(530, 330)


class WorldManagerDialog(QDialog):
    """Explicit saves and selection changes; never activates a workspace."""

    context_requested = pyqtSignal(str)

    def __init__(self, repository, campaign_id, library=None, parent=None):
        super().__init__(parent)
        campaign = repository.campaigns.get_campaign(campaign_id)
        if campaign is None:
            raise ValueError("Select a saved campaign before opening the World & Campaign Desk.")
        self.repository = repository
        self.campaign_id = campaign_id
        self.library = library or repository.library
        self._record = None
        self._dirty = False
        self._loading = False
        self._detail_widgets = {}
        self._handout_previews = []
        self._applied_filters = (None, None, "", False)
        self.setAttribute(Qt.WidgetAttribute.WA_QuitOnClose, False)
        self.setWindowTitle(f"World & Campaign Desk · {campaign.name}")
        self.resize(1130, 800)
        self.setMinimumSize(830, 540)
        layout = QVBoxLayout(self)
        title = _label("WORLD & CAMPAIGN DESK")
        title.setObjectName("pageTitle")
        layout.addWidget(title)
        layout.addWidget(_label(
            f"{campaign.name} · Quests, places, factions, handouts, events, travel, inventory, and rewards. "
            "Entries are campaign journals; saving inventory or rewards does not change character sheets, XP, or gold."))
        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setChildrenCollapsible(False)
        layout.addWidget(splitter, 1)
        navigation = QWidget()
        nav = QVBoxLayout(navigation)
        nav.setContentsMargins(0, 0, 8, 0)
        self.search = QLineEdit()
        self.search.setAccessibleName("Search campaign world entries")
        self.search.setPlaceholderText("Search names, notes, and details…")
        self.search.setMaxLength(500)
        self.search.setClearButtonEnabled(True)
        nav.addWidget(self.search)
        self.kind_filter = QComboBox()
        self.kind_filter.setAccessibleName("Filter world entries by type")
        self.kind_filter.addItem("All entry types", None)
        for kind, label in KIND_LABELS.items():
            self.kind_filter.addItem(label, kind)
        nav.addWidget(self.kind_filter)
        self.status_filter = QComboBox()
        self.status_filter.setAccessibleName("Filter world entries by status")
        self._fill_status_filter()
        nav.addWidget(self.status_filter)
        self.show_archived = QCheckBox("Include archived entries")
        nav.addWidget(self.show_archived)
        self.entries = QListWidget()
        self.entries.setAccessibleName("Campaign world entries")
        self.entries.currentItemChanged.connect(self._selection_changed)
        nav.addWidget(self.entries, 1)
        self.result_count = _label("")
        nav.addWidget(self.result_count)
        nav.addWidget(_label("Create an entry"))
        self.new_kind = QComboBox()
        self.new_kind.setAccessibleName("New world entry type")
        for kind, label in KIND_LABELS.items():
            self.new_kind.addItem(label, kind)
        nav.addWidget(self.new_kind)
        self.new_button = _button("New Entry", self.new_record)
        nav.addWidget(self.new_button)
        splitter.addWidget(navigation)
        self.editor = QWidget()
        editor = QVBoxLayout(self.editor)
        editor.setContentsMargins(8, 0, 0, 0)
        common = QFormLayout()
        self.name = QLineEdit()
        self.name.setMaxLength(200)
        self.name.setAccessibleName("World entry name")
        common.addRow("Name", self.name)
        self.kind_label = _label("")
        common.addRow("Type", self.kind_label)
        self.entry_status = QComboBox()
        self.entry_status.setAccessibleName("World entry status")
        common.addRow("Status", self.entry_status)
        self.archived_label = _label("")
        common.addRow(self.archived_label)
        editor.addLayout(common)
        self.tabs = QTabWidget()
        editor.addWidget(self.tabs, 1)
        detail_scroll = QScrollArea()
        detail_scroll.setWidgetResizable(True)
        detail_body = QWidget()
        self.detail_form = QFormLayout(detail_body)
        self.detail_form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        self.detail_form.setLabelAlignment(Qt.AlignmentFlag.AlignTop)
        detail_scroll.setWidget(detail_body)
        self.tabs.addTab(detail_scroll, "Typed Details")
        notes = QWidget()
        notes_layout = QVBoxLayout(notes)
        notes_layout.addWidget(_label("Public summary"))
        self.summary = QPlainTextEdit()
        self.summary.setAccessibleName("World entry public summary")
        notes_layout.addWidget(self.summary, 1)
        notes_layout.addWidget(_label("DM-only notes · never included in player handout exports"))
        self.dm_notes = QPlainTextEdit()
        self.dm_notes.setAccessibleName("World entry DM-only notes")
        notes_layout.addWidget(self.dm_notes, 2)
        self.tabs.addTab(notes, "Summary & DM Notes")
        relationships = QWidget()
        relationship_layout = QVBoxLayout(relationships)
        relationship_layout.addWidget(_label(
            "Directed links between entries in this campaign. Character and NPC references are selected in Typed Details. "
            "Relationship notes are DM-only."))
        self.relationships = QListWidget()
        self.relationships.setAccessibleName("World entry relationships")
        self.relationships.currentItemChanged.connect(self._sync_actions)
        relationship_layout.addWidget(self.relationships, 1)
        relationship_buttons = QHBoxLayout()
        self.add_relationship_button = _button("Add Relationship…", self.add_relationship)
        self.remove_relationship_button = _button("Remove Selected Relationship", self.remove_relationship)
        relationship_buttons.addWidget(self.add_relationship_button)
        relationship_buttons.addWidget(self.remove_relationship_button)
        relationship_layout.addLayout(relationship_buttons)
        self.tabs.addTab(relationships, "Relationships")
        splitter.addWidget(self.editor)
        splitter.setStretchFactor(0, 2)
        splitter.setStretchFactor(1, 4)
        splitter.setSizes([330, 730])
        self.message = _label("")
        self.message.setAccessibleName("World desk status")
        layout.addWidget(self.message)
        actions = QHBoxLayout()
        self.save_button = _button("Save Entry", self.save_changes)
        self.save_button.setObjectName("primaryButton")
        self.archive_button = _button("Archive Entry", self.toggle_archive)
        self.context_button = _button("Load Saved Entry into Scribe", self.load_context)
        actions.addWidget(self.save_button)
        actions.addWidget(self.archive_button)
        actions.addWidget(self.context_button)
        layout.addLayout(actions)
        output = QHBoxLayout()
        self.preview_button = _button("Preview Player Handout…", self.preview_handout)
        self.export_button = _button("Export Player Text…", self.export_handout)
        output.addWidget(self.preview_button)
        output.addWidget(self.export_button)
        output.addStretch()
        output.addWidget(_button("Close", self.reject))
        layout.addLayout(output)
        self.name.textChanged.connect(self._mark_dirty)
        self.entry_status.currentIndexChanged.connect(self._mark_dirty)
        self.summary.textChanged.connect(self._mark_dirty)
        self.dm_notes.textChanged.connect(self._mark_dirty)
        self.search.textChanged.connect(self._filter_changed)
        self.kind_filter.currentIndexChanged.connect(self._filter_changed)
        self.status_filter.currentIndexChanged.connect(self._filter_changed)
        self.show_archived.toggled.connect(self._filter_changed)
        self.refresh_entries()

    def _report(self, error):
        self.message.setText("Could not complete the action: " + str(error))

    def _mark_dirty(self, *args):
        if not self._loading and self._record is not None:
            self._dirty = True
            self._sync_actions()

    def _sync_actions(self, *args):
        saved = self._record is not None and bool(self._record.id)
        handout = saved and self._record.kind == "handout"
        self.save_button.setEnabled(self._record is not None and self._dirty)
        self.archive_button.setEnabled(saved)
        self.archive_button.setText("Restore Entry" if saved and self._record.archived else "Archive Entry")
        self.context_button.setEnabled(saved)
        self.preview_button.setEnabled(handout)
        self.export_button.setEnabled(handout)
        self.add_relationship_button.setEnabled(saved)
        self.remove_relationship_button.setEnabled(saved and self.relationships.currentItem() is not None)

    def _fill_status_filter(self, preferred=None):
        kind = self.kind_filter.currentData()
        statuses = STATUSES[kind] if kind else sorted({s for values in STATUSES.values() for s in values})
        self.status_filter.blockSignals(True)
        self.status_filter.clear()
        self.status_filter.addItem("All statuses", None)
        for status in statuses:
            self.status_filter.addItem(_status_label(status), status)
        index = self.status_filter.findData(preferred)
        self.status_filter.setCurrentIndex(max(0, index))
        self.status_filter.blockSignals(False)

    def _read_filters(self):
        return (self.kind_filter.currentData(), self.status_filter.currentData(),
                self.search.text(), self.show_archived.isChecked())

    def _restore_filters(self, filters):
        kind, status, query, archived = filters
        for widget in (self.kind_filter, self.status_filter, self.search, self.show_archived):
            widget.blockSignals(True)
        self.kind_filter.setCurrentIndex(self.kind_filter.findData(kind))
        self._fill_status_filter(status)
        self.search.setText(query)
        self.show_archived.setChecked(archived)
        for widget in (self.kind_filter, self.status_filter, self.search, self.show_archived):
            widget.blockSignals(False)

    def _filter_changed(self, *args):
        if self._loading:
            return
        if not self._confirm_changes():
            self._restore_filters(self._applied_filters)
            return
        self._fill_status_filter(self.status_filter.currentData())
        if not self.refresh_entries():
            self._restore_filters(self._applied_filters)

    @staticmethod
    def _item_id(item):
        return item.data(Qt.ItemDataRole.UserRole) if item is not None else ""

    def _select_id(self, identity):
        for row in range(self.entries.count()):
            if self._item_id(self.entries.item(row)) == identity:
                self.entries.setCurrentRow(row)
                return True
        self.entries.setCurrentRow(-1)
        return False

    @staticmethod
    def _entry_label(record):
        archived = " · ARCHIVED" if record.archived else ""
        return f"{record.name}\n{KIND_LABELS[record.kind]} · {_status_label(record.status)}{archived}"

    def refresh_entries(self, preferred_id=None):
        filters = self._read_filters()
        kind, status, query, archived = filters
        if preferred_id is None and self._record is not None:
            preferred_id = self._record.id
        try:
            records = self.repository.list(self.campaign_id, kind=kind, status=status,
                                           query=query, include_archived=archived)
            selected = next((record for record in records if record.id == preferred_id), records[0] if records else None)
            # Resolve references before replacing the list or any unsaved editor.
            choices = self._reference_choices(selected)
            links = self._relationship_rows(selected)
        except (ValueError, OSError, sqlite3.Error) as exc:
            self._report(exc)
            return False
        self.entries.blockSignals(True)
        self.entries.clear()
        for record in records:
            item = QListWidgetItem(self._entry_label(record))
            item.setData(Qt.ItemDataRole.UserRole, record.id)
            self.entries.addItem(item)
        self._select_id(selected.id if selected else "")
        self.entries.blockSignals(False)
        self._show_record(selected, choices=choices, links=links)
        self._applied_filters = filters
        self.result_count.setText(f"{len(records)} entries")
        return True

    def _selection_changed(self, current, previous):
        if self._loading:
            return
        target = self._item_id(current)
        previous_id = self._record.id if self._record is not None else ""
        if not self._confirm_changes():
            self.entries.blockSignals(True)
            self._select_id(previous_id)
            self.entries.blockSignals(False)
            return
        try:
            record = self.repository.get(target) if target else None
            if target and (record is None or record.campaign_id != self.campaign_id):
                raise ValueError("The selected campaign entry is missing or belongs to another campaign.")
            choices = self._reference_choices(record)
            links = self._relationship_rows(record)
        except (ValueError, OSError, sqlite3.Error) as exc:
            self._report(exc)
            self.entries.blockSignals(True)
            self._select_id(previous_id)
            self.entries.blockSignals(False)
            return
        self._show_record(record, choices=choices, links=links)

    def _reference_choices(self, record):
        if record is None:
            return {}
        types = {field.type for field in DETAIL_FIELDS[record.kind]}
        result = {}
        if "creatures" in types:
            result["creatures"] = self.library.list(include_archived=True)
        if "location" in types:
            result["location"] = self.repository.list(self.campaign_id, kind="location", include_archived=True)
        return result

    def _relationship_rows(self, record):
        if record is None or not record.id:
            return []
        result = []
        for link in self.repository.list_links(self.campaign_id, record.id):
            source = self.repository.get(link.source_id)
            target = self.repository.get(link.target_id)
            if source is None or target is None:
                raise ValueError("A related entry is missing. No relationship was silently omitted.")
            text = f"{source.name} → {link.relation} → {target.name}"
            if link.notes:
                text += "\nDM: " + link.notes
            result.append((link.id, text))
        return result

    def _show_record(self, record, *, choices=None, links=None):
        choices = self._reference_choices(record) if choices is None else choices
        links = self._relationship_rows(record) if links is None else links
        self._loading = True
        try:
            self._record = record
            self.name.setText(record.name if record else "")
            self.kind_label.setText(KIND_LABELS[record.kind] if record else "Select an entry or create one")
            self.entry_status.clear()
            if record:
                for status in STATUSES[record.kind]:
                    self.entry_status.addItem(_status_label(status), status)
                self.entry_status.setCurrentIndex(self.entry_status.findData(record.status))
            self.archived_label.setText("Archived · retained in this campaign" if record and record.archived else "")
            self.summary.setPlainText(record.summary if record else "")
            self.dm_notes.setPlainText(record.dm_notes if record else "")
            while self.detail_form.rowCount():
                self.detail_form.removeRow(0)
            self._detail_widgets = {}
            if record:
                values = record.details
                for field in DETAIL_FIELDS[record.kind]:
                    widget = self._make_detail_widget(field, values[field.key], choices)
                    widget.setAccessibleName(field.label)
                    self._detail_widgets[field.key] = widget
                    self.detail_form.addRow(field.label, widget)
                if record.kind in ("item", "reward"):
                    self.detail_form.addRow(_label(
                        "Journal entry only. No character inventory, XP, gold, or level is changed by saving."))
                elif record.kind == "event":
                    self.detail_form.addRow(_label(
                        "Campaign day is a fictional day number. This entry does not advance time or trigger automatic events."))
                elif record.kind == "handout":
                    self.detail_form.addRow(_label(
                        "Preview and export include exactly Player text. The entry name, summary, typed metadata, and DM notes are excluded."))
            self.relationships.clear()
            for identity, text in links:
                item = QListWidgetItem(text)
                item.setData(Qt.ItemDataRole.UserRole, identity)
                self.relationships.addItem(item)
            self.editor.setEnabled(record is not None)
            self._dirty = False
        finally:
            self._loading = False
        self._sync_actions()

    def _make_detail_widget(self, field, value, choices):
        if field.type == "integer":
            widget = QSpinBox()
            widget.setRange(0, field.maximum)
            widget.setValue(value)
            widget.valueChanged.connect(self._mark_dirty)
        elif field.type == "multiline":
            widget = QPlainTextEdit()
            widget.setPlainText(value)
            widget.setMinimumHeight(100)
            widget.textChanged.connect(self._mark_dirty)
        elif field.type == "creatures":
            widget = QListWidget()
            widget.setMinimumHeight(120)
            widget.setMaximumHeight(190)
            found = set()
            for creature in choices.get("creatures", []):
                found.add(creature.id)
                archived = " · archived" if creature.archived else ""
                item = QListWidgetItem(f"{creature.name} · {creature.kind.upper()}{archived}")
                item.setData(Qt.ItemDataRole.UserRole, creature.id)
                item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
                item.setCheckState(Qt.CheckState.Checked if creature.id in value else Qt.CheckState.Unchecked)
                widget.addItem(item)
            for identity in value:
                if identity not in found:
                    item = QListWidgetItem(f"Missing library record · {identity} (uncheck to revise)")
                    item.setData(Qt.ItemDataRole.UserRole, identity)
                    item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
                    item.setCheckState(Qt.CheckState.Checked)
                    widget.addItem(item)
            widget.itemChanged.connect(self._mark_dirty)
        elif field.type == "location":
            widget = QComboBox()
            widget.addItem("Not selected", "")
            for location in choices.get("location", []):
                widget.addItem(location.name + (" · archived" if location.archived else ""), location.id)
            index = widget.findData(value)
            if value and index < 0:
                widget.addItem("Missing location · " + value, value)
                index = widget.findData(value)
            widget.setCurrentIndex(max(0, index))
            widget.currentIndexChanged.connect(self._mark_dirty)
        else:
            widget = QLineEdit()
            widget.setMaxLength(field.maximum if field.type == "text" else 40)
            widget.setText(str(value))
            if field.type == "decimal":
                widget.setPlaceholderText("0.00" if field.places == 2 else "0.000")
            elif field.type == "time":
                widget.setPlaceholderText("HH:MM")
            widget.textChanged.connect(self._mark_dirty)
        return widget

    def _details_from_form(self):
        details = {}
        for field in DETAIL_FIELDS[self._record.kind]:
            widget = self._detail_widgets[field.key]
            if field.type == "integer":
                value = widget.value()
            elif field.type == "multiline":
                value = widget.toPlainText()
            elif field.type == "creatures":
                value = [widget.item(row).data(Qt.ItemDataRole.UserRole) for row in range(widget.count())
                         if widget.item(row).checkState() == Qt.CheckState.Checked]
            elif field.type == "location":
                value = widget.currentData()
            else:
                value = widget.text()
            details[field.key] = value
        return details

    def new_record(self):
        if not self._confirm_changes():
            return
        kind = self.new_kind.currentData()
        draft = WorldRecord("", self.campaign_id, kind, "", STATUSES[kind][0],
                            details_json=details_json(kind, default_details(kind)))
        try:
            choices = self._reference_choices(draft)
        except (ValueError, OSError, sqlite3.Error) as exc:
            self._report(exc)
            return
        self.entries.blockSignals(True)
        self.entries.setCurrentRow(-1)
        self.entries.blockSignals(False)
        self._show_record(draft, choices=choices, links=[])
        self._dirty = True
        self.message.setText("New entry · Save Entry adds it to this campaign.")
        self._sync_actions()
        self.name.setFocus()

    def save_changes(self, checked=False, *, refresh=True):
        if self._record is None:
            return True
        if not self._dirty:
            return True
        try:
            details = self._details_from_form()
            if self._record.id:
                saved = self.repository.save(replace(
                    self._record, name=self.name.text(), status=self.entry_status.currentData(),
                    summary=self.summary.toPlainText(), dm_notes=self.dm_notes.toPlainText(),
                    details_json=details_json(self._record.kind, details)))
            else:
                saved = self.repository.create(
                    self.campaign_id, self._record.kind, self.name.text(),
                    status=self.entry_status.currentData(), summary=self.summary.toPlainText(),
                    dm_notes=self.dm_notes.toPlainText(), details=details)
            # Keep the saved identity even if a subsequent refresh cannot read.
            self._record = saved
            self._dirty = False
            for row in range(self.entries.count()):
                item = self.entries.item(row)
                if self._item_id(item) == saved.id:
                    item.setText(self._entry_label(saved))
            if refresh:
                if not self.refresh_entries(preferred_id=saved.id):
                    self._sync_actions()
                    return True
            else:
                self._sync_actions()
            self.message.setText("Entry saved. Character sheets and the active workspace were not changed.")
            return True
        except (ValueError, OSError, sqlite3.Error) as exc:
            self._report(exc)
            return False

    def _confirm_changes(self):
        if not self._dirty:
            return True
        choice = QMessageBox.question(
            self, "Unsaved World Entry", "Save changes to this entry before continuing?",
            QMessageBox.StandardButton.Save | QMessageBox.StandardButton.Discard | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel)
        if choice == QMessageBox.StandardButton.Save:
            return self.save_changes(refresh=False)
        if choice != QMessageBox.StandardButton.Discard:
            return False
        try:
            record = self.repository.get(self._record.id) if self._record and self._record.id else None
            if self._record and self._record.id and record is None:
                raise ValueError("The saved entry no longer exists. Your draft has been kept.")
            self._show_record(record)
            return True
        except (ValueError, OSError, sqlite3.Error) as exc:
            self._report(exc)
            return False

    def toggle_archive(self):
        if not self._confirm_changes() or self._record is None or not self._record.id:
            return
        try:
            saved = self.repository.set_archived(self._record.id, not self._record.archived)
            self._record = saved
            self.refresh_entries(preferred_id=saved.id)
            self.message.setText("Entry archived; it remains saved." if saved.archived else "Entry restored.")
        except (ValueError, OSError, sqlite3.Error) as exc:
            self._report(exc)

    def add_relationship(self):
        if not self._confirm_changes() or self._record is None or not self._record.id:
            return
        try:
            records = [record for record in self.repository.list(self.campaign_id)
                       if record.id != self._record.id]
            if not records:
                raise ValueError("Create another entry in this campaign before adding a relationship.")
            dialog = RelationshipDialog(records, self)
            if dialog.exec() != QDialog.DialogCode.Accepted:
                return
            self.repository.create_link(self.campaign_id, self._record.id, dialog.target.currentData(),
                                        dialog.relation.text(), dialog.notes.toPlainText())
            self._show_record(self.repository.get(self._record.id))
            self.message.setText("Relationship saved.")
        except (ValueError, OSError, sqlite3.Error) as exc:
            self._report(exc)

    def remove_relationship(self):
        item = self.relationships.currentItem()
        identity = self._item_id(item)
        if not identity or not self._confirm_changes() or self._record is None:
            return
        try:
            self.repository.delete_link(identity, campaign_id=self.campaign_id)
            self._show_record(self.repository.get(self._record.id))
            self.message.setText("Relationship removed.")
        except (ValueError, OSError, sqlite3.Error) as exc:
            self._report(exc)

    def _saved_handout(self):
        if not self._confirm_changes() or self._record is None or not self._record.id:
            return None
        try:
            text = self.repository.player_handout(self._record.id)
            if not text.strip():
                raise ValueError("Write player text before previewing or exporting this handout.")
            return text
        except (ValueError, OSError, sqlite3.Error) as exc:
            self._report(exc)
            return None

    def preview_handout(self):
        text = self._saved_handout()
        if text is None:
            return
        preview = QDialog(self)
        preview.setAttribute(Qt.WidgetAttribute.WA_QuitOnClose, False)
        preview.setWindowTitle("Player Handout Preview")
        layout = QVBoxLayout(preview)
        body = QPlainTextEdit()
        body.setAccessibleName("Player handout text only")
        body.setReadOnly(True)
        body.setPlainText(text)
        layout.addWidget(body)
        layout.addWidget(_button("Close", preview.close))
        preview.resize(680, 520)
        self._handout_previews.append(preview)
        preview.show()

    def export_handout(self):
        if self._saved_handout() is None:
            return
        destination, _ = QFileDialog.getSaveFileName(self, "Export Player Text", "player-handout.txt", "Text files (*.txt)")
        if not destination:
            return
        try:
            self.repository.export_player_handout(self._record.id, destination)
            self.message.setText("Player text exported. Private fields were excluded.")
        except (ValueError, OSError, sqlite3.Error) as exc:
            self._report(exc)

    def load_context(self):
        if not self._confirm_changes() or self._record is None or not self._record.id:
            return
        try:
            context = build_world_context(self.repository, self._record.id)
            # Close the modal desk before the parent opens an interactive Scribe.
            self.accept()
            self.context_requested.emit(context)
            self.message.setText("Complete saved entry loaded into Scribe context. No AI request was run.")
        except (ValueError, OSError, sqlite3.Error) as exc:
            self._report(exc)

    def reject(self):
        if self._confirm_changes():
            super().reject()

    def closeEvent(self, event):
        if self._confirm_changes():
            event.accept()
        else:
            event.ignore()
