"""First-level D&D 3.5 character creation, with original rolling methods.

Rules are plain Python to allow testing without Qt. No proprietary artwork,
reference text, feats or spells are bundled.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from .dice import (DiceResult, ability_modifier, generate_abilities,
                   reroll_low_score, DiceSource)
from .models import Creature

ABILITIES = ("strength", "dexterity", "constitution",
             "intelligence", "wisdom", "charisma")

# Core player races. Values are score adjustments, not ability modifiers.
RACIAL_ADJUSTMENTS = {
    "Human": {},
    "Dwarf": {"constitution": 2, "charisma": -2},
    "Elf": {"dexterity": 2, "constitution": -2},
    "Gnome": {"constitution": 2, "strength": -2},
    "Half-elf": {},
    "Half-orc": {"strength": 2, "intelligence": -2, "charisma": -2},
    "Halfling": {"dexterity": 2, "strength": -2},
}

# Class -> (hit die, base skill points per level).
CORE_CLASSES = {
    "Barbarian": (12, 4), "Bard": (6, 6), "Cleric": (8, 2),
    "Druid": (8, 4), "Fighter": (10, 2), "Monk": (8, 4),
    "Paladin": (10, 2), "Ranger": (8, 6), "Rogue": (6, 8),
    "Sorcerer": (4, 2), "Wizard": (4, 2),
}
SMALL_RACES = frozenset({"Gnome", "Halfling"})


def adjusted_scores(base: dict[str, int], race: str) -> dict[str, int]:
    if race not in RACIAL_ADJUSTMENTS:
        raise ValueError("Unknown player race.")
    if set(base) != set(ABILITIES):
        raise ValueError("All six ability scores are required.")
    result = {}
    for ability in ABILITIES:
        score = base[ability] + RACIAL_ADJUSTMENTS[race].get(ability, 0)
        # The 3.5 half-orc racial minimum for INT is 3.
        if race == "Half-orc" and ability == "intelligence":
            score = max(3, score)
        result[ability] = max(1, score)
    return result


def first_level_hp(character_class: str, con_score: int) -> int:
    return max(1, CORE_CLASSES[character_class][0] + ability_modifier(con_score))


def first_level_skill_points(character_class: str, int_score: int,
                             race: str) -> int:
    base = CORE_CLASSES[character_class][1]
    # At first level: four times normal points (minimum four), human +4.
    return max(1, base + ability_modifier(int_score)) * 4 + (4 if race == "Human" else 0)


@dataclass
class CreationSession:
    """A working roll session, not a saved character.

    Never reroll an ability automatically: the player decides when to roll.
    """
    method: str = "method2"
    rolls: list[DiceResult] = field(default_factory=list)
    rerolled: set[int] = field(default_factory=set)
    reroll_notes: list[str] = field(default_factory=list)

    def roll_all(self, rng: DiceSource | None = None) -> None:
        self.rolls = list(generate_abilities(self.method, rng))
        self.rerolled.clear()
        self.reroll_notes.clear()

    def reroll(self, index: int, rng: DiceSource | None = None) -> bool:
        if self.method != "method1":
            raise ValueError("Individual rerolls are only available with Method 1.")
        if not self.rolls or not 0 <= index < 6:
            raise ValueError("Roll all six scores first.")
        if index in self.rerolled:
            raise ValueError("This ability has already been rerolled.")
        old = self.rolls[index]
        attempt = reroll_low_score(old, rng)
        improved = attempt.total > old.total
        self.rerolled.add(index)
        if improved:
            self.rolls[index] = attempt
        self.reroll_notes.append(
            f"{ABILITIES[index].title()} reroll: {old.total} vs "
            f"{attempt.total}; kept {max(old.total, attempt.total)}"
        )
        return improved

    def base_scores(self) -> dict[str, int]:
        if len(self.rolls) != 6:
            raise ValueError("Roll all six ability scores first.")
        return dict(zip(ABILITIES, (r.total for r in self.rolls)))


def build_character(*, name: str, race: str, character_class: str,
                    base: dict[str, int], method: str,
                    rolls: list[DiceResult] | None = None,
                    reroll_notes: list[str] | None = None,
                    notes: str = "", custom_hit_die: int | None = None,
                    custom_skill_points: int | None = None) -> Creature:
    """Create a level-one PC ready for the existing SQLite library."""
    if not name.strip():
        raise ValueError("Character name is required.")
    if race not in RACIAL_ADJUSTMENTS:
        raise ValueError("Choose a supported D&D 3.5 race.")
    if character_class not in CORE_CLASSES and (
        custom_hit_die is None or custom_skill_points is None
    ):
        raise ValueError("Custom classes require a hit die and skill-point rate.")
    if custom_hit_die is not None and not 4 <= custom_hit_die <= 20:
        raise ValueError("Hit die must be between d4 and d20.")
    if custom_skill_points is not None and not 1 <= custom_skill_points <= 20:
        raise ValueError("Class skill points must be between 1 and 20.")
    if any(not 3 <= score <= 18 for score in base.values()):
        # For manual entry and standard array, the basic unadjusted scores.
        raise ValueError("Base scores must be between 3 and 18.")
    final = adjusted_scores(base, race)
    hit_die = (CORE_CLASSES[character_class][0] if character_class in CORE_CLASSES
               else custom_hit_die)
    hp = max(1, hit_die + ability_modifier(final["constitution"]))
    ac = 10 + ability_modifier(final["dexterity"]) + (1 if race in SMALL_RACES else 0)
    skill_rate = (CORE_CLASSES[character_class][1] if character_class in CORE_CLASSES
                  else custom_skill_points)
    skill = max(1, skill_rate + ability_modifier(final["intelligence"])) * 4
    if race == "Human":
        skill += 4
    info = [
        f"Character created using {method}; base scores: " +
        ", ".join(f"{key[:3].upper()} {base[key]}" for key in ABILITIES),
        "Racial adjustments: " + (", ".join(
            f"{a[:3].upper()} {v:+d}"
            for a, v in RACIAL_ADJUSTMENTS[race].items()
        ) or "none"),
        f"Level 1 hit points: {hp} (maximum class hit die + CON modifier).",
        f"First-level skill points available: {skill} (not yet assigned).",
        "AC includes Dexterity and race size only; no armor or equipment.",
    ]
    if rolls:
        info.append("Original ability dice: " + "; ".join(
            f"{ABILITIES[i][:3].upper()} {r.notation} {r.detail}"
            for i, r in enumerate(rolls)
        ))
    info.extend(reroll_notes or [])
    if notes.strip():
        info.extend(("", notes.strip()))
    return Creature(
        name=name.strip(), kind="pc", race_type=race,
        character_class=character_class, level=1,
        armor_class=max(0, ac), max_hit_points=hp,
        notes="\n".join(info), **final,
    )
