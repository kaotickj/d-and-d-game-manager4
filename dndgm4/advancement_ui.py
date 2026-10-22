"""Explicit dice, editable class defaults, and a reviewable level-up draft."""
from __future__ import annotations

import json

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QAbstractItemView, QCheckBox, QComboBox, QDialog, QDialogButtonBox,
    QDoubleSpinBox, QFormLayout, QHBoxLayout, QHeaderView, QLabel, QLineEdit,
    QPlainTextEdit, QPushButton, QScrollArea, QSpinBox,
    QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

from .advancement import (
    advance_character, default_level_choices, default_progression_profile,
    level_up_requirements,
)
from .character_sheet import SKILLS
from .creation import ABILITIES
from .dice import ability_modifier, roll_expression
from .models import Creature


def _label(text: str) -> QLabel:
    label = QLabel(text)
    label.setTextFormat(Qt.TextFormat.PlainText)
    label.setWordWrap(True)
    return label


class ProgressionProfileDialog(QDialog):
    """Gather unmodeled class progression instead of inventing its mechanics."""

    def __init__(self, creature: Creature, parent=None):
        super().__init__(parent)
        self.creature = creature
        self.result_profile = None
        self.setWindowTitle("Class Advancement Profile")
        self.resize(610, 580)
        defaults = default_progression_profile(creature)
        root = QVBoxLayout(self)
        root.addWidget(_label(
            f"Confirm {creature.character_class}'s progression with the DM. "
            "The app will remember these settings for this character's later levels."))
        form = QFormLayout()
        self.hit_die = QSpinBox()
        self.hit_die.setRange(4, 20)
        self.hit_die.setPrefix("d")
        self.hit_die.setValue(defaults["hit_die"])
        self.hit_die.setAccessibleName("Class hit die")
        form.addRow("Hit die", self.hit_die)
        self.skill_points = QSpinBox()
        self.skill_points.setRange(1, 20)
        self.skill_points.setValue(defaults["skill_points"])
        self.skill_points.setAccessibleName("Base skill points per level")
        form.addRow("Skill points before INT", self.skill_points)
        self.bab = QComboBox()
        self.bab.addItem("Choose progression…", "")
        self.bab.addItem("Full (+1 per class level)", "full")
        self.bab.addItem("Three quarters (as Cleric)", "three_quarters")
        self.bab.addItem("Half (as Wizard)", "half")
        self.bab.setAccessibleName("Base attack progression")
        if defaults.get("bab_progression"):
            self.bab.setCurrentIndex(self.bab.findData(defaults["bab_progression"]))
        form.addRow("Base attack bonus", self.bab)
        saves = QHBoxLayout()
        self.good_saves = {}
        for name, title in (("fort", "Fortitude"), ("ref", "Reflex"), ("will", "Will")):
            control = QCheckBox(title)
            control.setChecked(name in defaults.get("good_saves", []))
            control.setAccessibleName("Good " + title + " progression")
            self.good_saves[name] = control
            saves.addWidget(control)
        form.addRow("Good saves", saves)
        root.addLayout(form)
        root.addWidget(_label("Class skills — one skill name per line"))
        self.class_skills = QPlainTextEdit("\n".join(defaults.get("class_skills", [])))
        self.class_skills.setAccessibleName("Class skills in advancement profile")
        root.addWidget(self.class_skills, 1)
        self.review_ack = QCheckBox("I confirmed these progression settings with the DM.")
        root.addWidget(self.review_ack)
        self.status = _label("Choose a base attack progression and confirm the class settings.")
        root.addWidget(self.status)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel)
        self.continue_button = buttons.addButton("Continue", QDialogButtonBox.ButtonRole.AcceptRole)
        buttons.rejected.connect(self.reject)
        self.continue_button.clicked.connect(self.confirm_profile)
        root.addWidget(buttons)

    def confirm_profile(self):
        if not self.bab.currentData():
            self.status.setText("Choose the class's base attack progression.")
            return
        if not self.review_ack.isChecked():
            self.status.setText("Confirm the progression settings with the DM before continuing.")
            return
        profile = {
            "hit_die": self.hit_die.value(), "skill_points": self.skill_points.value(),
            "bab_progression": self.bab.currentData(),
            "good_saves": [name for name, control in self.good_saves.items() if control.isChecked()],
            "class_skills": [line.strip() for line in self.class_skills.toPlainText().splitlines()
                             if line.strip()],
        }
        try:
            level_up_requirements(self.creature, profile=profile)
        except ValueError as exc:
            self.status.setText(str(exc))
            return
        self.result_profile = profile
        self.accept()


class LevelUpDialog(QDialog):
    """A pure character draft; only the caller persists an accepted result."""

    def __init__(self, creature: Creature, parent=None, *, profile=None):
        super().__init__(parent)
        self.original = creature
        self.profile = profile
        self.requirements = level_up_requirements(creature, profile=profile)
        self.result_creature = None
        self._hp_roll_detail = ""
        self._updating = False
        self._preview_creature = None
        self.setWindowTitle(f"Level Up — {creature.name}")
        self.resize(820, 820)
        self.setMinimumSize(620, 520)
        root = QVBoxLayout(self)
        root.addWidget(_label(
            f"{creature.name} · {self.requirements['class_name']} · "
            f"Level {creature.level} → {self.requirements['next_level']}"))
        root.addWidget(_label("Roll hit points and choose the new level's training, or fill the "
                              "class defaults and edit them. Review the result before saving."))
        self.mode = QComboBox()
        self.mode.addItem("Guided choices", "guided")
        self.mode.addItem("Use class default build", "default")
        self.mode.setAccessibleName("Level-up build method")
        method = QHBoxLayout()
        method.addWidget(self.mode, 1)
        self.defaults_button = QPushButton("Apply Class Defaults")
        self.defaults_button.clicked.connect(self.apply_defaults)
        method.addWidget(self.defaults_button)
        root.addLayout(method)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        page = QWidget()
        details = QVBoxLayout(page)
        scroll.setWidget(page)
        root.addWidget(scroll, 1)
        form = QFormLayout()
        hp = QHBoxLayout()
        self.hp_roll = QSpinBox()
        self.hp_roll.setRange(0, self.requirements["hit_die"])
        self.hp_roll.setSpecialValueText("Roll or enter result")
        self.hp_roll.setAccessibleName("Hit-point die result before Constitution modifier")
        hp.addWidget(self.hp_roll)
        self.roll_button = QPushButton(f"Roll d{self.requirements['hit_die']} for HP")
        self.roll_button.clicked.connect(self.roll_hit_points)
        hp.addWidget(self.roll_button)
        form.addRow("Hit-point die", hp)
        self.hp_detail = _label("The Constitution modifier is added after the die roll.")
        form.addRow("", self.hp_detail)
        self.ability = QComboBox()
        self.ability.addItem("Choose an ability…", "")
        for name in ABILITIES:
            self.ability.addItem(f"{name.title()} ({getattr(creature, name)} → "
                                 f"{getattr(creature, name) + 1})", name)
        self.ability.setAccessibleName("Ability score to increase at this level")
        if self.requirements["ability_due"]:
            form.addRow("Ability increase (+1)", self.ability)
        else:
            self.ability.hide()
        details.addLayout(form)

        self.skill_summary = _label("")
        details.addWidget(self.skill_summary)
        known = self.requirements.get("skills", {})
        class_skills = set(self.requirements.get("class_skills", []))
        names = sorted(set(SKILLS) | set(known) | class_skills,
                       key=lambda name: (name not in class_skills, name))
        self.skills = QTableWidget(len(names), 4)
        self.skills.setAccessibleName("Skill rank increases for this level")
        self.skills.setHorizontalHeaderLabels(["Skill", "Training", "Existing ranks", "Add ranks"])
        self.skills.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.skills.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        for column in (1, 2, 3):
            self.skills.horizontalHeader().setSectionResizeMode(column, QHeaderView.ResizeMode.ResizeToContents)
        self.skills.verticalHeader().hide()
        self.skills.verticalHeader().setDefaultSectionSize(42)
        self.skills.setMinimumHeight(260)
        self.skill_fields = {}
        for row, name in enumerate(names):
            in_class = name in class_skills
            self.skills.setItem(row, 0, QTableWidgetItem(name))
            self.skills.setItem(row, 1, QTableWidgetItem("Class" if in_class else "Cross-class"))
            self.skills.setItem(row, 2, QTableWidgetItem(f"{known.get(name, 0) / 2:g}"))
            control = QDoubleSpinBox()
            control.setDecimals(1)
            control.setMinimumWidth(92)
            control.setStyleSheet("QDoubleSpinBox { padding: 4px 8px; border-radius: 4px; }")
            control.setSingleStep(1 if in_class else 0.5)
            cap = self.requirements["max_class_ticks" if in_class else "max_cross_ticks"]
            control.setRange(0, max(0, cap - known.get(name, 0)) / 2)
            control.setAccessibleName("Add " + name + " ranks")
            control.valueChanged.connect(self.update_preview)
            self.skills.setCellWidget(row, 3, control)
            self.skill_fields[name] = control
        details.addWidget(self.skills)

        slots = self.requirements.get("feat_slots", {})
        available_slots = sum(slots.values())
        slot_details = ", ".join(f"{count} {name.replace('_', ' ')}" for name, count in slots.items() if count)
        details.addWidget(_label(
            f"New feat selections: {available_slots}"
            + (f" ({slot_details})" if slot_details else "")
            + ". Enter one feat per line; the app checks its supported prerequisites."))
        feat_picker = QHBoxLayout()
        self.feat_picker = QComboBox()
        self.feat_picker.addItem("Choose a feat…", "")
        suggestions = list(self.requirements.get("feat_options", []))
        for slot, options in self.requirements.get("bonus_feat_options", {}).items():
            if slots.get(slot):
                suggestions.extend(options)
        for name in sorted(set(suggestions)):
            self.feat_picker.addItem(name, name)
        self.feat_picker.setAccessibleName("Suggested feat for this level")
        feat_picker.addWidget(self.feat_picker, 1)
        self.add_feat_button = QPushButton("Add Feat")
        self.add_feat_button.clicked.connect(self.add_feat)
        feat_picker.addWidget(self.add_feat_button)
        details.addLayout(feat_picker)
        self.feats = QPlainTextEdit()
        self.feats.setMaximumHeight(92)
        self.feats.setAccessibleName("New feats selected this level")
        self.feats.setPlaceholderText("One new feat per line")
        details.addWidget(self.feats)
        self.feats.setEnabled(available_slots > 0)
        self.feat_picker.setEnabled(available_slots > 0)
        self.add_feat_button.setEnabled(available_slots > 0)
        self.feat_details = {}
        self.feat_detail_rows = {}
        for request in self.requirements.get("feat_detail_requests", []):
            row = QWidget()
            row_layout = QVBoxLayout(row)
            row_layout.setContentsMargins(0, 0, 0, 0)
            row_layout.addWidget(_label(request["label"]))
            control = QLineEdit()
            control.setAccessibleName(request["label"])
            control.textChanged.connect(self.update_preview)
            row_layout.addWidget(control)
            self.feat_details[request["feat"]] = control
            self.feat_detail_rows[request["feat"]] = row
            details.addWidget(row)

        choices = QFormLayout()
        choices.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)
        self.class_choices = {}
        for request in self.requirements.get("choice_requests", []):
            options = request.get("options", [])
            if options:
                control = QComboBox()
                control.addItem("Choose…", "")
                for option in options:
                    control.addItem(option, option)
                control.currentIndexChanged.connect(self.update_preview)
            else:
                control = QLineEdit()
                control.textChanged.connect(self.update_preview)
            control.setAccessibleName(request["label"])
            self.class_choices[request["key"]] = control
            choices.addRow(request["label"], control)
        details.addLayout(choices)
        if self.requirements.get("automatic_features"):
            details.addWidget(_label("Class features this level: " + "; ".join(
                self.requirements["automatic_features"])))
        details.addWidget(_label("Additional class features / DM adjustments"))
        self.class_notes = QPlainTextEdit()
        self.class_notes.setMaximumHeight(100)
        self.class_notes.setAccessibleName("Additional class features and DM adjustments")
        self.class_notes.setPlaceholderText("Record other features gained this level or agreed DM adjustments.")
        details.addWidget(self.class_notes)
        self.spell_notes = QPlainTextEdit()
        self.spell_notes.setMaximumHeight(105)
        self.spell_notes.setAccessibleName("Spell and power choices for this level")
        self.spell_notes.setPlaceholderText("Record new spells, spells known, or other casting choices.")
        self.spell_notes.setVisible(self.requirements.get("spell_review_required", False))
        if self.requirements.get("spell_review_required"):
            details.addWidget(_label("Spell progression choices — confirm with the DM"))
        details.addWidget(self.spell_notes)
        review = self.requirements.get("manual_review", [])
        if review:
            details.addWidget(_label("\n".join(review)))
        self.review_ack = QCheckBox("I reviewed the class and spell choices with the DM.")
        self.review_ack.setVisible(bool(review))
        details.addWidget(self.review_ack)

        self.preview = QPlainTextEdit()
        self.preview.setReadOnly(True)
        self.preview.setMaximumHeight(150)
        self.preview.setAccessibleName("Level-up result preview")
        root.addWidget(self.preview)
        self.status = _label("")
        root.addWidget(self.status)
        self.buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel)
        self.save_button = self.buttons.addButton("Save Level Up", QDialogButtonBox.ButtonRole.AcceptRole)
        self.buttons.rejected.connect(self.reject)
        self.save_button.clicked.connect(self.save_level)
        root.addWidget(self.buttons)
        self.mode.currentIndexChanged.connect(self.change_mode)
        self.hp_roll.valueChanged.connect(self.entered_hp)
        self.ability.currentIndexChanged.connect(self.update_preview)
        self.feats.textChanged.connect(self.update_preview)
        self.spell_notes.textChanged.connect(self.update_preview)
        self.class_notes.textChanged.connect(self.update_preview)
        self.review_ack.toggled.connect(self.update_preview)
        self.update_preview()

    def change_mode(self):
        if self.mode.currentData() == "default":
            self.apply_defaults()

    def apply_defaults(self):
        try:
            choices = default_level_choices(self.original, profile=self.profile)
        except ValueError as exc:
            self.status.setText(str(exc))
            return
        self._updating = True
        try:
            ability = self.ability.findData(choices.get("ability_increase", ""))
            self.ability.setCurrentIndex(max(0, ability))
            increases = choices.get("skill_increases", {})
            for name, control in self.skill_fields.items():
                control.setValue(increases.get(name, 0) / 2)
            self.feats.setPlainText("\n".join(choices.get("feats", [])))
            for feat, control in self.feat_details.items():
                control.setText(choices.get("feat_details", {}).get(feat, ""))
            for key, control in self.class_choices.items():
                value = choices.get("class_choices", {}).get(key, "")
                if isinstance(control, QComboBox):
                    control.setCurrentIndex(max(0, control.findData(value)))
                else:
                    control.setText(value)
            self.spell_notes.setPlainText(choices.get("spell_notes", ""))
            self.class_notes.setPlainText(choices.get("class_notes", ""))
            self.review_ack.setChecked(bool(choices.get("review_ack", False)))
        finally:
            self._updating = False
        self.update_preview()

    def roll_hit_points(self):
        result = roll_expression(f"1d{self.requirements['hit_die']}")
        self._updating = True
        self.hp_roll.setValue(result.total)
        self._updating = False
        self._hp_roll_detail = f"{result.notation} {result.detail}"
        self.hp_detail.setText(self._hp_roll_detail)
        self.update_preview()

    def entered_hp(self):
        if self._updating:
            return
        self._hp_roll_detail = f"Entered d{self.requirements['hit_die']} result: {self.hp_roll.value()}"
        self.hp_detail.setText(self._hp_roll_detail)
        self.update_preview()

    def add_feat(self):
        value = self.feat_picker.currentData()
        if not value:
            return
        current = [line.strip() for line in self.feats.toPlainText().splitlines() if line.strip()]
        if value not in current:
            self.feats.setPlainText("\n".join(current + [value]))

    def choices(self):
        feats = [line.strip() for line in self.feats.toPlainText().splitlines() if line.strip()]
        selections = {
            "hp_roll": self.hp_roll.value(), "hp_roll_detail": self._hp_roll_detail,
            "ability_increase": self.ability.currentData() if self.requirements["ability_due"] else "",
            "skill_increases": {name: round(control.value() * 2)
                                for name, control in self.skill_fields.items() if control.value()},
            "feats": feats,
            "feat_details": {feat: control.text().strip() for feat, control in self.feat_details.items()
                             if feat in feats and control.text().strip()},
            "class_choices": {key: control.currentData() if isinstance(control, QComboBox)
                              else control.text().strip() for key, control in self.class_choices.items()},
            "spell_notes": self.spell_notes.toPlainText().strip(),
            "class_notes": self.class_notes.toPlainText().strip(),
            "review_ack": self.review_ack.isChecked(),
        }
        if self.profile is not None:
            selections["profile"] = self.profile
        return selections

    def update_preview(self):
        if self._updating:
            return
        self._preview_creature = None
        choices = self.choices()
        for feat, row in self.feat_detail_rows.items():
            row.setVisible(feat in choices["feats"])
        class_skills = set(self.requirements.get("class_skills", []))
        spent = sum(value / 2 if name in class_skills else value
                    for name, value in choices["skill_increases"].items())
        intelligence = self.original.intelligence + int(choices["ability_increase"] == "intelligence")
        points = max(1, self.requirements["profile"]["skill_points"] + ability_modifier(intelligence))
        points += int(self.original.race_type == "Human")
        self.skill_summary.setText(
            f"Skill points: {spent:g} / {points} spent. Class skills cost 1 point per rank; "
            "cross-class skills cost 1 point per half rank.")
        try:
            candidate = advance_character(self.original, choices)
        except ValueError as exc:
            self.preview.setPlainText(
                f"Level {self.original.level} → {self.requirements['next_level']}\n"
                f"Current maximum HP: {self.original.max_hit_points}\n"
                "Complete the choices to preview the new character.")
            self.status.setText(str(exc))
            self.save_button.setEnabled(False)
            return
        self._preview_creature = candidate
        lines = [f"Level {self.original.level} → {candidate.level}",
                 f"Maximum HP: {self.original.max_hit_points} → {candidate.max_hit_points}"]
        progression = json.loads(candidate.sheet_json).get("progression", {})
        if "base_attack_bonus" in progression:
            lines.append(f"Base attack bonus: +{progression['base_attack_bonus']}")
        saves = progression.get("base_saves", {})
        if all(name in saves for name in ("fort", "ref", "will")):
            lines.append(f"Base saves: Fort +{saves['fort']} / Ref +{saves['ref']} / Will +{saves['will']}")
        for ability in ABILITIES:
            before, after = getattr(self.original, ability), getattr(candidate, ability)
            if before != after:
                lines.append(f"{ability.title()}: {before} → {after}")
        if choices["feats"]:
            lines.append("New feats: " + ", ".join(choices["feats"]))
        for feat, detail in choices["feat_details"].items():
            lines.append(f"{feat}: {detail}")
        if choices["class_notes"]:
            lines.append("Class notes: " + choices["class_notes"])
        if any(choices["class_choices"].values()):
            lines.append("Class choices: " + "; ".join(str(value) for value in
                                                     choices["class_choices"].values() if value))
        self.preview.setPlainText("\n".join(lines))
        self.status.setText("Ready. Review the level-up draft, then save.")
        self.save_button.setEnabled(True)

    def save_level(self):
        self.update_preview()
        if self._preview_creature is None:
            return
        self.result_creature = self._preview_creature
        self.accept()
