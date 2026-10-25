"""Dashboard projections use live state; quick notes cannot clobber journals."""
from contextlib import closing
from dataclasses import replace
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
import unittest

from dndgm4.battle_advanced import AdvancedBattle
from dndgm4.battle_rules import fighter_from_record
from dndgm4.campaigns import ActiveWorkspace, CampaignRepository
from dndgm4.models import Creature
from dndgm4.run_session import append_session_note, build_session_snapshot
from dndgm4.scene_context import blank_scene
from dndgm4.storage import CreatureRepository


class RunSessionTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "library.sqlite3"
        self.library = CreatureRepository(self.path)
        self.campaigns = CampaignRepository(self.path)
        self.hero = self.library.save(Creature(name="Bran", character_class="Fighter",
                                              level=3, armor_class=17, max_hit_points=24))
        self.campaign = self.campaigns.create_campaign("The marsh road")
        self.session = self.campaigns.create_session(self.campaign.id, "Crossing")
        self.encounter = self.campaigns.create_encounter(self.session.id, "Bridge")
        self.campaigns.set_party(self.campaign.id, [self.hero.id])
        self.workspace = ActiveWorkspace(self.campaign.id, self.session.id, self.encounter.id)
        self.scene = dict(blank_scene(), title="Live scene", scenery="Reeds", places="Bridge",
                          time_conditions="Night", campaign_notes="Secret", record_ids=[self.hero.id])
        self.battle = AdvancedBattle(title="Unsaved bridge")
        self.battle.add(fighter_from_record(self.hero))

    def snapshot(self, **kwargs):
        return build_session_snapshot(self.library, self.campaigns,
                                      kwargs.get("workspace", self.workspace),
                                      kwargs.get("scene", self.scene),
                                      kwargs.get("battle", self.battle))

    def database_dump(self):
        with self.campaigns._connection() as db:
            return list(db.iterdump())

    def test_live_snapshot_does_not_write_or_reload_saved_state(self):
        before = self.database_dump()
        saved_battle = self.campaigns.load_battle(self.encounter.id).snapshot()
        saved_scene = self.campaigns.load_scene(self.session.id)
        self.battle.fighters[0].hp = 9
        self.battle.fighters[0].initiative = 19
        self.battle.fighters[0].conditions = [{"name": "Prone", "rounds": None}]
        self.battle.current_id = self.battle.fighters[0].uid
        self.battle.phase, self.battle.round = "combat", 4
        self.battle.log = [f"event {index}" for index in range(50)]
        live_before = self.battle.snapshot()
        result = self.snapshot()
        self.assertEqual(result["encounter_title"], "Unsaved bridge")
        self.assertEqual(result["scene_title"], "Live scene")
        self.assertEqual(result["workspace_key"], (self.campaign.id, self.session.id, self.encounter.id))
        self.assertEqual(result["current_name"], "Bran")
        self.assertEqual(result["fighters"][0]["hp"], 9)
        self.assertTrue(result["fighters"][0]["current"])
        self.assertEqual(result["fighters"][0]["conditions"], "Prone")
        self.assertEqual(result["combat_log"], self.battle.log[-30:])
        self.assertIn("Time and conditions: Night", result["scene_text"])
        self.assertIn("Campaign notes: Secret", result["scene_text"])
        result["combat_log"].append("local view change")
        result["fighters"][0]["hp"] = 100
        self.assertEqual(self.battle.snapshot(), live_before)
        self.assertEqual(self.database_dump(), before)
        self.assertEqual(self.campaigns.load_battle(self.encounter.id).snapshot(), saved_battle)
        self.assertEqual(self.campaigns.load_scene(self.session.id), saved_scene)

    def test_duplicate_sources_report_each_instance_and_permanent_stats(self):
        self.battle.add(fighter_from_record(self.hero, name="Bran duplicate"))
        self.battle.fighters[0].hp = 4
        self.battle.fighters[1].hp = 12
        self.battle.fighters[1].temp_hp = 3
        self.battle.fighters[1].active = False
        result = self.snapshot()
        self.assertEqual(len(result["fighters"]), 2)
        self.assertIn("Bran: 4/24 HP", result["party"][0]["encounter_hp"])
        self.assertIn("Bran duplicate: 12/24 HP (+3 temporary)", result["party"][0]["encounter_hp"])
        self.assertEqual(result["party"][0]["max_hp"], 24)
        self.assertEqual(self.library.get(self.hero.id), self.hero)

    def test_standalone_and_party_not_in_encounter(self):
        result = self.snapshot(battle=None)
        self.assertEqual(result["party"][0]["encounter_hp"], "Not in encounter")
        self.assertEqual(result["encounter_title"], "Bridge")
        standalone = self.snapshot(workspace=ActiveWorkspace(), battle=None)
        self.assertEqual(standalone["party"], [])
        self.assertEqual(standalone["session_notes"], "")
        self.assertEqual(standalone["session_id"], "")
        self.assertEqual(standalone["fighters"], [])

    def test_cross_campaign_session_and_cross_session_encounter_are_rejected(self):
        other = self.campaigns.create_campaign("Other")
        other_session = self.campaigns.create_session(other.id, "Elsewhere")
        bad_workspaces = [ActiveWorkspace(other.id, self.session.id, ""),
                          ActiveWorkspace(self.campaign.id, self.session.id,
                                          self.campaigns.create_encounter(other_session.id, "Wrong").id),
                          ActiveWorkspace("", self.session.id, ""),
                          ActiveWorkspace(self.campaign.id, "missing", "")]
        before = self.database_dump()
        for workspace in bad_workspaces:
            with self.subTest(workspace=workspace), self.assertRaises(ValueError):
                self.snapshot(workspace=workspace)
        self.assertEqual(self.database_dump(), before)

    def test_missing_scene_reference_visible_missing_party_reference_error(self):
        scene = dict(self.scene, record_ids=[self.hero.id, "gone"])
        self.assertEqual(self.snapshot(scene=scene)["scene_roster"], ["Bran", "[Missing record: gone]"])
        # Deliberately model a corrupt legacy DB; normal repository APIs prevent this.
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute("UPDATE campaign_members SET creature_id='gone' WHERE campaign_id=?", (self.campaign.id,))
        with self.assertRaisesRegex(ValueError, "Party member no longer exists"):
            self.snapshot()

    def test_invalid_workspace_and_missing_current_fighter_rejected(self):
        with self.assertRaises(ValueError):
            self.snapshot(workspace=ActiveWorkspace(None, "", ""))
        self.battle.current_id = "gone"
        with self.assertRaisesRegex(ValueError, "missing combatant"):
            self.snapshot()
        self.battle.current_id = ""
        self.campaigns.save_campaign(replace(self.campaign, archived=True))
        with self.assertRaisesRegex(ValueError, "Unarchive"):
            self.snapshot()

    def test_note_exact_size_boundaries_and_saved_notes_snapshot(self):
        saved = append_session_note(self.campaigns, self.session.id, "x" * 5000, expected_notes="")
        self.assertEqual(saved.notes, "x" * 5000)
        self.campaigns.save_session(replace(saved, notes="x" * 99997))
        saved = append_session_note(self.campaigns, self.session.id, "y", expected_notes="x" * 99997)
        self.assertEqual(len(saved.notes), 100000)
        self.assertEqual(self.snapshot()["session_notes"], saved.notes)

    def test_note_preserves_concurrently_changed_non_note_journal_fields(self):
        current = self.campaigns.save_session(replace(
            self.session, title="Renamed", status="completed", notes="First", recap="Keep recap"))
        saved = append_session_note(self.campaigns, self.session.id, "  Opened the gate  ",
                                    expected_notes="First")
        self.assertEqual(saved.notes, "First\n\nOpened the gate")
        self.assertEqual(replace(saved, notes=current.notes, updated_at=current.updated_at), current)
        self.assertEqual(self.campaigns.get_session(saved.id), saved)

    def test_stale_note_and_invalid_inputs_leave_all_data_unchanged(self):
        self.campaigns.save_session(replace(self.session, notes="Someone else's note", recap="Recap"))
        before = self.database_dump()
        for note, expected in [("New", ""), ("", "Someone else's note"),
                               (" " * 3, "Someone else's note"),
                               ("x" * 5001, "Someone else's note"),
                               ("null\x00", "Someone else's note"),
                               ("surrogate\ud800", "Someone else's note")]:
            with self.subTest(note=repr(note[:20])), self.assertRaises(ValueError):
                append_session_note(self.campaigns, self.session.id, note, expected_notes=expected)
        with self.assertRaises(ValueError):
            append_session_note(self.campaigns, "missing", "New", expected_notes="")
        self.assertEqual(self.database_dump(), before)

    def test_combined_notes_limit_and_database_failure_roll_back(self):
        self.campaigns.save_session(replace(self.session, notes="x" * 99999))
        before = self.database_dump()
        with self.assertRaises(ValueError):
            append_session_note(self.campaigns, self.session.id, "New", expected_notes="x" * 99999)
        self.assertEqual(self.database_dump(), before)
        self.campaigns.save_session(replace(self.session, notes="Original", recap="Keep"))
        with self.campaigns._connection() as db:
            db.execute("CREATE TRIGGER fail_note AFTER UPDATE ON sessions "
                       "BEGIN SELECT RAISE(ABORT, 'Interrupted'); END")
        before = self.database_dump()
        with self.assertRaises(sqlite3.Error):
            append_session_note(self.campaigns, self.session.id, "New", expected_notes="Original")
        self.assertEqual(self.database_dump(), before)


if __name__ == "__main__":
    unittest.main()
