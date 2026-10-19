"""Non-blocking, optional local text writer using already installed GGUF files."""
from __future__ import annotations

from pathlib import Path
import time

from PyQt6.QtCore import QObject, QRunnable, QSettings, QThreadPool, pyqtSignal, pyqtSlot
from PyQt6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QFileDialog, QHBoxLayout, QLabel, QLineEdit,
    QMessageBox, QPlainTextEdit, QPushButton, QSpinBox, QVBoxLayout, QWidget,
)

from .local_ai import (
    DEFAULT_MODEL, DEFAULT_OLLAMA_MODEL, GGUF_MODELS, LocalAIError,
    discover_llama_server, recommended_cpu_threads, text_generate,
    unload_cached_model,
)


class _Signals(QObject):
    done = pyqtSignal(str, float)
    failed = pyqtSignal(str)


class _Generate(QRunnable):
    def __init__(self, kind, context, model, backend, runner, gpu_layers,
                 cpu_threads, batch_threads, keep_loaded):
        super().__init__()
        self.kind = kind
        self.context = context
        self.model = model
        self.backend = backend
        self.runner = runner
        self.gpu_layers = gpu_layers
        self.cpu_threads = cpu_threads
        self.batch_threads = batch_threads
        self.keep_loaded = keep_loaded
        self.signals = _Signals()

    @pyqtSlot()
    def run(self):
        started = time.monotonic()
        try:
            output = text_generate(
                self.kind, self.context, model=self.model,
                backend=self.backend, llama_server=self.runner,
                gpu_layers=self.gpu_layers,
                cpu_threads=self.cpu_threads,
                batch_threads=self.batch_threads,
                keep_loaded=self.keep_loaded,
            )
        except (LocalAIError, ValueError) as exc:
            self.signals.failed.emit(str(exc))
        except Exception as exc:
            self.signals.failed.emit(f"Local writing error: {exc}")
        else:
            self.signals.done.emit(output, time.monotonic() - started)


class AIWritingDialog(QDialog):
    """Write names, character biographies or DM scenes with local GGUF models.

    Does not invoke generation until the user clicks Generate. No models are
    downloaded, copied or modified. The selected gguf uses llama.cpp's
    llama-server executable running on 127.0.0.1 for a single request.
    """

    def __init__(self, kind: str = "dm", context: str = "", parent=None):
        super().__init__(parent)
        self.kind = kind
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
            "monster_bio": "Monster Bestiary Biography",
            "encounter_json": "Random Encounter Designer",
            "pc_json": "Generate Complete Character Draft",
            "npc_json": "Generate Complete NPC Draft",
            "monster_json": "Generate Monster Stat Draft",
            "campaign_outline": "Long-Form Campaign Architect",
            "campaign_chapter": "Campaign Chapter Writer",
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
        if kind not in ("names",):
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

        self.performance_toggle = QPushButton("Performance settings  ▸  CPU threads / model cache")
        self.performance_toggle.setCheckable(True)
        self.performance_toggle.setAccessibleName("Show performance settings")
        self.performance_toggle.toggled.connect(self._toggle_performance)
        root.addWidget(self.performance_toggle)
        self.performance_panel = QWidget()
        performance = QVBoxLayout(self.performance_panel)
        performance.setContentsMargins(0, 0, 0, 0)
        performance.setSpacing(7)

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
        performance.addWidget(self.gpu_row)

        threads_layout = QHBoxLayout()
        threads_layout.addWidget(QLabel("CPU threads"))
        self.cpu_threads = QSpinBox()
        self.cpu_threads.setRange(1, 64)
        suggested = recommended_cpu_threads()
        saved_cpu = self.settings.value("scribe/cpu_threads", suggested, type=int)
        self.cpu_threads.setValue(saved_cpu)
        self.cpu_threads.setAccessibleName("CPU inference threads")
        self.cpu_threads.setToolTip(
            "Native CPU threads used to generate tokens. A conservative "
            "starting point is about half the logical CPU count; "
            "more threads do not always improve throughput."
        )
        threads_layout.addWidget(self.cpu_threads)
        threads_layout.addWidget(QLabel("Prompt threads"))
        self.batch_threads = QSpinBox()
        self.batch_threads.setRange(1, 64)
        saved_batch = self.settings.value("scribe/batch_threads", suggested, type=int)
        self.batch_threads.setValue(saved_batch)
        self.batch_threads.setAccessibleName("CPU prompt processing threads")
        self.batch_threads.setToolTip(
            "Threads used when processing the prompt. Try the same value "
            "as CPU threads, then measure against other values."
        )
        threads_layout.addWidget(self.batch_threads)
        threads_layout.addStretch()
        self.threads_row = QWidget()
        self.threads_row.setLayout(threads_layout)
        performance.addWidget(self.threads_row)

        warm_line = QHBoxLayout()
        self.keep_loaded = QCheckBox("Keep the selected model loaded for the next prompt")
        self.keep_loaded.setAccessibleName("Reuse the loaded GGUF model")
        self.keep_loaded.setChecked(
            self.settings.value("scribe/keep_loaded", True, type=bool)
        )
        self.keep_loaded.setToolTip(
            "Avoids reloading several gigabytes on each prompt. "
            "Consumes RAM/VRAM until unloaded or the app exits."
        )
        warm_line.addWidget(self.keep_loaded, 1)
        self.unload_button = QPushButton("Unload Model")
        self.unload_button.setToolTip("Free local AI model RAM and GPU memory now.")
        self.unload_button.clicked.connect(self.unload_model)
        warm_line.addWidget(self.unload_button)
        self.warm_row = QWidget()
        self.warm_row.setLayout(warm_line)
        performance.addWidget(self.warm_row)
        root.addWidget(self.performance_panel)
        self.performance_panel.setVisible(False)

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
            "Use Draft" if kind != "dm" else "Close"
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

    def _toggle_performance(self, enabled):
        self.performance_panel.setVisible(
            enabled and self.backend.currentData() == "gguf"
        )
        self.performance_toggle.setText(
            "Performance settings  ▾  CPU threads / model cache" if enabled
            else "Performance settings  ▸  CPU threads / model cache"
        )

    def _update_engine(self, *args):
        gguf = self.backend.currentData() == "gguf"
        self.preset_row.setVisible(gguf)
        self.browse_model.setVisible(gguf)
        self.runtime_row.setVisible(gguf)
        self.performance_toggle.setVisible(gguf)
        self.performance_panel.setVisible(
            gguf and self.performance_toggle.isChecked()
        )
        if gguf:
            self._choose_preset()
            self.status.setText(
                "Existing GGUF files run with native CPU threading. "
                "Keeping a model loaded speeds up later prompts but uses RAM."
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

    def unload_model(self):
        if unload_cached_model():
            self.status.setText("Cached model unloaded. RAM/VRAM released.")
        else:
            self.status.setText(
                "The model is generating. Wait for completion before unloading."
            )

    def generate(self):
        backend = self.backend.currentData()
        if backend == "gguf":
            self.settings.setValue("scribe/llama_server", self.runner.text().strip())
            self.settings.setValue("scribe/cpu_threads", self.cpu_threads.value())
            self.settings.setValue("scribe/batch_threads", self.batch_threads.value())
            self.settings.setValue("scribe/keep_loaded", self.keep_loaded.isChecked())
        self.generate_button.setEnabled(False)
        self.status.setText(
            "Generating locally. First request may load the model into memory…"
        )
        self.unload_button.setEnabled(False)
        job = _Generate(self.kind, self.context.toPlainText(),
                        self.model.text().strip(), backend,
                        self.runner.text().strip() if backend == "gguf" else "",
                        self.gpu_layers.value() if backend == "gguf" else 0,
                        self.cpu_threads.value() if backend == "gguf" else None,
                        self.batch_threads.value() if backend == "gguf" else None,
                        self.keep_loaded.isChecked() if backend == "gguf" else False)
        self.worker = job
        job.signals.done.connect(self.done)
        job.signals.failed.connect(self.failed)
        QThreadPool.globalInstance().start(job)

    def done(self, output, elapsed):
        self.result.setPlainText(output)
        self.status.setText(
            f"Generated locally in {elapsed:.1f}s (includes any model loading). "
            "Review and edit before using."
        )
        self.generate_button.setEnabled(True)
        self.unload_button.setEnabled(True)
        self.worker = None

    def failed(self, reason):
        self.status.setText(reason)
        self.generate_button.setEnabled(True)
        self.unload_button.setEnabled(True)
        self.worker = None

    def copy_text(self):
        from PyQt6.QtWidgets import QApplication
        QApplication.clipboard().setText(self.result.toPlainText())
        self.status.setText("Draft copied to clipboard.")

    def accept_draft(self):
        if self.kind != "dm" and not self.result.toPlainText().strip():
            QMessageBox.information(self, "Nothing to use", "Write or generate a draft first.")
            return
        self.generated_text = self.result.toPlainText()
        self.accept()
