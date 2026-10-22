"""Shared SRD feat prerequisites and automatic grants stay outside feat slots."""
from copy import deepcopy
from dataclasses import asdict, replace
import json
import unittest

from dndgm4.advancement import (
    _qualifies, advance_character, default_level_choices, level_up_requirements,
)
from dndgm4.build_rules import automatic_class_feats, feat_review
from dndgm4.character_sheet import TEMPLATES, allocate_default_skills, build_sheet, load_sheet, skill_budget
from dndgm4.creation import ABILITIES, build_character
from dndgm4.models import Creature


SCORES = dict.fromkeys(ABILITIES, 14)


def character(class_name="Fighter", level=1, feats=(), **overrides):
    sheet = {"class": class_name, "skills_half_ranks": {}, "feats": list(feats),
             "class_features": [], "background": "Keep the biography"}
    return Creature(name="Ayla", character_class=class_name, level=level,
                    race_type="Elf", strength=16, dexterity=overrides.get("dexterity", 14),
                    constitution=14, intelligence=14, wisdom=14, charisma=14,
                    max_hit_points=12, sheet_json=json.dumps(sheet))


def reviewed_choices(creature):
    choices = default_level_choices(creature)
    requirements = level_up_requirements(creature)
    choices.update(hp_roll=requirements["hit_die"], review_ack=True,
                   spell_notes="Reviewed spell selections and progression")
    for request in requirements["choice_requests"]:
        choices["class_choices"].setdefault(request["key"],
                                           request["options"][0] if request["options"] else "DM reviewed")
    return choices


class FeatGrantTests(unittest.TestCase):
    def test_dodge_requires_dexterity_13_in_shared_and_creation_checks(self):
        low = {**SCORES, "dexterity": 12}
        high = {**SCORES, "dexterity": 13}
        self.assertFalse(_qualifies("Dodge", set(), low, 1))
        self.assertTrue(_qualifies("Dodge", set(), high, 1))
        warnings = feat_review(["Dodge"], low, class_name="Fighter", race="Elf", bab=1)
        self.assertEqual(warnings, ["Dodge requires Dexterity 13+."])
        with self.assertRaisesRegex(ValueError, "Dexterity 13"):
            feat_review(["Dodge"], low, class_name="Fighter", race="Elf", bab=1, strict=True)
        self.assertEqual(feat_review(["Dodge"], high, class_name="Fighter", race="Elf", bab=1, strict=True), [])

    def test_same_level_dodge_mobility_chain_remains_legal_when_dexterity_qualifies(self):
        self.assertEqual(feat_review(["Dodge", "Mobility"], {**SCORES, "dexterity": 13},
                                     class_name="Fighter", race="Elf", bab=1, strict=True), [])
        with self.assertRaisesRegex(ValueError, "Dexterity 13"):
            feat_review(["Dodge", "Mobility"], {**SCORES, "dexterity": 12},
                        class_name="Fighter", race="Elf", bab=1, strict=True)

    def test_first_level_ranger_grant_does_not_use_a_general_slot(self):
        feats = ["Track", "Point Blank Shot"]
        before = list(feats)
        self.assertEqual(feat_review(feats, SCORES, class_name="Ranger", race="Elf", bab=1, strict=True), [])
        self.assertEqual(feats, before)
        self.assertEqual(feat_review(["Track", "Point Blank Shot", "Endurance"], SCORES,
                                     class_name="Ranger", race="Human", bab=1, strict=True), [])
        with self.assertRaisesRegex(ValueError, "first-level selections"):
            feat_review(["Track", "Point Blank Shot", "Endurance"], SCORES,
                        class_name="Ranger", race="Elf", bab=1, strict=True)

    def test_wizard_automatic_scribe_scroll_is_not_a_selection_or_unknown_warning(self):
        self.assertEqual(feat_review(["Scribe Scroll", "Improved Initiative"], SCORES,
                                     class_name="Wizard", race="Elf", strict=True), [])
        with self.assertRaisesRegex(ValueError, "first-level selections"):
            feat_review(["Scribe Scroll", "Improved Initiative", "Alertness"], SCORES,
                        class_name="Wizard", race="Elf", strict=True)

    def test_automatic_names_do_not_exempt_other_classes_or_duplicate_entries(self):
        with self.assertRaisesRegex(ValueError, "first-level selections"):
            feat_review(["Track", "Point Blank Shot"], SCORES,
                        class_name="Rogue", race="Elf", strict=True)
        with self.assertRaisesRegex(ValueError, "Duplicate"):
            feat_review(["Track", "Track"], SCORES, class_name="Ranger", race="Elf", strict=True)

    def test_strict_creation_sheet_can_record_track_and_its_full_general_selection(self):
        creature = build_character(name="Trailkeeper", race="Elf", character_class="Ranger",
                                   base=dict.fromkeys(ABILITIES, 12), method="manual")
        feats = ["Track", "Point Blank Shot"]
        saved = build_sheet(character=creature, class_name="Ranger",
                            ranks=allocate_default_skills(TEMPLATES["Ranger"], skill_budget("Ranger", creature.intelligence, "Elf")),
                            feats=feats, equipment=[], alignment="True Neutral", deity="",
                            languages=["Common"], appearance="", personality="", background="", strict_feats=True)
        self.assertEqual(load_sheet(saved)["feats"], feats)
        self.assertEqual(load_sheet(saved)["feat_review_warnings"], [])
        self.assertEqual(feats, ["Track", "Point Blank Shot"])
        self.assertEqual(creature.sheet_json, "")

    def test_advancement_dodge_options_and_manual_choice_use_the_shared_prerequisite(self):
        original = character(dexterity=12)
        self.assertNotIn("Dodge", level_up_requirements(original)["feat_options"])
        choices = reviewed_choices(original)
        choices["feats"] = ["Dodge"]
        with self.assertRaisesRegex(ValueError, "prerequisites"):
            advance_character(original, choices)
        qualified = replace(original, dexterity=13)
        self.assertIn("Dodge", level_up_requirements(qualified)["feat_options"])
        advanced = advance_character(qualified, choices)
        self.assertIn("Dodge", load_sheet(advanced)["feats"])

    def test_same_level_ability_increase_can_satisfy_dodge(self):
        original = character(level=11, dexterity=12)
        choices = reviewed_choices(original)
        choices.update(ability_increase="dexterity", feats=["Dodge", "Power Attack"])
        advanced = advance_character(original, choices)
        self.assertEqual(advanced.dexterity, 13)
        self.assertIn("Dodge", load_sheet(advanced)["feats"])

    def test_ranger_three_reserves_endurance_before_default_general_selection(self):
        already_owned = ("Point Blank Shot", "Improved Initiative", "Alertness", "Iron Will",
                         "Great Fortitude", "Lightning Reflexes", "Blind-Fight", "Combat Casting")
        original = character("Ranger", level=2, feats=already_owned)
        before = asdict(original)
        requirements = level_up_requirements(original)
        self.assertEqual(requirements["feat_slots"]["general"], 1)
        self.assertEqual(requirements["automatic_feats"], ["Endurance"])
        self.assertNotIn("Endurance", requirements["feat_options"])
        self.assertNotIn("Track", requirements["feat_options"])
        choices = reviewed_choices(original)
        self.assertEqual(choices["feats"], ["Run"])
        advanced = advance_character(original, choices)
        sheet = load_sheet(advanced)
        self.assertEqual(sheet["feats"].count("Endurance"), 1)
        self.assertEqual(sheet["advancement_history"][-1]["feats"], ["Run"])
        self.assertEqual(sheet["advancement_history"][-1]["automatic_feats"], ["Endurance"])
        self.assertEqual(asdict(original), before)

    def test_manual_general_choices_cannot_spend_a_slot_on_ranger_grants(self):
        original = character("Ranger", level=2)
        for feat in ("Endurance", "Track"):
            choices = reviewed_choices(original)
            choices["feats"] = [feat]
            with self.subTest(feat=feat), self.assertRaisesRegex(ValueError, "automatically granted"):
                advance_character(original, choices)

    def test_previously_selected_endurance_is_not_granted_twice(self):
        original = character("Ranger", level=2, feats=["Track", "Endurance"])
        self.assertEqual(level_up_requirements(original)["automatic_feats"], [])
        advanced = advance_character(original, reviewed_choices(original))
        sheet = load_sheet(advanced)
        self.assertEqual(sheet["feats"].count("Endurance"), 1)
        self.assertEqual(sheet["feats"].count("Track"), 1)
        self.assertEqual(sheet["advancement_history"][-1]["automatic_feats"], [])

    def test_cumulative_class_grants_are_known_without_rewriting_legacy_sheets(self):
        self.assertEqual(automatic_class_feats("Ranger", 1), ["Track"])
        self.assertEqual(automatic_class_feats("Ranger", 2), ["Track"])
        self.assertEqual(automatic_class_feats("Ranger", 3), ["Track", "Endurance"])
        original = character("Ranger", level=5)
        before = deepcopy(load_sheet(original))
        requirements = level_up_requirements(original)
        self.assertEqual(requirements["automatic_feats"], [])
        self.assertNotIn("Track", requirements["feat_options"])
        self.assertNotIn("Endurance", requirements["feat_options"])
        self.assertEqual(load_sheet(original), before)

    def test_endurance_remains_a_general_choice_for_other_classes(self):
        original = character("Rogue", level=2)
        choices = reviewed_choices(original)
        choices["feats"] = ["Endurance"]
        advanced = advance_character(original, choices)
        self.assertEqual(load_sheet(advanced)["feats"], ["Endurance"])
        self.assertEqual(load_sheet(advanced)["advancement_history"][-1]["automatic_feats"], [])


if __name__ == "__main__":
    unittest.main()
