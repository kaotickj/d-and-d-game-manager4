"""Reviewed higher-level spell plans; never changes a live encounter.

Numeric class progression comes from cited SRD tables. Indexed spell names
are checked against the local SRD catalog. Custom entries require an explicit
DM review note. Existing first-level spellbook data is preserved verbatim.
"""
from __future__ import annotations

from copy import deepcopy
from dataclasses import asdict, replace
import json

from .models import Creature
from .spell_rules import SPELL_LISTS, bonus_slots
from .spell_tables import BASE_SLOTS, KNOWN_LIMITS, SOURCES
from .storage import validate

CASTING_ABILITIES = {"Wizard": "intelligence", "Sorcerer": "charisma",
                     "Bard": "charisma", "Cleric": "wisdom", "Druid": "wisdom",
                     "Paladin": "wisdom", "Ranger": "wisdom", "Adept": "wisdom"}
GROUPS = ("known", "prepared", "spellbook", "domain_prepared")


def progression_profile(class_name: str, class_level: int, ability_score: int) -> dict:
    if class_name not in BASE_SLOTS:
        raise ValueError("Choose an SRD spellcasting class.")
    if type(class_level) is not int or not 1 <= class_level <= 20:
        raise ValueError("Spell progression supports class levels 1 through 20.")
    if type(ability_score) is not int or not 0 <= ability_score <= 99:
        raise ValueError("Casting ability must be a score between 0 and 99.")
    row = BASE_SLOTS[class_name][class_level - 1]
    known = KNOWN_LIMITS.get(class_name, ())
    result = {"class": class_name, "class_level": class_level,
              "ability": CASTING_ABILITIES[class_name], "ability_score": ability_score,
              "mode": "spontaneous" if known else "prepared", "slots": {},
              "domain_slots": {}, "known_limits": {}, "unlocked": {}, "dc": {},
              "source": SOURCES[class_name]}
    for level in range(10):
        base = row[level] if level < len(row) else None
        eligible = base is not None and ability_score >= 10 + level
        key = str(level)
        result["unlocked"][key] = base is not None
        result["slots"][key] = (base + bonus_slots(ability_score, level)) if eligible else 0
        result["domain_slots"][key] = int(class_name == "Cleric" and level > 0 and eligible)
        result["known_limits"][key] = (known[class_level - 1][level] or 0) if known and level < len(known[class_level - 1]) else 0
        result["dc"][key] = 10 + level + (ability_score - 10) // 2
    return result


def _sheet(creature: Creature) -> dict:
    validate(creature)
    if creature.kind not in ("pc", "npc"):
        raise ValueError("Choose a class-based player character or NPC.")
    sheet = json.loads(creature.sheet_json) if creature.sheet_json else {}
    if not isinstance(sheet, dict):
        raise ValueError("The saved character sheet needs review.")
    return sheet


def caster_profiles(creature: Creature) -> dict[str, dict]:
    sheet = _sheet(creature)
    levels = sheet.get("class_levels")
    if levels is None:
        levels = {creature.character_class: creature.level}
    if (not isinstance(levels, dict) or not levels or
            any(not isinstance(name, str) or type(level) is not int or not 1 <= level <= 20
                for name, level in levels.items()) or sum(levels.values()) != creature.level):
        raise ValueError("Per-class levels must agree with the character's total level.")
    result = {name: progression_profile(name, level, getattr(creature, CASTING_ABILITIES[name]))
              for name, level in levels.items() if name in CASTING_ABILITIES}
    if not result:
        raise ValueError("No supported SRD casting class is recorded. Review multiclass history first.")
    return result


def load_spell_plan(creature: Creature, class_name: str) -> dict:
    profiles = caster_profiles(creature)
    if class_name not in profiles:
        raise ValueError("That casting class is not in this character's history.")
    sheet = _sheet(creature)
    plans = sheet.get("spell_progression", {})
    if not isinstance(plans, dict):
        raise ValueError("Saved spell progression needs review.")
    plan = plans.get(class_name)
    if plan is None:
        legacy = sheet.get("spellbook") or {}
        if not isinstance(legacy, dict):
            raise ValueError("The original spellbook needs review.")
        if legacy.get("casting_class", class_name) != class_name:
            legacy = {}
        plan = {group: deepcopy(legacy.get(group, {})) for group in GROUPS}
        plan.update(revision=0, custom_review="")
    if not isinstance(plan, dict):
        raise ValueError("The saved spell plan needs review.")
    if set(plan) - {*GROUPS, "revision", "custom_review", "profile", "custom_entries", "reviewed"}:
        raise ValueError("The saved spell plan contains unsupported fields and was not shortened.")
    if type(plan.get("revision", 0)) is not int or plan.get("revision", 0) < 0:
        raise ValueError("The saved spell-plan revision needs review.")
    review_note = plan.get("custom_review", "")
    if not isinstance(review_note, str) or len(review_note) > 5000 or "\x00" in review_note:
        raise ValueError("The saved custom spell review needs correction before editing.")
    clean = deepcopy(plan)
    for group in GROUPS:
        values = clean.get(group, {})
        if not isinstance(values, dict):
            raise ValueError("Saved spell groups must map levels to lists.")
        if set(values) - {str(level) for level in range(10)}:
            raise ValueError("Saved spell groups contain unsupported spell levels and were not shortened.")
        clean[group] = {str(level): _names(values.get(str(level), []), "Saved " + group) for level in range(10)}
    return clean


def spell_options(class_name: str, catalog=()) -> dict[str, set[str]]:
    options = {str(level): set(SPELL_LISTS.get(class_name, {}).get(level, ())) for level in range(10)}
    catalog_class = "Sorcerer/Wizard" if class_name in ("Sorcerer", "Wizard") else class_name
    for entry in catalog:
        if entry.get("class") == catalog_class and type(entry.get("level")) is int and 0 <= entry["level"] <= 9:
            options[str(entry["level"])].add(entry["name"])
    return options


def _names(value, label):
    if (not isinstance(value, list) or len(value) > 500 or
            any(not isinstance(name, str) or not name.strip() or len(name) > 110 or
                "\x00" in name or "\n" in name for name in value)):
        raise ValueError(f"{label} must be a list of at most 500 spell names.")
    try:
        for name in value:
            name.encode("utf-8")
    except UnicodeError as exc:
        raise ValueError(f"{label} contains invalid Unicode.") from exc
    return [name.strip() for name in value]


def build_spell_candidate(creature: Creature, class_name: str, plan: dict, *,
                          catalog=(), review_ack=False, custom_review="") -> Creature:
    """Return an immutable candidate after slot/list validation; no database writes."""
    if review_ack is not True:
        raise ValueError("Review the spell choices and source before saving.")
    profile = caster_profiles(creature).get(class_name)
    if profile is None:
        raise ValueError("Choose a casting class recorded for this character.")
    if not isinstance(plan, dict) or set(plan) - set(GROUPS):
        raise ValueError("Spell plans accept only known, prepared, spellbook and domain_prepared groups.")
    if not isinstance(custom_review, str) or len(custom_review) > 5000 or "\x00" in custom_review:
        raise ValueError("Custom spell review notes must be at most 5,000 characters.")
    options = spell_options(class_name, catalog)
    previous = load_spell_plan(creature, class_name)
    clean, custom = {}, []
    for group in GROUPS:
        values = plan.get(group, {})
        if not isinstance(values, dict) or set(values) - {str(level) for level in range(10)}:
            raise ValueError("Spell levels must use keys 0 through 9.")
        clean[group] = {}
        for level in range(10):
            key = str(level)
            names = _names(values.get(key, []), group)
            if group in ("known", "spellbook") and len({name.casefold() for name in names}) != len(names):
                raise ValueError("Known spells and spellbooks cannot repeat a spell at one level.")
            if names and not profile["unlocked"][key]:
                raise ValueError(f"{class_name} cannot select level-{level} spells at this class level.")
            if group in ("known", "spellbook") and profile["ability_score"] < 10 + level:
                additions = set(names) - set(previous[group][key])
                if additions:
                    raise ValueError(f"Learning level-{level} spells requires {profile['ability']} {10 + level}.")
            allowed = set(options[key])
            if group == "prepared":
                allowed.update(name for lower in range(level) for name in options[str(lower)])
            for name in names:
                if name not in allowed:
                    custom.append({"group": group, "slot_level": level, "name": name})
            clean[group][key] = names
    spontaneous = profile["mode"] == "spontaneous"
    if spontaneous and any(clean[group][key] for group in ("prepared", "spellbook", "domain_prepared") for key in clean[group]):
        raise ValueError("Spontaneous casters use spells known rather than prepared spell lists.")
    if not spontaneous and any(clean["known"].values()):
        raise ValueError("Prepared casters use prepared spells rather than spells known.")
    if class_name != "Wizard" and any(clean["spellbook"].values()):
        raise ValueError("Only Wizards use a spellbook in this core-class plan.")
    if class_name != "Cleric" and any(clean["domain_prepared"].values()):
        raise ValueError("Only Clerics receive these domain slots.")
    for level in range(10):
        key = str(level)
        if len(clean["prepared"][key]) > profile["slots"][key]:
            raise ValueError(f"Too many spells prepared in level-{level} daily slots.")
        if len(clean["domain_prepared"][key]) > profile["domain_slots"][key]:
            raise ValueError(f"Too many level-{level} domain spells.")
        if spontaneous and len(clean["known"][key]) > profile["known_limits"][key]:
            raise ValueError(f"Too many level-{level} spells known.")
        if class_name == "Wizard":
            book = {name for lower in range(level + 1) for name in clean["spellbook"][str(lower)]}
            if set(clean["prepared"][key]) - book - {"Read Magic"}:
                raise ValueError("A Wizard must record prepared spells in their spellbook first.")
    if (custom or any(clean["domain_prepared"].values())) and not custom_review.strip():
        raise ValueError("Add a DM review note for custom/unindexed spells and selected domain spells.")
    sheet = deepcopy(_sheet(creature))
    revision = previous.get("revision", 0)
    if type(revision) is not int or revision < 0:
        raise ValueError("The saved spell-plan revision needs review.")
    clean.update(revision=revision + 1, profile=profile, custom_entries=custom,
                 custom_review=custom_review.strip(), reviewed=True)
    sheet.setdefault("spell_progression", {})[class_name] = clean
    candidate = replace(creature, sheet_json=json.dumps(sheet, ensure_ascii=False, sort_keys=True))
    validate(candidate)
    return candidate


def save_spell_candidate(repository, baseline: Creature, candidate: Creature, *, catalog=()) -> Creature:
    """Save only this reviewed spell-plan change under the same stale-check lock."""
    if asdict(replace(candidate, sheet_json=baseline.sheet_json)) != asdict(baseline):
        raise ValueError("A spell review cannot change other character fields.")
    before, after = _sheet(baseline), _sheet(candidate)
    if {k: v for k, v in before.items() if k != "spell_progression"} != {k: v for k, v in after.items() if k != "spell_progression"}:
        raise ValueError("A spell review cannot change other character-sheet fields.")
    before_plans, after_plans = before.get("spell_progression", {}), after.get("spell_progression", {})
    if not isinstance(before_plans, dict) or not isinstance(after_plans, dict):
        raise ValueError("Saved spell progression needs review.")
    changed = [name for name in set(before_plans) | set(after_plans) if before_plans.get(name) != after_plans.get(name)]
    if len(changed) != 1 or changed[0] not in after_plans:
        raise ValueError("Review one casting class at a time.")
    name = changed[0]
    plan = after_plans[name]
    if not isinstance(plan, dict):
        raise ValueError("Review a valid spell plan before saving.")
    expected = build_spell_candidate(baseline, name, {group: plan.get(group, {}) for group in GROUPS},
                                     catalog=catalog, review_ack=plan.get("reviewed"),
                                     custom_review=plan.get("custom_review", ""))
    if json.loads(expected.sheet_json) != after:
        raise ValueError("The spell candidate differs from its reviewed choices.")
    validate(candidate)
    with repository._connection() as db:
        db.execute("BEGIN IMMEDIATE")
        row = db.execute("SELECT * FROM creatures WHERE id=?", (baseline.id,)).fetchone()
        if row is None or asdict(repository._from_row(row)) != asdict(baseline):
            raise ValueError("The character changed after this spell review opened. Reopen it before saving.")
        db.execute("UPDATE creatures SET sheet_json=?,updated_at=CURRENT_TIMESTAMP WHERE id=?",
                   (candidate.sheet_json, baseline.id))
        saved = db.execute("SELECT * FROM creatures WHERE id=?", (baseline.id,)).fetchone()
    return repository._from_row(saved)
