"""PyQt6 application for permanent character/NPC/monster library records."""
from dataclasses import replace
import sqlite3

from PyQt6.QtCore import Qt, QItemSelectionModel
from PyQt6.QtGui import QKeySequence, QShortcut
from PyQt6.QtWidgets import (
    QApplication, QButtonGroup, QCheckBox, QDialog, QFileDialog, QFormLayout, QFrame, QGridLayout,
    QHBoxLayout, QHeaderView, QLabel, QLineEdit, QMainWindow,
    QMessageBox, QPlainTextEdit, QPushButton, QScrollArea, QSpinBox,
    QSplitter, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget, QSizePolicy,
)

from . import __version__
from .artwork import CoverArtLabel, load_artwork, window_icon
from .models import Creature, KIND_LABELS
from .storage import CreatureRepository
from .library_transfer import read_library_export
from .import_ui import ImportPreviewDialog
from .name_ui import NamePickerDialog
from .roll_ui import CharacterCreatorDialog, DiceDialog
from .monster_ui import MonsterCreatorDialog
from .ai_ui import AIWritingDialog
from .scene_ui import SceneDialog
from .scene_context import SceneStore, blank_scene, add_records, build_scribe_context


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
        self.setAttribute(Qt.WidgetAttribute.WA_QuitOnClose, False)
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
        library_menu = self.menuBar().addMenu("Library")
        library_menu.addAction("Back Up Library…", self.backup_library)
        library_menu.addAction("Export Library as JSON…", self.export_library)
        library_menu.addAction("Import Library from JSON…", self.import_library)
        from .campaigns import ActiveWorkspace, CampaignRepository, SessionSceneStore
        self.campaigns = CampaignRepository(library.path)
        self._workspace_error = ""
        try:
            self.workspace = self.campaigns.get_workspace()
        except (ValueError, sqlite3.Error) as exc:
            self.workspace = ActiveWorkspace()
            self._workspace_error = str(exc)
        self.scene_store = (SessionSceneStore(self.campaigns, self.workspace.session_id)
                            if self.workspace.session_id else SceneStore(library.path))
        self._scene_error = ""
        try:
            self.scene = self.scene_store.load()
        except (ValueError, OSError, sqlite3.Error) as exc:
            # Leave a damaged scene file intact. Do not crash the entire app.
            self.scene = blank_scene()
            self._scene_error = str(exc)
        self.active_kind = None
        self._battle_window = None
        self._encounter_generator_dialog = None
        self._encounter_generator_dialogs = {}
        self.setWindowTitle(f"Dungeons & Dragons Game Manager 4 · {__version__} · The Compendium")
        self.setWindowIcon(window_icon())
        # 10% larger default desktop window; do not scale fonts, banners,
        # controls, ability tiles, or other UI elements. Qt layouts use the
        # extra free space while retaining compact-window support.
        self.resize(1551, 924)
        self.setMinimumSize(830, 540)
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
        workspace_line = QHBoxLayout()
        self.workspace_label = caption("", "muted", wrap=True)
        self.workspace_label.setAccessibleName("Active campaign, session, and encounter")
        workspace_line.addWidget(self.workspace_label, 1)
        self.campaigns_button = action("Campaigns & Sessions…", self.open_campaigns)
        workspace_line.addWidget(self.campaigns_button)
        body.addLayout(workspace_line)
        self._update_workspace_label()
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
        QShortcut(QKeySequence("Ctrl+B"), self, activated=self.open_battle_trakker)
        self.refresh()

    def _update_workspace_label(self):
        if not self.workspace.session_id:
            text = "Standalone workspace · local scene and encounter"
        else:
            campaign = self.campaigns.get_campaign(self.workspace.campaign_id)
            session = self.campaigns.get_session(self.workspace.session_id)
            encounter = (self.campaigns.get_encounter(self.workspace.encounter_id)
                         if self.workspace.encounter_id else None)
            text = f"{campaign.name if campaign else 'Campaign'} / {session.title if session else 'Session'}"
            if encounter is not None:
                text += f" / {encounter.title}"
        if self._workspace_error:
            text += " · saved workspace needs review"
        self.workspace_label.setText(text)

    def _flush_workspace(self):
        if self._battle_window is not None:
            self._battle_window._save()
        # Preserve unreadable scenes in place; switching away must never
        # replace a damaged saved scene with the blank error fallback.
        if not self._scene_error:
            self.scene_store.save(self.scene)

    def switch_workspace(self, workspace):
        """Validate the destination and save the current state before switching."""
        from .campaigns import ActiveWorkspace, CampaignBattleStore, SessionSceneStore
        from .battle_advanced import AdvancedBattleStore
        if not isinstance(workspace, ActiveWorkspace):
            raise ValueError("Choose a saved campaign session or the standalone workspace.")
        self._flush_workspace()
        if workspace.session_id:
            scene_store = SessionSceneStore(self.campaigns, workspace.session_id)
            scene = scene_store.load()
            if workspace.encounter_id:
                CampaignBattleStore(self.campaigns, workspace.encounter_id).load()
        else:
            if workspace.campaign_id or workspace.encounter_id:
                raise ValueError("A campaign workspace requires a session.")
            scene_store = SceneStore(self.library.path)
            scene = scene_store.load()
            # Leave a damaged standalone battle untouched and stay in the
            # current session until it is repaired or explicitly imported.
            AdvancedBattleStore(self.library.path).load()
        if workspace.session_id:
            activated = self.campaigns.activate(workspace.campaign_id, workspace.session_id,
                                                workspace.encounter_id)
        else:
            self.campaigns.clear_workspace()
            activated = ActiveWorkspace()
        self._encounter_generator_dialogs[self.workspace.session_id] = self._encounter_generator_dialog
        if self._battle_window is not None:
            if hasattr(self._battle_window, "advanced_desk"):
                self._battle_window.advanced_desk.hide()
            self._battle_window.hide()
            self._battle_window.deleteLater()
            self._battle_window = None
        writer = getattr(self, "_narrator_dialog", None)
        if writer is not None:
            writer.hide()
        self.workspace = activated
        self.scene_store, self.scene = scene_store, scene
        self._scene_error = self._workspace_error = ""
        self._encounter_generator_dialog = self._encounter_generator_dialogs.get(activated.session_id)
        self._update_workspace_label()
        self.statusBar().showMessage("Workspace opened · " + self.workspace_label.text())

    def open_campaigns(self):
        from .campaigns import ActiveWorkspace
        from .campaign_ui import CampaignManagerDialog
        try:
            self._flush_workspace()
            dialog = CampaignManagerDialog(self.campaigns, self.library, self)
            if dialog.exec() == QDialog.DialogCode.Accepted:
                if dialog.result_action in ("open", "standalone"):
                    target = (dialog.result_workspace if dialog.result_action == "open"
                              else ActiveWorkspace())
                    self.switch_workspace(target)
                elif dialog.result_action == "legacy_import":
                    from .battle_advanced import AdvancedBattleStore
                    local_scene = SceneStore(self.library.path).load()
                    local_battle = AdvancedBattleStore(self.library.path).load()
                    session = self.campaigns.import_legacy_session(
                        dialog.result_workspace.campaign_id, local_scene, local_battle)
                    encounter = self.campaigns.list_encounters(session.id)[0]
                    self.switch_workspace(ActiveWorkspace(session.campaign_id, session.id, encounter.id))
                elif dialog.result_action == "scribe":
                    self.open_campaign_scribe(dialog.result_session_id, dialog.result_task,
                                              campaign_id=dialog.result_workspace.campaign_id)
            current_campaign = (self.campaigns.get_campaign(self.workspace.campaign_id)
                                if self.workspace.campaign_id else None)
            if current_campaign is not None and current_campaign.archived:
                self.switch_workspace(ActiveWorkspace())
            self._update_workspace_label()
        except (ValueError, OSError, sqlite3.Error) as exc:
            QMessageBox.warning(self, "Campaign workspace not opened", str(exc))

    def open_campaign_scribe(self, session_id, task="session_plan", *, campaign_id=""):
        from .campaign_context import build_campaign_context, build_campaign_planning_context
        if task == "campaign_plan" and not session_id:
            context = build_campaign_planning_context(self.campaigns, self.library, campaign_id)
        else:
            context = build_campaign_context(self.campaigns, self.library, session_id, task=task)
        self._open_scribe_with_context(context, task=task)

    def add_party_to_scene(self):
        try:
            self._check_scene()
            if not self.workspace.campaign_id:
                raise ValueError("Open a campaign session before adding its party.")
            party = self.campaigns.party(self.workspace.campaign_id)
            if not party:
                raise ValueError("Choose and save a party in Campaigns & Sessions first.")
            if any(record.archived for record in party):
                raise ValueError("The party includes archived records. Restore them or edit the party first.")
            scene = add_records(self.scene, [record.id for record in party])
            self.scene_store.save(scene)
            self.scene = scene
            self.statusBar().showMessage(f"Added {len(party)} party members to this session's scene.")
        except (ValueError, OSError, sqlite3.Error) as exc:
            QMessageBox.warning(self, "Party not added", str(exc))

    def _battle_store(self, *, create=False):
        from .campaigns import CampaignBattleStore
        from .battle_advanced import AdvancedBattleStore
        if not self.workspace.session_id:
            return AdvancedBattleStore(self.library.path)
        if not self.workspace.encounter_id:
            if not create:
                return None
            encounters = self.campaigns.list_encounters(self.workspace.session_id)
            encounter = encounters[0] if encounters else self.campaigns.create_encounter(
                self.workspace.session_id, "Encounter 1")
            store = CampaignBattleStore(self.campaigns, encounter.id)
            store.load()
            self.workspace = self.campaigns.activate(self.workspace.campaign_id,
                                                      self.workspace.session_id, encounter.id)
            self._update_workspace_label()
            return store
        return CampaignBattleStore(self.campaigns, self.workspace.encounter_id)

    def backup_library(self):
        self._save_library_file(backup=True)

    def export_library(self):
        self._save_library_file(backup=False)

    def import_library(self):
        filename, _ = QFileDialog.getOpenFileName(
            self, "Import Library from JSON", "", "JSON files (*.json)")
        if not filename:
            return
        try:
            records = read_library_export(filename)
            dialog = ImportPreviewDialog(self.library, records, self)
            if dialog.exec() != QDialog.DialogCode.Accepted:
                return
        except (OSError, ValueError, sqlite3.Error) as exc:
            QMessageBox.warning(self, "Import Library", str(exc))
            return
        result = dialog.result_summary
        if result is None:
            return
        self.refresh()
        self.statusBar().showMessage(
            f"Library import complete · {result.added} added, {result.copied} copied, "
            f"{result.replaced} replaced, {result.skipped} skipped")

    def _save_library_file(self, *, backup):
        title = "Back Up Library" if backup else "Export Library as JSON"
        filename, _ = QFileDialog.getSaveFileName(
            self, title, "library-backup.sqlite3" if backup else "library-export.json",
            "SQLite database (*.sqlite3)" if backup else "JSON files (*.json)")
        if not filename:
            return
        try:
            if backup:
                self.library.backup(filename)
            else:
                self.library.export_json(filename)
        except (OSError, ValueError, sqlite3.Error) as exc:
            QMessageBox.warning(self, title, str(exc))
            return
        self.statusBar().showMessage(f"Library {'backup' if backup else 'export'} saved · {filename}")

    def setup_sidebar(self, shell):
        sidebar = QFrame()
        sidebar.setObjectName("sidebar")
        # Widen the left navigation to keep long labels and button text legible.
        # This does not alter its controls or the existing font sizes.
        sidebar_scroll = QScrollArea()
        sidebar_scroll.setObjectName("sidebarScroll")
        sidebar_scroll.setFixedWidth(326)
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
        layout.addWidget(action("Campaigns & Sessions", self.open_campaigns))
        layout.addWidget(action("Add Campaign Party to Scene", self.add_party_to_scene))
        dice_button = action("Roll Dice  /  Dice Eliminator", self.open_dice, "primaryButton")
        dice_button.setAccessibleName("Open the Dice Eliminator")
        layout.addWidget(dice_button)
        layout.addWidget(caption("Ctrl+D opens the dice tray", "muted"))
        names_button = action("RPG NAME GENIE  /  Generate Names", self.open_names, "primaryButton")
        names_button.setAccessibleName("Open standalone RPG Name Genie name generator")
        layout.addWidget(names_button)
        layout.addWidget(caption("Ctrl+G opens the Name Genie", "muted"))
        narrator = action("The Scribe  /  DM Assistant", self.open_narrator)
        narrator.setAccessibleName("Open local AI campaign planning, narration and Dungeon Master advice")
        layout.addWidget(narrator)
        encounters = action("Roll a Random Encounter", self.open_encounter_generator)
        encounters.setAccessibleName("Generate and review a random encounter and scene")
        layout.addWidget(encounters)
        combat = action("Battle Trakker  /  Combat Manager", self.open_battle_trakker)
        combat.setAccessibleName("Open the D&D 3.5 Battle Trakker encounter manager")
        layout.addWidget(combat)
        layout.addWidget(caption("Ctrl+B opens the Battle Trakker", "muted"))
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
        self.table.setSelectionMode(QTableWidget.SelectionMode.ExtendedSelection)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.horizontalHeader().setHighlightSections(False)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        for i, width in ((1, 89), (2, 115), (3, 107), (4, 83), (5, 81)):
            self.table.horizontalHeader().setSectionResizeMode(i, QHeaderView.ResizeMode.Interactive)
            self.table.setColumnWidth(i, width)
        self.table.itemSelectionChanged.connect(self.update_preview)
        self.table.doubleClicked.connect(self.edit)
        pane.addWidget(self.table, 1)
        pane.addWidget(caption(
            "Ctrl-click / Shift-click to select several records. "
            "Use All Records to mix PCs, NPCs and monsters.", "muted", wrap=True
        ))
        selection_actions = QHBoxLayout()
        self.add_scene_button = action("Add Selected to Scene", self.add_selection_to_scene)
        self.add_scene_button.setAccessibleName("Add all selected records to the current scene")
        selection_actions.addWidget(self.add_scene_button)
        self.load_selected_button = action("Load Selection into Scribe",
                                           self.load_selection_to_scribe)
        self.load_selected_button.setAccessibleName("Send full selected records to the local Scribe")
        selection_actions.addWidget(self.load_selected_button)
        pane.addLayout(selection_actions)
        combat_actions = QHBoxLayout()
        self.send_battle_button = action("Load Selected into Battle Trakker",
                                         self.load_selection_to_battle)
        combat_actions.addWidget(self.send_battle_button)
        pane.addLayout(combat_actions)
        self.battle_advice_button = action("Discuss Current Battle with Scribe", self.discuss_battle)
        pane.addWidget(self.battle_advice_button)
        scene_actions = QHBoxLayout()
        self.edit_scene_button = action("Edit Scene", self.edit_scene)
        scene_actions.addWidget(self.edit_scene_button)
        self.load_scene_button = action("Load Scene into Scribe",
                                        self.load_scene_to_scribe)
        scene_actions.addWidget(self.load_scene_button)
        pane.addLayout(scene_actions)
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
        self.level_up_button = action("Level Up…", self.level_up)
        self.level_up_button.setAccessibleName("Roll hit points and choose character level-up options")
        details.addWidget(self.level_up_button)
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
        previous_ids = ({select_id} if select_id is not None else
                        set(self._selected_ids()))
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
            for row in range(self.table.rowCount()):
                if self.table.item(row, 0).data(Qt.ItemDataRole.UserRole) in previous_ids:
                    self.table.selectionModel().select(
                        self.table.model().index(row, 0),
                        QItemSelectionModel.SelectionFlag.Select |
                        QItemSelectionModel.SelectionFlag.Rows
                    )
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

    def _selected_ids(self):
        selected = sorted(
            self.table.selectionModel().selectedRows(),
            key=lambda index: index.row()
        )
        return [self.table.item(idx.row(), 0).data(Qt.ItemDataRole.UserRole)
                for idx in selected if self.table.item(idx.row(), 0)]

    def _selected_id(self):
        ids = self._selected_ids()
        return ids[0] if len(ids) == 1 else None

    def selected(self):
        record_id = self._selected_id()
        return self.library.get(record_id) if record_id else None

    def selected_records(self):
        return [record for record_id in self._selected_ids()
                if (record := self.library.get(record_id)) is not None]

    def update_preview(self):
        selection = self.selected_records()
        record = selection[0] if len(selection) == 1 else None
        for control in (self.edit_button, self.duplicate_button, self.archive_button):
            control.setEnabled(record is not None)
        self.level_up_button.setEnabled(
            record is not None and record.kind in ("pc", "npc")
            and not record.archived and 1 <= record.level < 20)
        self.add_scene_button.setEnabled(bool(selection))
        self.load_selected_button.setEnabled(bool(selection))
        self.send_battle_button.setEnabled(bool(selection))
        if len(selection) > 1:
            self.preview_title.setText(f"{len(selection)} records selected")
            self.preview_sub.setText(
                "Selection includes PCs, NPCs or monsters. Load the complete "
                "record sheets into The Scribe or add them to the current scene."
            )
            self.detail.setText("\n".join(
                f"{c.name}  ·  {KIND_LABELS[c.kind]}" for c in selection
            ))
            self.notes_preview.clear()
            for score in self.stat_values.values():
                score.setText("—")
            self.archive_button.setText("Archive")
            return
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
        if not isinstance(sheet, dict):
            sheet = {}
        if record.kind == "monster" and sheet.get("monster_type"):
            computed = sheet.get("computed", {})
            if not isinstance(computed, dict):
                computed = {}
            saves = {}
            for save in ("fort", "ref", "will"):
                value = computed.get(save, 0)
                saves[save] = f"{value:+d}" if type(value) is int else "—"
            self.detail.setText(
                f"Species: {record.race_type or '—'}\n"
                f"Type: {sheet.get('monster_type', '')}"
                f"  ·  {sheet.get('size', 'Medium')}\n"
                f"Hit Dice: {computed.get('hit_dice_notation', '—')}"
                f"   ·   CR: {progression}\n"
                f"AC {record.armor_class}   ·   HP {record.max_hit_points}"
                f"   ·   BAB +{computed.get('bab', 0)}\n"
                f"Fort {saves['fort']}  /  "
                f"Ref {saves['ref']}  /  "
                f"Will {saves['will']}\n"
                "Special traits and CR require DM review."
            )
        else:
            self.detail.setText(
                f"Race / Type: {record.race_type or '—'}\n"
                f"Class: {record.character_class or '—'}\n"
                f"{progress_label}: {progression}\n"
                f"Armor Class: {record.armor_class}    ·    Hit Points: {record.max_hit_points}"
            )
        null_abilities = sheet.get("null_abilities", [])
        no_score = ({value for value in null_abilities if isinstance(value, str)}
                    if isinstance(null_abilities, list) else set())
        for attribute, score in self.stat_values.items():
            score.setText("—" if attribute in no_score else
                          str(getattr(record, attribute)))
        # Surface saved biographies without mixing them into DM notes.
        biography = (sheet.get("biography", "") if record.kind == "monster"
                     else sheet.get("background", ""))
        if isinstance(biography, str) and biography.strip():
            text = ("BESTIARY BIOGRAPHY" if record.kind == "monster"
                    else ("NPC BIOGRAPHY" if record.kind == "npc"
                          else "CHARACTER BIOGRAPHY"))
            text += "\n" + biography.strip()
            if record.notes.strip():
                text += "\n\nDM / CREATION NOTES\n" + record.notes
            self.notes_preview.setPlainText(text)
        else:
            self.notes_preview.setPlainText(record.notes)
        progression = sheet.get("progression", {})
        if isinstance(progression, dict) and type(progression.get("base_attack_bonus")) is int:
            lines = [f"LEVEL PROGRESSION · Level {record.level}",
                     f"Base attack bonus: +{progression['base_attack_bonus']}"]
            base_saves = progression.get("base_saves", {})
            if isinstance(base_saves, dict):
                lines.append("Base saves: " + " / ".join(
                    f"{name.title()} {base_saves[key]:+d}" for key, name in
                    (("fort", "Fort"), ("ref", "Ref"), ("will", "Will"))
                    if type(base_saves.get(key)) is int))
            self.detail.setText(self.detail.text() + "\n" + "\n".join(lines))
        history = sheet.get("advancement_history", [])
        if isinstance(history, list) and history:
            entries = ["LEVEL HISTORY"]
            for event in history:
                if not isinstance(event, dict):
                    continue
                entries.append(f"Level {event.get('from_level', '?')} → {event.get('to_level', '?')}: "
                               f"{event.get('hp_roll_detail') or event.get('hp_roll', '?')}; "
                               f"HP gained {event.get('hp_gain', '?')}, "
                               f"retroactive CON HP {event.get('retroactive_constitution_hp', 0)}.")
                for key in ("ability_increase", "skill_increases", "feats", "class_choices", "class_notes", "spell_notes"):
                    if event.get(key):
                        entries.append(f"{key.replace('_', ' ').title()}: {event[key]}")
            self.notes_preview.appendPlainText("\n" + "\n".join(entries))
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

    def _check_scene(self):
        if self._scene_error:
            raise ValueError(
                "Saved scene could not be read. Please back up or repair "
                "the scene for this workspace before changing it. " + self._scene_error
            )

    def add_selection_to_scene(self):
        try:
            self._check_scene()
            records = self.selected_records()
            if not records:
                raise ValueError("Select one or more library records first.")
            updated = add_records(self.scene, [r.id for r in records])
            self.scene_store.save(updated)
            self.scene = updated
            self.statusBar().showMessage(
                f"Added {len(records)} record(s) to scene. "
                f"Scene roster: {len(self.scene['record_ids'])}."
            )
        except (ValueError, OSError, sqlite3.Error) as exc:
            QMessageBox.warning(self, "Unable to update scene", str(exc))

    def edit_scene(self):
        try:
            self._check_scene()
        except ValueError as exc:
            QMessageBox.warning(self, "Scene file needs review", str(exc))
            return
        editor = SceneDialog(self.scene, self.library.list(), self)
        if editor.exec() == QDialog.DialogCode.Accepted:
            try:
                self.scene_store.save(editor.result_scene)
            except (ValueError, OSError, sqlite3.Error) as exc:
                QMessageBox.warning(self, "Scene not saved", str(exc))
                return
            self.scene = editor.result_scene
            self.statusBar().showMessage("Current scene saved locally.")

    def _scribe_scene_context(self, source):
        self._check_scene()
        if source == "scene" and self.workspace.session_id:
            from .campaign_context import build_campaign_context
            return build_campaign_context(self.campaigns, self.library,
                                          self.workspace.session_id, task="dm")
        if source == "selection":
            records = self.selected_records()
            if not records:
                raise ValueError("Select at least one record first.")
        elif source == "scene":
            index = {c.id: c for c in self.library.list()}
            missing = [key for key in self.scene["record_ids"] if key not in index]
            if missing:
                raise ValueError(
                    f"{len(missing)} scene record(s) are missing or archived. "
                    "Edit Scene to revise the roster before loading into Scribe."
                )
            records = [index[key] for key in self.scene["record_ids"]]
        else:
            raise ValueError("Unknown Scribe context source.")
        return build_scribe_context(self.scene, records, mode=source)

    def _show_scribe_context(self, source):
        try:
            context = self._scribe_scene_context(source)
        except (ValueError, OSError, sqlite3.Error) as exc:
            QMessageBox.warning(self, "Cannot load full Scribe context", str(exc))
            return
        self._open_scribe_with_context(context)

    def _open_scribe_with_context(self, context, *, task=None):
        existing = getattr(self, "_narrator_dialog", None)
        if existing is not None:
            # Explicit Load means replace the context, not the generated
            # draft. The draft is always editable and remains intact.
            existing.context.setPlainText(context)
            if task is not None:
                existing.dm_task.setCurrentIndex(existing.dm_task.findData(task))
            existing.show()
            existing.raise_()
            existing.activateWindow()
            return
        writer = AIWritingDialog("dm", context, self)
        if task is not None:
            writer.dm_task.setCurrentIndex(writer.dm_task.findData(task))
        writer.setAttribute(Qt.WidgetAttribute.WA_QuitOnClose, False)
        writer.setWindowModality(Qt.WindowModality.NonModal)
        self._narrator_dialog = writer
        writer.show()

    def discuss_battle(self):
        import json
        try:
            store = self._battle_store()
            battle = (self._battle_window.battle if self._battle_window is not None
                      else store.load() if store is not None else None)
            if battle is None or not battle.fighters:
                raise ValueError("Add combatants to Battle Trakker before asking about the current battle.")
            context = ("CURRENT D&D 3.5 BATTLE — DM CONTEXT\n"
                       "These are saved encounter instances, including current HP, initiative, "
                       "conditions, effects, and event history. Do not invent dice results or "
                       "change saved state.\n" + json.dumps(battle.snapshot(), ensure_ascii=False))
            if len(context) > 6000:
                raise ValueError("The complete battle context exceeds the Scribe's 6,000-character limit. "
                                 "Open the Scribe and enter the specific situation to discuss; "
                                 "no battle details were silently omitted.")
            self._open_scribe_with_context(context, task="dm_advice")
        except (ValueError, OSError, sqlite3.Error) as exc:
            QMessageBox.warning(self, "Cannot discuss battle", str(exc))

    def open_encounter_generator(self):
        from .encounter_ui import EncounterGeneratorDialog
        try:
            dialog = self._encounter_generator_dialog
            if dialog is None:
                dialog = EncounterGeneratorDialog(self.library.list(), self)
                self._encounter_generator_dialog = dialog
            else:
                # Keep the reviewed dice and edits available for the next
                # handoff. New rolls use the latest library templates.
                dialog.records = tuple(self.library.list())
            if dialog.exec() != QDialog.DialogCode.Accepted or dialog.result_draft is None:
                return
            draft = dialog.result_draft
            if dialog.result_action == "scene":
                self._check_scene()
                scene = draft.to_scene(self.scene)
                self.scene_store.save(scene)
                self.scene = scene
                self.statusBar().showMessage("Generated encounter saved as the current scene.")
            elif dialog.result_action == "scribe":
                self._open_scribe_with_context(draft.scribe_context(), task="session_plan")
            elif dialog.result_action == "battle":
                from copy import deepcopy
                tracker = self.open_battle_trakker()
                if tracker is None:
                    return
                candidate = deepcopy(tracker.battle)
                if not candidate.fighters:
                    candidate.title = draft.title
                candidate.scene = "\n\n".join(part for part in (candidate.scene, draft.dm_brief()) if part)
                if len(candidate.scene) > 12000:
                    raise ValueError("The combined encounter notes exceed Battle Trakker's size limit.")
                for fighter in draft.fighters:
                    candidate.add(fighter)
                tracker.store.save(candidate)
                tracker.battle = candidate
                tracker.encounter_title.setText(candidate.title)
                tracker.render()
                self.statusBar().showMessage(f"Added {len(draft.fighters)} independent combatants to Battle Trakker.")
        except (ValueError, OSError, sqlite3.Error) as exc:
            QMessageBox.warning(self, "Encounter not applied", str(exc))

    def level_up(self):
        from .advancement import needs_progression_profile
        from .advancement_ui import LevelUpDialog, ProgressionProfileDialog
        record = self.selected()
        if record is None:
            return
        try:
            profile = None
            if needs_progression_profile(record):
                profile_dialog = ProgressionProfileDialog(record, self)
                if profile_dialog.exec() != QDialog.DialogCode.Accepted:
                    return
                profile = profile_dialog.result_profile
            dialog = LevelUpDialog(record, self, profile=profile)
            if dialog.exec() == QDialog.DialogCode.Accepted and dialog.result_creature is not None:
                current = self.library.get(record.id)
                if current != record:
                    raise ValueError("This character changed while the level-up draft was open. "
                                     "Reopen Level Up to use the current sheet.")
                self.persist(dialog.result_creature)
        except (ValueError, TypeError, sqlite3.Error) as exc:
            QMessageBox.warning(self, "Unable to level up", str(exc))

    def load_selection_to_scribe(self):
        self._show_scribe_context("selection")

    def load_scene_to_scribe(self):
        self._show_scribe_context("scene")

    def open_narrator(self):
        """Open Scribe using explicit selection if present, otherwise the scene."""
        existing = getattr(self, "_narrator_dialog", None)
        if existing is not None and existing.isVisible():
            existing.raise_()
            existing.activateWindow()
            return
        self._show_scribe_context(
            "selection" if self._selected_ids() else "scene"
        )

    def closeEvent(self, event):
        # QApplication.setQuitOnLastWindowClosed(False) is intentionally used:
        # only a deliberate close of the real main window ends the app.
        try:
            self._flush_workspace()
        except (ValueError, OSError, sqlite3.Error) as exc:
            QMessageBox.warning(self, "Workspace not saved", str(exc))
            event.ignore()
            return
        super().closeEvent(event)
        if event.isAccepted():
            app = QApplication.instance()
            if app is not None:
                app.quit()

    def open_battle_trakker(self):
        """Open or reuse the live Battle Trakker without blocking Compendium."""
        from .battle_ui import BattleTrakkerDialog
        if self._battle_window is not None:
            self._battle_window.set_scene(self.scene)
            self._battle_window.show()
            self._battle_window.raise_()
            self._battle_window.activateWindow()
            return self._battle_window
        try:
            self._battle_window = BattleTrakkerDialog(
                self.library, self, scene=self.scene, store=self._battle_store(create=True))
        except (ValueError, OSError, sqlite3.Error) as exc:
            QMessageBox.warning(self, "Battle Trakker save needs review", str(exc))
            return None
        self._battle_window.show()
        return self._battle_window

    def load_selection_to_battle(self):
        records = self.selected_records()
        if not records:
            QMessageBox.information(self, "Select combatants",
                                    "Select one or more PC, NPC or monster records.")
            return
        tracker = self.open_battle_trakker()
        if tracker is not None:
            tracker._run(lambda: tracker._add_records(records))

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
        try:
            if (record.kind in ("pc", "npc") and record.sheet_json
                    and record.level == 1):
                dialog = CharacterCreatorDialog(self, creature=record)
            elif record.kind == "monster" and record.sheet_json:
                import json
                structure = json.loads(record.sheet_json)
                dialog = (MonsterCreatorDialog(self, creature=record)
                          if structure.get("monster_type") else
                          CreatureEditor(record, self))
            else:
                dialog = CreatureEditor(record, self)
        except (ValueError, TypeError, AttributeError, KeyError, OverflowError) as exc:
            QMessageBox.warning(
                self, "Unable to edit record",
                "The saved character sheet has an unrecognized structure and "
                "could not be opened. The saved record has not been changed.\n\n"
                + str(exc))
            return
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
