"""Campaign world records remain typed, isolated, private, and non-mechanical."""
from contextlib import closing
from dataclasses import replace
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
import unittest

from dndgm4.campaigns import ActiveWorkspace
from dndgm4.models import Creature
from dndgm4.world import (
    KINDS, STATUSES, WorldRepository, build_world_context,
)


class WorldRepositoryTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.path = Path(self.temp.name) / "library.sqlite3"
        self.repo = WorldRepository(self.path)
        self.campaign = self.repo.campaigns.create_campaign("The Ash Road", notes="Campaign secret")
        self.other = self.repo.campaigns.create_campaign("The Glass Coast")
        self.hero = self.repo.library.save(Creature(name="Élara", kind="pc", level=3))
        self.npc = self.repo.library.save(Creature(name="The Courier", kind="npc"))

    def tearDown(self):
        self.temp.cleanup()

    def create(self, kind="quest", name="Find the courier", **kwargs):
        return self.repo.create(self.campaign.id, kind, name, **kwargs)

    def test_every_typed_entry_survives_reopen_without_other_state_changes(self):
        records = [self.create(kind, "Saved " + kind) for kind in KINDS]
        reopened = WorldRepository(self.path)
        self.assertEqual({record.id for record in reopened.list(self.campaign.id)}, {record.id for record in records})
        for record in records:
            self.assertEqual(reopened.get(record.id), record)
            self.assertEqual(record.status, STATUSES[record.kind][0])
        self.assertEqual(self.repo.campaigns.get_workspace(), ActiveWorkspace())
        self.assertEqual(self.repo.library.get(self.hero.id), self.hero)
        self.assertEqual(self.repo.library.get(self.npc.id), self.npc)

    def test_campaign_search_type_status_and_archive_filters_compose(self):
        first = self.create(summary="A 100% reliable clue", dm_notes="The cellar conceals a cipher")
        second = self.create("quest", "The bridge", status="completed", details={"objectives": "Find the sigil"})
        location = self.create("location", "Old Crossing")
        self.repo.create(self.other.id, "quest", "Find the courier")
        self.assertEqual(self.repo.list(self.campaign.id, query="cipher"), [first])
        self.assertEqual(self.repo.list(self.campaign.id, query="100%"), [first])
        self.assertEqual(self.repo.list(self.campaign.id, query="_"), [])
        self.assertEqual(self.repo.list(self.campaign.id, kind="quest", status="completed", query="sigil"), [second])
        archived = self.repo.set_archived(first.id, True)
        self.assertNotIn(archived.id, {r.id for r in self.repo.list(self.campaign.id)})
        self.assertEqual(self.repo.list(self.campaign.id, query="cellar", include_archived=True), [archived])
        restored = self.repo.set_archived(first.id, False)
        self.assertFalse(restored.archived)
        self.assertEqual(self.repo.list(self.campaign.id, kind="location"), [location])

    def test_saved_entry_keeps_campaign_and_kind_identity(self):
        record = self.create()
        for edited in (replace(record, campaign_id=self.other.id), replace(record, kind="note")):
            with self.assertRaises(ValueError):
                self.repo.save(edited)
        self.assertEqual(self.repo.get(record.id), record)

    def test_invalid_metadata_does_not_create_entries(self):
        cases = [
            {"kind": "spell", "name": "No"}, {"name": " "}, {"name": "x" * 201},
            {"name": "bad\x00name"}, {"name": "bad\ud800name"}, {"status": "invented"},
            {"summary": "x" * 20001}, {"dm_notes": False}, {"details": []},
            {"details": {"secret_unknown": "must not be silently lost"}},
        ]
        for case in cases:
            arguments = {"kind": "quest", "name": "Invalid", **case}
            with self.subTest(case=repr(case)[:120]), self.assertRaises(ValueError):
                self.repo.create(self.campaign.id, **arguments)
        self.assertEqual(self.repo.list(self.campaign.id), [])

    def test_typed_numbers_time_and_references_reject_invalid_values(self):
        cases = [
            ("event", {"day": True}), ("event", {"day": -1}),
            ("event", {"time": "24:00"}), ("event", {"time": "8:00"}),
            ("event", {"duration_minutes": 52560001}),
            ("item", {"quantity": 1.5}), ("item", {"quantity": -1}),
            ("item", {"unit_value_gp": "0.001"}), ("item", {"unit_value_gp": "NaN"}),
            ("item", {"unit_value_gp": 0.1}), ("item", {"unit_weight_lb": "-1"}),
            ("reward", {"xp": "100"}), ("reward", {"gp": "1000000001"}),
            ("quest", {"assigned_ids": "all"}), ("quest", {"assigned_ids": ["missing"]}),
            ("faction", {"contacts_ids": [self.npc.id] * 251}),
        ]
        for kind, details in cases:
            with self.subTest(kind=kind, details=details), self.assertRaises(ValueError):
                self.create(kind, details=details)
        self.assertEqual(self.repo.list(self.campaign.id), [])

    def test_typed_campaign_entries_keep_precise_values_and_library_references(self):
        quest = self.create(details={"objectives": "Find the courier", "assigned_ids": [self.hero.id, self.hero.id, self.npc.id]})
        self.assertEqual(quest.details["assigned_ids"], [self.hero.id, self.npc.id])
        item = self.create("item", "Silver dust", details={"quantity": 3, "unit_value_gp": "25.50",
                                                           "unit_weight_lb": "0.125", "owner_ids": [self.hero.id],
                                                           "container": "Shared component pouch"})
        self.assertEqual(item.details["unit_value_gp"], "25.5")
        self.assertEqual(item.details["unit_weight_lb"], "0.125")
        event = self.create("event", "Council meeting", details={"day": 12, "time": "08:05", "duration_minutes": 90})
        self.assertEqual(event.details["time"], "08:05")
        self.create("reward", "Courier rescued", status="recorded",
                    details={"xp": 500, "gp": "100.01", "recipient_ids": [self.hero.id]})
        self.assertEqual(self.repo.library.get(self.hero.id), self.hero)
        self.assertEqual(self.repo.library.get(self.npc.id), self.npc)

    def test_route_endpoints_must_be_locations_owned_by_this_campaign(self):
        home = self.create("location", "South Gate")
        target = self.create("location", "Old Bridge")
        elsewhere = self.repo.create(self.other.id, "location", "Foreign harbor")
        quest = self.create()
        route = self.create("route", "Gate to Bridge", details={"from_id": home.id, "to_id": target.id,
                                                                 "distance_miles": "12.25", "pace": "On foot"})
        self.assertEqual(route.details["to_id"], target.id)
        for identity in (elsewhere.id, quest.id, "missing"):
            with self.subTest(identity=identity), self.assertRaises(ValueError):
                self.create("route", details={"from_id": identity})

    def test_archived_library_references_remain_explicit_and_preserved(self):
        archived = self.repo.library.save(replace(self.npc, archived=True))
        faction = self.create("faction", "The Watch", details={"contacts_ids": [archived.id]})
        edited = self.repo.save(replace(faction, dm_notes="The contact retired."))
        self.assertEqual(edited.details["contacts_ids"], [archived.id])
        self.assertEqual(self.repo.library.get(archived.id), archived)

    def test_relationships_are_directed_and_cannot_cross_campaigns(self):
        quest = self.create()
        location = self.create("location", "Bridge")
        foreign = self.repo.create(self.other.id, "location", "Tower")
        link = self.repo.create_link(self.campaign.id, quest.id, location.id, "takes place at", "Secret entrance")
        self.assertEqual(self.repo.list_links(self.campaign.id, quest.id), [link])
        self.assertEqual(self.repo.list_links(self.campaign.id, location.id), [link])
        for source, target in ((quest.id, foreign.id), (foreign.id, quest.id), (quest.id, quest.id)):
            with self.assertRaises(ValueError):
                self.repo.create_link(self.campaign.id, source, target, "invalid")
        with self.assertRaises(ValueError):
            self.repo.create_link(self.campaign.id, quest.id, location.id, "takes place at")
        with self.assertRaises(ValueError):
            self.repo.list_links(self.other.id, quest.id)
        with self.assertRaises(ValueError):
            self.repo.delete_link(link.id, campaign_id=self.other.id)
        self.assertEqual(self.repo.list_links(self.campaign.id), [link])
        self.repo.delete_link(link.id, campaign_id=self.campaign.id)
        self.assertEqual(self.repo.list_links(self.campaign.id), [])

    def test_corrupt_cross_campaign_relationship_is_reported(self):
        quest = self.create()
        foreign = self.repo.create(self.other.id, "note", "Foreign secret")
        with closing(sqlite3.connect(self.path)) as db:
            db.execute("INSERT INTO world_links(id,campaign_id,source_id,target_id,relation) VALUES(?,?,?,?,?)",
                       ("corrupt", self.campaign.id, quest.id, foreign.id, "broken"))
            db.commit()
        with self.assertRaisesRegex(ValueError, "crosses campaign"):
            self.repo.list_links(self.campaign.id)

    def test_player_handout_preview_and_export_never_include_other_fields(self):
        handout = self.create("handout", "Secret ambush title", summary="Secret editorial summary",
                              dm_notes="The courier is a shapeshifter", details={"player_text": "Meet me at the old bridge.\n— Élara"})
        location = self.create("location", "Hidden cellar")
        self.repo.create_link(self.campaign.id, handout.id, location.id, "conceals", "Private relationship")
        expected = "Meet me at the old bridge.\n— Élara"
        self.assertEqual(self.repo.player_handout(handout.id), expected)
        target = Path(self.temp.name) / "handout.txt"
        self.repo.export_player_handout(handout.id, target)
        self.assertEqual(target.read_text(encoding="utf-8"), expected)
        with self.assertRaises(ValueError):
            self.repo.export_player_handout(handout.id, self.path)
        blank = self.create("handout", "Blank", summary="Never use this as a fallback", dm_notes="Nor this")
        self.assertEqual(self.repo.player_handout(blank.id), "")
        with self.assertRaises(ValueError):
            self.repo.export_player_handout(blank.id, target)
        self.assertEqual(target.read_text(encoding="utf-8"), expected)
        with self.assertRaises(ValueError):
            self.repo.player_handout(location.id)

    def test_invalid_save_and_sql_error_preserve_original_entry(self):
        record = self.create("item", details={"quantity": 2})
        with self.assertRaises(ValueError):
            self.repo.save(replace(record, name="Must not persist", details_json='{"quantity":-1}'))
        self.assertEqual(self.repo.get(record.id), record)
        with closing(sqlite3.connect(self.path)) as db:
            db.execute("CREATE TRIGGER world_update_failure BEFORE UPDATE ON world_records "
                       "BEGIN SELECT RAISE(ABORT, 'Interrupted'); END")
            db.commit()
        with self.assertRaises(sqlite3.Error):
            self.repo.save(replace(record, name="Must not persist"))
        self.assertEqual(self.repo.get(record.id), record)

    def test_corrupt_stored_details_are_not_overwritten_by_read_or_archive(self):
        record = self.create("item")
        for raw in ('{"quantity":true}', '{"quantity":1,"quantity":2}', '{"quantity":NaN}', '[]'):
            with closing(sqlite3.connect(self.path)) as db:
                db.execute("UPDATE world_records SET details_json=? WHERE id=?", (raw, record.id))
                db.commit()
            with self.subTest(raw=raw):
                with self.assertRaises(ValueError):
                    self.repo.get(record.id)
                with self.assertRaises(ValueError):
                    self.repo.set_archived(record.id, True)
                with closing(sqlite3.connect(self.path)) as db:
                    self.assertEqual(db.execute("SELECT details_json,archived FROM world_records WHERE id=?", (record.id,)).fetchone(), (raw, 0))

    def test_backup_contains_world_records_and_relationships(self):
        first = self.create()
        second = self.create("location", "Bridge")
        link = self.repo.create_link(self.campaign.id, first.id, second.id, "located at")
        target = Path(self.temp.name) / "backup.sqlite3"
        self.repo.library.backup(target)
        reopened = WorldRepository(target)
        self.assertEqual(reopened.get(first.id), first)
        self.assertEqual(reopened.list_links(self.campaign.id), [link])

    def test_context_is_explicit_complete_bounded_and_read_only(self):
        record = self.create(dm_notes="Hidden motive", details={"objectives": "Question the courier", "assigned_ids": [self.npc.id]})
        context = build_world_context(self.repo, record.id)
        self.assertIn("Hidden motive", context)
        self.assertIn("Question the courier", context)
        self.assertIn("their records are not loaded", context)
        self.assertIn("DM-only", context)
        self.assertNotIn("Campaign secret", context)
        with self.assertRaisesRegex(ValueError, "No saved data was shortened"):
            build_world_context(self.repo, record.id, max_chars=10)
        self.assertEqual(self.repo.get(record.id), record)
        self.assertEqual(self.repo.campaigns.get_workspace(), ActiveWorkspace())
        self.assertEqual(self.repo.library.get(self.npc.id), self.npc)


if __name__ == "__main__":
    unittest.main()
