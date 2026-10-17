"""PyQt6 application for permanent character/NPC/monster library records."""
from dataclasses import replace

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QKeySequence, QShortcut
from PyQt6.QtWidgets import (
    QButtonGroup, QCheckBox, QDialog, QFormLayout, QFrame, QGridLayout,
    QHBoxLayout, QHeaderView, QLabel, QLineEdit, QMainWindow,
    QMessageBox, QPlainTextEdit, QPushButton, QScrollArea, QSpinBox,
    QSplitter, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

from .models import Creature, KIND_LABELS
from .storage import CreatureRepository


ABILITIES = (("strength", "STR"), ("dexterity", "DEX"), ("constitution", "CON"),
             ("intelligence", "INT"), ("wisdom", "WIS"), ("charisma", "CHA"))

def caption(text, role="", wrap=False):
    widget = QLabel(text)
    widget.setTextFormat(Qt.TextFormat.PlainText)
    widget.setWordWrap(wrap)
    if role:
        widget.setObjectName(role)
    return widget

def rule():
    line = QFrame()
    line.setObjectName("divider")
    line.setFixedHeight(1)
    return line

def action(text, callback, role=""):
    widget = QPushButton(text)
    if role:
        widget.setObjectName(role)
    widget.clicked.connect(callback)
    return widget

class CreatureEditor(QDialog):
    """Styled editor for the currently supported record fields."""

    def __init__(self, creature: Creature, parent=None):
        super().__init__(parent)
        self.original = creature
        self.result_creature = None
        title = "Edit Record" if creature.id else "Create Record"
        self.setWindowTitle(f"{title} | D&D Game Manager 4")
        self.resize(680, 780)
        self.setMinimumSize(580, 560)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(22, 22, 22, 18)
        layout.setSpacing(15)
        layout.addWidget(caption("THE COMPENDIUM / RECORD EDITOR", "eyebrow"))
        layout.addWidget(caption(title, "pageTitle"))
        layout.addWidget(caption(f"{KIND_LABELS[creature.kind]}  ·  D&D 3.5 library entry", "muted"))
        layout.addWidget(rule())
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll_body = QWidget()
        content = QVBoxLayout(scroll_body)
        content.setContentsMargins(5, 8, 16, 8)
        content.setSpacing(16)

        content.addWidget(caption("Identity & Classification", "sectionTitle"))
        identity = QFrame()
        identity.setObjectName("panel")
        form = QFormLayout(identity)
        form.setContentsMargins(18, 17, 18, 18)
        form.setSpacing(12)
        self.name = QLineEdit(creature.name)
        self.name.setMaxLength(200)
        self.name.setPlaceholderText("e.g. Elara Nightwind")
        self.name.setAccessibleName("Record name, required")
        form.addRow("Name *", self.name)
        self.race_type = QLineEdit(creature.race_type)
        form.addRow("Race / Creature Type", self.race_type)
        self.character_class = QLineEdit(creature.character_class)
        form.addRow("Class / Classes", self.character_class)
        content.addWidget(identity)

        content.addWidget(caption("Combat & Progression", "sectionTitle"))
        combat = QFrame()
        combat.setObjectName("panel")
        combat_form = QFormLayout(combat)
        combat_form.setContentsMargins(18, 17, 18, 18)
        combat_form.setSpacing(12)
        self.level = self.spin(creature.level, 0, 99)
        combat_form.addRow("Level", self.level)
        self.cr = QLineEdit(creature.challenge_rating)
        self.cr.setPlaceholderText("e.g. 1/2, 5")
        combat_form.addRow("Challenge Rating", self.cr)
        self.ac = self.spin(creature.armor_class, 0, 999)
        combat_form.addRow("Armor Class", self.ac)
        self.hp = self.spin(creature.max_hit_points, 0, 999999)
        combat_form.addRow("Maximum Hit Points", self.hp)
        content.addWidget(combat)

        content.addWidget(caption("Ability Scores", "sectionTitle"))
        stats_frame = QFrame()
        stats_frame.setObjectName("panel")
        grid = QGridLayout(stats_frame)
        grid.setContentsMargins(18, 16, 18, 16)
        grid.setSpacing(13)
        self.abilities = {}
        for i, (attribute, abbreviation) in enumerate(ABILITIES):
            group = QWidget()
            group_layout = QVBoxLayout(group)
            group_layout.setContentsMargins(0, 0, 0, 0)
            group_layout.addWidget(caption(abbreviation + "  ·  " + attribute.title(), "statName"))
            field = self.spin(getattr(creature, attribute), 0, 99)
            field.setAccessibleName(attribute.title())
            group_layout.addWidget(field)
            grid.addWidget(group, *divmod(i, 3))
            self.abilities[attribute] = field
        content.addWidget(stats_frame)

        content.addWidget(caption("Notes & History", "sectionTitle"))
        self.notes = QPlainTextEdit()
        self.notes.setPlainText(creature.notes)
        self.notes.setPlaceholderText("Appearance, background, story hooks, tactics, or other notes...")
        self.notes.setMinimumHeight(120)
        content.addWidget(self.notes)
        scroll.setWidget(scroll_body)
        layout.addWidget(scroll, 1)
        footer = QHBoxLayout()
        footer.addWidget(caption("* Required field  ·  Saved locally", "muted"))
        footer.addStretch()
        footer.addWidget(action("Cancel", self.reject))
        save_button = action("Save Record", self.save, "primaryButton")
        save_button.setDefault(True)
        footer.addWidget(save_button)
        layout.addLayout(footer)

    @staticmethod
    def spin(value, minimum, maximum):
        widget = QSpinBox()
        widget.setRange(minimum, maximum)
        widget.setValue(value)
        return widget

    def save(self):
        if not self.name.text().strip():
            QMessageBox.warning(self, "Name required", "Please enter a name for this record.")
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
    """Fantasy-tabletop library UI; preserves CRUD and SQLite contracts."""

    def __init__(self, library: CreatureRepository):
        super().__init__()
        self.library = library
        self.active_kind = None
        self.setWindowTitle("Dungeons & Dragons Game Manager 4 · The Compendium")
        self.resize(1380, 840)
        self.setMinimumSize(1010, 650)
        central = QWidget()
        self.setCentralWidget(central)
        shell = QHBoxLayout(central)
        shell.setContentsMargins(0, 0, 0, 0)
        shell.setSpacing(0)
        self.setup_sidebar(shell)
        workspace = QWidget()
        body = QVBoxLayout(workspace)
        body.setContentsMargins(27, 25, 27, 20)
        body.setSpacing(15)
        shell.addWidget(workspace, 1)
        self.setup_hero(body)
        self.setup_metrics(body)
        self.setup_filters(body)
        self.setup_library(body)
        self.statusBar().showMessage("Local library · " + str(self.library.path))
        QShortcut(QKeySequence("Ctrl+F"), self, activated=self.search.setFocus)
        QShortcut(QKeySequence("Ctrl+N"), self, activated=lambda: self.create("pc"))
        self.refresh()

    def setup_sidebar(self, shell):
        sidebar = QFrame()
        sidebar.setObjectName("sidebar")
        sidebar.setFixedWidth(246)
        shell.addWidget(sidebar)
        layout = QVBoxLayout(sidebar)
        layout.setContentsMargins(21, 28, 21, 26)
        layout.setSpacing(16)
        brand = QHBoxLayout()
        crest = caption("20", "crest")
        crest.setFixedSize(55, 55)
        crest.setAlignment(Qt.AlignmentFlag.AlignCenter)
        brand.addWidget(crest)
        titles = QVBoxLayout()
        titles.setSpacing(0)
        titles.addWidget(caption("D&D", "brandTitle"))
        titles.addWidget(caption("GAME MANAGER 4", "eyebrow"))
        brand.addLayout(titles)
        layout.addLayout(brand)
        layout.addWidget(rule())
        layout.addWidget(caption("THE ARCHIVES", "eyebrow"))
        self.nav = {}
        group = QButtonGroup(self)
        group.setExclusive(True)
        for kind, title in ((None, "All Records"), ("pc", "Player Characters"),
                            ("npc", "Nonplayer Characters"), ("monster", "Bestiary")):
            nav = QPushButton(title)
            nav.setObjectName("navButton")
            nav.setCheckable(True)
            nav.setAccessibleName("Show " + title)
            nav.clicked.connect(lambda checked=False, k=kind: self.change_section(k))
            group.addButton(nav)
            layout.addWidget(nav)
            self.nav[kind] = nav
        self.nav[None].setChecked(True)
        layout.addSpacing(12)
        layout.addWidget(rule())
        layout.addWidget(caption("QUICK CREATE", "eyebrow"))
        for title, kind in (("+  New Character", "pc"), ("+  New NPC", "npc"),
                            ("+  New Monster", "monster")):
            control = action(title, lambda checked=False, k=kind: self.create(k))
            if kind == "pc":
                control.setObjectName("primaryButton")
            layout.addWidget(control)
        layout.addStretch()
        layout.addWidget(rule())
        layout.addWidget(caption("D&D 3.5  ·  OFFLINE", "eyebrow"))
        layout.addWidget(caption("Your chronicles stay on this computer.", "muted", wrap=True))

    def setup_hero(self, root):
        hero = QFrame()
        hero.setObjectName("hero")
        row = QHBoxLayout(hero)
        row.setContentsMargins(24, 19, 24, 20)
        intro = QVBoxLayout()
        intro.setSpacing(6)
        intro.addWidget(caption("THE GAME MASTER'S DESK / CHARACTER LIBRARY", "eyebrow"))
        intro.addWidget(caption("The Adventurer's Archive", "pageTitle"))
        intro.addWidget(caption("A place for legends, villains, and everything in between.", "muted"))
        row.addLayout(intro, 1)
        tag = caption("THE COMPENDIUM", "tag")
        tag.setAlignment(Qt.AlignmentFlag.AlignCenter)
        row.addWidget(tag)
        root.addWidget(hero)

    def setup_metrics(self, root):
        metrics = QHBoxLayout()
        metrics.setSpacing(11)
        self.metrics = {}
        for key, title in (("pc", "PLAYER CHARACTERS"), ("npc", "NPCs"),
                           ("monster", "MONSTERS"), ("archived", "ARCHIVED")):
            frame = QFrame()
            frame.setObjectName("metric")
            col = QVBoxLayout(frame)
            col.setContentsMargins(17, 12, 17, 12)
            col.setSpacing(1)
            col.addWidget(caption(title, "metricLabel"))
            count = caption("0", "metricValue")
            col.addWidget(count)
            self.metrics[key] = count
            metrics.addWidget(frame, 1)
        root.addLayout(metrics)

    def setup_filters(self, root):
        row = QHBoxLayout()
        row.setSpacing(13)
        self.search = QLineEdit()
        self.search.setPlaceholderText("Search the archives by name, race, class, or notes...")
        self.search.setClearButtonEnabled(True)
        self.search.setAccessibleName("Search saved records")
        self.search.textChanged.connect(self.refresh)
        row.addWidget(self.search, 1)
        self.show_archived = QCheckBox("Include archived")
        self.show_archived.toggled.connect(self.refresh)
        row.addWidget(self.show_archived)
        root.addLayout(row)

    def setup_library(self, root):
        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setChildrenCollapsible(False)
        root.addWidget(splitter, 1)
        records_panel = QFrame()
        records_panel.setObjectName("panel")
        records_panel.setMinimumWidth(490)
        pane = QVBoxLayout(records_panel)
        pane.setContentsMargins(17, 18, 17, 15)
        pane.setSpacing(12)
        heading = QHBoxLayout()
        self.section_heading = caption("All Records", "sectionTitle")
        heading.addWidget(self.section_heading)
        heading.addStretch()
        self.result_summary = caption("", "muted")
        heading.addWidget(self.result_summary)
        pane.addLayout(heading)
        pane.addWidget(rule())
        self.table = QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels(
            ("NAME", "KIND", "RACE / TYPE", "CLASS", "LVL / CR", "STATUS")
        )
        self.table.verticalHeader().hide()
        self.table.setAlternatingRowColors(True)
        self.table.setShowGrid(False)
        self.table.setWordWrap(False)
        self.table.verticalHeader().setDefaultSectionSize(45)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.horizontalHeader().setHighlightSections(False)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        for i, width in ((1, 89), (2, 115), (3, 107), (4, 83), (5, 81)):
            self.table.horizontalHeader().setSectionResizeMode(i, QHeaderView.ResizeMode.Interactive)
            self.table.setColumnWidth(i, width)
        self.table.itemSelectionChanged.connect(self.update_preview)
        self.table.doubleClicked.connect(self.edit)
        pane.addWidget(self.table, 1)
        pane.addWidget(caption("Double-click a record to edit. All changes save locally.", "muted"))
        splitter.addWidget(records_panel)

        preview = QFrame()
        preview.setObjectName("panel")
        preview.setMinimumWidth(280)
        details = QVBoxLayout(preview)
        details.setContentsMargins(20, 18, 20, 16)
        details.setSpacing(12)
        details.addWidget(caption("SELECTED RECORD", "eyebrow"))
        self.preview_title = caption("Choose a record", "detailTitle", wrap=True)
        details.addWidget(self.preview_title)
        self.preview_sub = caption("Select an entry to inspect its details.", "muted", wrap=True)
        details.addWidget(self.preview_sub)
        details.addWidget(rule())
        self.detail = caption("", "muted", wrap=True)
        details.addWidget(self.detail)
        details.addWidget(caption("Ability Scores", "sectionTitle"))
        scores = QGridLayout()
        scores.setSpacing(8)
        self.stat_values = {}
        for i, (attribute, code) in enumerate(ABILITIES):
            tile = QFrame()
            tile.setObjectName("statChip")
            tile_layout = QVBoxLayout(tile)
            tile_layout.setContentsMargins(8, 7, 8, 7)
            tile_layout.setSpacing(1)
            short = caption(code, "statName")
            short.setAlignment(Qt.AlignmentFlag.AlignCenter)
            tile_layout.addWidget(short)
            value = caption("—", "statValue")
            value.setAlignment(Qt.AlignmentFlag.AlignCenter)
            tile_layout.addWidget(value)
            self.stat_values[attribute] = value
            scores.addWidget(tile, *divmod(i, 3))
        details.addLayout(scores)
        details.addWidget(caption("Notes", "sectionTitle"))
        self.notes_preview = QPlainTextEdit()
        self.notes_preview.setReadOnly(True)
        self.notes_preview.setPlaceholderText("No notes yet.")
        self.notes_preview.setMaximumHeight(130)
        details.addWidget(self.notes_preview, 1)
        self.edit_button = action("Edit Record", self.edit, "primaryButton")
        details.addWidget(self.edit_button)
        controls = QHBoxLayout()
        self.duplicate_button = action("Duplicate", self.duplicate)
        controls.addWidget(self.duplicate_button)
        self.archive_button = action("Archive", self.toggle_archive, "dangerButton")
        controls.addWidget(self.archive_button)
        details.addLayout(controls)
        splitter.addWidget(preview)
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 2)
        splitter.setSizes([720, 335])

    def change_section(self, kind):
        self.active_kind = kind
        self.refresh()

    def refresh(self, *args, select_id=None):
        previous_id = select_id if select_id is not None else self._selected_id()
        records = self.library.list(
            kind=self.active_kind,
            query=self.search.text(),
            include_archived=self.show_archived.isChecked(),
        )
        all_records = self.library.list(include_archived=True)
        self.table.blockSignals(True)
        try:
            self.table.setRowCount(len(records))
            for row, record in enumerate(records):
                texts = (
                    record.name, KIND_LABELS[record.kind], record.race_type,
                    record.character_class,
                    record.challenge_rating if record.kind == "monster" else str(record.level),
                    "Archived" if record.archived else "Active",
                )
                for col, value in enumerate(texts):
                    item = QTableWidgetItem(value)
                    if col == 0:
                        item.setData(Qt.ItemDataRole.UserRole, record.id)
                    item.setToolTip(value)
                    self.table.setItem(row, col, item)
            self.table.clearSelection()
            if previous_id:
                for row in range(self.table.rowCount()):
                    if self.table.item(row, 0).data(Qt.ItemDataRole.UserRole) == previous_id:
                        self.table.selectRow(row)
                        break
        finally:
            self.table.blockSignals(False)
        self.result_summary.setText(f"{len(records)} records")
        titles = {None: "All Records", "pc": "Player Characters",
                  "npc": "Nonplayer Characters", "monster": "The Bestiary"}
        self.section_heading.setText(titles[self.active_kind])
        for kind in ("pc", "npc", "monster"):
            self.metrics[kind].setText(str(sum(r.kind == kind and not r.archived for r in all_records)))
        self.metrics["archived"].setText(str(sum(r.archived for r in all_records)))
        self.update_preview()

    def _selected_id(self):
        selected_rows = self.table.selectionModel().selectedRows()
        if not selected_rows:
            return None
        item = self.table.item(selected_rows[0].row(), 0)
        return item.data(Qt.ItemDataRole.UserRole) if item else None

    def selected(self):
        selected_id = self._selected_id()
        return self.library.get(selected_id) if selected_id else None

    def update_preview(self):
        record = self.selected()
        for control in (self.edit_button, self.duplicate_button, self.archive_button):
            control.setEnabled(record is not None)
        if record is None:
            self.preview_title.setText("Choose a record")
            self.preview_sub.setText("Select an entry to inspect its details.")
            self.detail.setText("")
            self.notes_preview.clear()
            for score in self.stat_values.values():
                score.setText("—")
            self.archive_button.setText("Archive")
            return
        self.preview_title.setText(record.name)
        self.preview_sub.setText(KIND_LABELS[record.kind] + ("  ·  ARCHIVED" if record.archived else "  ·  ACTIVE"))
        progression = (record.challenge_rating or "—") if record.kind == "monster" else str(record.level)
        progress_label = "Challenge Rating" if record.kind == "monster" else "Level"
        self.detail.setText(
            f"Race / Type: {record.race_type or '—'}\n"
            f"Class: {record.character_class or '—'}\n"
            f"{progress_label}: {progression}\n"
            f"Armor Class: {record.armor_class}    ·    Hit Points: {record.max_hit_points}"
        )
        for attribute, score in self.stat_values.items():
            score.setText(str(getattr(record, attribute)))
        self.notes_preview.setPlainText(record.notes)
        self.archive_button.setText("Restore" if record.archived else "Archive")

    def persist(self, record):
        try:
            saved = self.library.save(record)
        except Exception as error:
            QMessageBox.critical(self, "Save failed", str(error))
            return
        self.refresh(select_id=saved.id)
        self.statusBar().showMessage(f"Saved {saved.name}  ·  {self.library.path}")

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
            try:
                self.library.set_archived(record.id, not record.archived)
            except Exception as error:
                QMessageBox.critical(self, "Unable to update record", str(error))
                return
            self.refresh(select_id=record.id)
