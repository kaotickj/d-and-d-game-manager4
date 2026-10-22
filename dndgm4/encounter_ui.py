"""Explicit roll, review and handoff for random encounter proposals."""
from __future__ import annotations

from dataclasses import replace

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QAbstractItemView, QCheckBox, QComboBox, QDialog, QFormLayout, QHBoxLayout,
    QHeaderView, QLabel, QLineEdit, QPlainTextEdit, QPushButton, QScrollArea,
    QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

from .encounter_generator import ENVIRONMENTS, generate_encounter


class EncounterGeneratorDialog(QDialog):
    """Build one draft without touching scenes, battles, or saved templates."""

    def __init__(self, records, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_QuitOnClose, False)
        self.setWindowTitle("Random Encounter Generator | DM Review")
        self.resize(900, 850)
        self.records = tuple(records)
        self.draft = None
        self.result_draft = None
        self.result_action = ""
        outer = QVBoxLayout(self)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        panel = QWidget()
        layout = QVBoxLayout(panel)
        heading = QLabel("RANDOM ENCOUNTER  /  ROLL & REVIEW")
        heading.setObjectName("pageTitle")
        layout.addWidget(heading)
        explanation = QLabel(
            "Roll a proposed scene and a group of creatures, then edit the result. "
            "Library creatures keep their saved statistics. Original creatures roll "
            "abilities and HP from Monster Maker type baselines; review their attacks, "
            "traits and balance before play. Challenge Ratings are not inferred.")
        explanation.setWordWrap(True)
        layout.addWidget(explanation)
        options = QFormLayout()
        self.source = QComboBox()
        self.source.addItem("Saved NPC / monster templates", "library")
        self.source.addItem("Original creature baselines", "original")
        if not any(record.kind in ("npc", "monster") and not record.archived for record in self.records):
            self.source.setCurrentIndex(1)
        self.source.setAccessibleName("Encounter creature source")
        options.addRow("Creatures:", self.source)
        self.environment = QComboBox()
        self.environment.addItems(ENVIRONMENTS)
        self.environment.setAccessibleName("Encounter environment")
        options.addRow("Environment:", self.environment)
        self.quantity = QLineEdit("1d4")
        self.quantity.setAccessibleName("Number of creatures as dice or a fixed number")
        self.quantity.setToolTip("Dice must always yield 1–12 creatures, e.g. 1d4, 2d6, 1d12; or enter a fixed count.")
        options.addRow("Count dice:", self.quantity)
        self.roll_initiative = QCheckBox("Roll initiative for each creature")
        options.addRow(self.roll_initiative)
        layout.addLayout(options)
        self.roll_button = QPushButton("Roll Encounter")
        self.roll_button.setObjectName("primaryButton")
        self.roll_button.clicked.connect(self.roll_encounter)
        layout.addWidget(self.roll_button)
        edits = QFormLayout()
        self.title = QLineEdit()
        self.title.setMaxLength(200)
        self.title.setAccessibleName("Encounter title")
        edits.addRow("Title:", self.title)
        self.hook = QLineEdit()
        self.hook.setAccessibleName("Encounter hook")
        edits.addRow("Hook:", self.hook)
        self.motive = QLineEdit()
        self.motive.setAccessibleName("Encounter creature motive")
        edits.addRow("Motive:", self.motive)
        self.complication = QLineEdit()
        self.complication.setAccessibleName("Encounter complication")
        edits.addRow("Complication:", self.complication)
        layout.addLayout(edits)
        layout.addWidget(QLabel("Player-facing read-aloud (editable)"))
        self.read_aloud = QPlainTextEdit()
        self.read_aloud.setMinimumHeight(85)
        self.read_aloud.setAccessibleName("Encounter read-aloud text")
        layout.addWidget(self.read_aloud)
        layout.addWidget(QLabel("Additional DM-only notes (editable)"))
        self.dm_notes = QPlainTextEdit()
        self.dm_notes.setMinimumHeight(70)
        self.dm_notes.setAccessibleName("Encounter DM-only notes")
        layout.addWidget(self.dm_notes)
        self.roster = QTableWidget(0, 4)
        self.roster.setAccessibleName("Generated encounter creatures")
        self.roster.setHorizontalHeaderLabels(("Creature", "HP", "AC", "Initiative"))
        self.roster.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.roster.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.roster.verticalHeader().hide()
        self.roster.setMinimumHeight(130)
        layout.addWidget(self.roster)
        layout.addWidget(QLabel("Creature details and DM brief"))
        self.details = QPlainTextEdit()
        self.details.setReadOnly(True)
        self.details.setAccessibleName("Full generated creature statistics and encounter brief")
        self.details.setMinimumHeight(170)
        layout.addWidget(self.details)
        layout.addWidget(QLabel("Roll log"))
        self.roll_log = QPlainTextEdit()
        self.roll_log.setReadOnly(True)
        self.roll_log.setAccessibleName("Encounter generation roll log")
        self.roll_log.setMinimumHeight(105)
        layout.addWidget(self.roll_log)
        scroll.setWidget(panel)
        outer.addWidget(scroll)
        self.status = QLabel("Ready. Nothing changes until you roll, review, and choose an action.")
        self.status.setWordWrap(True)
        outer.addWidget(self.status)
        actions = QHBoxLayout()
        self.scene_button = QPushButton("Save as Current Scene")
        self.scene_button.clicked.connect(lambda: self.accept_action("scene"))
        self.battle_button = QPushButton("Load into Battle Trakker")
        self.battle_button.setToolTip("Add these independent creatures to the current encounter; combat does not start automatically.")
        self.battle_button.clicked.connect(lambda: self.accept_action("battle"))
        self.scribe_button = QPushButton("Open in Scribe")
        self.scribe_button.clicked.connect(lambda: self.accept_action("scribe"))
        self.cancel_button = QPushButton("Cancel")
        self.cancel_button.clicked.connect(self.reject)
        for button in (self.scene_button, self.battle_button, self.scribe_button, self.cancel_button):
            actions.addWidget(button)
        outer.addLayout(actions)
        self._enable_actions(False)
        for field in (self.title, self.hook, self.motive, self.complication):
            field.textChanged.connect(self.update_details)
        self.read_aloud.textChanged.connect(self.update_details)
        self.dm_notes.textChanged.connect(self.update_details)

    def _enable_actions(self, enabled):
        for button in (self.scene_button, self.battle_button, self.scribe_button):
            button.setEnabled(enabled)

    def roll_encounter(self):
        try:
            draft = generate_encounter(
                self.records, environment=self.environment.currentText(),
                quantity=self.quantity.text(), source=self.source.currentData(),
                roll_initiative=self.roll_initiative.isChecked())
        except ValueError as exc:
            self.draft = None
            self._enable_actions(False)
            self.status.setText(f"Encounter not generated: {exc}")
            return
        self.draft = draft
        self.title.setText(draft.title)
        self.hook.setText(draft.hook)
        self.motive.setText(draft.motive)
        self.complication.setText(draft.complication)
        self.read_aloud.setPlainText(draft.read_aloud)
        self.dm_notes.setPlainText(draft.dm_notes)
        self.roster.setRowCount(len(draft.fighters))
        for row, fighter in enumerate(draft.fighters):
            for column, value in enumerate((fighter.name, fighter.hp, fighter.ac,
                                             fighter.initiative if fighter.initiative is not None else "Not rolled")):
                self.roster.setItem(row, column, QTableWidgetItem(str(value)))
        self.roll_log.setPlainText("\n".join(draft.roll_log))
        self.update_details()
        self._enable_actions(True)
        self.status.setText(
            f"Draft ready: {len(draft.fighters)} creatures. Review the scene, statistics and roll log. "
            "Loading into Battle Trakker adds creatures to the current encounter.")

    def _edited_draft(self):
        return replace(self.draft, title=self.title.text().strip(), hook=self.hook.text().strip(),
                       motive=self.motive.text().strip(), complication=self.complication.text().strip(),
                       read_aloud=self.read_aloud.toPlainText(), dm_notes=self.dm_notes.toPlainText())

    def update_details(self):
        if self.draft is not None:
            self.details.setPlainText(self._edited_draft().dm_brief(include_roll_log=False))

    def accept_action(self, action):
        if self.draft is None or action not in ("scene", "battle", "scribe"):
            return
        title = self.title.text().strip()
        if not title:
            self.status.setText("Enter an encounter title before using this draft.")
            return
        draft = self._edited_draft()
        try:
            if action == "scene":
                draft.to_scene()
            elif action == "scribe":
                draft.scribe_context()
        except ValueError as exc:
            self.status.setText(str(exc))
            return
        self.result_action = action
        self.result_draft = draft
        self.accept()
