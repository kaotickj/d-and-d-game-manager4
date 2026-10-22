"""Legacy feat names do not stand in for complete SRD prerequisites."""
from copy import deepcopy
import unittest
from unittest.mock import patch

from dndgm4.advancement import _qualifies, advance_character
from dndgm4.build_rules import PREREQUISITES, feat_review, prerequisite_failures
from dndgm4.character_sheet import load_sheet
from dndgm4.multiclass import (
    advance_multiclass, default_multiclass_choices, establish_history,
    multiclass_requirements,
)
from tests.test_feat_grants import SCORES, character, reviewed_choices


class PrerequisiteChainTests(unittest.TestCase):
    def test_incomplete_legacy_chain_fails_even_when_immediate_feat_is_owned(self):
        for feat, owned, missing, bab in (
            ("Great Cleave", {"Cleave"}, "Power Attack", 4),
            ("Spring Attack", {"Mobility"}, "Dodge", 4),
            ("Manyshot", {"Rapid Shot"}, "Point Blank Shot", 6),
        ):
            with self.subTest(feat=feat):
                scores = {**SCORES, "dexterity": 17}
                self.assertIn(f"{feat} requires {missing}.",
                              prerequisite_failures(feat, owned, scores, bab))
                self.assertFalse(_qualifies(feat, owned, scores, bab))
                self.assertTrue(_qualifies(feat, owned | {missing}, scores, bab))

    def test_owned_prerequisite_must_still_meet_its_ability_requirement(self):
        self.assertTrue(_qualifies("Precise Shot", {"Point Blank Shot"}, SCORES, 1))
        # Exercise an inherited ability requirement independently of the root.
        with patch.dict(PREREQUISITES, {"Precise Shot": (None, 0, "Rapid Shot", 0)}):
            failures = prerequisite_failures(
                "Precise Shot", {"Rapid Shot", "Point Blank Shot"},
                {**SCORES, "dexterity": 12}, 1)
        self.assertEqual(failures, ["Precise Shot requires Dexterity 13+."])

    def test_ability_and_bab_thresholds_are_independent(self):
        owned = {"Rapid Shot", "Point Blank Shot"}
        self.assertEqual(prerequisite_failures("Manyshot", owned,
                         {**SCORES, "dexterity": 16}, 5),
                         ["Manyshot requires Dexterity 17+.",
                          "Manyshot requires base attack bonus +6."])
        self.assertTrue(_qualifies("Manyshot", owned,
                                  {**SCORES, "dexterity": 17}, 6))

    def test_first_level_review_uses_the_same_complete_chain(self):
        feats = ["Cleave", "Great Cleave"]
        self.assertIn("Great Cleave requires Power Attack.", feat_review(
            feats, SCORES, class_name="Fighter", race="Elf", bab=4))
        with self.assertRaisesRegex(ValueError, "requires Power Attack"):
            feat_review(feats, SCORES, class_name="Fighter", race="Elf",
                        bab=4, strict=True)

    def test_same_level_chain_is_order_independent_and_inputs_are_preserved(self):
        feats = ["Great Cleave", "Cleave", "Power Attack"]
        scores = deepcopy(SCORES)
        self.assertEqual(feat_review(feats, scores, class_name="Fighter",
                                     race="Human", bab=4, strict=True), [])
        self.assertEqual(feats, ["Great Cleave", "Cleave", "Power Attack"])
        self.assertEqual(scores, SCORES)

    def test_single_class_rejects_legacy_chain_and_accepts_same_level_chain(self):
        original = character(level=3, feats=["Cleave"])
        before = original.sheet_json
        choices = reviewed_choices(original)
        choices["feats"] = ["Great Cleave"]
        with self.assertRaisesRegex(ValueError, "prerequisites"):
            advance_character(original, choices)
        self.assertEqual(original.sheet_json, before)
        original = character(level=5)
        choices = reviewed_choices(original)
        choices["feats"] = ["Mobility", "Dodge"]
        self.assertEqual(load_sheet(advance_character(original, choices))["feats"],
                         ["Mobility", "Dodge"])

    def test_multiclass_uses_shared_chain_check(self):
        original = establish_history(character(level=3, feats=["Cleave"]),
            {"Fighter": 3}, review_ack=True, no_racial_hd_ack=True,
            review_notes="DM confirmed class history and existing totals")
        req = multiclass_requirements(original, "Fighter")
        choices = default_multiclass_choices(original, "Fighter")
        choices.update(hp_roll=req["hit_die"], review_ack=True,
                       class_notes="Reviewed gained features", restriction_notes="Reviewed restrictions")
        choices["feat_selections"] = {"general": [], "fighter_bonus": ["Great Cleave"],
                                      "monk_bonus": [], "wizard_bonus": []}
        with self.assertRaisesRegex(ValueError, "prerequisites"):
            advance_multiclass(original, "Fighter", choices)

    def test_monk_bonus_exception_and_automatic_grants_remain_supported(self):
        monk = character("Monk", level=5)
        choices = reviewed_choices(monk)
        choices["feats"] = ["Improved Trip", "Alertness"]
        # No Combat Expertise is needed for this monk bonus selection.
        self.assertIn("Improved Trip", load_sheet(advance_character(monk, choices))["feats"])
        self.assertEqual(feat_review(["Track", "Dodge"], SCORES,
                                    class_name="Ranger", race="Elf", bab=1, strict=True), [])

    def test_cycles_fail_closed_without_recursion_or_input_mutation(self):
        owned = {"Dodge", "Mobility"}
        with patch.dict(PREREQUISITES, {"Dodge": ("dexterity", 13, "Mobility", 0)}):
            self.assertEqual(prerequisite_failures("Mobility", owned, SCORES, 1),
                             ["Mobility: cyclic prerequisite rules require DM review."])
            self.assertFalse(_qualifies("Mobility", owned, SCORES, 1))
        self.assertEqual(owned, {"Dodge", "Mobility"})

    def test_unknown_rules_and_unmodeled_weapon_focus_proficiency_are_honest(self):
        self.assertFalse(_qualifies("Mystery feat", set(), SCORES, 20))
        self.assertEqual(prerequisite_failures("Mystery feat", set(), SCORES, 20),
                         ["Unverified feat or prerequisites: Mystery feat (DM review)."])
        self.assertIn("Weapon Focus requires a chosen weapon and proficiency confirmation (DM review).",
                      feat_review(["Weapon Focus"], SCORES, class_name="Fighter",
                                  race="Elf", bab=1, strict=True))


if __name__ == "__main__":
    unittest.main()
