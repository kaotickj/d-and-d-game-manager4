"""Reviewed core/SRD NPC multiclass history and additive class advancement.

Class tables are rounded per class before summing. Spell lists remain separate
by class; no live encounter or inventory state is updated here.
"""
from __future__ import annotations

from copy import deepcopy
from dataclasses import asdict, replace
from hashlib import sha256
import json

from .advancement import (
    CLASS_PROGRESSION, _SAFE_FEATS, _WIZARD_FEATS, _bab, _choice_requests,
    _features, _owned_feat_names, _qualifies, _spell_review,
)
from .build_rules import FIGHTER_BONUS
from .character_sheet import K_ALL, SKILLS, TEMPLATES
from .creation import ABILITIES
from .dice import ability_modifier
from .models import Creature
from .storage import WRITE_COLUMNS, validate

CLASSES = tuple(CLASS_PROGRESSION)
SOURCE = "https://www.d20srd.org/srd/classes/multiclass.htm"
REVIEW = (
    "Confirm alignment, class re-entry restrictions (especially monk/paladin), favored-class/XP penalties, "
    "XP eligibility, prerequisites, class-feature interactions and any DM exceptions. These are not automatically adjudicated."
)
_MONK_BONUS = {1: ("Improved Grapple", "Stunning Fist"),
               2: ("Combat Reflexes", "Deflect Arrows"),
               6: ("Improved Disarm", "Improved Trip")}


def _automatic_feats(name, level):
    return {("Wizard", 1): ["Scribe Scroll"], ("Ranger", 1): ["Track"],
            ("Ranger", 3): ["Endurance"], ("Monk", 1): ["Improved Unarmed Strike"]}.get((name, level), [])


def _json(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _text(value, label, maximum=4000, required=False):
    if not isinstance(value, str) or len(value) > maximum or "\x00" in value:
        raise ValueError(f"{label} must be text of at most {maximum:,} characters.")
    try:
        value.encode("utf-8")
    except UnicodeError as exc:
        raise ValueError(f"{label} contains invalid Unicode.") from exc
    if required and not value.strip():
        raise ValueError(f"{label} is required.")
    return value.strip()


def _sheet(creature):
    if not isinstance(creature, Creature):
        raise ValueError("Choose a saved character.")
    for name in (*ABILITIES, "level", "max_hit_points", "armor_class"):
        if type(getattr(creature, name)) is not int:
            raise ValueError(f"Saved {name.replace('_', ' ')} must be a whole number.")
    try:
        validate(creature)
    except (TypeError, AttributeError, RecursionError) as exc:
        raise ValueError("The saved character contains unreadable fields or an excessively nested sheet.") from exc
    if creature.kind not in ("pc", "npc") or type(creature.level) is not int or not 1 <= creature.level <= 20:
        raise ValueError("Multiclass history supports class-based PCs and NPCs of total level 1–20.")
    try:
        sheet = json.loads(creature.sheet_json) if creature.sheet_json else {}
    except (ValueError, TypeError, RecursionError) as exc:
        raise ValueError("The saved character sheet could not be read.") from exc
    if not isinstance(sheet, dict):
        raise ValueError("The saved sheet must be an object.")
    baseline = sheet.get("multiclass_baseline")
    if baseline is not None:
        if not isinstance(baseline, dict):
            raise ValueError("Saved multiclass baseline must be an object.")
        order = baseline.get("level_order")
        if order is not None and (not isinstance(order, list) or len(order) > 20 or any(name not in CLASSES for name in order)):
            raise ValueError("Saved chronological classes need review.")
        _text(baseline.get("review_notes", ""), "Saved history review notes")
    for key in ("racial_hit_dice", "racial_hd", "racialHD", "level_adjustment", "levelAdjustment", "racial_hit_dice_count"):
        if sheet.get(key) not in (None, 0, "0", "", False):
            raise ValueError("Racial Hit Dice and level adjustment require a separate reviewed progression; this class-only tool cannot infer them.")
    for key in ("effective_character_level", "ecl"):
        if key in sheet and sheet[key] != creature.level:
            raise ValueError("Effective character level differs from class level; review racial Hit Dice/level adjustment separately.")
    for key in ("feats", "class_features"):
        values = sheet.get(key, [])
        if not isinstance(values, list) or len(values) > 1000 or any(not isinstance(v, str) or len(v) > 5000 for v in values):
            raise ValueError(f"Saved {key.replace('_', ' ')} need review.")
    for key in ("progression", "advancement_choices", "multiclass_choices", "multiclass_class_skills"):
        if not isinstance(sheet.get(key, {}), dict):
            raise ValueError(f"Saved {key.replace('_', ' ')} must be an object.")
    for choices in [sheet.get("advancement_choices", {}), *sheet.get("multiclass_choices", {}).values()]:
        if not isinstance(choices, dict) or any(not isinstance(key, str) or not isinstance(value, str) for key, value in choices.items()):
            raise ValueError("Saved class choices must contain text names and values.")
    for key in ("advancement_history", "multiclass_audit"):
        if not isinstance(sheet.get(key, []), list) or any(not isinstance(entry, dict) for entry in sheet.get(key, [])):
            raise ValueError(f"Saved {key.replace('_', ' ')} must be a list of entries.")
    if sheet.get("advancement_history") and sheet["advancement_history"][-1].get("to_level") != creature.level:
        raise ValueError("Saved advancement history does not end at the current character level.")
    skills = sheet.get("skills_half_ranks", {})
    if not isinstance(skills, dict) or any(name not in SKILLS or type(ticks) is not int or ticks < 0 for name, ticks in skills.items()):
        raise ValueError("Saved skills must contain supported names and nonnegative half-rank ticks.")
    return sheet


def validate_levels(levels, total):
    if not isinstance(levels, dict) or not levels or any(name not in CLASSES or type(level) is not int or not 1 <= level <= 20 for name, level in levels.items()):
        raise ValueError("Choose core or SRD NPC classes with whole class levels from 1–20.")
    if sum(levels.values()) != total:
        raise ValueError(f"Per-class levels must sum to the saved total character level {total}.")
    return dict(levels)


def class_label(levels):
    return next(iter(levels)) if len(levels) == 1 else " / ".join(f"{name} {levels[name]}" for name in sorted(levels))


def class_history(creature, *, require_confirmed=False):
    sheet = _sheet(creature)
    levels = sheet.get("class_levels")
    if levels is None and creature.character_class in CLASSES:
        levels = {creature.character_class: creature.level}
    levels = validate_levels(levels, creature.level)
    if require_confirmed:
        baseline = sheet.get("multiclass_baseline")
        if not isinstance(baseline, dict) or baseline.get("review_ack") is not True or baseline.get("no_racial_hd_ack") is not True:
            raise ValueError("Confirm the existing per-class history before multiclass advancement.")
        if sheet.get("class") != creature.character_class or creature.character_class != class_label(levels):
            raise ValueError("Saved class labels and per-class levels disagree. Review history first.")
    return levels


def _skill_list(sheet, name, expert_skills=None):
    saved = sheet.get("multiclass_class_skills", {}).get(name)
    if name == "Expert":
        if saved is not None and expert_skills is not None and expert_skills != saved:
            raise ValueError("Saved Expert class skills cannot be replaced during advancement; review history first.")
        skills = expert_skills if expert_skills is not None else saved
        if skills is None:
            skills = sheet.get("custom_class_skills", [])
        if not isinstance(skills, list) or len(skills) != 10 or any(not isinstance(skill, str) or skill not in SKILLS for skill in skills) or len(set(skills)) != 10:
            raise ValueError("Expert requires exactly ten distinct chosen class skills.")
        return list(skills)
    skills = list(TEMPLATES[name].class_skills)
    if name in ("Bard", "Wizard"):
        skills = list(dict.fromkeys(skills + list(K_ALL)))
    if saved is not None:
        if not isinstance(saved, list) or len(saved) > len(SKILLS) or any(skill not in SKILLS for skill in saved):
            raise ValueError("Saved class-skill history needs review.")
        skills = list(dict.fromkeys(skills + saved))
    elif sheet.get("class") == name:
        extra = sheet.get("custom_class_skills", [])
        if not isinstance(extra, list) or any(skill not in SKILLS for skill in extra):
            raise ValueError("Saved additional class skills need review.")
        skills = list(dict.fromkeys(skills + extra))
    return skills


def combined_progression(levels):
    result = {"base_attack_bonus": 0, "base_saves": {save: 0 for save in ("fort", "ref", "will")}}
    for name, level in levels.items():
        rate, good = CLASS_PROGRESSION[name]
        result["base_attack_bonus"] += _bab(level, rate)
        for save in result["base_saves"]:
            result["base_saves"][save] += 2 + level // 2 if save in good else level // 3
    return result


def _set_progression(sheet, levels):
    if "multiclass_original_progression" not in sheet and sheet.get("progression"):
        sheet["multiclass_original_progression"] = deepcopy(sheet["progression"])
    progression = {**sheet.get("progression", {}), **combined_progression(levels),
                   "class": class_label(levels), "character_level": sum(levels.values()),
                   "class_levels": dict(levels), "profile_source": SOURCE}
    progression.pop("class_level", None)
    sheet["progression"] = progression
    sheet["class_levels"] = dict(levels)
    sheet["class"] = class_label(levels)


def _fingerprint(creature):
    return sha256(_json(asdict(creature)).encode("utf-8")).hexdigest()


def establish_history(creature, levels, *, expert_skills=None, level_order=None,
                      review_ack=False, no_racial_hd_ack=False, review_notes=""):
    sheet = deepcopy(_sheet(creature))
    levels = validate_levels(levels, creature.level)
    if review_ack is not True or no_racial_hd_ack is not True:
        raise ValueError("Confirm the class history and that total level contains no racial Hit Dice or level adjustment.")
    review_notes = _text(review_notes, "History and class-restriction review notes", required=True)
    if level_order is not None:
        if not isinstance(level_order, list) or len(level_order) != creature.level or any(name not in levels for name in level_order):
            raise ValueError("The optional chronological class list needs one class per character level.")
        if {name: level_order.count(name) for name in levels} != levels:
            raise ValueError("Chronological class order must match the per-class totals.")
    profiles = {name: _skill_list(sheet, name, expert_skills) for name in levels}
    union = set(skill for skills in profiles.values() for skill in skills)
    for name, ticks in sheet.get("skills_half_ranks", {}).items():
        if ticks > (2 * (creature.level + 3) if name in union else creature.level + 3):
            raise ValueError(f"Saved {name} ranks exceed the confirmed class-history limit; review ranks first.")
    inputs = {"levels": dict(levels), "expert_skills": expert_skills, "level_order": level_order,
              "review_ack": True, "no_racial_hd_ack": True, "review_notes": review_notes}
    sheet["multiclass_baseline"] = {"total_level": creature.level, **deepcopy(inputs)}
    sheet["multiclass_class_skills"] = {**sheet.get("multiclass_class_skills", {}), **profiles}
    if creature.character_class in levels and creature.character_class not in sheet.get("multiclass_choices", {}):
        sheet["multiclass_choices"] = {**sheet.get("multiclass_choices", {}),
                                      creature.character_class: deepcopy(sheet.get("advancement_choices", {}))}
    sheet["multiclass_audit"] = sheet.get("multiclass_audit", []) + [{
        "operation": "establish", "source_fingerprint": _fingerprint(creature), "inputs": inputs,
        "original_class_label": creature.character_class, "source": SOURCE}]
    _set_progression(sheet, levels)
    candidate = replace(creature, character_class=class_label(levels), sheet_json=_json(sheet))
    validate(candidate)
    return candidate


def multiclass_requirements(creature, selected_class, *, expert_skills=None):
    sheet = _sheet(creature)
    levels = class_history(creature, require_confirmed=True)
    if creature.level >= 20:
        raise ValueError("Guided multiclass advancement ends at total character level 20.")
    if selected_class not in CLASSES:
        raise ValueError("Choose a core or SRD NPC class.")
    target_levels = {**levels, selected_class: levels.get(selected_class, 0) + 1}
    target, class_target = creature.level + 1, target_levels[selected_class]
    selected_skills = _skill_list(sheet, selected_class, expert_skills)
    union = set(selected_skills)
    for name in levels:
        union.update(_skill_list(sheet, name, expert_skills))
    old_union = set(skill for name in levels for skill in _skill_list(sheet, name, expert_skills))
    for skill, ticks in sheet.get("skills_half_ranks", {}).items():
        if ticks > (2 * (creature.level + 3) if skill in old_union else creature.level + 3):
            raise ValueError(f"Saved {skill} ranks exceed the current character-level limit.")
    class_choices = sheet.get("multiclass_choices", {}).get(selected_class, {})
    if not isinstance(class_choices, dict):
        raise ValueError("Saved per-class feature choices need review.")
    choice_sheet = {**sheet, "advancement_choices": class_choices}
    requests = _choice_requests(selected_class, class_target, choice_sheet)
    if selected_class == "Ranger" and class_target == 1:
        requests.append({"key": "favored_enemy", "label": "First favored enemy", "options": []})
    slots = {"general": int(target % 3 == 0),
             "fighter_bonus": int(selected_class == "Fighter" and (class_target == 1 or class_target % 2 == 0)),
             "monk_bonus": int(selected_class == "Monk" and class_target in _MONK_BONUS),
             "wizard_bonus": int(selected_class == "Wizard" and class_target % 5 == 0)}
    return {"selected_class": selected_class, "class_levels": target_levels, "character_level": target,
            "class_level": class_target, "hit_die": TEMPLATES[selected_class].hit_die,
            "skill_points": max(1, TEMPLATES[selected_class].skill_points + ability_modifier(creature.intelligence)) + int(creature.race_type == "Human"),
            "ability_due": target % 4 == 0, "current_class_skills": selected_skills,
            "class_skill_union": sorted(union), "skills": dict(sheet.get("skills_half_ranks", {})),
            "feat_slots": slots, "choice_requests": requests, "spell_review_required": _spell_review(selected_class, class_target),
            "bonus_feat_options": {"fighter_bonus": sorted(FIGHTER_BONUS), "monk_bonus": list(_MONK_BONUS.get(class_target, ())),
                                   "wizard_bonus": list(_WIZARD_FEATS)},
            "automatic_feats": [feat for feat in _automatic_feats(selected_class, class_target)
                                if feat not in _owned_feat_names(sheet.get("feats", []))],
            "progression": combined_progression(target_levels), "review": REVIEW}


def default_multiclass_choices(creature, selected_class, *, expert_skills=None):
    req = multiclass_requirements(creature, selected_class, expert_skills=expert_skills)
    ranks, increases, left = dict(req["skills"]), {}, req["skill_points"]
    current = set(req["current_class_skills"])
    union = set(req["class_skill_union"])
    order = list(dict.fromkeys(list(TEMPLATES[selected_class].suggested_skills) + req["current_class_skills"] + list(SKILLS)))
    while left:
        selected = next((skill for skill in order if ranks.get(skill, 0) + (2 if skill in current else 1)
                         <= (2 * (req["character_level"] + 3) if skill in union else req["character_level"] + 3)), None)
        if selected is None:
            raise ValueError("No supported skill has room for the remaining points; allocate with the DM.")
        ticks = 2 if selected in current else 1
        ranks[selected] = ranks.get(selected, 0) + ticks
        increases[selected] = increases.get(selected, 0) + ticks
        left -= 1
    sheet = _sheet(creature)
    owned = _owned_feat_names(sheet.get("feats", [])) | set(req["automatic_feats"])
    scores = {ability: getattr(creature, ability) for ability in ABILITIES}
    feats = {}
    for slot in ("monk_bonus", "fighter_bonus", "wizard_bonus", "general"):
        if not req["feat_slots"][slot]:
            feats[slot] = []
            continue
        options = req["bonus_feat_options"].get(slot, sorted(_SAFE_FEATS | set(_WIZARD_FEATS)))
        chosen = next((feat for feat in options if feat not in owned and (slot == "monk_bonus" or
                       _qualifies(feat, owned, scores, req["progression"]["base_attack_bonus"]))), None)
        feats[slot] = [chosen] if chosen else []
        if chosen:
            owned.add(chosen)
    return {"hp_roll": None, "hp_roll_detail": "", "ability_increase": "strength" if req["ability_due"] else "",
            "skill_increases": increases, "feat_selections": feats, "feat_details": {}, "expert_skills": expert_skills,
            "class_choices": {request["key"]: request.get("default", "") for request in req["choice_requests"]},
            "class_notes": "", "spell_notes": "", "restriction_notes": "", "review_ack": False}


def advance_multiclass(creature, selected_class, choices):
    if not isinstance(choices, dict):
        raise ValueError("Advancement choices must be an object.")
    req = multiclass_requirements(creature, selected_class, expert_skills=choices.get("expert_skills"))
    sheet = deepcopy(_sheet(creature))
    if choices.get("review_ack") is not True:
        raise ValueError("Acknowledge the class features and multiclass restrictions before previewing the change.")
    restrictions = _text(choices.get("restriction_notes", ""), "DM review of XP, alignment and class restrictions", required=True)
    class_notes = _text(choices.get("class_notes", ""), "Reviewed class features and choices", required=True)
    spell_notes = _text(choices.get("spell_notes", ""), "Spell review notes", 12000, req["spell_review_required"])
    roll = choices.get("hp_roll")
    if type(roll) is not int or not 1 <= roll <= req["hit_die"]:
        raise ValueError(f"Roll or enter one d{req['hit_die']} for the chosen class's HP.")
    roll_detail = _text(choices.get("hp_roll_detail", ""), "HP roll details", 2000)
    ability = choices.get("ability_increase", "")
    if (req["ability_due"] and ability not in ABILITIES) or (not req["ability_due"] and ability):
        raise ValueError("Choose an ability increase only at total character levels divisible by four.")
    scores = {name: getattr(creature, name) + int(name == ability) for name in ABILITIES}
    if any(value > 99 for value in scores.values()):
        raise ValueError("Ability score exceeds the supported maximum.")
    budget = max(1, TEMPLATES[selected_class].skill_points + ability_modifier(scores["intelligence"])) + int(creature.race_type == "Human")
    additions = choices.get("skill_increases", {})
    if not isinstance(additions, dict):
        raise ValueError("Skill increases must map supported skills to half-rank ticks.")
    ranks, spent = dict(req["skills"]), 0
    for skill, ticks in additions.items():
        if skill not in SKILLS or type(ticks) is not int or ticks < 0:
            raise ValueError("Skill increases need supported skill names and nonnegative half-rank ticks.")
        current = skill in req["current_class_skills"]
        if current and ticks % 2:
            raise ValueError(f"{skill}: a current-class skill point buys a whole rank (two ticks).")
        total = ranks.get(skill, 0) + ticks
        cap = 2 * (req["character_level"] + 3) if skill in req["class_skill_union"] else req["character_level"] + 3
        if total > cap:
            raise ValueError(f"{skill}: exceeds the multiclass rank cap.")
        ranks[skill] = total
        spent += ticks // 2 if current else ticks
    if spent != budget:
        raise ValueError(f"Allocate exactly {budget} new skill points; currently {spent}. New classes do not multiply skill points by four.")
    selections = choices.get("feat_selections", {})
    if not isinstance(selections, dict) or set(selections) - set(req["feat_slots"]):
        raise ValueError("Choose feats in the listed general and class-bonus slots.")
    owned = _owned_feat_names(sheet.get("feats", [])) | set(req["automatic_feats"])
    chosen, monk_exceptions = [], set()
    for slot, count in req["feat_slots"].items():
        values = selections.get(slot, [])
        if not isinstance(values, list) or len(values) != count:
            raise ValueError(f"Choose exactly {count} feat(s) for {slot.replace('_', ' ')}.")
        for feat in values:
            feat = _text(feat, "Feat", 180, True)
            if feat in owned or feat in chosen:
                raise ValueError("New feats must be distinct and not already owned or automatically granted this level.")
            if slot != "general" and feat not in req["bonus_feat_options"][slot]:
                raise ValueError(f"{feat} is not a supported {slot.replace('_', ' ')} selection.")
            if slot == "monk_bonus":
                monk_exceptions.add(feat)
            chosen.append(feat)
    for feat in chosen:
        if feat not in monk_exceptions and not _qualifies(feat, owned | (set(chosen) - {feat}), scores, req["progression"]["base_attack_bonus"]):
            raise ValueError(f"{feat}: encoded prerequisites are not met using the combined BAB, or this feat is not supported.")
    details = choices.get("feat_details", {})
    if not isinstance(details, dict) or set(details) - {"Weapon Focus"}:
        raise ValueError("Only the supported Weapon Focus weapon detail is accepted.")
    details = {key: _text(value, "Feat-specific choice", 120, True) for key, value in details.items()}
    if details and "Weapon Focus" not in chosen:
        raise ValueError("Weapon Focus details apply only when selecting that feat.")
    recorded = list(chosen)
    if "Weapon Focus" in chosen:
        weapon = _text(details.get("Weapon Focus", ""), "Weapon Focus weapon and reviewed proficiency", 120, True)
        recorded = [f"Weapon Focus ({weapon})" if feat == "Weapon Focus" else feat for feat in chosen]
    automatic = req["automatic_feats"]
    class_choices = choices.get("class_choices", {})
    if not isinstance(class_choices, dict) or any(not isinstance(key, str) or len(key) > 120 for key in class_choices):
        raise ValueError("Class choices must map short names to reviewed text.")
    class_choices = {key: _text(value, "Class choice", 4000, True) for key, value in class_choices.items()}
    allowed = {request["key"] for request in req["choice_requests"]}
    if set(class_choices) - allowed:
        raise ValueError("Use class notes for choices outside the listed requests.")
    for request in req["choice_requests"]:
        value = class_choices.get(request["key"], "")
        if not value or (request["options"] and value not in request["options"]):
            raise ValueError(f"Choose {request['label']}.")
    previous = sheet.get("multiclass_choices", {}).get(selected_class, {})
    combined = {**previous, **class_choices}
    features = _features(selected_class, req["class_level"], combined) + [f"{selected_class} {req['class_level']}: {class_notes}"]
    old_con, new_con = ability_modifier(creature.constitution), ability_modifier(scores["constitution"])
    gain = max(1, roll + new_con)
    retroactive = creature.level * (new_con - old_con)
    sheet["skills_half_ranks"] = {skill: ticks for skill, ticks in ranks.items() if ticks}
    sheet["feats"] = sheet.get("feats", []) + recorded + automatic
    sheet["class_features"] = list(dict.fromkeys(sheet.get("class_features", []) + features))
    sheet["multiclass_choices"] = {**sheet.get("multiclass_choices", {}), selected_class: combined}
    sheet["multiclass_class_skills"] = {**sheet.get("multiclass_class_skills", {}), selected_class: req["current_class_skills"]}
    if spell_notes:
        old_notes = sheet.get("spell_notes", "")
        _text(old_notes, "Saved spell notes", 100000)
        sheet["spell_notes"] = (old_notes.rstrip() + "\n\n" if old_notes.strip() else "") + f"{selected_class} {req['class_level']} (character {req['character_level']}): {spell_notes}"
    entry = {"from_level": creature.level, "to_level": req["character_level"], "class": selected_class,
             "class_level": req["class_level"], "class_levels": req["class_levels"], "hp_roll": roll,
             "hit_die": req["hit_die"], "hp_roll_detail": roll_detail, "constitution_modifier": new_con, "hp_gain": gain,
             "retroactive_constitution_hp": retroactive, "ability_increase": ability, "skill_points": budget,
             "skill_increases": dict(additions), "feats": recorded, "feat_details": dict(details), "automatic_feats": automatic,
             "class_choices": class_choices, "class_notes": class_notes, "spell_notes": spell_notes,
             "restriction_notes": restrictions, "review_ack": True, "source": SOURCE}
    sheet["advancement_history"] = sheet.get("advancement_history", []) + [entry]
    sheet["multiclass_audit"] = sheet.get("multiclass_audit", []) + [{"operation": "advance",
        "source_fingerprint": _fingerprint(creature), "selected_class": selected_class, "choices": deepcopy(choices), "source": SOURCE}]
    _set_progression(sheet, req["class_levels"])
    candidate = replace(creature, level=req["character_level"], character_class=class_label(req["class_levels"]),
                        max_hit_points=creature.max_hit_points + gain + retroactive, sheet_json=_json(sheet), **scores)
    validate(candidate)
    return candidate


def save_multiclass_candidate(repository, baseline, candidate):
    """Rebuild the reviewed operation and compare the full saved record under lock."""
    if not isinstance(baseline, Creature) or not isinstance(candidate, Creature) or not baseline.id or candidate.id != baseline.id:
        raise ValueError("Choose the original saved character before applying advancement.")
    sheet = _sheet(candidate)
    audit = sheet.get("multiclass_audit", [])
    if not audit or audit[-1].get("source_fingerprint") != _fingerprint(baseline):
        raise ValueError("This multiclass draft does not match its original character.")
    operation = audit[-1]
    if operation.get("operation") == "establish":
        inputs = dict(operation["inputs"])
        levels = inputs.pop("levels")
        expected = establish_history(baseline, levels, **inputs)
    elif operation.get("operation") == "advance":
        expected = advance_multiclass(baseline, operation["selected_class"], operation["choices"])
    else:
        raise ValueError("Unsupported multiclass operation.")
    if candidate != expected:
        raise ValueError("The reviewed draft changed; build another preview.")
    with repository._connection() as db:
        db.execute("BEGIN IMMEDIATE")
        row = db.execute("SELECT * FROM creatures WHERE id=?", (baseline.id,)).fetchone()
        if row is None or repository._from_row(row) != baseline:
            raise ValueError("The saved character changed. Reopen multiclass advancement before saving.")
        values = [getattr(candidate, column) for column in WRITE_COLUMNS]
        values[WRITE_COLUMNS.index("archived")] = int(candidate.archived)
        db.execute("UPDATE creatures SET " + ",".join(f"{column}=?" for column in WRITE_COLUMNS) +
                   ",updated_at=CURRENT_TIMESTAMP WHERE id=?", [*values, baseline.id])
        return repository._from_row(db.execute("SELECT * FROM creatures WHERE id=?", (baseline.id,)).fetchone())
