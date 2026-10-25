"""Explicit typed effects add suggestions without changing sheets or timers."""
from copy import deepcopy
from dataclasses import asdict
import unittest

from dndgm4.models import Creature
from dndgm4.equipment_rules import effective_stats
from dndgm4.spell_effects import CATALOG, preview_effects, validate_mechanics


def statistics(**changes):
    stats = {"ac": 16, "touch_ac": 12, "flat_footed_ac": 14,
             "armor_bonus": 2, "shield_bonus": 2, "attack_bonus": 5,
             "saves": {"fort": 4, "ref": 3, "will": 1},
             "warnings": ["Equipment limits"], "sources": ["equipment-source"],
             "components": {"dexterity": 2}, "manual_ac": 19}
    stats.update(changes)
    return stats


def timer(spell, *, target="hero", remaining=10, uid="effect-1", typed=True):
    result = {"id": uid, "name": spell, "target_id": target,
              "anchor_id": "caster", "remaining": remaining, "original": 10,
              "notes": "DM reviewed targets, duration and eligibility"}
    if typed:
        result["mechanics"] = {"version": 1, "spell": spell}
    return result


class SpellMechanicsTests(unittest.TestCase):
    def test_exact_metadata_contract_and_fresh_copy(self):
        for name in CATALOG:
            payload = {"version": 1, "spell": name}
            cleaned = validate_mechanics(payload)
            self.assertEqual(cleaned, payload)
            self.assertIsNot(cleaned, payload)
        for invalid in (None, [], {}, {"version": True, "spell": "Shield"},
                        {"version": 2, "spell": "Shield"},
                        {"version": 1, "spell": "Fireball"},
                        {"version": 1, "spell": ["Bless"]},
                        {"version": 1, "spell": "Shield", "bonus": 100}):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                validate_mechanics(invalid)

    def test_overlapping_armor_shield_and_bless_have_distinct_bonus_types(self):
        result = preview_effects(statistics(), [timer("Mage Armor"), timer("Shield"),
                                 timer("Bless")], "hero")
        self.assertEqual((result["ac"], result["flat_footed_ac"], result["touch_ac"]),
                         (20, 18, 12))
        self.assertEqual((result["armor_bonus"], result["shield_bonus"]), (4, 4))
        self.assertEqual(result["attack_bonus"], 6)
        self.assertEqual(result["fear_save_bonus"], 1)
        self.assertEqual(result["saves"], {"fort": 4, "ref": 3, "will": 1})
        self.assertEqual(len(result["active_effects"]), 3)
        for rule in CATALOG.values():
            self.assertIn(rule["source"], result["sources"])

    def test_duplicate_spells_do_not_stack_and_keep_separate_timer_descriptors(self):
        effects = [timer(name, uid=f"{name}-{index}") for name in CATALOG for index in (1, 2)]
        result = preview_effects(statistics(), effects, "hero")
        self.assertEqual((result["ac"], result["attack_bonus"]), (20, 6))
        self.assertEqual(len(result["active_effects"]), 3)
        self.assertEqual(len(result["suppressed_effects"]), 3)
        self.assertTrue(all("Duplicate" in item["reason"]
                            for item in result["suppressed_effects"]))
        # Expiry of one caster's timer leaves the other caster's bonus active.
        effects[0]["remaining"] = 0
        self.assertEqual(preview_effects(statistics(), effects, "hero")["attack_bonus"], 6)

    def test_equipped_armor_beats_mage_armor_but_shield_can_improve(self):
        base = statistics(ac=22, flat_footed_ac=20, armor_bonus=8)
        result = preview_effects(base, [timer("Mage Armor"), timer("Shield")], "hero")
        self.assertEqual((result["ac"], result["armor_bonus"], result["shield_bonus"]), (24, 8, 4))
        self.assertEqual(result["suppressed_effects"][0]["spell"], "Mage Armor")
        self.assertIn("equipped", result["suppressed_effects"][0]["reason"])
        equal = preview_effects(statistics(armor_bonus=4), [timer("Mage Armor")], "hero")
        self.assertEqual(equal["ac"], 16)
        self.assertEqual(equal["active_effects"], [])

    def test_target_expiration_and_legacy_names_do_not_activate_effects(self):
        effects = [timer("Shield", target="other"), timer("Mage Armor", remaining=0),
                   timer("Bless", target=""), timer("Shield", typed=False),
                   timer("Mage Armor", remaining=-1), timer("Bless", remaining=True)]
        result = preview_effects(statistics(), effects, "hero")
        self.assertEqual((result["ac"], result["attack_bonus"], result["fear_save_bonus"]),
                         (16, 5, 0))
        self.assertEqual(result["active_effects"], [])
        self.assertEqual(preview_effects(statistics(), [timer("Shield", target="")], "")["ac"], 16)

    def test_malformed_explicit_metadata_fails_even_on_another_target(self):
        for metadata in (None, {}, {"version": 1, "spell": "Unreviewed"}):
            effect = timer("Shield", target="other")
            effect["mechanics"] = metadata
            with self.subTest(metadata=metadata), self.assertRaises(ValueError):
                preview_effects(statistics(), [effect], "hero")

    def test_negative_dexterity_remains_in_touch_and_flat_footed_ac(self):
        base = statistics(ac=13, flat_footed_ac=13, touch_ac=9)
        result = preview_effects(base, [timer("Mage Armor"), timer("Shield")], "hero")
        self.assertEqual((result["ac"], result["flat_footed_ac"], result["touch_ac"]), (17, 17, 9))

    def test_bless_keeps_unavailable_attack_and_saves_unchanged(self):
        base = statistics(attack_bonus=None)
        result = preview_effects(base, [timer("Bless")], "hero")
        self.assertIsNone(result["attack_bonus"])
        self.assertEqual(result["saves"], base["saves"])
        self.assertEqual(result["fear_save_bonus"], 1)
        self.assertTrue(any("Fear eligibility" in warning for warning in result["warnings"]))

    def test_no_mutation_and_no_permanent_sheet_changes(self):
        creature = Creature(name="Hero", character_class="Fighter", race_type="Human",
                            level=3, strength=16, dexterity=14, armor_class=19,
                            sheet_json='{"inventory":[],"feats":[]}')
        original_creature = asdict(creature)
        profile = {"version": 1, "armor": "Leather", "shield": "Shield, heavy steel",
                   "weapon": "Longsword", "size": "Medium", "proficiency_confirmed": True,
                   "class_levels": {"Fighter": 3}, "weapon_focus_weapon": "",
                   "weapon_finesse": False,
                   "review_basis": {"class": "Fighter", "race": "Human", "level": 3}}
        base = effective_stats(creature, profile)
        effects = [timer("Shield")]
        before_base, before_effects = deepcopy(base), deepcopy(effects)
        result = preview_effects(base, effects, "hero")
        self.assertEqual(base, before_base)
        self.assertEqual(effects, before_effects)
        self.assertEqual(asdict(creature), original_creature)
        self.assertEqual(result["manual_ac"], 19)
        self.assertEqual((result["ac"], result["shield_bonus"]), (18, 4))
        result["components"].append({"changed_preview": -50})
        result["saves"]["Fortitude"] = -50
        result["warnings"].append("Changed preview")
        self.assertEqual(base, before_base)
        self.assertTrue(any("Magic missile" in warning for warning in result["warnings"]))


if __name__ == "__main__":
    unittest.main()
