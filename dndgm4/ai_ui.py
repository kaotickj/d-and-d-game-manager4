"""Non-blocking, optional local text writer using already installed GGUF files."""
from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import Qt, QObject, QRunnable, QSettings, QThreadPool, pyqtSignal, pyqtSlot
from PyQt6.QtWidgets import (
    QComboBox, QDialog, QFileDialog, QHBoxLayout, QLabel, QLineEdit,
    QMessageBox, QPlainTextEdit, QPushButton, QSpinBox, QVBoxLayout, QWidget,
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
        # Closing the Scribe must not signal QApplication to quit, even
        # when opened as a standalone non-modal child of the main window.
        self.setAttribute(Qt.WidgetAttribute.WA_QuitOnClose, False)
        self.generated_text: str | None = None
        self.worker = None
        self.settings = QSettings("Kaotick Jay", "DnDGameManager4")
        self.setWindowTitle("The Scribe | Local AI Writing Assistant")
        self.resize(790, 750)
        root = QVBoxLayout(self)
        root.setContentsMargins(22, 20, 22, 18)
        root.setSpacing(11)

        heading = QLabel("THE SCRIBE  /  LOCAL WRITING STUDIO")
        heading.setObjectName("eyebrow")
        root.addWidget(heading)
        title = QLabel({
            "bio": "Player Character Biography",
            "npc_bio": "Nonplayer Character Biography",
            "character_build": "Complete D&D 3.5 Character Draft",
            "monster_bio": "Monster Bestiary Biography",
            "dm": "Dungeon Master's Narrator",
            "names": "AI Name Inspiration",
        }[kind])
        title.setObjectName("pageTitle")
        root.addWidget(title)

        info = QLabel(
            "Use your existing Goodneighbor Blues AI Writer GGUF files in "
            "place. Select Qwen3 for general writing or Gemma for literary "
            "prose. A local llama.cpp llama-server executable is required. "
            "No model downloads, cloud requests or duplicate model files."
        )
        info.setObjectName("muted")
        info.setWordWrap(True)
        root.addWidget(info)

        engine_line = QHBoxLayout()
        engine_line.addWidget(QLabel("Inference backend"))
        self.backend = QComboBox()
        self.backend.addItem("Existing GGUF models (llama.cpp)", "gguf")
        self.backend.addItem("Ollama localhost server (optional)", "ollama")
        self.backend.setAccessibleName("Local writing engine")
        engine_line.addWidget(self.backend, 1)
        root.addLayout(engine_line)

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
        root.addWidget(self.preset_row)

        model_row = QHBoxLayout()
        model_row.addWidget(QLabel("Model file / name"))
        self.model = QLineEdit(DEFAULT_MODEL)
        self.model.setToolTip("Path to existing GGUF file; or Ollama model name.")
        self.model.setAccessibleName("Local GGUF file path or Ollama model name")
        model_row.addWidget(self.model, 1)
        self.browse_model = QPushButton("Browse…")
        self.browse_model.clicked.connect(self._browse_model)
        model_row.addWidget(self.browse_model)
        root.addLayout(model_row)

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
        root.addWidget(self.runtime_row)

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
        root.addWidget(self.gpu_row)

        root.addWidget(QLabel("Prompt / Campaign Details"))
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
        self.result = QPlainTextEdit()
        self.result.setMinimumHeight(150)
        self.result.setAccessibleName("AI-generated editable draft")
        root.addWidget(self.result, 3)

        self.status = QLabel("Ready. Select a local model and choose Generate.")
        self.status.setObjectName("muted")
        self.status.setWordWrap(True)
        root.addWidget(self.status)

        actions = QHBoxLayout()
        self.generate_button = QPushButton("Generate Locally")
        self.generate_button.setObjectName("primaryButton")
        self.generate_button.clicked.connect(self.generate)
        actions.addWidget(self.generate_button)
        copy = QPushButton("Copy Draft")
        copy.clicked.connect(self.copy_text)
        actions.addWidget(copy)
        actions.addStretch()
        self.use = QPushButton(
            "Use Draft" if kind in ("bio", "npc_bio", "monster_bio", "character_build", "names")
            else "Close"
        )
        self.use.clicked.connect(self.accept_draft)
        actions.addWidget(self.use)
        root.addLayout(actions)
        self.backend.currentIndexChanged.connect(self._update_engine)
        self._update_engine()

    def _choose_preset(self, *args):
        model_path = self.preset.currentData()
        if model_path:
            self.model.setText(model_path)

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

    def generate(self):
        backend = self.backend.currentData()
        if backend == "gguf":
            self.settings.setValue("scribe/llama_server", self.runner.text().strip())
        self.generate_button.setEnabled(False)
        self.status.setText("Generating using the local model. First load may take time…")
        job = _Generate(self.kind, self.context.toPlainText(),
                        self.model.text().strip(), backend,
                        self.runner.text().strip() if backend == "gguf" else "",
                        self.gpu_layers.value() if backend == "gguf" else 0)
        self.worker = job
        job.signals.done.connect(self.done)
        job.signals.failed.connect(self.failed)
        QThreadPool.globalInstance().start(job)

    def done(self, output):
        self.result.setPlainText(output)
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
