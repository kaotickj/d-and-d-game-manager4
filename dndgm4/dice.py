"""Dice and ability-roll rules, independent of Qt and SQLite.

Implements the original Liberty BASIC Dice Eliminator's dice plus D&D ability
rolling. Results expose every physical die to make outcomes auditable.
"""
from __future__ import annotations

import re
import secrets
from dataclasses import dataclass
from typing import Protocol


class DiceSource(Protocol):
    def randint(self, low: int, high: int) -> int: ...


_RNG = secrets.SystemRandom()
_EXPRESSION = re.compile(
    r"^\s*(?P<count>\d{0,3})[dD](?P<sides>\d{1,6})"
    r"(?:(?P<keep>kh)(?P<kept>\d{1,3}))?"
    r"\s*(?:(?P<sign>[+-])\s*(?P<bonus>\d{1,6}))?\s*$"
)


@dataclass(frozen=True)
class DiceResult:
    count: int
    sides: int
    faces: tuple[int, ...]
    kept: tuple[int, ...]
    modifier: int = 0

    @property
    def total(self) -> int:
        return sum(self.faces[i] for i in self.kept) + self.modifier

    @property
    def notation(self) -> str:
        keep = f"kh{len(self.kept)}" if len(self.kept) != self.count else ""
        bonus = f"{self.modifier:+d}" if self.modifier else ""
        return f"{self.count}d{self.sides}{keep}{bonus}"

    @property
    def detail(self) -> str:
        selected = set(self.kept)
        faces = ", ".join(str(n) if i in selected else f"({n} dropped)"
                          for i, n in enumerate(self.faces))
        suffix = f" {self.modifier:+d}" if self.modifier else ""
        return f"[{faces}]{suffix} = {self.total}"


def roll_dice(count: int, sides: int, modifier: int = 0,
              keep_highest: int | None = None,
              rng: DiceSource | None = None) -> DiceResult:
    """Roll between one and 200 dice, with optional keep-highest.

    Limits make accidentally huge expressions safe. All draws are unbiased,
    inclusive integers. A source can be injected for reproducible unit tests.
    """
    if not 1 <= count <= 200:
        raise ValueError("Roll between 1 and 200 dice.")
    if not 2 <= sides <= 100000:
        raise ValueError("A die must have between 2 and 100000 sides.")
    if not -100000 <= modifier <= 100000:
        raise ValueError("Modifier is out of range.")
    if keep_highest is not None and not 1 <= keep_highest <= count:
        raise ValueError("Keep count must be between 1 and the number of dice.")
    source = rng if rng is not None else _RNG
    faces = tuple(source.randint(1, sides) for _ in range(count))
    kept_count = count if keep_highest is None else keep_highest
    # Sorted indices rather than values: equal dice are still distinct.
    kept = tuple(sorted(sorted(range(count), key=lambda i: (-faces[i], i))
                        [:kept_count]))
    return DiceResult(count, sides, faces, kept, modifier)


def roll_expression(expression: str, rng: DiceSource | None = None) -> DiceResult:
    """Parse NdS, dS, NdS+M, NdS-M, NdSkhK, e.g. 4d6kh3."""
    match = _EXPRESSION.fullmatch(expression)
    if not match:
        raise ValueError("Use dice notation such as d20, 2d8+3 or 4d6kh3.")
    count = int(match["count"] or "1")
    sides = int(match["sides"])
    bonus = int(match["bonus"] or "0")
    if match["sign"] == "-":
        bonus = -bonus
    keep = int(match["kept"]) if match["keep"] else None
    return roll_dice(count, sides, bonus, keep, rng)


def ability_modifier(score: int) -> int:
    """D&D 3.5 floor((score - 10) / 2), including odd low scores."""
    return (score - 10) // 2


def generate_abilities(method: str, rng: DiceSource | None = None
                       ) -> tuple[DiceResult, ...]:
    """Six rolls in STR, DEX, CON, INT, WIS, CHA order.

    method1: original 3d6, one possible reroll of sub-10 scores.
    method2: original 4d6 drop the lowest, no individual rerolls.
    """
    if method not in {"method1", "method2"}:
        raise ValueError("Unknown rolling method.")
    expr = "3d6" if method == "method1" else "4d6kh3"
    return tuple(roll_expression(expr, rng) for _ in range(6))


def reroll_low_score(original: DiceResult, rng: DiceSource | None = None
                     ) -> DiceResult:
    """One fresh 3d6 attempt; caller keeps the higher total.

    Eligibility and one-attempt enforcement belong to creator session state.
    """
    if original.notation != "3d6" or original.total >= 10:
        raise ValueError("Only a Method 1 ability below 10 can be rerolled.")
    return roll_expression("3d6", rng)


def percentile_answer(roll: int) -> str:
    """Match the original Dice Eliminator's yes/no interpretation."""
    if not 1 <= roll <= 100:
        raise ValueError("Percentile must be from 1 to 100.")
    return "Yes" if roll <= 50 else "No"
