"""Standalone selected-field review desk; inference and writes stay explicit."""
from __future__ import annotations

import sqlite3

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QHBoxLayout, QLabel, QListWidget,
    QListWidgetItem, QMessageBox, QPlainTextEdit, QPushButton, QScrollArea,
    QSplitter, QVBoxLayout, QWidget,
)

from .reviewed_drafts import ReviewedDraftsRepository, build_draft_context


FIELD_LABELS = {
    "notes": "Session notes - planning proposal",
    "recap": "Session recap - cited recorded outcomes",
    "dm_notes": "Private DM notes - planning proposal",
    "summary": "Public summary - explicit public review",
    "player_text": "Handout player text - explicit public review",
}


class ReviewedDraftsDialog(QDialog):
    """Choose a saved target, paste/write a draft, review, then apply one field.

    The domain API also accepts several field proposals with a checked subset.
    This desk deliberately presents one complete field at a time.
    """

    def __init__(self, database_path, campaign_id, parent=None):
        super().__init__(parent)
        self.repository = ReviewedDraftsRepository(database_path, campaign_id)
        self._baseline = None
        self._proposal = None
        self._sources = ()
        self._writer = None
        self._writer_binding = None
        self._target_index = -1
        self._active_field = None
        self._loading = False
        self._dirty = False
        self.setWindowTitle("Reviewed Scribe Drafts | D&D Game Manager 4")
        self.setAttribute(Qt.WidgetAttribute.WA_QuitOnClose, False)
        self.resize(1050, 820)
        outer = QVBoxLayout(self)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        body = QWidget()
        root = QVBoxLayout(body)
        scroll.setWidget(body)
        outer.addWidget(scroll)
        title = QLabel("REVIEWED SCRIBE DRAFTS")
        title.setObjectName("pageTitle")
        root.addWidget(title)
        hint = QLabel("Choose one saved field. Paste a draft or open the local Scribe, then inspect the complete before/after text. "
                      "Apply saves only the checked field. No generation starts automatically.")
        hint.setWordWrap(True)
        hint.setObjectName("muted")
        root.addWidget(hint)
        target_row = QHBoxLayout()
        self.targets = QComboBox()
        self.targets.setAccessibleName("Saved session or world entry for draft")
        self.targets.setMinimumContentsLength(14)
        target_row.addWidget(self.targets, 1)
        self.reload_button = QPushButton("Reload Saved Target")
        self.reload_button.clicked.connect(self.reload_target)
        target_row.addWidget(self.reload_button)
        root.addLayout(target_row)
        self.field = QComboBox()
        self.field.setAccessibleName("Text field to review")
        root.addWidget(self.field)
        self.current = QPlainTextEdit()
        self.current.setReadOnly(True)
        self.current.setAccessibleName("Complete saved field before draft")
        self.current.setMaximumHeight(115)
        root.addWidget(self.current)
        self.draft = QPlainTextEdit()
        self.draft.setPlaceholderText("Paste or write the complete replacement text here.")
        self.draft.setAccessibleName("Editable field draft")
        self.draft.setMinimumHeight(110)
        root.addWidget(self.draft)
        writer_row = QHBoxLayout()
        self.open_scribe_button = QPushButton("Open Local Scribe with Selected Text")
        self.open_scribe_button.clicked.connect(self.open_scribe)
        writer_row.addWidget(self.open_scribe_button)
        self.retrieve_button = QPushButton("Retrieve Scribe Draft")
        self.retrieve_button.clicked.connect(self.retrieve_scribe)
        self.retrieve_button.setEnabled(False)
        writer_row.addWidget(self.retrieve_button)
        root.addLayout(writer_row)

        self.evidence_box = QWidget()
        evidence_layout = QVBoxLayout(self.evidence_box)
        evidence_layout.setContentsMargins(0, 0, 0, 0)
        explanation = QLabel("Recap evidence: select saved notes or encounter log excerpts that actually record outcomes. "
                             "Plans, a scene description, and membership are not event evidence. Select an excerpt to inspect its full text.")
        explanation.setWordWrap(True)
        evidence_layout.addWidget(explanation)
        evidence_split = QSplitter(Qt.Orientation.Horizontal)
        self.evidence = QListWidget()
        self.evidence.setAccessibleName("Saved recorded evidence candidates")
        self.evidence.setMinimumHeight(105)
        evidence_split.addWidget(self.evidence)
        self.evidence_preview = QPlainTextEdit()
        self.evidence_preview.setReadOnly(True)
        self.evidence_preview.setAccessibleName("Complete selected evidence excerpt")
        evidence_split.addWidget(self.evidence_preview)
        evidence_layout.addWidget(evidence_split)
        cite = QPushButton("Insert Checked Evidence Citations")
        cite.clicked.connect(self.insert_citations)
        evidence_layout.addWidget(cite)
        self.recorded_confirm = QCheckBox("Selected evidence records events or outcomes, rather than plans")
        evidence_layout.addWidget(self.recorded_confirm)
        root.addWidget(self.evidence_box)

        self.prepare_button = QPushButton("Prepare Before / After Review")
        self.prepare_button.clicked.connect(self.prepare_review)
        root.addWidget(self.prepare_button)
        self.review_field = QCheckBox("Apply this reviewed field")
        self.review_field.setChecked(True)
        root.addWidget(self.review_field)
        review_split = QSplitter(Qt.Orientation.Horizontal)
        before_box = QWidget()
        before_layout = QVBoxLayout(before_box)
        before_layout.addWidget(QLabel("BEFORE - saved text"))
        self.before = QPlainTextEdit()
        self.before.setReadOnly(True)
        self.before.setAccessibleName("Reviewed field before")
        before_layout.addWidget(self.before)
        after_box = QWidget()
        after_layout = QVBoxLayout(after_box)
        after_layout.addWidget(QLabel("AFTER - exact text to save"))
        self.after = QPlainTextEdit()
        self.after.setReadOnly(True)
        self.after.setAccessibleName("Reviewed field after")
        after_layout.addWidget(self.after)
        review_split.addWidget(before_box)
        review_split.addWidget(after_box)
        review_split.setMinimumHeight(165)
        root.addWidget(review_split)
        self.public_review = QCheckBox("I reviewed the complete public text: it contains no DM secrets")
        root.addWidget(self.public_review)
        self.apply_button = QPushButton("Apply Reviewed Field")
        self.apply_button.setObjectName("primaryButton")
        self.apply_button.setEnabled(False)
        self.apply_button.clicked.connect(self.apply_review)
        root.addWidget(self.apply_button)
        self.message = QLabel("")
        self.message.setWordWrap(True)
        root.addWidget(self.message)
        close = QPushButton("Close")
        close.clicked.connect(self.reject)
        outer.addWidget(close)

        self.targets.currentIndexChanged.connect(self._target_changed)
        self.field.currentIndexChanged.connect(self._field_changed)
        self.draft.textChanged.connect(self._edited)
        self.evidence.itemChanged.connect(self._edited)
        self.evidence.currentItemChanged.connect(self._show_evidence)
        self.recorded_confirm.toggled.connect(self._edited)
        self.public_review.toggled.connect(self._sync_apply)
        self.review_field.toggled.connect(self._sync_apply)
        self._loading = True
        for kind, identity, label in self.repository.list_targets():
            self.targets.addItem(label, (kind, identity))
        self._loading = False
        if self.targets.count():
            self._target_changed(0)
        else:
            self.message.setText("Create a saved session or world entry in this campaign before reviewing a draft.")
            for control in (self.field, self.draft, self.prepare_button, self.open_scribe_button, self.reload_button):
                control.setEnabled(False)
        self.evidence_box.setVisible(self.field.currentData() == "recap")
        self.public_review.setVisible(self.field.currentData() in ("summary", "player_text"))

    def _report(self, exc):
        self.message.setText(str(exc))

    def _edited(self, *args):
        if self._loading:
            return
        self._dirty = True
        self._proposal = None
        self.public_review.setChecked(False)
        self._sync_apply()

    def _sync_apply(self, *args):
        public = self.field.currentData() in ("summary", "player_text")
        self.apply_button.setEnabled(self._proposal is not None and self.review_field.isChecked()
                                     and (not public or self.public_review.isChecked()))

    def _discard_ok(self):
        if not self._dirty:
            return True
        return QMessageBox.question(self, "Unsaved Reviewed Draft", "Discard the unsaved draft before continuing?",
                                    QMessageBox.StandardButton.Discard | QMessageBox.StandardButton.Cancel,
                                    QMessageBox.StandardButton.Cancel) == QMessageBox.StandardButton.Discard

    def _target_changed(self, index):
        if self._loading or index < 0:
            return
        if not self._discard_ok():
            self.targets.blockSignals(True)
            self.targets.setCurrentIndex(self._target_index)
            self.targets.blockSignals(False)
            return
        try:
            kind, identity = self.targets.itemData(index)
            baseline = self.repository.snapshot(kind, identity)
            sources = self.repository.load_evidence(identity) if kind == "session" else ()
        except (OSError, ValueError, sqlite3.Error) as exc:
            self._report(exc)
            self.targets.blockSignals(True)
            self.targets.setCurrentIndex(self._target_index)
            self.targets.blockSignals(False)
            return
        self._target_index = index
        self._install_target(baseline, sources, clear_draft=True)

    def _install_target(self, baseline, sources, *, clear_draft):
        self._loading = True
        preferred = self.field.currentData()
        self._active_field = None
        self._baseline = baseline
        self._sources = sources
        self.field.clear()
        for field in baseline.allowed_fields:
            self.field.addItem(FIELD_LABELS[field], field)
        if preferred in baseline.allowed_fields:
            self.field.setCurrentIndex(self.field.findData(preferred))
        self.evidence.clear()
        self.evidence_preview.clear()
        for index, source in enumerate(sources):
            item = QListWidgetItem(source.citation + " " + source.title)
            item.setData(Qt.ItemDataRole.UserRole, index)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Unchecked)
            self.evidence.addItem(item)
        self.recorded_confirm.setChecked(False)
        self.public_review.setChecked(False)
        if clear_draft:
            self.draft.clear()
        self._loading = False
        self._proposal = None
        self._dirty = bool(self.draft.toPlainText())
        self.before.clear()
        self.after.clear()
        self._field_changed()

    def _field_changed(self, *args):
        if self._loading or self._baseline is None:
            return
        field = self.field.currentData()
        if self._active_field is not None and field != self._active_field:
            if not self._discard_ok():
                self.field.blockSignals(True)
                self.field.setCurrentIndex(self.field.findData(self._active_field))
                self.field.blockSignals(False)
                return
            self._loading = True
            self.draft.clear()
            self.recorded_confirm.setChecked(False)
            self._loading = False
            self._dirty = False
        self._active_field = field
        self.current.setPlainText(self._baseline.field_text(field))
        self.evidence_box.setVisible(field == "recap")
        self.public_review.setVisible(field in ("summary", "player_text"))
        self._proposal = None
        self.public_review.setChecked(False)
        self.before.clear()
        self.after.clear()
        self._sync_apply()

    def reload_target(self):
        if self._baseline is None:
            return
        try:
            baseline = self.repository.snapshot(self._baseline.kind, self._baseline.target_id)
            sources = self.repository.load_evidence(baseline.target_id) if baseline.kind == "session" else ()
        except (OSError, ValueError, sqlite3.Error) as exc:
            self._report(exc)
            return
        self._install_target(baseline, sources, clear_draft=False)
        self.message.setText("Saved target reloaded. The editable draft was retained; prepare its review again.")

    def selected_evidence(self):
        return tuple(self._sources[self.evidence.item(index).data(Qt.ItemDataRole.UserRole)]
                     for index in range(self.evidence.count())
                     if self.evidence.item(index).checkState() == Qt.CheckState.Checked)

    def _show_evidence(self, current, previous=None):
        self.evidence_preview.setPlainText("" if current is None else
                                          self._sources[current.data(Qt.ItemDataRole.UserRole)].text)

    def insert_citations(self):
        self.draft.insertPlainText(" ".join(item.citation for item in self.selected_evidence()))

    def prepare_review(self):
        if self._baseline is None:
            return False
        field = self.field.currentData()
        try:
            proposal = self.repository.prepare(
                self._baseline, {field: self.draft.toPlainText()},
                evidence=self.selected_evidence() if field == "recap" else (),
                recorded_evidence_confirmed=self.recorded_confirm.isChecked())
        except (OSError, ValueError, sqlite3.Error) as exc:
            self._proposal = None
            self._sync_apply()
            self._report(exc)
            return False
        self._proposal = proposal
        self.before.setPlainText(proposal.changes[0].before)
        self.after.setPlainText(proposal.changes[0].after)
        self.review_field.setText("Apply reviewed field: " + FIELD_LABELS[field])
        self.review_field.setChecked(True)
        self.public_review.setChecked(False)
        self.message.setText("Inspect the complete replacement above. Citations identify saved excerpts; the DM still checks that every claim is supported.")
        self._sync_apply()
        return True

    def apply_review(self):
        if self._proposal is None or not self.review_field.isChecked():
            self.message.setText("Prepare a review and check the field before applying it.")
            return False
        try:
            saved = self.repository.apply(self._proposal,
                                          selected_fields=(self.field.currentData(),),
                                          public_reviewed=self.public_review.isChecked())
        except (OSError, ValueError, sqlite3.Error) as exc:
            self._report(exc)
            return False
        self._baseline = saved
        self.current.setPlainText(saved.field_text(self.field.currentData()))
        self._proposal = None
        self._dirty = False
        self._sync_apply()
        self.message.setText("Reviewed field saved. Other fields, characters, rewards, dice and the active encounter were not changed.")
        return True

    def open_scribe(self):
        if self._baseline is None:
            return False
        field = self.field.currentData()
        try:
            if self._writer is not None and self._writer.worker is not None:
                raise ValueError("Wait for the current local Scribe request before opening another draft.")
            if field == "recap" and not self.recorded_confirm.isChecked():
                raise ValueError("Inspect and confirm recorded source evidence before requesting a recap draft.")
            context = build_draft_context(self._baseline, field, self.draft.toPlainText(),
                                          self.selected_evidence() if field == "recap" else ())
            from .ai_ui import AIWritingDialog
            if self._writer is not None:
                self._writer.hide()
                self._writer.deleteLater()
            self._writer = AIWritingDialog("dm", context, self)
            task = "recap" if field == "recap" else "session_plan"
            self._writer.dm_task.setCurrentIndex(self._writer.dm_task.findData(task))
            self._writer_binding = (self._baseline.digest, field)
            self._writer.show()
            self.retrieve_button.setEnabled(True)
        except (OSError, ValueError, sqlite3.Error) as exc:
            self._report(exc)
            return False
        self.message.setText("Scribe opened with selected text. Generate there explicitly, then return and retrieve its draft.")
        return True

    def load_scribe_draft(self, text, task="session_plan", session_id=None):
        """Integrator handoff: populate an editable draft, never prepare/apply.

        A named session must be in this dialog's campaign. A recap without a
        session ID selects the current session, or the first saved session.
        Other tasks use the current target's private planning field.
        """
        try:
            if not isinstance(text, str) or not text.strip() or len(text) > 100000 or "\x00" in text:
                raise ValueError("Supply a nonempty Scribe draft under 100,000 characters.")
            text.encode("utf-8")
            if task not in ("dm", "campaign_plan", "session_plan", "dm_advice", "recap"):
                raise ValueError("Choose a supported Scribe task for this draft.")
            index = self.targets.currentIndex()
            if session_id is not None:
                index = next((row for row in range(self.targets.count())
                              if self.targets.itemData(row) == ("session", session_id)), -1)
            elif task == "recap" and (index < 0 or self.targets.itemData(index)[0] != "session"):
                index = next((row for row in range(self.targets.count())
                              if self.targets.itemData(row)[0] == "session"), -1)
            if index < 0:
                raise ValueError("Select a saved session in this campaign for the Scribe draft.")
            kind, identity = self.targets.itemData(index)
            baseline = self.repository.snapshot(kind, identity)
            sources = self.repository.load_evidence(identity) if kind == "session" else ()
        except (OSError, ValueError, sqlite3.Error, UnicodeError) as exc:
            self._report(exc)
            return False
        if not self._discard_ok():
            return False
        self.targets.blockSignals(True)
        self.targets.setCurrentIndex(index)
        self.targets.blockSignals(False)
        self._target_index = index
        self._install_target(baseline, sources, clear_draft=True)
        field = ("recap" if task == "recap" else "notes") if kind == "session" else "dm_notes"
        self.field.setCurrentIndex(self.field.findData(field))
        self.draft.setPlainText(text)
        self.message.setText("Scribe draft loaded into the editable proposal. Review its field and evidence before preparing changes.")
        return True

    def retrieve_scribe(self):
        if self._writer is None or self._baseline is None:
            return False
        if self._writer_binding != (self._baseline.digest, self.field.currentData()):
            self.message.setText("This Scribe draft belongs to a different saved field or baseline. Open Scribe again for this target.")
            return False
        text = self._writer.result.toPlainText()
        if not text.strip():
            self.message.setText("The Scribe has no draft yet.")
            return False
        self.draft.setPlainText(text)
        self.message.setText("Scribe draft retrieved for review. Nothing was saved.")
        return True

    def reject(self):
        if self._discard_ok():
            if self._writer is not None:
                self._writer.hide()
            super().reject()

    def closeEvent(self, event):
        if not self._discard_ok():
            event.ignore()
            return
        if self._writer is not None:
            self._writer.hide()
        self._dirty = False
        super().closeEvent(event)
