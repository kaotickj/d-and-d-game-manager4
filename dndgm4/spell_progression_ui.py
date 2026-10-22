"""Higher-level spell desk with reviewed permanent-sheet saves."""
from __future__ import annotations

import sqlite3

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFormLayout, QHBoxLayout,
    QLabel, QListWidget, QMessageBox, QPlainTextEdit, QPushButton, QScrollArea,
    QTabWidget, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

from .spell_progression import (
    GROUPS, build_spell_candidate, caster_profiles, load_spell_plan,
    save_spell_candidate, spell_options,
)
from .srd35_spells import SpellCatalog


class SpellProgressionDialog(QDialog):
    def __init__(self, library_repository, creature_id, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_QuitOnClose, False)
        self.repository = library_repository
        self.baseline = library_repository.get(creature_id)
        if self.baseline is None:
            raise ValueError("Choose a saved character before opening spell management.")
        self.profiles = caster_profiles(self.baseline)
        self.plans = {name: load_spell_plan(self.baseline, name) for name in self.profiles}
        self.catalog = SpellCatalog(library_repository.path)
        self.current_class = None
        self.current_level = "0"
        self.saved_creature = None
        self.setWindowTitle("Grimoire | Spell Progression")
        self.resize(880, 780)
        outer = QVBoxLayout(self)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        content = QWidget()
        root = QVBoxLayout(content)
        scroll.setWidget(content)
        outer.addWidget(scroll)
        title = QLabel(f"GRIMOIRE  /  {self.baseline.name}")
        title.setObjectName("pageTitle")
        root.addWidget(title)
        hint = QLabel("Review daily slots and spell selections for class levels 1–20. Saving updates the permanent sheet. Encounter casting and spent slots remain independent.")
        hint.setWordWrap(True)
        root.addWidget(hint)
        row = QHBoxLayout()
        self.class_choice = QComboBox()
        self.class_choice.setAccessibleName("Casting class")
        for name, profile in self.profiles.items():
            self.class_choice.addItem(f"{name} {profile['class_level']}", name)
        row.addWidget(self.class_choice)
        self.level_choice = QComboBox()
        self.level_choice.setAccessibleName("Spell slot level")
        for level in range(10):
            self.level_choice.addItem(f"Spell / slot level {level}", str(level))
        row.addWidget(self.level_choice)
        root.addLayout(row)
        self.slots = QTableWidget(10, 5)
        self.slots.setHorizontalHeaderLabels(["Spell level", "Daily slots", "Domain slots", "Known limit", "Save DC"])
        self.slots.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.slots.setMaximumHeight(255)
        root.addWidget(self.slots)
        self.source = QLabel()
        self.source.setOpenExternalLinks(True)
        self.source.setWordWrap(True)
        root.addWidget(self.source)
        self.editors = {}
        self.tabs = QTabWidget()
        labels = {"known": "Spells known", "prepared": "Daily preparation", "spellbook": "Wizard spellbook", "domain_prepared": "Cleric domain preparation"}
        for group in GROUPS:
            editor = QPlainTextEdit()
            editor.setAccessibleName(labels[group])
            editor.setPlaceholderText("One spell name per line. Repeating a prepared spell uses another slot.")
            self.editors[group] = editor
            self.tabs.addTab(editor, labels[group])
        root.addWidget(self.tabs, 1)
        catalog_row = QHBoxLayout()
        self.options = QComboBox()
        self.options.setAccessibleName("Indexed spells at selected level")
        catalog_row.addWidget(self.options, 1)
        add = QPushButton("Add to Selected Tab")
        add.clicked.connect(self.add_selected)
        catalog_row.addWidget(add)
        root.addLayout(catalog_row)
        note = QLabel("First-level spell names are ready now. Import the SRD spell lists in Encounter Command for higher levels, or enter a spell and record the source you checked. Domain eligibility, specialization and metamagic require DM review.")
        note.setWordWrap(True)
        root.addWidget(note)
        self.custom_review = QPlainTextEdit()
        self.custom_review.setAccessibleName("Custom and domain spell source review")
        self.custom_review.setPlaceholderText("Source / DM review for custom, unindexed or domain spell choices")
        self.custom_review.setMaximumHeight(70)
        root.addWidget(self.custom_review)
        self.review = QCheckBox("I reviewed these spell choices, class limits and source requirements.")
        root.addWidget(self.review)
        self.status = QLabel("Choose a casting class and edit one spell level at a time.")
        self.status.setWordWrap(True)
        outer.addWidget(self.status)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        self.save_button = buttons.addButton("Save Reviewed Spell Plan", QDialogButtonBox.ButtonRole.ActionRole)
        self.save_button.clicked.connect(self.save_reviewed)
        buttons.rejected.connect(self.reject)
        outer.addWidget(buttons)
        self.class_choice.currentIndexChanged.connect(self.change_selection)
        self.level_choice.currentIndexChanged.connect(self.change_selection)
        for editor in self.editors.values():
            editor.textChanged.connect(lambda: self.review.setChecked(False))
        self.custom_review.textChanged.connect(lambda: self.review.setChecked(False))
        self.change_selection()

    def _stash(self):
        if self.current_class is None:
            return
        plan = self.plans[self.current_class]
        for group, editor in self.editors.items():
            plan[group][self.current_level] = [line.strip() for line in editor.toPlainText().splitlines() if line.strip()]
        plan["custom_review"] = self.custom_review.toPlainText()

    def change_selection(self, *_):
        self._stash()
        self.current_class = self.class_choice.currentData()
        self.current_level = self.level_choice.currentData()
        plan = self.plans[self.current_class]
        profile = self.profiles[self.current_class]
        for group, editor in self.editors.items():
            editor.setPlainText("\n".join(plan[group][self.current_level]))
            allowed = (group == "known" if profile["mode"] == "spontaneous" else
                       group == "prepared" or group == "spellbook" and self.current_class == "Wizard" or
                       group == "domain_prepared" and self.current_class == "Cleric")
            self.tabs.setTabEnabled(list(GROUPS).index(group), allowed)
        if not self.tabs.isTabEnabled(self.tabs.currentIndex()):
            self.tabs.setCurrentIndex(next(i for i in range(len(GROUPS)) if self.tabs.isTabEnabled(i)))
        self.custom_review.setPlainText(plan.get("custom_review", ""))
        for level in range(10):
            key = str(level)
            values = [key, str(profile["slots"][key]) if profile["unlocked"][key] else "—",
                      str(profile["domain_slots"][key]), str(profile["known_limits"][key]), str(profile["dc"][key])]
            for col, value in enumerate(values):
                self.slots.setItem(level, col, QTableWidgetItem(value))
        self.slots.resizeColumnsToContents()
        self.source.setText(f'<a href="{profile["source"]}">D&amp;D 3.5 SRD: {self.current_class} progression</a> · Ability score {profile["ability_score"]}. Domain slots are separate from regular slots.')
        self.options.clear()
        self.options.addItems(sorted(spell_options(self.current_class, self.catalog.spells)[self.current_level], key=str.casefold))
        self.review.setChecked(False)

    def add_selected(self):
        name = self.options.currentText()
        if name:
            self.editors[GROUPS[self.tabs.currentIndex()]].appendPlainText(name)

    def save_reviewed(self):
        self._stash()
        plan = self.plans[self.current_class]
        try:
            candidate = build_spell_candidate(self.baseline, self.current_class,
                {group: plan[group] for group in GROUPS}, catalog=self.catalog.spells,
                review_ack=self.review.isChecked(), custom_review=plan.get("custom_review", ""))
            self.saved_creature = save_spell_candidate(self.repository, self.baseline, candidate, catalog=self.catalog.spells)
        except (ValueError, OSError, sqlite3.Error) as exc:
            self.status.setText(str(exc))
            return
        self.baseline = self.saved_creature
        self.plans[self.current_class] = load_spell_plan(self.baseline, self.current_class)
        self.review.setChecked(False)
        self.status.setText("Reviewed spell plan saved. Existing first-level data and live encounter casting state were preserved.")
