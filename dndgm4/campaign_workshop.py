"""Campaign Workshop: coherent party-aware, user-reviewed local AI drafting.

One local active campaign, without altering the existing SQLite creature
schema. Only explicit Save/Import commits edited campaign data or creatures.
"""
from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QComboBox, QDialog, QDialogButtonBox, QFormLayout, QGridLayout, QGroupBox,
    QHBoxLayout, QLabel, QLineEdit, QListWidget, QListWidgetItem, QMessageBox,
    QPlainTextEdit, QPushButton, QScrollArea, QTabWidget, QVBoxLayout, QWidget,
)
from .ai_ui import AIWritingDialog
from .campaign_core import (
    CampaignStore, FIELDS, campaign_context, creature_from_ai_draft,
    random_encounter_seed, parse_model_json, validate_encounter_draft,
    append_chapter, save_outline, MAX_ENCOUNTERS,
)
from .character_sheet import TEMPLATES
from .npc_races import NPC_RACES
from .models import Creature
from .storage import CreatureRepository


class CampaignWorkshop(QDialog):
    """Editor for campaign continuity + encounters, characters and chapters."""

    MULTILINE = (
        "setting", "premise", "scenery", "conditions", "settlements",
        "inns_taverns", "factions", "current_quests", "session_notes"
    )

    def __init__(self, library: CreatureRepository, parent=None):
        super().__init__(parent)
        self.library = library
        self.store = CampaignStore(library.path)
        self.campaign = self.store.load()
        self.setWindowTitle("The Scribe | Campaign Workshop")
        self.resize(1000, 830)
        self.setMinimumSize(740, 580)
        root = QVBoxLayout(self)
        root.setContentsMargins(20, 16, 20, 16)
        root.setSpacing(10)
        eyebrow = QLabel("THE GAME MASTER'S DESK / CAMPAIGN CONTINUITY")
        eyebrow.setObjectName("eyebrow")
        root.addWidget(eyebrow)
        heading = QLabel("The Scribe's Campaign Workshop")
        heading.setObjectName("pageTitle")
        root.addWidget(heading)
        note = QLabel(
            "Gemma or Qwen3 can draft encounters, original characters, NPCs, "
            "monsters and chapter-by-chapter campaigns. Your party, scene, "
            "named places and lore inform the drafts. Nothing is imported "
            "without your review. All AI-generated rules require DM verification."
        )
        note.setObjectName("muted")
        note.setWordWrap(True)
        root.addWidget(note)

        self.tabs = QTabWidget()
        root.addWidget(self.tabs, 1)
        self._context_tab()
        self._generator_tab()
        self._campaign_tab()

        bottom = QHBoxLayout()
        self.status = QLabel("Changes to campaign details must be saved.")
        self.status.setObjectName("muted")
        self.status.setWordWrap(True)
        bottom.addWidget(self.status, 1)
        save = QPushButton("Save Campaign Context")
        save.setObjectName("primaryButton")
        save.clicked.connect(self.save_context)
        bottom.addWidget(save)
        close = QPushButton("Close")
        close.clicked.connect(self.accept)
        bottom.addWidget(close)
        root.addLayout(bottom)

    def _context_tab(self):
        page = QWidget()
        self.tabs.addTab(page, "World & Present Parties")
        root = QVBoxLayout(page)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        formpage = QWidget()
        form = QFormLayout(formpage)
        form.setContentsMargins(12, 14, 22, 12)
        form.setSpacing(10)
        self.fields = {}
        descriptions = {
            "title": "Campaign title",
            "setting": "World, region, era and tone references",
            "premise": "Campaign premise and established canon",
            "tone": "Genre / tone",
            "location": "Current location",
            "scenery": "Scenery, terrain, points of interest",
            "conditions": "Weather, time, conditions, ongoing hazards",
            "settlements": "Towns, villages, streets, landmarks",
            "inns_taverns": "Inns, taverns, shops, temples and their owners",
            "factions": "Factions, alliances, enemies and named contacts",
            "current_quests": "Current quests, leads, conflicts and goals",
            "session_notes": "Session chronology, rumors, secrets and changes",
        }
        for key in FIELDS:
            if key in self.MULTILINE:
                widget = QPlainTextEdit()
                widget.setMinimumHeight(76)
                widget.setMaximumHeight(130)
                widget.setPlaceholderText(descriptions[key])
                widget.setPlainText(self.campaign[key])
            else:
                widget = QLineEdit(self.campaign[key])
                widget.setPlaceholderText(descriptions[key])
            widget.setAccessibleName(descriptions[key])
            form.addRow(descriptions[key], widget)
            self.fields[key] = widget

        roster = QHBoxLayout()
        self.party = QListWidget()
        self.present = QListWidget()
        self.party.setAccessibleName("Party member checkboxes")
        self.present.setAccessibleName("Additional people and monsters present")
        all_records = self.library.list()
        for record in all_records:
            # The left list intentionally holds only PCs; the right one can
            # hold PCs, NPCs and monsters participating in the current scene.
            if record.kind == "pc":
                self._add_member(self.party, record, "party_ids")
            self._add_member(self.present, record, "present_ids")
        for heading, listbox in (
            ("Active adventuring party (PCs)", self.party),
            ("Others present (PCs / NPCs / monsters)", self.present)
        ):
            column = QVBoxLayout()
            label = QLabel(heading)
            label.setObjectName("sectionTitle")
            column.addWidget(label)
            listbox.setMinimumHeight(160)
            column.addWidget(listbox)
            roster.addLayout(column, 1)
        form.addRow("Present parties", roster)
        scroll.setWidget(formpage)
        root.addWidget(scroll)

    def _add_member(self, widget: QListWidget, record: Creature, key: str):
        rating = f"CR {record.challenge_rating or '?'}" if record.kind == "monster" else f"lvl {record.level}"
        item = QListWidgetItem(f"{record.name} • {record.kind.upper()} • {rating}")
        item.setData(Qt.ItemDataRole.UserRole, record.id)
        item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
        item.setCheckState(Qt.CheckState.Checked if record.id in self.campaign[key]
                           else Qt.CheckState.Unchecked)
        widget.addItem(item)

    @staticmethod
    def _checked(widget: QListWidget) -> list[str]:
        return [widget.item(i).data(Qt.ItemDataRole.UserRole)
                for i in range(widget.count())
                if widget.item(i).checkState() == Qt.CheckState.Checked]

    def read_context(self) -> dict:
        current = dict(self.campaign)
        for key, widget in self.fields.items():
            current[key] = (widget.toPlainText() if isinstance(widget, QPlainTextEdit)
                            else widget.text())
        current["party_ids"] = self._checked(self.party)
        current["present_ids"] = self._checked(self.present)
        return current

    def save_context(self):
        try:
            self.campaign = self.read_context()
            self.store.save(self.campaign)
        except (ValueError, OSError) as error:
            QMessageBox.warning(self, "Campaign save failed", str(error))
            return False
        self.status.setText("Campaign context saved locally.")
        return True

    def _generator_tab(self):
        page = QWidget()
        self.tabs.addTab(page, "Encounters & Creatures")
        root = QVBoxLayout(page)
        label = QLabel("PROPOSE, INSPECT, THEN IMPORT")
        label.setObjectName("eyebrow")
        root.addWidget(label)
        instruction = QLabel(
            "Random encounters use only saved NPC and monster records, plus "
            "your current party and conditions. New PCs, NPCs and monsters "
            "are checked by the existing rules builders. Level-one class "
            "features, feats, spells, monster abilities and CR still need "
            "the DM's final review."
        )
        instruction.setWordWrap(True)
        root.addWidget(instruction)
        grid = QGridLayout()
        buttons = (
            ("Generate Random Encounter", "encounter_json"),
            ("Generate Player Character", "pc_json"),
            ("Generate NPC", "npc_json"),
            ("Generate Monster", "monster_json"),
        )
        self.generator_buttons = {}
        for i, (text, kind) in enumerate(buttons):
            button = QPushButton(text)
            button.setObjectName("primaryButton" if i == 0 else "generatorButton")
            button.clicked.connect(lambda checked=False, k=kind: self.generate(k))
            button.setAccessibleName(text)
            grid.addWidget(button, i // 2, i % 2)
            self.generator_buttons[kind] = button
        root.addLayout(grid)
        root.addWidget(QLabel("Saved Encounters (inspect after generation)"))
        self.encounter_selector = QComboBox()
        self.encounter_selector.currentIndexChanged.connect(self.show_encounter)
        root.addWidget(self.encounter_selector)
        self.encounter_preview = QPlainTextEdit()
        self.encounter_preview.setReadOnly(True)
        self.encounter_preview.setPlaceholderText("Encounter suggestions appear here after review.")
        root.addWidget(self.encounter_preview, 1)
        self._refresh_encounters()

    def _refresh_encounters(self):
        self.encounter_selector.blockSignals(True)
        self.encounter_selector.clear()
        for i, encounter in enumerate(self.campaign.get("encounters", [])):
            self.encounter_selector.addItem(
                encounter.get("title", f"Encounter {i+1}"), i)
        self.encounter_selector.blockSignals(False)
        self.show_encounter()

    def show_encounter(self, *args):
        index = self.encounter_selector.currentIndex()
        if 0 <= index < len(self.campaign.get("encounters", [])):
            data = self.campaign["encounters"][index]
            lines = [data["title"], f"Location: {data['location']}",
                     "", data["setup"], "", "Read aloud:", data["read_aloud"],
                     "", "Participants:"]
            for actor in data["participants"]:
                lines.append(f"  {actor['count']} × {actor['name']} "
                             f"(CR {actor['cr'] or 'unassigned'})")
            lines += ["", "Terrain: " + data["terrain"],
                      "Stakes: " + data["stakes"],
                      "Consequences: " + data["consequences"],
                      "", data["gm_review"]]
            self.encounter_preview.setPlainText("\n".join(lines))
        else:
            self.encounter_preview.clear()

    def _campaign_tab(self):
        page = QWidget()
        self.tabs.addTab(page, "Campaign Architect")
        root = QVBoxLayout(page)
        instruction = QLabel(
            "Build a campaign over multiple local model requests. Start "
            "with an outline; generate and revise chapters one at a time. "
            "Saved chapter text and continuity are used for future drafts."
        )
        instruction.setWordWrap(True)
        root.addWidget(instruction)
        outline_tools = QHBoxLayout()
        write_outline = QPushButton("Draft Campaign Outline (Gemma / Qwen3)")
        write_outline.setObjectName("primaryButton")
        write_outline.clicked.connect(lambda: self.generate("campaign_outline"))
        outline_tools.addWidget(write_outline)
        keep_outline = QPushButton("Save Outline")
        keep_outline.clicked.connect(self.save_outline)
        outline_tools.addWidget(keep_outline)
        root.addLayout(outline_tools)
        self.outline = QPlainTextEdit(self.campaign.get("outline", ""))
        self.outline.setAccessibleName("Editable campaign outline")
        self.outline.setMinimumHeight(160)
        root.addWidget(self.outline, 2)
        chapter_row = QHBoxLayout()
        chapter_row.addWidget(QLabel("Chapter"))
        self.chapter_selector = QComboBox()
        self.chapter_selector.currentIndexChanged.connect(self.show_chapter)
        chapter_row.addWidget(self.chapter_selector, 1)
        new_chapter = QPushButton("New Chapter")
        new_chapter.clicked.connect(self.new_chapter)
        chapter_row.addWidget(new_chapter)
        root.addLayout(chapter_row)
        self.chapter_title = QLineEdit()
        self.chapter_title.setPlaceholderText("Chapter title")
        root.addWidget(self.chapter_title)
        self.chapter_body = QPlainTextEdit()
        self.chapter_body.setPlaceholderText("Generate the next chapter or write your own.")
        self.chapter_body.setMinimumHeight(120)
        root.addWidget(self.chapter_body, 3)
        chapters_actions = QHBoxLayout()
        generate = QPushButton("Draft Next Chapter")
        generate.setObjectName("primaryButton")
        generate.clicked.connect(lambda: self.generate("campaign_chapter"))
        chapters_actions.addWidget(generate)
        save = QPushButton("Save Chapter")
        save.clicked.connect(self.save_chapter)
        chapters_actions.addWidget(save)
        root.addLayout(chapters_actions)
        self._refresh_chapters()

    def _refresh_chapters(self):
        self.chapter_selector.blockSignals(True)
        self.chapter_selector.clear()
        self.chapter_selector.addItem("Unsaved / new chapter", -1)
        for index, chapter in enumerate(self.campaign.get("chapters", [])):
            self.chapter_selector.addItem(
                f"{index + 1}. {chapter['title']}", index)
        self.chapter_selector.blockSignals(False)

    def new_chapter(self):
        self.chapter_selector.setCurrentIndex(0)
        self.chapter_title.clear()
        self.chapter_body.clear()

    def show_chapter(self, *args):
        index = self.chapter_selector.currentData()
        if index is None or index < 0:
            return
        chapter = self.campaign["chapters"][index]
        self.chapter_title.setText(chapter["title"])
        self.chapter_body.setPlainText(chapter["text"])

    def save_outline(self):
        try:
            self.campaign = save_outline(self.read_context(),
                                         self.outline.toPlainText())
            self.store.save(self.campaign)
        except (ValueError, OSError) as exc:
            QMessageBox.warning(self, "Outline not saved", str(exc))
            return False
        self.status.setText("Campaign outline saved locally.")
        return True

    def save_chapter(self):
        title, text = self.chapter_title.text(), self.chapter_body.toPlainText()
        try:
            current = self.read_context()
            index = self.chapter_selector.currentData()
            if index is None or index < 0:
                current = append_chapter(current, title, text)
            else:
                # Validate changes using the same function as new chapters.
                candidate = append_chapter(
                    {**current, "chapters": []}, title, text)["chapters"][0]
                chapters = list(current["chapters"])
                chapters[index] = candidate
                current["chapters"] = chapters
            self.store.save(current)
            self.campaign = current
        except (ValueError, OSError) as exc:
            QMessageBox.warning(self, "Chapter not saved", str(exc))
            return False
        self._refresh_chapters()
        self.chapter_selector.setCurrentIndex(len(self.campaign["chapters"]))
        self.status.setText("Chapter saved. Continue writing when ready.")
        return True

    def _prompt_context(self, kind):
        current = self.read_context()
        world = campaign_context(current, self.library.list())
        outline = self.outline.toPlainText().strip()
        if kind == "encounter_json":
            world += ("\nAVAILABLE ENCOUNTER ACTORS (copy record_id exactly):\n"
                      + random_encounter_seed(self.library.list()))
        if kind in ("pc_json", "npc_json"):
            options = [name for name in TEMPLATES if
                       kind == "npc_json" or
                       name not in ("Adept","Aristocrat","Commoner","Expert","Warrior")]
            world += ("\nAVAILABLE CLASS LIST: " + ", ".join(options[:50]))
            if kind == "npc_json":
                world += "\nVERIFIED NPC RACES: " + ", ".join(NPC_RACES)
        if kind in ("campaign_outline", "campaign_chapter"):
            world += "\nCurrent campaign outline:\n" + outline[:3000]
        if kind == "campaign_chapter":
            last = self.campaign.get("chapters", [])[-2:]
            for chapter in last:
                world += ("\nPreviously saved chapter: " + chapter["title"] +
                          "\n" + chapter["text"][:1300])
            world += ("\nNew chapter request / title: " +
                      self.chapter_title.text().strip())
        return world[:6000] or "Original D&D 3.5 fantasy campaign."

    def generate(self, kind: str):
        if kind not in ("encounter_json","pc_json","npc_json","monster_json",
                        "campaign_outline","campaign_chapter"):
            raise ValueError("Unsupported Campaign Workshop generation task.")
        if not self.save_context():
            return
        context = self._prompt_context(kind)
        dialog = AIWritingDialog(kind, context, self)
        if (dialog.exec() != QDialog.DialogCode.Accepted or
                not dialog.generated_text or not dialog.generated_text.strip()):
            return
        text = dialog.generated_text.strip()
        try:
            if kind == "encounter_json":
                self._import_encounter(parse_model_json(text))
            elif kind in ("pc_json","npc_json","monster_json"):
                self._import_creature(parse_model_json(text),
                                      kind.removesuffix("_json"))
            elif kind == "campaign_outline":
                self.outline.setPlainText(text)
                self.tabs.setCurrentIndex(2)
                self.status.setText("Outline draft loaded for review. Click Save Outline.")
            else:
                if self.chapter_selector.currentData() not in (-1, None):
                    self.new_chapter()
                self.chapter_title.setText(
                    self.chapter_title.text() or
                    f"Chapter {len(self.campaign.get('chapters', [])) + 1}")
                self.chapter_body.setPlainText(text)
                self.tabs.setCurrentIndex(2)
                self.status.setText("Chapter draft loaded for review. Click Save Chapter.")
        except (ValueError, OSError) as exc:
            QMessageBox.warning(self, "Draft needs correction", str(exc) +
                                "\nEdit the AI draft and retry generation/import.")

    def _import_encounter(self, payload: dict):
        entry = validate_encounter_draft(payload, self.library.list())
        if len(self.campaign.get("encounters", [])) >= MAX_ENCOUNTERS:
            raise ValueError("Campaign has reached its saved encounter limit.")
        actor_list = (", ".join(f"{p['count']} × {p['name']}"
                                for p in entry["participants"]) or "None")
        approved = QMessageBox.question(
            self, "Save proposed encounter?",
            f"{entry['title']}\n\nLocation: {entry['location']}\n"
            f"Participants: {actor_list}\n\n{entry['setup'][:700]}\n\n"
            "This is a narrative proposal, NOT an automatically verified "
            "encounter level or balanced battle. Save for DM review?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if approved != QMessageBox.StandardButton.Yes:
            return
        current = self.read_context()
        current["encounters"] = list(current["encounters"]) + [entry]
        self.store.save(current)
        self.campaign = current
        self._refresh_encounters()
        self.encounter_selector.setCurrentIndex(len(current["encounters"])-1)
        self.status.setText("Encounter saved. Existing creature records are linked, not duplicated.")

    def _import_creature(self, payload: dict, kind: str):
        record = creature_from_ai_draft(payload, kind)
        description = (
            f"Name: {record.name}\nType: {record.kind.upper()}\n"
            f"Race / species: {record.race_type}\n"
            f"Class / monster type: {record.character_class}\n"
            f"Level: {record.level}\nHP: {record.max_hit_points}\n"
            f"AC: {record.armor_class}\n\n"
            "D&D 3.5 calculation used the existing rule engine, NOT the "
            "model's guessed combat statistics.\n\n"
            "Full advancement, feat prerequisites, spells, monster traits, "
            "equipment and CR still need the DM's verification.\n\n"
            "Add this reviewed draft to your creature library?"
        )
        approved = QMessageBox.question(
            self, "Import reviewed character/creature?", description,
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if approved != QMessageBox.StandardButton.Yes:
            return
        saved = self.library.save(record)
        self.status.setText(f"Imported {saved.name} as {kind.upper()}. Open in Forge to refine.")

