"""Reusable name picker for the Character Forge and Monster Maker.

Uses RPG Name Genie 2.4's curated naming banks through NameEngine. The
dialog only returns a selected name. It never writes to the source database.
"""
from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QApplication, QComboBox, QDialog, QHBoxLayout, QLabel, QListWidget,
    QMessageBox, QPushButton, QVBoxLayout,
)

from .namegen import (ALL_KINDS, CORE_RACES, EXPANDED_RACES, GENDERS,
                      MONSTER_RACES, NameEngine, UnsupportedCreature,
                      family_for)


class NamePickerDialog(QDialog):
    def __init__(self, *, race: str = "Human", monster: bool = False,
                 engine: NameEngine | None = None, parent=None,
                 standalone: bool = False):
        super().__init__(parent)
        self.setWindowTitle("RPG Name Genie | D&D Game Manager 4")
        self.resize(610, 610)
        self.setMinimumSize(520, 460)
        self.engine = engine or NameEngine()
        self.selected_name: str | None = None
        self.is_monster = monster
        self.standalone = standalone

        outer = QVBoxLayout(self)
        outer.setContentsMargins(22, 20, 22, 20)
        outer.setSpacing(12)
        eyebrow = QLabel("THE GAME MASTER'S DESK / RPG NAME GENIE")
        eyebrow.setObjectName("eyebrow")
        outer.addWidget(eyebrow)
        title = QLabel("The Naming Chamber")
        title.setObjectName("pageTitle")
        outer.addWidget(title)
        intro = QLabel(
            "Choose a D&D 3.5 race or creature, then refine its naming style. "
            "Names use the curated RPG Name Genie 2.4 approach; related "
            "creatures share coherent linguistic families."
        )
        intro.setObjectName("muted")
        intro.setWordWrap(True)
        outer.addWidget(intro)

        outer.addWidget(QLabel("Race / Creature"))
        self.race = QComboBox()
        self.race.setEditable(True)
        self.race.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        self.race.setAccessibleName("Race or creature to name")
        for category, options in (
            ("CORE PLAYER RACES", CORE_RACES),
            ("EXPANDED 3.5 RACES", EXPANDED_RACES),
            ("MONSTERS AND CREATURES", MONSTER_RACES),
        ):
            for name in options:
                if self.race.findText(name) == -1:
                    self.race.addItem(name)
        original = race.strip() if race.strip() else ("Goblin" if monster else "Human")
        self.race.setCurrentText(original)
        self.race.currentTextChanged.connect(self.show_family)
        outer.addWidget(self.race)

        row = QHBoxLayout()
        genders = QVBoxLayout()
        genders.addWidget(QLabel("Gender / Naming style"))
        self.gender = QComboBox()
        self.gender.addItems(GENDERS)
        self.gender.setAccessibleName("Name gender preference")
        genders.addWidget(self.gender)
        row.addLayout(genders, 1)

        structures = QVBoxLayout()
        structures.addWidget(QLabel("Name construction"))
        self.structure = QComboBox()
        self.structure.addItem("Traditional (family for characters)", None)
        self.structure.addItem("Given name only", False)
        self.structure.addItem("Given + family / clan", True)
        structures.addWidget(self.structure)
        row.addLayout(structures, 1)
        outer.addLayout(row)
        # Names in 2.4 may also be filtered by Class, Culture and Tone.
        # Blank = no restriction. Profiles without this metadata remain eligible.
        classifications = QHBoxLayout()
        for title, values, attribute in (
            ("Class", ("Any class", "Warrior", "Mage", "Rogue", "Ranger", "Cleric",
                       "Paladin", "Bard", "Druid", "Artificer", "Noble", "Warlock"), "character_class"),
            ("Culture", ("Any culture", "Highland", "Nordic", "Desert", "Coastal",
                         "Urban", "Nomadic", "Imperial"), "culture"),
            ("Tone", ("Any tone", "Heroic", "Dark", "Elegant", "Gritty", "Comic",
                      "Mystical"), "tone"),
        ):
            col = QVBoxLayout()
            col.addWidget(QLabel(title))
            selector = QComboBox()
            selector.addItems(values)
            selector.setAccessibleName(f"Name Genie {title.lower()} filter")
            col.addWidget(selector)
            setattr(self, attribute, selector)
            classifications.addLayout(col, 1)
        outer.addLayout(classifications)

        self.family = QLabel("")
        self.family.setObjectName("muted")
        self.family.setWordWrap(True)
        outer.addWidget(self.family)
        self.list_widget = QListWidget()
        self.list_widget.setAccessibleName("Generated name suggestions")
        self.list_widget.itemDoubleClicked.connect(lambda item: self.accept_name())
        outer.addWidget(self.list_widget, 1)

        footer = QHBoxLayout()
        regenerate = QPushButton("Generate Eight Names")
        regenerate.setObjectName("primaryButton")
        regenerate.clicked.connect(self.generate)
        footer.addWidget(regenerate)
        footer.addStretch()
        self.use_button = QPushButton("Copy Selected Name" if standalone else "Use Selected Name")
        self.use_button.setAccessibleName("Copy selected generated name" if standalone else "Use selected generated name")
        self.use_button.clicked.connect(self.accept_name)
        footer.addWidget(self.use_button)
        close = QPushButton("Cancel")
        close.clicked.connect(self.reject)
        footer.addWidget(close)
        outer.addLayout(footer)
        self.feedback = QLabel("Copy a name to the clipboard to use it anywhere." if standalone else
                               "Double-click a name to select it.")
        self.feedback.setObjectName("muted")
        outer.addWidget(self.feedback)
        self.show_family()
        self.generate()

    def show_family(self, *args):
        try:
            family = family_for(self.race.currentText())
            self.family.setText(
                f"Naming tradition: {family}. "
                "This affects names only, not D&D racial modifiers or creature statistics."
            )
        except UnsupportedCreature:
            self.family.setText(
                "No profile matches this spelling. Select a related race or family "
                "(for example Draconic, Orc, Goblinoid, Giantkin, or Undead)."
            )

    def generate(self):
        self.list_widget.clear()
        try:
            names = self.engine.generate(
                self.race.currentText(), gender=self.gender.currentText(),
                monster=self.is_monster, count=8,
                surname=self.structure.currentData(),
                character_class=self.character_class.currentText(),
                culture=self.culture.currentText(),
                tone=self.tone.currentText(),
            )
        except (ValueError, OSError) as exc:
            QMessageBox.warning(self, "Unable to generate names", str(exc))
            return
        self.list_widget.addItems(names)
        if names:
            self.list_widget.setCurrentRow(0)

    def accept_name(self):
        item = self.list_widget.currentItem()
        if item is None:
            QMessageBox.information(self, "Select a name", "Generate and select a name first.")
            return
        self.selected_name = item.text()
        if self.standalone:
            QApplication.clipboard().setText(self.selected_name)
            self.feedback.setText(f"Copied: {self.selected_name}. Generate again or close when finished.")
        else:
            self.accept()
