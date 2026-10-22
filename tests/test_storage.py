"""Database tests run without requiring a Qt display or PyQt installation."""
from dataclasses import replace
from contextlib import closing
from pathlib import Path
from tempfile import TemporaryDirectory
import sqlite3
import json
import unittest

from dndgm4.models import Creature
from dndgm4.storage import CreatureRepository


class CreatureRepositoryTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = TemporaryDirectory()
        self.path = Path(self.temp_dir.name) / "library.sqlite3"
        self.repo = CreatureRepository(self.path)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_persistence(self):
        c = self.repo.save(Creature(
            name="Alara", kind="pc", race_type="Elf",
            character_class="Ranger", level=4, strength=14))
        m = self.repo.save(Creature(
            name="Cave Troll", kind="monster",
            challenge_rating="5", max_hit_points=63))
        reopened = CreatureRepository(self.path)
        self.assertEqual(reopened.get(c.id).strength, 14)
        self.assertEqual(reopened.get(m.id).max_hit_points, 63)
        self.assertNotEqual(c.id, m.id)

    def test_search_and_type_filter(self):
        self.repo.save(Creature(name="Orc Captain", kind="monster"))
        self.repo.save(Creature(name="Orc Scout", kind="npc"))
        self.repo.save(Creature(name="Ayla", kind="pc", notes="Friend of the orcs"))
        self.assertEqual(len(self.repo.list(query="orc")), 3)
        self.assertEqual(len(self.repo.list(query="orc", kind="monster")), 1)
        self.assertEqual(self.repo.list(query="%"), [])
        self.assertEqual(len(self.repo.list(kind="pc")), 1)

    def test_edit_duplicate_and_archive(self):
        first = self.repo.save(Creature(name="Goblin", kind="monster", max_hit_points=6))
        changed = self.repo.save(replace(first, max_hit_points=9))
        duplicate = self.repo.save(changed.duplicate())
        self.assertNotEqual(first.id, duplicate.id)
        self.assertEqual(self.repo.get(first.id).max_hit_points, 9)
        self.assertEqual(self.repo.get(duplicate.id).name, "Goblin (Copy)")
        self.assertTrue(self.repo.set_archived(first.id, True))
        self.assertEqual(len(self.repo.list()), 1)
        self.assertEqual(len(self.repo.list(include_archived=True)), 2)
        self.assertTrue(self.repo.set_archived(first.id, False))
        self.assertEqual(len(self.repo.list()), 2)

    def test_validation(self):
        for bad in (
            Creature(name="  "), Creature(name="No", kind="dragon"),
            Creature(name="No", level=-1),
            Creature(name="No", strength=100),
        ):
            with self.subTest(bad=bad):
                with self.assertRaises(ValueError):
                    self.repo.save(bad)
        self.assertEqual(self.repo.list(), [])

    def test_deeply_nested_sheet_is_a_validation_error_and_preserves_the_library(self):
        saved = self.repo.save(Creature(name="Keep this hero"))
        nested = '{"data":' + '[' * 20000 + '0' + ']' * 20000 + '}'
        with self.assertRaisesRegex(ValueError, "valid JSON"):
            self.repo.save(replace(saved, sheet_json=nested))
        self.assertEqual(self.repo.get(saved.id), saved)

    def test_refuse_newer_schema(self):
        with closing(sqlite3.connect(self.path)) as db:
            db.execute("PRAGMA user_version = 99")
            db.commit()
        with self.assertRaises(RuntimeError):
            CreatureRepository(self.path)

    def test_reviewed_save_rejects_changed_or_deleted_baseline_without_lost_updates(self):
        baseline = self.repo.save(Creature(name="Starling"))
        candidate = replace(baseline, name="Reviewed name")
        saved = self.repo.save_if_unchanged(candidate, baseline)
        self.assertEqual(saved.name, "Reviewed name")
        later = self.repo.save(replace(saved, sheet_json='{"experience_points": 500}'))
        with self.assertRaisesRegex(ValueError, "draft was open"):
            self.repo.save_if_unchanged(replace(saved, name="Stale edit"), saved)
        self.assertEqual(self.repo.get(saved.id), later)
        with self.repo._connection() as db:
            db.execute("DELETE FROM creatures WHERE id=?", (saved.id,))
        with self.assertRaises(ValueError):
            self.repo.save_if_unchanged(candidate, baseline)
        self.assertIsNone(self.repo.get(saved.id))

    def test_additive_campaign_tools_migration_rolls_back_as_one_transaction(self):
        from unittest.mock import patch
        from dndgm4.storage import SCHEMA_VERSION
        original = self.repo.save(Creature(name="Legacy hero"))
        old_tables = {"creatures", "campaigns", "campaign_members", "sessions", "encounters", "workspace",
                      "world_records", "world_links", "maps", "campaign_clock", "time_changes",
                      "resource_operations", "resource_ledger"}
        with closing(sqlite3.connect(self.path)) as db:
            for (name,) in db.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall():
                if name not in old_tables and not name.startswith('sqlite_'):
                    db.execute('DROP TABLE "' + name.replace('"','""') + '"')
            db.execute("PRAGMA user_version=5")
            db.commit()
        def interrupted(db):
            db.execute("CREATE TABLE migration_probe (id TEXT)")
            raise sqlite3.OperationalError("Interrupted resource migration")
        with patch('dndgm4.resources.ensure_schema',side_effect=interrupted):
            with self.assertRaises(sqlite3.OperationalError):
                CreatureRepository(self.path)
        with closing(sqlite3.connect(self.path)) as db:
            self.assertEqual(db.execute("PRAGMA user_version").fetchone()[0],5)
            self.assertFalse(db.execute("SELECT name FROM sqlite_master WHERE name IN ('migration_probe','campaign_time_settings')").fetchall())
        reopened = CreatureRepository(self.path)
        self.assertEqual(reopened.get(original.id),original)
        with reopened._connection() as db:
            self.assertEqual(db.execute("PRAGMA user_version").fetchone()[0],SCHEMA_VERSION)

    def test_backup_is_independent_and_preserves_archived_sheets(self):
        saved = self.repo.save(Creature(name="Élara", archived=True,
                                       sheet_json='{"level": 4}'))
        destination = self.path.parent / "backup.sqlite3"
        self.repo.backup(destination)
        self.repo.save(replace(saved, name="Changed"))
        restored = CreatureRepository(destination).get(saved.id)
        self.assertEqual(restored, saved)

    def test_export_includes_all_records_and_metadata(self):
        saved = self.repo.save(Creature(name="Élara", archived=True,
                                       sheet_json='{"level": 4}'))
        destination = self.path.parent / "export.json"
        self.assertEqual(self.repo.export_json(destination), 1)
        payload = json.loads(destination.read_text(encoding="utf-8"))
        self.assertEqual(payload["format"], "dndgm4-library")
        self.assertEqual(payload["version"], 1)
        self.assertEqual(payload["creatures"][0]["id"], saved.id)
        self.assertEqual(payload["creatures"][0]["sheet_json"], saved.sheet_json)
        self.assertTrue(payload["creatures"][0]["archived"])

    def test_outputs_cannot_replace_live_database_or_hardlink(self):
        self.repo.save(Creature(name="Protected"))
        alias = self.path.parent / "alias.sqlite3"
        alias.hardlink_to(self.path)
        for destination in (self.path, alias):
            for operation in (self.repo.backup, self.repo.export_json):
                with self.assertRaises(ValueError):
                    operation(destination)
        self.assertEqual(self.repo.list()[0].name, "Protected")

    def test_failed_export_preserves_previous_file_and_cleans_staging(self):
        from unittest.mock import patch
        destination = self.path.parent / "export.json"
        destination.write_text("previous", encoding="utf-8")
        with patch("dndgm4.storage.os.replace", side_effect=OSError("Disk error")):
            with self.assertRaises(OSError):
                self.repo.export_json(destination)
        self.assertEqual(destination.read_text(), "previous")
        self.assertEqual(list(self.path.parent.glob(".dndgm4-*")), [])


if __name__ == "__main__":
    unittest.main()
