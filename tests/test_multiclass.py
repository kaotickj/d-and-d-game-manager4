"""Per-class rounding, total-level benefits and stale-safe reviewed saves."""
from dataclasses import asdict, replace
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from dndgm4.character_sheet import TEMPLATES
from dndgm4.models import Creature
from dndgm4.multiclass import (
    CLASSES, advance_multiclass, class_history, combined_progression,
    default_multiclass_choices, establish_history, multiclass_requirements,
    save_multiclass_candidate,
)
from dndgm4.storage import CreatureRepository


class MulticlassTests(unittest.TestCase):
    def character(self, levels=None, **overrides):
        levels = levels or {"Fighter": 1}
        label = next(iter(levels)) if len(levels) == 1 else "Older mixed-class label"
        sheet = {"class": label, "skills_half_ranks": {}, "feats": [], "class_features": [],
                 "background": "Keep the biography", "inventory": [{"name": "Sword", "quantity": 1}],
                 "spellbook": {"keep": True}, "experience_points": 12000,
                 "homebrew": {"keep": [1, 2]}, "advancement_choices": {"past_choice": "Preserve it"}}
        creature = Creature(name="Élara", id="hero-id", character_class=label,
                            level=sum(levels.values()), constitution=14, intelligence=10,
                            strength=16, dexterity=17, wisdom=14, charisma=12, race_type="Elf",
                            max_hit_points=30, notes="Keep private notes", sheet_json=json.dumps(sheet))
        creature = replace(creature, **overrides)
        return creature

    def confirmed(self, levels=None, **overrides):
        levels = levels or {"Fighter": 1}
        creature = self.character(levels, **overrides)
        return establish_history(creature, levels, expert_skills=list(TEMPLATES["Expert"].class_skills) if "Expert" in levels else None,
                                 review_ack=True, no_racial_hd_ack=True,
                                 review_notes="Existing totals and XP/milestone/class restrictions reviewed with the DM")

    def choices(self, creature, selected, **changes):
        expert = list(TEMPLATES["Expert"].class_skills) if selected == "Expert" or "Expert" in class_history(creature) else None
        choices = default_multiclass_choices(creature, selected, expert_skills=expert)
        req = multiclass_requirements(creature, selected, expert_skills=expert)
        choices.update(hp_roll=req["hit_die"], hp_roll_detail="Explicit recorded die face", review_ack=True,
                       class_notes="DM reviewed all gained class features and interactions",
                       spell_notes="DM reviewed separate class spells and slots",
                       restriction_notes="DM confirms XP/milestone eligibility, alignment and class re-entry")
        for request in req["choice_requests"]:
            if not choices["class_choices"].get(request["key"]):
                choices["class_choices"][request["key"]] = request["options"][0] if request["options"] else "DM selected choice"
        choices.update(changes)
        return choices

    def test_history_confirmation_preserves_existing_record_and_optional_order(self):
        original = self.character({"Wizard": 1, "Fighter": 2})
        before = asdict(original)
        candidate = establish_history(original, {"Wizard": 1, "Fighter": 2}, level_order=["Fighter", "Wizard", "Fighter"],
                     review_ack=True, no_racial_hd_ack=True, review_notes="Prior progression reviewed")
        self.assertEqual(asdict(original), before)
        self.assertEqual(class_history(candidate, require_confirmed=True), {"Fighter": 2, "Wizard": 1})
        sheet = json.loads(candidate.sheet_json)
        self.assertEqual(sheet["multiclass_baseline"]["level_order"], ["Fighter", "Wizard", "Fighter"])
        self.assertEqual(candidate.max_hit_points, original.max_hit_points)
        for key in ("background", "inventory", "spellbook", "homebrew", "experience_points"):
            self.assertEqual(sheet[key], json.loads(original.sheet_json)[key])

    def test_history_rejects_wrong_totals_unsupported_classes_and_racial_ambiguity(self):
        original = self.character({"Fighter": 2})
        for levels in ({"Fighter": 1}, {"Fighter": True, "Wizard": 1}, {"Assassin": 2}, {}):
            with self.assertRaises(ValueError):
                establish_history(original, levels, review_ack=True, no_racial_hd_ack=True, review_notes="Review")
        with self.assertRaisesRegex(ValueError, "chronological"):
            establish_history(original, {"Fighter": 2}, level_order=["Wizard", "Wizard"], review_ack=True, no_racial_hd_ack=True, review_notes="Review")
        for field, value in (("racial_hit_dice", 2), ("level_adjustment", 1), ("ecl", 4)):
            sheet = json.loads(original.sheet_json)
            sheet[field] = value
            with self.assertRaisesRegex(ValueError, "racial|Racial"):
                establish_history(replace(original, sheet_json=json.dumps(sheet)), {"Fighter": 2},
                                  review_ack=True, no_racial_hd_ack=True, review_notes="Review")
        with self.assertRaisesRegex(ValueError, "Confirm"):
            advance_multiclass(original, "Wizard", {})

    def test_class_tables_round_separately_and_sum_all_saves(self):
        self.assertEqual(combined_progression({"Fighter": 1, "Wizard": 1, "Sorcerer": 1}),
                         {"base_attack_bonus": 1, "base_saves": {"fort": 2, "ref": 0, "will": 4}})
        original = self.confirmed({"Fighter": 1, "Wizard": 1})
        advanced = advance_multiclass(original, "Sorcerer", self.choices(original, "Sorcerer"))
        self.assertEqual(json.loads(advanced.sheet_json)["progression"]["base_attack_bonus"], 1)
        self.assertEqual(class_history(advanced, require_confirmed=True), {"Fighter": 1, "Sorcerer": 1, "Wizard": 1})

    def test_all_core_and_npc_classes_can_be_joined_or_advanced(self):
        for selected in CLASSES:
            with self.subTest(selected=selected):
                original = self.confirmed()
                advanced = advance_multiclass(original, selected, self.choices(original, selected))
                self.assertEqual(advanced.level, 2)
                self.assertEqual(class_history(advanced)[selected], 2 if selected == "Fighter" else 1)

    def test_new_class_uses_rolled_hp_and_ordinary_skill_budget(self):
        original = self.confirmed(intelligence=10, constitution=14)
        choices = self.choices(original, "Rogue", hp_roll=1)
        advanced = advance_multiclass(original, "Rogue", choices)
        entry = json.loads(advanced.sheet_json)["advancement_history"][-1]
        self.assertEqual(advanced.max_hit_points, original.max_hit_points + 3)
        self.assertEqual(entry["skill_points"], 8)
        self.assertEqual(entry["class_level"], 1)
        self.assertEqual(entry["hp_roll"], 1)
        low_con = self.confirmed(constitution=1)
        self.assertEqual(advance_multiclass(low_con, "Wizard", self.choices(low_con, "Wizard", hp_roll=1)).max_hit_points,
                         low_con.max_hit_points + 1)

    def test_ability_and_general_feat_follow_total_level_not_selected_class_level(self):
        original = self.confirmed({"Fighter": 1, "Wizard": 1})
        choices = self.choices(original, "Rogue")
        self.assertEqual(multiclass_requirements(original, "Rogue")["feat_slots"]["general"], 1)
        level3 = advance_multiclass(original, "Rogue", choices)
        self.assertEqual(len(json.loads(level3.sheet_json)["feats"]), 1)
        choices = self.choices(level3, "Wizard", ability_increase="constitution")
        level3 = replace(level3, constitution=13)
        level4 = advance_multiclass(level3, "Wizard", choices)
        entry = json.loads(level4.sheet_json)["advancement_history"][-1]
        self.assertEqual(level4.constitution, 14)
        self.assertEqual(entry["retroactive_constitution_hp"], 3)
        self.assertEqual(level4.max_hit_points - level3.max_hit_points, 4 + 2 + 3)

    def test_skill_cost_uses_current_class_and_cap_uses_any_class(self):
        original = self.confirmed({"Fighter": 2, "Wizard": 1})
        sheet = json.loads(original.sheet_json)
        sheet["skills_half_ranks"] = {"Ride": 12}
        original = replace(original, sheet_json=json.dumps(sheet))
        choices = self.choices(original, "Wizard", skill_increases={"Ride": 2}, ability_increase="strength")
        advanced = advance_multiclass(original, "Wizard", choices)
        self.assertEqual(json.loads(advanced.sheet_json)["skills_half_ranks"]["Ride"], 14)
        with self.assertRaisesRegex(ValueError, "rank cap"):
            advance_multiclass(original, "Wizard", {**choices, "skill_increases": {"Ride": 4}})
        sheet["skills_half_ranks"] = {"Spellcraft": 3}
        original = replace(original, sheet_json=json.dumps(sheet))
        advanced = advance_multiclass(original, "Wizard", self.choices(original, "Wizard", skill_increases={"Spellcraft": 4}))
        self.assertEqual(json.loads(advanced.sheet_json)["skills_half_ranks"]["Spellcraft"], 7)

    def test_encoded_feat_checks_use_combined_bab_and_bonus_slots_are_distinct(self):
        original = self.confirmed({"Fighter": 1, "Rogue": 1})
        choices = self.choices(original, "Wizard", feat_selections={"general": ["Weapon Finesse"]})
        advanced = advance_multiclass(original, "Wizard", choices)
        self.assertIn("Weapon Finesse", json.loads(advanced.sheet_json)["feats"])
        original = self.confirmed({"Wizard": 1, "Sorcerer": 1})
        choices = self.choices(original, "Adept", feat_selections={"general": ["Weapon Finesse"]})
        with self.assertRaisesRegex(ValueError, "combined BAB"):
            advance_multiclass(original, "Adept", choices)
        original = self.confirmed({"Fighter": 1, "Wizard": 1})
        choices = self.choices(original, "Fighter")
        self.assertEqual(len(choices["feat_selections"]["general"]), 1)
        self.assertEqual(len(choices["feat_selections"]["fighter_bonus"]), 1)
        duplicate = choices["feat_selections"]["fighter_bonus"][0]
        choices["feat_selections"]["general"] = [duplicate]
        with self.assertRaisesRegex(ValueError, "distinct"):
            advance_multiclass(original, "Fighter", choices)

    def test_missing_roll_skills_review_features_spells_or_restriction_notes_rejects(self):
        original = self.confirmed()
        choices = self.choices(original, "Wizard")
        for changes in ({"hp_roll": True}, {"hp_roll": 0}, {"hp_roll": 5}, {"review_ack": False},
                        {"skill_increases": {}}, {"class_notes": ""}, {"spell_notes": ""},
                        {"restriction_notes": ""}, {"ability_increase": "strength"}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                advance_multiclass(original, "Wizard", {**choices, **changes})

    def test_automatic_class_feats_do_not_consume_discretionary_slots(self):
        original = self.confirmed({"Fighter": 2})
        choices = self.choices(original, "Ranger", feat_selections={"general": ["Track"]})
        with self.assertRaisesRegex(ValueError, "automatically granted"):
            advance_multiclass(original, "Ranger", choices)
        advanced = advance_multiclass(original, "Ranger", self.choices(original, "Ranger"))
        sheet = json.loads(advanced.sheet_json)
        self.assertIn("Track", sheet["feats"])
        self.assertEqual(sheet["advancement_history"][-1]["automatic_feats"], ["Track"])
        original = self.confirmed({"Ranger": 2})
        advanced = advance_multiclass(original, "Ranger", self.choices(original, "Ranger"))
        self.assertIn("Endurance", json.loads(advanced.sheet_json)["feats"])

    def test_preserves_original_history_and_unrelated_sheet_and_character_fields(self):
        original = self.confirmed({"Fighter": 2})
        sheet = json.loads(original.sheet_json)
        sheet["advancement_history"] = [{"from_level": 1, "to_level": 2, "original": "Keep exactly"}]
        original = replace(original, sheet_json=json.dumps(sheet))
        advanced = advance_multiclass(original, "Rogue", self.choices(original, "Rogue"))
        after = json.loads(advanced.sheet_json)
        self.assertEqual(after["advancement_history"][0], sheet["advancement_history"][0])
        for key in ("inventory", "background", "spellbook", "homebrew", "experience_points", "advancement_choices"):
            self.assertEqual(after[key], sheet[key])
        for key in ("id", "name", "notes", "armor_class", "race_type", "kind", "created_at", "archived"):
            self.assertEqual(getattr(advanced, key), getattr(original, key))

    def test_expert_skills_are_explicit_and_fixed_and_max_total_is_twenty(self):
        original = self.confirmed()
        with self.assertRaisesRegex(ValueError, "ten distinct"):
            multiclass_requirements(original, "Expert")
        twenty = self.confirmed({"Fighter": 10, "Wizard": 10})
        with self.assertRaisesRegex(ValueError, "20"):
            multiclass_requirements(twenty, "Rogue")
        original = self.confirmed({"Expert": 1})
        altered = list(TEMPLATES["Expert"].class_skills)
        altered[-1] = "Bluff"
        with self.assertRaisesRegex(ValueError, "cannot be replaced"):
            multiclass_requirements(original, "Fighter", expert_skills=altered)

    def test_malformed_expert_skills_and_fractional_saved_scores_are_rejected(self):
        original = self.character({"Expert": 1})
        with self.assertRaisesRegex(ValueError, "ten distinct"):
            establish_history(original, {"Expert": 1}, expert_skills=[["Craft"]] * 10,
                              review_ack=True, no_racial_hd_ack=True, review_notes="Review")
        for attribute, value in (("strength", 13.5), ("max_hit_points", True), ("intelligence", 12.5)):
            original = self.character(**{attribute: value})
            with self.assertRaisesRegex(ValueError, "whole number"):
                establish_history(original, {"Fighter": 1}, review_ack=True, no_racial_hd_ack=True, review_notes="Review")

    def test_transactional_save_rejects_stale_and_tampered_candidates(self):
        with TemporaryDirectory() as folder:
            repo = CreatureRepository(Path(folder) / "library.sqlite3")
            baseline = repo.save(self.character())
            candidate = establish_history(baseline, {"Fighter": 1}, review_ack=True, no_racial_hd_ack=True, review_notes="Reviewed")
            saved = save_multiclass_candidate(repo, baseline, candidate)
            levelup = advance_multiclass(saved, "Rogue", self.choices(saved, "Rogue"))
            with self.assertRaisesRegex(ValueError, "draft changed"):
                save_multiclass_candidate(repo, saved, replace(levelup, notes="Unreviewed edits"))
            repo.save(replace(saved, notes="Changed in another editor"))
            with self.assertRaisesRegex(ValueError, "saved character changed"):
                save_multiclass_candidate(repo, saved, levelup)
            self.assertEqual(repo.get(saved.id).level, 1)
            self.assertEqual(repo.get(saved.id).notes, "Changed in another editor")

    def test_failed_sql_rolls_back_all_permanent_changes(self):
        with TemporaryDirectory() as folder:
            repo = CreatureRepository(Path(folder) / "library.sqlite3")
            baseline = repo.save(self.confirmed())
            candidate = advance_multiclass(baseline, "Rogue", self.choices(baseline, "Rogue"))
            with repo._connection() as db:
                db.execute("CREATE TRIGGER reject_multiclass BEFORE UPDATE ON creatures BEGIN SELECT RAISE(ABORT,'simulated failure'); END")
            import sqlite3
            with self.assertRaises(sqlite3.IntegrityError):
                save_multiclass_candidate(repo, baseline, candidate)
            self.assertEqual(repo.get(baseline.id), baseline)

    def test_mixed_core_build_advances_to_total_twenty_with_consistent_history(self):
        creature = self.confirmed()
        sequence = ("Fighter", "Wizard", "Rogue", "Cleric", "Ranger")
        for index in range(19):
            selected = sequence[index % len(sequence)]
            creature = advance_multiclass(creature, selected, self.choices(creature, selected))
            self.assertEqual(sum(class_history(creature, require_confirmed=True).values()), creature.level)
        self.assertEqual(creature.level, 20)
        self.assertEqual(len(json.loads(creature.sheet_json)["advancement_history"]), 19)
