"""Text review boundaries, source provenance, and transactional application."""
from contextlib import closing
from dataclasses import FrozenInstanceError, replace
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
import unittest

from dndgm4.battle_advanced import AdvancedBattle
from dndgm4.campaigns import CampaignRepository
from dndgm4.models import Creature
from dndgm4.reviewed_drafts import (
    PROPOSAL_MARKER, ReviewedDraftsRepository, build_draft_context,
)
from dndgm4.world import WorldRepository


class ReviewedDraftTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.path = Path(self.temp.name) / "library.sqlite3"
        self.campaigns = CampaignRepository(self.path)
        self.campaign = self.campaigns.create_campaign("Ash Road")
        self.other = self.campaigns.create_campaign("Other Road")
        self.session = self.campaigns.create_session(self.campaign.id, "The bridge")
        self.session = self.campaigns.save_session(replace(self.session, notes="The party rescued the courier.\n\nThey returned the sealed letter."))
        self.world = WorldRepository(self.path)
        self.handout = self.world.create(self.campaign.id, "handout", "Hidden ambush title",
                                         summary="Public bridge notice", dm_notes="SECRET spy identity",
                                         details={"player_text": "Meet at the bridge."})
        self.hero = self.campaigns.library.save(Creature(name="Élara", max_hit_points=18))
        self.repo = ReviewedDraftsRepository(self.path, self.campaign.id)

    def tearDown(self):
        self.temp.cleanup()

    def test_immutable_baseline_and_allowlist_do_not_save_on_prepare(self):
        baseline = self.repo.snapshot("session", self.session.id)
        with self.assertRaises(FrozenInstanceError):
            baseline.target_id = "another"
        values = baseline.values
        values["notes"] = "Mutated detached dictionary"
        self.assertEqual(baseline.field_text("notes"), self.session.notes)
        proposal = self.repo.prepare(baseline, {"notes": "Plan a meeting at dawn."})
        self.assertIn(PROPOSAL_MARKER, proposal.changes[0].after)
        self.assertEqual(self.campaigns.get_session(self.session.id), self.session)
        for field in ("status", "campaign_id", "max_hit_points", "title"):
            with self.assertRaises(ValueError):
                self.repo.prepare(baseline, {field: "Forbidden"})

    def test_checked_field_only_and_other_state_unchanged(self):
        baseline = self.repo.snapshot("world", self.handout.id)
        proposal = self.repo.prepare(baseline, {"dm_notes": "A proposed secret", "summary": "A proposed public hook"})
        self.repo.apply(proposal, selected_fields=("dm_notes",))
        saved = self.world.get(self.handout.id)
        self.assertIn("A proposed secret", saved.dm_notes)
        self.assertEqual(saved.summary, self.handout.summary)
        self.assertEqual(saved.details, self.handout.details)
        self.assertEqual(self.campaigns.library.get(self.hero.id), self.hero)
        self.assertEqual(self.campaigns.get_workspace().campaign_id, "")

    def test_public_text_requires_dedicated_confirmation(self):
        baseline = self.repo.snapshot("world", self.handout.id)
        proposal = self.repo.prepare(baseline, {"player_text": "A public invitation."})
        with self.assertRaisesRegex(ValueError, "public text"):
            self.repo.apply(proposal)
        self.assertEqual(self.world.get(self.handout.id), self.handout)
        self.repo.apply(proposal, public_reviewed=True)
        saved = self.world.get(self.handout.id)
        self.assertEqual(saved.details["player_text"], "A public invitation.")
        self.assertEqual(saved.dm_notes, "SECRET spy identity")
        self.assertEqual(saved.summary, self.handout.summary)

    def test_public_scribe_context_excludes_target_metadata_and_private_fields(self):
        baseline = self.repo.snapshot("world", self.handout.id)
        context = build_draft_context(baseline, "player_text", "Write an invitation.")
        self.assertIn("Meet at the bridge.", context)
        for secret in (self.handout.dm_notes, self.handout.name, self.handout.summary):
            self.assertNotIn(secret, context)

    def test_recap_requires_selected_confirmed_evidence_and_valid_paragraph_citations(self):
        baseline = self.repo.snapshot("session", self.session.id)
        sources = self.repo.load_evidence(self.session.id)
        for text, evidence, confirmed in (("A recap", (), True), ("A recap " + sources[0].citation, sources[:1], False),
                                           ("Uncited paragraph", sources[:1], True),
                                           ("A recap [E-000000000000]", sources[:1], True),
                                           ("First " + sources[0].citation + "\n\nUncited outcome", sources[:1], True)):
            with self.assertRaises(ValueError):
                self.repo.prepare(baseline, {"recap": text}, evidence=evidence,
                                  recorded_evidence_confirmed=confirmed)
        raw = "The courier was rescued. " + sources[0].citation
        proposal = self.repo.prepare(baseline, {"recap": raw}, evidence=sources[:1], recorded_evidence_confirmed=True)
        self.repo.apply(proposal)
        saved = self.campaigns.get_session(self.session.id)
        self.assertIn(raw, saved.recap)
        self.assertIn(sources[0].text, saved.recap)
        self.assertIn("session_notes:" + self.session.id, saved.recap)
        self.assertIn(sources[0].source_digest, saved.recap)
        self.assertEqual(saved.notes, self.session.notes)
        self.assertEqual(saved.status, "planned")  # status is never inferred from a recap.

    def test_our_saved_planning_proposals_are_not_recap_evidence(self):
        proposal = self.repo.prepare(self.repo.snapshot("session", self.session.id),
                                     {"notes": "The party might rescue the courier next week."})
        self.repo.apply(proposal)
        self.assertEqual(self.repo.load_evidence(self.session.id), ())

    def test_changed_target_rejects_draft_without_overwriting_newer_journal(self):
        proposal = self.repo.prepare(self.repo.snapshot("session", self.session.id), {"notes": "A proposed scene"})
        newer = self.campaigns.save_session(replace(self.session, title="A corrected title"))
        with self.assertRaisesRegex(ValueError, "changed after"):
            self.repo.apply(proposal)
        self.assertEqual(self.campaigns.get_session(self.session.id), newer)

    def test_encounter_log_evidence_is_loaded_and_rechecked_atomically(self):
        encounter = self.campaigns.create_encounter(self.session.id, "Bridge Watch")
        battle = AdvancedBattle(title="Bridge Watch", log=["The watch accepted the surrender."])
        self.campaigns.save_battle(encounter.id, battle)
        source = next(item for item in self.repo.load_evidence(self.session.id) if item.source_kind == "encounter_log")
        proposal = self.repo.prepare(self.repo.snapshot("session", self.session.id),
                                     {"recap": "The watch accepted surrender. " + source.citation},
                                     evidence=(source,), recorded_evidence_confirmed=True)
        battle.log.append("The DM corrected the earlier result.")
        self.campaigns.save_battle(encounter.id, battle)
        with self.assertRaisesRegex(ValueError, "evidence changed"):
            self.repo.apply(proposal)
        self.assertEqual(self.campaigns.get_session(self.session.id).recap, "")

    def test_campaign_boundaries_apply_to_targets_and_evidence(self):
        foreign = self.campaigns.create_session(self.other.id, "Foreign session")
        self.campaigns.save_session(replace(foreign, notes="A different party found a map."))
        with self.assertRaises(ValueError):
            self.repo.snapshot("session", foreign.id)
        with self.assertRaises(ValueError):
            self.repo.load_evidence(foreign.id)
        other_repo = ReviewedDraftsRepository(self.path, self.other.id)
        other_source = other_repo.load_evidence(foreign.id)[0]
        with self.assertRaisesRegex(ValueError, "selected session"):
            self.repo.prepare(self.repo.snapshot("session", self.session.id),
                              {"recap": "A different party found a map. " + other_source.citation},
                              evidence=(other_source,), recorded_evidence_confirmed=True)
        other_proposal = other_repo.prepare(other_repo.snapshot("session", foreign.id), {"notes": "A foreign plan"})
        with self.assertRaises(ValueError):
            self.repo.apply(other_proposal)

    def test_transaction_failure_preserves_every_selected_field(self):
        baseline = self.repo.snapshot("world", self.handout.id)
        proposal = self.repo.prepare(baseline, {"summary": "Public proposal", "dm_notes": "Private proposal"})
        with closing(sqlite3.connect(self.path)) as db:
            db.execute("CREATE TRIGGER fail_review AFTER UPDATE ON world_records BEGIN "
                       "SELECT RAISE(ABORT, 'Interrupted reviewed write'); END")
            db.commit()
        with self.assertRaises(sqlite3.Error):
            self.repo.apply(proposal, public_reviewed=True)
        self.assertEqual(self.world.get(self.handout.id), self.handout)
        self.assertEqual(proposal.baseline, baseline)


if __name__ == "__main__":
    unittest.main()
