"""Library transfers validate the entire batch and preserve local data on failure."""
from contextlib import closing
from dataclasses import asdict, replace
import json
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from dndgm4.library_transfer import read_library_export
from dndgm4.models import Creature
from dndgm4.storage import CreatureRepository, WRITE_COLUMNS


class LibraryTransferTests(unittest.TestCase):
    def setUp(self):
        self.temporary = TemporaryDirectory()
        self.directory = Path(self.temporary.name)
        self.source = self.directory / "export.json"
        self.repo = CreatureRepository(self.directory / "library.sqlite3")

    def tearDown(self):
        self.temporary.cleanup()

    def write_payload(self, payload):
        self.source.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    def write_records(self, records):
        self.write_payload({"format": "dndgm4-library", "version": 1,
                            "creatures": records})

    def assert_summary(self, result, *, total, added=0, skipped=0, copied=0, replaced=0):
        self.assertEqual((result.total, result.added, result.skipped,
                          result.copied, result.replaced),
                         (total, added, skipped, copied, replaced))

    def test_export_read_import_roundtrip_preserves_every_creature_field(self):
        creature = Creature(
            name="Élara 灰", id="elara-1", kind="npc", race_type="Elf",
            character_class="Wizard", level=7, challenge_rating="6",
            armor_class=18, max_hit_points=29, strength=8, dexterity=16,
            constitution=12, intelligence=19, wisdom=13, charisma=10,
            notes="Line one\nLine two — party ally", archived=True,
            sheet_json='{"spells": ["light"], "background": "Élara"}')
        saved = self.repo.save(creature)
        self.assertEqual(self.repo.export_json(self.source), 1)
        records = read_library_export(self.source)
        self.assertIsInstance(records, tuple)
        self.assertEqual(records, (saved,))
        destination = CreatureRepository(self.directory / "restored.sqlite3")
        self.assert_summary(destination.import_records(records), total=1, added=1)
        self.assertEqual(destination.get(saved.id), saved)

    def test_known_optional_fields_receive_creature_defaults(self):
        self.write_records([{"name": "Alara", "id": "alara"}])
        self.assertEqual(read_library_export(self.source),
                         (Creature(name="Alara", id="alara"),))

    def test_empty_export_and_import_are_valid(self):
        self.repo.save(Creature(name="Local"))
        self.write_records([])
        records = read_library_export(self.source)
        self.assertEqual(records, ())
        self.assert_summary(self.repo.preview_import(records), total=0)
        self.assert_summary(self.repo.import_records(records), total=0)
        self.assertEqual(len(self.repo.list()), 1)

    def test_invalid_envelopes_are_rejected(self):
        valid = {"format": "dndgm4-library", "version": 1, "creatures": []}
        for payload in (
            None, [], "text", 1, {},
            {**valid, "format": "other-library"},
            {**valid, "version": 2}, {**valid, "version": True},
            {**valid, "version": "1"}, {**valid, "version": 1.0},
            {**valid, "creatures": {}}, {**valid, "creatures": None},
            {**valid, "unexpected": "not silently discarded"},
        ):
            with self.subTest(payload=payload):
                self.write_payload(payload)
                with self.assertRaises(ValueError):
                    read_library_export(self.source)

    def test_malformed_json_and_invalid_utf8_are_rejected(self):
        for raw in (b"{", b"not JSON", b"\xff", b""):
            with self.subTest(raw=raw):
                self.source.write_bytes(raw)
                with self.assertRaises(ValueError):
                    read_library_export(self.source)

    def test_missing_file_keeps_os_error(self):
        with self.assertRaises(OSError):
            read_library_export(self.source)

    def test_duplicate_outer_json_fields_are_rejected(self):
        for raw in (
            '{"format":"dndgm4-library","version":2,"version":1,"creatures":[]}',
            '{"format":"dndgm4-library","version":1,"creatures":'
            '[{"id":"first","id":"second","name":"Alara"}]}',
        ):
            with self.subTest(raw=raw):
                self.source.write_text(raw, encoding="utf-8")
                with self.assertRaises(ValueError):
                    read_library_export(self.source)

    def test_nonfinite_outer_json_numbers_are_rejected(self):
        for value in ("NaN", "Infinity", "-Infinity"):
            with self.subTest(value=value):
                self.source.write_text(
                    '{"format":"dndgm4-library","version":1,"creatures":'
                    '[{"id":"alara","name":"Alara","level":' + value + '}]}',
                    encoding="utf-8")
                with self.assertRaises(ValueError):
                    read_library_export(self.source)

    def test_unpaired_unicode_surrogates_are_rejected(self):
        for field in ("id", "name", "notes", "sheet_json"):
            with self.subTest(field=field):
                record = {"id": "alara", "name": "Alara", field: "\ud800"}
                self.source.write_text(json.dumps(
                    {"format": "dndgm4-library", "version": 1, "creatures": [record]}),
                    encoding="utf-8")
                with self.assertRaises(ValueError):
                    read_library_export(self.source)

    def test_excessively_nested_outer_json_is_reported_as_validation_error(self):
        self.source.write_text("[" * 10000 + "0" + "]" * 10000, encoding="utf-8")
        with self.assertRaises(ValueError):
            read_library_export(self.source)

    def test_invalid_record_shapes_and_identifiers_are_rejected(self):
        for record in (
            None, [], "creature", 17, {}, {"name": "Alara"},
            {"name": "Alara", "id": ""}, {"name": "Alara", "id": "   "},
            {"name": "Alara", "id": "x" * 201},
            {"name": "Alara", "id": "alara", "unexpected": "data"},
        ):
            with self.subTest(record=record):
                self.write_records([record])
                with self.assertRaises(ValueError):
                    read_library_export(self.source)

    def test_scalar_types_are_not_coerced(self):
        record = asdict(Creature(name="Alara", id="alara"))
        string_fields = [key for key, value in record.items() if isinstance(value, str)]
        integer_fields = [key for key, value in record.items() if type(value) is int]
        cases = [(key, value) for key in string_fields for value in (None, 3, True, [])]
        cases += [(key, value) for key in integer_fields
                  for value in (None, "10", 10.0, True)]
        cases += [("archived", value) for value in (None, 0, 1, "false")]
        for key, value in cases:
            with self.subTest(field=key, value=value):
                self.write_records([{**record, key: value}])
                with self.assertRaises(ValueError):
                    read_library_export(self.source)

    def test_record_values_follow_library_validation(self):
        record = asdict(Creature(name="Alara", id="alara"))
        for key, value in (
            ("name", "  "), ("name", "x" * 201), ("kind", "dragon"),
            ("level", -1), ("level", 100), ("armor_class", -1),
            ("max_hit_points", 1000000), ("strength", 100),
            ("sheet_json", "[1, 2]"), ("sheet_json", "{"),
            ("sheet_json", '"' + "x" * 262144 + '"'),
        ):
            with self.subTest(field=key, value=str(value)[:60]):
                self.write_records([{**record, key: value}])
                with self.assertRaises(ValueError):
                    read_library_export(self.source)

    def test_duplicate_identifiers_in_one_file_are_rejected(self):
        self.write_records([{"name": "Alara", "id": "same"},
                            {"name": "Different name", "id": "same"}])
        with self.assertRaises(ValueError):
            read_library_export(self.source)

    def test_size_limit_is_applied_before_parsing(self):
        self.write_records([{"name": "Alara", "id": "alara"}])
        with patch("dndgm4.library_transfer.MAX_IMPORT_BYTES", 16):
            with self.assertRaises(ValueError):
                read_library_export(self.source)

    def test_record_count_limit_is_enforced(self):
        self.write_records([{"name": "Alara", "id": "alara"},
                            {"name": "Rowan", "id": "rowan"}])
        with patch("dndgm4.library_transfer.MAX_IMPORT_RECORDS", 1):
            with self.assertRaises(ValueError):
                read_library_export(self.source)

    def test_preview_reports_each_policy_without_saving(self):
        existing = self.repo.save(Creature(id="same", name="Local", archived=True))
        records = (Creature(id="same", name="Incoming"),
                   Creature(id="new", name="New"))
        for policy, counts in (
            ("skip", {"added": 1, "skipped": 1}),
            ("copy", {"added": 1, "copied": 1}),
            ("replace", {"added": 1, "replaced": 1}),
        ):
            with self.subTest(policy=policy):
                result = self.repo.preview_import(records, duplicates=policy)
                self.assert_summary(result, total=2, **counts)
                self.assertEqual(self.repo.list(include_archived=True), [existing])

    def test_default_skip_includes_archived_identifier_conflicts(self):
        existing = self.repo.save(Creature(id="same", name="Local", archived=True))
        result = self.repo.import_records((Creature(id="same", name="Incoming"),
                                           Creature(id="new", name="New")))
        self.assert_summary(result, total=2, added=1, skipped=1)
        self.assertEqual(self.repo.get("same"), existing)
        self.assertEqual(self.repo.get("new").name, "New")

    def test_copy_preserves_templates_and_changes_only_conflicting_ids(self):
        existing = self.repo.save(Creature(id="same", name="Local", max_hit_points=9))
        incoming = Creature(id="same", name="Incoming", kind="monster", archived=True,
                            notes="Imported", sheet_json='{"attacks": ["bite"]}')
        result = self.repo.import_records((incoming, Creature(id="new", name="New")),
                                           duplicates="copy")
        self.assert_summary(result, total=2, added=1, copied=1)
        self.assertEqual(self.repo.get("same"), existing)
        copied, = [record for record in self.repo.list(include_archived=True)
                   if record.name == "Incoming"]
        self.assertNotIn(copied.id, ("same", "new", ""))
        for key in WRITE_COLUMNS:
            self.assertEqual(getattr(copied, key), getattr(incoming, key), key)
        self.assertEqual(self.repo.get("new").name, "New")

    def test_replace_retains_local_creation_time_and_replaces_record_fields(self):
        existing = self.repo.save(Creature(id="same", name="Local", archived=True))
        with closing(sqlite3.connect(self.repo.path)) as db:
            db.execute("UPDATE creatures SET created_at = ?, updated_at = ? WHERE id = ?",
                       ("2000-01-01 00:00:00", "2000-01-01 00:00:00", existing.id))
            db.commit()
        incoming = Creature(id="same", name="Incoming", kind="npc", max_hit_points=27,
                            created_at="1990-01-01 00:00:00",
                            updated_at="1990-02-01 00:00:00")
        self.assert_summary(self.repo.import_records((incoming,), duplicates="replace"),
                            total=1, replaced=1)
        updated = self.repo.get("same")
        for key in WRITE_COLUMNS:
            self.assertEqual(getattr(updated, key), getattr(incoming, key), key)
        self.assertEqual(updated.created_at, "2000-01-01 00:00:00")
        self.assertNotEqual(updated.updated_at, "2000-01-01 00:00:00")
        self.assertNotEqual(updated.updated_at, incoming.updated_at)

    def test_new_rows_preserve_imported_timestamps(self):
        record = Creature(id="new", name="New", created_at="2000-01-01 00:00:00",
                          updated_at="2001-02-03 04:05:06")
        self.repo.import_records((record,))
        self.assertEqual(self.repo.get(record.id), record)

    def test_same_name_with_distinct_ids_is_not_a_conflict(self):
        self.repo.save(Creature(id="local", name="Goblin"))
        result = self.repo.import_records((Creature(id="incoming", name="Goblin"),))
        self.assert_summary(result, total=1, added=1)
        self.assertEqual(len(self.repo.list()), 2)

    def test_sql_failure_rolls_back_prior_replacements_and_insertions(self):
        existing = self.repo.save(Creature(id="local", name="Local"))
        with closing(sqlite3.connect(self.repo.path)) as db:
            db.execute("""CREATE TRIGGER reject_import BEFORE INSERT ON creatures
                          WHEN NEW.name = 'Rejected'
                          BEGIN SELECT RAISE(ABORT, 'test import failure'); END""")
            db.commit()
        with self.assertRaises(sqlite3.Error):
            self.repo.import_records((replace(existing, name="Changed"),
                                      Creature(id="first", name="First"),
                                      Creature(id="fail", name="Rejected")),
                                     duplicates="replace")
        self.assertEqual(self.repo.list(include_archived=True), [existing])

    def test_invalid_batch_leaves_library_unchanged(self):
        existing = self.repo.save(Creature(id="local", name="Local"))
        for bad in (Creature(id="bad", name=""), Creature(id="bad", name="Bad", level=True),
                    Creature(id="", name="Missing identifier")):
            with self.subTest(bad=bad):
                with self.assertRaises(ValueError):
                    self.repo.import_records((Creature(id="first", name="First"), bad))
                self.assertEqual(self.repo.list(include_archived=True), [existing])

    def test_direct_import_rejects_duplicate_batch_identifiers(self):
        for operation in (self.repo.preview_import, self.repo.import_records):
            with self.subTest(operation=operation.__name__):
                with self.assertRaises(ValueError):
                    operation((Creature(id="same", name="First"),
                               Creature(id="same", name="Second")))
                self.assertEqual(self.repo.list(include_archived=True), [])

    def test_invalid_duplicate_policy_is_rejected_without_saving(self):
        records = (Creature(id="first", name="First"),)
        for operation in (self.repo.preview_import, self.repo.import_records):
            with self.subTest(operation=operation.__name__):
                with self.assertRaises(ValueError):
                    operation(records, duplicates="overwrite-anything")
                self.assertEqual(self.repo.list(include_archived=True), [])


if __name__ == "__main__":
    unittest.main()
