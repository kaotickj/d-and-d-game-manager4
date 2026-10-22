"""SRD table boundaries and reviewed higher-level sheet transactions."""
from dataclasses import replace
import json
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
import unittest

from dndgm4.models import Creature
from dndgm4.spell_progression import (
    GROUPS, build_spell_candidate, caster_profiles, load_spell_plan,
    progression_profile, save_spell_candidate,
)
from dndgm4.spell_tables import BASE_SLOTS, KNOWN_LIMITS
from dndgm4.storage import CreatureRepository


def empty_plan():
    return {group: {} for group in GROUPS}


class SpellProgressionTests(unittest.TestCase):
    def wizard(self, **changes):
        creature = Creature(name="Ayla", character_class="Wizard", level=5,
                            intelligence=18, notes="Keep secrets", max_hit_points=22,
                            sheet_json=json.dumps({"class": "Wizard", "background": "Keep biography",
                                "spellbook": {"casting_class": "Wizard", "spellbook": {"1": ["Magic Missile"]}},
                                "inventory": [{"name": "Old staff"}]}))
        return replace(creature, **changes)

    def test_all_tables_have_twenty_rows_and_keep_zero_distinct_from_absent(self):
        for name, table in BASE_SLOTS.items():
            self.assertEqual(len(table), 20, name)
        self.assertIsNone(BASE_SLOTS["Bard"][0][1])
        self.assertEqual(BASE_SLOTS["Bard"][1][1], 0)
        self.assertEqual(KNOWN_LIMITS["Bard"][1][1], 2)
        self.assertEqual(progression_profile("Bard", 1, 18)["slots"]["1"], 0)
        self.assertEqual(progression_profile("Bard", 2, 18)["slots"]["1"], 1)

    def test_wizard_sorcerer_unlock_and_cleric_domain_are_separate(self):
        self.assertEqual(progression_profile("Wizard", 3, 16)["slots"]["2"], 2)
        self.assertFalse(progression_profile("Sorcerer", 3, 18)["unlocked"]["2"])
        self.assertEqual(progression_profile("Sorcerer", 4, 18)["slots"]["2"], 4)
        cleric = progression_profile("Cleric", 3, 16)
        self.assertEqual(cleric["slots"]["2"], 2)
        self.assertEqual(cleric["domain_slots"]["2"], 1)
        self.assertEqual(cleric["domain_slots"]["0"], 0)

    def test_paladin_wisdom_gate_and_zero_base_bonus_slots(self):
        self.assertEqual(progression_profile("Paladin", 3, 18)["slots"]["1"], 0)
        self.assertEqual(progression_profile("Paladin", 4, 10)["slots"]["1"], 0)
        self.assertEqual(progression_profile("Paladin", 4, 12)["slots"]["1"], 1)
        self.assertEqual(progression_profile("Ranger", 20, 18)["slots"]["4"], 4)

    def test_bonus_spells_do_not_add_cantrip_or_spells_known(self):
        profile = progression_profile("Sorcerer", 20, 30)
        self.assertEqual(profile["slots"]["0"], 6)
        self.assertEqual(profile["known_limits"]["9"], 3)
        self.assertEqual(profile["slots"]["9"], 7)

    def test_structured_multiclass_counts_use_class_level_not_total(self):
        mixed = self.wizard(character_class="Fighter / Wizard", level=7,
                            sheet_json=json.dumps({"class_levels": {"Fighter": 4, "Wizard": 3}}))
        self.assertEqual(caster_profiles(mixed)["Wizard"]["class_level"], 3)
        self.assertFalse(caster_profiles(mixed)["Wizard"]["unlocked"]["3"])
        with self.assertRaisesRegex(ValueError, "total"):
            caster_profiles(replace(mixed, level=8))

    def test_indexed_higher_spell_and_lower_spell_in_higher_slot(self):
        creature = self.wizard()
        plan = empty_plan()
        plan["spellbook"] = {"1": ["Magic Missile"], "3": ["Fireball"]}
        plan["prepared"] = {"3": ["Magic Missile", "Fireball"]}
        catalog = [{"class": "Sorcerer/Wizard", "level": 3, "name": "Fireball"}]
        result = build_spell_candidate(creature, "Wizard", plan, catalog=catalog, review_ack=True)
        before, after = json.loads(creature.sheet_json), json.loads(result.sheet_json)
        for key in before:
            self.assertEqual(before[key], after[key])
        self.assertEqual(after["spell_progression"]["Wizard"]["prepared"]["3"], ["Magic Missile", "Fireball"])
        self.assertEqual(result.max_hit_points, creature.max_hit_points)
        self.assertEqual(result.notes, creature.notes)

    def test_missing_source_custom_spell_and_wizard_book_are_rejected(self):
        plan = empty_plan()
        plan["spellbook"] = {"3": ["Fireball"]}
        with self.assertRaisesRegex(ValueError, "review note"):
            build_spell_candidate(self.wizard(), "Wizard", plan, review_ack=True)
        plan["prepared"] = {"1": ["Magic Missile"]}
        with self.assertRaisesRegex(ValueError, "spellbook first"):
            build_spell_candidate(self.wizard(), "Wizard", plan, review_ack=True, custom_review="SRD checked")

    def test_slot_limits_known_limits_and_class_rules(self):
        plan = empty_plan()
        plan["known"] = {"1": ["Mage Armor", "Magic Missile", "Shield"]}
        sorcerer = self.wizard(character_class="Sorcerer", level=1, charisma=16, sheet_json="{}")
        with self.assertRaisesRegex(ValueError, "spells known"):
            build_spell_candidate(sorcerer, "Sorcerer", plan, review_ack=True)
        plan = empty_plan()
        plan["prepared"] = {"1": ["Mage Armor"]}
        with self.assertRaisesRegex(ValueError, "Spontaneous"):
            build_spell_candidate(sorcerer, "Sorcerer", plan, review_ack=True)
        plan = empty_plan()
        plan["prepared"] = {"3": ["Fireball"] * 4}
        plan["spellbook"] = {"3": ["Fireball"]}
        with self.assertRaisesRegex(ValueError, "Too many spells prepared"):
            build_spell_candidate(self.wizard(), "Wizard", plan, review_ack=True, custom_review="checked")

    def test_custom_domain_preparation_requires_explicit_review(self):
        cleric = self.wizard(character_class="Cleric", level=3, wisdom=16, sheet_json="{}")
        plan = empty_plan()
        plan["domain_prepared"] = {"2": ["Spiritual Weapon"]}
        with self.assertRaisesRegex(ValueError, "review note"):
            build_spell_candidate(cleric, "Cleric", plan, review_ack=True)
        candidate = build_spell_candidate(cleric, "Cleric", plan, review_ack=True,
                                          custom_review="War domain source checked by DM")
        self.assertEqual(json.loads(candidate.sheet_json)["spell_progression"]["Cleric"]["domain_prepared"]["2"], ["Spiritual Weapon"])

    def test_invalid_values_do_not_silently_shorten_data(self):
        for value in (True, 0, 21):
            with self.assertRaises(ValueError):
                progression_profile("Wizard", value, 16)
        plan = empty_plan()
        plan["spellbook"] = {"10": ["Unknown"]}
        with self.assertRaises(ValueError):
            build_spell_candidate(self.wizard(), "Wizard", plan, review_ack=True)
        with self.assertRaisesRegex(ValueError, "Review"):
            build_spell_candidate(self.wizard(), "Wizard", empty_plan())

    def test_malformed_saved_groups_are_rejected_instead_of_shortened(self):
        for malformed in ({"10": ["KeepMe"]}, {"1": "Magic Missile"}):
            creature = self.wizard(sheet_json=json.dumps({"spell_progression": {"Wizard": {"spellbook": malformed}}}))
            with self.assertRaises(ValueError):
                load_spell_plan(creature, "Wizard")
        with self.assertRaisesRegex(ValueError, "unsupported fields"):
            load_spell_plan(self.wizard(sheet_json=json.dumps({"spell_progression": {"Wizard": {"future_data": "Keep"}}})), "Wizard")

    def test_learning_requires_casting_ability_but_retains_existing_known_spells(self):
        sorcerer = self.wizard(character_class="Sorcerer", level=4, charisma=10, sheet_json="{}")
        plan = empty_plan()
        plan["known"] = {"1": ["Magic Missile"]}
        with self.assertRaisesRegex(ValueError, "Learning"):
            build_spell_candidate(sorcerer, "Sorcerer", plan, review_ack=True)
        old_sheet = {"spell_progression": {"Sorcerer": {"known": {"1": ["Magic Missile"]}}}}
        retained = build_spell_candidate(replace(sorcerer, sheet_json=json.dumps(old_sheet)),
                                          "Sorcerer", plan, review_ack=True)
        self.assertEqual(load_spell_plan(retained, "Sorcerer")["known"]["1"], ["Magic Missile"])

    def test_atomic_stale_and_failed_save_preserve_all_existing_data(self):
        with TemporaryDirectory() as temporary:
            repo = CreatureRepository(Path(temporary) / "library.sqlite3")
            original = repo.save(self.wizard())
            plan = empty_plan()
            plan["spellbook"] = {"1": ["Magic Missile"]}
            candidate = build_spell_candidate(original, "Wizard", plan, review_ack=True)
            repo.save(replace(original, notes="Changed elsewhere"))
            with self.assertRaisesRegex(ValueError, "changed after"):
                save_spell_candidate(repo, original, candidate)
            current = repo.get(original.id)
            candidate = build_spell_candidate(current, "Wizard", plan, review_ack=True)
            with repo._connection() as db:
                db.execute("CREATE TRIGGER block_spell BEFORE UPDATE ON creatures BEGIN SELECT RAISE(ABORT, 'disk failure'); END")
            with self.assertRaises(sqlite3.Error):
                save_spell_candidate(repo, current, candidate)
            self.assertEqual(repo.get(original.id), current)

    def test_saved_plan_round_trip_and_forged_candidate_rejection(self):
        with TemporaryDirectory() as temporary:
            repo = CreatureRepository(Path(temporary) / "library.sqlite3")
            original = repo.save(self.wizard())
            plan = empty_plan()
            plan["spellbook"] = {"1": ["Magic Missile"]}
            candidate = build_spell_candidate(original, "Wizard", plan, review_ack=True)
            with self.assertRaises(ValueError):
                save_spell_candidate(repo, original, replace(candidate, level=6))
            saved = save_spell_candidate(repo, original, candidate)
            self.assertEqual(load_spell_plan(repo.get(original.id), "Wizard")["revision"], 1)
            self.assertEqual(saved.notes, original.notes)
            self.assertEqual(json.loads(saved.sheet_json)["spellbook"], json.loads(original.sheet_json)["spellbook"])


if __name__ == "__main__":
    unittest.main()
