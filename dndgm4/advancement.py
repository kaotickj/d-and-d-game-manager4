"""Reviewed single-class D&D 3.5 advancement with auditable choices.

Numeric progression is deterministic. Feature labels and spell-review notes do
not imply their complete combat effects have been automated. Sources and scope
are recorded in docs/ADVANCEMENT_RULES.md.
"""
from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
import json

from .build_rules import FIGHTER_BONUS, PREREQUISITES, SIMPLE_FEATS, automatic_class_feats
from .character_sheet import SKILLS, TEMPLATES, NPC_CLASS_TEMPLATES
from .creation import ABILITIES, CORE_CLASSES
from .dice import ability_modifier
from .models import Creature
from .storage import validate

# (BAB progression, good saves). Rates are the SRD class tables, not fractions
# added to prior rounded levels, so every target level is calculated afresh.
CLASS_PROGRESSION = {
    "Barbarian": ("full", ("fort",)), "Bard": ("three_quarters", ("ref", "will")),
    "Cleric": ("three_quarters", ("fort", "will")),
    "Druid": ("three_quarters", ("fort", "will")), "Fighter": ("full", ("fort",)),
    "Monk": ("three_quarters", ("fort", "ref", "will")),
    "Paladin": ("full", ("fort",)), "Ranger": ("full", ("fort", "ref")),
    "Rogue": ("three_quarters", ("ref",)), "Sorcerer": ("half", ("will",)),
    "Wizard": ("half", ("will",)), "Adept": ("half", ("will",)),
    "Aristocrat": ("three_quarters", ("will",)), "Commoner": ("half", ()),
    "Expert": ("three_quarters", ("will",)), "Warrior": ("full", ("fort",)),
}
ABILITY_PRIORITIES = {
    "Barbarian": "strength", "Bard": "charisma", "Cleric": "wisdom",
    "Druid": "wisdom", "Fighter": "strength", "Monk": "wisdom",
    "Paladin": "strength", "Ranger": "dexterity", "Rogue": "dexterity",
    "Sorcerer": "charisma", "Wizard": "intelligence", "Adept": "wisdom",
    "Aristocrat": "charisma", "Commoner": "constitution", "Expert": "intelligence",
    "Warrior": "strength", "Artificer": "intelligence", "Beguiler": "intelligence",
    "Dragon Shaman": "constitution", "Duskblade": "intelligence",
    "Favored Soul": "charisma", "Hexblade": "strength", "Knight": "constitution",
    "Ninja": "dexterity", "Psion": "intelligence", "Psychic Warrior": "wisdom",
    "Samurai": "strength", "Scout": "dexterity", "Soulknife": "dexterity",
    "Spellthief": "dexterity", "Spirit Shaman": "wisdom", "Swashbuckler": "dexterity",
    "Warlock": "charisma", "Warmage": "charisma", "Wilder": "charisma",
}
DEFAULT_BUILDS = {
    name: {"ability": ABILITY_PRIORITIES.get(name, "constitution"),
           "skills": tuple(template.suggested_skills),
           "feats": tuple(template.suggested_feats)}
    for name, template in TEMPLATES.items()
}
_WIZARD_FEATS = ("Extend Spell", "Enlarge Spell", "Silent Spell", "Still Spell",
                 "Empower Spell", "Heighten Spell", "Maximize Spell", "Quicken Spell")
_SAFE_GENERAL = ("Improved Initiative", "Alertness", "Iron Will", "Great Fortitude",
                 "Lightning Reflexes", "Blind-Fight", "Combat Casting", "Endurance",
                 "Run", "Acrobatic", "Athletic", "Negotiator", "Stealthy")
# Toughness and Skill Focus need per-level HP or an additional skill choice;
# omit these from automatic defaults while allowing manual review selections.
_SAFE_FEATS = (SIMPLE_FEATS - {"Toughness", "Skill Focus"}) | set(PREREQUISITES)
_MONK_FEATS = {2: ("Combat Reflexes", "Deflect Arrows"),
               6: ("Improved Disarm", "Improved Trip")}
_ROGUE_SPECIALS = ("Crippling Strike", "Defensive Roll", "Improved Evasion",
                   "Opportunist", "Slippery Mind")
_FAVORED_ENEMIES = ("Aberration", "Animal", "Construct", "Dragon", "Elemental", "Fey",
                    "Giant", "Humanoid (goblinoid)", "Humanoid (orc)", "Magical beast",
                    "Monstrous humanoid", "Ooze", "Outsider (evil)", "Plant", "Undead", "Vermin")
_DEFAULT_FOCUS_WEAPONS = {
    "Barbarian": "greataxe", "Bard": "shortsword", "Cleric": "heavy mace",
    "Druid": "scimitar", "Fighter": "longsword", "Monk": "quarterstaff",
    "Paladin": "longsword", "Ranger": "longbow", "Rogue": "rapier",
    "Sorcerer": "quarterstaff", "Wizard": "quarterstaff", "Adept": "quarterstaff",
    "Aristocrat": "rapier", "Commoner": "quarterstaff", "Expert": "dagger",
    "Warrior": "longsword",
}


def _owned_feat_names(feats: list[str]) -> set[str]:
    """Recognize qualified saved feats when checking progression choices.

    A second Weapon Focus for another weapon is legal in the SRD, but choosing
    repeatable feat instances is outside this first guided implementation.
    """
    return {"Weapon Focus" if feat.startswith("Weapon Focus (") and feat.endswith(")")
            else feat for feat in feats}


def _sheet(creature: Creature) -> dict:
    validate(creature)
    if creature.kind not in ("pc", "npc"):
        raise ValueError("Level up is for class-based PCs and NPCs, not monster Hit Dice.")
    if type(creature.level) is not int or not 1 <= creature.level < 20:
        raise ValueError("Guided advancement supports character levels 1 through 20.")
    if not creature.character_class.strip():
        raise ValueError("Choose a class before leveling up.")
    if any(separator in creature.character_class for separator in ("/", "+", ";", ",")):
        raise ValueError("Multiclass advancement needs per-class history and is not supported yet.")
    try:
        sheet = json.loads(creature.sheet_json) if creature.sheet_json else {}
    except (ValueError, TypeError, RecursionError) as exc:
        raise ValueError("The saved character sheet could not be read.") from exc
    if not isinstance(sheet, dict):
        raise ValueError("The saved character sheet must be an object.")
    if sheet.get("class", creature.character_class) != creature.character_class:
        raise ValueError("Saved sheet class does not match the library class; review the record first.")
    if "class_levels" in sheet and sheet["class_levels"] != {creature.character_class: creature.level}:
        raise ValueError("Multiclass or inconsistent class-level history needs review first.")
    progression = sheet.get("progression", {})
    if not isinstance(progression, dict):
        raise ValueError("Saved progression must be an object.")
    if progression and (progression.get("class", creature.character_class) != creature.character_class
                        or progression.get("class_level", creature.level) != creature.level):
        raise ValueError("Saved progression is inconsistent with the character's current level.")
    for key in ("feats", "class_features"):
        values = sheet.get(key, [])
        if not isinstance(values, list) or any(not isinstance(x, str) for x in values):
            raise ValueError(f"Saved {key.replace('_', ' ')} must be a list of names.")
    history = sheet.get("advancement_history", [])
    if not isinstance(history, list) or any(not isinstance(x, dict) for x in history):
        raise ValueError("Saved advancement history must be a list of entries.")
    if history and history[-1].get("to_level") != creature.level:
        raise ValueError("Saved advancement history does not end at the current level.")
    skills = sheet.get("skills_half_ranks", {})
    if not isinstance(skills, dict) or any(name not in SKILLS or type(ticks) is not int or ticks < 0
                                           for name, ticks in skills.items()):
        raise ValueError("Saved skills must use supported names and nonnegative half-rank ticks.")
    return sheet


def _validate_profile(profile: dict) -> dict:
    if not isinstance(profile, dict):
        raise ValueError("A class progression profile is required.")
    hd, rate = profile.get("hit_die"), profile.get("skill_points")
    if type(hd) is not int or not 4 <= hd <= 20:
        raise ValueError("Class hit die must be d4 through d20.")
    if type(rate) is not int or not 1 <= rate <= 20:
        raise ValueError("Class skill-point rate must be 1 through 20.")
    bab = profile.get("bab_progression")
    if bab not in ("full", "three_quarters", "half"):
        raise ValueError("Choose full, three_quarters, or half BAB progression.")
    saves = profile.get("good_saves")
    if (not isinstance(saves, list) or any(save not in ("fort", "ref", "will") for save in saves)
            or len(set(saves)) != len(saves)):
        raise ValueError("Choose the class's good saving throws: fort, ref, and/or will.")
    skills = profile.get("class_skills")
    if (not isinstance(skills, list) or any(name not in SKILLS for name in skills)
            or len(set(skills)) != len(skills)):
        raise ValueError("Class skills must be distinct supported skill names.")
    return {"hit_die": hd, "skill_points": rate, "bab_progression": bab,
            "good_saves": list(saves), "class_skills": list(skills)}


def default_progression_profile(creature: Creature) -> dict:
    sheet = _sheet(creature)
    template = TEMPLATES.get(creature.character_class)
    return {"hit_die": template.hit_die if template else sheet.get("custom_hd", 8),
            "skill_points": template.skill_points if template else sheet.get("custom_skill_points", 4),
            "bab_progression": "", "good_saves": [],
            "class_skills": list(template.class_skills) if template else sheet.get("custom_class_skills", [])}


def needs_progression_profile(creature: Creature) -> bool:
    sheet = _sheet(creature)
    return creature.character_class not in CLASS_PROGRESSION and "advancement_profile" not in sheet


def _profile(creature: Creature, sheet: dict, profile: dict | None = None) -> dict:
    name = creature.character_class
    if name in CLASS_PROGRESSION:
        template = TEMPLATES[name]
        bab, saves = CLASS_PROGRESSION[name]
        skills = list(template.class_skills)
        manual = sheet.get("custom_class_skills", [])
        if not isinstance(manual, list) or any(skill not in SKILLS for skill in manual):
            raise ValueError("Saved additional class skills need review.")
        if name == "Expert":
            if len(set(manual)) != 10:
                raise ValueError("Expert requires ten chosen class skills before advancement.")
            skills = list(manual)
        else:
            skills = list(dict.fromkeys(skills + manual))
        return {"hit_die": template.hit_die, "skill_points": template.skill_points,
                "bab_progression": bab, "good_saves": list(saves), "class_skills": skills}
    supplied = profile if profile is not None else sheet.get("advancement_profile")
    if supplied is None:
        raise ValueError("This class needs a GM-confirmed progression profile: hit die, skill rate, BAB, saves, and class skills.")
    return _validate_profile(supplied)


def _bab(level: int, progression: str) -> int:
    return level if progression == "full" else (3 * level // 4 if progression == "three_quarters" else level // 2)


def _spell_review(name: str, level: int) -> bool:
    return name in ("Bard", "Cleric", "Druid", "Sorcerer", "Wizard", "Adept") or (
        name in ("Ranger", "Paladin") and level >= 4)


def _feat_slots(name: str, level: int) -> dict:
    return {"general": int(level % 3 == 0),
            "fighter_bonus": int(name == "Fighter" and level % 2 == 0),
            "monk_bonus": int(name == "Monk" and level in _MONK_FEATS),
            "wizard_bonus": int(name == "Wizard" and level % 5 == 0)}


def _qualifies(feat: str, owned: set[str], scores: dict, bab: int) -> bool:
    rule = PREREQUISITES.get(feat)
    if rule:
        attr, minimum, needed, min_bab = rule
        return (not attr or scores[attr] >= minimum) and (not needed or needed in owned) and bab >= min_bab
    return feat in _SAFE_FEATS or feat in _WIZARD_FEATS


def _choice_requests(name: str, level: int, sheet: dict) -> list[dict]:
    requests = []
    if name == "Ranger" and level == 2:
        requests.append({"key": "combat_style", "label": "Combat style",
                         "options": ["Archery", "Two-weapon combat"], "default": "Archery"})
    if name == "Ranger" and level in (6, 11) and sheet.get("advancement_choices", {}).get("combat_style") not in ("Archery", "Two-weapon combat"):
        requests.append({"key": "combat_style", "label": "Previously chosen combat style",
                         "options": ["Archery", "Two-weapon combat"]})
    if name == "Ranger" and level % 5 == 0:
        requests.extend([
            {"key": "favored_enemy", "label": "Additional favored enemy", "options": list(_FAVORED_ENEMIES), "default": "Undead"},
            {"key": "favored_enemy_increase", "label": "Favored enemy receiving the +2 increase (record existing choice)", "options": []},
        ])
    if name == "Rogue" and level in (10, 13, 16, 19):
        used = set(sheet.get("advancement_choices", {}).values())
        options = [label for label in _ROGUE_SPECIALS if label not in used]
        requests.append({"key": f"special_ability_{level}", "label": "Rogue special ability",
                         "options": options, "default": options[0]})
    if name not in CLASS_PROGRESSION:
        requests.append({"key": "class_progression", "label": "Class features and bonus selections for this level (GM-reviewed)", "options": []})
    return requests


def _features(name: str, level: int, class_choices: dict) -> list[str]:
    result = []
    if name == "Rogue":
        if level % 2: result.append(f"Sneak attack +{(level + 1) // 2}d6")
        if level in (2, 4, 8): result.append({2: "Evasion", 4: "Uncanny dodge", 8: "Improved uncanny dodge"}[level])
    elif name == "Barbarian":
        if level in (2, 5, 11, 14, 17, 20):
            result.append({2: "Uncanny dodge", 5: "Improved uncanny dodge", 11: "Greater rage", 14: "Indomitable will", 17: "Tireless rage", 20: "Mighty rage"}[level])
    elif name == "Monk":
        labels = {2: "Evasion", 3: "Still mind", 4: "Ki strike (magic)", 5: "Purity of body", 7: "Wholeness of body", 9: "Improved evasion", 10: "Ki strike (lawful)", 11: "Diamond body", 12: "Abundant step", 13: "Diamond soul", 15: "Quivering palm", 16: "Ki strike (adamantine)", 17: "Timeless body; tongue of the sun and moon", 19: "Empty body", 20: "Perfect self"}
        if level in labels: result.append(labels[level])
    elif name == "Ranger":
        labels = {3: "Endurance", 4: "Animal companion", 7: "Woodland stride", 8: "Swift tracker", 9: "Evasion", 13: "Camouflage", 17: "Hide in plain sight"}
        if level in labels: result.append(labels[level])
        if level in (2, 6, 11): result.append(f"Combat style: {class_choices.get('combat_style', '')} (light or no armor)")
    elif name == "Paladin":
        labels = {2: "Divine grace; lay on hands", 3: "Aura of courage; divine health", 4: "Turn undead", 5: "Special mount", 6: "Remove disease 1/week"}
        if level in labels: result.append(labels[level])
    elif name == "Adept" and level == 2: result.append("Summon familiar")
    for key, value in class_choices.items():
        if key != "combat_style": result.append(f"{key.replace('_', ' ').title()}: {value}")
    return result


def level_up_requirements(creature: Creature, *, profile: dict | None = None) -> dict:
    sheet = _sheet(creature)
    selected = _profile(creature, sheet, profile)
    name, target = creature.character_class, creature.level + 1
    skills = sheet.get("skills_half_ranks", {})
    class_skills = selected["class_skills"]
    for skill, ticks in skills.items():
        cap = 2 * (creature.level + 3) if skill in class_skills else creature.level + 3
        if ticks > cap or (skill in class_skills and ticks % 2):
            raise ValueError(f"Saved {skill} ranks exceed the current class limits; review the sheet first.")
    choices = sheet.get("advancement_choices", {})
    if not isinstance(choices, dict) or any(not isinstance(k, str) or not isinstance(v, str) for k, v in choices.items()):
        raise ValueError("Saved class choices must contain text values.")
    requests = _choice_requests(name, target, sheet)
    slots = _feat_slots(name, target)
    scores = {ability: getattr(creature, ability) for ability in ABILITIES}
    old_feats = _owned_feat_names(sheet.get("feats", []))
    class_grants = automatic_class_feats(name, target)
    prior_grants = automatic_class_feats(name, creature.level)
    automatic = [feat for feat in class_grants if feat not in prior_grants and feat not in old_feats]
    # Older creation sheets can record Track in class features rather than in
    # feats. It is still already owned, and cannot consume a later selection.
    available = old_feats | set(class_grants)
    bab = _bab(target, selected["bab_progression"])
    known = sorted(feat for feat in _SAFE_FEATS | set(_WIZARD_FEATS) if feat not in available and _qualifies(feat, available, scores, bab))
    reviews = ["Class-feature labels are recorded; situational effects, equipment, and unmodeled prerequisites remain GM-reviewed. Record additional class features or DM adjustments in class notes."]
    if sum(slots.values()):
        reviews.append("Weapon Focus requires choosing a weapon and confirming proficiency; its weapon-specific attack bonus is not automatically applied.")
    spell_review = _spell_review(name, target)
    if spell_review:
        reviews.append("Choose and record this level's spells and daily spell progression; higher-level spell selections are not automatically validated.")
    if name not in CLASS_PROGRESSION:
        reviews.append("This class uses your GM-confirmed progression profile; review its features, bonus feats, and spell/power choices for this level.")
    return {"class_name": name, "next_level": target, "hit_die": selected["hit_die"],
            "skill_points": max(1, selected["skill_points"] + ability_modifier(creature.intelligence)) + int(creature.race_type == "Human"),
            "ability_due": target % 4 == 0, "default_ability": ABILITY_PRIORITIES.get(name, "constitution"),
            "class_skills": list(class_skills), "skills": dict(skills),
            "max_class_ticks": 2 * (target + 3), "max_cross_ticks": target + 3,
            "choice_requests": requests, "manual_review": reviews,
            "spell_review_required": spell_review, "profile_supported": name in CLASS_PROGRESSION,
            "feat_slots": slots, "feat_options": known,
            "automatic_feats": automatic,
            "feat_detail_requests": [{"feat": "Weapon Focus", "label": "Weapon for Weapon Focus (confirm proficiency)"}],
            "bonus_feat_options": {"fighter_bonus": sorted(FIGHTER_BONUS), "monk_bonus": list(_MONK_FEATS.get(target, ())) if name == "Monk" else [], "wizard_bonus": list(_WIZARD_FEATS)},
            "automatic_features": _features(name, target, choices),
            "profile": selected}


def _allocate_skills(requirements: dict, points: int) -> dict:
    class_skills = set(requirements["class_skills"])
    name = requirements["class_name"]
    priorities = list(DEFAULT_BUILDS.get(name, {}).get("skills", ()))
    order = list(dict.fromkeys(priorities + requirements["class_skills"] + list(SKILLS)))
    existing, additions = requirements["skills"], {}
    remaining = points
    while remaining:
        changed = False
        for skill in order:
            if not remaining: break
            in_class = skill in class_skills
            step = 2 if in_class else 1
            cap = requirements["max_class_ticks"] if in_class else requirements["max_cross_ticks"]
            if existing.get(skill, 0) + additions.get(skill, 0) + step <= cap:
                additions[skill] = additions.get(skill, 0) + step
                remaining -= 1
                changed = True
        if not changed:
            raise ValueError("No skill capacity remains; adjust the class profile or existing ranks.")
    return additions


def default_level_choices(creature: Creature, *, profile: dict | None = None) -> dict:
    requirements = level_up_requirements(creature, profile=profile)
    ability = requirements["default_ability"] if requirements["ability_due"] else ""
    scores = {name: getattr(creature, name) + int(name == ability) for name in ABILITIES}
    points = max(1, requirements["profile"]["skill_points"] + ability_modifier(scores["intelligence"])) + int(creature.race_type == "Human")
    sheet = _sheet(creature)
    owned = (_owned_feat_names(sheet.get("feats", []))
             | set(automatic_class_feats(creature.character_class, requirements["next_level"])))
    feats = []
    bab = _bab(requirements["next_level"], requirements["profile"]["bab_progression"])
    slots = requirements["feat_slots"]
    candidates = list(DEFAULT_BUILDS.get(creature.character_class, {}).get("feats", ())) + list(_SAFE_GENERAL) + sorted(_SAFE_FEATS)
    # Reserve restricted bonus choices before filling a general feat slot.
    for slot in ("fighter_bonus", "monk_bonus", "wizard_bonus", "general"):
        count = slots[slot]
        if not count: continue
        options = candidates
        if slot == "fighter_bonus": options = [feat for feat in candidates if feat in FIGHTER_BONUS]
        elif slot == "monk_bonus": options = requirements["bonus_feat_options"][slot]
        elif slot == "wizard_bonus": options = list(_WIZARD_FEATS)
        selected = next((feat for feat in options if feat not in owned and (slot == "monk_bonus" or _qualifies(feat, owned, scores, bab))), None)
        if selected:
            feats.append(selected)
            owned.add(selected)
    feat_details = {}
    if "Weapon Focus" in feats and creature.character_class in _DEFAULT_FOCUS_WEAPONS:
        feat_details["Weapon Focus"] = _DEFAULT_FOCUS_WEAPONS[creature.character_class]
    return {"ability_increase": ability, "skill_increases": _allocate_skills(requirements, points),
            "feat_details": feat_details,
            "feats": feats, "class_choices": {request["key"]: request["default"] for request in requirements["choice_requests"] if "default" in request},
            "spell_notes": "", "class_notes": "", "review_ack": False, "profile": requirements["profile"]}


def advance_character(creature: Creature, choices: dict) -> Creature:
    if not isinstance(choices, dict):
        raise ValueError("Level-up choices must be an object.")
    requirements = level_up_requirements(creature, profile=choices.get("profile"))
    sheet = deepcopy(_sheet(creature))
    target, profile = requirements["next_level"], requirements["profile"]
    hp_roll = choices.get("hp_roll")
    if type(hp_roll) is not int or not 1 <= hp_roll <= profile["hit_die"]:
        raise ValueError(f"Roll or enter one d{profile['hit_die']} for hit points.")
    detail = choices.get("hp_roll_detail", "")
    if not isinstance(detail, str) or len(detail) > 2000:
        raise ValueError("Hit-point roll details must be short text.")
    ability = choices.get("ability_increase", "")
    if requirements["ability_due"]:
        if ability not in ABILITIES:
            raise ValueError("Choose one ability score to increase by 1.")
    elif ability:
        raise ValueError("An ability increase is only gained every fourth character level.")
    scores = {name: getattr(creature, name) + int(name == ability) for name in ABILITIES}
    if any(not 0 <= value <= 99 for value in scores.values()):
        raise ValueError("Ability score increase exceeds the library's supported range.")
    points = max(1, profile["skill_points"] + ability_modifier(scores["intelligence"])) + int(creature.race_type == "Human")
    increases = choices.get("skill_increases", {})
    if not isinstance(increases, dict):
        raise ValueError("Allocate skill increases in half-rank ticks.")
    ranks, spent = dict(requirements["skills"]), 0
    for skill, ticks in increases.items():
        if skill not in SKILLS or type(ticks) is not int or ticks < 0:
            raise ValueError("Skill increases require supported names and nonnegative half-rank ticks.")
        in_class = skill in requirements["class_skills"]
        if in_class and ticks % 2:
            raise ValueError(f"{skill}: class-skill increases must be whole ranks.")
        total = ranks.get(skill, 0) + ticks
        cap = requirements["max_class_ticks"] if in_class else requirements["max_cross_ticks"]
        if total > cap:
            raise ValueError(f"{skill}: exceeds the level-{target} rank limit.")
        ranks[skill] = total
        spent += ticks // 2 if in_class else ticks
    if spent != points:
        raise ValueError(f"Allocate exactly {points} skill points for this level (currently {spent}).")
    class_choices = choices.get("class_choices", {})
    if not isinstance(class_choices, dict) or any(not isinstance(k, str) or not isinstance(v, str) or len(v) > 4000 for k, v in class_choices.items()):
        raise ValueError("Class choices must contain short text values.")
    for request in requirements["choice_requests"]:
        selected = class_choices.get(request["key"], "").strip()
        if not selected or (request["options"] and selected not in request["options"]):
            raise ValueError(f"Choose {request['label']}.")
    spell_notes = choices.get("spell_notes", "")
    if not isinstance(spell_notes, str) or len(spell_notes) > 12000:
        raise ValueError("Spell review notes must be text under 12,000 characters.")
    if requirements["spell_review_required"] and not spell_notes.strip():
        raise ValueError("Record this level's spell selections and spell progression before saving.")
    class_notes = choices.get("class_notes", "")
    if not isinstance(class_notes, str) or len(class_notes) > 4000:
        raise ValueError("Class feature and DM adjustment notes must be text under 4,000 characters.")
    if choices.get("review_ack") is not True:
        raise ValueError("Review the listed class features and unmodeled rules before saving.")
    feats = choices.get("feats", [])
    slots = requirements["feat_slots"]
    if not isinstance(feats, list) or len(feats) != sum(slots.values()) or any(not isinstance(feat, str) or not feat.strip() or len(feat) > 180 for feat in feats):
        raise ValueError(f"Choose exactly {sum(slots.values())} new feat(s) for this level.")
    feats = [feat.strip() for feat in feats]
    owned = (_owned_feat_names(sheet.get("feats", []))
             | set(automatic_class_feats(creature.character_class, target)))
    if len(set(feats)) != len(feats) or any(feat in owned for feat in feats):
        raise ValueError("New feats must be distinct and not already on the sheet or automatically granted by this class.")
    special = set()
    if slots["monk_bonus"]:
        selected = next((feat for feat in feats if feat in requirements["bonus_feat_options"]["monk_bonus"]), None)
        if selected is None: raise ValueError("Choose a qualifying monk bonus feat.")
        special.add(selected)
    if slots["fighter_bonus"] and not any(feat in FIGHTER_BONUS for feat in feats):
        raise ValueError("One selected feat must qualify as a fighter bonus feat.")
    if slots["wizard_bonus"] and not any(feat in _WIZARD_FEATS for feat in feats):
        raise ValueError("One selected feat must qualify as a wizard bonus feat.")
    bab = _bab(target, profile["bab_progression"])
    available = owned | set(feats)
    for feat in feats:
        if feat not in special and not _qualifies(feat, available - {feat}, scores, bab):
            raise ValueError(f"{feat}: prerequisites are not satisfied or the feat needs a rule not yet encoded; choose a supported feat.")
    feat_details = choices.get("feat_details", {})
    if (not isinstance(feat_details, dict) or any(not isinstance(key, str)
            or not isinstance(value, str) or len(value) > 120 for key, value in feat_details.items())):
        raise ValueError("Feat-specific choices must contain short text values.")
    recorded_feats = list(feats)
    if "Weapon Focus" in feats:
        weapon = feat_details.get("Weapon Focus", "").strip()
        if not weapon:
            raise ValueError("Choose the weapon for Weapon Focus and confirm proficiency in the rules review.")
        feat_details = {"Weapon Focus": weapon}
        recorded_feats = [f"Weapon Focus ({weapon})" if feat == "Weapon Focus" else feat for feat in feats]
    else:
        feat_details = {}
    old_con = ability_modifier(creature.constitution)
    new_con = ability_modifier(scores["constitution"])
    hp_gain = max(1, hp_roll + new_con)
    retroactive_hp = creature.level * (new_con - old_con)
    combined_choices = {**sheet.get("advancement_choices", {}), **class_choices}
    features = _features(creature.character_class, target, combined_choices)
    if class_notes.strip():
        features.append(f"Level {target}: {class_notes.strip()}")
    base_saves = {save: 2 + target // 2 if save in profile["good_saves"] else target // 3 for save in ("fort", "ref", "will")}
    sheet["class"] = creature.character_class
    sheet["class_levels"] = {creature.character_class: target}
    sheet["skills_half_ranks"] = {name: value for name, value in ranks.items() if value}
    sheet["feats"] = sheet.get("feats", []) + recorded_feats + requirements["automatic_feats"]
    sheet["class_features"] = list(dict.fromkeys(sheet.get("class_features", []) + features))
    sheet["advancement_choices"] = combined_choices
    if spell_notes.strip():
        previous_notes = sheet.get("spell_notes", "")
        if not isinstance(previous_notes, str):
            raise ValueError("Saved spell notes must be text before advancement.")
        sheet["spell_notes"] = (previous_notes.rstrip() + "\n\n" if previous_notes.strip() else "") + f"Level {target}: {spell_notes.strip()}"
    if creature.character_class not in CLASS_PROGRESSION:
        sheet["advancement_profile"] = profile
    sheet["progression"] = {**sheet.get("progression", {}), "class": creature.character_class,
                            "class_level": target, "base_attack_bonus": bab,
                            "base_saves": base_saves, "profile_source": "SRD" if requirements["profile_supported"] else "GM-confirmed"}
    sheet["advancement_history"] = sheet.get("advancement_history", []) + [{
        "from_level": creature.level, "to_level": target, "class": creature.character_class,
        "hp_roll": hp_roll, "hp_roll_detail": detail, "constitution_modifier": new_con,
        "hp_gain": hp_gain, "retroactive_constitution_hp": retroactive_hp,
        "ability_increase": ability, "skill_points": points, "skill_increases": dict(increases),
        "feats": recorded_feats, "feat_details": dict(feat_details),
        "automatic_feats": requirements["automatic_feats"],
        "class_choices": dict(class_choices), "spell_notes": spell_notes.strip(),
        "features": features, "review_ack": True, "profile": profile,
    }]
    if class_notes.strip():
        sheet["advancement_history"][-1]["class_notes"] = class_notes.strip()
    result = replace(creature, level=target, max_hit_points=creature.max_hit_points + hp_gain + retroactive_hp,
                     sheet_json=json.dumps(sheet, ensure_ascii=False, sort_keys=True), **scores)
    validate(result)
    return result
