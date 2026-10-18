"""First-level skill, feat, equipment and character-detail editor.

All automatic builds are editable. Supplemental classes are transparent
starting templates: class features and legal feat/spell prerequisites require
human review. The same control surface handles custom class entry.
"""
from __future__ import annotations

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
        self.age = QLineEdit()
        self.age.setPlaceholderText("Years, or character-specific description")
        form.addRow("Age",self.age)
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
        self.tabs.addTab(page,"Story & Magic")

    def current_class(self):
        return (self.custom_class_name.text().strip()
                if self.class_picker.currentData() == "__custom__"
                else self.class_picker.currentText())

    def is_custom(self):
        return self.class_picker.currentData() == "__custom__"

    def spec(self):
        return class_specs(self.current_class() if not self.is_custom() else "",
                           self.hit_die.value(),self.sp_rate.value())

    def change_class(self,*args):
        custom=self.is_custom()
        self.custom_class_name.setVisible(custom)
        self.hit_die.setEnabled(custom)
        self.sp_rate.setEnabled(custom)
        self.custom_skills.setEnabled(custom)
        t=self.spec()
        self.hit_die.setValue(t.hit_die)
        self.sp_rate.setValue(t.skill_points)
        self.template_status.setText(
            ("Supplemental/homebrew starter. Special abilities and feat legality "
             "must be reviewed by the DM." if t.supplement or custom else
             "Core 3.5 class starter. Suggested feats, skills, gear can all be edited.")
        )
        allowed=t.class_skill_set|frozenset(lines(self.custom_skills.text()))
        for row,name in enumerate(SKILLS):
            in_class=name in allowed
            self.skill_table.item(row,1).setText("Class" if in_class else "Cross-class")
            field=self.skill_fields[name]
            field.setMaximum(4.0 if in_class else 2.0)
            field.setSingleStep(1.0 if in_class else .5)
            # Avoid invalid half-ranks for class skills after class change.
            if in_class and field.value() % 1:
                field.setValue(int(field.value()))
        self.apply_preset()
        self.update_budget()

    def apply_preset(self,*args):
        t=self.spec()
        mode=self.build_mode.currentIndex()
        if mode==0:
            self.feats.setPlainText("\n".join(t.suggested_feats))
            self.equipment.setPlainText("\n".join(t.suggested_equipment))
            self.spells.setPlainText(t.spellcasting_note)
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
            extra_notes=("Age: "+self.age.text().strip()+"\n"+self.other.toPlainText()).strip())

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
        self.appearance.setPlainText(data.get("appearance",""))
        self.personality.setPlainText(data.get("personality",""))
        self.background.setPlainText(data.get("background",""))
        self.spells.setPlainText(data.get("spell_notes",""))
        self.other.setPlainText(data.get("extra_notes",""))
        self.hit_die.setValue(data.get("custom_hd",8))
        self.sp_rate.setValue(data.get("custom_skill_points",4))
        self.custom_skills.setText(", ".join(data.get("custom_class_skills",[])))
        for name,field in self.skill_fields.items():
            field.setValue(data.get("skills_half_ranks",{}).get(name,0)/2)
        self.update_budget()
