"""Explicit review of campaign memories before loading a bounded Scribe context."""
from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QAbstractItemView, QComboBox, QDialog, QDialogButtonBox, QHBoxLayout, QLabel,
    QLineEdit, QPlainTextEdit, QPushButton, QTableWidget, QTableWidgetItem,
    QTabWidget, QVBoxLayout, QWidget,
)


_HIT_FIELDS = ("citation", "kind", "source_id", "field", "title", "text", "digest",
               "source_url", "source_version", "classification", "public")


def _label(text):
    widget = QLabel(text)
    widget.setTextFormat(Qt.TextFormat.PlainText)
    widget.setWordWrap(True)
    return widget


class CampaignRecallDialog(QDialog):
    """Search, inspect and review sources; never generate or persist anything."""

    MAX_HITS = 20
    MAX_CONTEXT_CHARS = 6000

    def __init__(self, search_provider, context_builder, parent=None, query="", audience="dm"):
        super().__init__(parent)
        if audience not in ("dm", "player"):
            raise ValueError("Choose DM or player-facing recall")
        self._search_provider = search_provider
        self._context_builder = context_builder
        self._hits = []
        self._search_valid = False
        self._reviewed = None
        self._changing = False
        self.result_context = None
        self.result_audience = None
        self.setWindowTitle("Campaign Recall | D&D Game Manager 4")
        self.resize(1040, 740)
        self.setMinimumSize(830, 540)
        self.setModal(False)
        root = QVBoxLayout(self)
        title = _label("REVIEW CAMPAIGN RECALL")
        title.setObjectName("pageTitle")
        root.addWidget(title)
        root.addWidget(_label("Search saved campaign sources, inspect their provenance, then select and preview the context to load into Scribe. "
                              "Player-facing recall uses only sources permitted for players. Loading sources does not generate narration or change campaign state."))
        search = QHBoxLayout()
        self.query = QLineEdit(str(query))
        self.query.setAccessibleName("Campaign recall search query")
        self.query.setPlaceholderText("Find an NPC, quest, recorded event, or rule…")
        search.addWidget(self.query, 1)
        self.audience = QComboBox()
        self.audience.addItem("DM", "dm")
        self.audience.addItem("Player-facing", "player")
        self.audience.setCurrentIndex(self.audience.findData(audience))
        self.audience.setAccessibleName("Recall audience")
        search.addWidget(self.audience)
        self.search_button = QPushButton("Search")
        self.search_button.clicked.connect(self.search)
        search.addWidget(self.search_button)
        root.addLayout(search)
        self.tabs = QTabWidget()
        root.addWidget(self.tabs, 1)
        sources = QWidget()
        source_layout = QVBoxLayout(sources)
        self.results = QTableWidget(0, 5)
        self.results.setHorizontalHeaderLabels(["Use", "Kind", "Title", "Classification", "Citation"])
        self.results.setAccessibleName("Campaign recall search results and source selection")
        self.results.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.results.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.results.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.results.setColumnWidth(0, 45)
        self.results.setColumnWidth(1, 100)
        self.results.setColumnWidth(2, 230)
        self.results.setColumnWidth(3, 120)
        self.results.horizontalHeader().setStretchLastSection(True)
        source_layout.addWidget(self.results, 1)
        self.source_preview = QPlainTextEdit()
        self.source_preview.setReadOnly(True)
        self.source_preview.setAccessibleName("Full selected source and provenance")
        source_layout.addWidget(self.source_preview, 1)
        self.tabs.addTab(sources, "Sources")
        self.context_preview = QPlainTextEdit()
        self.context_preview.setReadOnly(True)
        self.context_preview.setAccessibleName("Full reviewed Scribe source context")
        self.tabs.addTab(self.context_preview, "Context preview")
        self.status = _label("Search explicitly to retrieve sources. No sources are loaded yet.")
        self.status.setAccessibleName("Campaign recall review status")
        root.addWidget(self.status)
        controls = QHBoxLayout()
        self.preview_button = QPushButton("Preview selected context")
        self.preview_button.setEnabled(False)
        self.preview_button.clicked.connect(self.preview_context)
        controls.addWidget(self.preview_button)
        self.load_button = QPushButton("Load reviewed sources into Scribe")
        self.load_button.setEnabled(False)
        self.load_button.clicked.connect(self.accept)
        controls.addWidget(self.load_button)
        cancel = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel)
        cancel.rejected.connect(self.reject)
        controls.addWidget(cancel)
        root.addLayout(controls)
        self.query.textChanged.connect(self._clear_search)
        self.query.returnPressed.connect(self.search)
        self.audience.currentIndexChanged.connect(self._clear_search)
        self.results.itemChanged.connect(self._selection_changed)
        self.results.itemSelectionChanged.connect(self._show_source)

    def _invalidate_review(self):
        self._reviewed = None
        self.load_button.setEnabled(False)

    def _clear_search(self, *_args):
        self._invalidate_review()
        self._search_valid = False
        self._hits = []
        self._changing = True
        self.results.setRowCount(0)
        self._changing = False
        self.source_preview.clear()
        self.context_preview.clear()
        self.preview_button.setEnabled(False)
        self.status.setText("Query or audience changed. Search again before selecting sources.")

    def _selected_hits(self):
        return [hit for index, hit in enumerate(self._hits)
                if self.results.item(index, 0).checkState() == Qt.CheckState.Checked]

    @staticmethod
    def _hit_signature(hit):
        return tuple(getattr(hit, name) for name in _HIT_FIELDS)

    def _signature(self, context):
        return (self.query.text(), self.audience.currentData(),
                tuple(self._hit_signature(hit) for hit in self._selected_hits()), context)

    def search(self):
        self._invalidate_review()
        self._search_valid = False
        self.preview_button.setEnabled(False)
        try:
            hits = self._search_provider(self.query.text().strip(), audience=self.audience.currentData(), limit=self.MAX_HITS)
            if not isinstance(hits, list) or len(hits) > self.MAX_HITS:
                raise ValueError("Search returned too many sources or an invalid result list")
            for hit in hits:
                signature = self._hit_signature(hit)
                if any(not isinstance(value, str) for value in signature[:-1]) or type(hit.public) is not bool:
                    raise ValueError("Search returned an invalid source record")
        except Exception as exc:
            self.status.setText(f"Search failed: {exc}. Existing source draft retained; search successfully before loading.")
            return False
        self._hits = hits
        self._changing = True
        self.results.setRowCount(0)
        self.results.setRowCount(len(hits))
        for row, hit in enumerate(hits):
            check = QTableWidgetItem("")
            check.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsUserCheckable | Qt.ItemFlag.ItemIsSelectable)
            check.setCheckState(Qt.CheckState.Unchecked)
            self.results.setItem(row, 0, check)
            for column, value in enumerate((hit.kind, hit.title, hit.classification, hit.citation), 1):
                self.results.setItem(row, column, QTableWidgetItem(value))
        self._changing = False
        self.source_preview.clear()
        self.context_preview.clear()
        self._search_valid = True
        self.status.setText(f"{len(hits)} sources found. Check sources to include, then preview the context." if hits else "No matching permitted sources found. Try another query.")
        self.tabs.setCurrentIndex(0)
        if hits:
            self.results.selectRow(0)
        return True

    def _selection_changed(self, *_args):
        if self._changing:
            return
        self._invalidate_review()
        self.context_preview.clear()
        selected = len(self._selected_hits())
        self.preview_button.setEnabled(self._search_valid and 0 < selected <= self.MAX_HITS)
        self.status.setText(f"{selected} sources selected. Preview the full context before loading.")

    def _show_source(self):
        row = self.results.currentRow()
        if 0 <= row < len(self._hits):
            hit = self._hits[row]
            self.source_preview.setPlainText("\n".join([
                f"Citation: {hit.citation}", f"Kind: {hit.kind}", f"Title: {hit.title}",
                f"Classification: {hit.classification}", f"Public: {hit.public}",
                f"Source ID: {hit.source_id}", f"Field: {hit.field}",
                f"Digest: {hit.digest}", f"Source URL: {hit.source_url}",
                f"Source version: {hit.source_version}", "", hit.text,
            ]))
        else:
            self.source_preview.clear()

    def preview_context(self):
        self._invalidate_review()
        if not self._search_valid:
            return False
        try:
            selected = self._selected_hits()
            if not 1 <= len(selected) <= self.MAX_HITS:
                raise ValueError("Select between 1 and 20 sources")
            context = self._context_builder(selected, audience=self.audience.currentData(), max_chars=self.MAX_CONTEXT_CHARS)
            if not isinstance(context, str) or not context.strip():
                raise ValueError("Context builder returned no usable source context")
            if len(context) > self.MAX_CONTEXT_CHARS:
                raise ValueError("Selected context exceeds 6000 characters; select fewer sources. Nothing was truncated")
        except Exception as exc:
            self.status.setText(f"Cannot preview context: {exc}. Source draft retained; nothing loaded.")
            return False
        self.context_preview.setPlainText(context)
        self._reviewed = self._signature(context)
        self.load_button.setEnabled(True)
        self.status.setText(f"Review the full {len(context)}-character {self.audience.currentText()} context before loading into Scribe.")
        self.tabs.setCurrentWidget(self.context_preview)
        return True

    def accept(self):
        if not self._search_valid or self._reviewed is None or self._reviewed != self._signature(self.context_preview.toPlainText()):
            self._invalidate_review()
            self.status.setText("The reviewed context changed. Preview selected sources again before loading.")
            return
        try:
            fresh = self._search_provider(self.query.text().strip(), audience=self.audience.currentData(), limit=self.MAX_HITS)
            if not isinstance(fresh, list) or len(fresh) > self.MAX_HITS:
                raise ValueError("Search returned an invalid source list")
            fresh_signatures = [self._hit_signature(hit) for hit in fresh]
            if len({hit.citation for hit in fresh}) != len(fresh):
                raise ValueError("Search returned ambiguous source citations")
            if any(self._hit_signature(hit) not in fresh_signatures for hit in self._selected_hits()):
                raise ValueError("A selected source changed, disappeared, or is no longer in the current search results")
        except Exception as exc:
            self._invalidate_review()
            self._search_valid = False
            self.preview_button.setEnabled(False)
            self.status.setText(f"Sources could not be verified: {exc}. Draft retained. Search and preview again before loading.")
            return
        self.result_context = self.context_preview.toPlainText()
        self.result_audience = self.audience.currentData()
        super().accept()

    def reject(self):
        self.result_context = None
        self.result_audience = None
        super().reject()
