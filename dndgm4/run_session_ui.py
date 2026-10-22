"""A live session dashboard; all state changes go through its host controller."""
from __future__ import annotations

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtWidgets import (
    QAbstractItemView, QDialog, QHBoxLayout, QLabel, QLineEdit, QMessageBox,
    QPlainTextEdit, QPushButton, QSpinBox, QTabWidget, QTableWidget,
    QTableWidgetItem, QVBoxLayout, QWidget,
)


def _label(text=""):
    label = QLabel(text)
    label.setTextFormat(Qt.TextFormat.PlainText)
    label.setWordWrap(True)
    return label


class RunSessionDialog(QDialog):
    """Present current shared state without creating another campaign store."""

    def __init__(self, snapshot_provider, action_handler, parent=None):
        super().__init__(parent)
        self._provider = snapshot_provider
        self._handler = action_handler
        self._snapshot = None
        self._valid = False
        self._notice = ""
        self._note_workspace = None
        self._note_session_id = ""
        self._note_baseline = ""
        self._buttons = []
        self.setWindowTitle("Run Session | D&D Game Manager 4")
        self.setModal(False)
        self.setAttribute(Qt.WidgetAttribute.WA_QuitOnClose, False)
        self.resize(1040, 720)
        self.setMinimumSize(830, 540)
        root = QVBoxLayout(self)
        top = QHBoxLayout()
        self.heading = _label("RUN SESSION")
        self.heading.setObjectName("pageTitle")
        top.addWidget(self.heading, 1)
        refresh = QPushButton("Refresh")
        refresh.clicked.connect(self.refresh)
        top.addWidget(refresh)
        root.addLayout(top)
        self.message = _label()
        self.message.setAccessibleName("Dashboard status")
        root.addWidget(self.message)
        self.workspace = _label()
        root.addWidget(self.workspace)
        self.tabs = QTabWidget()
        root.addWidget(self.tabs, 1)
        session = QWidget()
        session_layout = QVBoxLayout(session)
        self.scene = QPlainTextEdit()
        self.scene.setReadOnly(True)
        self.scene.setAccessibleName("Current scene and roster")
        session_layout.addWidget(self.scene, 1)
        self.party = self._table(["Party member", "Class / level", "AC", "Maximum HP", "Encounter HP"])
        self.party.setAccessibleName("Active campaign party")
        session_layout.addWidget(self.party, 1)
        links = QHBoxLayout()
        for title, action in [("Campaigns", "campaigns"), ("Scene", "scene"), ("Add scene roster", "add_scene"), ("Add party", "add_party")]:
            links.addWidget(self._button(title, action))
        session_layout.addLayout(links)
        self.tabs.addTab(session, "Party and Scene")
        battle = QWidget()
        battle_layout = QVBoxLayout(battle)
        self.turn = _label()
        battle_layout.addWidget(self.turn)
        self.fighters = self._table(["Turn", "Combatant", "Initiative", "HP / max", "Temp HP", "AC", "Conditions"])
        self.fighters.setAccessibleName("Encounter initiative and hit points")
        battle_layout.addWidget(self.fighters, 1)
        controls = QHBoxLayout()
        for title, action in [("Roll initiative", "roll_initiative"), ("Start combat", "start"), ("Next turn", "next_turn")]:
            controls.addWidget(self._button(title, action))
        self.amount = QSpinBox()
        self.amount.setRange(1, 100000)
        self.amount.setAccessibleName("Damage or healing amount")
        controls.addWidget(self.amount)
        self.damage_button = self._button("Damage selected", "damage", selected=True)
        self.heal_button = self._button("Heal selected", "heal", selected=True)
        controls.addWidget(self.damage_button)
        controls.addWidget(self.heal_button)
        battle_layout.addLayout(controls)
        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setMaximumHeight(130)
        self.log.setAccessibleName("Recent combat log")
        battle_layout.addWidget(self.log)
        self.tabs.addTab(battle, "Combat")
        notes = QWidget()
        notes_layout = QVBoxLayout(notes)
        rolls = QHBoxLayout()
        self.expression = QLineEdit("1d20")
        self.expression.setAccessibleName("Dice expression")
        self.expression.returnPressed.connect(self._roll)
        rolls.addWidget(self.expression)
        roll = self._button("Roll", "roll")
        roll.clicked.disconnect()
        roll.clicked.connect(self._roll)
        rolls.addWidget(roll)
        for expression in ("1d20", "1d6"):
            button = self._button(expression, "roll", expression=expression)
            rolls.addWidget(button)
        notes_layout.addLayout(rolls)
        self.roll_result = _label("Roll dice at any time, including outside combat.")
        self.roll_result.setAccessibleName("Dice result")
        notes_layout.addWidget(self.roll_result)
        self.note_target = _label()
        notes_layout.addWidget(self.note_target)
        self.saved_notes = QPlainTextEdit()
        self.saved_notes.setReadOnly(True)
        self.saved_notes.setAccessibleName("Saved session notes")
        notes_layout.addWidget(self.saved_notes, 1)
        self.review_notes_button = self._button("Review latest notes", "review_notes")
        self.review_notes_button.clicked.disconnect()
        self.review_notes_button.clicked.connect(self.review_latest_notes)
        notes_layout.addWidget(self.review_notes_button)
        self.note = QPlainTextEdit()
        self.note.setPlaceholderText("Draft a quick note, then append it to the session journal.")
        self.note.setAccessibleName("Quick session note draft")
        self.note_input = self.note
        notes_layout.addWidget(self.note, 1)
        self.save_button = self._button("Append to Session", "save_note")
        self.save_button.clicked.disconnect()
        self.save_button.clicked.connect(self._save_note)
        notes_layout.addWidget(self.save_button)
        self.note.textChanged.connect(self._sync_buttons)
        self.tabs.addTab(notes, "Rolls and Notes")
        navigation = QHBoxLayout()
        for title, action in [("Battle", "battle"), ("Rules", "rules"), ("Scribe", "scribe"), ("Maps", "maps"), ("Time", "time"), ("Resources", "resources")]:
            navigation.addWidget(self._button(title, action))
        root.addLayout(navigation)
        self.fighters.itemSelectionChanged.connect(self._sync_buttons)
        self.timer = QTimer(self)
        self.timer.setInterval(1000)
        self.timer.timeout.connect(self.refresh)
        self.refresh()

    @staticmethod
    def _table(headers):
        table = QTableWidget(0, len(headers))
        table.setHorizontalHeaderLabels(headers)
        table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        table.horizontalHeader().setStretchLastSection(True)
        return table

    def _button(self, title, action, selected=False, **kwargs):
        button = QPushButton(title)
        button.setAccessibleName(title)
        button.clicked.connect(lambda _checked=False: self._act(action, selected=selected, **kwargs))
        self._buttons.append(button)
        return button

    def _selected_id(self):
        row = self.fighters.currentRow()
        item = self.fighters.item(row, 0) if row >= 0 else None
        return item.data(Qt.ItemDataRole.UserRole) if item else None

    def _sync_buttons(self):
        for button in self._buttons:
            button.setEnabled(self._valid)
        self.damage_button.setEnabled(self._valid and bool(self._selected_id()))
        self.heal_button.setEnabled(self._valid and bool(self._selected_id()))
        self.save_button.setEnabled(self._valid and bool(self._note_session_id) and bool(self.note.toPlainText().strip()))
        self.review_notes_button.setEnabled(self._valid and bool(self._note_session_id) and self._snapshot is not None and tuple(self._snapshot["workspace_key"]) == self._note_workspace)

    def _act(self, action, selected=False, **kwargs):
        if not self._valid:
            return False
        if selected:
            combatant_id = self._selected_id()
            if not combatant_id:
                return False
            kwargs.update(combatant_id=combatant_id, amount=self.amount.value())
        self._notice = ""
        try:
            result = self._handler(action, **kwargs)
        except Exception as exc:
            self._notice = f"Action failed: {exc}"
            self.message.setText(self._notice)
            return False
        self.refresh()
        if result:
            if action == "roll":
                self.roll_result.setText(str(result))
            else:
                self._notice = str(result)
                self.message.setText(self._notice)
        return True

    def _roll(self):
        self._act("roll", expression=self.expression.text().strip())

    def review_latest_notes(self):
        """Explicitly review a changed journal while retaining the draft."""
        self.refresh()
        if not self._valid or not self._snapshot or tuple(self._snapshot["workspace_key"]) != self._note_workspace:
            return False
        self._note_baseline = self._snapshot.get("session_notes", "")
        self.saved_notes.setPlainText(self._note_baseline)
        self._notice = "Latest saved notes shown above. Review them, then append your draft when ready."
        self.message.setText(self._notice)
        return True

    def _save_note(self):
        note = self.note.toPlainText().strip()
        if not self._valid or not self._note_session_id or not note:
            return False
        try:
            self._handler("save_note", session_id=self._note_session_id,
                          note=note, expected_notes=self._note_baseline)
        except Exception as exc:
            self._notice = f"Note was not saved; draft retained: {exc}. If the journal changed, use Review latest notes before retrying."
            self.message.setText(self._notice)
            return False
        self.note.clear()
        self._note_workspace = None
        self.refresh()
        self._notice = "Note appended to the session journal."
        self.message.setText(self._notice)
        return True

    def prepare_workspace_change(self):
        """Resolve the draft before the host changes campaign/session/encounter."""
        if not self.note.toPlainText().strip():
            return True
        choice = QMessageBox.question(
            self, "Unsaved session note", "Save this note before changing workspace?",
            QMessageBox.StandardButton.Save | QMessageBox.StandardButton.Discard | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel,
        )
        if choice == QMessageBox.StandardButton.Save:
            return self._save_note()
        if choice == QMessageBox.StandardButton.Discard:
            self.note.clear()
            self._note_workspace = None
            return True
        return False

    def refresh(self):
        try:
            snapshot = self._provider()
            # Validate the minimum contract before touching any existing display.
            workspace = tuple(snapshot["workspace_key"])
            party, fighters = snapshot["party"], snapshot["fighters"]
            for row in party + fighters:
                row["id"]
        except Exception as exc:
            self._valid = False
            self.message.setText(f"Cannot refresh session: {exc}. Existing view and draft retained.")
            self._sync_buttons()
            return
        selected = self._selected_id()
        self._snapshot = snapshot
        self._valid = True
        self.workspace.setText(f"{snapshot.get('campaign_name', 'Standalone')} • {snapshot.get('session_title', 'No active session')} • {snapshot.get('session_status', '')}")
        self.scene.setPlainText("\n".join(str(value) for value in (
            snapshot.get("scene_title", ""), snapshot.get("scene_location", ""), snapshot.get("scene_text", ""),
            "Scene roster: " + ", ".join(snapshot.get("scene_roster", [])),
        ) if value))
        self.party.setRowCount(len(party))
        for index, row in enumerate(party):
            values = [row.get("name", ""), f"{row.get('character_class', '')} / {row.get('level', '')}", row.get("ac", ""), row.get("max_hp", ""), row.get("encounter_hp", "")]
            for column, value in enumerate(values):
                self.party.setItem(index, column, QTableWidgetItem(str(value)))
        self.fighters.clearSelection()
        self.fighters.setCurrentCell(-1, -1)
        self.fighters.setRowCount(len(fighters))
        for index, row in enumerate(fighters):
            marker = "▶ Current" if row.get("current") else ("" if row.get("active", True) else "Inactive")
            values = [marker, row.get("name", ""), row.get("initiative") if row.get("initiative") is not None else "—", f"{row.get('hp', '')} / {row.get('max_hp', '')}", row.get("temp_hp", 0), row.get("ac", ""), row.get("conditions", "")]
            for column, value in enumerate(values):
                item = QTableWidgetItem(str(value))
                item.setData(Qt.ItemDataRole.UserRole, row["id"])
                self.fighters.setItem(index, column, item)
            if row["id"] == selected:
                self.fighters.selectRow(index)
        self.turn.setText(f"{snapshot.get('encounter_title', '')} • {snapshot.get('phase', '')} • Round {snapshot.get('round', 0)} • Current: {snapshot.get('current_name', '')}")
        self.log.setPlainText("\n".join(snapshot.get("combat_log", [])[-30:]))
        dirty = bool(self.note.toPlainText().strip())
        if not dirty:
            self._note_workspace = workspace
            self._note_session_id = snapshot.get("session_id", "")
            self._note_baseline = snapshot.get("session_notes", "")
            self.saved_notes.setPlainText(self._note_baseline)
            self.note_target.setText(f"Note destination: {snapshot.get('session_title', '')}" if self._note_session_id else "Select a saved session to append notes.")
        if dirty and workspace != self._note_workspace:
            self.message.setText("Workspace changed. Draft still belongs to its original session; save or discard it before drafting for this session.")
        else:
            self.message.setText(self._notice)
        self._sync_buttons()

    def showEvent(self, event):
        super().showEvent(event)
        self.refresh()
        self.timer.start()

    def hideEvent(self, event):
        self.timer.stop()
        super().hideEvent(event)

    def closeEvent(self, event):
        if self.prepare_workspace_change():
            event.accept()
        else:
            event.ignore()
