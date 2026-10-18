"""Deterministic tests for the D&D 3.5 dice and character-creation rules."""
import unittest

from dndgm4.creation import (ABILITIES, CreationSession, adjusted_scores,
                              build_character, first_level_hp,
                              first_level_skill_points)
from dndgm4.dice import (ability_modifier, generate_abilities,
                         percentile_answer, roll_dice, roll_expression)


class ScriptedDice:
    def __init__(self, *faces):
        self.faces = list(faces)

    def randint(self, low, high):
        if not self.faces:
            raise AssertionError("Too many dice rolls")
        face = self.faces.pop(0)
        if not low <= face <= high:
            raise AssertionError("Scripted die outside range")
        return face


class DiceRulesTests(unittest.TestCase):
    def test_standard_dice_and_minus_modifier(self):
        result = roll_expression("2d8-3", ScriptedDice(2, 7))
        self.assertEqual(result.faces, (2, 7))
        self.assertEqual(result.total, 6)
        self.assertEqual(result.notation, "2d8-3")

    def test_implicit_count_and_fair_bounds(self):
        result = roll_expression(" d20 + 4 ", ScriptedDice(20))
        self.assertEqual(result.total, 24)
        self.assertEqual(result.notation, "1d20+4")

    def test_four_d6_drop_lowest_with_tie(self):
        result = roll_expression("4d6kh3", ScriptedDice(1, 5, 5, 3))
        self.assertEqual(result.faces, (1, 5, 5, 3))
        self.assertEqual(result.kept, (1, 2, 3))
        self.assertEqual(result.total, 13)
        self.assertIn("dropped", result.detail)

    def test_invalid_expressions_and_limits(self):
        for expression in ("", "abc", "2d6*2", "0d6", "201d6",
                           "2d1", "4d6kh5", "1d1000000", "2d6+100001"):
            with self.subTest(expression=expression):
                with self.assertRaises(ValueError):
                    roll_expression(expression)
        with self.assertRaises(ValueError):
            roll_dice(1, 0)

    def test_original_percentile_answer(self):
        self.assertEqual(percentile_answer(1), "Yes")
        self.assertEqual(percentile_answer(50), "Yes")
        self.assertEqual(percentile_answer(51), "No")
        self.assertEqual(percentile_answer(100), "No")

    def test_ability_modifiers(self):
        self.assertEqual([ability_modifier(i) for i in (3, 8, 9, 10, 11, 12, 18)],
                         [-4, -1, -1, 0, 0, 1, 4])

    def test_method_one_six_3d6(self):
        results = generate_abilities("method1", ScriptedDice(*([3] * 18)))
        self.assertEqual([r.total for r in results], [9] * 6)
        self.assertEqual([r.notation for r in results], ["3d6"] * 6)

    def test_method_two_six_4d6_drop_lowest(self):
        results = generate_abilities("method2", ScriptedDice(*([1, 4, 5, 6] * 6)))
        self.assertEqual([r.total for r in results], [15] * 6)

    def test_method_one_single_low_score_reroll(self):
        session = CreationSession(method="method1")
        session.roll_all(ScriptedDice(*([2] * 18)))
        self.assertFalse(session.reroll(0, ScriptedDice(1, 1, 1)))
        self.assertEqual(session.base_scores()["strength"], 6)
        with self.assertRaises(ValueError):
            session.reroll(0, ScriptedDice(6, 6, 6))
        self.assertTrue(session.reroll(1, ScriptedDice(6, 6, 6)))
        self.assertEqual(session.base_scores()["dexterity"], 18)
        with self.assertRaises(ValueError):
            CreationSession(method="method2").reroll(0)


class CharacterRulesTests(unittest.TestCase):
    def test_racial_adjustments(self):
        base = dict.fromkeys(ABILITIES, 10)
        self.assertEqual(adjusted_scores(base, "Elf")["dexterity"], 12)
        self.assertEqual(adjusted_scores(base, "Dwarf")["charisma"], 8)
        self.assertEqual(adjusted_scores(base, "Gnome")["strength"], 8)
        self.assertEqual(adjusted_scores(base, "Halfling")["dexterity"], 12)
        self.assertEqual(adjusted_scores(base, "Half-orc")["intelligence"], 8)
        base["intelligence"] = 3
        self.assertEqual(adjusted_scores(base, "Half-orc")["intelligence"], 3)

    def test_first_level_hp_and_skill_points(self):
        self.assertEqual(first_level_hp("Fighter", 14), 12)
        self.assertEqual(first_level_hp("Wizard", 3), 1)
        self.assertEqual(first_level_skill_points("Rogue", 14, "Human"), 44)
        self.assertEqual(first_level_skill_points("Wizard", 3, "Elf"), 4)

    def test_build_character_and_audit_notes(self):
        scores = dict(zip(ABILITIES, (15, 14, 13, 12, 10, 8)))
        result = build_character(name="  Beryl  ", race="Halfling",
                                 character_class="Rogue", base=scores,
                                 method="Original Method 2", notes="Scout")
        self.assertEqual(result.name, "Beryl")
        self.assertEqual(result.kind, "pc")
        self.assertEqual(result.strength, 13)
        self.assertEqual(result.dexterity, 16)
        self.assertEqual(result.armor_class, 14)  # 10 + 3 DEX + 1 small
        self.assertEqual(result.max_hit_points, 7)
        self.assertIn("Scout", result.notes)
        self.assertIn("Original Method 2", result.notes)

    def test_rejects_incomplete_or_invalid_character(self):
        scores = dict.fromkeys(ABILITIES, 10)
        for name, race, cls in (("", "Human", "Wizard"),
                                ("T", "Unknown", "Wizard"),
                                ("T", "Human", "Unknown")):
            with self.subTest(name=name, race=race, cls=cls):
                with self.assertRaises(ValueError):
                    build_character(name=name, race=race,
                                    character_class=cls, base=scores,
                                    method="manual")


if __name__ == "__main__":
    unittest.main()
