"""Packaged fantasy artwork for the desktop interface.

The assets are bundled with the application, not loaded from the internet.
Keep the paths confined to this allowlisted package directory.
"""
from __future__ import annotations

from functools import lru_cache
from importlib.resources import files

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QIcon, QPixmap
from PyQt6.QtWidgets import QLabel, QSizePolicy

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
    image.loadFromData(files("dndgm4").joinpath("assets", name).read_bytes())
    return image


def window_icon() -> QIcon:
    """Use the same dragon/d20 crest across dialogs and taskbar surfaces."""
    return QIcon(load_artwork("dragon_crest.png"))


class CoverArtLabel(QLabel):
    """Accessible aspect-preserving banner without cropping or distortion.

    At ultrawide/fullscreen sizes the entire illustration remains visible,
    instead of cropping its top/bottom and cutting off the title.
    """
    def __init__(self, image_name: str, *, height: int = 158,
                 description: str = "", parent=None):
        super().__init__(parent)
        self.source = load_artwork(image_name)
        self.setFixedHeight(height)
        self.setMinimumWidth(0)
        self.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed
        )
        self.setObjectName("artworkBanner")
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setAccessibleName(description or "Fantasy artwork")
        self.setToolTip(description)
        self.update_picture()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.update_picture()

    def update_picture(self):
        if self.source.isNull():
            self.setText("D&D GAME MANAGER 4  |  THE COMPENDIUM")
            return
        if self.width() <= 0 or self.height() <= 0:
            return
        # Fit, never crop: on very wide displays the image has quiet margins,
        # but its dragon, map, title, and border remain intact.
        fitted = self.source.scaled(
            self.size(),
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        self.setPixmap(fitted)
