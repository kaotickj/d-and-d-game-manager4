"""Auditable random encounter drafts, kept separate from permanent records.

Original creatures are proposed baselines made with the Monster Maker's type
formulas. They are not published stat blocks or automatic balance estimates.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
import json
import re
from typing import Iterable

from .battle_rules import Fighter, fighter_from_record
from .creation import ABILITIES
from .dice import ability_modifier, roll_dice, roll_expression
from .models import Creature
from .monster_rules import MonsterBlueprint, TYPES, build_monster
from .scene_context import blank_scene, validate_scene
from .storage import validate

ENVIRONMENTS = ("Forest", "Road", "Ruins", "Cavern", "Marsh", "Urban")
_LOCATIONS = {
    "Forest": ("a root-choked trail", "a clearing around a split oak", "a narrow stream crossing", "a ruined charcoal camp"),
    "Road": ("a damaged milestone", "an abandoned roadside shrine", "a broken wagon at a bend", "a toll bridge over a dry gully"),
    "Ruins": ("a roofless courtyard", "a collapsed watchtower", "an ivy-covered stairway", "a plaza around a cracked fountain"),
    "Cavern": ("a shelf above an underground pool", "a tunnel of pale stone", "a chamber of broken pillars", "a narrow passage beside a deep shaft"),
    "Marsh": ("a sinking boardwalk", "a reed-fringed island", "a flooded causeway", "a hollow among drowned trees"),
    "Urban": ("a market after closing", "an alley beside an empty warehouse", "a courtyard behind a public bath", "a lantern-lit canal landing"),
}
_CONDITIONS = ("Cold mist hangs close to the ground.", "A dry wind carries distant sounds.",
               "Light rain makes every surface slick.", "Clouds briefly part above the gathering.")
_CAVERN_CONDITIONS = ("Cold droplets fall from the ceiling.", "A faint draft carries distant scraping sounds.",
                      "The air is still and damp.", "Faint vibrations travel through the stone.")
_TERRAIN = ("Scattered debris breaks up the open ground.",
            "Several paths allow an approach or retreat.",
            "A low wall divides the open space from shelter.",
            "Uneven ground gives way to patches of shallow water.")
_CAVERN_TERRAIN = ("Broken stone interrupts the cavern floor.",
                   "Several side passages branch away from the chamber.",
                   "A rock shelf divides the upper and lower floor.",
                   "Shallow pools lie between uneven slabs of stone.")
_HOOKS = ("A fresh trail leads toward a place the group has not explored.",
          "Someone has left a warning token where travelers will find it.",
          "A dropped satchel contains a clue whose owner is nearby.",
          "A distant call draws attention away from the obvious route.")
_MOTIVES = ("The group is protecting a temporary refuge.",
            "The group is searching for something that disappeared here.",
            "The group wants passage through the area.",
            "The group is responding to a recent disturbance.")
_ANIMAL_MOTIVES = ("The animals are seeking food.", "The animals are sheltering from a disturbance.",
                  "The animals are moving toward water.", "The animals are defending their resting place.")
_MINDLESS_MOTIVES = ("The creatures follow a repeating route through the area.",
                    "Nearby movement draws the creatures' response.",
                    "Vibration or sound draws the creatures toward its source.",
                    "The creatures remain around a physical landmark; the DM chooses why.")
_COMPLICATIONS = ("Another traveler may arrive while the party investigates.",
                  "The obvious route will soon be blocked by worsening conditions.",
                  "Evidence points toward two conflicting explanations.",
                  "An unnoticed escape route offers a way to avoid a fight.")
_ORIGINALS = {
    "Forest": (("Thornback Forager", "Animal", "Small", 2), ("Root Lantern Sentry", "Construct", "Small", 1), ("Trail Lookout", "Humanoid", "Medium", 1)),
    "Road": (("Wayside Lookout", "Humanoid", "Medium", 1), ("Dust Lantern Sentry", "Construct", "Small", 1), ("Dusk Forager", "Animal", "Small", 2)),
    "Ruins": (("Ashen Pilgrim", "Undead", "Medium", 2), ("Courtyard Watcher", "Construct", "Medium", 1), ("Rubble Strider", "Vermin", "Small", 1)),
    "Cavern": (("Stone Strider", "Vermin", "Small", 2), ("Echo Forager", "Animal", "Small", 2), ("Hollow Pilgrim", "Undead", "Medium", 1)),
    "Marsh": (("Reed Forager", "Animal", "Small", 2), ("Mud Strider", "Vermin", "Small", 2), ("Drowned Lantern Sentry", "Construct", "Small", 1)),
    "Urban": (("Canal Lookout", "Humanoid", "Medium", 1), ("Gutter Forager", "Animal", "Small", 1), ("Clockwork Porter", "Construct", "Small", 1)),
}
_QUANTITY = re.compile(r"^\s*(?:(\d{1,2})?[dD](\d{1,2})(?:\s*([+-])\s*(\d{1,2}))?|(\d{1,2}))\s*$")


def _count(expression: str, rng, log: list[str]) -> int:
    if not isinstance(expression, str):
        raise ValueError("Creature count must be dice such as 1d4 or a number from 1 to 12.")
    match = _QUANTITY.fullmatch(expression)
    if not match:
        raise ValueError("Use a creature count such as 1d4, 2d6, or 3.")
    count, sides, sign, modifier, fixed = match.groups()
    if fixed is not None:
        total = int(fixed)
        if not 1 <= total <= 12:
            raise ValueError("An encounter draft supports 1–12 creatures.")
        log.append(f"Creature count: fixed {total} (no roll).")
        return total
    count, sides = int(count or 1), int(sides)
    bonus = int(modifier or 0) * (-1 if sign == "-" else 1)
    if not 1 <= count <= 12 or not 2 <= sides <= 12 or not 1 <= count + bonus <= count * sides + bonus <= 12:
        raise ValueError("Count dice must always produce 1–12 creatures; use 1d4, 2d6, or 1d12.")
    roll = roll_expression(expression, rng=rng)
    log.append(f"Creature count: {roll.notation} {roll.detail}.")
    return roll.total


def _pick(label: str, values, rng, log: list[str]):
    if len(values) == 1:
        display = values[0].name if isinstance(values[0], Creature) else str(values[0])
        log.append(f"{label}: only option, {display} (no roll).")
        return values[0]
    result = roll_dice(1, len(values), rng=rng)
    choice = values[result.total - 1]
    display = choice.name if isinstance(choice, Creature) else str(choice)
    log.append(f"{label}: {result.notation} {result.detail} → {display}.")
    return choice


def _original(spec, environment: str, index: int, rng, log: list[str]) -> Creature:
    name, kind, size, hd = spec
    scores = {}
    for ability in ABILITIES:
        if ability == "constitution" and TYPES[kind].no_con:
            scores[ability] = None
            log.append(f"{name} #{index} CON: absent for {kind} (no roll).")
        elif ability == "intelligence" and kind in ("Construct", "Undead", "Vermin"):
            scores[ability] = None
            log.append(f"{name} #{index} INT: mindless baseline (no roll).")
        elif ability == "intelligence" and kind == "Animal":
            result = roll_expression("1d2", rng=rng)
            scores[ability] = result.total
            log.append(f"{name} #{index} INT: {result.notation} {result.detail}.")
        else:
            result = roll_expression("3d6", rng=rng)
            scores[ability] = result.total
            log.append(f"{name} #{index} {ability[:3].upper()}: {result.notation} {result.detail}.")
    die = TYPES[kind].die
    result = roll_dice(hd, die, rng=rng)
    log.append(f"{name} #{index} HP dice: {result.notation} {result.detail}.")
    faces = iter(result.faces)
    blueprint = MonsterBlueprint(
        name=name, species=f"Original {name}", creature_type=kind, hit_dice=hd,
        abilities=scores, size=size, environment=environment, hp_method="rolled",
        notes="Original generated baseline. Review abilities, attacks, traits and balance before play; CR is unassigned.")
    creature = build_monster(blueprint, roller=lambda low, high: next(faces))
    sheet = json.loads(creature.sheet_json)
    computed = sheet["computed"]
    damage_bonus = ability_modifier(creature.strength)
    sheet["attacks"] = f"Proposed strike {computed['melee']:+d} melee, 1d4{damage_bonus:+d} damage (DM review)."
    creature = replace(creature, sheet_json=json.dumps(sheet, ensure_ascii=False, sort_keys=True))
    log.append(f"{name} #{index} final HP: {creature.max_hit_points}, including type/CON adjustments.")
    return creature


@dataclass(frozen=True)
class EncounterDraft:
    title: str
    environment: str
    location: str
    conditions: str
    scenery: str
    hook: str
    motive: str
    complication: str
    read_aloud: str
    roll_log: tuple[str, ...]
    creatures: tuple[Creature, ...]
    fighters: tuple[Fighter, ...]
    dm_notes: str = ""

    def dm_brief(self, *, include_roll_log: bool = True) -> str:
        lines = [f"ENCOUNTER DRAFT / {self.title}", "DM review required; no balance or Challenge Rating is inferred.",
                 f"Environment: {self.environment}", f"Location: {self.location}",
                 f"Conditions: {self.conditions}", f"Terrain: {self.scenery}",
                 "PLAYER-FACING READ-ALOUD", self.read_aloud,
                 "DM-ONLY PROPOSED DETAILS", f"Hook: {self.hook}", f"Motive: {self.motive}",
                 f"Complication: {self.complication}", self.dm_notes, "CREATURES"]
        for creature, fighter in zip(self.creatures, self.fighters):
            lines.append(f"{fighter.name}: {creature.race_type or creature.kind}; HP {fighter.hp}/{fighter.max_hp}, "
                         f"AC {fighter.ac}, initiative {fighter.initiative if fighter.initiative is not None else 'not rolled'}, "
                         f"CR {creature.challenge_rating or 'unassigned'}.")
            sheet = json.loads(creature.sheet_json) if creature.sheet_json else {}
            absent = sheet.get("null_abilities", [])
            if not isinstance(absent, list):
                absent = []
            lines.append(", ".join(f"{key[:3].upper()} {'—' if key in absent else getattr(creature, key)}" for key in ABILITIES))
            if creature.sheet_json:
                computed = sheet.get("computed", {})
                if isinstance(computed, dict) and computed:
                    lines.append("Computed baseline: " + ", ".join(
                        f"{label} {computed.get(key, 'unassigned')}" for key, label in (
                            ("hit_dice_notation", "HD"), ("bab", "BAB"), ("fort", "Fort"),
                            ("ref", "Ref"), ("will", "Will"), ("grapple", "Grapple"),
                            ("melee", "Melee"), ("ranged", "Ranged"))))
                for key in ("speed", "attacks", "special_attacks", "special_qualities", "feats", "skills", "progression"):
                    if sheet.get(key):
                        lines.append(f"{key.replace('_', ' ').title()}: {sheet[key]}")
            if creature.notes:
                lines.append(creature.notes)
        if include_roll_log:
            lines.extend(("ROLL LOG", *self.roll_log))
        return "\n".join(line for line in lines if line)

    def to_scene(self, base_scene=None) -> dict:
        scene = validate_scene(base_scene if base_scene is not None else blank_scene())
        scene["title"] = self.title
        scene["location"] = self.location
        scene["time_conditions"] = self.conditions
        scene["scenery"] = self.read_aloud + "\n\nTerrain: " + self.scenery
        scene["record_ids"] = list(dict.fromkeys(scene["record_ids"] + [c.id for c in self.creatures if c.id]))
        scene["campaign_notes"] = (scene["campaign_notes"].rstrip() + "\n\n" + self.dm_brief()).strip()
        return validate_scene(scene)

    def scribe_context(self) -> str:
        text = ("D&D 3.5 ENCOUNTER PROPOSAL FOR DM REVIEW\n"
                "These are proposed encounter details, not established outcomes. "
                "Do not decide player actions, reveal DM-only secrets in read-aloud text, "
                "or invent rolls or changes to statistics. "
                "The dice audit is retained in the draft; reviewed final results follow.\n\n"
                + self.dm_brief(include_roll_log=False))
        if len(text) > 6000:
            raise ValueError(f"Full encounter context needs {len(text):,} characters; the Scribe limit is 6,000. "
                             "Use a smaller encounter or save the draft as a scene. No details were omitted.")
        return text


def generate_encounter(records: Iterable[Creature], *, environment: str = "Forest",
                       quantity: str = "1d4", source: str = "library",
                       roll_initiative: bool = False, rng=None) -> EncounterDraft:
    if environment not in ENVIRONMENTS:
        raise ValueError("Choose a supported encounter environment.")
    if source not in ("library", "original"):
        raise ValueError("Encounter source must be library or original.")
    if type(roll_initiative) is not bool:
        raise ValueError("Roll initiative must be true or false.")
    records = tuple(records)
    if any(not isinstance(record, Creature) for record in records):
        raise ValueError("Encounter candidates must be library creature records.")
    candidates = tuple(sorted((record for record in records
                               if record.kind in ("npc", "monster") and not record.archived),
                              key=lambda record: (record.name.casefold(), record.id)))
    if source == "library" and not candidates:
        raise ValueError("No active NPC or monster templates are available. Choose original creatures or add library records.")
    for record in candidates if source == "library" else ():
        validate(record)
    log = []
    count = _count(quantity, rng, log)
    location = _pick("Location", _LOCATIONS[environment], rng, log)
    conditions = _pick("Conditions", _CAVERN_CONDITIONS if environment == "Cavern" else _CONDITIONS, rng, log)
    scenery = _pick("Terrain", _CAVERN_TERRAIN if environment == "Cavern" else _TERRAIN, rng, log)
    hook = _pick("Hook", _HOOKS, rng, log)
    chosen = _pick("Creature template", candidates if source == "library" else _ORIGINALS[environment], rng, log)
    motives = _MOTIVES
    if source == "original":
        if chosen[1] == "Animal":
            motives = _ANIMAL_MOTIVES
        elif chosen[1] in ("Construct", "Undead", "Vermin"):
            motives = _MINDLESS_MOTIVES
    motive = _pick("Motive", motives, rng, log)
    complication = _pick("Complication", _COMPLICATIONS, rng, log)
    creatures, fighters = [], []
    for index in range(1, count + 1):
        creature = chosen if source == "library" else _original(chosen, environment, index, rng, log)
        if source == "library":
            log.append(f"{creature.name} #{index}: HP {creature.max_hit_points} and abilities retained from library template (no roll).")
        label = f"{creature.name[:194]} #{index}"
        safe_creature = creature
        if creature.sheet_json:
            safe_sheet = json.loads(creature.sheet_json)
            if not isinstance(safe_sheet.get("feats", []), list):
                safe_sheet["feats"] = []
                safe_creature = replace(creature, sheet_json=json.dumps(safe_sheet))
        fighter = fighter_from_record(safe_creature, name=label)
        if source == "original":
            sheet = json.loads(creature.sheet_json)
            stats = sheet["computed"]
            absent = sheet.get("null_abilities", [])
            fighter.notes += "\n" + ", ".join(
                f"{ability[:3].upper()} {'—' if ability in absent else getattr(creature, ability)}"
                for ability in ABILITIES)
            fighter.notes += (f"\nHD {stats['hit_dice_notation']}; BAB {stats['bab']:+d}; "
                              f"Fort {stats['fort']:+d}, Ref {stats['ref']:+d}, Will {stats['will']:+d}.\n"
                              + sheet["attacks"])
        if roll_initiative:
            result = roll_dice(1, 20, fighter.init_mod, rng=rng)
            fighter.initiative_roll, fighter.initiative = result.faces[0], result.total
            log.append(f"{label} initiative: {result.notation} {result.detail}.")
        creatures.append(creature)
        fighters.append(fighter)
    name = creatures[0].name
    return EncounterDraft(
        title=f"{environment}: {name}"[:200], environment=environment,
        location=location, conditions=conditions, scenery=scenery, hook=hook,
        motive=motive, complication=complication,
        read_aloud=f"Ahead lies {location}. {conditions} {scenery} Nearby: {count} {name}. Their intentions are not yet clear.",
        roll_log=tuple(log), creatures=tuple(creatures), fighters=tuple(fighters))
