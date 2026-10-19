"""Fantasy-themed D&D 3.5 SRD monster builder.

Type-derived values are calculated; species traits, natural attacks, feats
and CR stay DM-editable. Preserves structured monster fields on edit.
"""
from __future__ import annotations

import json
from dataclasses import replace
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFormLayout, QGridLayout,
    QHBoxLayout, QLabel, QLineEdit, QMessageBox, QPlainTextEdit,
    QPushButton, QScrollArea, QSpinBox, QVBoxLayout, QWidget,
)

from .creation import ABILITIES
from .monster_rules import (MonsterBlueprint, TYPES, SIZES, compute_monster,
                             build_monster)
from .namegen import MONSTER_RACES
from .name_ui import NamePickerDialog
from .ai_ui import AIWritingDialog

ARRAYS = {
    "Standard monster (11/11/11/10/10/10)": (11,11,11,10,10,10),
    "Nonelite (13/12/11/10/9/8)": (13,12,11,10,9,8),
    "Elite (15/14/13/12/10/8)": (15,14,13,12,10,8),
    "Manual ability scores": (),
}

def _lines(text:str)->list[str]:
    return [s.strip() for s in text.splitlines() if s.strip()]


class MonsterCreatorDialog(QDialog):
    """Create and reopen a creature's racial-Hit-Dice statistics in one dialog."""

    def __init__(self, parent=None, creature=None):
        super().__init__(parent)
        self.original=creature
        self.result_creature=None
        self.setWindowTitle("The Monster Forge | D&D Game Manager 4")
        self.resize(880,830)
        self.setMinimumSize(630,590)
        outer=QVBoxLayout(self)
        outer.setContentsMargins(20,18,20,16)
        outer.setSpacing(10)
        heading=QLabel("THE BESTIARY / D&D 3.5 MONSTER CREATION")
        heading.setObjectName("eyebrow")
        outer.addWidget(heading)
        title=QLabel("The Monster Forge")
        title.setObjectName("pageTitle")
        outer.addWidget(title)
        disclaimer=QLabel(
            "Build an original creature using racial Hit Dice and the 15 SRD "
            "creature types. Special attacks, species traits, monster class "
            "levels, templates and CR require DM review."
        )
        disclaimer.setObjectName("muted")
        disclaimer.setWordWrap(True)
        outer.addWidget(disclaimer)

        scroll=QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setObjectName("monsterForgeScroll")
        content=QWidget()
        form=QFormLayout(content)
        form.setContentsMargins(12,12,22,12)
        form.setSpacing(10)

        name_line=QHBoxLayout()
        self.name=QLineEdit()
        self.name.setMaxLength(200)
        self.name.setPlaceholderText("e.g. Ashwood Marsh Stalker")
        name_line.addWidget(self.name,1)
        name_btn=QPushButton("Name Genie")
        name_btn.clicked.connect(self.suggest_name)
        name_line.addWidget(name_btn)
        form.addRow("Monster name *", name_line)

        self.species=QComboBox()
        self.species.setEditable(True)
        self.species.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        self.species.addItems(MONSTER_RACES)
        self.species.setCurrentText("")
        self.species.setAccessibleName("Creature species, custom names allowed")
        form.addRow("Species",self.species)

        self.type=QComboBox()
        self.type.addItems(TYPES.keys())
        self.type.setAccessibleName("Creature type")
        form.addRow("SRD creature type",self.type)
        self.subtype=QLineEdit()
        self.subtype.setPlaceholderText("e.g. Goblinoid, Air, Fire, or Aquatic")
        form.addRow("Subtype(s)", self.subtype)
        self.size=QComboBox()
        self.size.addItems(SIZES)
        self.size.setCurrentText("Medium")
        form.addRow("Size",self.size)
        self.hd=QSpinBox()
        self.hd.setRange(1,99)
        self.hd.setValue(2)
        self.hd.setAccessibleName("Number of racial Hit Dice")
        form.addRow("Racial Hit Dice",self.hd)
        self.good_save=QComboBox()
        self.good_save.addItems(("Fort","Ref","Will"))
        self.good_save.setToolTip("Used for Humanoids; Elemental uses the subtype.")
        form.addRow("Humanoid good save",self.good_save)

        self.array=QComboBox()
        self.array.addItems(ARRAYS)
        form.addRow("Ability starting array",self.array)
        stat_grid=QGridLayout()
        stat_grid.setHorizontalSpacing(12)
        stat_grid.setVerticalSpacing(8)
        self.ability_fields={}
        for i, ability in enumerate(ABILITIES):
            column=QVBoxLayout()
            caption=QLabel(ability[:3].upper())
            caption.setObjectName("statName")
            column.addWidget(caption)
            control=QSpinBox()
            control.setRange(0,99)
            control.setValue(10)
            control.setAccessibleName(ability.title()+" score")
            column.addWidget(control)
            stat_grid.addLayout(column,i//3,i%3)
            self.ability_fields[ability]=control
        form.addRow("Ability scores",stat_grid)
        missing_row=QHBoxLayout()
        self.no_con=QCheckBox("No Constitution (Construct/Undead)")
        self.no_int=QCheckBox("Mindless (no Intelligence)")
        missing_row.addWidget(self.no_con)
        missing_row.addWidget(self.no_int)
        form.addRow("Absent abilities",missing_row)

        protection=QHBoxLayout()
        self.natural_ac=self._spin(-20,99,0,"Natural armor bonus")
        self.armor_ac=self._spin(0,99,0,"Armor bonus")
        self.shield_ac=self._spin(0,99,0,"Shield bonus")
        for label,box in (("Natural",self.natural_ac),("Armor",self.armor_ac),
                          ("Shield",self.shield_ac)):
            col=QVBoxLayout()
            col.addWidget(QLabel(label))
            col.addWidget(box)
            protection.addLayout(col)
        form.addRow("AC bonuses",protection)
        self.hp_method=QComboBox()
        self.hp_method.addItem("Average Hit Dice (recommended for NPC stats)","average")
        self.hp_method.addItem("Roll racial Hit Dice on Save","rolled")
        self.hp_method.addItem("Manual HP override","manual")
        form.addRow("Hit point method",self.hp_method)
        self.manual_hp=QSpinBox()
        self.manual_hp.setRange(1,999999)
        self.manual_hp.setValue(1)
        form.addRow("Manual HP",self.manual_hp)
        self.speed=QLineEdit("30 ft.")
        form.addRow("Movement",self.speed)
        self.cr=QLineEdit()
        self.cr.setPlaceholderText("DM-selected CR: 1/4, 1/2, 1, 2 …")
        form.addRow("Challenge Rating",self.cr)
        self.alignment=QLineEdit("Neutral")
        form.addRow("Alignment",self.alignment)
        self.attacks=self._edit("Natural attacks, attack routines, damage notation")
        form.addRow("Attacks & Damage",self.attacks)
        self.special_attacks=self._edit("Spell-like/supernatural/extraordinary attacks; DM-defined DCs")
        form.addRow("Special attacks",self.special_attacks)
        self.special_qualities=self._edit("Damage reduction, immunities, senses, languages, type traits")
        form.addRow("Special qualities",self.special_qualities)
        self.feats=self._edit("One feat per line; selections and prerequisites reviewed by DM")
        form.addRow("Selected feats",self.feats)
        self.skills=self._edit("List trained skills and rank allocations; DM review")
        form.addRow("Skills",self.skills)
        self.environment=QLineEdit()
        form.addRow("Environment",self.environment)
        self.organization=QLineEdit()
        form.addRow("Organization",self.organization)
        self.treasure=QLineEdit()
        form.addRow("Treasure",self.treasure)
        self.advancement=QLineEdit()
        form.addRow("Advancement",self.advancement)
        self.la=QLineEdit()
        self.la.setPlaceholderText("Level adjustment if applicable, or —")
        form.addRow("Level adjustment",self.la)
        self.biography = QPlainTextEdit()
        self.biography.setPlaceholderText(
            "Monster ecology, origin, rumors, sightings and adventure hooks. "
            "Write manually or generate an editable draft with The Scribe."
        )
        self.biography.setAccessibleName("Monster biography and bestiary lore")
        self.biography.setMinimumHeight(155)
        self.biography.setMaximumHeight(300)
        form.addRow("Bestiary biography", self.biography)
        self.bio_button = QPushButton("Generate Monster Biography (Gemma / Qwen3)")
        self.bio_button.setObjectName("primaryButton")
        self.bio_button.setAccessibleName("Generate monster bestiary lore with a local writing model")
        self.bio_button.clicked.connect(self.write_biography)
        form.addRow("", self.bio_button)
        self.notes=self._edit("Appearance, tactics, story hooks, encounter details")
        self.notes.setMinimumHeight(90)
        form.addRow("Notes",self.notes)
        scroll.setWidget(content)
        outer.addWidget(scroll,1)

        self.preview=QLabel("")
        self.preview.setObjectName("muted")
        self.preview.setWordWrap(True)
        self.preview.setMinimumHeight(52)
        outer.addWidget(self.preview)
        bottom=QDialogButtonBox(QDialogButtonBox.StandardButton.Save |
                                QDialogButtonBox.StandardButton.Cancel)
        bottom.accepted.connect(self.save_monster)
        bottom.rejected.connect(self.reject)
        outer.addWidget(bottom)

        for widget in (self.type,self.size,self.good_save,self.array,self.hp_method):
            if widget is self.array:
                widget.currentTextChanged.connect(self.apply_array)
            else:
                widget.currentTextChanged.connect(self.on_change)
        self.subtype.textChanged.connect(self.on_change)
        self.hd.valueChanged.connect(self.on_change)
        self.manual_hp.valueChanged.connect(self.on_change)
        self.name.textChanged.connect(self.on_change)
        self.species.currentTextChanged.connect(self.on_change)
        self.no_con.toggled.connect(self.on_change)
        self.no_int.toggled.connect(self.on_change)
        for box in self.ability_fields.values():
            box.valueChanged.connect(self.on_change)
        for box in (self.natural_ac,self.armor_ac,self.shield_ac):
            box.valueChanged.connect(self.on_change)
        self.apply_array()
        self.on_change()
        if creature is not None:
            self.load_monster(creature)

    @staticmethod
    def _spin(low,high,value,name):
        box=QSpinBox()
        box.setRange(low,high)
        box.setValue(value)
        box.setAccessibleName(name)
        return box

    @staticmethod
    def _edit(placeholder):
        box=QPlainTextEdit()
        box.setPlaceholderText(placeholder)
        box.setMaximumHeight(100)
        return box

    def apply_array(self,*args):
        values=ARRAYS[self.array.currentText()]
        if values:
            for ability,score in zip(ABILITIES,values):
                self.ability_fields[ability].setValue(score)
        self.on_change()

    def on_change(self,*args):
        kind=self.type.currentText()
        no_con=TYPES[kind].no_con
        self.no_con.blockSignals(True)
        self.no_con.setChecked(no_con)
        self.no_con.setEnabled(False)  # None for undead/construct, required for others
        self.no_con.blockSignals(False)
        self.ability_fields["constitution"].setEnabled(not no_con)
        # Some mindless monster types allow a genuinely absent Int score.
        supports_mindless=kind in ("Construct","Ooze","Plant","Undead","Vermin")
        self.no_int.setEnabled(supports_mindless)
        if not supports_mindless:
            self.no_int.blockSignals(True)
            self.no_int.setChecked(False)
            self.no_int.blockSignals(False)
        self.ability_fields["intelligence"].setEnabled(not self.no_int.isChecked())
        self.manual_hp.setEnabled(self.hp_method.currentData()=="manual")
        self.good_save.setEnabled(kind=="Humanoid")
        try:
            b=self.blueprint()
            # A preview is informational; dice are only rolled when saving.
            if b.hp_method=="rolled":
                b=replace(b,hp_method="average")
            stats=compute_monster(b)
            warning=" (CR needs DM selection)" if not b.cr.strip() else ""
            self.preview.setText(
                f"{b.hit_dice}d{stats['die']} | HP {stats['hp']} | AC {stats['armor_class']} | "
                f"BAB +{stats['bab']} | Fort {stats['fort']:+d} / "
                f"Ref {stats['ref']:+d} / Will {stats['will']:+d} | "
                f"Feats {stats['feats_available']} | Skill points {stats['skill_points']}"
                + warning)
        except ValueError as exc:
            self.preview.setText("Rules preview: "+str(exc))

    def blueprint(self):
        return MonsterBlueprint(
            name=self.name.text(),species=self.species.currentText(),
            creature_type=self.type.currentText(),hit_dice=self.hd.value(),
            abilities={name:(None if (name=="constitution" and self.no_con.isChecked())
                             or (name=="intelligence" and self.no_int.isChecked())
                             else box.value())
                       for name,box in self.ability_fields.items()},
            size=self.size.currentText(),subtype=self.subtype.text(),
            good_save=self.good_save.currentText(),natural_armor=self.natural_ac.value(),
            armor_bonus=self.armor_ac.value(),shield_bonus=self.shield_ac.value(),
            speed=self.speed.text(),attacks=self.attacks.toPlainText(),
            special_attacks=self.special_attacks.toPlainText(),
            special_qualities=self.special_qualities.toPlainText(),
            feats=_lines(self.feats.toPlainText()),skills=self.skills.toPlainText(),
            cr=self.cr.text(),alignment=self.alignment.text(),
            environment=self.environment.text(),organization=self.organization.text(),
            treasure=self.treasure.text(),advancement=self.advancement.text(),
            level_adjustment=self.la.text(),notes=self.notes.toPlainText(),
            biography=self.biography.toPlainText(),
            hp_method=self.hp_method.currentData(),
            manual_hit_points=self.manual_hp.value())

    def suggest_name(self):
        picker=NamePickerDialog(race=self.species.currentText() or "Goblin",
                                monster=True,parent=self)
        if picker.exec()==QDialog.DialogCode.Accepted and picker.selected_name:
            self.name.setText(picker.selected_name)
            if not self.species.currentText().strip():
                self.species.setCurrentText(picker.race.currentText())

    def write_biography(self):
        """Let either local writing model draft lore without changing stats."""
        attributes = ", ".join(
            f"{name[:3].upper()} "
            f"{'No score' if (name == 'constitution' and self.no_con.isChecked()) or (name == 'intelligence' and self.no_int.isChecked()) else box.value()}"
            for name, box in self.ability_fields.items()
        )
        context = "\n".join((
            f"Name: {self.name.text() or 'Unnamed creature'}",
            f"Species: {self.species.currentText() or 'Original species'}",
            f"Type: {self.type.currentText()}; subtype: {self.subtype.text()}",
            f"Size: {self.size.currentText()}; racial Hit Dice: {self.hd.value()}",
            f"Ability scores: {attributes}",
            f"Intelligence: {'Mindless' if self.no_int.isChecked() else str(self.ability_fields['intelligence'].value())}",
            f"Alignment: {self.alignment.text()}",
            f"Environment: {self.environment.text()}",
            f"Organization: {self.organization.text()}",
            f"Speed: {self.speed.text()}",
            f"Attacks: {self.attacks.toPlainText()[:550]}",
            f"Special attacks: {self.special_attacks.toPlainText()[:550]}",
            f"Special qualities: {self.special_qualities.toPlainText()[:550]}",
            f"Selected feats: {self.feats.toPlainText()[:300]}",
            f"Selected skills: {self.skills.toPlainText()[:300]}",
            f"Existing lore: {self.biography.toPlainText()[:800]}",
            f"DM notes: {self.notes.toPlainText()[:800]}",
            "Create story and ecology, not new game rules or a stat block.",
        ))
        dialog = AIWritingDialog("monster_bio", context[:6000], self)
        if (dialog.exec() == QDialog.DialogCode.Accepted
                and dialog.generated_text and dialog.generated_text.strip()):
            if self.biography.toPlainText().strip():
                choice = QMessageBox.question(
                    self, "Replace existing monster biography?",
                    "The bestiary biography already contains text. Replace it "
                    "with the reviewed AI draft? Monster statistics and DM "
                    "notes will remain unchanged.",
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                    QMessageBox.StandardButton.No,
                )
                if choice != QMessageBox.StandardButton.Yes:
                    return
            self.biography.setPlainText(dialog.generated_text)

    def save_monster(self):
        try:
            result=build_monster(self.blueprint())
            if self.original is not None:
                result=replace(result,id=self.original.id,
                               archived=self.original.archived,
                               created_at=self.original.created_at,
                               updated_at=self.original.updated_at)
            self.result_creature=result
        except ValueError as exc:
            QMessageBox.warning(self,"Invalid monster",str(exc))
            return
        self.accept()

    def load_monster(self,record):
        if not record.sheet_json:
            return
        data=json.loads(record.sheet_json)
        if data.get("version")!=1 or not data.get("monster_type"):
            return
        self.name.setText(record.name)
        self.species.setCurrentText(data.get("species",record.race_type))
        self.type.setCurrentText(data["monster_type"])
        self.subtype.setText(data.get("subtype",""))
        self.size.setCurrentText(data.get("size","Medium"))
        self.hd.setValue(data.get("hit_dice",1))
        for attr,box in self.ability_fields.items():
            box.setValue(getattr(record,attr) if attr not in data.get("null_abilities",[]) else 0)
        self.no_int.setChecked("intelligence" in data.get("null_abilities",[]))
        self.natural_ac.setValue(data.get("natural_armor",0))
        self.armor_ac.setValue(data.get("armor_bonus",0))
        self.shield_ac.setValue(data.get("shield_bonus",0))
        self.speed.setText(data.get("speed",""))
        self.cr.setText(record.challenge_rating)
        for key,ctrl in (("attacks",self.attacks),
                         ("special_attacks",self.special_attacks),
                         ("special_qualities",self.special_qualities),
                         ("skills",self.skills),("notes",self.notes)):
            ctrl.setPlainText(data.get(key,""))
        self.biography.setPlainText(data.get("biography", ""))
        self.feats.setPlainText("\n".join(data.get("feats",[])))
        for key,ctrl in (("alignment",self.alignment),
                         ("environment",self.environment),
                         ("organization",self.organization),
                         ("treasure",self.treasure),
                         ("advancement",self.advancement),
                         ("level_adjustment",self.la)):
            ctrl.setText(data.get(key,""))
        self.manual_hp.setValue(data.get("manual_hit_points",
                                         record.max_hit_points))
        # Preserve existing rolled HP when editing unrelated fields. Select
        # "Roll racial Hit Dice" explicitly to reroll on the next save.
        self.hp_method.setCurrentIndex(
            2 if data.get("hp_method") in ("manual","rolled") else 0)
        self.on_change()
