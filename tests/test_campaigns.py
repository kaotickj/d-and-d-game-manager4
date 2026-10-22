"""Campaign storage, migrations and independent encounter snapshots."""
from contextlib import closing
from dataclasses import replace
import json
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from dndgm4.battle_advanced import AdvancedBattle
from dndgm4.battle_rules import fighter_from_record
from dndgm4.campaigns import (
    ActiveWorkspace, CampaignBattleStore, CampaignRepository, SessionSceneStore,
)
from dndgm4.models import Creature
from dndgm4.scene_context import blank_scene
from dndgm4.storage import CreatureRepository, SCHEMA_VERSION


class CampaignStorageTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.path = Path(self.temp.name) / "library.sqlite3"
        self.library = CreatureRepository(self.path)
        self.hero = self.library.save(Creature(name="Élara", max_hit_points=18,
                                              sheet_json='{"background": "Keep this"}'))
        self.repo = CampaignRepository(self.path)
        self.campaign = self.repo.create_campaign("The Hollow Road", "A missing envoy", "DM secret")
        self.session = self.repo.create_session(self.campaign.id, "The old crossing", "2026-10-22")

    def tearDown(self):
        self.temp.cleanup()

    def populated_battle(self):
        battle = AdvancedBattle(title="Bridge Watch")
        fighter = fighter_from_record(self.hero)
        battle.add(fighter)
        battle.fighters[0].hp = 6
        battle.fighters[0].initiative = 17
        battle.fighters[0].initiative_roll = 15
        battle.begin()
        battle.set_condition(fighter.uid, "Blinded", 3)
        battle.set_spell_slots(fighter.uid, 1, 3, 1)
        battle.add_effect("Bless", target_id=fighter.uid, anchor_id=fighter.uid,
                          duration=5, unit="rounds", notes="Keep effect")
        return battle

    def test_campaign_and_session_metadata_persist_and_edit(self):
        edited = self.repo.save_campaign(replace(self.campaign, name="The Long Road", notes="Keep the secret"))
        session = self.repo.save_session(replace(self.session, status="completed", notes="Found the envoy",
                                                 recap="The party rescued the envoy."))
        reopened = CampaignRepository(self.path)
        self.assertEqual(reopened.get_campaign(edited.id), edited)
        self.assertEqual(reopened.get_session(session.id), session)
        self.assertEqual(reopened.list_sessions(edited.id), [session])
        self.assertEqual(reopened.list_campaigns(), [edited])
        self.assertEqual(self.library.get(self.hero.id), self.hero)

    def test_journal_save_commits_campaign_party_and_session_together(self):
        campaign, session = self.repo.save_journal(
            campaign=replace(self.campaign, name="Edited campaign"), record_ids=[self.hero.id],
            session=replace(self.session, notes="Recorded decisions"))
        self.assertEqual(campaign.name, "Edited campaign")
        self.assertEqual(session.notes, "Recorded decisions")
        self.assertEqual(self.repo.get_campaign(campaign.id), campaign)
        self.assertEqual(self.repo.get_session(session.id), session)
        self.assertEqual(self.repo.party_ids(campaign.id), [self.hero.id])
        self.assertEqual(self.repo.save_journal(), (None, None))

    def test_invalid_journal_session_leaves_campaign_and_party_unchanged(self):
        self.repo.set_party(self.campaign.id, [self.hero.id])
        with self.assertRaises(ValueError):
            self.repo.save_journal(campaign=replace(self.campaign, name="Must not commit"),
                                   record_ids=[],
                                   session=replace(self.session, session_date="not a date"))
        self.assertEqual(self.repo.get_campaign(self.campaign.id), self.campaign)
        self.assertEqual(self.repo.party_ids(self.campaign.id), [self.hero.id])
        self.assertEqual(self.repo.get_session(self.session.id), self.session)

    def test_late_journal_sql_error_rolls_back_campaign_and_party(self):
        self.repo.set_party(self.campaign.id, [self.hero.id])
        with closing(sqlite3.connect(self.path)) as db:
            db.execute("CREATE TRIGGER fail_session_update BEFORE UPDATE ON sessions "
                       "BEGIN SELECT RAISE(ABORT, 'Journal write interrupted'); END")
            db.commit()
        with self.assertRaises(sqlite3.Error):
            self.repo.save_journal(campaign=replace(self.campaign, notes="Must not commit"),
                                   record_ids=[], session=replace(self.session, notes="New notes"))
        self.assertEqual(self.repo.get_campaign(self.campaign.id), self.campaign)
        self.assertEqual(self.repo.party_ids(self.campaign.id), [self.hero.id])
        self.assertEqual(self.repo.get_session(self.session.id), self.session)

    def test_journal_requires_roster_owner_and_consistent_session_campaign(self):
        other = self.repo.create_campaign("Other campaign")
        with self.assertRaises(ValueError):
            self.repo.save_journal(record_ids=[self.hero.id])
        with self.assertRaises(ValueError):
            self.repo.save_journal(campaign=replace(other, notes="Must not commit"),
                                   session=self.session)
        self.assertEqual(self.repo.get_campaign(other.id), other)
        self.assertEqual(self.repo.get_session(self.session.id), self.session)

    def test_session_scene_isolation_and_store_adapter(self):
        other = self.repo.create_session(self.campaign.id, "A second day")
        scene = {**blank_scene(), "title": "A bridge", "location": "East bank",
                 "record_ids": [self.hero.id]}
        store = SessionSceneStore(self.repo, self.session.id)
        store.save(scene)
        self.assertEqual(store.load(), scene)
        self.assertEqual(self.repo.load_scene(other.id), blank_scene())
        loaded = store.load()
        loaded["record_ids"].clear()
        self.assertEqual(store.load()["record_ids"], [self.hero.id])
        self.assertEqual(store.path, self.path)

    def test_encounter_snapshots_are_isolated_and_preserve_advanced_state(self):
        first = self.repo.create_encounter(self.session.id, "First")
        second = self.repo.create_encounter(self.session.id, "Second")
        original = self.populated_battle()
        store = CampaignBattleStore(self.repo, first.id)
        store.save(original)
        restored = CampaignRepository(self.path).load_battle(first.id)
        self.assertEqual(restored.snapshot(), original.snapshot())
        self.assertEqual(restored.fighters[0].hp, 6)
        self.assertTrue(restored.effects)
        self.assertTrue(restored.spell_slots)
        self.assertEqual(self.repo.get_encounter(first.id).title, original.title)
        self.assertEqual(self.repo.load_battle(second.id).fighters, [])
        restored.fighters[0].hp = 1
        self.assertEqual(store.load().fighters[0].hp, 6)
        self.assertEqual(self.library.get(self.hero.id), self.hero)

    def test_party_validation_preserves_previous_members_on_failure(self):
        self.repo.set_party(self.campaign.id, [self.hero.id, self.hero.id])
        self.assertEqual(self.repo.party_ids(self.campaign.id), [self.hero.id])
        with self.assertRaises(ValueError):
            self.repo.set_party(self.campaign.id, ["missing"])
        self.assertEqual(self.repo.party(self.campaign.id), [self.hero])
        self.library.set_archived(self.hero.id, True)
        self.assertTrue(self.repo.party(self.campaign.id)[0].archived)
        self.assertEqual(self.repo.party_ids(self.campaign.id), [self.hero.id])

    def test_foreign_keys_prevent_deleting_party_creature(self):
        self.repo.set_party(self.campaign.id, [self.hero.id])
        with self.assertRaises(sqlite3.IntegrityError):
            with self.library._connection() as db:
                db.execute("DELETE FROM creatures WHERE id=?", (self.hero.id,))
        self.assertEqual(self.repo.party(self.campaign.id), [self.hero])

    def test_dangling_party_membership_is_reported_not_omitted(self):
        self.repo.set_party(self.campaign.id, [self.hero.id])
        with closing(sqlite3.connect(self.path)) as db:
            db.execute("PRAGMA foreign_keys=OFF")
            db.execute("DELETE FROM creatures WHERE id=?", (self.hero.id,))
            db.commit()
        with self.assertRaises(ValueError):
            self.repo.party(self.campaign.id)

    def test_active_workspace_reopens_and_checks_ownership_atomically(self):
        encounter = self.repo.create_encounter(self.session.id, "Bridge")
        expected = ActiveWorkspace(self.campaign.id, self.session.id, encounter.id)
        self.assertEqual(self.repo.activate(expected.campaign_id, expected.session_id, expected.encounter_id), expected)
        self.assertEqual(CampaignRepository(self.path).get_workspace(), expected)
        other = self.repo.create_campaign("Different campaign")
        with self.assertRaises(ValueError):
            self.repo.activate(other.id, self.session.id, encounter.id)
        unrelated = self.repo.create_session(other.id, "Elsewhere")
        unrelated_encounter = self.repo.create_encounter(unrelated.id, "Other fight")
        with self.assertRaises(ValueError):
            self.repo.activate(self.campaign.id, self.session.id, unrelated_encounter.id)
        self.assertEqual(self.repo.get_workspace(), expected)
        self.assertEqual(self.repo.clear_workspace(), ActiveWorkspace())
        self.assertEqual(self.repo.get_workspace(), ActiveWorkspace())

    def test_session_can_activate_without_an_encounter(self):
        expected = ActiveWorkspace(self.campaign.id, self.session.id)
        self.assertEqual(self.repo.activate(self.campaign.id, self.session.id), expected)
        self.assertEqual(self.repo.get_workspace(), expected)
        with self.assertRaises(ValueError):
            self.repo.activate(self.campaign.id, self.session.id, None)
        self.assertEqual(self.repo.get_workspace(), expected)

    def test_archived_campaign_requires_unarchive_and_retains_sessions(self):
        self.repo.save_campaign(replace(self.campaign, archived=True))
        self.assertEqual(self.repo.list_campaigns(), [])
        self.assertEqual(len(self.repo.list_campaigns(include_archived=True)), 1)
        with self.assertRaises(ValueError):
            self.repo.activate(self.campaign.id, self.session.id)
        self.assertEqual(self.repo.list_sessions(self.campaign.id), [self.session])
        self.repo.save_campaign(self.campaign)
        self.repo.activate(self.campaign.id, self.session.id)

    def test_encounter_rename_preserves_all_combat_state(self):
        encounter = self.repo.create_encounter(self.session.id, "Old name")
        original = self.populated_battle()
        self.repo.save_battle(encounter.id, original)
        self.repo.rename_encounter(encounter.id, "The crossing")
        loaded = self.repo.load_battle(encounter.id)
        original.title = "The crossing"
        self.assertEqual(loaded.snapshot(), original.snapshot())

    def test_invalid_metadata_is_rejected_without_changes(self):
        for name in ("", "  ", None, "x" * 201):
            with self.subTest(name=str(name)[:20]):
                with self.assertRaises(ValueError):
                    self.repo.create_campaign(name)
        for day in ("tomorrow", "2026-13-01", "20261022", None, "2026-1-01"):
            with self.subTest(day=day):
                with self.assertRaises(ValueError):
                    self.repo.create_session(self.campaign.id, "Invalid day", day)
        for changed in (replace(self.session, status="finished"),
                        replace(self.session, notes=[]),
                        replace(self.session, title="")):
            with self.assertRaises(ValueError):
                self.repo.save_session(changed)
        self.assertEqual(self.repo.get_session(self.session.id), self.session)

    def test_sessions_cannot_move_between_campaigns(self):
        other = self.repo.create_campaign("Other")
        with self.assertRaises(ValueError):
            self.repo.save_session(replace(self.session, campaign_id=other.id))
        self.assertEqual(self.repo.get_session(self.session.id), self.session)

    def test_scene_byte_limit_and_bad_shape_preserve_existing_scene(self):
        original = {**blank_scene(), "title": "Keep me"}
        self.repo.save_scene(self.session.id, original)
        large = {**blank_scene(), "title": "界" * 20000, "location": "界" * 20000,
                 "scenery": "界" * 20000}
        for invalid in (None, {**blank_scene(), "record_ids": [None]}, large):
            with self.assertRaises(ValueError):
                self.repo.save_scene(self.session.id, invalid)
        self.assertEqual(self.repo.load_scene(self.session.id), original)

    def test_invalid_battle_save_preserves_prior_snapshot(self):
        encounter = self.repo.create_encounter(self.session.id, "Bridge")
        original = self.populated_battle()
        self.repo.save_battle(encounter.id, original)
        invalid = self.populated_battle()
        invalid.fighters[0].hp = "hurt"
        with self.assertRaises(ValueError):
            self.repo.save_battle(encounter.id, invalid)
        self.assertEqual(self.repo.load_battle(encounter.id).snapshot(), original.snapshot())
        with patch("dndgm4.campaigns.MAX_BATTLE_BYTES", 10):
            with self.assertRaises(ValueError):
                self.repo.save_battle(encounter.id, original)

    def test_corrupt_scene_and_battle_are_not_silently_replaced(self):
        encounter = self.repo.create_encounter(self.session.id, "Bridge")
        with closing(sqlite3.connect(self.path)) as db:
            db.execute("UPDATE sessions SET scene_json='broken' WHERE id=?", (self.session.id,))
            db.execute("UPDATE encounters SET battle_json='broken' WHERE id=?", (encounter.id,))
            db.commit()
        with self.assertRaises(ValueError):
            self.repo.load_scene(self.session.id)
        with self.assertRaises(ValueError):
            self.repo.load_battle(encounter.id)
        with closing(sqlite3.connect(self.path)) as db:
            self.assertEqual(db.execute("SELECT scene_json FROM sessions WHERE id=?", (self.session.id,)).fetchone()[0], "broken")

    def test_import_legacy_session_is_atomic_and_preserves_sidecar_bytes(self):
        scene = {**blank_scene(), "title": "Legacy scene", "record_ids": [self.hero.id]}
        battle = self.populated_battle()
        sidecar = self.path.with_name("current_scene.json")
        sidecar.write_text(json.dumps(scene), encoding="utf-8")
        before = sidecar.read_bytes()
        imported = self.repo.import_legacy_session(self.campaign.id, scene, battle)
        encounters = self.repo.list_encounters(imported.id)
        self.assertEqual(self.repo.load_scene(imported.id), scene)
        self.assertEqual(self.repo.load_battle(encounters[0].id).snapshot(), battle.snapshot())
        self.assertEqual(sidecar.read_bytes(), before)
        self.assertEqual(self.repo.get_workspace(), ActiveWorkspace())

    def test_import_sql_failure_rolls_back_new_session(self):
        with closing(sqlite3.connect(self.path)) as db:
            db.execute("CREATE TRIGGER fail_encounter BEFORE INSERT ON encounters "
                       "BEGIN SELECT RAISE(ABORT, 'No space'); END")
            db.commit()
        with self.assertRaises(sqlite3.Error):
            self.repo.import_legacy_session(self.campaign.id, blank_scene(), AdvancedBattle())
        self.assertEqual(self.repo.list_sessions(self.campaign.id), [self.session])

    def test_sqlite_backup_contains_campaign_scene_and_encounter_state(self):
        encounter = self.repo.create_encounter(self.session.id, "Bridge")
        battle = self.populated_battle()
        self.repo.save_battle(encounter.id, battle)
        self.repo.set_party(self.campaign.id, [self.hero.id])
        self.repo.activate(self.campaign.id, self.session.id, encounter.id)
        backup = self.path.with_name("backup.sqlite3")
        self.library.backup(backup)
        reopened = CampaignRepository(backup)
        self.assertEqual(reopened.get_workspace(), self.repo.get_workspace())
        self.assertEqual(reopened.load_battle(encounter.id).snapshot(), battle.snapshot())
        self.assertEqual(reopened.party(self.campaign.id), [self.hero])

    def test_version_two_migration_preserves_creatures_and_sidecars(self):
        path = self.path.with_name("old.sqlite3")
        original_repo = CreatureRepository(path)
        original = original_repo.save(Creature(name="Old hero", notes="Old notes", archived=True))
        with closing(sqlite3.connect(path)) as db:
            for table in ("workspace", "campaign_members", "encounters", "sessions", "campaigns"):
                db.execute("DROP TABLE " + table)
            db.execute("PRAGMA user_version=2")
            db.commit()
        sidecar = path.with_name("battle_trakker.json")
        sidecar.write_bytes(b"legacy file unchanged")
        migrated = CampaignRepository(path)
        self.assertEqual(migrated.library.get(original.id), original)
        self.assertEqual(migrated.list_campaigns(), [])
        self.assertEqual(migrated.get_workspace(), ActiveWorkspace())
        self.assertEqual(sidecar.read_bytes(), b"legacy file unchanged")
        with closing(sqlite3.connect(path)) as db:
            self.assertEqual(db.execute("PRAGMA user_version").fetchone()[0], SCHEMA_VERSION)
        self.assertEqual(CampaignRepository(path).library.get(original.id), original)

    def test_failed_campaign_schema_migration_rolls_back_new_tables(self):
        path = self.path.with_name("interrupted.sqlite3")
        old = CreatureRepository(path)
        saved = old.save(Creature(name="Keep this hero"))
        with closing(sqlite3.connect(path)) as db:
            for table in ("workspace", "campaign_members", "encounters", "sessions", "campaigns"):
                db.execute("DROP TABLE " + table)
            db.execute("PRAGMA user_version=2")
            db.commit()
        connect = sqlite3.connect

        class FailingConnection(sqlite3.Connection):
            def execute(self, sql, *args):
                if "CREATE TABLE sessions" in sql:
                    raise sqlite3.OperationalError("Simulated migration interruption")
                return super().execute(sql, *args)

        with patch("dndgm4.storage.sqlite3.connect",
                   side_effect=lambda *args, **kwargs: connect(*args, factory=FailingConnection, **kwargs)):
            with self.assertRaises(sqlite3.OperationalError):
                CreatureRepository(path)
        with closing(connect(path)) as db:
            self.assertEqual(db.execute("PRAGMA user_version").fetchone()[0], 2)
            self.assertEqual(db.execute("SELECT COUNT(*) FROM sqlite_master WHERE name='campaigns'").fetchone()[0], 0)
        recovered = CampaignRepository(path)
        self.assertEqual(recovered.library.get(saved.id), saved)
