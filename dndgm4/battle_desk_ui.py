"""Additional battle desk, designed to coexist with the existing v0.8 window."""
from __future__ import annotations

import sqlite3

from PyQt6.QtCore import Qt, QTimer, QThread, pyqtSignal, QUrl
from PyQt6.QtGui import QDesktopServices
from PyQt6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QFormLayout, QGridLayout, QGroupBox,
    QHBoxLayout, QLabel, QLineEdit, QMessageBox, QPlainTextEdit, QPushButton,
    QSpinBox, QTabWidget, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget, QScrollArea,
    QAbstractItemView
)

from .srd35_spells import SpellCatalog, LISTS
from .ai_ui import AIWritingDialog

SRD_MODIFIERS = [
    ("Attack", "Flanking (melee)", "+2 attack", "Must threaten target from opposite side"),
    ("Attack", "Higher ground (melee)", "+1 attack", "Melee only"),
    ("Attack", "Charge", "+2 attack, -2 AC", "Charge requirements and path must be met"),
    ("Attack", "Fighting defensively", "-4 attack, +2 dodge AC", "Standard attack or full attack"),
    ("Attack", "Ranged into melee", "-4 attack", "Precise Shot can negate this penalty"),
    ("Attack", "Dazzled", "-1 attack", "Melee or ranged"),
    ("Attack", "Entangled", "-2 attack, -4 Dexterity", "Dex adjustment may change derived stats"),
    ("Attack", "Shaken / frightened", "-2 attack", "Also penalties on checks and saves"),
    ("Attack", "Prone attacker", "-4 melee attack", "Most ranged weapons unavailable"),
    ("Attack", "Squeezing", "-4 attack, -4 AC", "Tight space"),
    ("Attack", "Invisible attacker", "+2 attack", "Target generally loses Dex to AC"),
    ("Defense", "Cover", "+4 AC", "Cover may also protect against some special effects"),
    ("Defense", "Improved cover", "+8 AC", "Also +4 Reflex saves; verify geometry"),
    ("Defense", "Concealment", "20% miss chance", "Roll miss chance after a successful attack"),
    ("Defense", "Total concealment", "50% miss chance", "Must guess location; cannot target directly"),
    ("Defense", "Prone defender", "-4 AC melee, +4 AC ranged", "Direction of incoming attack matters"),
    ("Defense", "Blinded", "-2 AC, loses Dex bonus", "Opponents generally have total concealment"),
    ("Defense", "Stunned", "-2 AC, loses Dex bonus", "Cannot act"),
    ("Defense", "Helpless", "-4 AC vs melee", "Dexterity treated as 0 for AC"),
    ("Defense", "Total defense", "+4 dodge AC", "Standard action; cannot make AoOs"),
    ("Actions", "Attack action", "Standard", "One attack at chosen bonus"),
    ("Actions", "Full attack", "Full-round", "Iterative attacks use BAB, weapon rules"),
    ("Actions", "Cast spell", "Usually standard", "Spell casting time overrides; may provoke AoO"),
    ("Actions", "Withdraw", "Full-round", "First square exited doesn't provoke"),
    ("Actions", "Ready", "Standard", "Action before next turn; initiative may change"),
    ("Actions", "Delay", "No action spent yet", "Moves initiative to chosen later count"),
    ("Actions", "5-foot step", "No action", "Only when no other movement this round"),
    ("Actions", "Stand from prone", "Move", "Provokes an opportunity attack"),
    ("Actions", "Draw weapon", "Move / free with BAB +1 during move", "Check feat and circumstances"),
    ("Actions", "Charge", "Full-round / special standard", "Straight clear path, range restrictions"),
    ("Saving", "Natural 1 / 20", "Auto-fail / auto-success", "Applies to saving throws, not skill checks"),
    ("Other", "Nonlethal damage", "Track separately", "Equal HP staggered; greater HP unconscious"),
    ("Other", "Attacks of opportunity", "Usually 1 per round", "Combat Reflexes changes allowance"),
    ("Other", "Aid another", "+2 attack or AC", "Requires successful melee attack vs AC 10"),
]
SRD_URLS = {
    "Combat modifiers": "https://www.d20srd.org/srd/combat/combatModifiers.htm",
    "Actions": "https://www.d20srd.org/srd/combat/actionsInCombat.htm",
    "Special attacks": "https://www.d20srd.org/srd/combat/specialAttacks.htm",
    "Initiative": "https://www.d20srd.org/srd/combat/initiative.htm",
    "Conditions": "https://www.d20srd.org/srd/conditionSummary.htm",
    "Magic": "https://www.d20srd.org/srd/magicOverview/castingSpells.htm",
}


class SpellIndexer(QThread):
    completed = pyqtSignal(int)
    failed = pyqtSignal(str)

    def __init__(self, catalog, parent=None):
        super().__init__(parent)
        self.catalog = catalog

    def run(self):
        try:
            entries = self.catalog.build()
        except Exception as exc:
            self.failed.emit(str(exc))
        else:
            self.completed.emit(len(entries))


def spin(low, high, value=0, name=""):
    field = QSpinBox()
    field.setRange(low, high)
    field.setValue(value)
    if name:
        field.setAccessibleName(name)
    return field


class CombatDeskDialog(QDialog):
    """Separate, modeless SRD toolkit. Uses host._run for autosave and undo."""

    def __init__(self, host):
        super().__init__(host)
        self.setAttribute(Qt.WidgetAttribute.WA_QuitOnClose, False)
        self.host = host
        self.setWindowTitle("Combat Desk | D&D 3.5 Rules and Encounter Control")
        self.resize(1070, 760)
        self.setMinimumSize(800, 550)
        self.catalog = SpellCatalog(host.library.path)
        self.spell_worker = None
        self.timer_seconds = 60
        self.table_timer = QTimer(self)
        self.table_timer.setInterval(1000)
        self.table_timer.timeout.connect(self.countdown)
        root = QVBoxLayout(self)
        title = QLabel("COMBAT DESK   /   D&D 3.5 SRD")
        title.setObjectName("pageTitle")
        root.addWidget(title)
        self.clock = QLabel("")
        self.clock.setObjectName("sectionTitle")
        root.addWidget(self.clock)
        self.tabs = QTabWidget()
        root.addWidget(self.tabs, 1)
        self.build_timers()
        self.build_actions()
        self.build_attacks()
        self.build_spells()
        self.build_rules()
        self.build_narrator()
        self.refresh()

    def closeEvent(self, event):
        self.table_timer.stop()
        if self.spell_worker is not None and self.spell_worker.isRunning():
            # Qt worker remains owned until its network request finishes.
            event.ignore()
            self.hide()
            return
        self.hide()
        event.ignore()

    def page(self, name):
        page = QWidget()
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(page)
        self.tabs.addTab(scroll, name)
        form = QVBoxLayout(page)
        form.setContentsMargins(12, 12, 12, 12)
        return form

    def add_row(self, parent, *widgets):
        row = QHBoxLayout()
        for widget in widgets:
            row.addWidget(widget)
        parent.addLayout(row)
        return row

    def button(self, label, fn):
        widget = QPushButton(label)
        widget.clicked.connect(fn)
        return widget

    def combatants(self, combo, *, blank=False):
        selected = combo.currentData()
        combo.blockSignals(True)
        combo.clear()
        if blank:
            combo.addItem("Whole encounter / no target", "")
        for fighter in self.host.battle.fighters:
            combo.addItem(fighter.name, fighter.uid)
        for index in range(combo.count()):
            if combo.itemData(index) == selected:
                combo.setCurrentIndex(index)
                break
        else:
            if combo is not getattr(self, "effect_anchor", None):
                uid = self.host.battle.current_id
                if uid:
                    match = combo.findData(uid)
                    if match >= 0 and not blank:
                        combo.setCurrentIndex(match)
        combo.blockSignals(False)

    def refresh(self):
        battle = self.host.battle
        current = battle.get(battle.current_id).name if battle.current_id else "None"
        phase = "SURPRISE" if battle.phase == "surprise" else battle.phase.upper()
        self.clock.setText(
            f"{phase}  |  Round {battle.round}  |  In-game elapsed {battle.clock_label()} "
            f"|  Acting: {current}  |  Real-world timer {self.timer_seconds}s")
        for name, blank in (("effect_anchor", False), ("effect_target", True),
                            ("attack_actor", False), ("attack_target", False),
                            ("save_actor", False), ("spell_actor", False)):
            self.combatants(getattr(self, name), blank=blank)
        self.render_effects()
        budget = ", ".join(f"{k}: {v}" for k,v in battle.action_state.items()) or "None spent"
        self.action_status.setText("This turn: " + budget)
        self.slot_status.setText(
            "Slot tracking is encounter-local. Configure totals per caster and spell level."
        )

    def build_timers(self):
        page = self.page("Round & Effect Clocks")
        info = QLabel("D&D 3.5: 1 round = 6 in-game seconds. An effect of N rounds "
                      "expires just BEFORE the caster's initiative count returns N times. "
                      "The separate wall-clock timer never advances combat automatically.")
        info.setWordWrap(True)
        page.addWidget(info)
        row = QHBoxLayout()
        self.wall_timer = QLabel("01:00")
        self.wall_timer.setObjectName("sectionTitle")
        row.addWidget(self.wall_timer)
        row.addWidget(QLabel("Real-world seconds"))
        self.wall_seconds = spin(5, 3600, 60, "Optional table timer seconds")
        row.addWidget(self.wall_seconds)
        row.addWidget(self.button("Start / Resume", lambda: self.table_timer.start(1000)))
        row.addWidget(self.button("Pause", self.table_timer.stop))
        row.addWidget(self.button("Reset", self.reset_timer))
        row.addStretch()
        page.addLayout(row)
        fields = QGridLayout()
        self.effect_name = QLineEdit()
        self.effect_name.setPlaceholderText("e.g. Bless, Web, poisoned fog")
        self.effect_name.setAccessibleName("Timed effect name")
        self.effect_anchor = QComboBox()
        self.effect_target = QComboBox()
        self.effect_duration = spin(1, 100000, 2, "Duration amount")
        self.effect_unit = QComboBox()
        self.effect_unit.addItems(["rounds", "minutes", "hours"])
        self.effect_notes = QLineEdit()
        self.effect_notes.setPlaceholderText("Caster level, save DC, concentration, reminders...")
        fields.addWidget(QLabel("Effect / spell"), 0, 0)
        fields.addWidget(self.effect_name, 0, 1, 1, 3)
        fields.addWidget(QLabel("Origin / initiative anchor"), 1, 0)
        fields.addWidget(self.effect_anchor, 1, 1)
        fields.addWidget(QLabel("Affected"), 1, 2)
        fields.addWidget(self.effect_target, 1, 3)
        fields.addWidget(QLabel("Duration"), 2, 0)
        fields.addWidget(self.effect_duration, 2, 1)
        fields.addWidget(self.effect_unit, 2, 2)
        fields.addWidget(self.button("Start Clock", self.add_effect), 2, 3)
        fields.addWidget(QLabel("GM notes"), 3, 0)
        fields.addWidget(self.effect_notes, 3, 1, 1, 3)
        page.addLayout(fields)
        supported = QHBoxLayout()
        from .spell_effects import CATALOG
        self.supported_spell = QComboBox()
        self.supported_spell.addItems(list(CATALOG))
        self.supported_spell.setAccessibleName("Supported spell mechanics to review")
        supported.addWidget(self.supported_spell)
        supported.addWidget(self.button("Review Supported Spell Effect…", self.add_supported_effect))
        page.addLayout(supported)
        self.effect_table = QTableWidget(0, 5)
        self.effect_table.setHorizontalHeaderLabels(
            ["Effect", "Target", "Initiative anchor", "Rounds remaining", "Notes"])
        self.effect_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.effect_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.effect_table.setColumnWidth(0, 200)
        self.effect_table.setColumnWidth(1, 170)
        self.effect_table.setColumnWidth(2, 170)
        self.effect_table.setColumnWidth(3, 130)
        self.effect_table.horizontalHeader().setStretchLastSection(True)
        page.addWidget(self.effect_table, 1)
        edit = QHBoxLayout()
        self.remaining = spin(1, 100000000, 1, "Remaining in-game rounds")
        edit.addWidget(QLabel("Selected effect remaining rounds"))
        edit.addWidget(self.remaining)
        edit.addWidget(self.button("Change Remaining", self.adjust_effect))
        edit.addWidget(self.button("Dismiss Effect", self.cancel_effect))
        edit.addStretch()
        page.addLayout(edit)

    def reset_timer(self):
        self.timer_seconds = self.wall_seconds.value()
        self.wall_timer.setText(
            f"{self.timer_seconds // 60:02d}:{self.timer_seconds % 60:02d}")
        self.table_timer.stop()
        self.refresh()

    def countdown(self):
        self.timer_seconds = max(0, self.timer_seconds - 1)
        self.wall_timer.setText(
            f"{self.timer_seconds // 60:02d}:{self.timer_seconds % 60:02d}")
        if self.timer_seconds == 0:
            self.table_timer.stop()
            self.wall_timer.setText("00:00  |  TIME")

    def effect_id(self):
        row = self.effect_table.currentRow()
        if row < 0 or row >= len(self.host.battle.effects):
            raise ValueError("Select an active effect first.")
        return self.effect_table.item(row, 0).data(Qt.ItemDataRole.UserRole)

    def render_effects(self):
        battle = self.host.battle
        self.effect_table.setRowCount(len(battle.effects))
        for row, effect in enumerate(battle.effects):
            target = battle.get(effect["target_id"]).name if effect["target_id"] else "Everyone"
            anchor = battle.get(effect["anchor_id"]).name
            for col, value in enumerate((
                effect["name"], target, anchor,
                str(effect["remaining"]), effect["notes"]
            )):
                item = QTableWidgetItem(value)
                if col == 0:
                    item.setData(Qt.ItemDataRole.UserRole, effect["id"])
                self.effect_table.setItem(row, col, item)

    def add_effect(self):
        self.host._run(lambda: self.host.battle.add_effect(
            self.effect_name.text().strip(),
            target_id=self.effect_target.currentData() or "",
            anchor_id=self.effect_anchor.currentData() or "",
            duration=self.effect_duration.value(), unit=self.effect_unit.currentText(),
            notes=self.effect_notes.text()))

    def adjust_effect(self):
        try:
            uid = self.effect_id()
        except ValueError as exc:
            QMessageBox.information(self, "Select effect", str(exc))
            return
        self.host._run(lambda: self.host.battle.adjust_effect(uid, self.remaining.value()))

    def add_supported_effect(self):
        from .spell_effects import CATALOG
        spell = self.supported_spell.currentText()
        target = self.effect_target.currentData()
        if not target:
            QMessageBox.information(self, "Select a target", "Choose one explicit recipient. Apply area effects separately to reviewed recipients.")
            return
        try:
            recipient = self.host.battle.get(target).name
        except ValueError as exc:
            QMessageBox.warning(self, "Review spell recipient", str(exc))
            return
        text = (f"Apply {spell} to {recipient} using the selected duration and initiative anchor? "
                "This creates a supported effect for reviewed roll suggestions. Spell slots and actions remain separate explicit commands.")
        if not self._confirm_calculation("Review supported spell", text, CATALOG[spell]):
            return
        self.host._run(lambda: self.host.battle.add_effect(
            spell, target_id=target, anchor_id=self.effect_anchor.currentData() or "",
            duration=self.effect_duration.value(), unit=self.effect_unit.currentText(),
            notes=self.effect_notes.text(), mechanics={"version": 1, "spell": spell}))

    def cancel_effect(self):
        try:
            uid = self.effect_id()
        except ValueError as exc:
            QMessageBox.information(self, "Select effect", str(exc))
            return
        self.host._run(lambda: self.host.battle.cancel_effect(uid))

    def build_actions(self):
        page = self.page("Action Economy")
        hint = QLabel("Track standard, move, full-round, free, swift and immediate "
                      "actions. Advanced exceptions (ready/delay, AoOs, full attacks, "
                      "movement geometry, special attacks) remain DM-adjudicated.")
        hint.setWordWrap(True)
        page.addWidget(hint)
        self.action_status = QLabel("")
        self.action_status.setObjectName("sectionTitle")
        page.addWidget(self.action_status)
        grid = QGridLayout()
        for i, (action, desc) in enumerate([
            ("standard", "Attack, cast spell, total defense, special attack"),
            ("move", "Move speed, stand, draw item"),
            ("full", "Full attack, withdraw, charge"),
            ("swift", "One swift action"),
            ("immediate", "One immediate action (affects next swift)"),
            ("free", "Speak, drop item, other free action"),
            ("5-foot step", "Only without other movement"),
            ("reset", "GM override / reset current turn")
        ]):
            btn = self.button(action.title(), lambda checked=False, k=action:
                              self.host._run(lambda: self.host.battle.spend_action(k)))
            btn.setToolTip(desc)
            grid.addWidget(btn, i//2, (i%2)*2)
            grid.addWidget(QLabel(desc), i//2, (i%2)*2+1)
        page.addLayout(grid)
        self.action_note = QLineEdit()
        self.action_note.setPlaceholderText("Ready, Delay, AoO, bull rush, grapple, trip, conditions, or ruling...")
        page.addWidget(self.action_note)
        page.addWidget(self.button("Log Special Action / DM Ruling", self.log_action))
        page.addStretch(1)

    def log_action(self):
        note = self.action_note.text().strip()
        if note:
            self.host._run(lambda: self._note("DM ruling: " + note))
            self.action_note.clear()

    def _note(self, value):
        battle = self.host.battle
        battle._remember()
        battle.note(value[:5000])

    def build_attacks(self):
        page = self.page("Attacks, Saves & Checks")
        page.addWidget(QLabel("D&D 3.5: natural 1 misses and natural 20 hits; "
                              "critical threats require confirmation; concealment uses d100."))
        grid = QGridLayout()
        self.attack_actor = QComboBox()
        self.attack_target = QComboBox()
        self.attack_bonus = spin(-100, 200, 0, "Total melee or ranged attack bonus")
        self.attack_misc = spin(-100, 100, 0, "Situational attack modifier")
        self.attack_damage = QLineEdit("1d8+2")
        self.attack_damage.setAccessibleName("Damage dice expression")
        self.attack_threat = spin(2, 20, 20, "Critical threat starts at")
        self.attack_mult = spin(2, 4, 2, "Critical damage multiplier")
        self.cover = QComboBox()
        for text, value in [("No cover", 0), ("Cover (+4 AC)", 4),
                            ("Improved cover (+8 AC)", 8)]:
            self.cover.addItem(text, value)
        self.conceal = QComboBox()
        for text, value in [("Clear (0%)", 0), ("Concealment (20%)", 20),
                            ("Total concealment (50%)", 50)]:
            self.conceal.addItem(text, value)
        self.damage_reduction = spin(0, 1000, 0, "Unbypassed damage reduction")
        self.apply_damage = QCheckBox("Apply damage to target automatically")
        rows = [
            ("Attacker", self.attack_actor), ("Target", self.attack_target),
            ("Total attack bonus", self.attack_bonus), ("Misc adjustment", self.attack_misc),
            ("Weapon damage", self.attack_damage), ("Critical threat ≥", self.attack_threat),
            ("Critical multiplier", self.attack_mult), ("Cover", self.cover),
            ("Concealment", self.conceal), ("Unbypassed DR", self.damage_reduction),
        ]
        for i, (name, widget) in enumerate(rows):
            grid.addWidget(QLabel(name), i//2, (i%2)*2)
            grid.addWidget(widget, i//2, (i%2)*2+1)
        page.addLayout(grid)
        page.addWidget(self.apply_damage)
        page.addWidget(self.button("Review Character Attack Suggestion…", self.review_character_attack))
        self._attack_suggestion = None
        for field in (self.attack_bonus, self.attack_damage, self.attack_threat, self.attack_mult):
            signal = field.currentIndexChanged if isinstance(field, QComboBox) else field.textChanged if isinstance(field, QLineEdit) else field.valueChanged
            signal.connect(self._clear_attack_suggestion)
        target_review = QHBoxLayout()
        self.defense_kind = QComboBox()
        for label, key in (("Normal AC", "ac"), ("Touch AC", "touch_ac"), ("Flat-footed AC", "flat_footed_ac")):
            self.defense_kind.addItem(label, key)
        target_review.addWidget(self.defense_kind)
        target_review.addWidget(self.button("Review Target Defense…", self.review_target_defense))
        self.use_reviewed_defense = QCheckBox("Use reviewed AC for this roll")
        self.use_reviewed_defense.setEnabled(False)
        target_review.addWidget(self.use_reviewed_defense)
        self._target_suggestion = None
        self.attack_target.currentIndexChanged.connect(self._clear_target_suggestion)
        self.defense_kind.currentIndexChanged.connect(self._clear_target_suggestion)
        page.addLayout(target_review)
        page.addWidget(self.button("Roll Attack / Resolve", self.resolve_attack))
        self.attack_result = QLabel("Result appears in the combat log.")
        self.attack_result.setWordWrap(True)
        page.addWidget(self.attack_result)
        group = QGroupBox("Saving throws, concentration and skill checks")
        form = QFormLayout(group)
        self.save_actor = QComboBox()
        self.save_kind = QComboBox()
        self.save_kind.addItems(["Fortitude", "Reflex", "Will", "Concentration", "Skill / Ability"])
        self.save_mod = spin(-100, 200, 0, "Check or save modifier")
        self.save_dc = spin(1, 500, 15, "Difficulty class")
        form.addRow("Creature", self.save_actor)
        form.addRow("Type", self.save_kind)
        form.addRow("Total modifier", self.save_mod)
        form.addRow("DC", self.save_dc)
        self.fear_save = QCheckBox("This saving throw is against fear (review Bless bonus)")
        form.addRow(self.fear_save)
        self._save_suggestion = None
        self.save_mod.valueChanged.connect(self._clear_save_suggestion)
        form.addRow(self.button("Review Character Save Suggestion…", self.review_character_save))
        form.addRow(self.button("Roll Saving Throw / Check", self.resolve_save))
        page.addWidget(group)
        page.addStretch()

    def _clear_attack_suggestion(self, *args):
        self._attack_suggestion = None

    def _clear_save_suggestion(self, *args):
        self._save_suggestion = None

    def _clear_target_suggestion(self, *args):
        self._target_suggestion = None
        self.use_reviewed_defense.setChecked(False)
        self.use_reviewed_defense.setEnabled(False)

    def _loadout_stats(self, uid):
        from .equipment_rules import read_loadout, effective_stats
        from .spell_effects import preview_effects
        fighter = self.host.battle.get(uid)
        record = self.host.library.get(fighter.source_id) if fighter.source_id else None
        if record is None:
            raise ValueError("This combatant has no saved character source. Enter manual modifiers after DM review.")
        profile = read_loadout(record)
        if profile is None:
            raise ValueError("Review and save this character's equipment calculation from the Compendium first.")
        return preview_effects(effective_stats(record, profile), self.host.battle.effects, uid)

    def _confirm_calculation(self, title, text, details):
        box = QMessageBox(QMessageBox.Icon.Question, title, text,
                          QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, self)
        box.setTextFormat(Qt.TextFormat.PlainText)
        box.setDefaultButton(QMessageBox.StandardButton.No)
        box.setDetailedText("\n".join(f"{key}: {value}" for key, value in details.items()))
        return box.exec() == QMessageBox.StandardButton.Yes

    def review_character_attack(self):
        try:
            uid = self.attack_actor.currentData()
            stats = self._loadout_stats(uid)
            if stats["attack_bonus"] is None:
                raise ValueError("Confirm equipment proficiency in the loadout review first.")
            if not self._confirm_calculation("Review attack suggestion",
                    "Copy this supported character attack calculation into the roll controls? Review temporary conditions, range and action choices separately.", stats):
                return
            self.attack_bonus.setValue(stats["attack_bonus"])
            self.attack_damage.setText(stats["damage_expression"])
            self.attack_threat.setValue(stats["threat_min"])
            self.attack_mult.setValue(stats["multiplier"])
            self._attack_suggestion = (uid, stats)
        except (ValueError, OSError, sqlite3.Error) as exc:
            QMessageBox.warning(self, "Character suggestion unavailable", str(exc))

    def review_target_defense(self):
        try:
            uid = self.attack_target.currentData()
            stats = self._loadout_stats(uid)
            key = self.defense_kind.currentData()
            if self._confirm_calculation("Review target defense",
                    f"Use {self.defense_kind.currentText()} {stats[key]} for this roll? Saved encounter AC stays {self.host.battle.get(uid).ac}. Review circumstances and supported-rule limits.", stats):
                self._target_suggestion = (uid, key, stats)
                self.use_reviewed_defense.setEnabled(True)
                self.use_reviewed_defense.setChecked(True)
        except (ValueError, OSError, sqlite3.Error) as exc:
            QMessageBox.warning(self, "Character defense unavailable", str(exc))

    def review_character_save(self):
        try:
            uid, kind = self.save_actor.currentData(), self.save_kind.currentText()
            stats = self._loadout_stats(uid)
            if kind not in stats["saves"]:
                raise ValueError("Only Fortitude, Reflex and Will suggestions are supported. Enter checks manually.")
            bonus = stats["saves"][kind] + (stats.get("fear_save_bonus", 0) if self.fear_save.isChecked() else 0)
            if self._confirm_calculation("Review saving throw suggestion", f"Use {kind} modifier {bonus:+d}? Review circumstances and other temporary modifiers.", stats):
                self.save_mod.setValue(bonus)
                self._save_suggestion = (uid, kind, self.fear_save.isChecked(), stats)
        except (ValueError, OSError, sqlite3.Error) as exc:
            QMessageBox.warning(self, "Character save unavailable", str(exc))

    def resolve_attack(self):
        actor = self.attack_actor.currentData()
        target = self.attack_target.currentData()
        if not actor or not target:
            QMessageBox.information(self, "Combatants needed", "Add an attacker and target.")
            return
        target_ac = None
        try:
            if self._attack_suggestion is not None:
                uid, reviewed = self._attack_suggestion
                if uid != actor or self._loadout_stats(actor) != reviewed:
                    raise ValueError("Character or supported effects changed. Review the attack suggestion again or enter manual values.")
            if self.use_reviewed_defense.isChecked():
                uid, key, reviewed = self._target_suggestion
                if uid != target or self._loadout_stats(target) != reviewed:
                    raise ValueError("Target or supported effects changed. Review target defense again.")
                target_ac = reviewed[key]
        except (ValueError, OSError, sqlite3.Error) as exc:
            QMessageBox.warning(self, "Review changed modifiers", str(exc))
            return
        result = self.host._run(lambda: self.host.battle.resolve_attack(
            actor, target, bonus=self.attack_bonus.value(),
            damage=self.attack_damage.text(), situational=self.attack_misc.value(),
            threat_min=self.attack_threat.value(), multiplier=self.attack_mult.value(),
            cover=self.cover.currentData(), concealment=self.conceal.currentData(),
            damage_reduction=self.damage_reduction.value(),
            apply_damage=self.apply_damage.isChecked(), target_ac_override=target_ac))
        if result is not None:
            self.attack_result.setText(result.description)

    def resolve_save(self):
        uid = self.save_actor.currentData()
        if uid:
            kind = self.save_kind.currentText()
            try:
                if self._save_suggestion is not None:
                    actor, save_kind, fear, stats = self._save_suggestion
                    if (actor != uid or kind != save_kind or fear != self.fear_save.isChecked()
                            or self._loadout_stats(uid) != stats):
                        raise ValueError("Character, saving throw or supported effects changed. Review the save suggestion again or enter manual values.")
            except (ValueError, OSError, sqlite3.Error) as exc:
                QMessageBox.warning(self, "Review changed modifiers", str(exc))
                return
            self.host._run(lambda: self.host.battle.resolve_check(
                uid, kind, self.save_mod.value(), self.save_dc.value(),
                save=kind not in ("Skill / Ability", "Concentration")))

    def build_spells(self):
        page = self.page("3.5 SRD Spell Compendium")
        hint = QLabel("Indexes SRD class spell lists (names, spell levels and reference "
                      "links). First import requires internet; later searches work offline. "
                      "Casting and duration are GM-selected, never AI-invented.")
        hint.setWordWrap(True)
        page.addWidget(hint)
        row = QHBoxLayout()
        self.spell_query = QLineEdit()
        self.spell_query.setPlaceholderText("Find spells...")
        self.spell_query.textChanged.connect(self.filter_spells)
        row.addWidget(self.spell_query, 1)
        self.spell_class = QComboBox()
        self.spell_class.addItem("Every class", "")
        for name in LISTS:
            self.spell_class.addItem(name, name)
        self.spell_class.currentIndexChanged.connect(self.filter_spells)
        row.addWidget(self.spell_class)
        self.spell_level = QComboBox()
        self.spell_level.addItem("Any level", -1)
        for i in range(10):
            self.spell_level.addItem(f"Level {i}", i)
        self.spell_level.currentIndexChanged.connect(self.filter_spells)
        row.addWidget(self.spell_level)
        page.addLayout(row)
        self.spell_results = QLabel()
        page.addWidget(self.spell_results)
        self.spell_table = QTableWidget(0, 3)
        self.spell_table.setHorizontalHeaderLabels(["Spell", "Class", "Level"])
        self.spell_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.spell_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.spell_table.horizontalHeader().setStretchLastSection(True)
        self.spell_table.cellDoubleClicked.connect(lambda *_: self.open_spell())
        page.addWidget(self.spell_table, 1)
        self.add_row(page,
                     self.button("Import / Rebuild Complete SRD Class Index", self.import_spells),
                     self.button("Open Selected Spell Reference", self.open_spell))
        group = QGroupBox("Cast / Track Spell Slots (encounter-local)")
        form = QFormLayout(group)
        self.spell_actor = QComboBox()
        self.spell_slot_level = spin(0, 9, 1, "Spell slot level")
        self.spell_slot_total = spin(0, 100, 3, "Slots per day at selected level")
        self.spell_slot_used = spin(0, 100, 0, "Used slots at selected level")
        form.addRow("Caster", self.spell_actor)
        form.addRow("Slot level", self.spell_slot_level)
        form.addRow("Total daily slots", self.spell_slot_total)
        form.addRow("Slots used", self.spell_slot_used)
        form.addRow(self.button("Set Slot Budget", self.set_spell_slots))
        form.addRow(self.button("Cast Selected Spell (Spend Slot)", self.cast_spell))
        page.addWidget(group)
        self.slot_status = QLabel("")
        page.addWidget(self.slot_status)
        self.filter_spells()

    def selected_spell(self):
        row = self.spell_table.currentRow()
        if row < 0:
            raise ValueError("Select a spell.")
        item = self.spell_table.item(row, 0)
        if item is None:
            raise ValueError("Select a spell.")
        return item.data(Qt.ItemDataRole.UserRole)

    def filter_spells(self):
        entries = self.catalog.search(
            self.spell_query.text(), self.spell_class.currentData() or "",
            None if self.spell_level.currentData() == -1 else self.spell_level.currentData())
        self.spell_table.setRowCount(len(entries))
        for row, spell in enumerate(entries):
            for col, value in enumerate((spell["name"], spell["class"], str(spell["level"]))):
                item = QTableWidgetItem(value)
                if col == 0:
                    item.setData(Qt.ItemDataRole.UserRole, spell)
                self.spell_table.setItem(row, col, item)
        self.spell_results.setText(f"{len(entries)} indexed spell/class rows "
                                   f"({len(self.catalog.spells)} cached).")

    def open_spell(self):
        try:
            spell = self.selected_spell()
        except ValueError as exc:
            QMessageBox.information(self, "Select spell", str(exc))
            return
        QDesktopServices.openUrl(QUrl(spell["url"]))

    def import_spells(self):
        if self.spell_worker is not None and self.spell_worker.isRunning():
            return
        self.spell_results.setText("Retrieving six SRD class lists (only after this click)...")
        self.spell_worker = SpellIndexer(self.catalog, self)
        self.spell_worker.completed.connect(self.index_ready)
        self.spell_worker.failed.connect(self.index_failed)
        self.spell_worker.start()

    def index_ready(self, count):
        self.filter_spells()
        QMessageBox.information(self, "Spell index ready",
                                f"Indexed {count} spell/class entries locally. "
                                "Search now works offline.")

    def index_failed(self, message):
        self.spell_results.setText("Import failed; existing spell cache preserved.")
        QMessageBox.warning(self, "SRD import failed", message)

    def set_spell_slots(self):
        uid = self.spell_actor.currentData()
        if uid:
            self.host._run(lambda: self.host.battle.set_spell_slots(
                uid, self.spell_slot_level.value(), self.spell_slot_total.value(),
                self.spell_slot_used.value()))

    def cast_spell(self):
        try:
            spell = self.selected_spell()
        except ValueError as exc:
            QMessageBox.information(self, "Select spell", str(exc))
            return
        uid = self.spell_actor.currentData()
        if not uid:
            return
        if self.spell_slot_level.value() < spell["level"]:
            QMessageBox.warning(self, "Slot level", "Choose a spell slot at least "
                                "as high as the indexed class spell level.")
            return
        self.host._run(lambda: self.host.battle.use_spell_slot(
            uid, self.spell_slot_level.value(), spell["name"]))
        self.effect_name.setText(spell["name"])
        self.effect_anchor.setCurrentIndex(max(0, self.effect_anchor.findData(uid)))

    def build_rules(self):
        page = self.page("SRD Combat Reference")
        note = QLabel("3.5 SRD rules reference, not a blanket automatic bonus calculator. "
                      "Apply situational modifiers explicitly, avoid stacking identical bonus "
                      "types, and adjudicate geometry, reach, feats and equipment.")
        note.setWordWrap(True)
        page.addWidget(note)
        self.rules_table = QTableWidget(len(SRD_MODIFIERS), 4)
        self.rules_table.setHorizontalHeaderLabels(["Area", "Situation", "Modifier", "SRD ruling"])
        self.rules_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.rules_table.horizontalHeader().setStretchLastSection(True)
        for row, values in enumerate(SRD_MODIFIERS):
            for col, value in enumerate(values):
                self.rules_table.setItem(row, col, QTableWidgetItem(value))
        self.rules_table.setColumnWidth(0, 100)
        self.rules_table.setColumnWidth(1, 180)
        self.rules_table.setColumnWidth(2, 220)
        page.addWidget(self.rules_table, 1)
        references = QHBoxLayout()
        for title, url in SRD_URLS.items():
            btn = self.button(title, lambda checked=False, link=url:
                              QDesktopServices.openUrl(QUrl(link)))
            references.addWidget(btn)
        page.addLayout(references)

    def build_narrator(self):
        page = self.page("DM Narration & Plot")
        note = QLabel("Uses your existing local Gemma or Qwen3 text model through The Scribe. "
                      "AI provides editable narrative only, never decides SRD statistics, "
                      "makes secret rolls or changes the encounter automatically.")
        note.setWordWrap(True)
        page.addWidget(note)
        self.narrative_instruction = QPlainTextEdit()
        self.narrative_instruction.setPlaceholderText(
            "What should the narrator write? Opening scene, enemy tactics, "
            "battle consequences, foreshadowing, alternate plot branch...")
        self.narrative_instruction.setPlainText(
            "Narrate the immediate scene and three meaningful player-driven "
            "consequences. Preserve all tracked combat facts and established lore.")
        page.addWidget(self.narrative_instruction)
        page.addWidget(self.button("Open Local AI Narrator with Encounter Context", self.open_narrator))
        page.addStretch()

    def open_narrator(self):
        battle = self.host.battle
        facts = [
            "D&D 3.5 encounter, use ONLY provided combat facts; do not invent stats.",
            "Scene: " + battle.scene,
            f"Encounter: {battle.title}; round {battle.round}; phase {battle.phase}",
            "Roster: " + "; ".join(
                f"{f.name} ({f.kind}, HP {f.hp}/{f.max_hp}, AC {f.ac})"
                for f in battle.fighters),
            "Timed effects: " + "; ".join(
                f"{e['name']} ({e['remaining']} rounds)" for e in battle.effects),
            "Last 15 recorded combat log lines:\n" + "\n".join(battle.log[-15:]),
            "DM request: " + self.narrative_instruction.toPlainText(),
        ]
        context = "\n\n".join(facts)
        if len(context) > 6000:
            QMessageBox.warning(self, "Encounter context too large", "The complete selected encounter context exceeds 6,000 characters. Use Campaign Recall to select complete source excerpts; nothing was abbreviated.")
            return
        existing = getattr(self, "ai_dialog", None)
        if existing is not None and existing.worker is not None:
            QMessageBox.warning(self, "Scribe busy", "Wait for the current request before replacing its sources.")
            return
        if existing is None:
            self.ai_dialog = AIWritingDialog(kind="dm", context=context, parent=self)
        self.ai_dialog.load_context(context, audience="dm")
        self.ai_dialog.dm_task.setCurrentIndex(self.ai_dialog.dm_task.findData("dm_advice"))
        self.ai_dialog.setAttribute(Qt.WidgetAttribute.WA_QuitOnClose, False)
        self.ai_dialog.show()
        self.ai_dialog.raise_()
        self.ai_dialog.activateWindow()
