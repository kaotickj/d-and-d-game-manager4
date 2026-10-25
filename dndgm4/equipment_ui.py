"""Review a supported equipment calculation before creating a save candidate."""
from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
import json

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFormLayout, QHBoxLayout,
    QLabel, QPlainTextEdit, QPushButton, QScrollArea, QSpinBox, QTabWidget,
    QVBoxLayout, QWidget,
)

from .equipment_rules import ARMOR, SHIELDS, WEAPONS, CLASS_NAMES, effective_stats, validate_loadout, read_character_sheet


def _label(text):
    label = QLabel(text)
    label.setTextFormat(Qt.TextFormat.PlainText)
    label.setWordWrap(True)
    return label


class EquipmentLoadoutDialog(QDialog):
    """No database writes, purchases, saved-AC changes, or encounter changes."""

    def __init__(self, creature, parent=None):
        super().__init__(parent)
        self.baseline = creature
        self.result_profile = None
        self.result_creature = None
        self._reviewed_profile = None
        self._candidate = None
        self._loading = True
        self._load_error = ""
        self._initial_notice = ""
        self._sheet = {}
        self._existing = None
        try:
            self._sheet = read_character_sheet(creature)
            if "combat_loadout" in self._sheet:
                self._existing = validate_loadout(self._sheet["combat_loadout"])
        except (ValueError, TypeError, OverflowError) as exc:
            self._load_error = str(exc)
        self.setWindowTitle(f"Equipment Calculation · {creature.name}")
        self.resize(980, 720)
        self.setMinimumSize(760, 540)
        root = QVBoxLayout(self)
        heading = _label("REVIEW EQUIPMENT CALCULATION")
        heading.setObjectName("pageTitle")
        root.addWidget(heading)
        root.addWidget(_label(
            "Supported D&D 3.5 equipment and feat calculations require confirmed class levels and eligibility. "
            "Saving records this reviewed loadout only. It does not replace saved AC, change encounter instances, "
            "buy equipment, or transfer campaign inventory."))
        self.tabs = QTabWidget()
        root.addWidget(self.tabs, 1)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        body = QWidget()
        form = QFormLayout(body)
        scroll.setWidget(body)
        self.tabs.addTab(scroll, "Loadout and eligibility")
        self.armor = self._combo(ARMOR)
        self.shield = self._combo(SHIELDS)
        self.weapon = self._combo(WEAPONS)
        self.size = self._combo(("Small", "Medium"))
        self.size.setCurrentText("Medium")
        for title, widget in (("Armor", self.armor), ("Shield", self.shield), ("Weapon", self.weapon), ("Size", self.size)):
            widget.setAccessibleName(title)
            form.addRow(title, widget)
        self.proficiency = QCheckBox("I confirm proficiency with the selected weapon, armor, and shield")
        self.proficiency.setAccessibleName("Confirm weapon, armor, and shield proficiency")
        form.addRow(self.proficiency)
        feats = self._sheet.get("feats", [])
        if not isinstance(feats, list):
            feats = []
        owned_focus = any(isinstance(feat, str) and (feat == "Weapon Focus" or feat.startswith("Weapon Focus (") and feat.endswith(")")) for feat in feats)
        self.weapon_focus = self._combo(("", *WEAPONS))
        self.weapon_focus.setAccessibleName("Owned Weapon Focus weapon")
        self.weapon_focus.setEnabled(owned_focus)
        form.addRow("Weapon Focus weapon (owned feat only)", self.weapon_focus)
        self.weapon_finesse = QCheckBox("Use owned Weapon Finesse when supported for this weapon")
        self.weapon_finesse.setEnabled("Weapon Finesse" in feats)
        form.addRow(self.weapon_finesse)
        self.monk_eligible = QCheckBox("Confirm unencumbered, able to move, not helpless (Monk AC)")
        self.paladin_eligible = QCheckBox("Confirm active Divine Grace eligibility")
        form.addRow(self.monk_eligible)
        form.addRow(self.paladin_eligible)
        form.addRow(_label("Confirm class levels explicitly. The total must match the saved character level. "
                           "Display class names and computed statistics are not used to infer history."))
        self.class_levels = {}
        levels_body = QWidget()
        levels = QFormLayout(levels_body)
        for name in CLASS_NAMES:
            spin = QSpinBox()
            spin.setRange(0, 20)
            spin.setAccessibleName(f"Confirmed {name} levels")
            self.class_levels[name] = spin
            levels.addRow(name, spin)
        form.addRow(levels_body)
        self.preview = QPlainTextEdit()
        self.preview.setReadOnly(True)
        self.preview.setAccessibleName("Reviewed calculation breakdown and rule sources")
        self.tabs.addTab(self.preview, "Calculation and sources")
        self.status = _label("")
        self.status.setAccessibleName("Equipment review status")
        root.addWidget(self.status)
        buttons = QHBoxLayout()
        self.review_button = QPushButton("Review calculation")
        self.review_button.clicked.connect(self.review_calculation)
        buttons.addWidget(self.review_button)
        self.save_button = QPushButton("Save reviewed loadout")
        self.save_button.setEnabled(False)
        self.save_button.clicked.connect(self.accept)
        buttons.addWidget(self.save_button)
        cancel = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel)
        cancel.rejected.connect(self.reject)
        buttons.addWidget(cancel)
        root.addLayout(buttons)
        self._load_initial(feats)
        for combo in (self.armor, self.shield, self.weapon, self.size, self.weapon_focus):
            combo.currentIndexChanged.connect(self._invalidate)
        for checkbox in (self.proficiency, self.weapon_finesse, self.monk_eligible, self.paladin_eligible):
            checkbox.toggled.connect(self._invalidate)
        for spin in self.class_levels.values():
            spin.valueChanged.connect(self._invalidate)
        self._loading = False
        if self._load_error:
            self.review_button.setEnabled(False)
            body.setEnabled(False)
            self.status.setText(f"Cannot review this saved sheet: {self._load_error}. Original data retained; cancel and repair the record first.")
        else:
            self.status.setText(self._initial_notice or "Choose equipment and confirm class levels, then review the calculation.")

    @staticmethod
    def _combo(items):
        combo = QComboBox()
        combo.addItems(list(items))
        return combo

    def _basis(self):
        return {"class": self.baseline.character_class, "race": self.baseline.race_type, "level": self.baseline.level}

    def _valid_levels(self, levels):
        return (isinstance(levels, dict) and bool(levels) and
                all(name in CLASS_NAMES and type(value) is int and 1 <= value <= 20 for name, value in levels.items()) and
                sum(levels.values()) == self.baseline.level)

    def _load_initial(self, feats):
        profile = self._existing or {}
        for key, combo in (("armor", self.armor), ("shield", self.shield), ("weapon", self.weapon), ("size", self.size), ("weapon_focus_weapon", self.weapon_focus)):
            if key in profile:
                combo.setCurrentText(profile[key])
        if not profile:
            for feat in feats:
                if isinstance(feat, str) and feat.startswith("Weapon Focus (") and feat.endswith(")"):
                    chosen = feat[len("Weapon Focus ("):-1]
                    matches = [name for name in WEAPONS if name.casefold() == chosen.casefold()]
                    if matches:
                        self.weapon_focus.setCurrentText(matches[0])
                        break
        levels = profile.get("class_levels", self._sheet.get("class_levels", {}))
        if self._valid_levels(levels):
            for name, count in levels.items():
                self.class_levels[name].setValue(count)
        stale = bool(profile) and profile.get("review_basis") != self._basis()
        self.proficiency.setChecked(bool(profile.get("proficiency_confirmed", False)) and not stale)
        self.weapon_finesse.setChecked(bool(profile.get("weapon_finesse", False)) and self.weapon_finesse.isEnabled())
        self.monk_eligible.setChecked(bool(profile.get("monk_ac_eligible", False)) and not stale)
        self.paladin_eligible.setChecked(bool(profile.get("paladin_grace_eligible", False)) and not stale)
        if stale:
            self._initial_notice = "The saved class, race, or level differs from the previous review. Reconfirm eligibility and review this loadout again."

    def profile(self):
        return dict(version=1, armor=self.armor.currentText(), shield=self.shield.currentText(),
                    weapon=self.weapon.currentText(), size=self.size.currentText(),
                    proficiency_confirmed=self.proficiency.isChecked(),
                    class_levels={name: spin.value() for name, spin in self.class_levels.items() if spin.value()},
                    weapon_focus_weapon=self.weapon_focus.currentText() if self.weapon_focus.isEnabled() else "",
                    weapon_finesse=self.weapon_finesse.isChecked() and self.weapon_finesse.isEnabled(),
                    monk_ac_eligible=self.monk_eligible.isChecked(),
                    paladin_grace_eligible=self.paladin_eligible.isChecked(), review_basis=self._basis())

    def _invalidate(self, *_args):
        if self._loading:
            return
        self._reviewed_profile = None
        self._candidate = None
        self.save_button.setEnabled(False)
        self.preview.clear()
        self.status.setText("Choices changed. Review the calculation again before saving.")

    def review_calculation(self):
        self._reviewed_profile = None
        self._candidate = None
        self.save_button.setEnabled(False)
        if self._load_error:
            return False
        try:
            profile = validate_loadout(self.profile(), self.baseline)
            calculated = effective_stats(self.baseline, profile)
            sheet = deepcopy(self._sheet)
            sheet["combat_loadout"] = deepcopy(profile)
            candidate = replace(self.baseline, sheet_json=json.dumps(sheet, ensure_ascii=False, allow_nan=False))
            text = self._preview_text(calculated)
        except (ValueError, TypeError, OverflowError) as exc:
            self.status.setText(f"Cannot review calculation: {exc}. Original character retained.")
            self.preview.clear()
            return False
        self._reviewed_profile = deepcopy(profile)
        self._candidate = candidate
        self.preview.setPlainText(text)
        self.save_button.setEnabled(True)
        self.status.setText("Calculation ready for review. Saving preserves the character's manual AC and encounter instances.")
        self.tabs.setCurrentWidget(self.preview)
        return True

    def _preview_text(self, calculated):
        manual = self.baseline.armor_class
        computed = calculated.get("ac")
        lines = [f"Saved manual AC: {manual}", f"Calculated loadout AC: {computed}"]
        if computed != manual:
            lines.append("AC discrepancy: this calculation differs from saved manual AC. Saving this loadout does not replace manual AC.")
        lines.append("Calculated values are conditional on the confirmed eligibility and supported rules below.")
        lines.append(f"\nArmor Class: {computed} | Touch: {calculated['touch_ac']} | Flat-footed: {calculated['flat_footed_ac']}")
        attack = calculated['attack_bonus']
        lines.append("Attack: " + (f"{attack:+d}" if attack is not None else "Confirm proficiency to calculate"))
        lines.append(f"Damage: {calculated['damage_expression'] or 'Confirm proficiency to calculate'}")
        lines.append(f"Critical threat: {calculated['threat_min']}–20 | Multiplier: ×{calculated['multiplier']}")
        lines.append("Saving throws: " + " | ".join(f"{name} {value:+d}" for name, value in calculated['saves'].items()))
        lines.append(f"Initiative: {calculated['initiative']:+d} | Armor check penalty: {calculated['armor_check_penalty']}")
        lines.append(f"Maximum Dexterity bonus to AC: {calculated['max_dex'] if calculated['max_dex'] is not None else 'No armor limit'}")
        for key, title in (("components", "Calculation breakdown"), ("warnings", "Review these circumstances"),
                           ("unsupported", "Rules that still need DM adjudication"), ("sources", "Rule sources")):
            lines.append("\n" + title)
            lines.extend("• " + str(value) for value in calculated[key])
        return "\n".join(lines)

    def accept(self):
        if self._candidate is None or self._reviewed_profile != self.profile():
            self._invalidate()
            return
        self.result_profile = deepcopy(self._reviewed_profile)
        self.result_creature = self._candidate
        super().accept()

    def reject(self):
        self.result_profile = None
        self.result_creature = None
        super().reject()
