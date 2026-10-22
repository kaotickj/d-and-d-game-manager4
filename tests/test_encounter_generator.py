"""Reproducible random proposals never mutate templates or start combat."""
from dataclasses import asdict, replace
import json
from random import Random
import unittest

from dndgm4.battle_rules import Battle
from dndgm4.encounter_generator import ENVIRONMENTS, generate_encounter
from dndgm4.models import Creature
from dndgm4.scene_context import blank_scene


class NoRolls:
    def randint(self, low, high):
        raise AssertionError("An invalid request must not draw dice.")


class EncounterGeneratorTests(unittest.TestCase):
    def setUp(self):
        self.template = Creature(id="library-sentry", kind="monster", name="Bog Sentry",
                                 max_hit_points=19, armor_class=14, dexterity=14,
                                 sheet_json=json.dumps({"feats": ["Improved Initiative"],
                                                        "attacks": "Staff +2 melee (1d6)",
                                                        "special_qualities": "DM-defined sense"}))

    def test_library_instances_preserve_template_and_have_independent_state(self):
        original = asdict(self.template)
        draft = generate_encounter([self.template], quantity="3", roll_initiative=True, rng=Random(7))
        self.assertEqual(len(draft.creatures), 3)
        self.assertEqual(asdict(self.template), original)
        self.assertEqual(len({fighter.uid for fighter in draft.fighters}), 3)
        for fighter in draft.fighters:
            self.assertEqual(fighter.source_id, self.template.id)
            self.assertEqual(fighter.hp, self.template.max_hit_points)
            self.assertEqual(fighter.init_mod, 6)
            self.assertEqual(fighter.initiative, fighter.initiative_roll + 6)
        draft.fighters[0].hp = 1
        self.assertEqual(draft.fighters[1].hp, 19)
        self.assertEqual(self.template.max_hit_points, 19)
        battle = Battle(fighters=list(draft.fighters))
        self.assertEqual(Battle.from_dict(battle.snapshot()).phase, "setup")
        self.assertIn("HP 19 and abilities retained", "\n".join(draft.roll_log))
        self.assertIn("initiative", "\n".join(draft.roll_log))

    def test_seed_reproduces_settings_statistics_and_rolls(self):
        first = generate_encounter([], source="original", quantity="1d4", rng=Random(13))
        second = generate_encounter([], source="original", quantity="1d4", rng=Random(13))
        self.assertEqual(first.creatures, second.creatures)
        self.assertEqual(first.roll_log, second.roll_log)
        self.assertEqual(first.read_aloud, second.read_aloud)
        self.assertEqual(first.location, second.location)
        self.assertEqual([f.hp for f in first.fighters], [f.hp for f in second.fighters])
        self.assertNotEqual(first.fighters[0].uid, second.fighters[0].uid)

    def test_caverns_use_underground_conditions_and_creature_appropriate_motives(self):
        from dndgm4.encounter_generator import _ANIMAL_MOTIVES, _MINDLESS_MOTIVES
        observed = set()
        for seed in range(12):
            draft = generate_encounter([], source="original", environment="Cavern",
                                       quantity="1", rng=Random(seed))
            self.assertNotIn("rain", draft.conditions.casefold())
            self.assertNotIn("cloud", draft.conditions.casefold())
            kind = json.loads(draft.creatures[0].sheet_json)["monster_type"]
            observed.add(kind)
            self.assertIn(draft.motive, _ANIMAL_MOTIVES if kind == "Animal" else _MINDLESS_MOTIVES)
        self.assertIn("Animal", observed)
        self.assertTrue(observed.intersection(("Undead", "Vermin")))

    def test_original_creatures_work_without_library_for_every_environment(self):
        for environment in ENVIRONMENTS:
            with self.subTest(environment=environment):
                draft = generate_encounter([], source="original", environment=environment,
                                           quantity="2", rng=Random(3))
                self.assertEqual(draft.environment, environment)
                self.assertEqual(len(draft.fighters), 2)
                self.assertIn("original", draft.creatures[0].notes.casefold())
                for creature, fighter in zip(draft.creatures, draft.fighters):
                    self.assertEqual(creature.id, "")
                    self.assertEqual(fighter.source_id, "")
                    self.assertEqual(creature.challenge_rating, "")
                    self.assertEqual(fighter.hp, creature.max_hit_points)
                    sheet = json.loads(creature.sheet_json)
                    self.assertIn("Proposed strike", sheet["attacks"])
                    self.assertEqual(sheet["hp_method"], "rolled")
                    self.assertIn("BAB", fighter.notes)
                self.assertIn("HP dice:", "\n".join(draft.roll_log))
                self.assertIn("Computed baseline:", draft.dm_brief())
                self.assertIn("Attacks:", draft.dm_brief())
                self.assertNotIn(draft.motive, draft.read_aloud)
                self.assertNotIn(draft.complication, draft.read_aloud)

    def test_count_expressions_are_bounded_before_any_random_draws(self):
        for quantity in ("0", "13", "200d6", "1d100000", "12d12", "1d12+1", "1d4-1", "__import__('os')", "-1", None):
            with self.subTest(quantity=quantity), self.assertRaises(ValueError):
                generate_encounter([], source="original", quantity=quantity, rng=NoRolls())
        for quantity in ("1d4", "2d6", "1d12", "1d4+1", "12"):
            with self.subTest(quantity=quantity):
                draft = generate_encounter([], source="original", quantity=quantity, rng=Random(5))
                self.assertTrue(1 <= len(draft.fighters) <= 12)

    def test_library_filters_archived_records_and_player_characters(self):
        records = (self.template, Creature(name="Player", kind="pc", id="pc"),
                   replace(self.template, id="archived", name="Archived", archived=True))
        draft = generate_encounter(records, quantity="2", rng=Random(5))
        self.assertTrue(all(creature.id == self.template.id for creature in draft.creatures))
        with self.assertRaisesRegex(ValueError, "No active NPC or monster"):
            generate_encounter(records[1:], rng=NoRolls())

    def test_scene_handoff_preserves_roster_and_campaign_notes_without_mutation(self):
        scene = {**blank_scene(), "record_ids": ["party-pc", self.template.id],
                 "campaign_notes": "An established campaign fact.", "places": "The old inn"}
        before = json.loads(json.dumps(scene))
        draft = generate_encounter([self.template], quantity="2", rng=Random(9))
        updated = draft.to_scene(scene)
        self.assertEqual(scene, before)
        self.assertEqual(updated["record_ids"], ["party-pc", self.template.id])
        self.assertEqual(updated["places"], "The old inn")
        self.assertEqual(updated["location"], draft.location)
        self.assertIn("An established campaign fact.", updated["campaign_notes"])
        self.assertIn("Bog Sentry #2", updated["campaign_notes"])
        self.assertIn("ROLL LOG", updated["campaign_notes"])
        originals = generate_encounter([], source="original", quantity="2", rng=Random(2))
        self.assertEqual(originals.to_scene(scene)["record_ids"], scene["record_ids"])

    def test_scribe_context_contains_final_encounter_facts_and_keeps_audit_in_draft(self):
        draft = generate_encounter([], source="original", quantity="4", rng=Random(2))
        context = draft.scribe_context()
        self.assertLessEqual(len(context), 6000)
        self.assertIn("dice audit is retained in the draft", context)
        self.assertNotIn("ROLL LOG", context)
        self.assertIn("ROLL LOG", draft.dm_brief())
        self.assertIn(draft.motive, context)
        self.assertIn("Computed baseline:", context)
        for fighter in draft.fighters:
            self.assertIn(fighter.name, context)
        enormous = replace(draft, dm_notes="x" * 6001)
        with self.assertRaisesRegex(ValueError, "No details were omitted"):
            enormous.scribe_context()

    def test_invalid_environment_source_and_optional_metadata_are_handled(self):
        for arguments in ({"environment": "Space"}, {"source": "untrusted"}, {"roll_initiative": "yes"}):
            with self.subTest(arguments=arguments), self.assertRaises(ValueError):
                generate_encounter([self.template], rng=NoRolls(), **arguments)
        malformed_optional = replace(self.template, sheet_json='{"feats": null, "computed": null}')
        draft = generate_encounter([malformed_optional], quantity="1", rng=Random(1))
        self.assertEqual(draft.creatures, (malformed_optional,))
        self.assertEqual(draft.fighters[0].init_mod, 2)


if __name__ == "__main__":
    unittest.main()
