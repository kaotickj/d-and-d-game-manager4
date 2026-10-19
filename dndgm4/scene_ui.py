"""The current scenario/scene editor for selected records and local Scribe."""
from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QDialog, QDialogButtonBox, QFormLayout, QLabel, QListWidget,
    QListWidgetItem, QPlainTextEdit, QScrollArea, QVBoxLayout, QWidget,
)

from .scene_context import SCENE_FIELDS, validate_scene


class SceneDialog(QDialog):
    """Edit a saved scene and precisely which library records are present."""

    def __init__(self, scene: dict, records: list, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_QuitOnClose, False)
        self.setWindowTitle("Current Scene | D&D Game Manager 4")
        self.resize(750, 660)
        self.result_scene = None
        self.scene = validate_scene(scene)
        outer = QVBoxLayout(self)
        title = QLabel("SCENE ROSTER / THE SCRIBE'S CONTEXT")
        title.setObjectName("sectionTitle")
        outer.addWidget(title)
        hint = QLabel("Tick the PCs, NPCs and monsters actually present. "
                      "Only these records will be sent to The Scribe when "
                      "you load the saved scene. Scene details stay local.")
        hint.setWordWrap(True)
        outer.addWidget(hint)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        form_body = QWidget()
        form = QFormLayout(form_body)
        self.fields = {}
        titles = {
            "title": "Scene / encounter title",
            "location": "Current location",
            "time_conditions": "Time, weather and conditions",
            "scenery": "Scenery, terrain, hazards",
            "places": "Towns, inns, taverns, landmarks",
            "campaign_notes": "Campaign continuity and current quest details",
        }
        for field in SCENE_FIELDS:
            widget = QPlainTextEdit(self.scene[field])
            widget.setAccessibleName(titles[field])
            widget.setMaximumHeight(100)
            widget.setMinimumHeight(55)
            form.addRow(titles[field], widget)
            self.fields[field] = widget
        self.roster = QListWidget()
        self.roster.setAccessibleName("Scene members, all character and creature types")
        self.roster.setMinimumHeight(180)
        for record in records:
            if record.archived:
                continue
            item = QListWidgetItem(
                f"{record.name}  |  {record.kind.upper()}  |  "
                f"{record.race_type or 'Unspecified'}")
            item.setData(Qt.ItemDataRole.UserRole, record.id)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(
                Qt.CheckState.Checked if record.id in self.scene["record_ids"]
                else Qt.CheckState.Unchecked
            )
            self.roster.addItem(item)
        form.addRow("Present characters / creatures", self.roster)
        scroll.setWidget(form_body)
        outer.addWidget(scroll, 1)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save |
            QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.save_scene)
        buttons.rejected.connect(self.reject)
        outer.addWidget(buttons)

    def save_scene(self):
        scene = dict(self.scene)
        for field, widget in self.fields.items():
            scene[field] = widget.toPlainText()
        scene["record_ids"] = [
            self.roster.item(i).data(Qt.ItemDataRole.UserRole)
            for i in range(self.roster.count())
            if self.roster.item(i).checkState() == Qt.CheckState.Checked
        ]
        self.result_scene = validate_scene(scene)
        self.accept()
