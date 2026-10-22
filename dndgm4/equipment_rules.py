"""Reviewed ordinary SRD loadouts, calculated separately from manual sheets.

This intentionally covers one normal attack, not an inventory/effect engine.
All inputs are explicit; class labels and prose never grant mechanics.
"""
from __future__ import annotations

import json
import math

from .advancement import CLASS_PROGRESSION
from .dice import ability_modifier
from .storage import validate as validate_creature

ARMOR_SOURCE = "https://www.d20srd.org/srd/equipment/armor.htm"
WEAPON_SOURCE = "https://www.d20srd.org/srd/equipment/weapons.htm"
COMBAT_SOURCE = "https://www.d20srd.org/srd/combat/combatStatistics.htm"
FEAT_SOURCE = "https://www.d20srd.org/srd/feats.htm"
MONK_SOURCE = "https://www.d20srd.org/srd/classes/monk.htm"
PALADIN_SOURCE = "https://www.d20srd.org/srd/classes/paladin.htm"
CLASS_NAMES = tuple(CLASS_PROGRESSION)

ARMOR = {name: {"bonus": bonus, "max_dex": cap, "check_penalty": penalty}
         for name, bonus, cap, penalty in (
             ("None", 0, None, 0), ("Padded", 1, 8, 0), ("Leather", 2, 6, 0),
             ("Studded leather", 3, 5, -1), ("Chain shirt", 4, 4, -2),
             ("Breastplate", 5, 3, -4), ("Full plate", 8, 1, -6))}
SHIELDS = {name: {"bonus": bonus, "check_penalty": penalty}
           for name, bonus, penalty in (
               ("None", 0, 0), ("Shield, light wooden", 1, -1),
               ("Shield, heavy wooden", 2, -2), ("Shield, heavy steel", 2, -2))}
WEAPONS = {
    name: {"small_damage": small, "medium_damage": medium,
           "attack_ability": ability, "damage_mode": mode, "hands": hands,
           "finesse": finesse, "threat_min": threat, "multiplier": multiplier}
    for name, small, medium, ability, mode, hands, finesse, threat, multiplier in (
        ("Dagger", "1d3", "1d4", "strength", "strength", 1, True, 19, 2),
        ("Sword, short", "1d4", "1d6", "strength", "strength", 1, True, 19, 2),
        ("Longsword", "1d6", "1d8", "strength", "strength", 1, False, 19, 2),
        ("Rapier", "1d4", "1d6", "strength", "strength", 1, True, 18, 2),
        ("Greatsword", "1d10", "2d6", "strength", "two_handed", 2, False, 19, 2),
        ("Greataxe", "1d10", "1d12", "strength", "two_handed", 2, False, 20, 3),
        ("Longbow", "1d6", "1d8", "dexterity", "bow", 2, False, 20, 3),
        ("Crossbow, light", "1d6", "1d8", "dexterity", "none", 2, False, 19, 2),
    )
}

_REQUIRED = {"version", "armor", "shield", "weapon", "size", "proficiency_confirmed",
             "class_levels", "weapon_focus_weapon", "weapon_finesse", "review_basis"}
_OPTIONAL = {"monk_ac_eligible", "paladin_grace_eligible"}


def read_character_sheet(creature):
    raw = creature.sheet_json
    if not isinstance(raw, str) or len(raw) > 262144:
        raise ValueError("Character sheet exceeds the supported size or is not text.")

    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError(f"Duplicate saved sheet key: {key}")
            result[key] = value
        return result

    def constant(value):
        raise ValueError(f"Non-finite saved sheet number: {value}")

    def check(value):
        if isinstance(value, str):
            value.encode("utf-8")
        elif isinstance(value, float) and not math.isfinite(value):
            raise ValueError("Non-finite saved sheet number.")
        elif isinstance(value, dict):
            for key, child in value.items():
                check(key)
                check(child)
        elif isinstance(value, list):
            for child in value:
                check(child)

    try:
        raw.encode("utf-8")
        sheet = json.loads(raw or "{}", object_pairs_hook=pairs, parse_constant=constant)
        check(sheet)
    except (TypeError, ValueError, UnicodeError, RecursionError, OverflowError) as exc:
        raise ValueError("Saved character sheet is unreadable; repair it before reviewing equipment.") from exc
    if not isinstance(sheet, dict):
        raise ValueError("Saved character sheet must be an object.")
    return sheet


def read_loadout(creature):
    """Read a supported current reviewed loadout, or None when none is saved.

    Unknown/malformed profiles raise rather than silently falling back to a
    different interpretation. No saved metadata is rewritten.
    """
    sheet = read_character_sheet(creature)
    if "combat_loadout" not in sheet:
        return None
    return validate_loadout(sheet["combat_loadout"], creature)


def _saved_feats(creature):
    sheet = read_character_sheet(creature)
    feats = sheet.get("feats", [])
    if not isinstance(feats, list) or any(not isinstance(feat, str) for feat in feats):
        raise ValueError("Saved feats must be a list of names.")
    return {feat.strip().casefold() for feat in feats}


def _has_focus(feats, weapon):
    return "weapon focus" in feats or f"weapon focus ({weapon.casefold()})" in feats


def _base_attack(levels):
    return sum(level * {"full": 4, "three_quarters": 3, "half": 2}[CLASS_PROGRESSION[name][0]] // 4
               for name, level in levels.items())


def validate_loadout(profile, creature=None) -> dict:
    """Return a fresh validated profile; supplying a creature checks review age.

    Structural validation alone permits reopening a stale saved profile. It
    never makes that profile eligible for effective-stat suggestions.
    """
    if not isinstance(profile, dict) or not _REQUIRED <= profile.keys() or profile.keys() - (_REQUIRED | _OPTIONAL):
        raise ValueError("Loadout must contain only the supported reviewed profile fields.")
    if type(profile["version"]) is not int or profile["version"] != 1:
        raise ValueError("Unknown loadout version.")
    for key, catalog in (("armor", ARMOR), ("shield", SHIELDS), ("weapon", WEAPONS)):
        if not isinstance(profile[key], str) or profile[key] not in catalog:
            raise ValueError(f"Choose a supported {key}.")
    if profile["size"] not in ("Small", "Medium"):
        raise ValueError("Only reviewed Small and Medium loadouts are supported.")
    for key in ("proficiency_confirmed", "weapon_finesse", "monk_ac_eligible", "paladin_grace_eligible"):
        if type(profile.get(key, False)) is not bool:
            raise ValueError(f"{key} must be a checkbox value.")
    levels = profile["class_levels"]
    if (not isinstance(levels, dict) or not levels
            or any(name not in CLASS_NAMES or type(level) is not int or not 1 <= level <= 20
                   for name, level in levels.items()) or sum(levels.values()) > 20):
        raise ValueError("Confirm supported class levels totaling at most 20.")
    focus = profile["weapon_focus_weapon"]
    if not isinstance(focus, str) or focus and focus not in WEAPONS:
        raise ValueError("Weapon Focus needs a supported weapon or a blank selection.")
    if (focus or profile["weapon_finesse"]) and _base_attack(levels) < 1:
        raise ValueError("Weapon Focus and Weapon Finesse require base attack bonus +1.")
    weapon = WEAPONS[profile["weapon"]]
    if weapon["hands"] == 2 and profile["shield"] != "None":
        raise ValueError("This two-handed weapon cannot be used with the selected shield.")
    if profile["weapon_finesse"] and not weapon["finesse"]:
        raise ValueError("Weapon Finesse does not apply to the selected weapon.")
    if profile.get("monk_ac_eligible", False) and not levels.get("Monk"):
        raise ValueError("Monk AC eligibility requires confirmed Monk levels.")
    if profile.get("paladin_grace_eligible", False) and levels.get("Paladin", 0) < 2:
        raise ValueError("Divine Grace eligibility requires at least two Paladin levels.")
    basis = profile["review_basis"]
    if (not isinstance(basis, dict) or set(basis) != {"class", "race", "level"}
            or not isinstance(basis["class"], str) or not isinstance(basis["race"], str)
            or type(basis["level"]) is not int or not 1 <= basis["level"] <= 20
            or sum(levels.values()) != basis["level"]):
        raise ValueError("Loadout review basis must match its confirmed class level total.")
    if creature is not None:
        validate_creature(creature)
        if creature.kind not in ("pc", "npc"):
            raise ValueError("Loadouts support class-based PCs and NPCs; racial Hit Dice are not supported.")
        if basis != {"class": creature.character_class, "race": creature.race_type, "level": creature.level}:
            raise ValueError("Character class, race or level changed; review the loadout again.")
        sheet = read_character_sheet(creature)
        for key in ("racial_hit_dice", "racial_hd", "racialHD", "level_adjustment", "levelAdjustment", "racial_hit_dice_count"):
            if sheet.get(key) not in (None, 0, "0", "", False):
                raise ValueError("Racial Hit Dice and level adjustment require separate reviewed mechanics.")
        for key in ("effective_character_level", "ecl"):
            if key in sheet and sheet[key] != creature.level:
                raise ValueError("Effective character level differs; review racial progression separately.")
        if "class_levels" in sheet and sheet["class_levels"] != levels:
            raise ValueError("Confirmed loadout classes must match the saved class history. Review history in Multiclass Advancement first.")
        feats = _saved_feats(creature)
        if profile["weapon_finesse"] and "weapon finesse" not in feats:
            raise ValueError("Weapon Finesse mode requires the saved Weapon Finesse feat.")
        if focus and not _has_focus(feats, focus):
            raise ValueError("The selected Weapon Focus requires its saved feat.")
    result = dict(profile)
    result["class_levels"], result["review_basis"] = dict(levels), dict(basis)
    for key in _OPTIONAL:
        result.setdefault(key, False)
    return result


def effective_stats(creature, profile) -> dict:
    """Calculate ordinary equipment and supported constant benefits only.

    Manual AC, saved computed values, item ownership, resources and combat
    instances remain untouched. Every returned value is a review suggestion.
    """
    profile = validate_loadout(profile, creature)
    feats = _saved_feats(creature)
    armor, shield, weapon = ARMOR[profile["armor"]], SHIELDS[profile["shield"]], WEAPONS[profile["weapon"]]
    levels = profile["class_levels"]
    modifiers = {name: ability_modifier(getattr(creature, name)) for name in (
        "strength", "dexterity", "constitution", "wisdom", "charisma")}
    dex = modifiers["dexterity"]
    ac_dex = min(dex, armor["max_dex"]) if armor["max_dex"] is not None else dex
    size = 1 if profile["size"] == "Small" else 0
    bab = _base_attack(levels)
    sources = [ARMOR_SOURCE, WEAPON_SOURCE, COMBAT_SOURCE, FEAT_SOURCE,
               "https://www.d20srd.org/srd/classes/multiclass.htm"]
    for name in levels:
        section = "npcClasses" if name in ("Adept", "Aristocrat", "Commoner", "Expert", "Warrior") else "classes"
        sources.append(f"https://www.d20srd.org/srd/{section}/{name.lower()}.htm")
    warnings = ["Ordinary equipment suggestions assume the selected size and confirmed active class levels."]
    components = [f"Armor bonus {armor['bonus']:+d}; shield bonus {shield['bonus']:+d}; "
                  f"Dexterity AC {ac_dex:+d}; size AC/attack {size:+d}. Source: {ARMOR_SOURCE}",
                  f"Base attack bonus {bab:+d}, adding each confirmed class table separately."]
    monk_bonus = 0
    if levels.get("Monk"):
        sources.append(MONK_SOURCE)
        if profile["monk_ac_eligible"] and profile["armor"] == "None" and profile["shield"] == "None":
            monk_bonus = max(0, modifiers["wisdom"]) + levels["Monk"] // 5
            components.append(f"Monk AC {monk_bonus:+d} also applies to touch and flat-footed AC. Source: {MONK_SOURCE}")
            warnings.append("Monk AC confirmation must remain unencumbered, able to move and not helpless.")
        else:
            warnings.append("Monk AC omitted: confirm eligibility and use no armor or shield.")
    base_ac = 10 + size + monk_bonus
    ac = base_ac + armor["bonus"] + shield["bonus"] + ac_dex
    # Losing a Dexterity bonus does not remove a Dexterity penalty.
    flat_ac = base_ac + armor["bonus"] + shield["bonus"] + min(0, dex)
    saves = {}
    grace = 0
    if levels.get("Paladin", 0) >= 2:
        sources.append(PALADIN_SOURCE)
        if profile["paladin_grace_eligible"]:
            grace = max(0, modifiers["charisma"])
            components.append(f"Divine Grace {grace:+d} to each save. Source: {PALADIN_SOURCE}")
        else:
            warnings.append("Divine Grace omitted until active eligibility is confirmed.")
    for label, short, ability, feat in (
            ("Fortitude", "fort", "constitution", "great fortitude"),
            ("Reflex", "ref", "dexterity", "lightning reflexes"),
            ("Will", "will", "wisdom", "iron will")):
        base = sum(2 + level // 2 if short in CLASS_PROGRESSION[name][1] else level // 3
                   for name, level in levels.items())
        feat_bonus = 2 if feat in feats else 0
        saves[label] = base + modifiers[ability] + grace + feat_bonus
        components.append(f"{label}: base {base:+d}, ability {modifiers[ability]:+d}, "
                          f"feat {feat_bonus:+d}, Divine Grace {grace:+d}.")
    initiative = dex + (4 if "improved initiative" in feats else 0)
    components.append(f"Initiative {initiative:+d}: Dexterity plus Improved Initiative once if owned.")
    attack, damage = None, None
    if profile["proficiency_confirmed"]:
        attack_ability = "dexterity" if profile["weapon_finesse"] else weapon["attack_ability"]
        focus_bonus = int(bool(profile["weapon_focus_weapon"] == profile["weapon"]
                               and _has_focus(feats, profile["weapon"])))
        finesse_penalty = shield["check_penalty"] if profile["weapon_finesse"] else 0
        attack = bab + modifiers[attack_ability] + size + focus_bonus + finesse_penalty
        strength = modifiers["strength"]
        damage_bonus = {"strength": strength, "two_handed": strength * 3 // 2 if strength > 0 else strength,
                        "bow": min(0, strength), "none": 0}[weapon["damage_mode"]]
        dice = weapon["small_damage"] if profile["size"] == "Small" else weapon["medium_damage"]
        damage = dice + (f"{damage_bonus:+d}" if damage_bonus else "")
        components.append(f"Attack: BAB {bab:+d}, {attack_ability} {modifiers[attack_ability]:+d}, "
                          f"size {size:+d}, Weapon Focus {focus_bonus:+d}, finesse shield penalty {finesse_penalty:+d}.")
        components.append(f"Damage: {dice}, Strength contribution {damage_bonus:+d}. Source: {WEAPON_SOURCE}")
        if damage_bonus < 0:
            warnings.append("A successful damaging hit still deals at least 1 damage; the dice expression alone does not enforce this.")
    else:
        warnings.append("Attack and damage omitted until weapon, armor and shield proficiency are confirmed.")
    if profile["weapon_focus_weapon"] and profile["weapon_focus_weapon"] != profile["weapon"]:
        warnings.append("Weapon Focus selection does not match the equipped weapon; no bonus applied.")
    unsupported = [
        "Magic, masterwork, special materials, natural armor, racial traits and racial Hit Dice.",
        "Conditions, encumbrance penalties, cover, range, ammunition, thrown modes and situational modifiers.",
        "Full attacks, two-weapon fighting, flurry, rage, smite, sneak attack and other active class features.",
        "Uncanny dodge and other unlisted passive class features; flat-footed AC assumes Dexterity bonus is lost.",
        "Dodge target, Power Attack, Cleave, Point Blank Shot and other situational feat benefits.",
        "Prestige classes, epic levels, unlisted spell effects, spell failure and movement/skill penalties.",
    ]
    return {"ac": ac, "touch_ac": base_ac + ac_dex, "flat_footed_ac": flat_ac,
            "armor_bonus": armor["bonus"], "shield_bonus": shield["bonus"],
            "manual_ac": creature.armor_class, "attack_bonus": attack, "damage_expression": damage,
            "threat_min": weapon["threat_min"], "multiplier": weapon["multiplier"],
            "saves": saves, "initiative": initiative,
            "armor_check_penalty": armor["check_penalty"] + shield["check_penalty"],
            "max_dex": armor["max_dex"], "components": components,
            "warnings": warnings, "sources": sources, "unsupported": unsupported}
