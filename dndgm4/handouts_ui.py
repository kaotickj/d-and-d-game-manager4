"""Handout image attachments with one reviewed public preview/export snapshot."""
from __future__ import annotations

import sqlite3

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QImage, QPixmap
from PyQt6.QtWidgets import (
    QCheckBox, QDialog, QDialogButtonBox, QFileDialog, QHBoxLayout, QLabel,
    QListWidget, QListWidgetItem, QPlainTextEdit, QPushButton, QScrollArea,
    QSplitter, QVBoxLayout, QWidget,
)

from .artwork import window_icon
from .handouts import HandoutRepository, PublicHandout


def _label(text):
    widget = QLabel(text)
    widget.setWordWrap(True)
    widget.setTextFormat(Qt.TextFormat.PlainText)
    return widget


def _button(text, callback):
    widget = QPushButton(text)
    widget.clicked.connect(callback)
    return widget


class _PublicImage(QLabel):
    def __init__(self, payload, parent=None):
        super().__init__(parent)
        self.image = QImage.fromData(payload, b"PNG")
        if self.image.isNull():
            raise ValueError("The reviewed public image could not be displayed.")
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setAccessibleName("Player handout illustration")
        self.setMinimumSize(100, 100)
        self.setStyleSheet("background: #09070a;")

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.setPixmap(QPixmap.fromImage(self.image).scaled(
            self.size(), Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation))


class PlayerHandoutWindow(QDialog):
    """Receives only the public snapshot; no library paths or world record."""
    def __init__(self, payload: PublicHandout, parent=None, *, preview=False):
        super().__init__(parent)
        if not isinstance(payload, PublicHandout):
            raise ValueError("Choose a reviewed public handout.")
        self.payload = payload
        self.setAttribute(Qt.WidgetAttribute.WA_QuitOnClose, False)
        self.setWindowTitle("Player Handout Preview" if preview else "Player Handout")
        self.resize(900, 700)
        self.setMinimumSize(360, 300)
        layout = QVBoxLayout(self)
        splitter = QSplitter(Qt.Orientation.Vertical)
        layout.addWidget(splitter)
        self.image_view = None
        self.text_view = None
        if payload.image_png is not None:
            self.image_view = _PublicImage(payload.image_png)
            splitter.addWidget(self.image_view)
        if payload.text:
            self.text_view = QPlainTextEdit()
            self.text_view.setReadOnly(True)
            self.text_view.setAcceptDrops(False)
            self.text_view.setAccessibleName("Player handout text only")
            self.text_view.setPlainText(payload.text)
            splitter.addWidget(self.text_view)
        if payload.image_png is not None and payload.text:
            splitter.setSizes([440, 220])


class HandoutGalleryDialog(QDialog):
    assets_changed = pyqtSignal()

    def __init__(self, library_repository, campaign_id, parent=None):
        super().__init__(parent)
        self.repository = HandoutRepository(library_repository)
        self.campaign_id = campaign_id
        campaign = self.repository.world.campaigns.get_campaign(campaign_id)
        if campaign is None:
            raise ValueError("Choose a saved campaign before opening Player Handout Gallery.")
        self._handout_id = None
        self._loading = False
        self._reviewed_payload = None
        self.preview_window = None
        self.player_window = None
        self.setAttribute(Qt.WidgetAttribute.WA_QuitOnClose, False)
        self.setWindowTitle(f"Player Handout Gallery · {campaign.name}")
        self.setWindowIcon(window_icon())
        self.resize(1030, 730)
        self.setMinimumSize(830, 540)
        layout = QVBoxLayout(self)
        heading = _label("PLAYER HANDOUT GALLERY")
        heading.setObjectName("pageTitle")
        layout.addWidget(heading)
        layout.addWidget(_label("Select a saved handout from the World & Campaign Desk. Attach an illustration, choose its player image, then review the exact text and image before displaying or exporting them."))
        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setChildrenCollapsible(False)
        layout.addWidget(splitter, 1)
        navigation = QWidget()
        nav = QVBoxLayout(navigation)
        nav.addWidget(_label("Saved handouts · names are DM-only"))
        self.handouts = QListWidget()
        self.handouts.setAccessibleName("Saved campaign handouts")
        self.handouts.currentItemChanged.connect(self._handout_changed)
        nav.addWidget(self.handouts, 1)
        nav.addWidget(_button("Refresh Saved Handouts", self.refresh_handouts))
        splitter.addWidget(navigation)
        body = QWidget()
        content = QVBoxLayout(body)
        content.addWidget(_label("Images attached to this handout"))
        self.images = QListWidget()
        self.images.setAccessibleName("Attached handout images")
        self.images.setMinimumHeight(150)
        self.images.currentItemChanged.connect(self._image_changed)
        content.addWidget(self.images, 1)
        self.show_archived = QCheckBox("Include archived images")
        self.show_archived.toggled.connect(self.refresh_images)
        content.addWidget(self.show_archived)
        self.attach_button = _button("Attach PNG / JPEG / WebP…", self.attach_image)
        content.addWidget(self.attach_button)
        row = QHBoxLayout()
        self.select_button = _button("Use Selected Image", self.use_selected_image)
        self.text_only_button = _button("Use Player Text Only", self.use_text_only)
        row.addWidget(self.select_button)
        row.addWidget(self.text_only_button)
        content.addLayout(row)
        self.archive_button = _button("Archive Selected Image", self.archive_selected)
        content.addWidget(self.archive_button)
        self.selection_status = _label("")
        content.addWidget(self.selection_status)
        content.addWidget(_label("Imported images are copied into managed assets and stripped of source metadata. Archiving retains their files for recovery. Only the image marked [For players] and the saved Player text enter the public preview."))
        self.review_button = _button("Review Player Preview…", self.review_player_handout)
        self.review_button.setObjectName("primaryButton")
        content.addWidget(self.review_button)
        row = QHBoxLayout()
        self.display_button = _button("Open Reviewed Player Display", self.open_player_display)
        self.export_button = _button("Export Reviewed Handout ZIP…", self.export_reviewed)
        row.addWidget(self.display_button)
        row.addWidget(self.export_button)
        content.addLayout(row)
        content.addWidget(_label("Display and export use the same reviewed snapshot. Review again after editing Player text in the World Desk or changing the selected image. ZIP files contain only handout.txt and, when selected, image.png."))
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(body)
        splitter.addWidget(scroll)
        splitter.setSizes([290, 740])
        self.message = _label("")
        self.message.setAccessibleName("Handout gallery operation result")
        layout.addWidget(self.message)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.close)
        layout.addWidget(buttons)
        self.refresh_handouts()

    def _report(self, error):
        self.message.setText(str(error))
        return False

    def _close_public_windows(self):
        for window in (self.preview_window, self.player_window):
            if window is not None:
                window.close()
        self.preview_window = self.player_window = None

    def _invalidate_review(self):
        self._reviewed_payload = None
        self._close_public_windows()
        self.display_button.setEnabled(False)
        self.export_button.setEnabled(False)

    def refresh_handouts(self):
        self._invalidate_review()
        try:
            records = self.repository.list_handouts(self.campaign_id)
        except (ValueError, sqlite3.Error, OSError) as exc:
            return self._report(exc)
        current = self._handout_id
        self.handouts.blockSignals(True)
        self.handouts.clear()
        for record in records:
            item = QListWidgetItem(record.name)
            item.setData(Qt.ItemDataRole.UserRole, record.id)
            self.handouts.addItem(item)
            if record.id == current:
                self.handouts.setCurrentItem(item)
        if self.handouts.currentRow() < 0 and self.handouts.count():
            self.handouts.setCurrentRow(0)
        self.handouts.blockSignals(False)
        self._handout_changed()
        return True

    def _handout_changed(self, *_):
        self._invalidate_review()
        item = self.handouts.currentItem()
        self._handout_id = item.data(Qt.ItemDataRole.UserRole) if item else None
        self.refresh_images()

    def refresh_images(self, *_args, preferred=None):
        self._invalidate_review()
        self._loading = True
        self.images.clear()
        try:
            if self._handout_id:
                assets = self.repository.list_images(self.campaign_id, self._handout_id, include_archived=self.show_archived.isChecked())
                for number, asset in enumerate(assets, 1):
                    suffix = " [Archived]" if asset.archived else " [For players]" if asset.selected else ""
                    item = QListWidgetItem(f"Image {number} · {asset.width:,} × {asset.height:,}{suffix}")
                    item.setData(Qt.ItemDataRole.UserRole, asset)
                    self.images.addItem(item)
                    if asset.id == preferred or (preferred is None and asset.selected):
                        self.images.setCurrentItem(item)
        except (ValueError, sqlite3.Error, OSError) as exc:
            self._report(exc)
        finally:
            self._loading = False
        self._sync_controls()

    def _image_changed(self, *_):
        if not self._loading:
            self._invalidate_review()
            self._sync_controls()

    def _sync_controls(self):
        enabled = bool(self._handout_id)
        self.attach_button.setEnabled(enabled)
        self.text_only_button.setEnabled(enabled)
        self.review_button.setEnabled(enabled)
        current = self.images.currentItem()
        asset = current.data(Qt.ItemDataRole.UserRole) if current else None
        self.select_button.setEnabled(asset is not None and not asset.archived)
        self.archive_button.setEnabled(asset is not None)
        self.archive_button.setText("Restore Selected Image" if asset and asset.archived else "Archive Selected Image")
        if not enabled:
            text = "Create and save a handout in World & Campaign Desk to begin."
        else:
            chosen = next((self.images.item(row).text() for row in range(self.images.count())
                           if self.images.item(row).data(Qt.ItemDataRole.UserRole).selected), None)
            text = f"Current public image: {chosen}" if chosen else "Current player output uses Player text only."
            if asset and not asset.selected:
                text += "\nThe highlighted image is not selected for players."
        self.selection_status.setText(text)

    def attach_image(self):
        if not self._handout_id:
            return False
        source, _ = QFileDialog.getOpenFileName(self, "Attach a Handout Illustration", "", "Raster images (*.png *.jpg *.jpeg *.webp)")
        if not source:
            return False
        try:
            saved = self.repository.import_image(self.campaign_id, self._handout_id, source)
            self.refresh_images(preferred=saved.id)
            self.message.setText("Image attached and selected. Review the player preview before displaying or exporting it.")
            self.assets_changed.emit()
            return True
        except (ValueError, sqlite3.Error, OSError) as exc:
            return self._report(exc)

    def use_selected_image(self):
        current = self.images.currentItem()
        if not current or not self._handout_id:
            return False
        try:
            asset = current.data(Qt.ItemDataRole.UserRole)
            self.repository.select_image(self.campaign_id, self._handout_id, asset.id)
            self.refresh_images(preferred=asset.id)
            self.message.setText("Player image selected. Review a new public preview.")
            self.assets_changed.emit()
            return True
        except (ValueError, sqlite3.Error, OSError) as exc:
            return self._report(exc)

    def use_text_only(self):
        if not self._handout_id:
            return False
        try:
            self.repository.select_image(self.campaign_id, self._handout_id, None)
            self.refresh_images()
            self.message.setText("No image selected. The player preview will contain only saved Player text.")
            self.assets_changed.emit()
            return True
        except (ValueError, sqlite3.Error, OSError) as exc:
            return self._report(exc)

    def archive_selected(self):
        current = self.images.currentItem()
        if not current or not self._handout_id:
            return False
        try:
            asset = current.data(Qt.ItemDataRole.UserRole)
            self.repository.set_archived(self.campaign_id, self._handout_id, asset.id, not asset.archived)
            self.refresh_images(preferred=asset.id)
            self.message.setText("Image restored; select it explicitly for players." if asset.archived else "Image archived. Its file is retained in complete backups.")
            self.assets_changed.emit()
            return True
        except (ValueError, sqlite3.Error, OSError) as exc:
            return self._report(exc)

    def review_player_handout(self):
        if not self._handout_id:
            return False
        self._invalidate_review()
        try:
            payload = self.repository.public_payload(self.campaign_id, self._handout_id)
            self.preview_window = PlayerHandoutWindow(payload, self, preview=True)
            self._reviewed_payload = payload
            self.preview_window.show()
            self.display_button.setEnabled(True)
            self.export_button.setEnabled(True)
            self.message.setText("Public snapshot reviewed. Display and export will use exactly this text and image.")
            return True
        except (ValueError, sqlite3.Error, OSError) as exc:
            return self._report(exc)

    def open_player_display(self):
        if self._reviewed_payload is None:
            return self._report("Review a player preview before opening its display.")
        if self.player_window is not None:
            self.player_window.close()
        self.player_window = PlayerHandoutWindow(self._reviewed_payload, self)
        self.player_window.show()
        return True

    def export_reviewed(self):
        if self._reviewed_payload is None:
            return self._report("Review a player preview before exporting it.")
        destination, _ = QFileDialog.getSaveFileName(self, "Export Reviewed Player Handout", "player-handout.zip", "ZIP files (*.zip)")
        if not destination:
            return False
        try:
            self.repository.export_payload(self._reviewed_payload, destination)
            self.message.setText("Reviewed player snapshot exported. Private metadata and source filenames were excluded.")
            return True
        except (ValueError, sqlite3.Error, OSError) as exc:
            return self._report(exc)

    def reject(self):
        self._close_public_windows()
        super().reject()

    def closeEvent(self, event):
        self._close_public_windows()
        super().closeEvent(event)
