"""Installer preservation fixture is isolated and its check cannot migrate data."""
from contextlib import closing
from hashlib import sha256
import json
from pathlib import Path
import sqlite3
import struct
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest
import zlib

SCRIPT = Path(__file__).resolve().parents[1] / "build" / "windows_upgrade_fixture.py"


class WindowsUpgradeFixtureTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name)
        self.root = self.directory / "isolated-localappdata"
        self.report = self.directory / "baseline.json"

    def run_cli(self, action):
        return subprocess.run([sys.executable, str(SCRIPT), action, str(self.root), str(self.report)],
                              text=True, capture_output=True, timeout=20)

    def seed(self):
        result = self.run_cli("seed")
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(self.report.read_text(encoding="utf-8"))

    def test_seed_and_repeated_checks_preserve_exact_schema_three_fixture(self):
        baseline = self.seed()
        self.assertEqual(baseline["schema_version"], 3)
        self.assertEqual(set(baseline["ids"]), {"hero", "campaign", "session", "encounter"})
        self.assertEqual(len(baseline["files"]), 3)
        before = {str(path): path.read_bytes() for path in self.directory.rglob("*") if path.is_file()}
        for _ in range(2):
            result = self.run_cli("check")
            self.assertEqual(result.returncode, 0, result.stderr)
        after = {str(path): path.read_bytes() for path in self.directory.rglob("*") if path.is_file()}
        self.assertEqual(after, before)
        for name, metadata in baseline["files"].items():
            payload = (self.root / name).read_bytes()
            self.assertEqual(metadata, {"size": len(payload), "sha256": sha256(payload).hexdigest()})
        png = (self.root / "DnDGameManager4/assets/installer-fixture.png").read_bytes()
        self.assertEqual(png[:8], b"\x89PNG\r\n\x1a\n")
        offset = 8
        while offset < len(png):
            size = struct.unpack(">I", png[offset:offset+4])[0]
            chunk = png[offset+4:offset+8+size]
            self.assertEqual(zlib.crc32(chunk), struct.unpack(">I", png[offset+8+size:offset+12+size])[0])
            offset += 12 + size

    def test_seed_refuses_existing_root_and_preserves_report(self):
        self.seed()
        before = self.report.read_bytes()
        result = self.run_cli("seed")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("existing ROOT", result.stderr)
        self.assertEqual(self.report.read_bytes(), before)

    def test_check_rejects_record_changes_without_mutating_database(self):
        self.seed()
        database = self.root / "DnDGameManager4" / "library.sqlite3"
        with closing(sqlite3.connect(database)) as db:
            db.execute("UPDATE creatures SET notes='installer damaged this record'")
            db.commit()
        before = database.read_bytes()
        result = self.run_cli("check")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("library.sqlite3", result.stderr)
        self.assertEqual(database.read_bytes(), before)

    def test_check_rejects_migration_without_migrating_or_repairing(self):
        self.seed()
        database = self.root / "DnDGameManager4" / "library.sqlite3"
        with closing(sqlite3.connect(database)) as db:
            db.execute("PRAGMA user_version=6")
        before = database.read_bytes()
        result = self.run_cli("check")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("schema changed", result.stderr)
        self.assertEqual(database.read_bytes(), before)

    def test_check_rejects_missing_managed_asset(self):
        self.seed()
        asset = self.root / "DnDGameManager4" / "assets" / "installer-fixture.png"
        asset.unlink()
        result = self.run_cli("check")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("installer-fixture.png", result.stderr)
        self.assertFalse(asset.exists())
