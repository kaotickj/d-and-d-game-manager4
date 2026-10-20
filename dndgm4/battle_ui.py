"""Battle Trakker: integrated encounter/initiative manager for D&D 3.5.

Modeless child window. Combat snapshots never update permanent SQLite sheets.
The original Compendium, its banner and ability-score grid are untouched.
"""
from __future__ import annotations

from pathlib import Path
from uuid import uuid4

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import (
    QAbstractItemView, QCheckBox, QComboBox, QDialog, QDialogButtonBox,
    QFormLayout, QGridLayout, QGroupBox, QHBoxLayout, QLabel, QLineEdit,
    QListWidget, QListWidgetItem, QMessageBox, QPlainTextEdit, QPushButton,
    QSpinBox, QSplitter, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

from .battle_rules import (
    Battle, BattleStore, Fighter, CONDITIONS, fighter_from_record
)
from .storage import CreatureRepository


class LibraryCombatantsDialog(QDialog):
    """Select multiple saved records, with separate quantity per species."""
    def __init__(self, records, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_QuitOnClose, False)
        self.setWindowTitle("Add Library Combatants")
        self.resize(670, 520)
        root = QVBoxLayout(self)
        header = QLabel("Select PCs, NPCs and monsters from the Compendium")
        header.setObjectName("sectionTitle")
        root.addWidget(header)
        hint = QLabel("Select several rows with Ctrl/Shift. Add multiple copies of "
                      "the same monster using the quantity control. Each copy has "
                      "its own hit points and initiative.")
        hint.setWordWrap(True)
        root.addWidget(hint)
        self.records = records
        self.listbox = QListWidget()
        self.listbox.setSelectionMode(
            QAbstractItemView.SelectionMode.ExtendedSelection)
        for record in records:
            item = QListWidgetItem(
                f"{record.name}   ·   {record.kind.upper()}   ·   "
                f"AC {record.armor_class}   ·   HP {record.max_hit_points}")
            item.setData(Qt.ItemDataRole.UserRole, record.id)
            self.listbox.addItem(item)
        root.addWidget(self.listbox, 1)
        footer = QHBoxLayout()
        footer.addWidget(QLabel("Copies per selected record"))
        self.quantity = QSpinBox()
        self.quantity.setRange(1, 20)
        self.quantity.setValue(1)
        footer.addWidget(self.quantity)
        footer.addStretch()
        root.addLayout(footer)
        controls = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok |
            QDialogButtonBox.StandardButton.Cancel)
        controls.accepted.connect(self.accept)
        controls.rejected.connect(self.reject)
        root.addWidget(controls)

    def chosen(self):
        ids = {item.data(Qt.ItemDataRole.UserRole)
               for item in self.listbox.selectedItems()}
        return [record for record in self.records if record.id in ids]


class CustomCombatantDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_QuitOnClose, False)
        self.setWindowTitle("Add Custom Combatant")
        form = QFormLayout(self)
        self.name = QLineEdit()
        self.name.setPlaceholderText("Creature / ally / hazard name")
        form.addRow("Name", self.name)
        self.hp = QSpinBox()
        self.hp.setRange(1, 999999)
        self.hp.setValue(10)
        form.addRow("Maximum HP", self.hp)
        self.ac = QSpinBox()
        self.ac.setRange(-99, 999)
        self.ac.setValue(10)
        form.addRow("Armor Class", self.ac)
        self.dex = QSpinBox()
        self.dex.setRange(-99, 99)
        form.addRow("Dexterity modifier", self.dex)
        self.mod = QSpinBox()
        self.mod.setRange(-100, 100)
        self.mod.setToolTip("Total initiative modifier: Dexterity + feat + misc.")
        form.addRow("Total initiative modifier", self.mod)
        self.dex.valueChanged.connect(self._suggest_modifier)
        self.surprised = QCheckBox("Surprised (cannot act in surprise round)")
        form.addRow("", self.surprised)
        actions = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok |
            QDialogButtonBox.StandardButton.Cancel)
        actions.accepted.connect(self.check)
        actions.rejected.connect(self.reject)
        form.addRow(actions)

    def _suggest_modifier(self, value):
        self.mod.setValue(value)

    def check(self):
        if not self.name.text().strip():
            QMessageBox.warning(self, "Name required", "Enter a combatant name.")
            return
        self.accept()

    def fighter(self):
        return Fighter(
            uid=str(uuid4()), name=self.name.text().strip(), kind="custom",
            max_hp=self.hp.value(), hp=self.hp.value(), ac=self.ac.value(),
            dex_mod=self.dex.value(), init_mod=self.mod.value(),
            surprised=self.surprised.isChecked())


class BattleTrakkerDialog(QDialog):
    """One independently autosaved encounter with live initiative and HP."""

    def __init__(self, library: CreatureRepository, parent=None, *,
                 scene: dict | None = None):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_QuitOnClose, False)
        self.setWindowTitle("Battle Trakker | D&D 3.5 Combat Manager")
        self.resize(1200, 810)
        self.setMinimumSize(790, 570)
        self.library = library
        self.store = BattleStore(library.path)
        self.battle = self.store.load()  # never overwrite malformed saves
        self.scene = scene or {}
        root = QVBoxLayout(self)
        root.setContentsMargins(16, 15, 16, 13)
        root.setSpacing(9)
        heading = QLabel("BATTLE TRAKKER  /  COMBAT & ENCOUNTERS")
        heading.setObjectName("pageTitle")
        root.addWidget(heading)
        intro = QLabel(
            "D&D 3.5 turn order, surprise, HP, conditions, and encounter history. "
            "Combat changes remain separate from permanent character sheets.")
        intro.setObjectName("muted")
        intro.setWordWrap(True)
        root.addWidget(intro)
        title_line = QHBoxLayout()
        title_line.addWidget(QLabel("Encounter"))
        self.encounter_title = QLineEdit(self.battle.title)
        self.encounter_title.setAccessibleName("Battle encounter title")
        title_line.addWidget(self.encounter_title, 1)
        self.save_button = QPushButton("Save Encounter")
        self.save_button.clicked.connect(self.save)
        title_line.addWidget(self.save_button)
        root.addLayout(title_line)

        toolbar = QHBoxLayout()
        self.library_button = QPushButton("Add from Library")
        self.library_button.clicked.connect(self.add_from_library)
        toolbar.addWidget(self.library_button)
        self.selection_button = QPushButton("Add Selected Records")
        self.selection_button.clicked.connect(self.add_selected)
        toolbar.addWidget(self.selection_button)
        self.scene_button = QPushButton("Add Scene Roster")
        self.scene_button.clicked.connect(self.add_scene)
        toolbar.addWidget(self.scene_button)
        self.custom_button = QPushButton("+ Custom")
        self.custom_button.clicked.connect(self.add_custom)
        toolbar.addWidget(self.custom_button)
        self.remove_button = QPushButton("Remove")
        self.remove_button.clicked.connect(self.remove_selected)
        toolbar.addWidget(self.remove_button)
        toolbar.addStretch()
        root.addLayout(toolbar)

        self.header = QLabel()
        self.header.setObjectName("sectionTitle")
        root.addWidget(self.header)
        main_split = QSplitter(Qt.Orientation.Vertical)
        root.addWidget(main_split, 1)
        roster = QWidget()
        roster_layout = QVBoxLayout(roster)
        roster_layout.setContentsMargins(0, 0, 0, 0)
        self.table = QTableWidget(0, 9)
        self.table.setHorizontalHeaderLabels(
            ["Turn", "Combatant", "Kind", "Initiative", "HP",
             "Temp", "AC", "Conditions", "Status"])
        self.table.setSelectionBehavior(
            QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(
            QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setEditTriggers(
            QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.setColumnWidth(0, 55)
        self.table.setColumnWidth(1, 195)
        self.table.setColumnWidth(2, 76)
        self.table.setColumnWidth(3, 90)
        self.table.setColumnWidth(4, 98)
        self.table.setColumnWidth(5, 60)
        self.table.setColumnWidth(6, 70)
        self.table.setColumnWidth(7, 190)
        self.table.selectionModel().selectionChanged.connect(
            lambda *_: self.refresh_selection())
        roster_layout.addWidget(self.table, 1)
        main_split.addWidget(roster)

        lower = QWidget()
        lower_layout = QVBoxLayout(lower)
        lower_layout.setContentsMargins(2, 5, 2, 2)
        lower_layout.setSpacing(8)
        turn_controls = QHBoxLayout()
        self.roll_button = QPushButton("Roll All Initiative")
        self.roll_button.setObjectName("primaryButton")
        self.roll_button.clicked.connect(self.roll_initiative)
        turn_controls.addWidget(self.roll_button)
        turn_controls.addWidget(QLabel("Manual init"))
        self.initiative_input = QSpinBox()
        self.initiative_input.setRange(-999, 999)
        turn_controls.addWidget(self.initiative_input)
        manual_button = QPushButton("Set")
        manual_button.clicked.connect(self.set_initiative)
        turn_controls.addWidget(manual_button)
        self.start_button = QPushButton("Start Encounter")
        self.start_button.clicked.connect(self.start)
        turn_controls.addWidget(self.start_button)
        self.next_button = QPushButton("Next Turn")
        self.next_button.setObjectName("primaryButton")
        self.next_button.clicked.connect(self.advance)
        turn_controls.addWidget(self.next_button)
        self.undo_button = QPushButton("Undo Last Action")
        self.undo_button.clicked.connect(self.undo)
        turn_controls.addWidget(self.undo_button)
        turn_controls.addStretch()
        lower_layout.addLayout(turn_controls)

        hp_row = QHBoxLayout()
        hp_row.addWidget(QLabel("HP adjustment"))
        self.hp_amount = QSpinBox()
        self.hp_amount.setRange(1, 999999)
        self.hp_amount.setValue(1)
        hp_row.addWidget(self.hp_amount)
        damage_button = QPushButton("Damage")
        damage_button.clicked.connect(self.damage)
        hp_row.addWidget(damage_button)
        healing_button = QPushButton("Heal")
        healing_button.clicked.connect(self.heal)
        hp_row.addWidget(healing_button)
        hp_row.addWidget(QLabel("Current HP"))
        self.hp_value = QSpinBox()
        self.hp_value.setRange(-999999, 999999)
        hp_row.addWidget(self.hp_value)
        sethp = QPushButton("Set HP")
        sethp.clicked.connect(self.override_hp)
        hp_row.addWidget(sethp)
        hp_row.addWidget(QLabel("Temp HP"))
        self.temp_value = QSpinBox()
        self.temp_value.setRange(0, 999999)
        hp_row.addWidget(self.temp_value)
        temp_button = QPushButton("Set Temp")
        temp_button.clicked.connect(self.override_temp)
        hp_row.addWidget(temp_button)
        hp_row.addStretch()
        lower_layout.addLayout(hp_row)

        condition_row = QHBoxLayout()
        condition_row.addWidget(QLabel("Condition"))
        self.condition = QComboBox()
        self.condition.setEditable(True)
        self.condition.addItems(CONDITIONS)
        self.condition.setAccessibleName("Condition or custom status")
        condition_row.addWidget(self.condition, 1)
        condition_row.addWidget(QLabel("Turns"))
        self.duration = QSpinBox()
        self.duration.setRange(0, 9999)
        self.duration.setSpecialValueText("Indefinite")
        self.duration.setToolTip(
            "Duration decreases at the end of this combatant's own turn.")
        condition_row.addWidget(self.duration)
        apply_condition = QPushButton("Apply / Update")
        apply_condition.clicked.connect(self.apply_condition)
        condition_row.addWidget(apply_condition)
        clear_condition = QPushButton("Remove Condition")
        clear_condition.clicked.connect(self.remove_condition)
        condition_row.addWidget(clear_condition)
        self.surprised = QCheckBox("Surprised")
        self.surprised.clicked.connect(self.toggle_surprised)
        condition_row.addWidget(self.surprised)
        self.active = QCheckBox("Active")
        self.active.clicked.connect(self.toggle_active)
        condition_row.addWidget(self.active)
        lower_layout.addLayout(condition_row)

        log_heading = QHBoxLayout()
        log_heading.addWidget(QLabel("Combat Log"))
        note_button = QPushButton("Add DM Note")
        note_button.clicked.connect(self.add_log_note)
        log_heading.addWidget(note_button)
        finish_button = QPushButton("End Encounter")
        finish_button.clicked.connect(self.finish)
        log_heading.addWidget(finish_button)
        reset_button = QPushButton("New / Reset Encounter")
        reset_button.clicked.connect(self.reset)
        log_heading.addWidget(reset_button)
        lower_layout.addLayout(log_heading)
        self.note_input = QLineEdit()
        self.note_input.setPlaceholderText(
            "Quick note, attack roll, spell effect, save result...")
        self.note_input.returnPressed.connect(self.add_log_note)
        lower_layout.addWidget(self.note_input)
        self.log_display = QPlainTextEdit()
        self.log_display.setReadOnly(True)
        self.log_display.setMinimumHeight(72)
        lower_layout.addWidget(self.log_display, 1)
        main_split.addWidget(lower)
        main_split.setSizes([345, 330])
        bottom = QHBoxLayout()
        self.detail = QLabel()
        self.detail.setObjectName("muted")
        self.detail.setWordWrap(True)
        bottom.addWidget(self.detail, 1)
        close = QPushButton("Close Battle Trakker")
        close.clicked.connect(self.close)
        bottom.addWidget(close)
        root.addLayout(bottom)
        self.render()

    def closeEvent(self, event):
        # MainWindow owns this reusable, nonmodal window.
        # Never terminate QApplication from a secondary window.
        self.hide()
        event.ignore()

    def set_scene(self, scene: dict):
        self.scene = scene or {}

    def _save(self):
        self.battle.title = self.encounter_title.text().strip() or "New Encounter"
        self.store.save(self.battle)

    def save(self):
        try:
            self._save()
            self.detail.setText("Encounter saved locally: " + str(self.store.path))
        except (ValueError, OSError) as exc:
            QMessageBox.warning(self, "Encounter save failed", str(exc))

    def _run(self, callback, *, select_id=None):
        try:
            result = callback()
            self._save()  # also autosave each action so a crash won't erase play
            self.render(select_id=select_id)
            return result
        except (ValueError, OSError) as exc:
            QMessageBox.warning(self, "Battle Trakker", str(exc))
            self.render()
            return None

    def _selected_id(self):
        rows = self.table.selectionModel().selectedRows()
        if not rows:
            raise ValueError("Select a combatant in the encounter table.")
        item = self.table.item(rows[0].row(), 1)
        if item is None:
            raise ValueError("Select a combatant.")
        return item.data(Qt.ItemDataRole.UserRole)

    def _selected(self):
        return self.battle.get(self._selected_id())

    def _add_records(self, records, quantity=1):
        if not records:
            raise ValueError("No library records selected.")
        if len(self.battle.fighters)+len(records)*quantity > 120:
            raise ValueError("Too many combatants. Limit: 120.")
        for record in records:
            for copy_index in range(1,quantity+1):
                label = (f"{record.name} #{copy_index}" if quantity>1
                         else record.name)
                self.battle.add(fighter_from_record(record,name=label))

    def add_selected(self):
        window = self.parent()
        records = window.selected_records() if hasattr(window, "selected_records") else []
        self._run(lambda: self._add_records(records))

    def add_from_library(self):
        dialog = LibraryCombatantsDialog(self.library.list(), self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            records = dialog.chosen()
            self._run(lambda: self._add_records(records,dialog.quantity.value()))

    def add_scene(self):
        index = {record.id: record for record in self.library.list()}
        ids = self.scene.get("record_ids", [])
        if not ids:
            QMessageBox.information(
                self, "No scene members", "Use Add Selected to Scene or Edit Scene "
                "in the main Compendium, then reopen Battle Trakker.")
            return
        missing = [uid for uid in ids if uid not in index]
        if missing:
            QMessageBox.warning(self, "Incomplete scene",
                f"{len(missing)} scene record(s) are archived or missing. "
                "Please edit the scene roster before adding them.")
            return
        def perform():
            if not self.battle.fighters:
                self.battle.scene = (
                    f"{self.scene.get('location','')}\n"
                    f"{self.scene.get('time_conditions','')}\n"
                    f"{self.scene.get('scenery','')}\n"
                    f"{self.scene.get('campaign_notes','')}"
                ).strip()[:12000]
            self._add_records([index[uid] for uid in ids])
        self._run(perform)

    def add_custom(self):
        dialog = CustomCombatantDialog(self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self._run(lambda: self.battle.add(dialog.fighter()))

    def remove_selected(self):
        try:
            uid = self._selected_id()
        except ValueError as exc:
            QMessageBox.information(self, "Select combatant", str(exc))
            return
        self._run(lambda: self.battle.remove(uid))

    def roll_initiative(self):
        self._run(self.battle.roll_initiatives)

    def set_initiative(self):
        self._run(lambda: self.battle.set_initiative(
            self._selected_id(), self.initiative_input.value()))

    def start(self):
        self._run(self.battle.begin)

    def advance(self):
        self._run(self.battle.advance)

    def damage(self):
        self._run(lambda: self.battle.change_hp(
            self._selected_id(),self.hp_amount.value()))

    def heal(self):
        self._run(lambda: self.battle.change_hp(
            self._selected_id(),self.hp_amount.value(),heal=True))

    def override_hp(self):
        self._run(lambda: self.battle.set_hp(
            self._selected_id(),self.hp_value.value()))

    def override_temp(self):
        self._run(lambda: self.battle.set_temp_hp(
            self._selected_id(),self.temp_value.value()))

    def apply_condition(self):
        self._run(lambda: self.battle.set_condition(
            self._selected_id(),self.condition.currentText().strip(),
            self.duration.value() or None))

    def remove_condition(self):
        self._run(lambda: self.battle.clear_condition(
            self._selected_id(),self.condition.currentText().strip()))

    def toggle_surprised(self, checked):
        self._run(lambda: self.battle.set_surprised(
            self._selected_id(), checked))

    def toggle_active(self, checked):
        self._run(lambda: self.battle.set_active(
            self._selected_id(), checked))

    def add_log_note(self):
        note = self.note_input.text().strip()
        if not note:
            return
        def perform():
            self.battle._remember()
            self.battle.note("DM: " + note[:5000])
        self._run(perform)
        self.note_input.clear()

    def undo(self):
        if not self.battle.undo():
            QMessageBox.information(self, "Nothing to undo",
                                    "No previous action in this session.")
            return
        self.save()
        self.render()

    def finish(self):
        if self.battle.phase not in ("combat", "surprise"):
            QMessageBox.information(self, "No running encounter",
                                    "Start the encounter first.")
            return
        self._run(self.battle.finish)

    def reset(self):
        answer = QMessageBox.question(
            self, "Start a new encounter?",
            "Replace the active encounter and its combat log? This can't be "
            "undone after you close Battle Trakker.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No)
        if answer != QMessageBox.StandardButton.Yes:
            return
        def perform():
            self.battle = Battle()
            self.encounter_title.setText(self.battle.title)
        self._run(perform)

    def refresh_selection(self):
        try:
            fighter = self._selected()
        except ValueError:
            self.detail.setText("Select a combatant to adjust HP, initiative, or conditions.")
            return
        self.initiative_input.setValue(fighter.initiative or 0)
        self.hp_value.setValue(fighter.hp)
        self.temp_value.setValue(fighter.temp_hp)
        self.surprised.blockSignals(True)
        self.active.blockSignals(True)
        self.surprised.setChecked(fighter.surprised)
        self.active.setChecked(fighter.active)
        self.surprised.blockSignals(False)
        self.active.blockSignals(False)
        statuses = ", ".join(
            f"{c['name']} ({c['rounds'] if c['rounds'] is not None else '∞'})"
            for c in fighter.conditions) or "None"
        self.detail.setText(
            f"{fighter.name} · AC {fighter.ac} · Initiative mod "
            f"{fighter.init_mod:+} · {fighter.status()} · "
            f"Conditions: {statuses}")

    def render(self, *, select_id=None):
        try:
            select_id = select_id or self._selected_id()
        except ValueError:
            select_id = self.battle.current_id
        ordered = self.battle.order()
        # Show every member, including inactive and surprised ones, even
        # though only eligible combatants receive turns in the current phase.
        used = {f.uid for f in ordered}
        arranged = ordered + [f for f in self.battle.fighters if f.uid not in used]
        self.table.blockSignals(True)
        try:
            self.table.setRowCount(len(arranged))
            for row, fighter in enumerate(arranged):
                turn = ("▶" if fighter.uid == self.battle.current_id
                        and self.battle.phase in ("surprise","combat") else "")
                if self.battle.phase=="surprise" and fighter.surprised:
                    turn = "—"
                statuses = ", ".join(
                    f"{entry['name']}({entry['rounds'] if entry['rounds'] is not None else '∞'})"
                    for entry in fighter.conditions)
                values = [
                    turn, fighter.name, fighter.kind.upper(),
                    "—" if fighter.initiative is None else str(fighter.initiative),
                    f"{fighter.hp} / {fighter.max_hp}",
                    str(fighter.temp_hp), str(fighter.ac),
                    statuses, fighter.status() if fighter.active else "Inactive",
                ]
                for col, text in enumerate(values):
                    item = QTableWidgetItem(text)
                    if col==1:
                        item.setData(Qt.ItemDataRole.UserRole,fighter.uid)
                    item.setToolTip(text)
                    if fighter.uid==self.battle.current_id:
                        item.setBackground(QColor("#514631"))
                    elif fighter.hp <= 0:
                        item.setBackground(QColor("#482c2b"))
                    self.table.setItem(row,col,item)
            self.table.clearSelection()
            for row, fighter in enumerate(arranged):
                if fighter.uid==select_id:
                    self.table.selectRow(row)
                    break
        finally:
            self.table.blockSignals(False)
        phase = {"setup":"Ready", "surprise":"Surprise round",
                 "combat":f"Round {self.battle.round}",
                 "finished":"Encounter ended"}[self.battle.phase]
        current = (self.battle.get(self.battle.current_id).name
                   if self.battle.current_id else "—")
        self.header.setText(
            f"{phase}   ·   Current turn: {current}   ·   "
            f"{len(self.battle.fighters)} combatant(s)")
        self.start_button.setEnabled(self.battle.phase in ("setup","finished"))
        self.next_button.setEnabled(
            self.battle.phase in ("combat","surprise") and
            bool(self.battle.current_id))
        self.undo_button.setEnabled(bool(self.battle._history))
        self.log_display.setPlainText("\n".join(self.battle.log))
        self.log_display.verticalScrollBar().setValue(
            self.log_display.verticalScrollBar().maximum())
        self.refresh_selection()
