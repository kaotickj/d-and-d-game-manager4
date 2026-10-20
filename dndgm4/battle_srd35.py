"""D&D 3.5 SRD combat calculations, independent of the Qt interface.

No Pathfinder advantage/disadvantage or 5e mechanics. Rolls are deliberately
explicit: situational bonuses, equipment, cover and DM adjudications remain
visible in the UI rather than secretly guessed.
SRD: https://www.d20srd.org/srd/combat/combatStatistics.htm
     https://www.d20srd.org/srd/combat/actionsInCombat.htm
     https://www.d20srd.org/srd/conditionSummary.htm
"""
from __future__ import annotations

from dataclasses import dataclass
import random
import re

DICE = re.compile(r"^\s*(\d{1,2})d(\d{1,4})(?:\s*([+-])\s*(\d{1,5}))?\s*$", re.I)
MAX_DICE = 100
MAX_SIDES = 1000


def roll_damage(notation: str, *, rng=None) -> tuple[int, tuple[int, ...]]:
    """Parse NdS(+/-N) dice, rejecting unbounded or executable expressions."""
    match = DICE.fullmatch(notation)
    if not match:
        raise ValueError("Damage must be dice notation such as 1d8+3 or 2d6-1.")
    count, sides = int(match[1]), int(match[2])
    if not 1 <= count <= MAX_DICE or not 2 <= sides <= MAX_SIDES:
        raise ValueError("Dice count or die size exceeds the encounter limits.")
    bonus = int(match[4] or 0) * (-1 if match[3] == "-" else 1)
    source = rng or random
    faces = tuple(source.randint(1, sides) for _ in range(count))
    return max(0, sum(faces) + bonus), faces


def seconds_as_clock(seconds: int) -> str:
    seconds = max(0, seconds)
    hours, rest = divmod(seconds, 3600)
    minutes, sec = divmod(rest, 60)
    return f"{hours:d}:{minutes:02d}:{sec:02d}" if hours else f"{minutes:02d}:{sec:02d}"


def rounds_to_seconds(rounds: int) -> int:
    if type(rounds) is not int or rounds < 0:
        raise ValueError("Round count must be nonnegative.")
    return rounds * 6


def duration_to_rounds(amount: int, unit: str) -> int:
    """3.5: one round = 6 seconds; one minute = 10 rounds."""
    if type(amount) is not int or not 1 <= amount <= 100000:
        raise ValueError("Duration must be between 1 and 100000 units.")
    rates = {"rounds": 1, "minutes": 10, "hours": 600}
    if unit not in rates:
        raise ValueError("Choose rounds, minutes, or hours.")
    return amount * rates[unit]


@dataclass(frozen=True)
class AttackResult:
    attack_roll: int
    attack_total: int
    target_ac: int
    hit: bool
    threat: bool
    confirmation_roll: int | None
    confirmation_total: int | None
    critical: bool
    concealment_roll: int | None
    concealed_miss: bool
    damage: int
    damage_rolls: tuple[int, ...]
    critical_damage_rolls: tuple[tuple[int, ...], ...]
    description: str


def attack(*, attack_bonus: int, target_ac: int, damage: str = "1d6",
           threat_min: int = 20, multiplier: int = 2, cover: int = 0,
           concealment: int = 0, situational: int = 0,
           damage_reduction: int = 0, rng=None) -> AttackResult:
    """SRD d20 attack, confirm critical, independent additional crit damage dice.

    The provided attack_bonus is the creature's complete base attack modifier
    (BAB, ability, size, weapon bonuses as entered by the DM). Cover = AC bonus.
    Unverified immunity, energy resistances and precision damage are DM-reviewed.
    """
    if not 2 <= threat_min <= 20 or not 2 <= multiplier <= 4:
        raise ValueError("Threat range or critical multiplier is invalid.")
    if cover not in (0, 4, 8):
        raise ValueError("Cover must be 0, 4 or 8 AC; total cover forbids attacks.")
    if concealment not in (0, 20, 50):
        raise ValueError("Concealment must be 0%, 20%, or 50%.")
    if not 0 <= damage_reduction <= 100000:
        raise ValueError("Damage reduction must be nonnegative.")
    source = rng or random
    ac = target_ac + cover
    die = source.randint(1, 20)
    total = die + attack_bonus + situational
    hit = die == 20 or (die != 1 and total >= ac)
    threat = hit and die >= threat_min
    confirm_die = confirm_total = None
    critical = False
    if threat:
        confirm_die = source.randint(1, 20)
        confirm_total = confirm_die + attack_bonus + situational
        critical = confirm_die == 20 or (
            confirm_die != 1 and confirm_total >= ac)
    miss_roll = None
    missed = False
    if hit and concealment:
        miss_roll = source.randint(1, 100)
        missed = miss_roll <= concealment
    rolls: tuple[int, ...] = ()
    extra: tuple[tuple[int, ...], ...] = ()
    total_damage = 0
    if hit and not missed:
        dealt, rolls = roll_damage(damage, rng=source)
        more = []
        # D&D 3.5: roll regular weapon damage separately for each multiplier
        # increment. Callers enter nonmultiplied extra damage separately.
        if critical:
            for _ in range(multiplier - 1):
                addition, faces = roll_damage(damage, rng=source)
                dealt += addition
                more.append(faces)
        extra = tuple(more)
        total_damage = max(0, dealt - damage_reduction)
    status = ("miss (concealment)" if missed else
              "critical hit" if critical else "hit" if hit else "miss")
    description = (f"d20 {die} + {attack_bonus + situational:+} = {total} "
                   f"vs AC {ac}: {status}; damage {total_damage}")
    if threat:
        description += f"; confirm d20 {confirm_die} = {confirm_total}"
    if miss_roll is not None:
        description += f"; concealment d100 {miss_roll} vs {concealment}%"
    if damage_reduction and hit and not missed:
        description += f"; DR {damage_reduction} applied"
    return AttackResult(die, total, ac, hit and not missed, threat,
                        confirm_die, confirm_total, critical and not missed,
                        miss_roll, missed, total_damage, rolls, extra, description)


@dataclass(frozen=True)
class CheckResult:
    die: int
    modifier: int
    total: int
    dc: int
    success: bool
    text: str


def saving_throw(*, modifier: int, dc: int, rng=None) -> CheckResult:
    """D&D 3.5 natural 1/20 auto-fail/success rule for saving throws."""
    die = (rng or random).randint(1, 20)
    total = die + modifier
    success = die == 20 or (die != 1 and total >= dc)
    return CheckResult(die, modifier, total, dc, success,
                       f"Save d20 {die} {modifier:+} = {total} vs DC {dc}: "
                       f"{'PASS' if success else 'FAIL'}")


def skill_check(*, modifier: int, dc: int, rng=None) -> CheckResult:
    """Unlike attacks and saves, natural 1/20 aren't automatic skill outcomes."""
    die = (rng or random).randint(1, 20)
    total = die + modifier
    success = total >= dc
    return CheckResult(die, modifier, total, dc, success,
                       f"Check d20 {die} {modifier:+} = {total} vs DC {dc}: "
                       f"{'PASS' if success else 'FAIL'}")


def condition_modifiers(names: set[str], *, melee: bool = True) -> dict:
    """Unambiguous common SRD condition modifiers; remaining cases DM-reviewed.

    Returns only broadly applicable penalties, not a character's entire attack
    calculation. AC adjustments requiring Dex/flat-footed math are left manual.
    """
    hit = 0
    damage = 0
    ac = 0
    for name in names:
        if name in {"Shaken", "Frightened", "Panicked", "Sickened"}:
            hit -= 2
        if name == "Sickened":
            damage -= 2
        if name == "Dazzled":
            hit -= 1
        if name == "Entangled":
            hit -= 2
        if name == "Prone" and melee:
            hit -= 4
        if name in {"Blinded", "Stunned", "Cowering"}:
            ac -= 2
        if name == "Prone":
            ac += -4 if melee else 4
    return {"attack": hit, "damage": damage, "ac": ac}
