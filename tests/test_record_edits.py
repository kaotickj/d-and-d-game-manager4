"""An older edit must never erase XP, spell plans or another saved change."""
from dataclasses import replace
import json
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
import unittest

from dndgm4.models import Creature
from dndgm4.record_edits import save_reviewed_record
from dndgm4.storage import CreatureRepository


class ReviewedRecordEditTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.repo = CreatureRepository(Path(self.temp.name) / "library.sqlite3")
        self.original = self.repo.save(Creature(name="Ember", character_class="Wizard", level=1,
            sheet_json=json.dumps({"experience_points": 0, "spell_progression": {"Wizard": {"revision": 1}}})))

    def tearDown(self):
        self.temp.cleanup()

    def test_same_second_xp_change_invalidates_editor_baseline(self):
        draft = replace(self.original, notes="Edited background")
        other_sheet = json.loads(self.original.sheet_json)
        other_sheet["experience_points"] = 300
        latest = self.repo.save(replace(self.original, sheet_json=json.dumps(other_sheet)))
        # Content comparison protects edits even if SQLite timestamps have the
        # same one-second value for both commits.
        with self.assertRaisesRegex(ValueError, "changed while"):
            save_reviewed_record(self.repo, self.original, draft)
        self.assertEqual(self.repo.get(self.original.id), latest)
        self.assertEqual(draft.notes, "Edited background")

    def test_reviewed_edit_preserves_identity_metadata_and_commits(self):
        draft = replace(self.original, name="Ember of the Coast", notes="Edited background")
        saved = save_reviewed_record(self.repo, self.original, draft)
        self.assertEqual(saved.name, draft.name)
        self.assertEqual(saved.sheet_json, self.original.sheet_json)
        self.assertEqual(saved.created_at, self.original.created_at)
        self.assertEqual(saved.id, self.original.id)

    def test_failed_sql_rolls_back_and_deleted_or_replaced_identity_is_refused(self):
        draft = replace(self.original, notes="Keep this draft")
        with self.repo._connection() as db:
            db.execute("CREATE TRIGGER fail_edit BEFORE UPDATE ON creatures BEGIN SELECT RAISE(ABORT, 'failure'); END")
        with self.assertRaises(sqlite3.Error):
            save_reviewed_record(self.repo, self.original, draft)
        self.assertEqual(self.repo.get(self.original.id), self.original)
        with self.assertRaises(ValueError):
            save_reviewed_record(self.repo, self.original, replace(draft, id="other"))
        with self.repo._connection() as db:
            db.execute("DROP TRIGGER fail_edit")
            db.execute("DELETE FROM creatures WHERE id=?", (self.original.id,))
        with self.assertRaisesRegex(ValueError, "changed while"):
            save_reviewed_record(self.repo, self.original, draft)
