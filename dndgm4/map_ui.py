"""A local map desk with draggable tokens and a separate, filtered player view."""
from __future__ import annotations

from copy import deepcopy
import math
import sqlite3
from uuid import uuid4

from PyQt6.QtCore import QLineF, QPointF, QRectF, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QColor, QPainter, QPainterPath, QPen, QPixmap
from PyQt6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QDoubleSpinBox, QFileDialog, QGraphicsEllipseItem,
    QGraphicsItem, QGraphicsPathItem, QGraphicsRectItem, QGraphicsScene, QGraphicsSimpleTextItem,
    QGraphicsTextItem,
    QGraphicsView, QHBoxLayout, QInputDialog, QLabel, QLineEdit, QListWidget,
    QListWidgetItem, QMessageBox, QPushButton, QScrollArea, QSpinBox,
    QVBoxLayout, QWidget,
)

from .artwork import window_icon
from .maps import (MapRepository, TOKEN_COLORS, map_distance, player_map_image,
                   player_map_state, validate_map_state)
from .theme import COLORS


class MapTokenItem(QGraphicsEllipseItem):
    def __init__(self, canvas, token):
        radius = max(8, min(20, canvas.state["grid_size"] * 0.32))
        super().__init__(-radius, -radius, radius * 2, radius * 2)
        self.canvas, self.token_id = canvas, token["id"]
        self.setBrush(QColor(token["color"]))
        pen = QPen(QColor(COLORS["selected_text"]), 2)
        if not token["visible"]:
            pen.setStyle(Qt.PenStyle.DashLine)
            self.setOpacity(0.6)
        self.setPen(pen)
        self.setZValue(20)
        self.setToolTip(token["label"])
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable, not canvas.public)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsMovable, not canvas.public)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemSendsGeometryChanges, True)
        self.setPos(token["x"], token["y"])
        text = QGraphicsSimpleTextItem(token["label"], self)
        text.setBrush(QColor(COLORS["selected_text"]))
        text.setPos(radius + 4, -text.boundingRect().height() / 2)
        text.setAcceptedMouseButtons(Qt.MouseButton.NoButton)

    def itemChange(self, change, value):
        if change == QGraphicsItem.GraphicsItemChange.ItemPositionChange:
            return QPointF(max(0, min(self.canvas.state["width"] - 0.001, value.x())),
                           max(0, min(self.canvas.state["height"] - 0.001, value.y())))
        return super().itemChange(change, value)

    def mouseReleaseEvent(self, event):
        super().mouseReleaseEvent(event)
        self.canvas.commit_token_position(self)


class MapAnnotationItem(QGraphicsRectItem):
    def __init__(self, canvas, note):
        super().__init__()
        self.canvas, self.annotation_id = canvas, note["id"]
        self.setBrush(QColor(COLORS["panel"]))
        pen = QPen(QColor(note["color"]), 1)
        if not note["visible"]:
            pen.setStyle(Qt.PenStyle.DashLine)
        self.setPen(pen)
        self.setZValue(25)
        self.setToolTip(note["text"])
        text = QGraphicsTextItem(self)
        text.setPlainText(note["text"])
        text.setDefaultTextColor(QColor(COLORS["selected_text"]))
        text.setTextWidth(160)
        text.setAcceptedMouseButtons(Qt.MouseButton.NoButton)
        self.setRect(text.boundingRect())
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable, not canvas.public)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsMovable, not canvas.public)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemSendsGeometryChanges, True)
        self.setPos(note["x"], note["y"])

    def itemChange(self, change, value):
        if change == QGraphicsItem.GraphicsItemChange.ItemPositionChange:
            return QPointF(max(0, min(self.canvas.state["width"] - 0.001, value.x())),
                           max(0, min(self.canvas.state["height"] - 0.001, value.y())))
        return super().itemChange(change, value)

    def mouseReleaseEvent(self, event):
        super().mouseReleaseEvent(event)
        self.canvas.commit_annotation_position(self)


class MapCanvas(QGraphicsView):
    stateChanged = pyqtSignal(dict)
    tokenSelected = pyqtSignal(str)
    annotationSelected = pyqtSignal(str)
    measurementChanged = pyqtSignal(str)

    def __init__(self, *, public=False, parent=None):
        super().__init__(parent)
        self.public = public
        self.state = None
        self.image = None
        self.reveal_mode = False
        self.ruler_mode = False
        self._ruler_start = None
        self._ruler_end = None
        self._ruler_drawing = False
        self._ruler_items = []
        self.token_items = {}
        self.annotation_items = {}
        self.fog_item = None
        self.setScene(QGraphicsScene(self))
        self.setBackgroundBrush(QColor("#000000"))
        self.setRenderHints(QPainter.RenderHint.Antialiasing | QPainter.RenderHint.SmoothPixmapTransform)
        self.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
        self.setAccessibleName("Player map" if public else "Campaign map canvas")
        self.scene().selectionChanged.connect(self._selection_changed)

    def set_map(self, image, state):
        clean = player_map_state(state) if self.public else validate_map_state(state)
        if self.public:
            image = player_map_image(image, clean)
        self.clear_ruler()
        self.image = QPixmap.fromImage(image)
        self.state = clean
        self._rebuild()
        self.fit_map()

    def clear_map(self):
        self.clear_ruler()
        self.state = self.image = None
        self.token_items = {}
        self.annotation_items = {}
        self.fog_item = None
        self.scene().clear()
        self.scene().setSceneRect(QRectF())

    def set_state(self, state, *, rebuild=True):
        self.state = player_map_state(state) if self.public else validate_map_state(state)
        if self.public and self.image is not None:
            self.image = QPixmap.fromImage(player_map_image(self.image.toImage(), self.state))
        if rebuild and self.image is not None:
            self._rebuild()

    def _rebuild(self):
        self.token_items = {}
        self.annotation_items = {}
        self._ruler_items = []
        self.fog_item = None
        self.scene().clear()
        self.scene().setSceneRect(QRectF(0, 0, self.state["width"], self.state["height"]))
        self.scene().addPixmap(self.image)
        if self.state["show_grid"]:
            grid = QPainterPath()
            width, height, edge = self.state["width"], self.state["height"], self.state["grid_size"]
            for x in range(0, width + 1, edge):
                grid.moveTo(x, 0)
                grid.lineTo(x, height)
            for y in range(0, height + 1, edge):
                grid.moveTo(0, y)
                grid.lineTo(width, y)
            item = self.scene().addPath(grid, QPen(QColor(255, 243, 226, 105), 0))
            item.setZValue(5)
        self._draw_fog()
        for token in self.state["tokens"]:
            item = MapTokenItem(self, token)
            self.scene().addItem(item)
            self.token_items[token["id"]] = item
        for note in self.state["annotations"]:
            item = MapAnnotationItem(self, note)
            self.scene().addItem(item)
            self.annotation_items[note["id"]] = item
        self._draw_ruler()

    def _draw_fog(self):
        if self.fog_item is not None:
            self.scene().removeItem(self.fog_item)
            self.fog_item = None
        if not self.state["fog_enabled"]:
            return
        path = QPainterPath()
        path.setFillRule(Qt.FillRule.OddEvenFill)
        path.addRect(QRectF(0, 0, self.state["width"], self.state["height"]))
        edge = self.state["grid_size"]
        for x, y in self.state["revealed"]:
            path.addRect(QRectF(x * edge, y * edge,
                               min(edge, self.state["width"] - x * edge),
                               min(edge, self.state["height"] - y * edge)))
        item = QGraphicsPathItem(path)
        item.setPen(QPen(Qt.PenStyle.NoPen))
        item.setBrush(QColor(0, 0, 0, 255 if self.public else 155))
        item.setAcceptedMouseButtons(Qt.MouseButton.NoButton)
        item.setZValue(10)
        self.scene().addItem(item)
        self.fog_item = item

    def fit_map(self):
        if self.state:
            self.fitInView(self.sceneRect(), Qt.AspectRatioMode.KeepAspectRatio)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.fit_map()

    def wheelEvent(self, event):
        factor = 1.15 if event.angleDelta().y() > 0 else 1 / 1.15
        if 0.02 <= self.transform().m11() * factor <= 12:
            self.scale(factor, factor)
        event.accept()

    def _selection_changed(self):
        selected = [item.token_id for item in self.scene().selectedItems()
                    if isinstance(item, MapTokenItem)]
        self.tokenSelected.emit(selected[0] if selected else "")
        selected_notes = [item.annotation_id for item in self.scene().selectedItems()
                          if isinstance(item, MapAnnotationItem)]
        self.annotationSelected.emit(selected_notes[0] if selected_notes else "")

    def select_token(self, token_id):
        self.scene().clearSelection()
        if token_id in self.token_items:
            self.token_items[token_id].setSelected(True)

    def select_annotation(self, annotation_id):
        self.scene().clearSelection()
        if annotation_id in self.annotation_items:
            self.annotation_items[annotation_id].setSelected(True)

    def commit_annotation_position(self, item):
        if self.public or self.state is None:
            return
        for note in self.state["annotations"]:
            if note["id"] == item.annotation_id:
                point = item.pos()
                if (note["x"], note["y"]) != (point.x(), point.y()):
                    note["x"], note["y"] = point.x(), point.y()
                    self.stateChanged.emit(deepcopy(self.state))
                return

    def clear_ruler(self):
        for item in self._ruler_items:
            self.scene().removeItem(item)
        self._ruler_items = []
        self._ruler_start = self._ruler_end = None
        self._ruler_drawing = False
        self.measurementChanged.emit("")

    def _draw_ruler(self):
        for item in self._ruler_items:
            self.scene().removeItem(item)
        self._ruler_items = []
        if self.public or self.state is None or self._ruler_start is None or self._ruler_end is None:
            return
        start, end = self._ruler_start, self._ruler_end
        distance = map_distance(self.state, (start.x(), start.y()), (end.x(), end.y()))
        label = f"{distance:.2f}".rstrip("0").rstrip(".") + " " + self.state["unit_label"]
        line = self.scene().addLine(QLineF(start, end), QPen(QColor(COLORS["focus"]), 0))
        line.setZValue(40)
        line.setAcceptedMouseButtons(Qt.MouseButton.NoButton)
        text = self.scene().addSimpleText(label)
        text.setBrush(QColor(COLORS["focus"]))
        text.setPos(end + QPointF(5, 5))
        text.setZValue(40)
        text.setAcceptedMouseButtons(Qt.MouseButton.NoButton)
        self._ruler_items = [line, text]
        self.measurementChanged.emit("Straight-line: " + label)

    def _ruler_point(self, position):
        point = self.mapToScene(position)
        return QPointF(max(0, min(self.state["width"], point.x())),
                       max(0, min(self.state["height"], point.y())))

    def commit_token_position(self, item):
        if self.public or self.state is None:
            return
        point = item.pos()
        if self.state["snap_to_grid"]:
            edge = self.state["grid_size"]
            point = QPointF((math.floor(point.x() / edge) + 0.5) * edge,
                            (math.floor(point.y() / edge) + 0.5) * edge)
        point = QPointF(min(self.state["width"] - 0.001, max(0, point.x())),
                        min(self.state["height"] - 0.001, max(0, point.y())))
        item.setPos(point)
        for token in self.state["tokens"]:
            if token["id"] == item.token_id:
                if (token["x"], token["y"]) == (point.x(), point.y()):
                    return
                token["x"], token["y"] = point.x(), point.y()
                self.stateChanged.emit(deepcopy(self.state))
                return

    def reveal_cell(self, x, y):
        if self.public or not self.state or not self.state["fog_enabled"]:
            return
        if not (0 <= x < self.state["width"] and 0 <= y < self.state["height"]):
            return
        edge = self.state["grid_size"]
        cell = [int(x // edge), int(y // edge)]
        if cell in self.state["revealed"]:
            self.state["revealed"].remove(cell)
        else:
            self.state["revealed"].append(cell)
        self._draw_fog()
        self.stateChanged.emit(deepcopy(self.state))

    def mousePressEvent(self, event):
        if (not self.public and self.ruler_mode and self.state is not None
                and event.button() == Qt.MouseButton.LeftButton):
            self._ruler_start = self._ruler_end = self._ruler_point(event.pos())
            self._ruler_drawing = True
            self._draw_ruler()
            event.accept()
            return
        if (not self.public and self.reveal_mode and self.state is not None
                and event.button() == Qt.MouseButton.LeftButton):
            point = self.mapToScene(event.pos())
            self.reveal_cell(point.x(), point.y())
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._ruler_drawing and self.ruler_mode and not self.public:
            self._ruler_end = self._ruler_point(event.pos())
            self._draw_ruler()
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if self._ruler_drawing and self.ruler_mode and not self.public:
            self._ruler_end = self._ruler_point(event.pos())
            self._ruler_drawing = False
            self._draw_ruler()
            event.accept()
            return
        super().mouseReleaseEvent(event)


class PlayerMapWindow(QDialog):
    """Only public map pixels and explicitly visible, revealed token labels."""
    def __init__(self, image, state, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_QuitOnClose, False)
        self.setWindowTitle("Player Map | D&D Game Manager 4")
        self.resize(1000, 720)
        layout = QVBoxLayout(self)
        self.canvas = MapCanvas(public=True)
        layout.addWidget(self.canvas)
        self.update_map(image, state)

    def update_map(self, image, state):
        public = player_map_state(state)
        self.canvas.set_map(player_map_image(image, public), public)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if hasattr(self, "canvas"):
            self.canvas.fit_map()


class MapDeskDialog(QDialog):
    def __init__(self, library, campaign_id, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_QuitOnClose, False)
        self.setWindowTitle("The Cartographer's Desk | D&D Game Manager 4")
        self.setWindowIcon(window_icon())
        self.resize(1200, 800)
        self.setMinimumSize(830, 540)
        self.repository = MapRepository(library)
        self.campaign_id = campaign_id
        self.record = None
        self.player_window = None
        self._loading = False
        self._selected_token = ""
        self._selected_annotation = ""
        self._map_buttons = []
        root = QVBoxLayout(self)
        heading = QLabel("THE CARTOGRAPHER'S DESK")
        heading.setObjectName("pageTitle")
        root.addWidget(heading)
        help_text = QLabel("Import a campaign map, drag tokens, and reveal explored grid cells. Changes save automatically.")
        help_text.setWordWrap(True)
        help_text.setObjectName("muted")
        root.addWidget(help_text)
        body = QHBoxLayout()
        root.addLayout(body, 1)
        tools = QWidget()
        sidebar = QVBoxLayout(tools)
        sidebar.setContentsMargins(0, 0, 8, 0)
        self.import_button = self._button(sidebar, "Import Local Map…", self.import_map, primary=True, requires_map=False)
        self.map_list = QListWidget()
        self.map_list.setAccessibleName("Campaign maps")
        self.map_list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.map_list.setMinimumHeight(100)
        self.map_list.setMaximumHeight(155)
        self.map_list.currentItemChanged.connect(self._map_selected)
        sidebar.addWidget(self.map_list)
        self.title = QLineEdit()
        self.title.setAccessibleName("Map title for the DM")
        self.title.setMaxLength(200)
        self.title.editingFinished.connect(self._rename)
        sidebar.addWidget(self.title)
        self._button(sidebar, "Reload Map", self._reload_current)
        sidebar.addWidget(QLabel("Grid size in image pixels"))
        self.grid_size = QSpinBox()
        self.grid_size.setRange(16, 512)
        self.grid_size.setAccessibleName("Map grid size in pixels")
        self.grid_size.valueChanged.connect(lambda value: self._change("grid_size", value))
        sidebar.addWidget(self.grid_size)
        sidebar.addWidget(QLabel("Distance per grid cell"))
        self.units_per_cell = QDoubleSpinBox()
        self.units_per_cell.setRange(0.001, 100000)
        self.units_per_cell.setDecimals(3)
        self.units_per_cell.setKeyboardTracking(False)
        self.units_per_cell.setAccessibleName("Distance units per map grid cell")
        self.units_per_cell.valueChanged.connect(lambda value: self._change("units_per_cell", value))
        sidebar.addWidget(self.units_per_cell)
        self.unit_label = QLineEdit()
        self.unit_label.setMaxLength(24)
        self.unit_label.setAccessibleName("Map distance unit label")
        self.unit_label.editingFinished.connect(lambda: self._change("unit_label", self.unit_label.text()))
        sidebar.addWidget(self.unit_label)
        self.ruler_button = self._button(sidebar, "Straight-line Ruler", self._set_ruler_mode)
        self.ruler_button.setCheckable(True)
        self._button(sidebar, "Clear Ruler", lambda: self.canvas.clear_ruler())
        self.grid_visible = self._checkbox(sidebar, "Show grid", "show_grid")
        self.snap = self._checkbox(sidebar, "Snap tokens to grid", "snap_to_grid")
        self.fog = self._checkbox(sidebar, "Fog of war enabled", "fog_enabled")
        self.fog.setToolTip("Turn off to reveal the entire map in the player view.")
        self.reveal_button = self._button(sidebar, "Reveal / Conceal Cells", self._set_reveal_mode)
        self.reveal_button.setCheckable(True)
        self._button(sidebar, "Reveal Entire Map", self.reveal_all)
        self._button(sidebar, "Hide Entire Map", self.hide_all)
        self.tokens = QListWidget()
        self.tokens.setAccessibleName("DM map tokens")
        self.tokens.setMinimumHeight(90)
        self.tokens.setMaximumHeight(140)
        self.tokens.currentItemChanged.connect(self._token_selected)
        sidebar.addWidget(self.tokens)
        self.token_color = QComboBox()
        self.token_color.setAccessibleName("New token color")
        for color, name in zip(TOKEN_COLORS, ("Crimson", "Azure", "Gold", "Forest", "Violet", "Copper")):
            self.token_color.addItem(name, color)
        sidebar.addWidget(self.token_color)
        self._button(sidebar, "Add Token…", self.add_token)
        self._button(sidebar, "Add Encounter Token…", self.add_encounter_token)
        self.token_visible = QCheckBox("Selected token visible to players")
        self.token_visible.setToolTip("The token also needs to stand in a revealed cell while fog is enabled.")
        self.token_visible.toggled.connect(self._set_token_visible)
        sidebar.addWidget(self.token_visible)
        self.remove_token_button = self._button(sidebar, "Remove Selected Token", self.remove_token)
        self.unlink_token_button = self._button(sidebar, "Unlink Selected Token", self.unlink_token)
        self.unlink_all_button = self._button(sidebar, "Unlink All Encounter Tokens", self.unlink_all_tokens)
        sidebar.addWidget(QLabel("Map annotations"))
        self.annotations = QListWidget()
        self.annotations.setAccessibleName("DM map annotations")
        self.annotations.setMinimumHeight(90)
        self.annotations.setMaximumHeight(140)
        self.annotations.currentItemChanged.connect(self._annotation_selected)
        sidebar.addWidget(self.annotations)
        self._button(sidebar, "Add Note…", self.add_annotation)
        self.annotation_visible = QCheckBox("Selected note visible to players")
        self.annotation_visible.setToolTip("Only explicitly public notes in revealed cells appear in Player View.")
        self.annotation_visible.toggled.connect(self._set_annotation_visible)
        sidebar.addWidget(self.annotation_visible)
        self.edit_annotation_button = self._button(sidebar, "Edit Selected Note…", self.edit_annotation)
        self.remove_annotation_button = self._button(sidebar, "Remove Selected Note", self.remove_annotation)
        self._button(sidebar, "Fit Map", lambda: self.canvas.fit_map())
        self.preview_button = self._button(sidebar, "Open Player View", self.open_player_view, primary=True)
        sidebar.addStretch()
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setMinimumWidth(235)
        scroll.setMaximumWidth(310)
        scroll.setWidget(tools)
        body.addWidget(scroll)
        self.canvas = MapCanvas()
        self.canvas.stateChanged.connect(lambda state: self._save_state(state, rebuild=False))
        self.canvas.tokenSelected.connect(self._canvas_token_selected)
        self.canvas.annotationSelected.connect(self._canvas_annotation_selected)
        body.addWidget(self.canvas, 1)
        self.ruler_result = QLabel("Drag the straight-line ruler to measure calibrated distance.")
        self.ruler_result.setObjectName("muted")
        self.ruler_result.setTextFormat(Qt.TextFormat.PlainText)
        self.ruler_result.setWordWrap(True)
        root.addWidget(self.ruler_result)
        self.canvas.measurementChanged.connect(lambda text: self.ruler_result.setText(
            text or "Drag the straight-line ruler to measure calibrated distance."))
        self.status = QLabel("Import a map to begin. New maps start fully hidden from the player view.")
        self.status.setWordWrap(True)
        self.status.setTextFormat(Qt.TextFormat.PlainText)
        self.status.setObjectName("muted")
        root.addWidget(self.status)
        self._refresh_maps()

    def _button(self, layout, text, callback, *, primary=False, requires_map=True):
        button = QPushButton(text)
        if primary:
            button.setObjectName("primaryButton")
        button.clicked.connect(callback)
        layout.addWidget(button)
        if requires_map:
            self._map_buttons.append(button)
        return button

    def _checkbox(self, layout, text, key):
        box = QCheckBox(text)
        box.toggled.connect(lambda value: self._change(key, value))
        layout.addWidget(box)
        return box

    def _error(self, error):
        QMessageBox.warning(self, "Map could not be updated", str(error))

    def _refresh_maps(self, preferred=""):
        records = self.repository.list(self.campaign_id)
        self.map_list.blockSignals(True)
        self.map_list.clear()
        selected = 0
        for index, record in enumerate(records):
            item = QListWidgetItem(record.title)
            item.setToolTip(record.title)
            item.setData(Qt.ItemDataRole.UserRole, record.id)
            self.map_list.addItem(item)
            if record.id == preferred:
                selected = index
        self.map_list.setCurrentRow(selected if records else -1)
        self.map_list.blockSignals(False)
        self._map_selected(self.map_list.currentItem(), None)

    def _map_selected(self, item, previous):
        if self.player_window is not None:
            self.player_window.close()
            self.player_window = None
        self.record = None
        self._selected_token = self._selected_annotation = ""
        self.canvas.clear_map()
        if item is not None:
            try:
                record = self.repository.get(item.data(Qt.ItemDataRole.UserRole), campaign_id=self.campaign_id)
                image = self.repository.load_image(record)
                self.record = record
                self.canvas.set_map(image, record.state)
                self.status.setText("Saved locally. Wheel to zoom; drag empty map space to pan. Fog is translucent in the DM view.")
            except (ValueError, OSError, sqlite3.Error) as exc:
                self.canvas.clear_map()
                self._error(exc)
        self._refresh_controls()

    def _reload_current(self):
        self._map_selected(self.map_list.currentItem(), None)

    def _refresh_controls(self):
        self._loading = True
        state = self.record.state if self.record else None
        self.title.setText(self.record.title if self.record else "")
        self.title.setCursorPosition(0)
        self.title.setEnabled(state is not None)
        for button in self._map_buttons:
            button.setEnabled(state is not None)
        for widget in (self.grid_size, self.units_per_cell, self.unit_label,
                       self.grid_visible, self.snap, self.fog,
                       self.reveal_button, self.token_color, self.preview_button):
            widget.setEnabled(state is not None)
        self.grid_size.setValue(state["grid_size"] if state else 50)
        self.units_per_cell.setValue(state["units_per_cell"] if state else 5)
        self.unit_label.setText(state["unit_label"] if state else "ft")
        self.grid_visible.setChecked(state["show_grid"] if state else True)
        self.snap.setChecked(state["snap_to_grid"] if state else True)
        self.fog.setChecked(state["fog_enabled"] if state else True)
        self.unlink_all_button.setEnabled(state is not None and any("link" in token for token in state["tokens"]))
        self.tokens.clear()
        if state:
            for token in state["tokens"]:
                item = QListWidgetItem(token["label"] + (" (encounter)" if "link" in token else "")
                                       + ("" if token["visible"] else " (DM only)"))
                item.setData(Qt.ItemDataRole.UserRole, token["id"])
                self.tokens.addItem(item)
                if token["id"] == self._selected_token:
                    self.tokens.setCurrentItem(item)
        self.annotations.clear()
        if state:
            for note in state["annotations"]:
                item = QListWidgetItem(note["text"].replace("\n", " / ")[:60]
                                       + ("" if note["visible"] else " (DM only)"))
                item.setData(Qt.ItemDataRole.UserRole, note["id"])
                item.setToolTip(note["text"])
                self.annotations.addItem(item)
                if note["id"] == self._selected_annotation:
                    self.annotations.setCurrentItem(item)
        self._loading = False
        self._sync_token_controls()
        self._sync_annotation_controls()

    def _sync_token_controls(self):
        token = next((token for token in self.record.state["tokens"] if token["id"] == self._selected_token), None) if self.record else None
        self.token_visible.blockSignals(True)
        self.token_visible.setChecked(token["visible"] if token else False)
        self.token_visible.setEnabled(token is not None)
        self.token_visible.blockSignals(False)
        self.remove_token_button.setEnabled(token is not None)
        self.unlink_token_button.setEnabled(token is not None and "link" in token)

    def _sync_annotation_controls(self):
        note = next((note for note in self.record.state["annotations"] if note["id"] == self._selected_annotation), None) if self.record else None
        self.annotation_visible.blockSignals(True)
        self.annotation_visible.setChecked(note["visible"] if note else False)
        self.annotation_visible.setEnabled(note is not None)
        self.annotation_visible.blockSignals(False)
        self.edit_annotation_button.setEnabled(note is not None)
        self.remove_annotation_button.setEnabled(note is not None)

    def _save_state(self, state, *, rebuild=True):
        if self._loading or self.record is None:
            return False
        try:
            self.record = self.repository.save_state(self.record.id, state, campaign_id=self.campaign_id,
                                                     expected_state=self.record.state)
            self._loading = True
            self.canvas.set_state(self.record.state, rebuild=rebuild)
            if rebuild and self._selected_token:
                self.canvas.select_token(self._selected_token)
            elif rebuild and self._selected_annotation:
                self.canvas.select_annotation(self._selected_annotation)
            self._loading = False
            self._refresh_controls()
            if self.player_window is not None:
                self.player_window.update_map(self.canvas.image.toImage(), self.record.state)
            self.status.setText("Map saved. Player View shows revealed areas and explicitly public tokens and notes.")
            return True
        except (ValueError, OSError, sqlite3.Error) as exc:
            self._loading = False
            # Let a token's mouse-release event finish before replacing items.
            QTimer.singleShot(0, self._restore_saved_canvas)
            self._refresh_controls()
            self.status.setText("Map not saved: " + str(exc))
            self._error(exc)
            return False

    def _restore_saved_canvas(self):
        if self.record is not None:
            self._loading = True
            self.canvas.set_state(self.record.state)
            self._loading = False

    def _change(self, key, value):
        if self._loading or self.record is None:
            return False
        if self.record.state.get(key) == value:
            return True
        state = deepcopy(self.record.state)
        state[key] = value
        saved = self._save_state(state)
        if saved and key == "grid_size":
            self.status.setText("Grid size saved. Individually revealed cells were cleared to protect unexplored areas.")
        return saved

    def _rename(self):
        if self._loading or self.record is None or self.title.text() == self.record.title:
            return
        try:
            self.record = self.repository.rename(self.record.id, self.title.text(), campaign_id=self.campaign_id)
            self.map_list.currentItem().setText(self.record.title)
        except (ValueError, OSError, sqlite3.Error) as exc:
            self.title.setText(self.record.title)
            self._error(exc)

    def import_map(self):
        path, _ = QFileDialog.getOpenFileName(self, "Import a local campaign map", "",
                                             "Map images (*.png *.jpg *.jpeg *.webp *.bmp)")
        if not path:
            return
        try:
            record = self.repository.import_image(self.campaign_id, path)
            self._refresh_maps(record.id)
        except (ValueError, OSError, sqlite3.Error) as exc:
            self._error(exc)

    def _set_reveal_mode(self):
        self.ruler_button.setChecked(False)
        self.canvas.ruler_mode = False
        self.canvas._ruler_drawing = False
        self.canvas.reveal_mode = self.reveal_button.isChecked()
        self.canvas.setDragMode(QGraphicsView.DragMode.NoDrag if self.canvas.reveal_mode
                                else QGraphicsView.DragMode.ScrollHandDrag)
        self.status.setText("Click a grid cell to reveal or conceal it." if self.canvas.reveal_mode
                            else "Drag tokens to move them; drag empty map space to pan.")

    def _set_ruler_mode(self):
        self.reveal_button.setChecked(False)
        self.canvas.reveal_mode = False
        self.canvas.ruler_mode = self.ruler_button.isChecked()
        self.canvas._ruler_drawing = False
        self.canvas.setDragMode(QGraphicsView.DragMode.NoDrag if self.canvas.ruler_mode
                                else QGraphicsView.DragMode.ScrollHandDrag)
        self.status.setText("Drag from one point to another to measure straight-line distance in the configured units."
                            if self.canvas.ruler_mode else "Drag tokens to move them; drag empty map space to pan.")

    def reveal_all(self):
        self._change("fog_enabled", False)

    def hide_all(self):
        if self.record is not None:
            state = deepcopy(self.record.state)
            state.update(fog_enabled=True, revealed=[])
            self._save_state(state)

    def add_token(self):
        if self.record is None:
            return
        label, accepted = QInputDialog.getText(self, "Add map token", "Token label (starts visible only to the DM)")
        if not accepted or not label.strip():
            return
        state = deepcopy(self.record.state)
        state["tokens"].append({"id": str(uuid4()), "label": label, "x": state["width"] / 2,
                                "y": state["height"] / 2, "color": self.token_color.currentData(), "visible": False})
        self._selected_token = state["tokens"][-1]["id"]
        self._selected_annotation = ""
        self._save_state(state)

    def add_encounter_token(self):
        if self.record is None:
            return
        from .campaigns import CampaignRepository
        try:
            actors = self.repository.encounter_actors(self.campaign_id)
            linked = {(token["link"]["encounter_id"], token["link"]["fighter_uid"])
                      for token in self.record.state["tokens"] if "link" in token}
            actors = [actor for actor in actors if (actor.encounter_id, actor.fighter_uid) not in linked]
            if not actors:
                QMessageBox.information(self, "No unplaced encounter actors",
                                        "Save fighters in a campaign encounter first. Actors already linked on this map are omitted.")
                return
            labels = [f"{index + 1}. {actor.session_title} / {actor.encounter_title} — {actor.name or 'Unnamed combatant'}"
                      for index, actor in enumerate(actors)]
            workspace = CampaignRepository(self.repository.library.path).get_workspace()
            current = next((index for index, actor in enumerate(actors)
                            if workspace.campaign_id == self.campaign_id
                            and actor.encounter_id == workspace.encounter_id), 0)
            choice, accepted = QInputDialog.getItem(self, "Add encounter token",
                                                     "Saved actor from this campaign", labels, current, False)
            if not accepted:
                return
            actor = actors[labels.index(choice)]
            state = deepcopy(self.record.state)
            token = dict(id=str(uuid4()), label=(actor.name.strip() or "Unnamed combatant")[:80],
                         x=state["width"] / 2, y=state["height"] / 2,
                         color=self.token_color.currentData(), visible=False,
                         link=dict(encounter_id=actor.encounter_id, fighter_uid=actor.fighter_uid))
            state["tokens"].append(token)
            self._selected_token, self._selected_annotation = token["id"], ""
            self._save_state(state)
        except (ValueError, OSError, sqlite3.Error) as exc:
            self._error(exc)

    def unlink_token(self):
        if self.record is None or not self._selected_token:
            return
        state = deepcopy(self.record.state)
        for token in state["tokens"]:
            if token["id"] == self._selected_token:
                token.pop("link", None)
        self._save_state(state)

    def unlink_all_tokens(self):
        if self.record is None:
            return
        state = deepcopy(self.record.state)
        for token in state["tokens"]:
            token.pop("link", None)
        self._save_state(state)

    def add_annotation(self):
        if self.record is None:
            return
        text, accepted = QInputDialog.getMultiLineText(self, "Add map note", "Note (starts visible only to the DM)")
        if not accepted or not text.strip():
            return
        state = deepcopy(self.record.state)
        note = dict(id=str(uuid4()), text=text, x=state["width"] / 2, y=state["height"] / 2,
                    color=self.token_color.currentData(), visible=False)
        state["annotations"].append(note)
        self._selected_annotation, self._selected_token = note["id"], ""
        self._save_state(state)

    def edit_annotation(self):
        if self.record is None:
            return
        note = next((note for note in self.record.state["annotations"]
                     if note["id"] == self._selected_annotation), None)
        if note is None:
            return
        text, accepted = QInputDialog.getMultiLineText(self, "Edit map note", "Note", note["text"])
        if not accepted:
            return
        state = deepcopy(self.record.state)
        for annotation in state["annotations"]:
            if annotation["id"] == self._selected_annotation:
                annotation["text"] = text
        self._save_state(state)

    def remove_annotation(self):
        if self.record is None or not self._selected_annotation:
            return
        state = deepcopy(self.record.state)
        state["annotations"] = [note for note in state["annotations"] if note["id"] != self._selected_annotation]
        self._selected_annotation = ""
        self._save_state(state)

    def _annotation_selected(self, item, previous):
        if self._loading:
            return
        self._selected_annotation = item.data(Qt.ItemDataRole.UserRole) if item else ""
        self.canvas.select_annotation(self._selected_annotation)
        self._sync_annotation_controls()

    def _canvas_annotation_selected(self, annotation_id):
        if self._loading:
            return
        self._selected_annotation = annotation_id
        self.annotations.blockSignals(True)
        for index in range(self.annotations.count()):
            item = self.annotations.item(index)
            if item.data(Qt.ItemDataRole.UserRole) == annotation_id:
                self.annotations.setCurrentItem(item)
                break
        else:
            self.annotations.setCurrentRow(-1)
        self.annotations.blockSignals(False)
        self._sync_annotation_controls()

    def _set_annotation_visible(self, value):
        if self._loading or self.record is None or not self._selected_annotation:
            return
        state = deepcopy(self.record.state)
        for note in state["annotations"]:
            if note["id"] == self._selected_annotation:
                note["visible"] = value
        self._save_state(state)

    def _token_selected(self, item, previous):
        if self._loading:
            return
        self._selected_token = item.data(Qt.ItemDataRole.UserRole) if item else ""
        self.canvas.select_token(self._selected_token)
        self._sync_token_controls()

    def _canvas_token_selected(self, token_id):
        if self._loading:
            return
        self._selected_token = token_id
        self.tokens.blockSignals(True)
        for index in range(self.tokens.count()):
            item = self.tokens.item(index)
            if item.data(Qt.ItemDataRole.UserRole) == token_id:
                self.tokens.setCurrentItem(item)
                break
        else:
            self.tokens.setCurrentRow(-1)
        self.tokens.blockSignals(False)
        self._sync_token_controls()

    def _set_token_visible(self, value):
        if self.record is None or self._loading:
            return
        state = deepcopy(self.record.state)
        for token in state["tokens"]:
            if token["id"] == self._selected_token:
                token["visible"] = value
        self._save_state(state)

    def remove_token(self):
        if self.record is None or not self._selected_token:
            return
        state = deepcopy(self.record.state)
        state["tokens"] = [token for token in state["tokens"] if token["id"] != self._selected_token]
        self._selected_token = ""
        self._save_state(state)

    def open_player_view(self):
        if self.record is None:
            return
        if self.player_window is None:
            try:
                self.player_window = PlayerMapWindow(self.repository.load_image(self.record), self.record.state, self)
            except (ValueError, OSError, sqlite3.Error) as exc:
                self._error(exc)
                return
        self.player_window.show()
        self.player_window.canvas.fit_map()
        self.player_window.raise_()

    def closeEvent(self, event):
        if self.player_window is not None:
            self.player_window.close()
        super().closeEvent(event)

    def done(self, result):
        if self.player_window is not None:
            self.player_window.close()
        super().done(result)
