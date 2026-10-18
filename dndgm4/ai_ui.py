"""A non-blocking, explicitly invoked local AI writing assistant for tabletop use."""
from __future__ import annotations

from PyQt6.QtCore import QObject, QRunnable, QThreadPool, pyqtSignal, pyqtSlot
from PyQt6.QtWidgets import (
    QComboBox, QDialog, QFormLayout, QHBoxLayout, QLabel, QLineEdit,
    QMessageBox, QPlainTextEdit, QPushButton, QVBoxLayout,
)
from .local_ai import DEFAULT_MODEL, LocalAIError, text_generate


class _Signals(QObject):
    done = pyqtSignal(str)
    failed = pyqtSignal(str)


class _Generate(QRunnable):
    def __init__(self, kind, context, model):
        super().__init__()
        self.kind = kind
        self.context = context
        self.model = model
        self.signals = _Signals()

    @pyqtSlot()
    def run(self):
        try:
            output = text_generate(self.kind, self.context, model=self.model)
        except (LocalAIError, ValueError) as exc:
            self.signals.failed.emit(str(exc))
        except Exception as exc:
            self.signals.failed.emit(f"Local AI error: {exc}")
        else:
            self.signals.done.emit(output)


class AIWritingDialog(QDialog):
    """Use existing local Ollama-compatible Qwen3 LLM, not Qwen3-TTS.

    The user opts in by pressing Generate. The output is always editable.
    Closing the dialog never affects stored character data.
    """

    def __init__(self, kind: str = "dm", context: str = "", parent=None):
        super().__init__(parent)
        self.kind = kind
        self.generated_text: str | None = None
        self.worker = None
        self.setWindowTitle("The Scribe | Local AI Writing Assistant")
        self.resize(770,730)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(22,20,22,18)
        layout.setSpacing(11)
        heading = QLabel("THE SCRIBE  /  LOCAL QWEN3")
        heading.setObjectName("eyebrow")
        layout.addWidget(heading)
        title = QLabel({"bio":"Character Biography","dm":"Dungeon Master's Narrator",
                        "names":"AI Name Inspiration"}[kind])
        title.setObjectName("pageTitle")
        layout.addWidget(title)
        caution = QLabel(
            "Text model required: Qwen3-TTS from Plague's Voice Studio creates speech, "
            "not prose. This tool contacts only your computer's Ollama server at "
            "127.0.0.1:11434, and only when you select Generate. "
            "No model is downloaded automatically."
        )
        caution.setWordWrap(True)
        caution.setObjectName("muted")
        layout.addWidget(caution)
        model_row=QHBoxLayout()
        model_row.addWidget(QLabel("Local text model"))
        self.model=QLineEdit(DEFAULT_MODEL)
        self.model.setToolTip("Name of installed Ollama text model, e.g. qwen3:4b")
        self.model.setAccessibleName("Ollama language model name")
        model_row.addWidget(self.model,1)
        layout.addLayout(model_row)
        layout.addWidget(QLabel("Prompt / Campaign Details"))
        self.context = QPlainTextEdit()
        self.context.setPlainText(context)
        self.context.setPlaceholderText(
            "For DM narration: party location, mood, current scene and any constraints.\n"
            "For bios: character name, race, class, goals, personality and tone."
        )
        self.context.setMinimumHeight(110)
        self.context.setAccessibleName("Narration or biography context")
        layout.addWidget(self.context,2)
        layout.addWidget(QLabel("Generated Draft (editable)"))
        self.result = QPlainTextEdit()
        self.result.setMinimumHeight(180)
        self.result.setAccessibleName("AI-generated editable draft")
        layout.addWidget(self.result,3)
        self.status=QLabel("Ready. Start your local language model, then choose Generate.")
        self.status.setObjectName("muted")
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        actions=QHBoxLayout()
        self.generate_button=QPushButton("Generate Locally")
        self.generate_button.setObjectName("primaryButton")
        self.generate_button.clicked.connect(self.generate)
        actions.addWidget(self.generate_button)
        copy=QPushButton("Copy Draft")
        copy.clicked.connect(self.copy_text)
        actions.addWidget(copy)
        actions.addStretch()
        self.use=QPushButton("Use Draft" if kind=="bio" else "Close")
        self.use.clicked.connect(self.accept_draft)
        actions.addWidget(self.use)
        layout.addLayout(actions)

    def generate(self):
        self.generate_button.setEnabled(False)
        self.status.setText("Generating on local computer. This may take a moment...")
        job=_Generate(self.kind,self.context.toPlainText(),self.model.text().strip())
        self.worker=job
        job.signals.done.connect(self.done)
        job.signals.failed.connect(self.failed)
        QThreadPool.globalInstance().start(job)

    def done(self,output):
        self.result.setPlainText(output)
        self.status.setText("Generated locally. Review and edit before using.")
        self.generate_button.setEnabled(True)
        self.worker=None

    def failed(self,reason):
        self.status.setText(reason)
        self.generate_button.setEnabled(True)
        self.worker=None

    def copy_text(self):
        from PyQt6.QtWidgets import QApplication
        QApplication.clipboard().setText(self.result.toPlainText())
        self.status.setText("Draft copied to clipboard.")

    def accept_draft(self):
        if self.kind=="bio" and not self.result.toPlainText().strip():
            QMessageBox.information(self,"Nothing to use","Write or generate a draft first.")
            return
        self.generated_text=self.result.toPlainText()
        self.accept()
