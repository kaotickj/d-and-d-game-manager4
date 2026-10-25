"""Meaningful SRD examples, review gates, and calculator non-mutation."""
from copy import deepcopy
from dataclasses import replace
import json
import unittest

from dndgm4.equipment_rules import ARMOR, SHIELDS, WEAPONS, effective_stats, read_loadout, validate_loadout
from dndgm4.models import Creature


class EquipmentRulesTests(unittest.TestCase):
    def setUp(self):
        self.hero = Creature(name="Bran", character_class="Fighter", race_type="Human", level=4,
                             armor_class=27, strength=16, dexterity=18, constitution=14,
                             wisdom=12, charisma=14, sheet_json=json.dumps({"feats": []}))

    def profile(self, creature=None, **changes):
        creature = creature or self.hero
        result = {"version": 1, "armor": "None", "shield": "None", "weapon": "Longsword",
                  "size": "Medium", "proficiency_confirmed": True,
                  "class_levels": {"Fighter": creature.level}, "weapon_focus_weapon": "",
                  "weapon_finesse": False, "monk_ac_eligible": False,
                  "paladin_grace_eligible": False,
                  "review_basis": {"class": creature.character_class, "race": creature.race_type,
                                   "level": creature.level}}
        result.update(changes)
        return result

    def test_armor_and_shield_stack_but_cap_positive_dex_and_preserve_manual_ac(self):
        stats = effective_stats(self.hero, self.profile(armor="Full plate", shield="Shield, heavy steel"))
        self.assertEqual((stats["ac"], stats["touch_ac"], stats["flat_footed_ac"]), (21, 11, 20))
        self.assertEqual(stats["manual_ac"], 27)
        self.assertEqual(stats["armor_check_penalty"], -8)
        self.assertEqual(stats["max_dex"], 1)

    def test_negative_dex_remains_in_all_ac_modes_and_is_not_limited_by_armor(self):
        hero = replace(self.hero, dexterity=6)
        stats = effective_stats(hero, self.profile(hero, armor="Full plate"))
        self.assertEqual((stats["ac"], stats["touch_ac"], stats["flat_footed_ac"]), (16, 8, 16))

    def test_small_size_affects_ac_attack_and_damage_dice(self):
        stats = effective_stats(self.hero, self.profile(size="Small"))
        self.assertEqual(stats["ac"], 15)
        self.assertEqual(stats["attack_bonus"], 8)
        self.assertEqual(stats["damage_expression"], "1d6+3")

    def test_multiclass_rounds_each_class_separately_and_stacks_good_save_bases(self):
        hero = replace(self.hero, level=3, character_class="Cleric / Rogue / Wizard",
                       strength=10, dexterity=10, constitution=10, wisdom=10)
        stats = effective_stats(hero, self.profile(hero, class_levels={"Cleric": 1, "Rogue": 1, "Wizard": 1}))
        self.assertEqual(stats["attack_bonus"], 0)
        self.assertEqual(stats["saves"], {"Fortitude": 2, "Reflex": 2, "Will": 4})

    def test_two_handed_strength_rounds_down_bonus_but_not_penalty(self):
        stats = effective_stats(self.hero, self.profile(weapon="Greatsword"))
        self.assertEqual(stats["damage_expression"], "2d6+4")
        weak = replace(self.hero, strength=6)
        self.assertEqual(effective_stats(weak, self.profile(weak, weapon="Greatsword"))["damage_expression"], "2d6-2")

    def test_regular_bow_ignores_positive_strength_but_retains_penalty(self):
        profile = self.profile(weapon="Longbow")
        stats = effective_stats(self.hero, profile)
        self.assertEqual(stats["attack_bonus"], 8)
        self.assertEqual(stats["damage_expression"], "1d8")
        self.assertEqual((stats["threat_min"], stats["multiplier"]), (20, 3))
        weak = replace(self.hero, strength=6)
        self.assertEqual(effective_stats(weak, self.profile(weak, weapon="Longbow"))["damage_expression"], "1d8-2")

    def test_racial_progression_and_disagreement_with_saved_class_history_are_rejected(self):
        for extra in ({"racial_hit_dice": 2}, {"level_adjustment": 1},
                      {"ecl": 6}, {"class_levels": {"Wizard": 4}}):
            with self.subTest(extra=extra):
                hero = replace(self.hero, sheet_json=json.dumps({"feats": [], **extra}))
                with self.assertRaises(ValueError):
                    effective_stats(hero, self.profile(hero))

    def test_crossbow_never_adds_strength(self):
        for strength in (6, 18):
            hero = replace(self.hero, strength=strength)
            stats = effective_stats(hero, self.profile(hero, weapon="Crossbow, light"))
            self.assertEqual(stats["damage_expression"], "1d8")
            self.assertEqual((stats["threat_min"], stats["multiplier"]), (19, 2))

    def test_finesse_requires_owned_feat_eligible_weapon_and_applies_shield_penalty(self):
        profile = self.profile(weapon="Rapier", weapon_finesse=True, shield="Shield, heavy wooden")
        with self.assertRaisesRegex(ValueError, "saved Weapon Finesse"):
            effective_stats(self.hero, profile)
        hero = replace(self.hero, sheet_json=json.dumps({"feats": ["Weapon Finesse"]}))
        stats = effective_stats(hero, profile)
        self.assertEqual(stats["attack_bonus"], 6)  # BAB4 +Dex4 -shield2
        self.assertEqual(stats["damage_expression"], "1d6+3")
        with self.assertRaisesRegex(ValueError, "does not apply"):
            effective_stats(hero, self.profile(hero, weapon_finesse=True))

    def test_weapon_focus_parameter_is_required_and_does_not_stack_duplicates(self):
        hero = replace(self.hero, sheet_json=json.dumps({"feats": ["Weapon Focus (longsword)"] * 2}))
        self.assertEqual(effective_stats(hero, self.profile(hero))["attack_bonus"], 7)
        self.assertEqual(effective_stats(hero, self.profile(hero, weapon_focus_weapon="Longsword"))["attack_bonus"], 8)
        with self.assertRaisesRegex(ValueError, "requires its saved feat"):
            effective_stats(hero, self.profile(hero, weapon_focus_weapon="Rapier"))
        bare = replace(self.hero, sheet_json=json.dumps({"feats": ["Weapon Focus"]}))
        stats = effective_stats(bare, self.profile(bare, weapon_focus_weapon="Rapier"))
        self.assertEqual(stats["attack_bonus"], 7)
        self.assertTrue(any("does not match" in warning for warning in stats["warnings"]))

    def test_constant_feat_bonuses_apply_once_and_ignore_old_computed_fields(self):
        hero = replace(self.hero, sheet_json=json.dumps({"feats": ["Improved Initiative"] * 2 +
            ["Great Fortitude", "Lightning Reflexes", "Iron Will"],
            "computed": {"initiative": 999, "armor_class": 999}}))
        stats = effective_stats(hero, self.profile(hero))
        self.assertEqual(stats["initiative"], 8)
        self.assertEqual(stats["saves"], {"Fortitude": 8, "Reflex": 7, "Will": 4})

    def test_monk_bonus_requires_explicit_conditions_and_no_armor_or_shield(self):
        hero = replace(self.hero, character_class="Monk", level=10, wisdom=16)
        profile = self.profile(hero, class_levels={"Monk": 10})
        self.assertEqual(effective_stats(hero, profile)["ac"], 14)
        profile["monk_ac_eligible"] = True
        stats = effective_stats(hero, profile)
        self.assertEqual((stats["ac"], stats["touch_ac"], stats["flat_footed_ac"]), (19, 19, 15))
        self.assertEqual(effective_stats(hero, dict(profile, armor="Leather"))["ac"], 16)
        self.assertEqual(effective_stats(hero, dict(profile, shield="Shield, light wooden"))["ac"], 15)
        low_wisdom = replace(hero, wisdom=6)
        self.assertEqual(effective_stats(low_wisdom, profile)["ac"], 16)  # levelbonus2, noWispenalty

    def test_divine_grace_requires_level_and_confirmation_and_uses_positive_cha_only(self):
        hero = replace(self.hero, character_class="Paladin", level=2)
        profile = self.profile(hero, class_levels={"Paladin": 2})
        self.assertEqual(effective_stats(hero, profile)["saves"]["Fortitude"], 5)
        profile["paladin_grace_eligible"] = True
        self.assertEqual(effective_stats(hero, profile)["saves"]["Fortitude"], 7)
        self.assertEqual(effective_stats(replace(hero, charisma=6), profile)["saves"]["Fortitude"], 5)
        novice = replace(hero, level=1)
        with self.assertRaisesRegex(ValueError, "two Paladin"):
            validate_loadout(self.profile(novice, class_levels={"Paladin": 1}, paladin_grace_eligible=True), novice)

    def test_unconfirmed_proficiency_suppresses_attack_suggestions(self):
        stats = effective_stats(self.hero, self.profile(proficiency_confirmed=False))
        self.assertIsNone(stats["attack_bonus"])
        self.assertIsNone(stats["damage_expression"])
        self.assertTrue(any("proficiency" in warning for warning in stats["warnings"]))

    def test_weapon_feat_base_attack_prerequisite_is_checked(self):
        hero = replace(self.hero, character_class="Wizard", level=1,
                       sheet_json=json.dumps({"feats": ["Weapon Focus", "Weapon Finesse"]}))
        for choice in ({"weapon_focus_weapon": "Dagger"}, {"weapon_finesse": True}):
            with self.subTest(choice=choice), self.assertRaisesRegex(ValueError, "base attack bonus"):
                effective_stats(hero, self.profile(hero, class_levels={"Wizard": 1}, weapon="Dagger", **choice))

    def test_stale_review_rejected_but_can_be_opened_structurally(self):
        profile = self.profile()
        for hero in (replace(self.hero, level=5), replace(self.hero, race_type="Elf"),
                     replace(self.hero, character_class="Wizard")):
            with self.subTest(hero=hero), self.assertRaisesRegex(ValueError, "review the loadout again"):
                validate_loadout(profile, hero)
        self.assertEqual(validate_loadout(profile)["review_basis"], profile["review_basis"])

    def test_unknown_invalid_unsafe_or_incompatible_profiles_rejected(self):
        changes = [{"version": True}, {"armor": "Magic plate"}, {"weapon": []},
                   {"shield": "Buckler"}, {"size": "Large"}, {"class_levels": {}},
                   {"class_levels": {"Fighter": True}}, {"class_levels": {"Fighter": 21}},
                   {"class_levels": {"Fighter": 3}}, {"class_levels": {"Assassin": 4}},
                   {"proficiency_confirmed": 1}, {"monk_ac_eligible": True},
                   {"weapon": "Greatsword", "shield": "Shield, heavy steel"},
                   {"unknown": "cannot ignore"}, {"review_basis": {}},
                   {"weapon_focus_weapon": "Magic longsword"}]
        for change in changes:
            with self.subTest(change=change), self.assertRaises(ValueError):
                validate_loadout(self.profile(**change), self.hero)

    def test_monster_racial_hd_and_bad_sheets_rejected(self):
        for hero in (replace(self.hero, kind="monster"), replace(self.hero, sheet_json="bad"),
                     replace(self.hero, sheet_json='{"feats": "Weapon Finesse"}')):
            with self.subTest(hero=hero), self.assertRaises(ValueError):
                effective_stats(hero, self.profile(hero))

    def test_strict_sheet_reader_rejects_ambiguous_nonfinite_oversized_and_unicode_data(self):
        invalid = ['{"feats": [], "feats": ["Improved Initiative"]}',
                   '{"nested": {"a":1,"a":2}}', '{"number": NaN}',
                   '{"number": Infinity}', '{"number": 1e999}',
                   '{"text":"\\ud800"}', '{"\\ud800": 1}',
                   " " * 262145, '{"text":"\ud800"}', "[" * 2000]
        for raw in invalid:
            hero = replace(self.hero, sheet_json=raw)
            with self.subTest(raw=repr(raw[:30])):
                with self.assertRaises(ValueError):
                    effective_stats(hero, self.profile(hero))
                with self.assertRaises(ValueError):
                    read_loadout(hero)

    def test_read_loadout_preserves_absence_and_rejects_present_invalid_or_stale_profiles(self):
        self.assertIsNone(read_loadout(self.hero))
        profile = self.profile()
        hero = replace(self.hero, sheet_json=json.dumps({"combat_loadout": profile, "feats": []}))
        result = read_loadout(hero)
        self.assertEqual(result, profile)
        result["class_levels"]["Fighter"] = 20
        self.assertEqual(read_loadout(hero), profile)
        with self.assertRaises(ValueError):
            read_loadout(replace(hero, race_type="Elf"))
        with self.assertRaises(ValueError):
            read_loadout(replace(hero, sheet_json='{"combat_loadout": null}'))

    def test_explicit_class_levels_not_feature_prose_determine_progressions(self):
        hero = replace(self.hero, character_class="Fighter / Paladin", sheet_json=json.dumps({
            "class_features": ["Divine Grace"], "computed": {"saves": {"Fortitude": 999}}}))
        stats = effective_stats(hero, self.profile(hero, class_levels={"Wizard": 4}))
        self.assertEqual(stats["saves"]["Fortitude"], 3)
        self.assertEqual(stats["attack_bonus"], 5)

    def test_no_input_or_catalog_mutation_and_sources_limits_visible(self):
        profile = self.profile()
        before = deepcopy(profile)
        catalogs = deepcopy((ARMOR, SHIELDS, WEAPONS))
        hero_json = self.hero.sheet_json
        normalized = validate_loadout(profile, self.hero)
        normalized["class_levels"]["Fighter"] = 20
        stats = effective_stats(self.hero, profile)
        self.assertEqual(profile, before)
        self.assertEqual(self.hero.sheet_json, hero_json)
        self.assertEqual((ARMOR, SHIELDS, WEAPONS), catalogs)
        self.assertTrue(all(source.startswith("https://www.d20srd.org/") for source in stats["sources"]))
        self.assertTrue(stats["components"])
        self.assertTrue(any("Prestige classes" in item for item in stats["unsupported"]))


if __name__ == "__main__":
    unittest.main()
