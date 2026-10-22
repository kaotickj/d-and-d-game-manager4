"""Real handout UI lifecycle and public preview/export identity checks."""
from dataclasses import replace
from importlib.util import find_spec
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch
import zipfile


@unittest.skipUnless(find_spec("PyQt6"), "PyQt6 is not installed")
class HandoutUiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        from PyQt6.QtWidgets import QApplication
        from dndgm4.theme import apply_theme
        cls.app = QApplication.instance() or QApplication([])
        apply_theme(cls.app)

    def setUp(self):
        from PyQt6.QtGui import QColor, QImage
        from dndgm4.handouts import HandoutRepository
        from dndgm4.storage import CreatureRepository
        from dndgm4.world import WorldRepository
        self.temp = TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.library = CreatureRepository(self.root / "library.sqlite3")
        self.world = WorldRepository(self.library.path)
        self.campaign = self.world.campaigns.create_campaign("SECRET campaign title")
        self.handout = self.world.create(self.campaign.id, "handout", "SECRET DM handout title", summary="SECRET summary", dm_notes="SECRET private instructions", details={"player_text": "Follow the red road."})
        self.repo = HandoutRepository(self.library)
        self.source = self.root / "SECRET source.png"
        image = QImage(120, 80, QImage.Format.Format_ARGB32)
        image.fill(QColor("#884433"))
        image.setText("Author", "SECRET metadata")
        self.assertTrue(image.save(str(self.source), "PNG"))
        self.dialogs = []

    def tearDown(self):
        for dialog in self.dialogs:
            dialog.close()
        self.app.processEvents()
        self.temp.cleanup()

    def dialog(self):
        from PyQt6.QtCore import Qt
        from dndgm4.handouts_ui import HandoutGalleryDialog
        dialog = HandoutGalleryDialog(self.library, self.campaign.id)
        self.dialogs.append(dialog)
        for row in range(dialog.handouts.count()):
            if dialog.handouts.item(row).data(Qt.ItemDataRole.UserRole) == self.handout.id:
                dialog.handouts.setCurrentRow(row)
                break
        return dialog

    def attach(self, dialog):
        with patch("dndgm4.handouts_ui.QFileDialog.getOpenFileName", return_value=(str(self.source), "PNG")):
            self.assertTrue(dialog.attach_image())

    def test_attach_requires_review_before_display_and_public_window_has_no_dm_controls(self):
        from PyQt6.QtWidgets import QLabel, QPushButton
        dialog = self.dialog()
        self.assertFalse(dialog.display_button.isEnabled())
        self.assertFalse(dialog.export_button.isEnabled())
        self.attach(dialog)
        self.assertIsNone(dialog.preview_window)
        self.assertFalse(dialog.open_player_display())
        self.assertTrue(dialog.review_player_handout())
        self.assertTrue(dialog.open_player_display())
        window = dialog.player_window
        self.assertEqual(window.text_view.toPlainText(), "Follow the red road.")
        self.assertTrue(window.text_view.isReadOnly())
        self.assertEqual(window.findChildren(QPushButton), [])
        self.assertNotIn("SECRET", window.windowTitle())
        self.assertTrue(all("SECRET" not in label.text() for label in window.findChildren(QLabel)))
        self.assertEqual(window.image_view.image.textKeys(), [])
        self.assertEqual(window.payload, dialog.preview_window.payload)

    def test_export_reuses_reviewed_snapshot_and_refresh_requires_new_review(self):
        from dndgm4.world import details_json
        dialog = self.dialog()
        self.attach(dialog)
        self.assertTrue(dialog.review_player_handout())
        preview = dialog.preview_window
        reviewed = preview.payload
        self.world.save(replace(self.handout, details_json=details_json("handout", {"player_text": "New saved text for next review."})))
        target = self.root / "public.zip"
        with patch("dndgm4.handouts_ui.QFileDialog.getSaveFileName", return_value=(str(target), "ZIP")):
            self.assertTrue(dialog.export_reviewed())
        with zipfile.ZipFile(target) as archive:
            self.assertEqual(archive.read("handout.txt"), reviewed.text.encode("utf-8"))
            self.assertEqual(archive.read("image.png"), reviewed.image_png)
        dialog.open_player_display()
        player = dialog.player_window
        dialog.refresh_handouts()
        self.app.processEvents()
        self.assertFalse(preview.isVisible())
        self.assertFalse(player.isVisible())
        self.assertFalse(dialog.export_button.isEnabled())
        self.assertIsNone(dialog._reviewed_payload)
        self.assertTrue(dialog.review_player_handout())
        self.assertEqual(dialog.preview_window.payload.text, "New saved text for next review.")

    def test_archiving_retains_file_and_restoration_needs_explicit_selection(self):
        from PyQt6.QtCore import Qt
        dialog = self.dialog()
        self.attach(dialog)
        asset = dialog.images.currentItem().data(Qt.ItemDataRole.UserRole)
        self.assertTrue(dialog.archive_selected())
        self.assertTrue((self.root / asset.image_path).is_file())
        self.assertIsNone(self.repo.public_payload(self.campaign.id, self.handout.id).image_png)
        dialog.show_archived.setChecked(True)
        dialog.images.setCurrentRow(0)
        self.assertEqual(dialog.archive_button.text(), "Restore Selected Image")
        self.assertTrue(dialog.archive_selected())
        self.assertIsNone(self.repo.public_payload(self.campaign.id, self.handout.id).image_png)
        self.assertTrue(dialog.use_selected_image())
        self.assertIsNotNone(self.repo.public_payload(self.campaign.id, self.handout.id).image_png)

    def test_failed_attachment_and_export_preserve_existing_image_and_library(self):
        dialog = self.dialog()
        self.attach(dialog)
        before = self.repo.public_payload(self.campaign.id, self.handout.id)
        bad = self.root / "bad.png"
        bad.write_text("not a raster")
        with patch("dndgm4.handouts_ui.QFileDialog.getOpenFileName", return_value=(str(bad), "PNG")):
            self.assertFalse(dialog.attach_image())
        self.assertEqual(self.repo.public_payload(self.campaign.id, self.handout.id), before)
        self.assertTrue(dialog.review_player_handout())
        database = self.library.path.read_bytes()
        with patch("dndgm4.handouts_ui.QFileDialog.getSaveFileName", return_value=(str(self.library.path), "ZIP")):
            self.assertFalse(dialog.export_reviewed())
        self.assertEqual(self.library.path.read_bytes(), database)
        self.assertIn("outside", dialog.message.text())

    def test_changing_handout_and_parent_close_close_all_public_windows(self):
        from PyQt6.QtCore import Qt
        second = self.world.create(self.campaign.id, "handout", "Second", details={"player_text": "A second letter."})
        dialog = self.dialog()
        self.assertTrue(dialog.review_player_handout())
        preview = dialog.preview_window
        dialog.open_player_display()
        player = dialog.player_window
        for row in range(dialog.handouts.count()):
            if dialog.handouts.item(row).data(Qt.ItemDataRole.UserRole) == second.id:
                dialog.handouts.setCurrentRow(row)
        self.app.processEvents()
        self.assertFalse(preview.isVisible())
        self.assertFalse(player.isVisible())
        dialog.review_player_handout()
        dialog.open_player_display()
        preview, player = dialog.preview_window, dialog.player_window
        dialog.reject()
        self.app.processEvents()
        self.assertFalse(preview.isVisible())
        self.assertFalse(player.isVisible())

    def test_compact_gallery_is_scrollable_and_opening_changes_no_handout(self):
        from PyQt6.QtWidgets import QScrollArea
        before = self.world.get(self.handout.id)
        dialog = self.dialog()
        dialog.resize(830, 540)
        dialog.show()
        self.app.processEvents()
        self.assertTrue(dialog.findChild(QScrollArea).widgetResizable())
        self.assertEqual(dialog.size().width(), 830)
        self.assertEqual(self.world.get(self.handout.id), before)
        self.assertEqual(self.repo.list_images(self.campaign.id, self.handout.id), [])

    def test_close_ends_a_real_modal_gallery_event_loop(self):
        from PyQt6.QtCore import QTimer
        from PyQt6.QtWidgets import QDialog
        dialog = self.dialog()
        self.assertTrue(dialog.review_player_handout())
        preview = dialog.preview_window
        QTimer.singleShot(0, dialog.close)
        self.assertEqual(dialog.exec(), QDialog.DialogCode.Rejected)
        self.assertFalse(preview.isVisible())
