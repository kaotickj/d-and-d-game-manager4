"""Readable theme states and packaged, visible checkbox affordances."""
from importlib.util import find_spec
import os
import unittest


def contrast_ratio(first, second):
    """WCAG relative luminance, independent of the theme implementation."""
    def luminance(value):
        channels = [int(value[index:index + 2], 16) / 255 for index in (1, 3, 5)]
        linear = [channel / 12.92 if channel <= 0.04045 else
                  ((channel + 0.055) / 1.055) ** 2.4 for channel in channels]
        return sum(channel * weight for channel, weight in zip(linear, (0.2126, 0.7152, 0.0722)))
    values = sorted((luminance(first), luminance(second)))
    return (values[1] + 0.05) / (values[0] + 0.05)


@unittest.skipUnless(find_spec("PyQt6") is not None, "PyQt6 unavailable")
class RedBlackThemeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        from PyQt6.QtWidgets import QApplication
        from dndgm4.theme import apply_theme
        cls.app = QApplication.instance() or QApplication([])
        apply_theme(cls.app)

    def test_text_stays_readable_across_normal_selected_and_disabled_states(self):
        from dndgm4.theme import COLORS
        for foreground, background in (
            ("text", "window"), ("text", "panel"), ("text", "input"),
            ("muted", "panel"), ("muted", "sidebar"), ("accent", "raised"),
            ("selected_text", "primary"), ("selected_text", "primary_hover"),
            ("selected_text", "selection"), ("disabled_text", "disabled"),
            ("tooltip_text", "tooltip"),
        ):
            with self.subTest(foreground=foreground, background=background):
                self.assertGreaterEqual(contrast_ratio(COLORS[foreground], COLORS[background]), 4.5)

    def test_transient_native_controls_receive_a_readable_dark_palette(self):
        from PyQt6.QtGui import QPalette
        palette = self.app.palette()
        for group in (QPalette.ColorGroup.Active, QPalette.ColorGroup.Inactive,
                      QPalette.ColorGroup.Disabled):
            for foreground, background in (
                (QPalette.ColorRole.WindowText, QPalette.ColorRole.Window),
                (QPalette.ColorRole.Text, QPalette.ColorRole.Base),
                (QPalette.ColorRole.ButtonText, QPalette.ColorRole.Button),
                (QPalette.ColorRole.HighlightedText, QPalette.ColorRole.Highlight),
            ):
                with self.subTest(group=group, foreground=foreground):
                    self.assertGreaterEqual(contrast_ratio(
                        palette.color(group, foreground).name(),
                        palette.color(group, background).name()), 4.5)
        self.assertLess(palette.window().color().lightness(), 20)

    def test_keyboard_focus_is_visible_on_selected_and_action_buttons(self):
        from PyQt6.QtCore import Qt
        from PyQt6.QtWidgets import QDialog, QPushButton, QVBoxLayout
        from dndgm4.theme import COLORS
        dialog = QDialog()
        layout = QVBoxLayout(dialog)
        try:
            for name in ("navButton", "primaryButton", "dangerButton"):
                button = QPushButton("Prepare the next session")
                button.setObjectName(name)
                if name == "navButton":
                    button.setCheckable(True)
                    button.setChecked(True)
                layout.addWidget(button)
            dialog.show()
            for button in dialog.findChildren(QPushButton):
                with self.subTest(button=button.objectName()):
                    button.setFocus(Qt.FocusReason.TabFocusReason)
                    self.app.processEvents()
                    self.assertTrue(button.hasFocus())
                    pixels = button.grab().toImage()
                    focus_pixels = sum(
                        pixels.pixelColor(x, y).name() == COLORS["focus"]
                        for y in range(pixels.height()) for x in range(pixels.width())
                    )
                    self.assertGreater(focus_pixels, button.width())
        finally:
            dialog.close()

    def test_checked_checkbox_draws_a_glyph_without_relying_on_color(self):
        from importlib.resources import files
        from PyQt6.QtWidgets import QCheckBox
        from dndgm4.theme import COLORS
        self.assertTrue(files("dndgm4").joinpath("assets", "checkmark.svg").is_file())
        checkbox = QCheckBox("Archived campaign")
        checkbox.resize(240, 36)
        try:
            checkbox.show()
            for checked in (False, True):
                checkbox.setChecked(checked)
                self.app.processEvents()
                pixels = checkbox.grab().toImage()
                # Only inspect the indicator; label text cannot satisfy this.
                glyph_pixels = sum(
                    pixels.pixelColor(x, y).name() == COLORS["selected_text"]
                    for y in range(pixels.height()) for x in range(23)
                )
                if checked:
                    self.assertGreater(glyph_pixels, 5)
                else:
                    self.assertEqual(glyph_pixels, 0)
        finally:
            checkbox.close()


if __name__ == "__main__":
    unittest.main()
