"""Campaign time UI makes all game-clock and weather changes explicit."""
from importlib.util import find_spec
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch


@unittest.skipUnless(find_spec("PyQt6") is not None, "PyQt6 is not installed")
class CampaignTimeUiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        from PyQt6.QtWidgets import QApplication
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        from dndgm4.campaign_time import CampaignTimeRepository
        from dndgm4.time_ui import CampaignTimeDialog
        self.temp = TemporaryDirectory()
        self.path = Path(self.temp.name) / "library.sqlite3"
        self.repo = CampaignTimeRepository(self.path)
        self.campaign = self.repo.campaigns.create_campaign("Ash Road")
        self.dialog = CampaignTimeDialog(self.path, self.campaign.id)

    def tearDown(self):
        self.dialog._calendar_dirty = False
        self.dialog.close()
        self.dialog.deleteLater()
        self.app.processEvents()
        self.temp.cleanup()

    def test_open_preview_and_cancel_leave_clock_and_workspace_unchanged(self):
        from dndgm4.campaigns import ActiveWorkspace
        self.assertEqual(self.repo.get_clock(self.campaign.id).minutes, 0)
        self.repo.add_event(self.campaign.id, 30, "A visitor")
        self.assertTrue(self.dialog.preview_advance())
        self.assertIn("A visitor", self.dialog.advance_preview.toPlainText())
        self.assertEqual(self.repo.get_clock(self.campaign.id).minutes, 0)
        self.dialog.reject()
        self.assertEqual(self.repo.get_clock(self.campaign.id).minutes, 0)
        self.assertEqual(self.repo.campaigns.get_workspace(), ActiveWorkspace())

    def test_edit_invalidates_review_and_apply_saves_clock_once(self):
        self.dialog.preview_advance()
        self.assertTrue(self.dialog.advance_apply.isEnabled())
        self.dialog.advance_minutes.setValue(90)
        self.assertFalse(self.dialog.advance_apply.isEnabled())
        self.assertFalse(self.dialog.apply_time())
        self.assertTrue(self.dialog.preview_advance())
        self.assertTrue(self.dialog.apply_time())
        self.assertEqual(self.repo.get_clock(self.campaign.id).minutes, 90)
        self.assertFalse(self.dialog.advance_apply.isEnabled())
        self.assertIn("90", self.dialog.history.toPlainText())

    def test_stale_review_failure_preserves_clock_and_reports_refresh_action(self):
        self.dialog.preview_advance()
        self.repo.apply_preview(self.repo.preview_advance(self.campaign.id, 15, "Another window"))
        self.assertFalse(self.dialog.apply_time())
        self.assertIn("clock changed", self.dialog.message.text())
        self.assertEqual(self.repo.get_clock(self.campaign.id).minutes, 15)
        self.assertFalse(self.dialog.advance_apply.isEnabled())

    def test_travel_and_rest_are_reviewed_workflows_with_clear_resource_limits(self):
        self.dialog.travel_distance.setText("10")
        self.dialog.travel_speed.setText("2.5")
        self.dialog.travelers.setValue(4)
        self.assertTrue(self.dialog.preview_travel())
        self.assertIn("supplies", self.dialog.travel_preview.toPlainText())
        self.assertEqual(self.repo.get_clock(self.campaign.id).minutes, 0)
        self.assertTrue(self.dialog.apply_time())
        self.assertEqual(self.repo.get_clock(self.campaign.id).minutes, 240)
        self.assertTrue(self.dialog.preview_rest())
        self.assertIn("nothing is replenished", self.dialog.rest_preview.toPlainText())
        self.assertTrue(self.dialog.apply_time())
        self.assertEqual(self.repo.get_clock(self.campaign.id).minutes, 720)
        self.dialog.travel_speed.setText("bad")
        self.assertFalse(self.dialog.preview_travel())
        self.assertEqual(self.dialog.travel_speed.text(), "bad")

    def test_named_calendar_review_then_save_and_custom_day_event(self):
        self.dialog.calendar_name.setText("Ember cycle")
        self.dialog.calendar_months.setPlainText("Thaw | 2\nEmber | 3")
        self.dialog.calendar_hours.setValue(10)
        self.assertTrue(self.dialog.preview_calendar())
        self.assertEqual(self.repo.get_clock(self.campaign.id).calendar.name, "Campaign calendar")
        self.assertTrue(self.dialog.apply_calendar())
        self.assertEqual(self.repo.get_clock(self.campaign.id).calendar.name, "Ember cycle")
        self.assertEqual(self.dialog.event_hour.maximum(), 9)
        self.dialog.event_day.setValue(2)
        self.dialog.event_hour.setValue(1)
        self.dialog.event_title.setText("Dawn council")
        self.assertTrue(self.dialog.add_event())
        self.assertEqual(self.repo.timeline(self.campaign.id)[0].at_minutes, 1260)
        self.assertIn("Ember 1", self.dialog.events.item(0).text())

    def test_weather_requires_save_and_day_change_discards_unsaved_roll(self):
        self.assertTrue(self.dialog.preview_weather())
        self.assertIsNone(self.repo.weather(self.campaign.id, 0))
        self.dialog.weather_day.setValue(1)
        self.assertFalse(self.dialog.weather_apply.isEnabled())
        self.assertFalse(self.dialog.apply_weather())
        self.assertTrue(self.dialog.preview_weather())
        roll = self.dialog._weather_preview.roll
        self.assertTrue(self.dialog.apply_weather())
        self.assertEqual(self.repo.weather(self.campaign.id, 1)["roll"], roll)
        self.assertIn("Saved:", self.dialog.saved_weather.text())

    def test_calendar_invalid_draft_and_sql_failure_are_visible_without_data_loss(self):
        self.dialog.calendar_months.setPlainText("No separator")
        self.assertFalse(self.dialog.preview_calendar())
        self.assertEqual(self.dialog.calendar_months.toPlainText(), "No separator")
        self.assertFalse(self.dialog.calendar_apply.isEnabled())
        self.assertTrue(self.dialog.preview_advance())
        import sqlite3
        with patch.object(self.dialog.repository, "apply_preview", side_effect=sqlite3.OperationalError("Disk is full")):
            self.assertFalse(self.dialog.apply_time())
        self.assertEqual(self.dialog.message.text(), "Disk is full")
        self.assertEqual(self.repo.get_clock(self.campaign.id).minutes, 0)

    def test_calendar_draft_survives_time_save_refresh_and_cancel_close(self):
        from PyQt6.QtWidgets import QMessageBox
        self.dialog.calendar_months.setPlainText("Unfinished calendar draft")
        self.dialog.preview_advance()
        self.assertTrue(self.dialog.apply_time())
        self.assertEqual(self.dialog.calendar_months.toPlainText(), "Unfinished calendar draft")
        with patch("dndgm4.time_ui.QMessageBox.question", return_value=QMessageBox.StandardButton.Cancel):
            self.dialog.reject()
        self.assertTrue(self.dialog._calendar_dirty)
        self.assertEqual(self.dialog.calendar_months.toPlainText(), "Unfinished calendar draft")
