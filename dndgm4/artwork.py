"""Packaged fantasy artwork for the desktop interface.

The assets are bundled with the application, not loaded from the internet.
Keep the paths confined to this allowlisted package directory.
"""
from __future__ import annotations

from functools import lru_cache
from importlib.resources import files

from PyQt6.QtCore import QPointF, QRectF, Qt
from PyQt6.QtGui import QColor, QIcon, QPainter, QPainterPath, QPen, QPixmap
from PyQt6.QtWidgets import QLabel

from .theme import COLORS

_ASSET_NAMES = frozenset({
    "app_banner.jpg",
    "dragon_crest.png",
    "name_genie_crest.png",
})


@lru_cache(maxsize=8)
def load_artwork(name: str) -> QPixmap:
    """Load image bytes from the installed package or a PyInstaller bundle."""
    if name not in _ASSET_NAMES:
        raise ValueError("Unknown artwork asset.")
    image = QPixmap()
    try:
        payload = files("dndgm4").joinpath("assets", name).read_bytes()
    except (FileNotFoundError, OSError):
        # A partially installed or quarantined art file must never prevent
        # the entire application from launching. The banner renders its
        # existing text fallback if its image cannot be loaded.
        return image
    image.loadFromData(payload)
    return image


def window_icon() -> QIcon:
    """Use the same dragon/d20 crest across dialogs and taskbar surfaces."""
    return QIcon(load_artwork("dragon_crest.png"))


class CoverArtLabel(QLabel):
    """Accessible crop-to-fill banner without image stretching.

    A fixed-height banner avoids sacrificing the Compendium's table space.
    """
    def __init__(self, image_name: str, *, height: int = 158,
                 description: str = "", parent=None):
        super().__init__(parent)
        self.source = load_artwork(image_name)
        self.setFixedHeight(height)
        self.setMinimumWidth(200)
        self.setObjectName("artworkBanner")
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setAccessibleName(description or "Fantasy artwork")
        self.setToolTip(description)
        self.update_picture()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.update_picture()

    def paintEvent(self, event):
        super().paintEvent(event)
        # Draw interface ornament over the image instead of modifying the
        # packaged artwork or cached pixmaps. It stays sharp at any display DPI.
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.setPen(QPen(QColor(COLORS["border"]), 1.0))
        painter.drawRoundedRect(QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5), 10, 10)

        inset, arm = 5.5, 27.0
        for right, bottom in ((False, False), (True, False), (False, True), (True, True)):
            x = self.width() - inset if right else inset
            y = self.height() - inset if bottom else inset
            dx, dy = (-1 if right else 1), (-1 if bottom else 1)
            corner = QPainterPath(QPointF(x, y + dy * arm))
            corner.lineTo(x, y + dy * 9)
            corner.lineTo(x + dx * 9, y)
            corner.lineTo(x + dx * arm, y)
            painter.setPen(QPen(QColor(COLORS["window"]), 3.0))
            painter.drawPath(corner)
            painter.setPen(QPen(QColor(COLORS["ember"]), 1.0))
            painter.drawPath(corner)

        # Small lozenges echo the banner's original compass and d20 geometry.
        painter.setPen(QPen(QColor(COLORS["ember"]), 0.8))
        painter.setBrush(QColor(COLORS["raised"]))
        center = self.width() / 2
        for y in (5.5, self.height() - 5.5):
            diamond = QPainterPath(QPointF(center, y - 3))
            diamond.lineTo(center + 6, y)
            diamond.lineTo(center, y + 3)
            diamond.lineTo(center - 6, y)
            diamond.closeSubpath()
            painter.drawPath(diamond)

    def update_picture(self):
        if self.source.isNull():
            self.setText("D&D GAME MANAGER 4  |  THE COMPENDIUM")
            return
        if self.width() <= 0 or self.height() <= 0:
            return
        expanded = self.source.scaled(
            self.size(),
            Qt.AspectRatioMode.KeepAspectRatioByExpanding,
            Qt.TransformationMode.SmoothTransformation,
        )
        left = max(0, (expanded.width() - self.width()) // 2)
        top = max(0, (expanded.height() - self.height()) // 2)
        self.setPixmap(expanded.copy(left, top, self.width(), self.height()))
