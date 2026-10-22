"""Single-level advancement uses visible rolls, bounded choices, and no writes."""
from dataclasses import asdict, replace
import json
import unittest

from dndgm4.advancement import (
    CLASS_PROGRESSION, DEFAULT_BUILDS, advance_character, default_level_choices,
    default_progression_profile, level_up_requirements, needs_progression_profile,
)
from dndgm4.character_sheet import TEMPLATES
from dndgm4.models import Creature


class AdvancementTests(unittest.TestCase):
    def character(self, class_name="Fighter", level=1, **overrides):
        sheet = {"class": class_name, "skills_half_ranks": {}, "feats": [],
                 "class_features": [], "background": "Keep the biography",
                 "inventory": [{"name": "Sword", "quantity": 1}],
                 "spellbook": {"custom": "Keep spell choices"}, "homebrew": {"keep": True}}
        if class_name == "Expert":
            sheet["custom_class_skills"] = list(TEMPLATES["Expert"].class_skills)
        values = {"name": "Ayla", "id": "stable-id", "race_type": "Human",
                  "character_class": class_name, "level": level, "max_hit_points": 12,
                  "strength": 16, "dexterity": 14, "intelligence": 14, "wisdom": 14,
                  "constitution": 14, "charisma": 14, "notes": "Keep DM notes",
                  "created_at": "2000-01-01", "archived": False,
                  "sheet_json": json.dumps(sheet)}
        values.update(overrides)
        return Creature(**values)

    def choices(self, creature, profile=None):
        choices = default_level_choices(creature, profile=profile)
        choices.update(hp_roll=level_up_requirements(creature, profile=profile)["hit_die"],
                       hp_roll_detail="Recorded test roll", review_ack=True,
                       spell_notes="Reviewed spells and daily progression")
        requirements = level_up_requirements(creature, profile=profile)
        for request in requirements["choice_requests"]:
            choices["class_choices"].setdefault(request["key"],
                                               request["options"][0] if request["options"] else "GM reviewed selections")
        return choices

    def test_level_two_roll_and_record_preservation(self):
        original = self.character()
        before = asdict(original)
        choices = self.choices(original)
        advanced = advance_character(original, choices)
        self.assertEqual(advanced.level, 2)
        self.assertEqual(advanced.max_hit_points, 24)
        self.assertEqual(asdict(original), before)
        old_sheet, sheet = json.loads(original.sheet_json), json.loads(advanced.sheet_json)
        for key in ("background", "inventory", "spellbook", "homebrew"):
            self.assertEqual(sheet[key], old_sheet[key])
        for key in ("id", "notes", "armor_class", "race_type", "created_at", "archived"):
            self.assertEqual(getattr(advanced, key), getattr(original, key))
        self.assertEqual(sheet["advancement_history"][0]["hp_roll_detail"], "Recorded test roll")
        self.assertEqual(sheet["progression"]["base_attack_bonus"], 2)
        self.assertEqual(sheet["progression"]["base_saves"], {"fort": 3, "ref": 0, "will": 0})

    def test_every_core_and_npc_profile_can_advance_with_defaults_and_review(self):
        for name in CLASS_PROGRESSION:
            with self.subTest(class_name=name):
                original = self.character(name, kind="npc" if name not in (
                    "Barbarian", "Bard", "Cleric", "Druid", "Fighter", "Monk", "Paladin", "Ranger", "Rogue", "Sorcerer", "Wizard") else "pc")
                advanced = advance_character(original, self.choices(original))
                self.assertEqual(advanced.level, 2)
                self.assertEqual(json.loads(advanced.sheet_json)["progression"]["class"], name)

    def test_default_build_strategy_for_every_template(self):
        self.assertEqual(set(DEFAULT_BUILDS), set(TEMPLATES))
        for name, plan in DEFAULT_BUILDS.items():
            self.assertIn(plan["ability"], ("strength", "dexterity", "constitution", "intelligence", "wisdom", "charisma"))
            self.assertIsInstance(plan["skills"], tuple)

    def test_default_core_and_npc_builds_can_progress_to_twenty(self):
        for name in CLASS_PROGRESSION:
            with self.subTest(class_name=name):
                creature = self.character(name)
                for target in range(2, 21):
                    creature = advance_character(creature, self.choices(creature))
                    self.assertEqual(creature.level, target)
                self.assertEqual(len(json.loads(creature.sheet_json)["advancement_history"]), 19)

    def test_level_three_general_feat_and_level_four_ability(self):
        original = self.character(level=2)
        level3 = advance_character(original, self.choices(original))
        self.assertEqual(len(json.loads(level3.sheet_json)["feats"]), 1)
        level4 = advance_character(level3, self.choices(level3))
        self.assertEqual(level4.strength, level3.strength + 1)
        self.assertEqual(len(json.loads(level4.sheet_json)["feats"]), 2)
        self.assertEqual(len(json.loads(level4.sheet_json)["advancement_history"]), 2)

    def test_constitution_increase_applies_to_prior_levels(self):
        original = self.character(level=3, constitution=13)
        choices = self.choices(original)
        choices["ability_increase"] = "constitution"
        advanced = advance_character(original, choices)
        self.assertEqual(advanced.constitution, 14)
        self.assertEqual(advanced.max_hit_points - original.max_hit_points, 10 + 2 + 3)
        entry = json.loads(advanced.sheet_json)["advancement_history"][-1]
        self.assertEqual(entry["retroactive_constitution_hp"], 3)

    def test_intelligence_increase_grants_only_current_level_points(self):
        original = self.character("Wizard", level=3, intelligence=13)
        requirements = level_up_requirements(original)
        choices = self.choices(original)
        self.assertEqual(choices["ability_increase"], "intelligence")
        advanced = advance_character(original, choices)
        entry = json.loads(advanced.sheet_json)["advancement_history"][-1]
        self.assertEqual(entry["skill_points"], requirements["skill_points"] + 1)
        self.assertEqual(entry["skill_points"], 5)

    def test_minimum_one_hp_per_level(self):
        original = self.character("Wizard", constitution=1)
        choices = self.choices(original)
        choices["hp_roll"] = 1
        advanced = advance_character(original, choices)
        self.assertEqual(advanced.max_hit_points, original.max_hit_points + 1)

    def test_cross_class_half_rank_costs_one_point(self):
        original = self.character(intelligence=10, race_type="Elf")
        choices = self.choices(original)
        choices["skill_increases"] = {"Spellcraft": 1, "Ride": 2}
        advanced = advance_character(original, choices)
        ranks = json.loads(advanced.sheet_json)["skills_half_ranks"]
        self.assertEqual(ranks, {"Spellcraft": 1, "Ride": 2})

    def test_invalid_roll_allocation_ability_or_missing_review_is_rejected(self):
        original = self.character()
        for changes in ({"hp_roll": 0}, {"hp_roll": 11}, {"hp_roll": True},
                        {"skill_increases": {}}, {"skill_increases": {"Ride": 11}},
                        {"skill_increases": {"Ride": 100}}, {"skill_increases": {"Ride": True}},
                        {"ability_increase": "strength"}, {"review_ack": False},
                        {"feats": ["Power Attack", "Cleave"]}):
            with self.subTest(changes=changes):
                choices = self.choices(original)
                choices.update(changes)
                with self.assertRaises(ValueError):
                    advance_character(original, choices)

    def test_known_feat_prerequisite_and_duplicate_rejection(self):
        original = self.character(strength=10)
        choices = self.choices(original)
        choices["feats"] = ["Power Attack"]
        with self.assertRaisesRegex(ValueError, "prerequisites"):
            advance_character(original, choices)
        sheet = json.loads(original.sheet_json)
        sheet["feats"] = ["Blind-Fight"]
        original = replace(original, sheet_json=json.dumps(sheet))
        choices = self.choices(original)
        choices["feats"] = ["Blind-Fight"]
        with self.assertRaisesRegex(ValueError, "already"):
            advance_character(original, choices)

    def test_monk_bonus_feat_does_not_require_normal_prerequisites(self):
        original = self.character("Monk", level=5, intelligence=8)
        choices = self.choices(original)
        choices["feats"] = ["Alertness", "Improved Trip"]
        advanced = advance_character(original, choices)
        self.assertIn("Improved Trip", json.loads(advanced.sheet_json)["feats"])

    def test_weapon_focus_requires_a_weapon_and_records_the_parameter(self):
        original = self.character()
        choices = self.choices(original)
        choices["feats"] = ["Weapon Focus"]
        choices["feat_details"] = {}
        with self.assertRaisesRegex(ValueError, "weapon for Weapon Focus"):
            advance_character(original, choices)
        choices["feat_details"] = {"Weapon Focus": "longsword"}
        advanced = advance_character(original, choices)
        sheet = json.loads(advanced.sheet_json)
        self.assertIn("Weapon Focus (longsword)", sheet["feats"])
        self.assertEqual(sheet["advancement_history"][-1]["feat_details"], {"Weapon Focus": "longsword"})

    def test_existing_qualified_weapon_focus_is_not_selected_again(self):
        original = self.character()
        sheet = json.loads(original.sheet_json)
        sheet["feats"] = ["Weapon Focus (longsword)"]
        original = replace(original, sheet_json=json.dumps(sheet))
        self.assertNotIn("Weapon Focus", level_up_requirements(original)["feat_options"])
        self.assertNotIn("Weapon Focus", default_level_choices(original)["feats"])
        choices = self.choices(original)
        choices["feats"] = ["Weapon Focus"]
        choices["feat_details"] = {"Weapon Focus": "longsword"}
        with self.assertRaisesRegex(ValueError, "already"):
            advance_character(original, choices)

    def test_manual_profile_weapon_focus_needs_explicit_weapon(self):
        original = self.character("My Homebrew", level=2)
        profile = default_progression_profile(original)
        profile.update(bab_progression="full", good_saves=["fort"], class_skills=["Ride"])
        choices = self.choices(original, profile)
        choices["feats"] = ["Weapon Focus"]
        choices["feat_details"] = {}
        with self.assertRaisesRegex(ValueError, "weapon for Weapon Focus"):
            advance_character(original, choices)

    def test_wizard_requires_spell_input_and_saves_existing_spellbook(self):
        original = self.character("Wizard")
        choices = self.choices(original)
        choices["spell_notes"] = ""
        with self.assertRaisesRegex(ValueError, "spell selections"):
            advance_character(original, choices)
        choices["spell_notes"] = "Added spell choices; reviewed daily slots"
        advanced = advance_character(original, choices)
        sheet = json.loads(advanced.sheet_json)
        self.assertEqual(sheet["spellbook"], json.loads(original.sheet_json)["spellbook"])
        self.assertEqual(sheet["advancement_history"][-1]["spell_notes"], choices["spell_notes"])
        self.assertIn("Level 2: " + choices["spell_notes"], sheet["spell_notes"])

    def test_rogue_and_ranger_choice_requests(self):
        rogue = self.character("Rogue", level=9)
        requirements = level_up_requirements(rogue)
        self.assertEqual(requirements["choice_requests"][0]["key"], "special_ability_10")
        advanced = advance_character(rogue, self.choices(rogue))
        self.assertIn("Crippling Strike", json.loads(advanced.sheet_json)["advancement_choices"].values())
        ranger = self.character("Ranger")
        choices = self.choices(ranger)
        choices["class_choices"] = {}
        with self.assertRaisesRegex(ValueError, "Combat style"):
            advance_character(ranger, choices)

    def test_manual_profile_is_collected_and_reused_for_supplemental_class(self):
        original = self.character("Warlock")
        self.assertTrue(needs_progression_profile(original))
        profile = default_progression_profile(original)
        self.assertEqual(profile["hit_die"], 6)
        self.assertEqual(profile["bab_progression"], "")
        with self.assertRaisesRegex(ValueError, "progression profile"):
            level_up_requirements(original)
        profile.update(bab_progression="three_quarters", good_saves=["will"])
        choices = self.choices(original, profile)
        advanced = advance_character(original, choices)
        self.assertFalse(needs_progression_profile(advanced))
        self.assertEqual(json.loads(advanced.sheet_json)["advancement_profile"], profile)
        self.assertEqual(level_up_requirements(advanced)["hit_die"], 6)

    def test_homebrew_profile_works_without_claiming_srd_validation(self):
        original = self.character("My Homebrew")
        profile = default_progression_profile(original)
        profile.update(bab_progression="full", good_saves=["fort"], class_skills=["Ride"])
        advanced = advance_character(original, self.choices(original, profile))
        self.assertEqual(json.loads(advanced.sheet_json)["progression"]["profile_source"], "GM-confirmed")

    def test_additional_class_notes_are_recorded_without_losing_existing_features(self):
        original = self.character("Druid")
        sheet = json.loads(original.sheet_json)
        sheet["class_features"] = ["Nature sense"]
        original = replace(original, sheet_json=json.dumps(sheet))
        choices = self.choices(original)
        choices["class_notes"] = "Woodland stride; DM-reviewed terrain interaction"
        advanced = advance_character(original, choices)
        saved = json.loads(advanced.sheet_json)
        self.assertIn("Nature sense", saved["class_features"])
        self.assertIn("Level 2: " + choices["class_notes"], saved["class_features"])
        self.assertEqual(saved["advancement_history"][-1]["class_notes"], choices["class_notes"])
        self.assertEqual(json.loads(original.sheet_json)["class_features"], ["Nature sense"])

    def test_class_notes_are_optional_bounded_text(self):
        original = self.character()
        choices = self.choices(original)
        self.assertNotIn("class_notes", json.loads(advance_character(original, choices).sheet_json)["advancement_history"][-1])
        for notes in (None, [], "x" * 4001):
            with self.subTest(notes=str(notes)[:30]):
                choices["class_notes"] = notes
                with self.assertRaisesRegex(ValueError, "notes must be text"):
                    advance_character(original, choices)

    def test_monsters_multiclass_and_inconsistent_history_are_rejected(self):
        for original in (self.character(kind="monster"), self.character("Fighter/Wizard"),
                         self.character(level=20), self.character(sheet_json='{"class": "Wizard"}'),
                         self.character(sheet_json='{"skills_half_ranks": null}'),
                         self.character(sheet_json='{"advancement_history": [{"to_level": 4}]}')):
            with self.subTest(original=original):
                with self.assertRaises(ValueError):
                    level_up_requirements(original)

    def test_preview_and_defaults_never_mutate_the_source(self):
        original = self.character()
        before = asdict(original)
        level_up_requirements(original)
        default_level_choices(original)
        self.assertEqual(asdict(original), before)


if __name__ == "__main__":
    unittest.main()
