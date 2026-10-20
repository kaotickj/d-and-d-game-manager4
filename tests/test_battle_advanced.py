"""Regression tests for SRD 3.5 extensions. No GUI required."""
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from dndgm4.battle_rules import Fighter
from dndgm4.battle_advanced import AdvancedBattle, AdvancedBattleStore
from dndgm4.battle_srd35 import (
    attack, roll_damage, saving_throw, skill_check, duration_to_rounds
)
from dndgm4.srd35_spells import SpellCatalog, parse_spell_list, download_srd_catalog, LISTS


class FixedRoller:
    def __init__(self, rolls):
        self.rolls = iter(rolls)
    def randint(self, a, b):
        number = next(self.rolls)
        assert a <= number <= b, (a, b, number)
        return number


def encounter():
    battle = AdvancedBattle()
    battle.add(Fighter(uid="mage", name="Wizard", hp=15, max_hp=15,
                       init_mod=3, dex_mod=3))
    battle.add(Fighter(uid="ogre", name="Ogre", hp=30, max_hp=30,
                       init_mod=0, dex_mod=0, ac=16))
    battle.set_initiative("mage", 18)
    battle.set_initiative("ogre", 10)
    battle.begin()
    return battle


class ClockTests(unittest.TestCase):
    def test_expiration_on_originating_initiative_not_target_end(self):
        b = encounter()
        uid = b.add_effect("Glitterdust", target_id="ogre",
                           anchor_id="mage", duration=2)
        self.assertEqual(b.clock_label(), "00:00")
        b.advance()  # ogre starts; its condition does not expire here
        self.assertEqual(b.effects[0]["remaining"], 2)
        b.advance()  # mage starts R2
        self.assertEqual(b.round, 2)
        self.assertEqual(b.effects[0]["remaining"], 1)
        self.assertEqual(b.clock_label(), "00:06")
        b.advance()  # ogre R2
        self.assertEqual(len(b.effects), 1)
        b.advance()  # just before mage R3, effect expires
        self.assertEqual(len(b.effects), 0)
        self.assertTrue(b.undo())
        self.assertEqual(b.effects[0]["remaining"], 1)
        self.assertEqual(b.current_id, "ogre")

    def test_duration_units_and_surprise_time(self):
        self.assertEqual(duration_to_rounds(1, "minutes"), 10)
        self.assertEqual(duration_to_rounds(1, "hours"), 600)
        b = encounter()
        b.set_spell_slots("mage", 3, 2)
        b.use_spell_slot("mage", 3, "Fireball")
        self.assertEqual(b.spell_slots["mage"]["3"], [2, 1])
        self.assertTrue(b.undo())
        self.assertEqual(b.spell_slots["mage"]["3"], [2, 0])

    def test_action_budget(self):
        b = encounter()
        b.spend_action("standard")
        b.spend_action("move")
        with self.assertRaisesRegex(ValueError, "exhausted"):
            b.spend_action("move")
        with self.assertRaises(ValueError):
            b.spend_action("full")
        b.advance()
        self.assertEqual(b.action_state, {})
        b.spend_action("full")
        with self.assertRaises(ValueError):
            b.spend_action("standard")

    def test_persistence_compatible_old_v1_and_new(self):
        with TemporaryDirectory() as folder:
            store = AdvancedBattleStore(Path(folder) / "library.sqlite3")
            b = encounter()
            b.add_effect("Bless", anchor_id="mage", duration=1, unit="minutes")
            b.set_spell_slots("mage", 1, 4, 2)
            b.spend_action("standard")
            store.save(b)
            loaded = store.load()
            self.assertIsInstance(loaded, AdvancedBattle)
            self.assertEqual(loaded.effects[0]["remaining"], 10)
            self.assertEqual(loaded.spell_slots["mage"]["1"], [4, 2])
            self.assertEqual(loaded.action_state, {"standard": 1})
            old = b.snapshot()
            for key in ("effects", "spell_slots", "action_state", "had_surprise"):
                old.pop(key, None)
            loaded_old = AdvancedBattle.from_dict({"version": 1, **old})
            self.assertEqual(loaded_old.effects, [])
            self.assertEqual(loaded_old.spell_slots, {})

    def test_no_malformed_effect_or_slot_preserved(self):
        b = encounter()
        raw = {"version": 1, **b.snapshot()}
        raw["effects"] = [dict(id="e", name="Test", target_id="bogus",
                               anchor_id="mage", remaining=1, original=1, notes="")]
        with self.assertRaises(ValueError):
            AdvancedBattle.from_dict(raw)
        raw = {"version": 1, **b.snapshot()}
        raw["spell_slots"] = {"mage": {"1": [2, 4]}}
        with self.assertRaises(ValueError):
            AdvancedBattle.from_dict(raw)


class CombatRulesTests(unittest.TestCase):
    def test_damage_dice_and_critical_confirmation(self):
        self.assertEqual(roll_damage("2d6+3", rng=FixedRoller([4, 5])),
                         (12, (4, 5)))
        # natural 20, critical confirmation 17, damage 4+2 and 5+2
        result = attack(attack_bonus=6, target_ac=18, damage="1d8+2",
                        rng=FixedRoller([20, 17, 4, 5]))
        self.assertTrue(result.critical)
        self.assertTrue(result.hit)
        self.assertEqual(result.damage, 13)

    def test_concealment_and_natural_one(self):
        miss = attack(attack_bonus=99, target_ac=1,
                      rng=FixedRoller([1]))
        self.assertFalse(miss.hit)
        hidden = attack(attack_bonus=10, target_ac=10, concealment=50,
                        rng=FixedRoller([13, 32]))
        self.assertFalse(hidden.hit)
        self.assertTrue(hidden.concealed_miss)

    def test_saving_throw_vs_skill_nat_1_and_20(self):
        save = saving_throw(modifier=50, dc=1, rng=FixedRoller([1]))
        self.assertFalse(save.success)
        skill = skill_check(modifier=50, dc=1, rng=FixedRoller([1]))
        self.assertTrue(skill.success)
        save20 = saving_throw(modifier=-20, dc=100, rng=FixedRoller([20]))
        self.assertTrue(save20.success)


class SpellIndexTests(unittest.TestCase):
    def test_parse_class_and_level_and_spell_links(self):
        html = ('<h3>0-Level Bard Spells</h3>'
                '<p><a href="../spells/detectMagic.htm">Detect Magic</a></p>'
                '<h3>1st-Level Bard Spells</h3>'
                '<a href="../spells/sleep.htm">Sleep</a>')
        spells = parse_spell_list(html, "Bard", LISTS["Bard"])
        # source URL should be a full URL in real downloader
        self.assertEqual(len(spells), 2)
        self.assertEqual([s["level"] for s in spells], [0, 1])

    def test_offline_cache_and_all_six_core_lists(self):
        self.assertEqual(len(LISTS), 6)
        def fetch(url):
            return ('<h3>1st-Level Spells</h3>' +
                    ''.join(f'<a href="../spells/spell{i}.htm">Spell {i}</a>'
                            for i in range(8)))
        result = download_srd_catalog(fetch=fetch)
        self.assertEqual(len(result), 48)
        with TemporaryDirectory() as folder:
            catalog = SpellCatalog(Path(folder) / "library.sqlite3")
            self.assertEqual(catalog.spells, [])
            catalog.store(result)
            fresh = SpellCatalog(Path(folder) / "library.sqlite3")
            self.assertEqual(len(fresh.search(class_name="Bard")), 8)


if __name__ == "__main__":
    unittest.main()
