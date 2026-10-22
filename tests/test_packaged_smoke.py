"""Release checks use real rendering/recovery and fail on missing capabilities."""
from contextlib import closing
from importlib.util import find_spec
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import Mock, patch


class SmokeImportTests(unittest.TestCase):
    def test_import_does_not_create_gui_or_import_production_models(self):
        result = subprocess.run([sys.executable, "-c", "import sys; import dndgm4.packaged_smoke; "
            "assert not any(k.startswith('PyQt6') for k in sys.modules); "
            "assert 'dndgm4.storage' not in sys.modules; "
            "assert 'dndgm4.ui' not in sys.modules"], capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)


@unittest.skipUnless(find_spec("PyQt6"), "PyQt6 is not installed")
class PackagedSmokeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        from PyQt6.QtWidgets import QApplication
        from dndgm4.theme import apply_theme
        cls.app = QApplication.instance() or QApplication([])
        apply_theme(cls.app)

    def setUp(self):
        self.temp = TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.report_path = self.root / "acceptance.json"
        self.previous_quit = self.app.quitOnLastWindowClosed()

    def tearDown(self):
        self.assertEqual(self.app.quitOnLastWindowClosed(), self.previous_quit)
        self.app.processEvents()
        self.temp.cleanup()

    def read_report(self):
        return json.loads(self.report_path.read_text(encoding="utf-8"))

    def test_real_desks_migration_recovery_and_rendering_are_isolated(self):
        from PyQt6.QtGui import QImage
        from PyQt6.QtWidgets import QApplication
        from dndgm4.packaged_smoke import run_packaged_smoke
        with (patch("dndgm4.storage.default_database_path", side_effect=AssertionError("user library touched")),
              patch("dndgm4.ui.QSettings", side_effect=AssertionError("preferences touched")),
              patch("urllib.request.urlopen", side_effect=AssertionError("network requested")),
              patch("socket.create_connection", side_effect=AssertionError("network requested"))):
            self.assertEqual(run_packaged_smoke(self.report_path), 0)
        report = self.read_report()
        self.assertEqual(report["status"], "passed", report["errors"])
        from dndgm4 import __version__
        self.assertEqual(report["app_version"], __version__)
        self.assertEqual(report["errors"], [])
        self.assertIs(QApplication.instance(), self.app)
        checks = {check["name"]: check for check in report["checks"]}
        required = {"packaged_artwork_and_svg", "create_core_v3_fixture", "v3_to_current_migration",
            "new_campaign_tools_saved_state", "main_window_desktop", "main_window_830x540",
            "render_campaign", "render_world", "render_map", "render_player-map", "render_time",
            "render_resources", "render_reviewed-drafts", "render_handouts", "render_player-handout",
            "render_spells", "render_multiclass", "complete_backup", "restore_to_new_folder",
            "reopened_restored_core_records", "restored_campaign_tools_and_assets", "restart_restored_main_window"}
        self.assertEqual(set(checks), required)
        self.assertTrue(all(check["status"] == "passed" for check in checks.values()))
        font = checks["packaged_artwork_and_svg"]["details"]["font"]
        self.assertEqual(font["probe"], "D&D Game Manager 4")
        self.assertTrue(font["resolved_font_family"])
        self.assertTrue(font["backend"])
        self.assertTrue(font["qt_version"])
        self.assertTrue(font["pyqt_version"])
        self.assertEqual(font["application_font_family"], self.app.font().family())
        self.assertTrue(all(font["glyph_indexes"][index] > 0
                           for index, character in enumerate(font["probe"]) if not character.isspace()))
        self.assertEqual(report["qt"]["backend"], self.app.platformName())
        self.assertEqual(checks["main_window_830x540"]["details"]["size"], [830, 540])
        self.assertEqual(len(report["screenshots"]), 14)
        for filename in report["screenshots"]:
            path = Path(filename)
            self.assertEqual(path.parent, self.root / "acceptance-screenshots")
            self.assertFalse(QImage(str(path)).isNull(), filename)
        folder = Path(report["temporary_data_path"])
        self.assertEqual(folder.parent, self.root)
        self.assertFalse(folder.exists())
        self.assertTrue(report["temporary_data_removed"])
        self.assertFalse(any(widget.isVisible() for widget in self.app.topLevelWidgets()))
        self.assertFalse(list(self.root.glob("**/*.sqlite3")))

    def test_original_fixture_is_v3_and_migration_preserves_exact_state(self):
        from dndgm4.packaged_smoke import _create_v3_fixture, _verify_core
        from dndgm4.storage import CreatureRepository, SCHEMA_VERSION
        path = self.root / "library.sqlite3"
        expected = _create_v3_fixture(path)
        with closing(sqlite3.connect(path)) as db, db:
            self.assertEqual(db.execute("PRAGMA user_version").fetchone()[0], 3)
            tables = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            self.assertNotIn("maps", tables)
            self.assertNotIn("world_records", tables)
        result = _verify_core(CreatureRepository(path), expected)
        self.assertEqual(result["schema_version"], SCHEMA_VERSION)
        with closing(sqlite3.connect(path)) as db, db:
            db.execute("UPDATE sessions SET recap='lost recap'")
        with self.assertRaisesRegex(RuntimeError, "Session metadata changed"):
            _verify_core(CreatureRepository(path), expected)

    def test_missing_packaged_artwork_fails_closed(self):
        from PyQt6.QtGui import QPixmap
        from dndgm4.packaged_smoke import run_packaged_smoke
        with patch("dndgm4.artwork.load_artwork", return_value=QPixmap()):
            self.assertEqual(run_packaged_smoke(self.report_path), 1)
        report = self.read_report()
        self.assertEqual(report["status"], "failed")
        self.assertEqual(report["checks"][0]["status"], "failed")
        self.assertIn("could not be decoded", report["errors"][0]["error"])
        self.assertEqual(report["screenshots"], [])

    def test_missing_svg_image_plugin_fails_closed(self):
        from dndgm4.packaged_smoke import run_packaged_smoke
        with patch("PyQt6.QtGui.QImageReader.supportedImageFormats", return_value=[b"png", b"jpeg"]):
            self.assertEqual(run_packaged_smoke(self.report_path), 1)
        report = self.read_report()
        self.assertEqual(report["status"], "failed")
        self.assertIn("SVG image plugin is unavailable", report["errors"][0]["error"])

    def test_invalid_application_font_fails_before_any_capture(self):
        from dndgm4.packaged_smoke import run_packaged_smoke
        raw_font = Mock()
        raw_font.isValid.return_value = False
        with patch("PyQt6.QtGui.QRawFont.fromFont", return_value=raw_font):
            self.assertEqual(run_packaged_smoke(self.report_path), 1)
        report = self.read_report()
        self.assertEqual(report["status"], "failed")
        self.assertEqual(report["checks"][0]["status"], "failed")
        self.assertIn("application font is invalid", report["errors"][0]["error"])
        self.assertEqual(report["qt"]["application_font_family"], self.app.font().family())
        self.assertEqual(report["qt"]["backend"], self.app.platformName())
        self.assertTrue(report["qt"]["qt_version"])
        self.assertTrue(report["qt"]["pyqt_version"])
        self.assertEqual(report["screenshots"], [])
        raw_font.glyphIndexesForString.assert_not_called()

    def test_valid_font_with_missing_ascii_glyphs_cannot_pass(self):
        from dndgm4.packaged_smoke import run_packaged_smoke
        raw_font = Mock()
        raw_font.isValid.return_value = True
        # A font object alone is insufficient: one missing non-space glyph
        # must reject the report even when every other ASCII glyph resolves.
        glyphs = [23] * len("D&D Game Manager 4")
        glyphs[1] = 0
        raw_font.glyphIndexesForString.return_value = glyphs
        with patch("PyQt6.QtGui.QRawFont.fromFont", return_value=raw_font):
            self.assertEqual(run_packaged_smoke(self.report_path), 1)
        report = self.read_report()
        self.assertEqual(report["status"], "failed")
        self.assertIn("missing ASCII title glyphs", report["errors"][0]["error"])
        self.assertEqual(report["screenshots"], [])
        raw_font.glyphIndexesForString.assert_called_once_with("D&D Game Manager 4")

    def test_restore_failure_cannot_be_reported_as_a_pass(self):
        from dndgm4.packaged_smoke import run_packaged_smoke
        with patch("dndgm4.recovery.restore_backup", side_effect=ValueError("checksum mismatch fixture")):
            self.assertEqual(run_packaged_smoke(self.report_path), 1)
        report = self.read_report()
        self.assertEqual(report["status"], "failed")
        self.assertEqual(report["checks"][-1]["name"], "restore_to_new_folder")
        self.assertEqual(report["checks"][-1]["status"], "failed")
        self.assertIn("checksum mismatch", report["errors"][0]["error"])
        self.assertNotIn("restart_restored_main_window", {item["name"] for item in report["checks"]})
        self.assertTrue(report["temporary_data_removed"])
        self.assertFalse(Path(report["temporary_data_path"]).exists())

    def test_existing_library_and_report_are_preserved(self):
        from dndgm4.packaged_smoke import run_packaged_smoke
        database = self.root / "library.sqlite3"
        with closing(sqlite3.connect(database)) as db, db:
            db.execute("CREATE TABLE saved_game (name TEXT)")
            db.execute("INSERT INTO saved_game VALUES('Keep this campaign')")
        original = database.read_bytes()
        self.assertEqual(run_packaged_smoke(database), 1)
        self.assertEqual(database.read_bytes(), original)
        self.report_path.write_text("Keep the earlier acceptance evidence", encoding="utf-8")
        self.assertEqual(run_packaged_smoke(self.report_path), 1)
        self.assertEqual(self.report_path.read_text(), "Keep the earlier acceptance evidence")
        self.assertFalse((self.root / "acceptance-screenshots").exists())
        self.assertFalse(list(self.root.glob("dndgm4-smoke-*")))

    def test_report_symlink_never_replaces_its_target(self):
        from dndgm4.packaged_smoke import run_packaged_smoke
        target = self.root / "current_scene.json"
        target.write_text('{"private": "saved scene"}', encoding="utf-8")
        try:
            self.report_path.symlink_to(target)
        except OSError as exc:
            self.skipTest(f"Symbolic links unavailable: {exc}")
        self.assertEqual(run_packaged_smoke(self.report_path), 1)
        self.assertTrue(self.report_path.is_symlink())
        self.assertEqual(target.read_text(), '{"private": "saved scene"}')
        self.assertFalse((self.root / "acceptance-screenshots").exists())

    def test_colliding_screenshot_output_is_preserved_without_report_write(self):
        from dndgm4.packaged_smoke import run_packaged_smoke
        destination = self.root / "acceptance-screenshots"
        destination.mkdir()
        saved = destination / "main-desktop.png"
        saved.write_bytes(b"Preserve an existing user image")
        self.assertEqual(run_packaged_smoke(self.report_path), 1)
        self.assertFalse(self.report_path.exists())
        self.assertEqual(saved.read_bytes(), b"Preserve an existing user image")
        self.assertFalse(list(self.root.glob("dndgm4-smoke-*")))


if __name__ == "__main__":
    unittest.main()
