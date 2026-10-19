"""PyQt6 application for permanent character/NPC/monster library records."""
from dataclasses import replace

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QKeySequence, QShortcut
from PyQt6.QtWidgets import (
    QButtonGroup, QCheckBox, QDialog, QFormLayout, QFrame, QGridLayout,
    QHBoxLayout, QHeaderView, QLabel, QLineEdit, QMainWindow,
    QMessageBox, QPlainTextEdit, QPushButton, QScrollArea, QSpinBox,
    QSplitter, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget, QSizePolicy,
)

from . import __version__
from .artwork import CoverArtLabel, load_artwork, window_icon
from .models import Creature, KIND_LABELS
from .storage import CreatureRepository
from .name_ui import NamePickerDialog
from .roll_ui import CharacterCreatorDialog, DiceDialog
from .monster_ui import MonsterCreatorDialog
from .ai_ui import AIWritingDialog


ABILITIES = (("strength", "STR"), ("dexterity", "DEX"), ("constitution", "CON"),
             ("intelligence", "INT"), ("wisdom", "WIS"), ("charisma", "CHA"))

class SquareAbilityGrid(QWidget):
    """Six fluid 1:1 score tiles; never allow the preview to flatten them.

    A fixed 76px box is too small at ordinary desktop widths, while normal
    grid cells get vertically squeezed by the crowded record-detail pane.
    Calculate square dimensions from the available grid width, cap them to
    a readable range, then reserve the correct two-row height.
    """
    GAP = 8
    MIN_EDGE = 80
    MAX_EDGE = 112

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("abilityScoreGrid")
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.tiles = []
        self.grid = QGridLayout(self)
        self.grid.setContentsMargins(0, 0, 0, 0)
        self.grid.setHorizontalSpacing(self.GAP)
        self.grid.setVerticalSpacing(self.GAP)
        for col in range(3):
            self.grid.setColumnStretch(col, 1)
        self._edge = 0
        self._set_edge(self.MIN_EDGE)

    def add_tile(self, tile, index):
        self.tiles.append(tile)
        self.grid.addWidget(tile, index // 3, index % 3,
                            Qt.AlignmentFlag.AlignCenter)
        tile.setFixedSize(self._edge, self._edge)

    def _set_edge(self, edge):
        if self._edge == edge:
            return
        self._edge = edge
        for tile in self.tiles:
            tile.setFixedSize(edge, edge)
        # Reserve full height for BOTH rows; QVBoxLayout must not squeeze
        # scores into horizontal strips, even when the preview is short.
        self.setFixedHeight(edge * 2 + self.GAP)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        available = max(0, event.size().width() - 2 * self.GAP)
        edge = min(self.MAX_EDGE, max(self.MIN_EDGE, available // 3))
        self._set_edge(edge)


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
        name_controls = QHBoxLayout()
        name_controls.addWidget(self.name, 1)
        name_generate = QPushButton("Generate Name")
        name_generate.setToolTip("RPG Name Genie 2.4 naming traditions, including expanded D&D creatures")
        name_generate.clicked.connect(self.suggest_name)
        name_controls.addWidget(name_generate)
        form.addRow("Name *", name_controls)
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

    def suggest_name(self):
        creature_type = self.race_type.text().strip()
        picker = NamePickerDialog(race=creature_type or ("Goblin" if self.original.kind == "monster" else "Human"),
                                  monster=self.original.kind == "monster", parent=self)
        if picker.exec() == QDialog.DialogCode.Accepted and picker.selected_name:
            self.name.setText(picker.selected_name)
            if not self.race_type.text().strip():
                self.race_type.setText(picker.race.currentText())

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
        self.setWindowTitle(f"Dungeons & Dragons Game Manager 4 · {__version__} · The Compendium")
        self.setWindowIcon(window_icon())
        self.resize(1380, 840)
        # Retain the original desktop presentation, but permit compact windows.
        self.setMinimumSize(800, 540)
        self._splitter_layout = None
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
        # Scroll the original dashboard when height is limited; this does not
        # alter its header/banner presentation or default spacing.
        self.workspace_scroll = QScrollArea()
        self.workspace_scroll.setObjectName("workspaceScroll")
        self.workspace_scroll.setWidgetResizable(True)
        self.workspace_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.workspace_scroll.setWidget(workspace)
        shell.addWidget(self.workspace_scroll, 1)
        self.setup_hero(body)
        self.setup_metrics(body)
        self.setup_filters(body)
        self.setup_library(body)
        self._update_preview_layout()
        self.statusBar().showMessage("Local library · " + str(self.library.path))
        QShortcut(QKeySequence("Ctrl+F"), self, activated=self.search.setFocus)
        QShortcut(QKeySequence("Ctrl+N"), self, activated=lambda: self.create("pc"))
        QShortcut(QKeySequence("Ctrl+D"), self, activated=self.open_dice)
        QShortcut(QKeySequence("Ctrl+G"), self, activated=self.open_names)
        QShortcut(QKeySequence("Ctrl+Shift+N"), self, activated=self.open_narrator)
        self.refresh()

    def setup_sidebar(self, shell):
        sidebar = QFrame()
        sidebar.setObjectName("sidebar")
        # The classic sidebar proportions are unchanged at desktop sizes.
        # A scroller only prevents control clipping on shorter laptop screens.
        sidebar_scroll = QScrollArea()
        sidebar_scroll.setObjectName("sidebarScroll")
        sidebar_scroll.setFixedWidth(246)
        sidebar_scroll.setFrameShape(QFrame.Shape.NoFrame)
        sidebar_scroll.setWidgetResizable(True)
        sidebar_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        shell.addWidget(sidebar_scroll)
        layout = QVBoxLayout(sidebar)
        layout.setContentsMargins(21, 28, 21, 26)
        layout.setSpacing(16)
        brand = QHBoxLayout()
        crest = QLabel()
        crest.setObjectName("brandMark")
        crest.setFixedSize(61, 61)
        crest.setPixmap(load_artwork("dragon_crest.png").scaled(
            61, 61, Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation))
        crest.setAccessibleName("Dragon and d20 game manager emblem")
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
        layout.addWidget(caption("THE GAME MASTER'S TOOLS", "eyebrow"))
        dice_button = action("Roll Dice  /  Dice Eliminator", self.open_dice, "primaryButton")
        dice_button.setAccessibleName("Open the Dice Eliminator")
        layout.addWidget(dice_button)
        layout.addWidget(caption("Ctrl+D opens the dice tray", "muted"))
        names_button = action("RPG NAME GENIE  /  Generate Names", self.open_names, "primaryButton")
        names_button.setAccessibleName("Open standalone RPG Name Genie name generator")
        layout.addWidget(names_button)
        layout.addWidget(caption("Ctrl+G opens the Name Genie", "muted"))
        narrator = action("The Scribe  /  DM Narration", self.open_narrator)
        narrator.setAccessibleName("Open the local AI Dungeon Master narration tool")
        layout.addWidget(narrator)
        layout.addSpacing(8)
        layout.addWidget(caption("QUICK CREATE", "eyebrow"))
        for title, kind in (("+  New Character", "pc"), ("+  New NPC", "npc"),
                            ("+  New Monster", "monster")):
            control = action(title, lambda checked=False, k=kind: self.create(k))
            if kind == "pc":
                control.setObjectName("primaryButton")
            layout.addWidget(control)
        layout.addStretch()
        layout.addWidget(rule())
        layout.addWidget(caption(f"D&D 3.5  ·  v{__version__}  ·  OFFLINE", "eyebrow"))
        layout.addWidget(caption("Your chronicles stay on this computer.", "muted", wrap=True))
        sidebar_scroll.setWidget(sidebar)

    def setup_hero(self, root):
        # Artwork includes the title. The former top Generate Names button
        # is removed: Name Genie remains accessible from sidebar and Ctrl+G.
        self.hero_banner = CoverArtLabel(
            "app_banner.jpg", height=166,
            description="D&D Game Manager 4. Fantasy dragon, d20 and fortress."
        )
        root.addWidget(self.hero_banner)
        root.addWidget(caption(
            "THE ADVENTURER'S ARCHIVE   ·   CHARACTERS, CREATURES & CHRONICLES",
            "eyebrow"
        ))

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
        splitter.setObjectName("librarySplitter")
        self.library_splitter = splitter
        splitter.setMinimumHeight(385)
        root.addWidget(splitter, 1)
        records_panel = QFrame()
        records_panel.setObjectName("panel")
        records_panel.setMinimumWidth(0)
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
        preview.setMinimumWidth(0)
        # Only the record-detail content scrolls when vertical space runs
        # short. The outer preview panel and the rest of the GUI stay put.
        # This prevents Qt from squeezing the square score cards to make
        # room for Notes and action buttons.
        preview_outer = QVBoxLayout(preview)
        preview_outer.setContentsMargins(0, 0, 0, 0)
        preview_scroll = QScrollArea()
        preview_scroll.setObjectName("recordPreviewScroll")
        preview_scroll.setFrameShape(QFrame.Shape.NoFrame)
        preview_scroll.setWidgetResizable(True)
        preview_scroll.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        content = QWidget()
        details = QVBoxLayout(content)
        details.setContentsMargins(20, 18, 20, 16)
        details.setSpacing(12)
        preview_scroll.setWidget(content)
        preview_outer.addWidget(preview_scroll)
        self.preview_scroll = preview_scroll
        details.addWidget(caption("SELECTED RECORD", "eyebrow"))
        self.preview_title = caption("Choose a record", "detailTitle", wrap=True)
        details.addWidget(self.preview_title)
        self.preview_sub = caption("Select an entry to inspect its details.", "muted", wrap=True)
        details.addWidget(self.preview_sub)
        details.addWidget(rule())
        self.detail = caption("", "muted", wrap=True)
        details.addWidget(self.detail)
        details.addWidget(caption("Ability Scores", "sectionTitle"))
        scores = SquareAbilityGrid()
        self.ability_score_grid = scores
        self.stat_values = {}
        for i, (attribute, code) in enumerate(ABILITIES):
            tile = QFrame()
            tile.setObjectName("statChip")
            tile.setAccessibleName(f"{code} ability score")
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
            scores.add_tile(tile, i)
        details.addWidget(scores)
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

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._update_preview_layout()

    def _update_preview_layout(self):
        """Change only the record/ability-score preview, never the banner."""
        if not hasattr(self, "library_splitter"):
            return
        layout = "stacked" if self.width() < 1130 else "columns"
        if layout == self._splitter_layout:
            return
        self._splitter_layout = layout
        if layout == "stacked":
            self.library_splitter.setOrientation(Qt.Orientation.Vertical)
            self.library_splitter.setMinimumHeight(680)
            self.library_splitter.setSizes([365, 315])
        else:
            self.library_splitter.setOrientation(Qt.Orientation.Horizontal)
            self.library_splitter.setMinimumHeight(385)
            self.library_splitter.setSizes([680, 330])

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
        import json
        try:
            sheet = json.loads(record.sheet_json) if record.sheet_json else {}
        except (ValueError, TypeError):
            sheet = {}
        if record.kind == "monster" and sheet.get("monster_type"):
            computed = sheet.get("computed", {})
            self.detail.setText(
                f"Species: {record.race_type or '—'}\n"
                f"Type: {sheet.get('monster_type', '')}"
                f"  ·  {sheet.get('size', 'Medium')}\n"
                f"Hit Dice: {computed.get('hit_dice_notation', '—')}"
                f"   ·   CR: {progression}\n"
                f"AC {record.armor_class}   ·   HP {record.max_hit_points}"
                f"   ·   BAB +{computed.get('bab', 0)}\n"
                f"Fort {computed.get('fort', 0):+d}  /  "
                f"Ref {computed.get('ref', 0):+d}  /  "
                f"Will {computed.get('will', 0):+d}\n"
                "Special traits and CR require DM review."
            )
        else:
            self.detail.setText(
                f"Race / Type: {record.race_type or '—'}\n"
                f"Class: {record.character_class or '—'}\n"
                f"{progress_label}: {progression}\n"
                f"Armor Class: {record.armor_class}    ·    Hit Points: {record.max_hit_points}"
            )
        no_score = set(sheet.get("null_abilities", []))
        for attribute, score in self.stat_values.items():
            score.setText("—" if attribute in no_score else
                          str(getattr(record, attribute)))
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

    def open_names(self):
        """Standalone Name Genie, accessible even when no records exist."""
        dialog = NamePickerDialog(race="Human", standalone=True, parent=self)
        dialog.exec()

    def open_narrator(self):
        record = self.selected()
        context = (f"Scene features {record.name}, a {record.race_type} {record.character_class}. "
                   f"Notes: {record.notes[:900]}" if record else "")
        writer = AIWritingDialog("dm", context, self)
        writer.exec()

    def open_dice(self):
        dialog = DiceDialog(self)
        dialog.exec()

    def create(self, kind):
        if kind in ("pc", "npc"):
            dialog = CharacterCreatorDialog(self, kind=kind)
        elif kind == "monster":
            dialog = MonsterCreatorDialog(self)
        else:
            raise ValueError("Unknown record type.")
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.persist(dialog.result_creature)

    def edit(self, *args):
        record = self.selected()
        if record is None:
            return
        if (record.kind in ("pc", "npc") and record.sheet_json
                and record.level == 1):
            dialog = CharacterCreatorDialog(self, creature=record)
        elif record.kind == "monster" and record.sheet_json:
            import json
            try:
                structure = json.loads(record.sheet_json)
            except ValueError:
                structure = {}
            dialog = (MonsterCreatorDialog(self, creature=record)
                      if structure.get("monster_type") else
                      CreatureEditor(record, self))
        else:
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
