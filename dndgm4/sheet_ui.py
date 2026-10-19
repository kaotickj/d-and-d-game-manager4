"""First-level skill, feat, equipment and character-detail editor.

All automatic builds are editable. Supplemental classes are transparent
starting templates: class features and legal feat/spell prerequisites require
human review. The same control surface handles custom class entry.
"""
from __future__ import annotations
from dataclasses import replace

import json
from PyQt6.QtWidgets import (
    QComboBox, QDoubleSpinBox, QFormLayout, QFrame, QGridLayout, QHBoxLayout,
    QLabel, QLineEdit, QPlainTextEdit, QPushButton, QScrollArea, QSpinBox,
    QTabWidget, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)
from PyQt6.QtCore import Qt

from .character_sheet import (
    ALIGNMENTS, SKILLS, TEMPLATES, allocate_default_skills, build_sheet,
    class_specs, skill_budget, validate_allocations, load_sheet
)
from .spell_rules import CASTERS, SPELL_LISTS, default_spellbook, spell_profile, validate_spellbook
from .build_rules import inventory_from_text, inventory_to_text, feat_review

FIRST_LEVEL_FEATURES = {
    "Barbarian": ("Rage 1/day", "Fast movement"),
    "Bard": ("Bardic music", "Bardic knowledge"),
    "Cleric": ("Turn or rebuke undead", "Two divine domains (choose and verify)"),
    "Druid": ("Animal companion", "Nature sense", "Wild empathy",
              "Spontaneous summon nature's ally"),
    "Fighter": ("Fighter bonus combat feat",),
    "Monk": ("Flurry of blows", "Unarmed strike", "AC bonus",
             "Choose monk bonus feat (DM review)"),
    "Paladin": ("Aura of good", "Detect evil", "Smite evil 1/day"),
    "Ranger": ("Favored enemy", "Track (bonus feat)", "Wild empathy"),
    "Rogue": ("Sneak attack +1d6", "Trapfinding"),
    "Sorcerer": ("Summon familiar",),
    "Wizard": ("Scribe Scroll (bonus feat)", "Summon familiar"),
}



def lines(value: str) -> list[str]:
    return [line.strip() for line in value.replace(",", "\n").splitlines()
            if line.strip()]


class SheetOptions(QWidget):
    """Configurable sheet details, embedded in the existing Character Forge."""

    def __init__(self, class_picker: QComboBox, race_picker: QComboBox,
                 scores_provider, parent=None):
        super().__init__(parent)
        self.class_picker = class_picker
        self.race_picker = race_picker
        self.scores_provider = scores_provider
        self.skill_fields = {}
        root = QVBoxLayout(self)
        root.setContentsMargins(0,0,0,0)
        root.setSpacing(8)
        title = QLabel("Build, Skills, Equipment & Character Details")
        title.setObjectName("sectionTitle")
        root.addWidget(title)
        self.tabs = QTabWidget()
        self.tabs.setObjectName("sheetTabs")
        root.addWidget(self.tabs)
        self._build_tab()
        self._skills_tab()
        self._story_tab()
        self._magic_tab()
        self._inventory_tab()
        self.class_picker.currentIndexChanged.connect(self.change_class)
        self.race_picker.currentIndexChanged.connect(self.update_budget)
        self.change_class()

    def _build_tab(self):
        page = QWidget()
        form = QFormLayout(page)
        form.setContentsMargins(16,16,16,12)
        form.setSpacing(10)
        self.build_mode = QComboBox()
        self.build_mode.addItems((
            "Recommended class starter build",
            "Custom build (manually choose everything)",
            "Blank sheet (start empty)",
        ))
        self.build_mode.currentIndexChanged.connect(self.apply_preset)
        form.addRow("Build method", self.build_mode)
        self.custom_class_name = QLineEdit()
        self.custom_class_name.setPlaceholderText("Enter homebrew class name")
        form.addRow("Custom class", self.custom_class_name)
        hp_sp = QHBoxLayout()
        self.hit_die = QSpinBox()
        self.hit_die.setRange(4,20)
        self.hit_die.setValue(8)
        self.hit_die.setPrefix("d")
        self.hit_die.setAccessibleName("Class hit die")
        hp_sp.addWidget(self.hit_die)
        self.sp_rate = QSpinBox()
        self.sp_rate.setRange(1,20)
        self.sp_rate.setValue(4)
        self.sp_rate.setSuffix(" + INT")
        self.sp_rate.setAccessibleName("Skill points per level")
        hp_sp.addWidget(self.sp_rate)
        form.addRow("Hit die / skill rate", hp_sp)
        self.custom_skills = QLineEdit()
        self.custom_skills.setPlaceholderText("For homebrew: comma-separated class skills")
        form.addRow("Additional class skills", self.custom_skills)
        self.custom_skills.textChanged.connect(self.refresh_skill_types)
        self.template_status = QLabel()
        self.template_status.setObjectName("muted")
        self.template_status.setWordWrap(True)
        form.addRow("",self.template_status)
        self.feats = QPlainTextEdit()
        self.feats.setPlaceholderText("One feat per line. GM review required for prerequisites/bonus feats.")
        self.feats.setMaximumHeight(100)
        self.feats.setAccessibleName("Character feats")
        form.addRow("Feats (editable)",self.feats)
        self.equipment = QPlainTextEdit()
        self.equipment.setPlaceholderText("One equipment item per line; edit suggested kit freely.")
        self.equipment.setMaximumHeight(120)
        self.equipment.setAccessibleName("Starting equipment")
        form.addRow("Equipment",self.equipment)
        self.features = QPlainTextEdit()
        self.features.setPlaceholderText("Class features, bonus feats, special abilities, custom rules...")
        self.features.setMaximumHeight(95)
        form.addRow("Special abilities",self.features)
        self.tabs.addTab(page,"Class Build & Gear")

    def _skills_tab(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(14,12,14,12)
        label = QLabel("Allocate first-level ranks. Class ranks cost 1 point each; cross-class ranks cost 2.")
        label.setObjectName("muted")
        label.setWordWrap(True)
        layout.addWidget(label)
        self.skill_budget_label = QLabel("Skill budget: —")
        self.skill_budget_label.setObjectName("sectionTitle")
        layout.addWidget(self.skill_budget_label)
        table = QTableWidget(len(SKILLS),3)
        table.setHorizontalHeaderLabels(("Skill","Training","Ranks"))
        table.horizontalHeader().setStretchLastSection(True)
        table.verticalHeader().hide()
        table.setAlternatingRowColors(True)
        table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        table.setColumnWidth(0,230)
        table.setColumnWidth(1,105)
        table.setMinimumHeight(265)
        for row, name in enumerate(SKILLS):
            table.setItem(row,0,QTableWidgetItem(name))
            table.setItem(row,1,QTableWidgetItem("Cross-class"))
            field = QDoubleSpinBox()
            field.setRange(0,2)
            field.setSingleStep(.5)
            field.setDecimals(1)
            field.setAccessibleName(f"{name} ranks")
            field.valueChanged.connect(self.update_budget)
            table.setCellWidget(row,2,field)
            self.skill_fields[name] = field
        layout.addWidget(table,1)
        self.skill_table = table
        self.tabs.addTab(page,"Skills")

    def _story_tab(self):
        page = QWidget()
        form = QFormLayout(page)
        form.setContentsMargins(14,12,14,12)
        form.setSpacing(10)
        self.alignment = QComboBox()
        self.alignment.addItems(ALIGNMENTS)
        self.alignment.setCurrentText("True Neutral")
        form.addRow("Alignment",self.alignment)
        self.deity = QLineEdit()
        form.addRow("Deity / faith",self.deity)
        self.languages = QLineEdit("Common")
        form.addRow("Languages",self.languages)
        self.gender = QComboBox()
        self.gender.setEditable(True)
        self.gender.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        self.gender.addItems(("Unspecified", "Female", "Male", "Nonbinary",
                              "Genderless", "Other"))
        self.gender.setAccessibleName("Character gender or identity")
        self.gender.setToolTip("Descriptive only; no game-mechanical modifiers.")
        form.addRow("Gender", self.gender)
        self.age = QLineEdit()
        self.age.setMaxLength(80)
        self.age.setPlaceholderText("e.g. 24 years, venerable, ageless")
        self.age.setAccessibleName("Character age or life stage")
        self.age.setToolTip("Age-related D&D 3.5 ability adjustments are not automatic.")
        form.addRow("Age / life stage",self.age)
        self.appearance = QPlainTextEdit()
        self.appearance.setMaximumHeight(66)
        form.addRow("Appearance",self.appearance)
        self.personality = QPlainTextEdit()
        self.personality.setMaximumHeight(66)
        form.addRow("Personality",self.personality)
        self.background = QPlainTextEdit()
        self.background.setMinimumHeight(120)
        self.background.setPlaceholderText("Write a biography, or use optional local Qwen3 text generation.")
        form.addRow("Biography",self.background)
        self.spells = QPlainTextEdit()
        self.spells.setMaximumHeight(85)
        self.spells.setPlaceholderText("Spells known/prepared, domains, powers, invocations; manual entry.")
        form.addRow("Spells & powers",self.spells)
        self.other = QPlainTextEdit()
        self.other.setMaximumHeight(80)
        form.addRow("Other attributes",self.other)
        self.tabs.addTab(page,"Story")


    def _magic_tab(self):
        page=QWidget()
        form=QFormLayout(page)
        form.setContentsMargins(14,12,14,12)
        self.magic_status=QLabel()
        self.magic_status.setWordWrap(True)
        form.addRow("SRD spellcasting",self.magic_status)
        self.spell_fields={}
        for kind,title in (("known","Spells known"),("prepared","Prepared spells"),
                           ("spellbook","Spellbook")):
            for level in ("0","1"):
                control=QPlainTextEdit()
                control.setAccessibleName(f"{title} level {level}")
                control.setPlaceholderText("One SRD spell per line")
                control.setMaximumHeight(90)
                control.setMinimumHeight(48)
                form.addRow(f"{title} (level {level})",control)
                self.spell_fields[(kind,level)]=control
        self.domains=QLineEdit()
        self.domains.setPlaceholderText("Cleric domains; DM checks actual domain spell")
        form.addRow("Cleric domains",self.domains)
        self.school=QLineEdit()
        self.school.setPlaceholderText("Wizard specialization (DM review)")
        form.addRow("Wizard school",self.school)
        self.prohibited_schools=QLineEdit()
        form.addRow("Prohibited schools",self.prohibited_schools)
        self.tabs.addTab(page,"Spells & Spellbook")

    def _inventory_tab(self):
        page=QWidget()
        outer=QVBoxLayout(page)
        note=QLabel("One item per line; enter 3 x Torch, 2 x Rations, or Spellbook. "
                    "Item weight, price, and equipment slots still require DM review.")
        note.setWordWrap(True)
        outer.addWidget(note)
        self.inventory=QPlainTextEdit()
        self.inventory.setAccessibleName("Quantity-aware inventory")
        self.inventory.setMinimumHeight(170)
        outer.addWidget(self.inventory)
        self.tabs.addTab(page,"Inventory")

    def refresh_spell_profile(self):
        name=self.current_class()
        profile=spell_profile(name,self.scores_provider())
        if name not in CASTERS:
            self.magic_status.setText(
                "No validated level-one SRD spellcasting. "
                "Supplemental and homebrew powers remain in Story notes.")
        else:
            self.magic_status.setText(
                f"{name} • {profile['mode']} • {profile['stat']} • "
                f"Slots per day: cantrips {profile['slots']['0']}, "
                f"1st {profile['slots']['1']} • "
                f"Spell save DCs: {profile['spell_dc_0']}/{profile['spell_dc_1']}. "
                "Catalog spell names and first-level limits are checked.")
        for (kind,level),field in self.spell_fields.items():
            valid=(name=="Wizard" if kind=="spellbook" else
                   profile["mode"]=="spontaneous" if kind=="known" else
                   profile["mode"]=="prepared")
            field.setEnabled(valid)
            if name in SPELL_LISTS:
                field.setToolTip(", ".join(SPELL_LISTS[name][int(level)]))

    def fill_spellbook(self, data):
        for kind in ("known","prepared","spellbook"):
            for level in ("0","1"):
                self.spell_fields[(kind,level)].setPlainText(
                    "\n".join(data.get(kind,{}).get(level,[])))
        self.domains.setText(", ".join(data.get("domains",[])))
        self.school.setText(data.get("specialization",""))
        self.prohibited_schools.setText(
            ", ".join(data.get("prohibited_schools",[])))

    def current_spellbook(self):
        payload={
            "version":1,"casting_class":self.current_class(),
            **{kind:{level:lines(self.spell_fields[(kind,level)].toPlainText())
                      for level in ("0","1")}
               for kind in ("known","prepared","spellbook")},
            "domains":lines(self.domains.text()),
            "specialization":self.school.text().strip(),
            "prohibited_schools":lines(self.prohibited_schools.text()),
        }
        return validate_spellbook(self.current_class(),self.scores_provider(),payload)

    def current_class(self):
        return (self.custom_class_name.text().strip()
                if self.class_picker.currentData() == "__custom__"
                else self.class_picker.currentText())

    def is_custom(self):
        return self.class_picker.currentData() == "__custom__"

    def spec(self):
        t = class_specs(self.current_class() if not self.is_custom() else "",
                        self.hit_die.value(),self.sp_rate.value())
        if self.current_class() == "Expert":
            choices = lines(self.custom_skills.text())
            if choices:
                t = replace(t,class_skills=tuple(choices),
                            suggested_skills=tuple(choices[:4]))
        return t

    def change_class(self,*args):
        custom=self.is_custom()
        self.custom_class_name.setVisible(custom)
        self.hit_die.setEnabled(custom)
        self.sp_rate.setEnabled(custom)
        self.custom_skills.setEnabled(custom or self.current_class()=="Expert")
        if self.current_class()=="Expert" and not self.custom_skills.text().strip():
            self.custom_skills.setText(", ".join(
                class_specs("Expert").class_skills))
        t=self.spec()
        self.hit_die.setValue(t.hit_die)
        self.sp_rate.setValue(t.skill_points)
        self.template_status.setText(
            ("Supplemental/homebrew starter. Special abilities and feat legality "
             "must be reviewed by the DM." if t.supplement or custom else
             "Core 3.5 class starter. Suggested feats, skills, gear can all be edited.")
        )
        self.refresh_skill_types()
        self.apply_preset()
        self.refresh_spell_profile()
        self.update_budget()

    def refresh_skill_types(self, *args):
        t = self.spec()
        allowed = t.class_skill_set | frozenset(lines(self.custom_skills.text()))
        for row, name in enumerate(SKILLS):
            in_class = name in allowed
            self.skill_table.item(row, 1).setText("Class" if in_class else "Cross-class")
            field = self.skill_fields[name]
            field.setMaximum(4.0 if in_class else 2.0)
            field.setSingleStep(1.0 if in_class else .5)
            if in_class and field.value() % 1:
                field.setValue(int(field.value()))
        self.update_budget()

    def apply_preset(self,*args):
        t=self.spec()
        mode=self.build_mode.currentIndex()
        if mode==0:
            # Avoid starting a level-one Fighter at STR 10 with illegal
            # Power Attack/Cleave. Retain the desired preset if legal;
            # otherwise use broadly available SRD first-level feats.
            chosen=list(t.suggested_feats)
            score=self.scores_provider()
            if self.current_class() in TEMPLATES and not t.supplement:
                try:
                    issues=feat_review(chosen,score,
                        class_name=self.current_class(),
                        race=self.race_picker.currentText(),
                        bab=1 if self.current_class() in
                            ("Fighter","Barbarian","Ranger","Paladin") else 0,
                        strict=True)
                    if issues:raise ValueError("; ".join(issues))
                except ValueError:
                    candidates=("Improved Initiative","Toughness","Alertness")
                    chosen=list(candidates[:max(1,len(chosen))])
            self.feats.setPlainText("\n".join(chosen))
            self.equipment.setPlainText("\n".join(t.suggested_equipment))
            self.spells.setPlainText(t.spellcasting_note)
            self.features.setPlainText("\n".join(FIRST_LEVEL_FEATURES.get(
                self.current_class(),())))
            self.fill_spellbook(default_spellbook(
                self.current_class(),self.scores_provider()))
            self.inventory.setPlainText("\n".join(t.suggested_equipment))
            try:
                race=self.race_picker.currentText()
                score=self.scores_provider()
                budget=skill_budget(self.current_class(),score["intelligence"],
                                    race,self.hit_die.value(),self.sp_rate.value())
            except (ValueError,KeyError):
                budget=0
            allocated=allocate_default_skills(t,budget)
        else:
            allocated={}
            if mode==2:
                self.feats.clear()
                self.equipment.clear()
                self.spells.clear()
                self.inventory.clear()
                self.features.clear()
                self.fill_spellbook({})
        for name,field in self.skill_fields.items():
            field.blockSignals(True)
            field.setValue(allocated.get(name,0)/2)
            field.blockSignals(False)
        self.update_budget()

    def update_budget(self,*args):
        try:
            score=self.scores_provider()
            race=self.race_picker.currentText()
            t=self.spec()
            budget=skill_budget(self.current_class(),score["intelligence"],race,
                                self.hit_die.value(),self.sp_rate.value())
            ranks=self.ranks()
            spent=validate_allocations(ranks,t,budget,
                                       frozenset(lines(self.custom_skills.text())))
            message=f"Skill points: {spent}/{budget} spent — {budget-spent} remaining"
        except (ValueError, KeyError) as exc:
            message=f"Skill allocation needs attention: {exc}"
        self.skill_budget_label.setText(message)

    def ranks(self):
        return {name:round(field.value()*2) for name,field in self.skill_fields.items()
                if field.value()>0}

    def finish(self,creature):
        return build_sheet(
            character=creature,class_name=self.current_class(),
            ranks=self.ranks(),feats=lines(self.feats.toPlainText()),
            equipment=lines(self.equipment.toPlainText()),
            alignment=self.alignment.currentText(),deity=self.deity.text(),
            languages=lines(self.languages.text()),appearance=self.appearance.toPlainText(),
            personality=self.personality.toPlainText(),
            background=self.background.toPlainText(),
            custom_hd=self.hit_die.value(),custom_sp=self.sp_rate.value(),
            custom_class_skills=lines(self.custom_skills.text()),
            class_features=lines(self.features.toPlainText()),
            spell_notes=self.spells.toPlainText(),
            spellbook=self.current_spellbook(),
            inventory=inventory_from_text(self.inventory.toPlainText()),
            gender=self.gender.currentText(),age=self.age.text(),
            extra_notes=self.other.toPlainText().strip())

    def load_existing(self,creature):
        data=load_sheet(creature)
        if not data:
            return
        self.build_mode.setCurrentIndex(1)
        self.feats.setPlainText("\n".join(data.get("feats",[])))
        self.equipment.setPlainText("\n".join(data.get("equipment",[])))
        self.features.setPlainText("\n".join(data.get("class_features",[])))
        self.alignment.setCurrentText(data.get("alignment","True Neutral"))
        self.deity.setText(data.get("deity",""))
        self.languages.setText(", ".join(data.get("languages",[])))
        # Old sheets stored age in extra_notes as 'Age: ...'; migrate it
        # on editing without duplicating it or losing the remaining notes.
        legacy_notes = data.get("extra_notes", "")
        legacy_age = ""
        if legacy_notes.startswith("Age:"):
            first, separator, rest = legacy_notes.partition("\n")
            legacy_age = first[4:].strip()
            legacy_notes = rest if separator else ""
        self.gender.setCurrentText(data.get("gender", "Unspecified"))
        self.age.setText(data.get("age") or legacy_age)
        self.appearance.setPlainText(data.get("appearance",""))
        self.personality.setPlainText(data.get("personality",""))
        self.background.setPlainText(data.get("background",""))
        self.spells.setPlainText(data.get("spell_notes",""))
        self.fill_spellbook(data.get("spellbook") or default_spellbook(
            self.current_class(),self.scores_provider()))
        self.inventory.setPlainText(inventory_to_text(
            data.get("inventory") or inventory_from_text(
                "\n".join(data.get("equipment",[])))))
        self.other.setPlainText(legacy_notes)
        self.hit_die.setValue(data.get("custom_hd",8))
        self.sp_rate.setValue(data.get("custom_skill_points",4))
        self.custom_skills.setText(", ".join(data.get("custom_class_skills",[])))
        for name,field in self.skill_fields.items():
            field.setValue(data.get("skills_half_ranks",{}).get(name,0)/2)
        self.update_budget()
