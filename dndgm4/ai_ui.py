"""Non-blocking, optional local text writer using already installed GGUF files."""
from __future__ import annotations

from pathlib import Path
import os
import tempfile

from PyQt6.QtCore import Qt, QObject, QRunnable, QSettings, QThreadPool, pyqtSignal, pyqtSlot
from PyQt6.QtWidgets import (
    QComboBox, QDialog, QFileDialog, QHBoxLayout, QLabel, QLineEdit,
    QMessageBox, QPlainTextEdit, QPushButton, QScrollArea, QSpinBox, QVBoxLayout, QWidget,
)


DM_TASKS = (
    ("dm", "Scene narration",
     "Player-facing read-aloud text, with sensory details and room for player choices."),
    ("campaign_plan", "Campaign planning",
     "Develop a premise, factions, locations, hooks and branching consequences."),
    ("session_plan", "Session preparation",
     "Prepare flexible scenes, NPC motives, clues, complications and pacing."),
    ("dm_advice", "Advice during play",
     "Describe the decision or rules question. Review suggestions and uncertain rulings as the DM."),
    ("recap", "Session recap",
     "Supply what actually happened; the recap uses recorded events and marks missing information."),
)

from .local_ai import (
    DEFAULT_MODEL, DEFAULT_OLLAMA_MODEL, GGUF_MODELS, LocalAIError,
    discover_llama_server, text_generate,
)


class _Signals(QObject):
    done = pyqtSignal(str)
    failed = pyqtSignal(str)


class _Generate(QRunnable):
    def __init__(self, kind, context, model, backend, runner, gpu_layers):
        super().__init__()
        self.kind = kind
        self.context = context
        self.model = model
        self.backend = backend
        self.runner = runner
        self.gpu_layers = gpu_layers
        self.signals = _Signals()

    @pyqtSlot()
    def run(self):
        try:
            output = text_generate(
                self.kind, self.context, model=self.model,
                backend=self.backend, llama_server=self.runner,
                gpu_layers=self.gpu_layers,
            )
        except (LocalAIError, ValueError) as exc:
            self.signals.failed.emit(str(exc))
        except Exception as exc:
            self.signals.failed.emit(f"Local writing error: {exc}")
        else:
            self.signals.done.emit(output)


class AIWritingDialog(QDialog):
    """Write names, character biographies or DM scenes with local GGUF models.

    Does not invoke generation until the user clicks Generate. No models are
    downloaded, copied or modified. The selected gguf uses llama.cpp's
    llama-server executable running on 127.0.0.1 for a single request.
    """

    def __init__(self, kind: str = "dm", context: str = "", parent=None):
        super().__init__(parent)
        self.kind = kind
        self.source_audience = "user"
        self.request_audience = "user"
        # Closing the Scribe must not signal QApplication to quit, even
        # when opened as a standalone non-modal child of the main window.
        self.setAttribute(Qt.WidgetAttribute.WA_QuitOnClose, False)
        self.generated_text: str | None = None
        self.worker = None
        self.settings = QSettings("Kaotick Jay", "DnDGameManager4")
        self.setWindowTitle("The Scribe | Local AI Writing Assistant")
        self.resize(790, 750)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        self.form_scroll = QScrollArea()
        self.form_scroll.setWidgetResizable(True)
        self.form_scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        self.form_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        form = QWidget()
        root = QVBoxLayout(form)
        self.form_scroll.setWidget(form)
        outer.addWidget(self.form_scroll)
        root.setContentsMargins(22, 20, 22, 18)
        root.setSpacing(11)

        heading = QLabel("THE SCRIBE  /  LOCAL WRITING STUDIO")
        heading.setObjectName("eyebrow")
        root.addWidget(heading)
        self.title = QLabel({
            "bio": "Player Character Biography",
            "npc_bio": "Nonplayer Character Biography",
            "character_build": "Complete D&D 3.5 Character Draft",
            "monster_bio": "Monster Bestiary Biography",
            "dm": "Dungeon Master's Assistant",
            "names": "AI Name Inspiration",
        }[kind])
        self.title.setObjectName("pageTitle")
        root.addWidget(self.title)

        self.engine_settings = QWidget()
        engine_root = QVBoxLayout(self.engine_settings)
        engine_root.setContentsMargins(0, 0, 0, 0)
        engine_root.setSpacing(9)
        if kind == "dm":
            self.settings_toggle = QPushButton("Local model settings ▸")
            self.settings_toggle.setCheckable(True)
            self.settings_toggle.setAccessibleName("Show or hide local model settings")
            self.settings_toggle.toggled.connect(self.engine_settings.setVisible)
            self.settings_toggle.toggled.connect(lambda visible: self.settings_toggle.setText(
                "Local model settings ▾" if visible else "Local model settings ▸"))
            root.addWidget(self.settings_toggle)
            self.engine_settings.hide()
        root.addWidget(self.engine_settings)

        info = QLabel(
            "Use your existing Goodneighbor Blues AI Writer GGUF files in "
            "place. Select Qwen3 for general writing or Gemma for literary "
            "prose. A local llama.cpp llama-server executable is required. "
            "No model downloads, cloud requests or duplicate model files."
        )
        info.setObjectName("muted")
        info.setWordWrap(True)
        engine_root.addWidget(info)

        engine_line = QHBoxLayout()
        engine_line.addWidget(QLabel("Inference backend"))
        self.backend = QComboBox()
        self.backend.addItem("Existing GGUF models (llama.cpp)", "gguf")
        self.backend.addItem("Ollama localhost server (optional)", "ollama")
        self.backend.setAccessibleName("Local writing engine")
        engine_line.addWidget(self.backend, 1)
        engine_root.addLayout(engine_line)

        preset_line = QHBoxLayout()
        self.presets_label = QLabel("Model preset")
        preset_line.addWidget(self.presets_label)
        self.preset = QComboBox()
        for display, path in GGUF_MODELS.items():
            self.preset.addItem(display, str(path))
        self.preset.addItem("Custom GGUF file", "")
        if kind in ("dm", "bio", "npc_bio", "monster_bio", "character_build"):
            self.preset.setCurrentIndex(1)  # Gemma writer is the prose default.
        self.preset.setAccessibleName("Choose Qwen3, Gemma or custom GGUF model")
        self.preset.currentIndexChanged.connect(self._choose_preset)
        preset_line.addWidget(self.preset, 1)
        self.preset_row = QWidget()
        self.preset_row.setLayout(preset_line)
        engine_root.addWidget(self.preset_row)

        model_row = QHBoxLayout()
        model_row.addWidget(QLabel("Model file / name"))
        self.model = QLineEdit(DEFAULT_MODEL)
        self.model.setToolTip("Path to existing GGUF file; or Ollama model name.")
        self.model.setAccessibleName("Local GGUF file path or Ollama model name")
        model_row.addWidget(self.model, 1)
        self.browse_model = QPushButton("Browse…")
        self.browse_model.clicked.connect(self._browse_model)
        model_row.addWidget(self.browse_model)
        engine_root.addLayout(model_row)

        runtime_line = QHBoxLayout()
        runtime_line.addWidget(QLabel("llama-server"))
        saved_runner = str(self.settings.value("scribe/llama_server", "") or "")
        self.runner = QLineEdit(saved_runner or discover_llama_server())
        self.runner.setPlaceholderText("Select existing llama-server.exe")
        self.runner.setAccessibleName("llama.cpp server executable path")
        runtime_line.addWidget(self.runner, 1)
        choose_runner = QPushButton("Browse…")
        choose_runner.clicked.connect(self._browse_runner)
        runtime_line.addWidget(choose_runner)
        self.runtime_row = QWidget()
        self.runtime_row.setLayout(runtime_line)
        engine_root.addWidget(self.runtime_row)

        gpu_line = QHBoxLayout()
        gpu_line.addWidget(QLabel("GPU layers"))
        self.gpu_layers = QSpinBox()
        self.gpu_layers.setRange(0, 99)
        self.gpu_layers.setValue(0)
        self.gpu_layers.setToolTip(
            "0 runs on CPU. Increase only when using a compatible Vulkan, "
            "CUDA or other GPU-enabled llama.cpp build."
        )
        self.gpu_layers.setAccessibleName("Number of GGUF GPU offload layers")
        gpu_line.addWidget(self.gpu_layers)
        gpu_note = QLabel("0 = CPU (portable default)")
        gpu_note.setObjectName("muted")
        gpu_line.addWidget(gpu_note)
        gpu_line.addStretch()
        self.gpu_row = QWidget()
        self.gpu_row.setLayout(gpu_line)
        engine_root.addWidget(self.gpu_row)

        if kind == "dm":
            task_line = QHBoxLayout()
            task_line.addWidget(QLabel("Help with"))
            self.dm_task = QComboBox()
            self.dm_task.setAccessibleName("Dungeon Master assistance task")
            for task, label, _ in DM_TASKS:
                self.dm_task.addItem(label, task)
            task_line.addWidget(self.dm_task, 1)
            root.addLayout(task_line)
            self.task_hint = QLabel(DM_TASKS[0][2])
            self.task_hint.setWordWrap(True)
            self.task_hint.setObjectName("muted")
            root.addWidget(self.task_hint)
            request_line = QHBoxLayout()
            request_line.addWidget(QLabel("Your request"))
            self.dm_request = QLineEdit()
            self.dm_request.setMaxLength(2000)
            self.dm_request.textChanged.connect(self._mark_request_audience)
            self.dm_request.setAccessibleName("Request for the Dungeon Master assistant")
            self.dm_request.setPlaceholderText("What would help you plan or run this session?")
            request_line.addWidget(self.dm_request, 1)
            root.addLayout(request_line)
            self.dm_task.currentIndexChanged.connect(self._update_task)

        root.addWidget(QLabel("Prompt / Campaign Details"))
        if kind == "dm":
            self.context_source = QLabel("Context: text entered by you; review it before player narration.")
            self.context_source.setWordWrap(True)
            self.context_source.setObjectName("muted")
            root.addWidget(self.context_source)
            sources = QHBoxLayout()
            self.recall_button = QPushButton("Recall Campaign Sources…")
            self.recall_button.clicked.connect(self.recall_campaign_sources)
            sources.addWidget(self.recall_button)
            clear = QPushButton("Clear Sources / Write a New Prompt")
            clear.clicked.connect(self.clear_source_context)
            sources.addWidget(clear)
            root.addLayout(sources)
        self.context = QPlainTextEdit()
        self.context.setPlainText(context)
        self.context.setPlaceholderText(
            "For DM narration: the party's location, atmosphere and situation.\n"
            "For biographies: race/species, class or creature type, personality, "
            "ecology, existing lore and campaign constraints."
        )
        self.context.setMinimumHeight(105)
        self.context.setAccessibleName("Scene or character writing context")
        root.addWidget(self.context, 2)

        root.addWidget(QLabel("Generated Draft (editable)"))
        if kind == "dm":
            self.draft_audience = QLabel("Draft audience is unverified; review before sharing.")
            self.draft_audience.setWordWrap(True)
            root.addWidget(self.draft_audience)
        self.result = QPlainTextEdit()
        self.result.setMinimumHeight(150)
        self.result.setAccessibleName("AI-generated editable draft")
        root.addWidget(self.result, 3)
        self.review_campaign_button = None
        if kind == "dm" and callable(getattr(parent, "review_scribe_draft", None)):
            self.review_campaign_button = QPushButton("Review Draft for Campaign…")
            self.review_campaign_button.setAccessibleName("Review the editable Scribe draft before saving a campaign field")
            self.review_campaign_button.setEnabled(False)
            self.review_campaign_button.clicked.connect(self.review_campaign_draft)
            self.result.textChanged.connect(lambda: self.review_campaign_button.setEnabled(
                bool(self.result.toPlainText().strip())))
            root.addWidget(self.review_campaign_button)

        self.status = QLabel("Ready. Select a local model and choose Generate.")
        self.status.setObjectName("muted")
        self.status.setWordWrap(True)
        self.status.setContentsMargins(22, 0, 22, 0)
        outer.addWidget(self.status)

        actions = QHBoxLayout()
        actions.setContentsMargins(22, 0, 22, 16)
        self.generate_button = QPushButton("Generate Locally")
        self.generate_button.setObjectName("primaryButton")
        self.generate_button.clicked.connect(self.generate)
        actions.addWidget(self.generate_button)
        copy = QPushButton("Copy Draft")
        copy.clicked.connect(self.copy_text)
        actions.addWidget(copy)
        self.save_draft_button = QPushButton("Save Draft…")
        self.save_draft_button.setAccessibleName("Save the editable draft as a text file")
        self.save_draft_button.clicked.connect(self.save_draft)
        actions.addWidget(self.save_draft_button)
        actions.addStretch()
        self.use = QPushButton(
            "Use Draft" if kind in ("bio", "npc_bio", "monster_bio", "character_build", "names")
            else "Close"
        )
        self.use.clicked.connect(self.accept_draft)
        actions.addWidget(self.use)
        outer.addLayout(actions)
        self.backend.currentIndexChanged.connect(self._update_engine)
        self._update_engine()

    def _choose_preset(self, *args):
        model_path = self.preset.currentData()
        if model_path:
            self.model.setText(model_path)

    def review_campaign_draft(self):
        text = self.result.toPlainText()
        if text.strip() and self.kind == "dm":
            callback = getattr(self.parent(), "review_scribe_draft", None)
            if callable(callback):
                callback(text, task=self.dm_task.currentData())

    def _update_engine(self, *args):
        gguf = self.backend.currentData() == "gguf"
        self.preset_row.setVisible(gguf)
        self.browse_model.setVisible(gguf)
        self.runtime_row.setVisible(gguf)
        self.gpu_row.setVisible(gguf)
        if gguf:
            self._choose_preset()
            self.status.setText(
                "Existing GGUF files are used directly. Select llama-server "
                "if it is not installed on PATH."
            )
        else:
            self.model.setText(DEFAULT_OLLAMA_MODEL)
            self.status.setText(
                "Ollama compatibility mode uses the running localhost server "
                "and its existing model registry, not the GGUF file paths."
            )

    def _browse_model(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Select existing GGUF model", str(Path(self.model.text()).parent),
            "GGUF model (*.gguf);;All files (*)",
        )
        if path:
            self.preset.setCurrentIndex(self.preset.count() - 1)
            self.model.setText(path)

    def _browse_runner(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Select llama.cpp llama-server",
            str(Path(self.runner.text()).parent) if self.runner.text() else str(Path.home()),
            "Executables (*.exe);;All files (*)",
        )
        if path:
            self.runner.setText(path)

    def load_context(self, context, *, audience="dm"):
        if audience not in ("dm", "player", "user"):
            raise ValueError("Choose a valid context audience.")
        if self.worker is not None:
            raise ValueError("Wait for the current Scribe request before replacing its sources.")
        if self.kind == "dm" and audience == "player" and self.source_audience != "player":
            self.dm_request.clear()
        self.context.setPlainText(context)
        self.source_audience = audience
        if self.kind == "dm":
            labels = {"dm": "Private saved DM sources: use planning, advice or recap. Player narration requires public sources.",
                      "player": "Player-facing sources: only the reviewed public-field selection was loaded.",
                      "user": "Context: text entered by you; review it before player narration."}
            self.context_source.setText(labels[audience])
            if self.result.toPlainText().strip():
                self.status.setText("Sources loaded. The existing draft has not been regenerated for these sources.")

    def clear_source_context(self):
        try:
            self.load_context("", audience="user")
            self.dm_request.clear()
        except ValueError as exc:
            self.status.setText(str(exc))

    def _mark_request_audience(self, *args):
        self.request_audience = "player" if self.dm_task.currentData() == "dm" else "dm"

    def recall_campaign_sources(self):
        host = self.parent()
        while host is not None:
            callback = getattr(host, "open_campaign_recall", None)
            if callable(callback):
                callback(query=self.dm_request.text().strip(),
                         audience="player" if self.dm_task.currentData() == "dm" else "dm", writer=self)
                return
            host = host.parent()
        self.status.setText("Open Campaign Recall from the main campaign window after selecting a saved session.")

    def generate(self):
        # Keep the loaded saved-record context intact; a task-specific request
        # is appended only for this generation, never written into the library.
        context = self.context.toPlainText()
        task = self.kind
        if self.kind == "dm":
            task = self.dm_task.currentData()
            if task == "dm" and self.source_audience == "dm":
                self.status.setText("Private saved sources cannot be used for player narration. Recall player-facing sources, or clear the context and write a new public prompt.")
                return
            if task == "dm" and self.dm_request.text().strip() and self.request_audience == "dm":
                self.status.setText("This request was written for private DM work. Clear it or rewrite it for player narration before generating.")
                return
            request = self.dm_request.text().strip()
            if request:
                context = context.rstrip() + ("\n\n" if context.strip() else "")
                context += "DM REQUEST:\n" + request
        if not 1 <= len(context.strip()) <= 6000:
            self.status.setText(
                "Provide 1–6,000 characters of context and request combined. "
                "Shorten the text before generating; no details were omitted.")
            return
        backend = self.backend.currentData()
        if backend == "gguf":
            self.settings.setValue("scribe/llama_server", self.runner.text().strip())
        self.generate_button.setEnabled(False)
        self.status.setText("Generating using the local model. First load may take time…")
        job = _Generate(task, context,
                        self.model.text().strip(), backend,
                        self.runner.text().strip() if backend == "gguf" else "",
                        self.gpu_layers.value() if backend == "gguf" else 0)
        self._generation_audience = "player" if task == "dm" else "dm"
        self.worker = job
        job.signals.done.connect(self.generation_completed)
        job.signals.failed.connect(self.failed)
        QThreadPool.globalInstance().start(job)

    def _update_task(self):
        task = self.dm_task.currentData()
        self.task_hint.setText(next(hint for key, _, hint in DM_TASKS if key == task))

    def save_draft(self):
        draft = self.result.toPlainText()
        if not draft.strip():
            QMessageBox.information(self, "Nothing to save", "Write or generate a draft first.")
            return
        filename, _ = QFileDialog.getSaveFileName(
            self, "Save Scribe Draft", "scribe-draft.txt",
            "Text files (*.txt);;Markdown files (*.md)")
        if not filename:
            return
        target = Path(filename)
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(
                    mode="w", encoding="utf-8", dir=target.parent,
                    prefix=".scribe_", suffix=".tmp", delete=False) as output:
                temporary = Path(output.name)
                output.write(draft)
                output.flush()
                os.fsync(output.fileno())
            os.replace(temporary, target)
        except (OSError, UnicodeError) as exc:
            QMessageBox.warning(self, "Draft not saved", str(exc))
            return
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)
        self.status.setText(f"Draft saved · {target}")

    def generation_completed(self, output):
        """Handle completed inference without overriding QDialog.done(int).

        Qt invokes QDialog.done(result_code) when Use Draft calls accept().
        A Python method named done(output) shadows that virtual method and
        receives an integer here, crashing the Windows Qt event loop.
        """
        self.result.setPlainText(output)
        if self.kind == "dm":
            self.draft_audience.setText("Player narration draft: review before sharing." if getattr(self, "_generation_audience", "dm") == "player"
                                       else "Private DM draft: use for planning, advice or a reviewed recap.")
        self.status.setText("Generated locally. Review and edit before using.")
        self.generate_button.setEnabled(True)
        self.worker = None

    def failed(self, reason):
        self.status.setText(reason)
        self.generate_button.setEnabled(True)
        self.worker = None

    def copy_text(self):
        from PyQt6.QtWidgets import QApplication
        QApplication.clipboard().setText(self.result.toPlainText())
        self.status.setText("Draft copied to clipboard.")

    def closeEvent(self, event):
        if self.kind == "dm":
            # This sidebar narrator stays owned by MainWindow. Closing it
            # must not enter QDialog's native reject/finalize path, which
            # can end the application's window loop on some Windows setups.
            self.hide()
            event.ignore()
            return
        super().closeEvent(event)

    def accept_draft(self):
        if self.kind in ("bio", "npc_bio", "monster_bio", "character_build", "names") and not self.result.toPlainText().strip():
            QMessageBox.information(self, "Nothing to use", "Write or generate a draft first.")
            return
        self.generated_text = self.result.toPlainText()
        if self.kind == "dm":
            self.hide()
        else:
            self.accept()
