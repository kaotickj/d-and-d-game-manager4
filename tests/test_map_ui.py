"""Map desk persistence and player-window secrecy/lifecycle regressions."""
from copy import deepcopy
from importlib.util import find_spec
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch


@unittest.skipUnless(find_spec("PyQt6") is not None, "PyQt6 unavailable")
class MapDeskTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        from PyQt6.QtWidgets import QApplication
        from dndgm4.theme import apply_theme
        cls.app = QApplication.instance() or QApplication([])
        apply_theme(cls.app)

    def setUp(self):
        from PyQt6.QtGui import QColor, QImage
        from dndgm4.campaigns import CampaignRepository
        from dndgm4.maps import MapRepository
        from dndgm4.storage import CreatureRepository
        self.folder = TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.root = Path(self.folder.name)
        self.library = CreatureRepository(self.root / "library.sqlite3")
        self.campaign = CampaignRepository(self.library.path).create_campaign("Secret DM campaign title")
        source = self.root / "private-location-name.png"
        self.image = QImage(200, 160, QImage.Format.Format_RGB32)
        self.image.fill(QColor("#448855"))
        self.assertTrue(self.image.save(str(source)))
        self.repository = MapRepository(self.library)
        self.record = self.repository.import_image(self.campaign.id, source, "Secret DM map title")

    def test_grid_tokens_movement_and_fog_save_automatically(self):
        from PyQt6.QtCore import QPointF
        from dndgm4.map_ui import MapDeskDialog
        dialog = MapDeskDialog(self.library, self.campaign.id)
        self.addCleanup(dialog.close)
        dialog.show()
        self.app.processEvents()
        with patch.object(dialog, "_error", side_effect=AssertionError("Unexpected map error")):
            dialog.grid_size.setValue(40)
            self.assertEqual(self.repository.get(self.record.id).state["grid_size"], 40)
            with patch("dndgm4.map_ui.QInputDialog.getText", return_value=("Arden", True)):
                dialog.add_token()
            token = dialog.record.state["tokens"][0]
            self.assertFalse(token["visible"])
            item = dialog.canvas.token_items[token["id"]]
            item.setPos(QPointF(90, 70))
            dialog.canvas.commit_token_position(item)
            saved = self.repository.get(self.record.id)
            self.assertEqual((saved.state["tokens"][0]["x"], saved.state["tokens"][0]["y"]), (100, 60))
            dialog.token_visible.setChecked(True)
            self.assertTrue(self.repository.get(self.record.id).state["tokens"][0]["visible"])
            dialog.canvas.reveal_cell(100, 60)
            self.assertIn([2, 1], self.repository.get(self.record.id).state["revealed"])
            dialog.open_player_view()
            self.app.processEvents()
            self.assertEqual(len(dialog.player_window.canvas.token_items), 1)
            dialog.hide_all()
            self.assertEqual(len(dialog.player_window.canvas.token_items), 0)
            self.assertEqual(self.repository.get(self.record.id).state["revealed"], [])
        dialog.reject()
        self.app.processEvents()
        self.assertFalse(dialog.player_window.isVisible())

    def test_player_pixels_are_black_under_fog_and_revealed_cells_show_map(self):
        from PyQt6.QtCore import QRectF
        from PyQt6.QtGui import QImage, QPainter
        from dndgm4.map_ui import MapCanvas
        canvas = MapCanvas(public=True)
        self.addCleanup(canvas.close)
        state = deepcopy(self.record.state)
        state["show_grid"] = False
        state["revealed"] = [[0, 0]]
        canvas.set_map(self.image, state)
        rendered = QImage(200, 160, QImage.Format.Format_RGB32)
        rendered.fill(0)
        painter = QPainter(rendered)
        canvas.scene().render(painter, QRectF(0, 0, 200, 160), QRectF(0, 0, 200, 160))
        painter.end()
        self.assertEqual(rendered.pixelColor(25, 25).name(), "#448855")
        self.assertEqual(rendered.pixelColor(125, 125).name(), "#000000")
        # The source held by the public scene is redacted too, before overlays.
        self.assertEqual(canvas.image.toImage().pixelColor(25, 25).name(), "#448855")
        self.assertEqual(canvas.image.toImage().pixelColor(125, 125).name(), "#000000")

    def test_pointer_ruler_reports_saved_calibration_with_explicit_units(self):
        from PyQt6.QtCore import QPointF, Qt
        from PyQt6.QtTest import QTest
        from dndgm4.map_ui import MapDeskDialog
        dialog = MapDeskDialog(self.library, self.campaign.id)
        self.addCleanup(dialog.close)
        dialog.show()
        self.app.processEvents()
        dialog.units_per_cell.setValue(10)
        dialog.unit_label.setText("m")
        dialog.unit_label.editingFinished.emit()
        dialog.ruler_button.click()
        canvas = dialog.canvas
        start = canvas.mapFromScene(QPointF(25, 25))
        end = canvas.mapFromScene(QPointF(115, 145))
        QTest.mousePress(canvas.viewport(), Qt.MouseButton.LeftButton, pos=start)
        QTest.mouseMove(canvas.viewport(), end, 20)
        QTest.mouseRelease(canvas.viewport(), Qt.MouseButton.LeftButton, pos=end)
        self.app.processEvents()
        self.assertTrue(dialog.ruler_result.text().startswith("Straight-line: "))
        self.assertTrue(dialog.ruler_result.text().endswith(" m"))
        self.assertAlmostEqual(float(dialog.ruler_result.text().split()[1]), 30, delta=0.15)
        saved = self.repository.get(self.record.id)
        self.assertEqual(saved.state["units_per_cell"], 10)
        self.assertEqual(saved.state["unit_label"], "m")
        self.assertEqual(len(canvas._ruler_items), 2)
        canvas.clear_ruler()
        self.assertEqual(canvas._ruler_items, [])

    def test_annotations_are_private_by_default_and_public_notes_are_filtered_before_items(self):
        from PyQt6.QtCore import QPointF, Qt
        from PyQt6.QtTest import QTest
        from PyQt6.QtWidgets import QGraphicsTextItem
        from dndgm4.map_ui import MapDeskDialog
        dialog = MapDeskDialog(self.library, self.campaign.id)
        self.addCleanup(dialog.close)
        dialog.show()
        self.app.processEvents()
        with patch("dndgm4.map_ui.QInputDialog.getMultiLineText", return_value=("Secret trap DC 20", True)):
            dialog.add_annotation()
        self.assertFalse(dialog.record.state["annotations"][0]["visible"])
        with patch("dndgm4.map_ui.QInputDialog.getMultiLineText", return_value=("Town gate", True)):
            dialog.add_annotation()
        note_id = dialog.record.state["annotations"][-1]["id"]
        canvas = dialog.canvas
        start = canvas.mapFromScene(QPointF(110, 90))
        end = canvas.mapFromScene(QPointF(35, 35))
        QTest.mousePress(canvas.viewport(), Qt.MouseButton.LeftButton, pos=start)
        QTest.mouseMove(canvas.viewport(), end, 20)
        QTest.mouseRelease(canvas.viewport(), Qt.MouseButton.LeftButton, pos=end)
        self.app.processEvents()
        moved = next(note for note in self.repository.get(self.record.id).state["annotations"] if note["id"] == note_id)
        self.assertAlmostEqual(moved["x"], 25, delta=2)
        self.assertAlmostEqual(moved["y"], 25, delta=2)
        dialog.annotation_visible.setChecked(True)
        dialog.open_player_view()
        self.app.processEvents()
        player = dialog.player_window.canvas
        self.assertEqual(player.annotation_items, {})
        dialog.canvas.reveal_cell(25, 25)
        self.assertEqual(set(player.annotation_items), {note_id})
        texts = [item.toPlainText() for item in player.scene().items() if isinstance(item, QGraphicsTextItem)]
        self.assertEqual(texts, ["Town gate"])
        self.assertNotIn("Secret trap DC 20", str(player.state))
        with patch("dndgm4.map_ui.QInputDialog.getMultiLineText", return_value=("Old town gate", True)):
            dialog.edit_annotation()
        self.assertEqual([item.toPlainText() for item in player.scene().items() if isinstance(item, QGraphicsTextItem)], ["Old town gate"])
        dialog.remove_annotation()
        self.assertEqual(player.annotation_items, {})
        self.assertEqual(len(self.repository.get(self.record.id).state["annotations"]), 1)

    def test_player_pixmap_is_refreshed_from_dm_source_when_cells_are_revealed(self):
        from dndgm4.map_ui import MapDeskDialog
        dialog = MapDeskDialog(self.library, self.campaign.id)
        self.addCleanup(dialog.close)
        dialog.open_player_view()
        player = dialog.player_window.canvas
        self.assertEqual(player.image.toImage().pixelColor(125, 125).name(), "#000000")
        dialog.canvas.reveal_cell(125, 125)
        self.assertEqual(player.image.toImage().pixelColor(125, 125).name(), "#448855")
        self.assertEqual(player.image.toImage().pixelColor(25, 25).name(), "#000000")
        dialog.hide_all()
        self.assertEqual(player.image.toImage().pixelColor(125, 125).name(), "#000000")

    def test_stale_editor_reports_failure_without_overwriting_and_can_reload(self):
        from dndgm4.map_ui import MapDeskDialog
        first = MapDeskDialog(self.library, self.campaign.id)
        stale = MapDeskDialog(self.library, self.campaign.id)
        self.addCleanup(first.close)
        self.addCleanup(stale.close)
        self.assertTrue(first._change("units_per_cell", 10))
        with patch.object(stale, "_error") as error:
            self.assertFalse(stale._change("grid_size", 60))
        error.assert_called_once()
        self.assertIn("not saved", stale.status.text())
        self.assertNotIn("Grid size saved", stale.status.text())
        saved = self.repository.get(self.record.id)
        self.assertEqual(saved.state["grid_size"], 50)
        self.assertEqual(saved.state["units_per_cell"], 10)
        stale._reload_current()
        self.assertTrue(stale._change("grid_size", 60))
        self.assertEqual(self.repository.get(self.record.id).state["units_per_cell"], 10)
        self.app.processEvents()

    def test_failed_map_reload_clears_ruler_and_can_recover_after_image_restore(self):
        from PyQt6.QtCore import QPointF
        from dndgm4.map_ui import MapDeskDialog
        dialog = MapDeskDialog(self.library, self.campaign.id)
        self.addCleanup(dialog.close)
        dialog.canvas._ruler_start = QPointF(25, 25)
        dialog.canvas._ruler_end = QPointF(100, 100)
        dialog.canvas._draw_ruler()
        path = self.repository.image_path(self.record)
        path.unlink()
        with patch.object(dialog, "_error") as error:
            dialog._reload_current()
        error.assert_called_once()
        self.assertIsNone(dialog.canvas.state)
        self.assertEqual(dialog.canvas._ruler_items, [])
        self.assertTrue(self.image.save(str(path)))
        dialog._reload_current()
        self.assertEqual(dialog.record.id, self.record.id)
        self.assertFalse(dialog.canvas.image.isNull())

    def test_encounter_picker_only_offers_campaign_actors_and_unlink_preserves_marker(self):
        from dndgm4.battle_rules import fighter_from_record
        from dndgm4.campaigns import CampaignRepository
        from dndgm4.map_ui import MapDeskDialog
        from dndgm4.models import Creature
        campaigns = CampaignRepository(self.library.path)
        foreign_campaign = campaigns.create_campaign("Other campaign")
        creature = self.library.save(Creature(name="Arden", kind="pc", max_hit_points=24))
        encounters = []
        for campaign, title in ((self.campaign, "Local battle"), (foreign_campaign, "Foreign battle")):
            session = campaigns.create_session(campaign.id, title + " session")
            encounter = campaigns.create_encounter(session.id, title)
            battle = campaigns.load_battle(encounter.id)
            battle.fighters = [fighter_from_record(creature)]
            campaigns.save_battle(encounter.id, battle)
            encounters.append((encounter, battle.fighters[0].uid))
        offered = []
        def choose(parent, title, prompt, choices, current, editable):
            offered.extend(choices)
            return choices[current], True
        dialog = MapDeskDialog(self.library, self.campaign.id)
        self.addCleanup(dialog.close)
        with patch("dndgm4.map_ui.QInputDialog.getItem", side_effect=choose):
            dialog.add_encounter_token()
        self.assertEqual(len(offered), 1)
        self.assertNotIn("Foreign", offered[0])
        token = dialog.record.state["tokens"][0]
        self.assertEqual(token["link"], dict(encounter_id=encounters[0][0].id, fighter_uid=encounters[0][1]))
        self.assertFalse(token["visible"])
        dialog.unlink_token_button.click()
        unlinked = self.repository.get(self.record.id).state["tokens"][0]
        self.assertNotIn("link", unlinked)
        self.assertEqual(unlinked["label"], "Arden")
        self.assertEqual(self.library.get(creature.id).max_hit_points, 24)

    def test_pointer_drag_and_reveal_tool_commit_their_changes(self):
        from PyQt6.QtCore import QPointF, Qt
        from PyQt6.QtTest import QTest
        from dndgm4.map_ui import MapDeskDialog
        state = deepcopy(self.record.state)
        state["snap_to_grid"] = False
        state["tokens"] = [dict(id="hero", label="Arden", x=50, y=50, color="#ed6276", visible=False)]
        self.repository.save_state(self.record.id, state)
        dialog = MapDeskDialog(self.library, self.campaign.id)
        self.addCleanup(dialog.close)
        dialog.show()
        self.app.processEvents()
        canvas = dialog.canvas
        start = canvas.mapFromScene(QPointF(50, 50))
        finish = canvas.mapFromScene(QPointF(100, 80))
        QTest.mousePress(canvas.viewport(), Qt.MouseButton.LeftButton, pos=start)
        QTest.mouseMove(canvas.viewport(), finish, 20)
        QTest.mouseRelease(canvas.viewport(), Qt.MouseButton.LeftButton, pos=finish)
        self.app.processEvents()
        moved = self.repository.get(self.record.id).state["tokens"][0]
        self.assertAlmostEqual(moved["x"], 100, delta=2)
        self.assertAlmostEqual(moved["y"], 80, delta=2)
        dialog.reveal_button.click()
        cell = canvas.mapFromScene(QPointF(175, 125))
        QTest.mouseClick(canvas.viewport(), Qt.MouseButton.LeftButton, pos=cell)
        self.assertIn([3, 2], self.repository.get(self.record.id).state["revealed"])

    def test_player_scene_never_constructs_secret_or_unexplored_labels(self):
        from PyQt6.QtWidgets import QGraphicsItem, QGraphicsSimpleTextItem, QLabel
        from dndgm4.map_ui import PlayerMapWindow
        state = deepcopy(self.record.state)
        state["revealed"] = [[0, 0]]
        state["tokens"] = [
            dict(id="public", label="Arden", x=25, y=25, color="#ed6276", visible=True),
            dict(id="secret", label="Secret assassin", x=25, y=25, color="#ed6276", visible=False),
            dict(id="unknown", label="Unexplored dragon", x=125, y=125, color="#ed6276", visible=True),
        ]
        window = PlayerMapWindow(self.image, state)
        self.addCleanup(window.close)
        window.show()
        self.app.processEvents()
        labels = [item.text() for item in window.canvas.scene().items() if isinstance(item, QGraphicsSimpleTextItem)]
        self.assertEqual(labels, ["Arden"])
        self.assertEqual(set(window.canvas.token_items), {"public"})
        self.assertFalse(window.canvas.token_items["public"].flags() & QGraphicsItem.GraphicsItemFlag.ItemIsMovable)
        self.assertNotIn("Secret", window.windowTitle())
        self.assertFalse(window.findChildren(QLabel))
        original = deepcopy(window.canvas.state)
        window.canvas.reveal_cell(125, 125)
        self.assertEqual(window.canvas.state, original)

    def test_compact_desk_and_repeated_player_window_close_remain_usable(self):
        from dndgm4.map_ui import MapDeskDialog
        dialog = MapDeskDialog(self.library, self.campaign.id)
        self.addCleanup(dialog.close)
        dialog.resize(895, 640)
        dialog.show()
        self.app.processEvents()
        self.assertGreater(dialog.canvas.viewport().width(), 350)
        self.assertGreater(dialog.canvas.viewport().height(), 300)
        for _ in range(3):
            dialog.open_player_view()
            self.app.processEvents()
            dialog.player_window.close()
            dialog.open_player_view()
            self.app.processEvents()
            self.assertTrue(dialog.player_window.isVisible())
        dialog.close()
        self.app.processEvents()
        self.assertFalse(dialog.player_window.isVisible())


if __name__ == "__main__":
    unittest.main()
