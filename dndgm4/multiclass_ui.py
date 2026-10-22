"""Explicit history confirmation and reviewed core multiclass advancement."""
from __future__ import annotations

import json
import sqlite3

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFormLayout, QHBoxLayout,
    QHeaderView, QLabel, QLineEdit, QPlainTextEdit, QPushButton, QScrollArea,
    QSpinBox, QTableWidget, QTableWidgetItem, QTabWidget, QVBoxLayout, QWidget,
)

from .advancement import _SAFE_FEATS, _WIZARD_FEATS
from .character_sheet import SKILLS
from .creation import ABILITIES
from .dice import ability_modifier, roll_expression
from .multiclass import (
    CLASSES, REVIEW, SOURCE, advance_multiclass, class_history,
    combined_progression, default_multiclass_choices, establish_history, multiclass_requirements,
    save_multiclass_candidate, _sheet,
)


def _label(text):
    widget = QLabel(text)
    widget.setWordWrap(True)
    widget.setTextFormat(Qt.TextFormat.PlainText)
    return widget


def _button(text, callback):
    button = QPushButton(text)
    button.clicked.connect(callback)
    return button


class MulticlassDialog(QDialog):
    record_saved = pyqtSignal(object)

    def __init__(self, library_repository, creature_id, parent=None):
        super().__init__(parent)
        self.repository = library_repository
        self.baseline = library_repository.get(creature_id)
        if self.baseline is None:
            raise ValueError("Choose a saved character before multiclass advancement.")
        _sheet(self.baseline)
        self.result_creature = None
        self._candidate = None
        self._requirements = None
        self._loading = True
        self._hp_detail = ""
        self.setAttribute(Qt.WidgetAttribute.WA_QuitOnClose, False)
        self.setWindowTitle(f"Multiclass History & Advancement · {self.baseline.name}")
        self.resize(1050, 820)
        self.setMinimumSize(760, 540)
        root = QVBoxLayout(self)
        heading = _label("MULTICLASS HISTORY & ADVANCEMENT")
        heading.setObjectName("pageTitle")
        root.addWidget(heading)
        self.summary = _label("")
        root.addWidget(self.summary)
        root.addWidget(_label(REVIEW))
        self.tabs = QTabWidget()
        root.addWidget(self.tabs, 1)
        self._build_history()
        self._build_advance()
        self._build_review()
        self.status = _label("")
        self.status.setAccessibleName("Multiclass advancement status")
        root.addWidget(self.status)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)
        self._loading = False
        self._load_character()

    def _page(self, name):
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        body = QWidget()
        layout = QVBoxLayout(body)
        scroll.setWidget(body)
        self.tabs.addTab(scroll, name)
        return layout

    def _build_history(self):
        layout = self._page("1 · Confirm History")
        layout.addWidget(_label("Record existing class totals. They must sum to the saved character level. "
                                "Confirming history recalculates base BAB/saves, while keeping existing HP, skills, feats and biography. "
                                "No class acquisition order is invented."))
        self.history_table = QTableWidget(len(CLASSES), 2)
        self.history_table.setHorizontalHeaderLabels(("Class", "Existing class levels"))
        self.history_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.history_table.setMinimumHeight(220)
        self.history_levels = {}
        for row, name in enumerate(CLASSES):
            item = QTableWidgetItem(name)
            item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self.history_table.setItem(row, 0, item)
            spin = QSpinBox()
            spin.setRange(0, 20)
            spin.setAccessibleName(name + " existing class levels")
            spin.valueChanged.connect(self._invalidate)
            self.history_levels[name] = spin
            self.history_table.setCellWidget(row, 1, spin)
        layout.addWidget(self.history_table)
        layout.addWidget(_label("Chronological classes, optional · one class name per character level; leave blank if unknown"))
        self.level_order = QPlainTextEdit()
        self.level_order.setMaximumHeight(90)
        self.level_order.textChanged.connect(self._invalidate)
        layout.addWidget(self.level_order)
        layout.addWidget(_label("Expert's ten chosen class skills, if present · one supported skill per line"))
        self.history_expert = QPlainTextEdit()
        self.history_expert.setMaximumHeight(90)
        self.history_expert.textChanged.connect(self._invalidate)
        layout.addWidget(self.history_expert)
        self.history_notes = QLineEdit()
        self.history_notes.setMaxLength(4000)
        self.history_notes.setPlaceholderText("DM review of existing history, restrictions and any unknown acquisition order")
        self.history_notes.textChanged.connect(self._invalidate)
        layout.addWidget(self.history_notes)
        self.no_racial_ack = QCheckBox("I confirmed that total level contains class levels only, with no racial Hit Dice or level adjustment.")
        self.history_ack = QCheckBox("I confirmed this per-class history and class restrictions with the DM.")
        for check in (self.no_racial_ack, self.history_ack):
            check.toggled.connect(self._invalidate)
            layout.addWidget(check)
        layout.addWidget(_button("Preview Confirmed History", self.preview_history))

    def _build_advance(self):
        layout = self._page("2 · Add Class Level")
        self.requirement_summary = _label("Confirm and save the existing history first.")
        layout.addWidget(self.requirement_summary)
        form = QFormLayout()
        self.selected_class = QComboBox()
        self.selected_class.addItems(CLASSES)
        self.selected_class.currentTextChanged.connect(self.load_requirements)
        form.addRow("Class to advance", self.selected_class)
        self.hp_roll = QSpinBox()
        self.hp_roll.setRange(0, 20)
        self.hp_roll.setSpecialValueText("Roll or enter HP")
        self.hp_roll.valueChanged.connect(self._hp_edited)
        hp_row = QHBoxLayout()
        hp_row.addWidget(self.hp_roll)
        hp_row.addWidget(_button("Roll Chosen Class Hit Die", self.roll_hp))
        form.addRow("Hit points", hp_row)
        self.ability = QComboBox()
        self.ability.addItem("No ability increase", "")
        for ability in ABILITIES:
            self.ability.addItem(ability.title(), ability)
        self.ability.currentIndexChanged.connect(self._ability_changed)
        form.addRow("Total-level ability increase", self.ability)
        self.weapon_focus = QLineEdit()
        self.weapon_focus.setMaxLength(120)
        self.weapon_focus.textChanged.connect(self._invalidate)
        form.addRow("Weapon Focus weapon (confirm proficiency)", self.weapon_focus)
        layout.addLayout(form)
        self.feat_form = QFormLayout()
        layout.addLayout(self.feat_form)
        self.feat_widgets = {}
        self.choice_form = QFormLayout()
        layout.addLayout(self.choice_form)
        self.choice_widgets = {}
        layout.addWidget(_label("Joining Expert? Choose ten supported class skills, one per line. Existing Expert choices remain fixed."))
        self.advance_expert = QPlainTextEdit()
        self.advance_expert.setMaximumHeight(80)
        self.advance_expert.textChanged.connect(self._expert_changed)
        layout.addWidget(self.advance_expert)
        layout.addWidget(_button("Load / Refresh Class Requirements", self.load_requirements))
        self.skill_budget = _label("")
        layout.addWidget(self.skill_budget)
        self.skill_table = QTableWidget(len(SKILLS), 5)
        self.skill_table.setHorizontalHeaderLabels(("Skill", "Saved ranks", "Cost this class", "New skill points", "Rank cap"))
        self.skill_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.skill_table.setMinimumHeight(220)
        self.skill_points = {}
        for row, skill in enumerate(SKILLS):
            item = QTableWidgetItem(skill)
            item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self.skill_table.setItem(row, 0, item)
            spin = QSpinBox()
            spin.setRange(0, 100)
            spin.valueChanged.connect(self._skills_changed)
            spin.setAccessibleName(skill + " new skill points")
            self.skill_points[skill] = spin
            self.skill_table.setCellWidget(row, 3, spin)
        layout.addWidget(self.skill_table)
        layout.addWidget(_button("Suggest Editable Skill Allocation", self.suggest_skills))
        layout.addWidget(_label("Class features and choices for this class level · required, DM-reviewed"))
        self.class_notes = QPlainTextEdit()
        self.class_notes.setMaximumHeight(100)
        self.class_notes.textChanged.connect(self._invalidate)
        layout.addWidget(self.class_notes)
        layout.addWidget(_label("Spells / powers review · required for supported casting levels; separate spell plans remain intact"))
        self.spell_notes = QPlainTextEdit()
        self.spell_notes.setMaximumHeight(100)
        self.spell_notes.textChanged.connect(self._invalidate)
        layout.addWidget(self.spell_notes)
        self.restriction_notes = QLineEdit()
        self.restriction_notes.setMaxLength(4000)
        self.restriction_notes.setPlaceholderText("Required: XP or milestone eligibility, alignment, class re-entry, prerequisites and DM exceptions")
        self.restriction_notes.textChanged.connect(self._invalidate)
        layout.addWidget(self.restriction_notes)
        self.advance_ack = QCheckBox("I reviewed this level's class features, spell choices, XP/milestone eligibility and multiclass restrictions with the DM.")
        self.advance_ack.toggled.connect(self._invalidate)
        layout.addWidget(self.advance_ack)
        self.preview_level_button = _button("Preview Added Class Level", self.preview_level)
        layout.addWidget(self.preview_level_button)

    def _build_review(self):
        layout = self._page("3 · Review & Save")
        self.preview_text = QPlainTextEdit()
        self.preview_text.setReadOnly(True)
        self.preview_text.setAccessibleName("Multiclass before and after preview")
        layout.addWidget(self.preview_text, 1)
        self.save_ack = QCheckBox("I reviewed this exact before/after preview and approve saving it to the permanent character.")
        self.save_ack.toggled.connect(self._sync_save)
        layout.addWidget(self.save_ack)
        self.save_button = _button("Save Reviewed Character", self.save_reviewed)
        self.save_button.setEnabled(False)
        layout.addWidget(self.save_button)

    @staticmethod
    def _lines(editor):
        return [line.strip() for line in editor.toPlainText().splitlines() if line.strip()]

    def _invalidate(self, *_):
        if self._loading:
            return
        self._candidate = None
        self.save_ack.setChecked(False)
        self.save_button.setEnabled(False)
        self.preview_text.clear()

    def _sync_save(self, *_):
        self.save_button.setEnabled(self._candidate is not None and self.save_ack.isChecked())

    def _error(self, error):
        self.status.setText(str(error))
        return False

    def _load_character(self):
        self._loading = True
        sheet = json.loads(self.baseline.sheet_json) if self.baseline.sheet_json else {}
        try:
            levels = class_history(self.baseline)
        except ValueError:
            levels = {}
        for name, spin in self.history_levels.items():
            spin.setValue(levels.get(name, 0))
        baseline = sheet.get("multiclass_baseline", {})
        order = baseline.get("level_order") or []
        if order:
            order = list(order)
            for entry in sheet.get("advancement_history", []):
                if entry.get("from_level", -1) >= baseline.get("total_level", self.baseline.level):
                    order.append(entry.get("class", ""))
            if len(order) != self.baseline.level:
                order = []
        self.level_order.setPlainText("\n".join(order))
        skills = sheet.get("multiclass_class_skills", {}).get("Expert", sheet.get("custom_class_skills", []) if "Expert" in levels else [])
        self.history_expert.setPlainText("\n".join(skills))
        self.advance_expert.setPlainText("\n".join(skills))
        self.history_notes.setText(baseline.get("review_notes", ""))
        self.history_ack.setChecked(False)
        self.no_racial_ack.setChecked(False)
        xp = sheet.get("experience_points")
        xp_text = f" · recorded XP {xp:,}" if type(xp) is int and xp >= 0 else " · XP/milestone eligibility requires DM review"
        self.summary.setText(f"{self.baseline.name} · {self.baseline.character_class} · total level {self.baseline.level} · max HP {self.baseline.max_hit_points}{xp_text}")
        if levels:
            self.selected_class.setCurrentText(next(iter(levels)))
        self._loading = False
        self._invalidate()
        self.load_requirements()

    def preview_history(self):
        self._invalidate()
        try:
            levels = {name: spin.value() for name, spin in self.history_levels.items() if spin.value()}
            candidate = establish_history(self.baseline, levels,
                         expert_skills=self._lines(self.history_expert) if "Expert" in levels else None,
                         level_order=self._lines(self.level_order) or None, review_ack=self.history_ack.isChecked(),
                         no_racial_hd_ack=self.no_racial_ack.isChecked(), review_notes=self.history_notes.text())
            return self._show_candidate(candidate, "Confirm existing class history")
        except (ValueError, sqlite3.Error) as error:
            return self._error(error)

    def _clear_form(self, form):
        while form.rowCount():
            form.removeRow(0)

    def load_requirements(self, *_):
        if self._loading:
            return False
        self._invalidate()
        try:
            selected = self.selected_class.currentText()
            expert = self._lines(self.advance_expert) or None
            req = multiclass_requirements(self.baseline, selected, expert_skills=expert)
            defaults = default_multiclass_choices(self.baseline, selected, expert_skills=expert)
            self._loading = True
            self._requirements = req
            self._clear_form(self.feat_form)
            self._clear_form(self.choice_form)
            self.feat_widgets, self.choice_widgets = {}, {}
            for slot, count in req["feat_slots"].items():
                if not count:
                    continue
                combo = QComboBox()
                combo.addItem("Choose a supported feat…", "")
                for feat in req["bonus_feat_options"].get(slot, sorted(_SAFE_FEATS | set(_WIZARD_FEATS))):
                    combo.addItem(feat, feat)
                choice = (defaults["feat_selections"].get(slot) or [""])[0]
                combo.setCurrentIndex(max(0, combo.findData(choice)))
                combo.currentIndexChanged.connect(self._invalidate)
                self.feat_widgets[slot] = combo
                self.feat_form.addRow(slot.replace("_", " ").title(), combo)
            for request in req["choice_requests"]:
                if request["options"]:
                    widget = QComboBox()
                    widget.addItem("Choose…", "")
                    for value in request["options"]:
                        widget.addItem(value, value)
                    widget.setCurrentIndex(max(0, widget.findData(defaults["class_choices"].get(request["key"], ""))))
                    widget.currentIndexChanged.connect(self._invalidate)
                else:
                    widget = QLineEdit(defaults["class_choices"].get(request["key"], ""))
                    widget.setMaxLength(4000)
                    widget.textChanged.connect(self._invalidate)
                self.choice_widgets[request["key"]] = widget
                self.choice_form.addRow(request["label"], widget)
            self.hp_roll.setRange(0, req["hit_die"])
            self.hp_roll.setValue(0)
            self._hp_detail = ""
            self.ability.setEnabled(req["ability_due"])
            self.ability.setCurrentIndex(1 if req["ability_due"] else 0)
            self.advance_ack.setChecked(False)
            self.requirement_summary.setText(f"Total level {self.baseline.level} → {req['character_level']}; {selected} class level → {req['class_level']}. "
                f"Roll d{req['hit_die']}; combined BAB +{req['progression']['base_attack_bonus']}. "
                "A new class grants ordinary additional-level skill points and rolled HP, without ×4 points or maximum first-level HP.")
            for row, skill in enumerate(SKILLS):
                current = skill in req["current_class_skills"]
                cap = req["character_level"] + 3 if skill in req["class_skill_union"] else (req["character_level"] + 3) / 2
                texts = {1: f"{req['skills'].get(skill, 0) / 2:g}", 2: "1 point = 1 rank" if current else "1 point = ½ rank", 4: f"{cap:g}"}
                for column, value in texts.items():
                    item = QTableWidgetItem(value)
                    item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                    self.skill_table.setItem(row, column, item)
                self.skill_points[skill].setValue(0)
            self.preview_level_button.setEnabled(True)
            self._loading = False
            self.suggest_skills()
            self.status.setText("Review the selected class's choices, record an HP roll, and preview before saving.")
            return True
        except (ValueError, sqlite3.Error) as error:
            self._loading = False
            self._requirements = None
            self.preview_level_button.setEnabled(False)
            self.requirement_summary.setText(str(error))
            return self._error(error)

    def _budget(self):
        req = self._requirements
        return req["skill_points"] + (ability_modifier(self.baseline.intelligence + 1) - ability_modifier(self.baseline.intelligence)
                                    if self.ability.currentData() == "intelligence" else 0)

    def _skills_changed(self, *_):
        if self._loading:
            return
        self._invalidate()
        if self._requirements:
            self.skill_budget.setText(f"New skill points: {sum(spin.value() for spin in self.skill_points.values())} / {self._budget()}. "
                                      "Cost follows the class being advanced; rank cap uses the union of all your classes.")

    def _ability_changed(self, *_):
        self._skills_changed()

    def _expert_changed(self):
        if self._loading:
            return
        self._invalidate()
        self._requirements = None
        self.preview_level_button.setEnabled(False)
        self.status.setText("Reload class requirements after editing Expert skills.")

    def suggest_skills(self):
        if not self._requirements:
            return False
        self._invalidate()
        req = self._requirements
        current, union = set(req["current_class_skills"]), set(req["class_skill_union"])
        ranks, allocations, left = dict(req["skills"]), {}, self._budget()
        order = list(dict.fromkeys(req["current_class_skills"] + list(SKILLS)))
        while left:
            skill = next((name for name in order if ranks.get(name, 0) + (2 if name in current else 1) <=
                          (2 * (req["character_level"] + 3) if name in union else req["character_level"] + 3)), None)
            if skill is None:
                return self._error("No supported skill has room for the remaining points.")
            ranks[skill] = ranks.get(skill, 0) + (2 if skill in current else 1)
            allocations[skill] = allocations.get(skill, 0) + 1
            left -= 1
        self._loading = True
        for skill, spin in self.skill_points.items():
            spin.setValue(allocations.get(skill, 0))
        self._loading = False
        self._skills_changed()
        return True

    def _hp_edited(self, *_):
        self._hp_detail = "Entered HP die face; DM reviewed"
        self._invalidate()

    def roll_hp(self):
        if not self._requirements:
            return self._error("Load valid class requirements first.")
        result = roll_expression(f"1d{self._requirements['hit_die']}")
        self.hp_roll.setValue(result.total)
        self._hp_detail = f"{result.notation}: {result.detail}"
        return True

    def preview_level(self):
        self._invalidate()
        if not self._requirements:
            return self._error("Confirm and save history, then load class requirements.")
        try:
            req = self._requirements
            selected = self.selected_class.currentText()
            if selected != req["selected_class"]:
                raise ValueError("Reload requirements after selecting another class.")
            choices = {"hp_roll": self.hp_roll.value(), "hp_roll_detail": self._hp_detail,
                "ability_increase": self.ability.currentData(),
                "skill_increases": {skill: spin.value() * (2 if skill in req["current_class_skills"] else 1)
                                    for skill, spin in self.skill_points.items() if spin.value()},
                "feat_selections": {slot: [combo.currentData()] for slot, combo in self.feat_widgets.items()},
                "feat_details": {"Weapon Focus": self.weapon_focus.text()} if self.weapon_focus.text().strip() and
                    any(combo.currentData() == "Weapon Focus" for combo in self.feat_widgets.values()) else {},
                "expert_skills": self._lines(self.advance_expert) or None,
                "class_choices": {key: widget.currentData() if isinstance(widget, QComboBox) else widget.text()
                                  for key, widget in self.choice_widgets.items()},
                "class_notes": self.class_notes.toPlainText(), "spell_notes": self.spell_notes.toPlainText(),
                "restriction_notes": self.restriction_notes.text(), "review_ack": self.advance_ack.isChecked()}
            candidate = advance_multiclass(self.baseline, selected, choices)
            return self._show_candidate(candidate, "Add one reviewed class level")
        except (ValueError, sqlite3.Error) as error:
            return self._error(error)

    def _show_candidate(self, candidate, title):
        before = json.loads(self.baseline.sheet_json) if self.baseline.sheet_json else {}
        after = json.loads(candidate.sheet_json)
        progression = after["progression"]
        try:
            old_progression = combined_progression(class_history(self.baseline))
        except ValueError:
            old_progression = None
        old_bab = f"+{old_progression['base_attack_bonus']}" if old_progression else "unconfirmed"
        def saves_text(values):
            return ", ".join(f"{label} +{values[key]}" for key, label in (("fort", "Fort"), ("ref", "Ref"), ("will", "Will")))
        old_saves = saves_text(old_progression["base_saves"]) if old_progression else "unconfirmed"
        lines = [title, "", f"Class history: {self.baseline.character_class} → {candidate.character_class}",
                 f"Total character level: {self.baseline.level} → {candidate.level}",
                 f"Maximum HP: {self.baseline.max_hit_points} → {candidate.max_hit_points}",
                 f"Combined BAB: {old_bab} → +{progression['base_attack_bonus']}",
                 f"Combined base saves: {old_saves} → {saves_text(progression['base_saves'])}"]
        lines.extend(f"{name.title()}: {getattr(self.baseline, name)} → {getattr(candidate, name)}" for name in ABILITIES if getattr(self.baseline, name) != getattr(candidate, name))
        added = after.get("feats", [])[len(before.get("feats", [])):]
        if added:
            lines.append("Added feats: " + ", ".join(added))
        if candidate.level != self.baseline.level:
            entry = after["advancement_history"][-1]
            lines += [f"HP roll: d{entry['hit_die']} face {entry['hp_roll']} · {entry['hp_roll_detail'] or 'DM-entered die face'}",
                      f"New level HP: {entry['hp_gain']}; prior-level CON adjustment: {entry['retroactive_constitution_hp']}",
                      f"New skill points: {entry['skill_points']}"]
            for skill in entry["skill_increases"]:
                old_rank = before.get("skills_half_ranks", {}).get(skill, 0) / 2
                new_rank = after["skills_half_ranks"].get(skill, 0) / 2
                if old_rank != new_rank:
                    lines.append(f"{skill} ranks: {old_rank:g} → {new_rank:g}")
            lines += ["", "Class review: " + entry["class_notes"],
                      "Spell review: " + (entry["spell_notes"] or "No spell review required for this class level"),
                      "Restrictions/XP review: " + entry["restriction_notes"]]
        lines += ["", "Live encounter HP, combat state, equipment, XP and unrelated sheet data are preserved.", REVIEW, "", "Source: " + SOURCE]
        self._candidate = candidate
        self.preview_text.setPlainText("\n".join(lines))
        self.save_ack.setChecked(False)
        self.save_button.setEnabled(False)
        self.tabs.setCurrentIndex(2)
        self.status.setText("Preview only. Acknowledge this exact change before saving.")
        return True

    def save_reviewed(self):
        if self._candidate is None or not self.save_ack.isChecked():
            return self._error("Review the before/after preview and acknowledge it first.")
        try:
            saved = save_multiclass_candidate(self.repository, self.baseline, self._candidate)
            self.baseline = saved
            self.result_creature = saved
            self._load_character()
            self.record_saved.emit(saved)
            self.status.setText("Reviewed character saved. Live encounters are unchanged.")
            return True
        except (ValueError, sqlite3.Error) as error:
            self._invalidate()
            return self._error(error)
