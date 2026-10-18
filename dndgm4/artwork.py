"""Packaged fantasy artwork for the desktop interface.

The assets are bundled with the application, not loaded from the internet.
Keep the paths confined to this allowlisted package directory.
"""
from __future__ import annotations

from functools import lru_cache
from importlib.resources import files

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QIcon, QPixmap
from PyQt6.QtWidgets import QLabel

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
