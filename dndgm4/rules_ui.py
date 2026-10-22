"""Search local 3.5 rules, inspect provenance, and explicitly share evidence."""
from __future__ import annotations

from pathlib import Path
import sqlite3

from PyQt6.QtCore import Qt, QObject, QRunnable, QThreadPool, QUrl, pyqtSignal, pyqtSlot
from PyQt6.QtGui import QDesktopServices
from PyQt6.QtWidgets import (
    QComboBox, QDialog, QDialogButtonBox, QFileDialog, QFormLayout,
    QHBoxLayout, QLabel, QLineEdit, QListWidget, QListWidgetItem,
    QMessageBox, QPlainTextEdit, QPushButton, QSplitter, QVBoxLayout, QWidget,
)

from .rules_reference import (MAX_QUERY_CHARS, SRD_SOURCES, RuleHit,
                              RulesRepository, build_rules_context)


class ImportRulesDialog(QDialog):
    """Collect source metadata before adding a local UTF-8 document."""

    def __init__(self, repository: RulesRepository, path: str, parent=None):
        super().__init__(parent)
        self.repository = repository
        self.path = Path(path)
        self.document_id: str | None = None
        self.setWindowTitle("Import a 3.5 Rules Document")
        self.resize(560, 350)
        root = QVBoxLayout(self)
        description = QLabel(
            "Add a D&D 3.5 text or HTML document to the offline reference library. "
            "The original file is kept as it is. This document will be labelled as a local import.")
        description.setWordWrap(True)
        root.addWidget(description)
        form = QFormLayout()
        filename = QLabel(self.path.name)
        filename.setTextFormat(Qt.TextFormat.PlainText)
        form.addRow("File", filename)
        form.addRow("Edition", QLabel("D&D 3.5"))
        self.title = QLineEdit(self.path.stem)
        self.title.setMaxLength(200)
        self.title.setAccessibleName("Rules document title")
        self.source_url = QLineEdit()
        self.source_url.setMaxLength(2000)
        self.source_url.setPlaceholderText("Optional reference URL")
        self.source_url.setAccessibleName("Rules document source URL")
        self.section = QLineEdit()
        self.section.setMaxLength(250)
        self.section.setAccessibleName("Rules document section")
        self.version = QLineEdit("User-supplied 3.5 document")
        self.version.setMaxLength(250)
        self.version.setAccessibleName("Rules document version")
        form.addRow("Title", self.title)
        form.addRow("Source URL", self.source_url)
        form.addRow("Section", self.section)
        form.addRow("Version", self.version)
        root.addLayout(form)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel)
        self.import_button = buttons.addButton("Import Document", QDialogButtonBox.ButtonRole.AcceptRole)
        self.import_button.clicked.connect(self.import_document)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

    def import_document(self):
        try:
            document_id = self.repository.import_file(
                self.path, title=self.title.text(), source_url=self.source_url.text(),
                section=self.section.text(), source_version=self.version.text())
        except (OSError, ValueError, sqlite3.Error) as exc:
            QMessageBox.warning(self, "Import Rules", str(exc))
            return
        self.document_id = document_id
        self.accept()


class _FetchSignals(QObject):
    done = pyqtSignal(str)
    failed = pyqtSignal(str)


class _FetchSource(QRunnable):
    def __init__(self, repository: RulesRepository, key: str):
        super().__init__()
        self.repository = repository
        self.key = key
        self.signals = _FetchSignals()

    @pyqtSlot()
    def run(self):
        try:
            document_id = self.repository.fetch_source(self.key)
        except Exception as exc:
            self.signals.failed.emit(f"Could not download the SRD section: {exc}")
        else:
            self.signals.done.emit(document_id)


class RulesReferenceDialog(QDialog):
    context_requested = pyqtSignal(str)

    def __init__(self, reference_store: RulesRepository, parent=None):
        super().__init__(parent)
        self.reference_store = reference_store
        self.result_context: str | None = None
        self.hits: list[RuleHit] = []
        self.fetch_worker = None
        self.setAttribute(Qt.WidgetAttribute.WA_QuitOnClose, False)
        self.setWindowTitle("Rules Compendium | D&D 3.5")
        self.resize(1020, 720)
        root = QVBoxLayout(self)
        root.setContentsMargins(22, 20, 22, 18)
        heading = QLabel("RULES COMPENDIUM  /  D&D 3.5")
        heading.setObjectName("eyebrow")
        root.addWidget(heading)
        title = QLabel("Consult the Archives")
        title.setObjectName("pageTitle")
        root.addWidget(title)
        explanation = QLabel(
            "Search offline reference summaries and imported source passages. "
            "Select a result to read its evidence and source. The Scribe can use a selected "
            "passage with citations; no model is trained or downloaded here.")
        explanation.setWordWrap(True)
        explanation.setObjectName("muted")
        root.addWidget(explanation)
        search_line = QHBoxLayout()
        self.query = QLineEdit()
        self.query.setMaxLength(MAX_QUERY_CHARS)
        self.query.setAccessibleName("Search D&D 3.5 rules")
        self.query.setPlaceholderText("Search words, for example: cover, skill checks, critical hits")
        self.query.returnPressed.connect(self.search)
        search_line.addWidget(self.query, 1)
        self.search_button = QPushButton("Search")
        self.search_button.clicked.connect(self.search)
        search_line.addWidget(self.search_button)
        root.addLayout(search_line)
        self.results = QListWidget()
        self.results.setAccessibleName("Rules search results")
        self.results.setWordWrap(True)
        self.results.currentRowChanged.connect(self.show_result)
        detail = QWidget()
        detail_root = QVBoxLayout(detail)
        detail_root.setContentsMargins(0, 0, 0, 0)
        self.passage_title = QLabel("Select a rule")
        self.passage_title.setTextFormat(Qt.TextFormat.PlainText)
        self.passage_title.setWordWrap(True)
        self.passage_title.setObjectName("sectionTitle")
        detail_root.addWidget(self.passage_title)
        self.passage_kind = QLabel()
        self.passage_kind.setWordWrap(True)
        self.passage_kind.setTextFormat(Qt.TextFormat.PlainText)
        detail_root.addWidget(self.passage_kind)
        self.passage = QPlainTextEdit()
        self.passage.setReadOnly(True)
        self.passage.setAccessibleName("Selected rules passage")
        detail_root.addWidget(self.passage, 1)
        self.source_info = QPlainTextEdit()
        self.source_info.setReadOnly(True)
        self.source_info.setAccessibleName("Rules source provenance")
        self.source_info.setMaximumHeight(155)
        detail_root.addWidget(self.source_info)
        detail_buttons = QHBoxLayout()
        self.document_button = QPushButton("Read Whole Document")
        self.document_button.clicked.connect(self.show_document)
        detail_buttons.addWidget(self.document_button)
        self.source_button = QPushButton("Open Source")
        self.source_button.clicked.connect(self.open_source)
        detail_buttons.addWidget(self.source_button)
        self.scribe_button = QPushButton("Use in Scribe")
        self.scribe_button.clicked.connect(self.use_in_scribe)
        detail_buttons.addWidget(self.scribe_button)
        detail_root.addLayout(detail_buttons)
        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.addWidget(self.results)
        splitter.addWidget(detail)
        splitter.setSizes([350, 600])
        root.addWidget(splitter, 1)
        online_line = QHBoxLayout()
        self.source_picker = QComboBox()
        self.source_picker.setAccessibleName("3.5 SRD section to download")
        for source in SRD_SOURCES:
            self.source_picker.addItem(source.title, source.key)
        online_line.addWidget(self.source_picker, 1)
        self.fetch_button = QPushButton("Download SRD Section")
        self.fetch_button.setToolTip("Download this listed 3.5 SRD page into your offline library.")
        self.fetch_button.clicked.connect(self.fetch_source)
        online_line.addWidget(self.fetch_button)
        self.import_button = QPushButton("Import Document…")
        self.import_button.clicked.connect(self.import_document)
        online_line.addWidget(self.import_button)
        root.addLayout(online_line)
        self.status = QLabel()
        self.status.setTextFormat(Qt.TextFormat.PlainText)
        self.status.setWordWrap(True)
        root.addWidget(self.status)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.close)
        root.addWidget(buttons)
        self.show_result(-1)
        self._idle_status()

    def _idle_status(self):
        try:
            documents = self.reference_store.list_documents()
            summaries = sum(item.origin == "authored-summary" for item in documents)
            self.status.setText(
                f"Offline library: {len(documents)} documents, including {summaries} authored summaries. "
                "Source pages download only when you click Download SRD Section.")
        except (OSError, ValueError, sqlite3.Error) as exc:
            self.status.setText(f"Could not read the rules library: {exc}")

    def selected_hit(self) -> RuleHit | None:
        row = self.results.currentRow()
        return self.hits[row] if 0 <= row < len(self.hits) else None

    def search(self):
        try:
            hits = self.reference_store.search(self.query.text())
        except (OSError, ValueError, sqlite3.Error) as exc:
            QMessageBox.warning(self, "Search Rules", str(exc))
            return
        self.results.clear()
        self.hits = hits
        for hit in hits:
            label = "Authored summary" if hit.origin == "authored-summary" else "Source passage"
            item = QListWidgetItem(f"{hit.title}\n{label} · D&D {hit.edition}\n{hit.snippet}")
            item.setToolTip(f"{hit.source_title}\n{hit.source_url}")
            self.results.addItem(item)
        if hits:
            self.results.setCurrentRow(0)
        else:
            self.show_result(-1)
        self.status.setText(
            f"{len(hits)} matching passages. All search words must appear in a result."
            if hits else "No matching passages. Try fewer words, import a document, or download a listed SRD section.")

    def show_result(self, row: int):
        hit = self.hits[row] if 0 <= row < len(self.hits) else None
        self.source_button.setEnabled(bool(hit and hit.source_url))
        self.document_button.setEnabled(hit is not None)
        self.scribe_button.setEnabled(hit is not None)
        self.passage_title.setText(hit.title if hit else "Select a rule")
        self.passage.setPlainText(hit.text if hit else "Search the offline compendium to find a rule.")
        if hit:
            self.passage_kind.setText(
                "Authored reference summary — an orientation note; consult the linked rule for full details."
                if hit.origin == "authored-summary" else "Imported source passage — read the whole document for surrounding rules and exceptions.")
            self.source_info.setPlainText(
                f"Source: {hit.source_title}\nEdition: {hit.edition}\n"
                f"Document: {hit.source_document_id}\nSection: {hit.section}\n"
                f"Version: {hit.source_version}\nURL: {hit.source_url or '[Local import; no URL supplied]'}\n"
                f"Imported (UTC): {hit.imported_at}\nCanonical document SHA-256: {hit.digest}\n"
                f"Original file SHA-256: {hit.source_digest or '[Authored summary; no downloaded file]'}\n"
                f"License reference: {hit.license_url or '[No source license metadata supplied]'}\n"
                f"Source notice: {hit.license_notice or '[No source copyright notice supplied]'}")
        else:
            self.passage_kind.clear()
            self.source_info.clear()
        self.document_button.setText("Read Whole Document")

    def show_document(self):
        hit = self.selected_hit()
        if not hit:
            return
        if self.document_button.text() == "Return to Passage":
            self.show_result(self.results.currentRow())
            return
        try:
            document = self.reference_store.get_document(hit.document_id)
            if document is None:
                raise ValueError("The source document is no longer available. Search again.")
        except (OSError, ValueError, sqlite3.Error) as exc:
            QMessageBox.warning(self, "Read Rules Document", str(exc))
            return
        self.passage.setPlainText(document.text)
        self.document_button.setText("Return to Passage")

    def open_source(self):
        hit = self.selected_hit()
        if hit and hit.source_url:
            if not QDesktopServices.openUrl(QUrl(hit.source_url)):
                QMessageBox.warning(self, "Open Rules Source", "The browser could not open the source URL.")

    def use_in_scribe(self):
        hit = self.selected_hit()
        if not hit:
            return
        try:
            context = build_rules_context([hit], self.query.text())
        except ValueError as exc:
            QMessageBox.warning(self, "Use Rules in Scribe", str(exc))
            return
        self.result_context = context
        # Finish a modal reference lookup before showing the modeless Scribe.
        self.accept()
        self.context_requested.emit(context)

    def import_document(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Import a 3.5 Rules Document", "", "Text and HTML (*.txt *.md *.html *.htm)")
        if not path:
            return
        dialog = ImportRulesDialog(self.reference_store, path, self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self._idle_status()
            if self.query.text().strip():
                self.search()

    def fetch_source(self):
        if self.fetch_worker is not None:
            return
        self.fetch_button.setEnabled(False)
        self.source_picker.setEnabled(False)
        self.status.setText(f"Downloading {self.source_picker.currentText()}…")
        worker = _FetchSource(self.reference_store, self.source_picker.currentData())
        self.fetch_worker = worker
        worker.signals.done.connect(self._fetch_done)
        worker.signals.failed.connect(self._fetch_failed)
        QThreadPool.globalInstance().start(worker)

    def _fetch_finished(self):
        self.fetch_worker = None
        self.fetch_button.setEnabled(True)
        self.source_picker.setEnabled(True)

    def _fetch_done(self, document_id: str):
        self._fetch_finished()
        self._idle_status()
        if self.query.text().strip():
            self.search()
        else:
            self.status.setText("SRD section saved for offline search. Enter words above to find its passages.")

    def _fetch_failed(self, message: str):
        self._fetch_finished()
        self.status.setText(message)
        QMessageBox.warning(self, "Download SRD Section", message)
