"""Campaign Scribe memory is explicit, complete, and read-only."""
from dataclasses import replace
from contextlib import closing
import json
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from dndgm4.campaign_context import (CAMPAIGN_TASKS, build_campaign_context,
                                    build_campaign_planning_context)
from dndgm4.campaigns import CampaignRepository
from dndgm4.models import Creature
from dndgm4.scene_context import blank_scene
from dndgm4.storage import CreatureRepository


class CampaignContextTests(unittest.TestCase):
    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.path = Path(self.tmp.name) / "library.sqlite3"
        self.library = CreatureRepository(self.path)
        self.repo = CampaignRepository(self.path)
        self.pc = self.library.save(Creature(
            name="Élara 灰", character_class="Wizard", intelligence=17,
            notes="Carries an old brass key.", sheet_json=json.dumps({
                "background": "From the silver marsh.",
                "inventory": [{"name": "Moon ledger", "quantity": 1}],
                "custom_lore": {"mother": "The mapmaker"},
            }, ensure_ascii=False)))
        self.npc = self.library.save(Creature(name="Keeper Tamsin", kind="npc",
                                             notes="Knows the eastern gate."))
        self.campaign = self.repo.create_campaign(
            "Lantern Road", description="Restore the lost observatory.",
            notes="DM-ONLY SECRET: The patron forged the first map.")
        self.repo.set_party(self.campaign.id, [self.pc.id])
        self.session = self.repo.create_session(self.campaign.id, "The night crossing", "2026-10-22")
        self.session = self.repo.save_session(replace(
            self.session, notes="Recorded outcome: the party rescued the ferryman.",
            recap="The party learned the eastern gate was shut."))
        self.scene = blank_scene()
        self.scene.update(title="The gatehouse", location="Lantern Bridge",
                          scenery="A locked gate beside deep water.",
                          campaign_notes="Proposed clue: a torn seal under the desk.",
                          record_ids=[self.pc.id, self.npc.id])
        self.repo.save_scene(self.session.id, self.scene)

    def tearDown(self):
        self.tmp.cleanup()

    def build(self, **kwargs):
        return build_campaign_context(self.repo, self.library, self.session.id, **kwargs)

    def test_complete_saved_metadata_notes_scene_and_nested_records_are_preserved(self):
        context = self.build()
        for expected in (
            self.campaign.name, self.campaign.description, self.campaign.notes,
            self.session.id, self.session.title, self.session.session_date, self.session.status,
            self.session.notes, self.session.recap, self.scene["title"],
            self.scene["location"], self.scene["scenery"], self.scene["campaign_notes"],
            self.pc.name, self.pc.notes, self.npc.name, "Moon ledger", "custom_lore", "The mapmaker",
        ):
            with self.subTest(expected=expected):
                self.assertIn(expected, context)
        self.assertIn('"intelligence":17', context)
        self.assertIn("current presence not implied", context)
        self.assertIn("explicitly present in the selected scene", context)
        self.assertIn("Complete unique library records: 2", context)
        self.assertEqual(context.count('"name":"Élara 灰"'), 1)
        self.assertEqual(context.count('"name":"Keeper Tamsin"'), 1)

    def test_party_membership_does_not_imply_scene_presence(self):
        scene = {**self.scene, "record_ids": [self.npc.id]}
        self.repo.save_scene(self.session.id, scene)
        context = self.build()
        self.assertIn(self.pc.name, context)
        self.assertIn("CAMPAIGN PARTY MEMBERSHIP / PRESENCE NOT IMPLIED", context)
        self.assertIn("Use: campaign party; current presence not implied", context)
        self.assertIn("Use: explicitly present in the selected scene", context)

    def test_only_earlier_completed_recaps_enter_campaign_memory(self):
        early = self.repo.create_session(self.campaign.id, "Earlier session")
        early = self.repo.save_session(replace(early, status="completed", recap="EARLIER_CONFIRMED_OUTCOME"))
        planned = self.repo.create_session(self.campaign.id, "Unplayed outline")
        planned = self.repo.save_session(replace(planned, recap="UNPLAYED_PLAN_SHOULD_NOT_APPEAR"))
        selected = self.repo.create_session(self.campaign.id, "Selected session")
        later = self.repo.create_session(self.campaign.id, "Later session")
        self.repo.save_session(replace(later, status="completed", recap="FUTURE_OUTCOME_SHOULD_NOT_APPEAR"))
        other = self.repo.create_campaign("Another campaign")
        other_session = self.repo.create_session(other.id, "Other campaign session")
        self.repo.save_session(replace(other_session, status="completed", recap="OTHER_CAMPAIGN_SHOULD_NOT_APPEAR"))
        context = build_campaign_context(self.repo, self.library, selected.id)
        self.assertIn("EARLIER_CONFIRMED_OUTCOME", context)
        self.assertNotIn("UNPLAYED_PLAN_SHOULD_NOT_APPEAR", context)
        self.assertNotIn("FUTURE_OUTCOME_SHOULD_NOT_APPEAR", context)
        self.assertNotIn("OTHER_CAMPAIGN_SHOULD_NOT_APPEAR", context)

    def test_recap_separates_recorded_events_from_scene_preparation(self):
        context = self.build(task="recap")
        self.assertIn("SELECTED SESSION NOTES / DM-SUPPLIED EVENT EVIDENCE", context)
        self.assertIn("SELECTED SESSION SCENE / PREPARATION BACKGROUND", context)
        self.assertIn("A plan, roster, or scene description is not evidence", context)
        self.assertIn("request event notes instead of inventing a recap", context)
        self.assertIn(self.session.notes, context)
        self.assertIn(self.scene["campaign_notes"], context)

    def test_empty_session_notes_request_evidence_instead_of_fabrication(self):
        self.repo.save_session(replace(self.session, notes="", recap=""))
        context = self.build(task="recap")
        self.assertIn("[No session notes recorded.]", context)
        self.assertIn("[No recap recorded.]", context)
        self.assertIn("request event notes", context)

    def test_each_supported_task_has_specific_guidance_and_same_saved_facts(self):
        for task in CAMPAIGN_TASKS:
            with self.subTest(task=task):
                context = self.build(task=task)
                self.assertIn(f"Requested task: {task}", context)
                self.assertIn(self.campaign.notes, context)
                self.assertIn(self.session.notes, context)
                self.assertIn("DM-only material must remain separate", context)

    def test_archived_party_member_is_reported_without_silent_omission(self):
        self.library.set_archived(self.pc.id, True)
        with self.assertRaisesRegex(ValueError, "party record.*archived"):
            self.build()
        self.assertTrue(self.library.get(self.pc.id).archived)

    def test_archived_scene_only_member_is_reported_without_silent_omission(self):
        self.library.set_archived(self.npc.id, True)
        with self.assertRaisesRegex(ValueError, "scene record.*archived"):
            self.build()

    def test_missing_scene_record_is_reported(self):
        self.repo.save_scene(self.session.id, {**self.scene, "record_ids": ["missing-scene-member"]})
        with self.assertRaisesRegex(ValueError, "scene record.*missing"):
            self.build()

    def test_dangling_party_membership_is_reported(self):
        # Model a DB repaired outside the app with FK checks disabled. The
        # context must not quietly turn a broken membership into a smaller party.
        with closing(sqlite3.connect(self.path)) as db:
            db.execute("PRAGMA foreign_keys=OFF")
            db.execute("DELETE FROM creatures WHERE id=?", (self.pc.id,))
            db.commit()
        with self.assertRaisesRegex(ValueError, "party record.*missing"):
            self.build()

    def test_missing_session_and_campaign_have_actionable_errors(self):
        with self.assertRaisesRegex(ValueError, "session no longer exists"):
            build_campaign_context(self.repo, self.library, "unknown-session")
        with patch.object(self.repo, "get_campaign", return_value=None):
            with self.assertRaisesRegex(ValueError, "campaign no longer exists"):
                self.build()

    def test_invalid_task_context_limit_or_selection_is_rejected(self):
        for task in ("unknown", None, []):
            with self.subTest(task=task):
                with self.assertRaises(ValueError):
                    self.build(task=task)
        for limit in (0, -1, True, 12.0):
            with self.subTest(limit=limit):
                with self.assertRaises(ValueError):
                    self.build(max_chars=limit)
        for identity in ("", None):
            with self.subTest(identity=identity):
                with self.assertRaises(ValueError):
                    build_campaign_context(self.repo, self.library, identity)

    def test_oversized_context_is_rejected_and_saved_text_is_not_shortened(self):
        notes = "Full campaign memory " * 400
        updated = self.repo.save_campaign(replace(self.campaign, notes=notes))
        with self.assertRaisesRegex(ValueError, "No campaign history or character details"):
            self.build()
        self.assertEqual(self.repo.get_campaign(updated.id).notes, notes)
        context = self.build(max_chars=30000)
        self.assertIn(notes, context)

    def test_loading_context_never_changes_workspace_records_or_history(self):
        before = (self.repo.get_campaign(self.campaign.id), self.repo.get_session(self.session.id),
                  self.repo.get_workspace(), self.repo.load_scene(self.session.id),
                  self.library.list(include_archived=True))
        for task in CAMPAIGN_TASKS:
            self.build(task=task)
        after = (self.repo.get_campaign(self.campaign.id), self.repo.get_session(self.session.id),
                 self.repo.get_workspace(), self.repo.load_scene(self.session.id),
                 self.library.list(include_archived=True))
        self.assertEqual(after, before)

    def test_inconsistent_campaign_session_listing_is_reported(self):
        with patch.object(self.repo, "list_sessions", return_value=[]):
            with self.assertRaisesRegex(ValueError, "missing from its campaign history"):
                self.build()

    def test_campaign_planning_without_sessions_preserves_premise_and_party(self):
        campaign = self.repo.create_campaign("Fresh campaign", "Follow the star roads.", "DM-only: the guide is lost.")
        self.repo.set_party(campaign.id, [self.pc.id])
        context = build_campaign_planning_context(self.repo, self.library, campaign.id)
        for expected in (campaign.name, campaign.description, campaign.notes, self.pc.name,
                         "Moon ledger", "custom_lore", "No session or scene is selected",
                         "[No completed recaps recorded.]", "Requested task: campaign_plan"):
            with self.subTest(expected=expected):
                self.assertIn(expected, context)
        self.assertNotIn(self.npc.name, context)
        self.assertEqual(self.repo.list_sessions(campaign.id), [])

    def test_campaign_planning_includes_only_completed_recaps_not_unplayed_plans(self):
        completed = self.repo.create_session(self.campaign.id, "Completed journey")
        self.repo.save_session(replace(completed, status="completed", recap="CAMPAIGN_COMPLETED_OUTCOME"))
        planned = self.repo.create_session(self.campaign.id, "Planned journey")
        self.repo.save_session(replace(planned, notes="UNPLAYED_NOTES", recap="UNPLAYED_RECAP"))
        in_progress = self.repo.create_session(self.campaign.id, "Current journey")
        self.repo.save_session(replace(in_progress, status="in_progress", recap="IN_PROGRESS_RECAP"))
        context = build_campaign_planning_context(self.repo, self.library, self.campaign.id)
        self.assertIn("CAMPAIGN_COMPLETED_OUTCOME", context)
        self.assertNotIn("UNPLAYED_NOTES", context)
        self.assertNotIn("UNPLAYED_RECAP", context)
        self.assertNotIn("IN_PROGRESS_RECAP", context)
        self.assertNotIn(self.scene["location"], context)

    def test_campaign_planning_missing_or_archived_party_is_not_silently_omitted(self):
        self.library.set_archived(self.pc.id, True)
        with self.assertRaisesRegex(ValueError, "party record.*archived"):
            build_campaign_planning_context(self.repo, self.library, self.campaign.id)
        self.library.set_archived(self.pc.id, False)
        with closing(sqlite3.connect(self.path)) as db:
            db.execute("PRAGMA foreign_keys=OFF")
            db.execute("DELETE FROM creatures WHERE id=?", (self.pc.id,))
            db.commit()
        with self.assertRaisesRegex(ValueError, "party record.*missing"):
            build_campaign_planning_context(self.repo, self.library, self.campaign.id)

    def test_campaign_planning_validates_identity_and_limit(self):
        for identity in ("", None, "unknown-campaign"):
            with self.subTest(identity=identity):
                with self.assertRaises(ValueError):
                    build_campaign_planning_context(self.repo, self.library, identity)
        for limit in (0, -1, True, 12.0):
            with self.subTest(limit=limit):
                with self.assertRaises(ValueError):
                    build_campaign_planning_context(self.repo, self.library, self.campaign.id, max_chars=limit)

    def test_campaign_planning_oversize_fails_without_mutating_or_shortening(self):
        campaign = self.repo.save_campaign(replace(self.campaign, notes="Unabridged memory " * 400))
        before = (campaign, self.repo.get_workspace(), self.library.list(include_archived=True),
                  self.repo.list_sessions(campaign.id))
        with self.assertRaisesRegex(ValueError, "No campaign history or character details"):
            build_campaign_planning_context(self.repo, self.library, campaign.id)
        context = build_campaign_planning_context(self.repo, self.library, campaign.id, max_chars=30000)
        self.assertIn(campaign.notes, context)
        after = (self.repo.get_campaign(campaign.id), self.repo.get_workspace(),
                 self.library.list(include_archived=True), self.repo.list_sessions(campaign.id))
        self.assertEqual(after, before)

    def test_compact_record_json_preserves_every_detail_without_formatting_overhead(self):
        context = self.build()
        marker = "Use: campaign party; current presence not implied; explicitly present in the selected scene\n"
        record_json = context.split(marker, 1)[1].split("\n\n", 1)[0]
        from dndgm4.scene_context import record_details
        self.assertEqual(json.loads(record_json), json.loads(record_details(self.pc)))
        self.assertLess(len(record_json), len(record_details(self.pc)))
