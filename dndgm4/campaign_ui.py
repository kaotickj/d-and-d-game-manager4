"""Campaign journals and explicit workspace selection, independent of activation."""
from __future__ import annotations

from dataclasses import replace
import sqlite3

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QFormLayout, QHBoxLayout, QInputDialog,
    QLabel, QLineEdit, QListWidget, QListWidgetItem, QMessageBox,
    QPlainTextEdit, QPushButton, QScrollArea, QSplitter, QTabWidget,
    QVBoxLayout, QWidget,
)

from .campaigns import ActiveWorkspace


def _label(text):
    label = QLabel(text)
    label.setWordWrap(True)
    return label


def _button(text, callback, accessible=None):
    button = QPushButton(text)
    button.clicked.connect(callback)
    if accessible:
        button.setAccessibleName(accessible)
    return button


class CampaignManagerDialog(QDialog):
    """Save journal edits explicitly; let MainWindow activate reviewed choices."""

    def __init__(self, repository, library, parent=None):
        super().__init__(parent)
        self.repository = repository
        self.library = library
        self.result_workspace = None
        self.result_action = ""
        self.result_session_id = ""
        self.result_task = ""
        self._campaign = None
        self._session = None
        self._loading = False
        self._campaign_dirty = False
        self._session_dirty = False
        self.setAttribute(Qt.WidgetAttribute.WA_QuitOnClose, False)
        self.setWindowTitle("Campaigns & Sessions | D&D Game Manager 4")
        self.resize(1100, 760)
        self.setMinimumSize(830, 540)
        root = QVBoxLayout(self)
        heading = _label("CAMPAIGNS & SESSIONS")
        heading.setObjectName("pageTitle")
        root.addWidget(heading)
        root.addWidget(_label(
            "Keep a party, journal, scene, and named encounters for each campaign. "
            "Save journal edits here; Open loads the selected session and encounter."))
        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setChildrenCollapsible(False)
        root.addWidget(splitter, 1)
        navigation = QWidget()
        nav = QVBoxLayout(navigation)
        nav.setContentsMargins(0, 0, 8, 0)
        self.show_archived = QCheckBox("Include archived campaigns")
        self.show_archived.toggled.connect(self.refresh_campaigns)
        nav.addWidget(self.show_archived)
        self.campaigns = QListWidget()
        self.campaigns.setAccessibleName("Campaigns")
        self.campaigns.setMinimumHeight(80)
        self.campaigns.currentItemChanged.connect(self._campaign_selected)
        nav.addWidget(self.campaigns, 1)
        nav.addWidget(_button("New Campaign…", self.new_campaign))
        nav.addWidget(_label("Sessions"))
        self.sessions = QListWidget()
        self.sessions.setAccessibleName("Campaign sessions")
        self.sessions.setMinimumHeight(80)
        self.sessions.currentItemChanged.connect(self._session_selected)
        nav.addWidget(self.sessions, 1)
        self.new_session_button = _button("New Session…", self.new_session)
        nav.addWidget(self.new_session_button)
        nav.addWidget(_label("Saved encounters"))
        self.encounters = QListWidget()
        self.encounters.setAccessibleName("Session encounters")
        self.encounters.setMinimumHeight(70)
        self.encounters.currentItemChanged.connect(self._sync_actions)
        nav.addWidget(self.encounters, 1)
        encounter_buttons = QHBoxLayout()
        self.new_encounter_button = _button("New…", self.new_encounter, "Create a named encounter")
        self.rename_encounter_button = _button("Rename…", self.rename_encounter, "Rename selected encounter")
        encounter_buttons.addWidget(self.new_encounter_button)
        encounter_buttons.addWidget(self.rename_encounter_button)
        nav.addLayout(encounter_buttons)
        navigation_scroll = QScrollArea()
        navigation_scroll.setWidgetResizable(True)
        navigation_scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        navigation_scroll.setMinimumWidth(230)
        navigation_scroll.setWidget(navigation)
        splitter.addWidget(navigation_scroll)
        self.tabs = QTabWidget()
        self.tabs.setAccessibleName("Campaign and session journal")
        splitter.addWidget(self.tabs)
        splitter.setStretchFactor(0, 2)
        splitter.setStretchFactor(1, 3)
        splitter.setSizes([350, 700])

        campaign_page, campaign_form = self._form_page()
        self.campaign_name = QLineEdit()
        self.campaign_name.setMaxLength(200)
        self.campaign_name.setAccessibleName("Campaign name")
        campaign_form.addRow("Name", self.campaign_name)
        self.campaign_description = QPlainTextEdit()
        self.campaign_description.setAccessibleName("Campaign description")
        self.campaign_description.setMinimumHeight(100)
        campaign_form.addRow("Premise / description", self.campaign_description)
        self.campaign_notes = QPlainTextEdit()
        self.campaign_notes.setAccessibleName("Campaign DM notes")
        self.campaign_notes.setMinimumHeight(180)
        campaign_form.addRow("Campaign / DM notes", self.campaign_notes)
        self.campaign_archived = QCheckBox("Archive this campaign")
        campaign_form.addRow(self.campaign_archived)
        campaign_form.addRow(_label("Archived campaigns remain saved. Unarchive and save before opening them."))
        self.tabs.addTab(campaign_page, "Campaign")
        self.campaign_page = campaign_page

        party_page = QWidget()
        party_layout = QVBoxLayout(party_page)
        party_layout.addWidget(_label(
            "Choose the campaign's party and companions. Membership does not change "
            "the saved character or put it into every scene automatically."))
        self.party = QListWidget()
        self.party.setAccessibleName("Campaign party and companions")
        self.party.itemChanged.connect(self._mark_campaign_dirty)
        party_layout.addWidget(self.party, 1)
        self.tabs.addTab(party_page, "Party")
        self.party_page = party_page

        session_page, session_form = self._form_page()
        self.session_title = QLineEdit()
        self.session_title.setMaxLength(200)
        self.session_title.setAccessibleName("Session title")
        session_form.addRow("Title", self.session_title)
        self.session_date = QLineEdit()
        self.session_date.setPlaceholderText("YYYY-MM-DD (optional)")
        self.session_date.setAccessibleName("Session date in YYYY-MM-DD format")
        session_form.addRow("Date", self.session_date)
        self.session_status = QComboBox()
        for label, value in (("Planned", "planned"), ("In progress", "in_progress"), ("Completed", "completed")):
            self.session_status.addItem(label, value)
        self.session_status.setAccessibleName("Session status")
        session_form.addRow("Status", self.session_status)
        self.session_notes = QPlainTextEdit()
        self.session_notes.setAccessibleName("Session preparation and event notes")
        self.session_notes.setMinimumHeight(150)
        session_form.addRow("Preparation / event notes", self.session_notes)
        self.session_recap = QPlainTextEdit()
        self.session_recap.setAccessibleName("Session recap")
        self.session_recap.setMinimumHeight(150)
        session_form.addRow("Reviewed recap", self.session_recap)
        self.tabs.addTab(session_page, "Session Journal")
        self.session_page = session_page
        for field in (self.campaign_name,):
            field.textChanged.connect(self._mark_campaign_dirty)
        for field in (self.campaign_description, self.campaign_notes):
            field.textChanged.connect(self._mark_campaign_dirty)
        self.campaign_archived.toggled.connect(self._mark_campaign_dirty)
        for field in (self.session_title, self.session_date):
            field.textChanged.connect(self._mark_session_dirty)
        for field in (self.session_notes, self.session_recap):
            field.textChanged.connect(self._mark_session_dirty)
        self.session_status.currentIndexChanged.connect(self._mark_session_dirty)

        self.status = _label("")
        self.status.setTextFormat(Qt.TextFormat.PlainText)
        root.addWidget(self.status)
        edits = QHBoxLayout()
        self.save_button = _button("Save Journal Changes", self.save_changes)
        self.save_button.setObjectName("primaryButton")
        edits.addWidget(self.save_button)
        self.plan_button = _button("Plan Session in Scribe", lambda: self.request_scribe("session_plan"))
        self.campaign_plan_button = _button("Plan Campaign in Scribe", lambda: self.request_scribe("campaign_plan"))
        self.recap_button = _button("Recap in Scribe", lambda: self.request_scribe("recap"))
        edits.addWidget(self.plan_button)
        edits.addWidget(self.campaign_plan_button)
        edits.addWidget(self.recap_button)
        root.addLayout(edits)
        actions = QHBoxLayout()
        self.open_button = _button("Open Selected Session / Encounter", self.open_selected)
        actions.addWidget(self.open_button)
        self.import_button = _button("Import Standalone Scene/Battle", self.import_legacy)
        self.import_button.setToolTip("Copy the standalone local scene and battle into a new session in this campaign.")
        actions.addWidget(self.import_button)
        actions.addWidget(_button("Standalone Workspace", self.use_standalone))
        actions.addWidget(_button("Close", self.reject))
        root.addLayout(actions)
        try:
            workspace = self.repository.get_workspace()
        except ValueError:
            # Let the manager repair an archived or inconsistent selection;
            # opening it must not erase the stored workspace automatically.
            workspace = ActiveWorkspace()
        self.refresh_campaigns(preferred_id=workspace.campaign_id)
        if workspace.session_id:
            self._select_id(self.sessions, workspace.session_id)
        if workspace.encounter_id:
            self._select_id(self.encounters, workspace.encounter_id)
        self._sync_actions()

    @staticmethod
    def _form_page():
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        body = QWidget()
        form = QFormLayout(body)
        form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignTop)
        scroll.setWidget(body)
        return scroll, form

    @staticmethod
    def _id(item):
        return item.data(Qt.ItemDataRole.UserRole) if item is not None else ""

    def _select_id(self, widget, record_id):
        for row in range(widget.count()):
            if self._id(widget.item(row)) == record_id:
                widget.setCurrentRow(row)
                return True
        return False

    def _item_by_id(self, widget, record_id):
        for row in range(widget.count()):
            item = widget.item(row)
            if self._id(item) == record_id:
                return item
        return None

    def _mark_campaign_dirty(self, *args):
        if not self._loading and self._campaign is not None:
            self._campaign_dirty = True
            self._sync_actions()

    def _mark_session_dirty(self, *args):
        if not self._loading and self._session is not None:
            self._session_dirty = True
            self._sync_actions()

    def _confirm_edits(self):
        if not (self._campaign_dirty or self._session_dirty):
            return True
        answer = QMessageBox.question(
            self, "Unsaved journal changes", "Save the campaign or session changes before continuing?",
            QMessageBox.StandardButton.Save | QMessageBox.StandardButton.Discard |
            QMessageBox.StandardButton.Cancel, QMessageBox.StandardButton.Save)
        if answer == QMessageBox.StandardButton.Cancel:
            return False
        if answer == QMessageBox.StandardButton.Save:
            return self.save_changes()
        self._campaign_dirty = self._session_dirty = False
        return True

    def _restore_selection(self, widget, record_id):
        self._loading = True
        try:
            self._select_id(widget, record_id)
        finally:
            self._loading = False

    def _read_error(self, exc):
        # Qt signal callbacks must report a failed read rather than allow an
        # exception to escape the event loop. Disable editors until reloaded.
        self._loading = False
        self._campaign = self._session = None
        self._campaign_dirty = self._session_dirty = False
        self._sync_actions()
        self.status.setText("The journal could not be loaded. Reopen the manager after resolving the error.")
        QMessageBox.warning(self, "Cannot read campaign journal", str(exc))

    def refresh_campaigns(self, *args, preferred_id=None):
        if self._loading:
            return
        current = self._campaign.id if self._campaign is not None else ""
        if not self._confirm_edits():
            self._loading = True
            self.show_archived.setChecked(not self.show_archived.isChecked())
            self._loading = False
            return
        try:
            campaigns = self.repository.list_campaigns(include_archived=self.show_archived.isChecked())
        except (OSError, ValueError, sqlite3.Error) as exc:
            self._read_error(exc)
            return
        self._loading = True
        self.campaigns.clear()
        for campaign in campaigns:
            item = QListWidgetItem(campaign.name + (" (archived)" if campaign.archived else ""))
            item.setData(Qt.ItemDataRole.UserRole, campaign.id)
            item.setToolTip(item.text())
            self.campaigns.addItem(item)
        wanted = preferred_id or current
        if not self._select_id(self.campaigns, wanted) and self.campaigns.count():
            self.campaigns.setCurrentRow(0)
        self._loading = False
        try:
            self._load_campaign(self._id(self.campaigns.currentItem()))
        except (OSError, ValueError, sqlite3.Error) as exc:
            self._read_error(exc)

    def _campaign_selected(self, item, previous):
        if self._loading:
            return
        if not self._confirm_edits():
            self._restore_selection(self.campaigns, self._id(previous))
            return
        try:
            self._load_campaign(self._id(item))
        except (OSError, ValueError, sqlite3.Error) as exc:
            self._read_error(exc)

    def _load_campaign(self, campaign_id):
        self._loading = True
        try:
            self._campaign = self.repository.get_campaign(campaign_id) if campaign_id else None
            campaign = self._campaign
            self.campaign_name.setText(campaign.name if campaign else "")
            self.campaign_description.setPlainText(campaign.description if campaign else "")
            self.campaign_notes.setPlainText(campaign.notes if campaign else "")
            self.campaign_archived.setChecked(bool(campaign and campaign.archived))
            self.party.clear()
            selected_ids = {record.id for record in self.repository.party(campaign_id)} if campaign else set()
            for record in self.library.list(include_archived=True) if campaign else ():
                item = QListWidgetItem(f"{record.name} | {record.kind.upper()}" + (" (archived)" if record.archived else ""))
                item.setData(Qt.ItemDataRole.UserRole, record.id)
                item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
                item.setCheckState(Qt.CheckState.Checked if record.id in selected_ids else Qt.CheckState.Unchecked)
                self.party.addItem(item)
            self.sessions.clear()
            for session in self.repository.list_sessions(campaign_id) if campaign else ():
                self._add_session_item(session)
            if self.sessions.count():
                self.sessions.setCurrentRow(0)
            session_id = self._id(self.sessions.currentItem())
            self._campaign_dirty = self._session_dirty = False
        finally:
            self._loading = False
        self._load_session(session_id)

    def _add_session_item(self, session):
        text = session.title + (f" · {session.session_date}" if session.session_date else "")
        item = QListWidgetItem(text)
        item.setData(Qt.ItemDataRole.UserRole, session.id)
        item.setToolTip(text)
        self.sessions.addItem(item)

    def _session_selected(self, item, previous):
        if self._loading:
            return
        if not self._confirm_edits():
            self._restore_selection(self.sessions, self._id(previous))
            return
        try:
            self._load_session(self._id(item))
        except (OSError, ValueError, sqlite3.Error) as exc:
            self._read_error(exc)

    def _load_session(self, session_id):
        self._loading = True
        try:
            self._session = self.repository.get_session(session_id) if session_id else None
            session = self._session
            self.session_title.setText(session.title if session else "")
            self.session_date.setText(session.session_date if session else "")
            index = self.session_status.findData(session.status if session else "planned")
            self.session_status.setCurrentIndex(max(index, 0))
            self.session_notes.setPlainText(session.notes if session else "")
            self.session_recap.setPlainText(session.recap if session else "")
            self.encounters.clear()
            for encounter in self.repository.list_encounters(session_id) if session else ():
                item = QListWidgetItem(encounter.title)
                item.setData(Qt.ItemDataRole.UserRole, encounter.id)
                self.encounters.addItem(item)
            if self.encounters.count():
                self.encounters.setCurrentRow(0)
            self._session_dirty = False
        finally:
            self._loading = False
        self._sync_actions()

    def _sync_actions(self, *args):
        if self._loading:
            return
        campaign = self._campaign
        session = self._session
        self.campaign_page.setEnabled(campaign is not None)
        self.party_page.setEnabled(campaign is not None)
        self.session_page.setEnabled(session is not None)
        self.new_session_button.setEnabled(campaign is not None)
        self.new_encounter_button.setEnabled(session is not None)
        self.rename_encounter_button.setEnabled(self.encounters.currentItem() is not None)
        self.save_button.setEnabled(self._campaign_dirty or self._session_dirty)
        active = campaign is not None and not campaign.archived
        self.open_button.setEnabled(active and session is not None)
        self.plan_button.setEnabled(session is not None)
        self.campaign_plan_button.setEnabled(campaign is not None)
        self.recap_button.setEnabled(session is not None)
        self.import_button.setEnabled(active)
        if self._campaign_dirty or self._session_dirty:
            self.status.setText("Unsaved journal changes. Save before opening another workspace.")
        elif campaign is None:
            self.status.setText("Create a campaign to begin a journal and party roster.")
        elif session is None:
            self.status.setText("Create a session, then add named encounters when needed.")
        else:
            self.status.setText(f"{campaign.name} / {session.title} · {session.status.replace('_', ' ')}")

    def save_changes(self):
        campaign = session = None
        ids = None
        try:
            if self._campaign is not None and self._campaign_dirty:
                campaign = replace(self._campaign, name=self.campaign_name.text().strip(),
                                   description=self.campaign_description.toPlainText(),
                                   notes=self.campaign_notes.toPlainText(),
                                   archived=self.campaign_archived.isChecked())
                ids = [self._id(self.party.item(row)) for row in range(self.party.count())
                       if self.party.item(row).checkState() == Qt.CheckState.Checked]
            if self._session is not None and self._session_dirty:
                session = replace(self._session, title=self.session_title.text().strip(),
                                  session_date=self.session_date.text().strip(),
                                  status=self.session_status.currentData(),
                                  notes=self.session_notes.toPlainText(), recap=self.session_recap.toPlainText())
            if campaign is not None or session is not None:
                saved_campaign, saved_session = self.repository.save_journal(
                    campaign=campaign, record_ids=ids, session=session)
            else:
                saved_campaign = saved_session = None
        except (OSError, ValueError, sqlite3.Error) as exc:
            QMessageBox.warning(self, "Journal not saved", str(exc))
            return False
        # Publish refreshed metadata and clear dirty flags only after every
        # changed journal field and party member has committed together.
        if saved_campaign is not None:
            self._campaign = saved_campaign
            item = self._item_by_id(self.campaigns, saved_campaign.id)
            if item is not None:
                item.setText(saved_campaign.name + (" (archived)" if saved_campaign.archived else ""))
            self._campaign_dirty = False
        if saved_session is not None:
            self._session = saved_session
            item = self._item_by_id(self.sessions, saved_session.id)
            if item is not None:
                item.setText(saved_session.title + (f" · {saved_session.session_date}" if saved_session.session_date else ""))
            self._session_dirty = False
        self._sync_actions()
        self.status.setText("Campaign and session journal saved locally.")
        return True

    def new_campaign(self):
        if not self._confirm_edits():
            return
        name, ok = QInputDialog.getText(self, "New Campaign", "Campaign name")
        if not ok:
            return
        try:
            campaign = self.repository.create_campaign(name)
            self.refresh_campaigns(preferred_id=campaign.id)
        except (OSError, ValueError, sqlite3.Error) as exc:
            QMessageBox.warning(self, "Campaign not created", str(exc))

    def new_session(self):
        if self._campaign is None or not self._confirm_edits():
            return
        title, ok = QInputDialog.getText(self, "New Session", "Session title")
        if not ok:
            return
        try:
            session = self.repository.create_session(self._campaign.id, title)
            self._loading = True
            self._add_session_item(session)
            self._select_id(self.sessions, session.id)
            self._loading = False
            self._load_session(session.id)
            self.tabs.setCurrentWidget(self.session_page)
        except (OSError, ValueError, sqlite3.Error) as exc:
            self._loading = False
            QMessageBox.warning(self, "Session not created", str(exc))

    def new_encounter(self):
        if self._session is None or not self._confirm_edits():
            return
        title, ok = QInputDialog.getText(self, "New Encounter", "Encounter title")
        if not ok:
            return
        try:
            encounter = self.repository.create_encounter(self._session.id, title)
            item = QListWidgetItem(encounter.title)
            item.setData(Qt.ItemDataRole.UserRole, encounter.id)
            self.encounters.addItem(item)
            self.encounters.setCurrentItem(item)
        except (OSError, ValueError, sqlite3.Error) as exc:
            QMessageBox.warning(self, "Encounter not created", str(exc))

    def rename_encounter(self):
        encounter_id = self._id(self.encounters.currentItem())
        if not encounter_id or not self._confirm_edits():
            return
        title, ok = QInputDialog.getText(self, "Rename Encounter", "Encounter title",
                                        text=self.encounters.currentItem().text())
        if not ok:
            return
        try:
            encounter = self.repository.rename_encounter(encounter_id, title)
            self.encounters.currentItem().setText(encounter.title)
        except (OSError, ValueError, sqlite3.Error) as exc:
            QMessageBox.warning(self, "Encounter not renamed", str(exc))

    def _workspace(self):
        return ActiveWorkspace(self._campaign.id if self._campaign else "",
                               self._session.id if self._session else "",
                               self._id(self.encounters.currentItem()))

    def open_selected(self):
        if self._campaign is None or self._session is None or not self._confirm_edits():
            return
        if self._campaign.archived:
            self.status.setText("Unarchive and save the campaign before opening it.")
            return
        self.result_action = "open"
        self.result_workspace = self._workspace()
        self.accept()

    def use_standalone(self):
        if self._confirm_edits():
            self.result_action = "standalone"
            self.result_workspace = ActiveWorkspace()
            self.accept()

    def import_legacy(self):
        if self._campaign is None or not self._confirm_edits():
            return
        if self._campaign.archived:
            self.status.setText("Unarchive and save the campaign before importing a session.")
            return
        self.result_action = "legacy_import"
        self.result_workspace = ActiveWorkspace(self._campaign.id)
        self.accept()

    def request_scribe(self, task):
        if self._campaign is None or task not in ("campaign_plan", "session_plan", "recap"):
            return
        if task != "campaign_plan" and self._session is None:
            return
        if not self._confirm_edits():
            return
        self.result_action = "scribe"
        self.result_workspace = self._workspace()
        self.result_session_id = self._session.id if self._session is not None else ""
        self.result_task = task
        self.accept()

    def reject(self):
        if self._confirm_edits():
            super().reject()

    def closeEvent(self, event):
        if self._confirm_edits():
            super().closeEvent(event)
        else:
            event.ignore()
