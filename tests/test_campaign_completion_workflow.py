"""A populated campaign survives cross-tool edits and a portable recovery."""
from dataclasses import replace
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from dndgm4.campaigns import CampaignRepository
from dndgm4.campaign_time import CampaignTimeRepository
from dndgm4.models import Creature
from dndgm4.multiclass import (
    advance_multiclass, class_history, default_multiclass_choices,
    establish_history, save_multiclass_candidate,
)
from dndgm4.recovery import create_backup, restore_backup
from dndgm4.resources import ResourceRepository
from dndgm4.reviewed_drafts import ReviewedDraftsRepository
from dndgm4.rules_reference import RulesRepository
from dndgm4.spell_progression import GROUPS, build_spell_candidate, caster_profiles, save_spell_candidate
from dndgm4.srd35_spells import SpellCatalog
from dndgm4.storage import CreatureRepository
from dndgm4.world import WorldRepository


class CampaignCompletionWorkflowTests(unittest.TestCase):
    def test_play_review_resources_spells_and_restore_keep_distinct_state(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            path = root / "live" / "library.sqlite3"
            library = CreatureRepository(path)
            hero = library.save(Creature(name="Ember", character_class="Wizard", level=5,
                intelligence=18, max_hit_points=25, notes="Secret patron identity",
                sheet_json=json.dumps({"background": "Original biography", "inventory": [{"name": "Staff"}]})))
            campaigns = CampaignRepository(path)
            campaign = campaigns.create_campaign("The Ember Road")
            campaigns.set_party(campaign.id, [hero.id])
            session = campaigns.create_session(campaign.id, "The bridge", "2026-10-22")
            session = campaigns.save_session(replace(session, notes="The party crossed the bridge and rescued the courier."))
            encounter = campaigns.create_encounter(session.id, "Bridge guardians")
            battle = campaigns.load_battle(encounter.id)
            battle.log.append("The courier escaped safely; the DM recorded the outcome.")
            campaigns.save_battle(encounter.id, battle)
            battle_before = campaigns.load_battle(encounter.id).snapshot()
            campaigns.activate(campaign.id, session.id, encounter.id)

            world = WorldRepository(path)
            handout = world.create(campaign.id, "handout", "Hidden ambush title",
                summary="Secret summary", dm_notes="A spy is waiting at the bridge.",
                details={"player_text": "Meet the courier at the bridge."})
            world.create(campaign.id, "event", "Couriers depart", details={"day": 0, "time": "00:30"})
            clock = CampaignTimeRepository(path)
            travel = clock.preview_travel(campaign.id, "3", "3", travelers=1,
                                         encounter_roll=True, roller=lambda: 12)
            self.assertEqual(len(travel.events), 1)
            clock.apply_preview(travel)
            clock.apply_preview(travel)
            self.assertEqual(clock.get_clock(campaign.id).minutes, 60)
            weather = clock.preview_weather(campaign.id, 0, roller=lambda: 19)
            clock.apply_weather(weather)
            self.assertEqual(library.get(hero.id), hero)
            self.assertEqual(campaigns.load_battle(encounter.id).snapshot(), battle_before)

            resources = ResourceRepository(path)
            treasury = resources.create_wallet(campaign.id, "Party treasury")
            purse = resources.create_wallet(campaign.id, "Ember's purse", hero.id)
            resources.award(campaign.id, [{"wallet_id": treasury.id, "copper": 1000, "xp": 0},
                            {"wallet_id": purse.id, "copper": 0, "xp": 300}],
                            "Rescued courier", "courier-reward", session_id=session.id, encounter_id=encounter.id)
            resources.transfer_money(campaign.id, treasury.id, purse.id, 250, "Reviewed share", "share-1", session_id=session.id)
            resources.add_item(campaign.id, purse.id, "Rations", 3, 1000, "Travel supplies", "rations-1")

            plan = {group: {} for group in GROUPS}
            plan["spellbook"] = {"3": ["Fireball"]}
            plan["prepared"] = {"3": ["Fireball"]}
            catalog = [{"class": "Sorcerer/Wizard", "level": 3, "name": "Fireball",
                        "url": "https://www.d20srd.org/srd/spells/fireball.htm"}]
            SpellCatalog(path).store(catalog)
            stale_spell = build_spell_candidate(hero, "Wizard", plan, catalog=catalog, review_ack=True)
            resources.apply_xp(resources.preview_xp(campaign.id, purse.id), "apply-courier-xp")
            with self.assertRaisesRegex(ValueError, "changed after"):
                save_spell_candidate(library, hero, stale_spell, catalog=catalog)
            updated = library.get(hero.id)
            candidate = build_spell_candidate(updated, "Wizard", plan, catalog=catalog, review_ack=True)
            updated = save_spell_candidate(library, updated, candidate, catalog=catalog)
            self.assertEqual(json.loads(updated.sheet_json)["experience_points"], 300)
            self.assertEqual(updated.level, hero.level)
            self.assertEqual(updated.max_hit_points, hero.max_hit_points)
            self.assertEqual(updated.notes, hero.notes)

            history = establish_history(updated, {"Wizard": 5}, review_ack=True,
                no_racial_hd_ack=True, review_notes="The DM reviewed the existing class-only history.")
            updated = save_multiclass_candidate(library, updated, history)
            choices = default_multiclass_choices(updated, "Fighter")
            choices.update(hp_roll=6, hp_roll_detail="Recorded d10 face: 6", review_ack=True,
                class_notes="Reviewed Fighter first-level features and weapon/armor proficiencies.",
                restriction_notes="The DM approved milestone advancement and class restrictions.")
            advanced = advance_multiclass(updated, "Fighter", choices)
            updated = save_multiclass_candidate(library, updated, advanced)
            self.assertEqual(class_history(updated, require_confirmed=True), {"Fighter": 1, "Wizard": 5})
            self.assertEqual(caster_profiles(updated)["Wizard"]["class_level"], 5)
            self.assertEqual(json.loads(updated.sheet_json)["experience_points"], 300)
            self.assertEqual(json.loads(updated.sheet_json)["spell_progression"]["Wizard"]["prepared"]["3"], ["Fireball"])
            self.assertEqual(campaigns.load_battle(encounter.id).snapshot(), battle_before)

            reviews = ReviewedDraftsRepository(path, campaign.id)
            evidence = reviews.load_evidence(session.id)[:1]
            proposal = reviews.prepare(reviews.snapshot("session", session.id),
                {"recap": "The party rescued the courier. " + evidence[0].citation},
                evidence=evidence, recorded_evidence_confirmed=True)
            reviews.apply(proposal)
            public_file = root / "courier-handout.txt"
            world.export_player_handout(handout.id, public_file)
            self.assertEqual(public_file.read_text(), "Meet the courier at the bridge.")
            self.assertNotIn("spy", public_file.read_text())
            rules = RulesRepository(path.with_name("rules.sqlite3"), seed=False)
            rules.import_document("Campaign bridge ruling", "Homebrew bridge ruling: the bridge toll is waived after the rescue.")
            asset = path.parent / "assets" / "handouts" / "courier.txt"
            asset.parent.mkdir(parents=True)
            asset.write_text(public_file.read_text())

            archive = root / "complete.dndbackup"
            create_backup(library, archive)
            restored_path = restore_backup(archive, root / "recovered")
            restored = CreatureRepository(restored_path)
            self.assertEqual(restored.get(hero.id), updated)
            self.assertEqual(class_history(restored.get(hero.id), require_confirmed=True), {"Fighter": 1, "Wizard": 5})
            restored_campaigns = CampaignRepository(restored_path)
            self.assertEqual(restored_campaigns.get_workspace(), campaigns.get_workspace())
            self.assertEqual(restored_campaigns.load_battle(encounter.id).snapshot(), battle_before)
            self.assertIn("RECORDED SOURCE EVIDENCE", restored_campaigns.get_session(session.id).recap)
            restored_resources = ResourceRepository(restored_path)
            self.assertEqual(restored_resources.get_wallet(campaign.id, purse.id).copper, 250)
            self.assertEqual(restored_resources.get_wallet(campaign.id, treasury.id).copper, 750)
            self.assertEqual(restored_resources.preview_xp(campaign.id, purse.id).pending, 0)
            self.assertEqual(restored_resources.list_items(campaign.id, purse.id)[0].quantity, 3)
            restored_clock = CampaignTimeRepository(restored_path)
            self.assertEqual(restored_clock.get_clock(campaign.id).minutes, 60)
            self.assertEqual(restored_clock.weather(campaign.id, 0)["roll"], 19)
            self.assertEqual(WorldRepository(restored_path).player_handout(handout.id), public_file.read_text())
            self.assertTrue(RulesRepository(restored_path.with_name("rules.sqlite3"), seed=False).search("bridge"))
            self.assertEqual(SpellCatalog(restored_path).search("Fireball", "Sorcerer/Wizard", 3), catalog)
            self.assertEqual((restored_path.parent / "assets/handouts/courier.txt").read_text(), public_file.read_text())
            self.assertEqual(library.get(hero.id), updated)
