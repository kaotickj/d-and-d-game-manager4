"""PyQt6 application for permanent character/NPC/monster library records."""
from dataclasses import replace

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFormLayout,
    QHBoxLayout, QHeaderView, QLabel, QLineEdit, QMainWindow,
    QMessageBox, QPushButton, QScrollArea, QSpinBox, QTableWidget,
    QTableWidgetItem, QTextEdit, QVBoxLayout, QWidget,
)

from .models import Creature, KIND_LABELS
from .storage import CreatureRepository


class CreatureEditor(QDialog):
    def __init__(self, creature: Creature, parent=None):
        super().__init__(parent)
        self.original = creature
        self.result_creature = None
        self.setWindowTitle("Edit entry" if creature.id else "New entry")
        self.resize(560, 650)
        layout = QVBoxLayout(self)
        heading = QLabel(KIND_LABELS[creature.kind])
        heading.setStyleSheet("font-size: 17px; font-weight: bold")
        layout.addWidget(heading)
        form_holder = QWidget()
        form = QFormLayout(form_holder)
        self.name = QLineEdit(creature.name)
        self.name.setMaxLength(200)
        form.addRow("Name *", self.name)
        self.race_type = QLineEdit(creature.race_type)
        form.addRow("Race / Creature type", self.race_type)
        self.character_class = QLineEdit(creature.character_class)
        form.addRow("Class / Classes", self.character_class)
        self.level = self.spin(creature.level, 0, 99)
        form.addRow("Level", self.level)
        self.cr = QLineEdit(creature.challenge_rating)
        form.addRow("Challenge rating", self.cr)
        self.ac = self.spin(creature.armor_class, 0, 999)
        form.addRow("Armor class", self.ac)
        self.hp = self.spin(creature.max_hit_points, 0, 999999)
        form.addRow("Maximum HP", self.hp)
        self.abilities = {}
        for attribute in (
            "strength", "dexterity", "constitution",
            "intelligence", "wisdom", "charisma"
        ):
            widget = self.spin(getattr(creature, attribute), 0, 99)
            form.addRow(attribute.title(), widget)
            self.abilities[attribute] = widget
        self.notes = QTextEdit()
        self.notes.setPlainText(creature.notes)
        self.notes.setMinimumHeight(110)
        form.addRow("Notes", self.notes)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(form_holder)
        layout.addWidget(scroll)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save |
            QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.save)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    @staticmethod
    def spin(value, minimum, maximum):
        widget = QSpinBox()
        widget.setRange(minimum, maximum)
        widget.setValue(value)
        return widget

    def save(self):
        if not self.name.text().strip():
            QMessageBox.warning(self, "Name required", "Enter a name.")
            self.name.setFocus()
            return
        self.result_creature = replace(
            self.original,
            name=self.name.text().strip(),
            race_type=self.race_type.text().strip(),
            character_class=self.character_class.text().strip(),
            level=self.level.value(),
            challenge_rating=self.cr.text().strip(),
            armor_class=self.ac.value(),
            max_hit_points=self.hp.value(),
            notes=self.notes.toPlainText(),
            **{key: value.value() for key, value in self.abilities.items()},
        )
        self.accept()


class MainWindow(QMainWindow):
    def __init__(self, library: CreatureRepository):
        super().__init__()
        self.library = library
        self.setWindowTitle("Dungeons & Dragons Game Manager 4")
        self.resize(1100, 690)
        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        heading = QLabel("Character & Monster Library")
        heading.setStyleSheet("font-weight: bold; font-size: 23px")
        root.addWidget(heading)

        filters = QHBoxLayout()
        self.search = QLineEdit()
        self.search.setClearButtonEnabled(True)
        self.search.setPlaceholderText("Search name, class, race/type or notes")
        self.search.textChanged.connect(self.refresh)
        filters.addWidget(self.search)
        self.kind_filter = QComboBox()
        for label, data in (
            ("All entries", None), ("Characters", "pc"),
            ("NPCs", "npc"), ("Monsters", "monster")
        ):
            self.kind_filter.addItem(label, data)
        self.kind_filter.currentIndexChanged.connect(self.refresh)
        filters.addWidget(self.kind_filter)
        self.show_archived = QCheckBox("Show archived")
        self.show_archived.toggled.connect(self.refresh)
        filters.addWidget(self.show_archived)
        root.addLayout(filters)

        self.table = QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels(
            ("Name", "Category", "Race / Type", "Class", "Level / CR", "Status")
        )
        self.table.setAlternatingRowColors(True)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.ResizeMode.Stretch
        )
        for column in range(1, 6):
            self.table.horizontalHeader().setSectionResizeMode(
                column, QHeaderView.ResizeMode.ResizeToContents
            )
        self.table.doubleClicked.connect(self.edit)
        root.addWidget(self.table)

        actions = QHBoxLayout()
        for label, kind in (
            ("New Character", "pc"), ("New NPC", "npc"), ("New Monster", "monster")
        ):
            button = QPushButton(label)
            button.clicked.connect(lambda checked=False, k=kind: self.create(k))
            actions.addWidget(button)
        for label, callback in (
            ("Edit", self.edit),
            ("Duplicate", self.duplicate),
            ("Archive / Restore", self.toggle_archive),
        ):
            button = QPushButton(label)
            button.clicked.connect(callback)
            actions.addWidget(button)
        root.addLayout(actions)
        self.statusBar().showMessage("Library: " + str(self.library.path))
        self.refresh()

    def refresh(self, *args):
        records = self.library.list(
            kind=self.kind_filter.currentData(),
            query=self.search.text(),
            include_archived=self.show_archived.isChecked(),
        )
        self.table.setRowCount(len(records))
        for row, record in enumerate(records):
            texts = (
                record.name, KIND_LABELS[record.kind], record.race_type,
                record.character_class,
                record.challenge_rating if record.kind == "monster"
                else str(record.level),
                "Archived" if record.archived else "Active",
            )
            for column, text in enumerate(texts):
                item = QTableWidgetItem(text)
                if column == 0:
                    item.setData(Qt.ItemDataRole.UserRole, record.id)
                self.table.setItem(row, column, item)

    def selected(self):
        row = self.table.currentRow()
        if row < 0:
            return None
        item = self.table.item(row, 0)
        if item is None:
            return None
        return self.library.get(item.data(Qt.ItemDataRole.UserRole))

    def persist(self, record):
        try:
            self.library.save(record)
        except Exception as error:
            QMessageBox.critical(self, "Save failed", str(error))
            return
        self.refresh()

    def create(self, kind):
        dialog = CreatureEditor(Creature(name="", kind=kind), self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.persist(dialog.result_creature)

    def edit(self, *args):
        record = self.selected()
        if record is None:
            return
        dialog = CreatureEditor(record, self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.persist(dialog.result_creature)

    def duplicate(self, *args):
        record = self.selected()
        if record is not None:
            self.persist(record.duplicate())

    def toggle_archive(self, *args):
        record = self.selected()
        if record is not None:
            self.library.set_archived(record.id, not record.archived)
            self.refresh()
