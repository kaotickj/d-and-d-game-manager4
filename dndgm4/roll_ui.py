"""Fantasy-styled dice tray and level-one character creator dialogs."""
from __future__ import annotations
from dataclasses import replace
import json

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFormLayout,
    QFrame, QGridLayout, QHBoxLayout, QLabel, QLineEdit, QMessageBox,
    QPlainTextEdit, QPushButton, QScrollArea, QSpinBox, QVBoxLayout,
    QWidget,
)
from .creation import (ABILITIES, CORE_CLASSES, RACIAL_ADJUSTMENTS,
                       CreationSession, adjusted_scores, build_character,
                       first_level_hp, first_level_skill_points)
from .dice import ability_modifier, percentile_answer, roll_dice, roll_expression
from .name_ui import NamePickerDialog
from .character_sheet import TEMPLATES, NPC_CLASS_TEMPLATES, skill_budget
from .npc_races import NPC_RACES, NPC_RACE_NAMES
from .sheet_ui import SheetOptions
from .ai_ui import AIWritingDialog


def text_label(value: str, role: str = "", *, wrap: bool = False) -> QLabel:
    label = QLabel(value)
    label.setTextFormat(Qt.TextFormat.PlainText)
    label.setWordWrap(wrap)
    if role:
        label.setObjectName(role)
    return label


class DiceDialog(QDialog):
    """Standalone successor to the legacy Dice Eliminator."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("The Dice Eliminator | D&D Game Manager 4")
        self.resize(760, 700)
        self.setMinimumSize(580, 520)
        self.roll_count = {}
        self.cumulative = {}
        root = QVBoxLayout(self)
        root.setContentsMargins(23, 21, 23, 20)
        root.setSpacing(14)
        root.addWidget(text_label("THE GAME MASTER'S DESK / DICE", "eyebrow"))
        root.addWidget(text_label("The Dice Eliminator", "pageTitle"))
        root.addWidget(text_label("Fair dice, visible results, and the running totals you remember.", "muted"))
        grid = QGridLayout()
        for i, sides in enumerate((4, 6, 8, 10, 12, 20, 100)):
            btn = QPushButton(f"Roll d{sides}")
            btn.setAccessibleName(f"Roll {sides}-sided dice")
            btn.clicked.connect(lambda checked=False, s=sides: self.roll_quick(s))
            grid.addWidget(btn, i // 4, i % 4)
        root.addLayout(grid)
        options = QFrame()
        options.setObjectName("panel")
        row = QHBoxLayout(options)
        row.addWidget(text_label("Dice count"))
        self.count = QSpinBox()
        self.count.setRange(1, 200)
        self.count.setValue(1)
        self.count.setAccessibleName("Dice count")
        row.addWidget(self.count)
        row.addWidget(text_label("Modifier"))
        self.modifier = QSpinBox()
        self.modifier.setRange(-100000, 100000)
        self.modifier.setPrefix("+" if self.modifier.value() > 0 else "")
        self.modifier.setAccessibleName("Dice modifier")
        row.addWidget(self.modifier)
        root.addWidget(options)
        custom = QHBoxLayout()
        self.expression = QLineEdit("2d6+3")
        self.expression.setAccessibleName("Dice expression")
        self.expression.setPlaceholderText("Examples: d20, 2d8+3, 4d6kh3")
        self.expression.returnPressed.connect(self.roll_custom)
        custom.addWidget(self.expression, 1)
        btn = QPushButton("Roll Expression")
        btn.setObjectName("primaryButton")
        btn.clicked.connect(self.roll_custom)
        custom.addWidget(btn)
        root.addLayout(custom)
        root.addWidget(text_label("Expression syntax: NdS, NdS+M, NdS-M, or NdSkhK (keep highest).", "muted"))
        self.last_result = text_label("Choose a die to begin.", "sectionTitle", wrap=True)
        self.last_result.setMinimumHeight(45)
        root.addWidget(self.last_result)
        root.addWidget(text_label("ROLL HISTORY  /  individual dice, results, and totals", "eyebrow"))
        self.history = QPlainTextEdit()
        self.history.setReadOnly(True)
        self.history.setAccessibleName("Dice roll history")
        root.addWidget(self.history, 1)
        controls = QHBoxLayout()
        clear = QPushButton("Clear History & Totals")
        clear.clicked.connect(self.clear_history)
        controls.addWidget(clear)
        copy = QPushButton("Copy History")
        copy.clicked.connect(self.copy_history)
        controls.addWidget(copy)
        controls.addStretch()
        close = QPushButton("Close")
        close.clicked.connect(self.accept)
        controls.addWidget(close)
        root.addLayout(controls)

    def record_roll(self, outcome, *, percentile=False):
        key = outcome.sides
        self.roll_count[key] = self.roll_count.get(key, 0) + outcome.count
        self.cumulative[key] = self.cumulative.get(key, 0) + outcome.total
        answer = f"  •  YES/NO: {percentile_answer(outcome.total)}" if percentile else ""
        line = (f"{outcome.notation}   {outcome.detail}{answer}\n"
                f"  d{key} dice rolled: {self.roll_count[key]}  |  "
                f"running d{key} total: {self.cumulative[key]}")
        self.last_result.setText(f"Result: {outcome.total}{answer}")
        self.history.appendPlainText(line + "\n")

    def roll_quick(self, sides: int):
        try:
            result = roll_dice(self.count.value(), sides, self.modifier.value())
            # Match the legacy percentile YES/NO on a single unmodified d100.
            self.record_roll(result, percentile=(sides == 100 and
                                                 self.count.value() == 1 and
                                                 self.modifier.value() == 0))
        except ValueError as exc:
            QMessageBox.warning(self, "Invalid dice", str(exc))

    def roll_custom(self):
        try:
            result = roll_expression(self.expression.text())
            self.record_roll(result, percentile=(result.sides == 100 and
                                                 result.count == 1 and
                                                 result.modifier == 0))
        except ValueError as exc:
            QMessageBox.warning(self, "Invalid expression", str(exc))

    def clear_history(self):
        self.roll_count.clear()
        self.cumulative.clear()
        self.history.clear()
        self.last_result.setText("Choose a die to begin.")

    def copy_history(self):
        QApplication.clipboard().setText(self.history.toPlainText())


class CharacterCreatorDialog(QDialog):
    """Original methods 1/2 with race adjustments and first-level class stats."""

    def __init__(self, parent=None, creature=None, kind="pc"):
        super().__init__(parent)
        self.original = creature
        self.kind = creature.kind if creature is not None else kind
        if self.kind not in ("pc", "npc"):
            raise ValueError("Character Forge supports PCs and NPCs.")
        self.setWindowTitle(("NPC Forge" if self.kind == "npc" else "The Character Forge") + " | D&D Game Manager 4")
        self.resize(790, 810)
        self.setMinimumSize(650, 590)
        self.result_creature = None
        self.session = CreationSession()
        self.score_inputs = {}
        self.roll_details = {}
        self.reroll_buttons = {}
        self.result_labels = {}
        outer = QVBoxLayout(self)
        outer.setContentsMargins(22, 20, 22, 18)
        outer.setSpacing(12)
        outer.addWidget(text_label("THE GAME MASTER'S DESK / CHARACTER CREATION", "eyebrow"))
        outer.addWidget(text_label("The Character Forge", "pageTitle"))
        outer.addWidget(text_label(
            "D&D 3.5 level-one NPCs: expanded ancestry and NPC classes, "
            "manual overrides for unverified races." if self.kind == "npc" else
            "Level-one character creation using D&D 3.5 core races and classes.", "muted"))
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        sheet = QWidget()
        body = QVBoxLayout(sheet)
        body.setContentsMargins(5, 5, 17, 5)
        body.setSpacing(15)

        identity = QFrame()
        identity.setObjectName("panel")
        id_form = QFormLayout(identity)
        id_form.setContentsMargins(18, 16, 18, 16)
        self.name = QLineEdit()
        self.name.setMaxLength(200)
        self.name.setPlaceholderText("Name of the adventurer")
        self.name.setAccessibleName("Character name")
        name_row = QHBoxLayout()
        name_row.addWidget(self.name, 1)
        name_button = QPushButton("Generate Name")
        name_button.clicked.connect(self.suggest_name)
        name_row.addWidget(name_button)
        id_form.addRow("Character Name *", name_row)
        self.race = QComboBox()
        self.race.addItems(NPC_RACE_NAMES if self.kind == "npc"
                           else RACIAL_ADJUSTMENTS.keys())
        if self.kind == "npc":
            self.race.setEditable(True)
            self.race.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        self.race.setAccessibleName("NPC race or species" if self.kind == "npc" else "Player race")
        self.race.currentTextChanged.connect(self.update_totals)
        if self.kind == "npc":
            self.race.currentTextChanged.connect(self.npc_race_changed)
        id_form.addRow("Race", self.race)
        self.character_class = QComboBox()
        self.character_class.addItems(CORE_CLASSES.keys())
        for extra in TEMPLATES:
            if extra not in CORE_CLASSES and (
                self.kind == "npc" or extra not in NPC_CLASS_TEMPLATES):
                self.character_class.addItem(extra)
        self.character_class.addItem("Custom / Homebrew", "__custom__")
        self.character_class.setAccessibleName("Character class")
        self.character_class.currentIndexChanged.connect(self.update_totals)
        id_form.addRow("Class", self.character_class)
        self.npc_mods = {}
        if self.kind == "npc":
            self.character_class.setCurrentText("Warrior")
            self.npc_size = QComboBox()
            self.npc_size.addItems(("Fine","Diminutive","Tiny","Small","Medium",
                                    "Large","Huge","Gargantuan","Colossal"))
            self.npc_size.currentTextChanged.connect(self.update_totals)
            id_form.addRow("NPC Size", self.npc_size)
            modifications = QHBoxLayout()
            for attribute in ABILITIES:
                column = QVBoxLayout()
                column.addWidget(text_label(attribute[:3].upper(), "statName"))
                control = QSpinBox()
                control.setRange(-30, 30)
                control.setPrefix("+" if control.value()>0 else "")
                control.setAccessibleName(attribute.title()+" racial modifier")
                control.valueChanged.connect(self.update_totals)
                column.addWidget(control)
                modifications.addLayout(column)
                self.npc_mods[attribute] = control
            id_form.addRow("Racial score modifiers", modifications)
            self.npc_race_status = text_label("", "muted", wrap=True)
            id_form.addRow("Ancestry rules", self.npc_race_status)
            self.npc_manual_ack = QCheckBox(
                "Unverified ancestry: I will review racial HD, level adjustment, "
                "traits and class-based statistics before play."
            )
            id_form.addRow("", self.npc_manual_ack)
            self.npc_race_changed()
        body.addWidget(text_label("Identity and Ancestry", "sectionTitle"))
        body.addWidget(identity)

        methods = QFrame()
        methods.setObjectName("panel")
        method_layout = QVBoxLayout(methods)
        method_layout.setContentsMargins(18, 16, 18, 16)
        self.method = QComboBox()
        self.method.addItem("Method 2: 4d6, drop lowest (original)", "method2")
        self.method.addItem("Method 1: 3d6, one reroll for scores below 10", "method1")
        self.method.addItem("Manual ability scores", "manual")
        self.method.currentIndexChanged.connect(self.change_method)
        method_layout.addWidget(self.method)
        buttons = QHBoxLayout()
        self.roll_button = QPushButton("Roll All Six Abilities")
        self.roll_button.setObjectName("primaryButton")
        self.roll_button.clicked.connect(self.roll_all)
        buttons.addWidget(self.roll_button)
        buttons.addStretch()
        method_layout.addLayout(buttons)
        body.addWidget(text_label("Ability Rolling", "sectionTitle"))
        body.addWidget(methods)

        stats = QFrame()
        stats.setObjectName("panel")
        statgrid = QGridLayout(stats)
        statgrid.setContentsMargins(17, 16, 17, 16)
        statgrid.setHorizontalSpacing(11)
        statgrid.setVerticalSpacing(10)
        for col, title in enumerate(("ABILITY", "BASE", "DICE DETAIL", "FINAL / MOD", "REROLL")):
            statgrid.addWidget(text_label(title, "eyebrow"), 0, col)
        for row, attr in enumerate(ABILITIES, start=1):
            statgrid.addWidget(text_label(attr.title(), "statName"), row, 0)
            score = QSpinBox()
            score.setRange(3, 18)
            score.setValue(10)
            score.setEnabled(False)
            score.setAccessibleName(f"{attr.title()} base ability score")
            score.valueChanged.connect(self.update_totals)
            statgrid.addWidget(score, row, 1)
            self.score_inputs[attr] = score
            detail = text_label("Not rolled", "muted", wrap=True)
            statgrid.addWidget(detail, row, 2)
            self.roll_details[attr] = detail
            result = text_label("—", "statValue")
            statgrid.addWidget(result, row, 3)
            self.result_labels[attr] = result
            reroll = QPushButton("Re-roll")
            reroll.setToolTip("Method 1 only. Once per score below 10; keep the higher.")
            reroll.clicked.connect(lambda checked=False, i=row-1: self.reroll(i))
            reroll.setEnabled(False)
            statgrid.addWidget(reroll, row, 4)
            self.reroll_buttons[attr] = reroll
        statgrid.setColumnStretch(2, 2)
        body.addWidget(stats)

        self.options = SheetOptions(self.character_class, self.race, self.final_scores)
        body.addWidget(self.options)

        info = QFrame()
        info.setObjectName("panel")
        infobox = QVBoxLayout(info)
        infobox.setContentsMargins(18, 15, 18, 15)
        self.summary = text_label("", "muted", wrap=True)
        infobox.addWidget(self.summary)
        body.addWidget(text_label("Level One Preview", "sectionTitle"))
        body.addWidget(info)
        self.notes = QPlainTextEdit()
        self.notes.setPlaceholderText("Optional character notes or background...")
        self.notes.setMinimumHeight(90)
        body.addWidget(self.notes)
        self.bio_button = QPushButton("Generate Character Biography (Local AI)")
        self.bio_button.setAccessibleName("Generate biography with locally hosted Qwen3 language model")
        self.bio_button.clicked.connect(self.write_biography)
        body.addWidget(self.bio_button)
        scroll.setWidget(sheet)
        outer.addWidget(scroll, 1)
        self.message = text_label("Roll your scores to start.", "muted", wrap=True)
        outer.addWidget(self.message)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save |
            QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.save_character)
        buttons.rejected.connect(self.reject)
        outer.addWidget(buttons)
        self.change_method()
        if self.original is not None:
            self.load_character(self.original)

    def npc_race_changed(self, *args):
        if self.kind != "npc" or not self.npc_mods:
            return
        profile = NPC_RACES.get(self.race.currentText())
        for attr,control in self.npc_mods.items():
            control.blockSignals(True)
            control.setValue(profile.ability_adjustments.get(attr,0) if profile else 0)
            control.blockSignals(False)
        self.npc_size.setCurrentText(profile.size if profile else "Medium")
        self.npc_manual_ack.setVisible(profile is None)
        self.npc_manual_ack.setChecked(False)
        if profile:
            self.npc_race_status.setText(
                "SRD-supported ancestry | LA +" + str(profile.level_adjustment) +
                " | racial HD replaced by class HD. Traits: " +
                (", ".join(profile.traits) or "Review ancestry special abilities.")
            )
        else:
            self.npc_race_status.setText(
                "Manual race. The forge builds only one class level; "
                "racial Hit Dice, level adjustment and special traits are NOT "
                "calculated. For a creature with 2+ racial HD, use Monster Forge."
            )
        self.update_totals()

    def racial_modifiers(self):
        if self.kind == "npc":
            return {name:control.value() for name,control in self.npc_mods.items()}
        return None

    def final_scores(self):
        return adjusted_scores(self.base_scores(),self.race.currentText(),
                               self.racial_modifiers())

    def load_character(self, creature):
        self.name.setText(creature.name)
        self.race.setCurrentText(creature.race_type)
        self.character_class.setCurrentText(creature.character_class)
        if self.character_class.currentText() != creature.character_class:
            self.character_class.setCurrentIndex(self.character_class.count()-1)
            self.options.custom_class_name.setText(creature.character_class)
        self.method.setCurrentIndex(2)
        race_sheet = json.loads(creature.sheet_json) if creature.sheet_json else {}
        if self.kind == "npc":
            meta = race_sheet.get("npc_ancestry", {})
            for attr, control in self.npc_mods.items():
                control.setValue(meta.get("modifiers",{}).get(
                    attr, NPC_RACES.get(creature.race_type,
                                        NPC_RACES["Human"]).ability_adjustments.get(attr,0)))
            self.npc_size.setCurrentText(meta.get("size","Medium"))
            if creature.race_type not in NPC_RACES:
                self.npc_manual_ack.setChecked(True)
        for attr, field in self.score_inputs.items():
            modifier=(self.racial_modifiers() or
                      RACIAL_ADJUSTMENTS.get(creature.race_type,{})).get(attr,0)
            field.setValue(min(18,max(3,getattr(creature,attr)-modifier)))
        self.notes.setPlainText(creature.notes)
        self.options.load_existing(creature)
        self.update_totals()

    def write_biography(self):
        scores = ", ".join(f"{attr[:3].upper()} {self.score_inputs[attr].value()}"
                           for attr in ABILITIES)
        context=(
            f"Character: {self.name.text().strip() or 'Unnamed'}, "
            f"Race: {self.race.currentText()}, Class: {self.options.current_class()}, "
            f"Alignment: {self.options.alignment.currentText()}, {scores}.\n"
            f"Personality: {self.options.personality.toPlainText()}.\n"
            f"Player notes: {self.notes.toPlainText()}"
        )
        dialog=AIWritingDialog("bio", context, self)
        if dialog.exec() == QDialog.DialogCode.Accepted and dialog.generated_text:
            self.options.background.setPlainText(dialog.generated_text)
            self.options.tabs.setCurrentIndex(2)

    def suggest_name(self):
        picker = NamePickerDialog(race=self.race.currentText(), monster=False, parent=self)
        if picker.exec() == QDialog.DialogCode.Accepted and picker.selected_name:
            self.name.setText(picker.selected_name)
            if picker.race.currentText() in (NPC_RACE_NAMES if self.kind=="npc" else RACIAL_ADJUSTMENTS):
                self.race.setCurrentText(picker.race.currentText())
            else:
                self.message.setText("Name applied. Expanded-race mechanics are not yet implemented; "
                                     "the character retains its selected core race.")

    def change_method(self, *args):
        method = self.method.currentData()
        self.session = CreationSession(method=method if method != "manual" else "method2")
        manual = method == "manual"
        self.roll_button.setEnabled(not manual)
        for attr in ABILITIES:
            self.score_inputs[attr].setEnabled(manual)
            self.score_inputs[attr].setValue(10)
            self.roll_details[attr].setText("Manual" if manual else "Not rolled")
            self.reroll_buttons[attr].setEnabled(False)
        self.message.setText("Enter unadjusted base scores." if manual else "Roll all six abilities to start.")
        self.update_totals()

    def roll_all(self):
        self.session.roll_all()
        for i, attr in enumerate(ABILITIES):
            roll = self.session.rolls[i]
            self.score_inputs[attr].setValue(roll.total)
            self.roll_details[attr].setText(roll.detail)
        self.message.setText("All six abilities rolled. Choose a race and class, then save.")
        self.update_totals()
        if self.options.build_mode.currentIndex() == 0:
            self.options.apply_preset()

    def reroll(self, index: int):
        attr = ABILITIES[index]
        try:
            improved = self.session.reroll(index)
        except ValueError as exc:
            QMessageBox.information(self, "Reroll unavailable", str(exc))
            return
        chosen = self.session.rolls[index]
        self.score_inputs[attr].setValue(chosen.total)
        self.roll_details[attr].setText(chosen.detail)
        self.message.setText(self.session.reroll_notes[-1] +
                             (". Improved!" if improved else ". Original kept."))
        self.update_totals()

    def base_scores(self):
        return {key: inp.value() for key, inp in self.score_inputs.items()}

    def update_totals(self, *args):
        # Identity widgets can emit change signals before the score grid
        # and build tabs have finished initializing.
        if len(self.score_inputs) != 6 or len(self.result_labels) != 6:
            return
        scores = self.final_scores()
        for attr in ABILITIES:
            val = scores[attr]
            self.result_labels[attr].setText(f"{val}  ({ability_modifier(val):+d})")
            idx = ABILITIES.index(attr)
            can_reroll = (self.method.currentData() == "method1"
                          and len(self.session.rolls) == 6
                          and idx not in self.session.rerolled
                          and self.session.rolls[idx].total < 10)
            self.reroll_buttons[attr].setEnabled(can_reroll)
        if hasattr(self, "options"):
            template=self.options.spec()
            hp=max(1,template.hit_die+ability_modifier(scores["constitution"]))
            skills=skill_budget(self.options.current_class(), scores["intelligence"],
                                self.race.currentText(),
                                self.options.hit_die.value(),self.options.sp_rate.value())
            self.options.update_budget()
        else:
            hp=first_level_hp(self.character_class.currentText(),scores["constitution"])
            skills=first_level_skill_points(self.character_class.currentText(),
                                             scores["intelligence"],self.race.currentText())
        size = self.npc_size.currentText() if self.kind == "npc" else ("Small (+1 AC)" if self.race.currentText() in ("Gnome", "Halfling") else "Medium")
        self.summary.setText(
            f"Maximum starting HP: {hp}    •    Unassigned skill points: {skills}\n"
            f"Size: {size}    •    Ability modifiers and racial bonuses applied.\n"
            "Use the Build, Skills and Story tabs for presets or full manual editing."
        )

    def save_character(self):
        method = self.method.currentData()
        if method != "manual" and len(self.session.rolls) != 6:
            QMessageBox.warning(self, "Roll required",
                                "Roll all six ability scores before saving.")
            return
        try:
            class_name = self.options.current_class()
            if not class_name:
                raise ValueError("Enter a name for the custom class.")
            template = self.options.spec()
            if self.kind == "npc" and (self.race.currentText() not in NPC_RACES
                                       and not self.npc_manual_ack.isChecked()):
                raise ValueError("Confirm manual ancestry review before saving an unverified NPC race.")
            created = build_character(
                name=self.name.text(), race=self.race.currentText(),
                character_class=class_name,
                base=self.base_scores(),
                method={"method1": "Original Method 1 (3d6)",
                        "method2": "Original Method 2 (4d6 drop lowest)",
                        "manual": "Manual scores"}[method],
                rolls=self.session.rolls if method != "manual" else None,
                reroll_notes=self.session.reroll_notes,
                notes=self.notes.toPlainText(),
                custom_hit_die=template.hit_die, custom_skill_points=template.skill_points,
                kind=self.kind, racial_override=self.racial_modifiers(),
                size_override=self.npc_size.currentText() if self.kind=="npc" else None,
            )
            created=self.options.finish(created)
            if self.kind == "npc":
                metadata=json.loads(created.sheet_json)
                profile=NPC_RACES.get(self.race.currentText())
                metadata["npc_ancestry"] = {
                    "race":self.race.currentText(),
                    "modifiers":self.racial_modifiers(),
                    "size":self.npc_size.currentText(),
                    "level_adjustment": profile.level_adjustment if profile else None,
                    "racial_hit_dice": profile.racial_hit_dice if profile else None,
                    "verified_profile":profile is not None,
                    "traits":list(profile.traits) if profile else [],
                    "manual_review_required":profile is None,
                }
                created=replace(created,sheet_json=json.dumps(metadata,sort_keys=True))
            
            if self.original is not None:
                created=replace(created,id=self.original.id,
                                archived=self.original.archived,
                                created_at=self.original.created_at,
                                updated_at=self.original.updated_at)
            self.result_creature=created
        except ValueError as exc:
            QMessageBox.warning(self, "Invalid character", str(exc))
            return
        self.accept()
