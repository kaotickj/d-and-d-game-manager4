"""Structured D&D 3.5 first-level character sheets and editable build presets.

Core base-class HD and skill budgets follow the 3.5 rules framework. Extra
classes are optional editable starting templates, NOT complete supplementary
class mechanics, spell lists, class features, or prerequisite validation.
"""
from __future__ import annotations

from dataclasses import dataclass
import json
from .creation import (ABILITIES, CORE_CLASSES, RACIAL_ADJUSTMENTS, SMALL_RACES,
                       adjusted_scores, first_level_skill_points)
from .dice import ability_modifier
from .models import Creature

# Every skill is available for custom allocation; use the class list for
# suggestions and point-cost accounting only. Crafts and Professions are
# individual specializations entered as separate freeform lines when needed.
SKILLS = (
    "Appraise", "Balance", "Bluff", "Climb", "Concentration", "Craft",
    "Decipher Script", "Diplomacy", "Disable Device", "Disguise",
    "Escape Artist", "Forgery", "Gather Information", "Handle Animal",
    "Heal", "Hide", "Intimidate", "Jump", "Knowledge (arcana)",
    "Knowledge (architecture)", "Knowledge (dungeoneering)",
    "Knowledge (geography)", "Knowledge (history)",
    "Knowledge (local)", "Knowledge (nature)", "Knowledge (nobility)",
    "Knowledge (religion)", "Knowledge (the planes)", "Listen",
    "Move Silently", "Open Lock", "Perform", "Profession", "Ride",
    "Search", "Sense Motive", "Sleight of Hand", "Speak Language",
    "Spellcraft", "Spot", "Survival", "Swim", "Tumble",
    "Use Magic Device", "Use Rope",
)
K_ALL = tuple(s for s in SKILLS if s.startswith("Knowledge ("))

@dataclass(frozen=True)
class ClassTemplate:
    hit_die: int
    skill_points: int
    class_skills: tuple[str, ...]
    suggested_skills: tuple[str, ...]
    suggested_feats: tuple[str, ...]
    suggested_equipment: tuple[str, ...]
    spellcasting_note: str = ""
    supplement: bool = False

    @property
    def class_skill_set(self) -> frozenset[str]:
        return frozenset(self.class_skills)

def spec(hd, sp, skills, favored, feats, kit, casting="", extra=False):
    return ClassTemplate(hd, sp, tuple(dict.fromkeys(skills.split("|"))),
                         tuple(favored.split("|")), tuple(feats.split("|")),
                         tuple(kit.split("|")), casting, extra)

_KN = list(K_ALL)
# Defaults deliberately use broadly accessible feats and put all selections
# through a manual review. Feats are never silently auto-validated.
TEMPLATES = {
    "Barbarian": spec(12,4,"Climb|Craft|Handle Animal|Intimidate|Jump|Listen|Ride|Survival|Swim",
        "Survival|Listen|Jump|Climb","Power Attack","Greataxe|Hide armor|Backpack"),
    "Bard": spec(6,6,"Appraise|Balance|Bluff|Climb|Concentration|Craft|Decipher Script|Diplomacy|Disguise|Escape Artist|Gather Information|Hide|Jump|Knowledge (arcana)|Knowledge (history)|Knowledge (local)|Knowledge (nobility)|Listen|Move Silently|Perform|Profession|Sense Motive|Sleight of Hand|Speak Language|Spellcraft|Swim|Tumble|Use Magic Device",
        "Perform|Diplomacy|Bluff|Use Magic Device|Listen","Improved Initiative","Short sword|Leather armor|Lute","Arcane spontaneous caster; choose spells manually."),
    "Cleric": spec(8,2,"Concentration|Craft|Diplomacy|Heal|Knowledge (arcana)|Knowledge (history)|Knowledge (religion)|Knowledge (the planes)|Profession|Spellcraft",
        "Concentration|Knowledge (religion)|Heal","Improved Initiative","Mace|Scale mail|Wooden shield|Holy symbol","Divine prepared caster; choose deity, domains and spells."),
    "Druid": spec(8,4,"Concentration|Craft|Diplomacy|Handle Animal|Heal|Knowledge (nature)|Listen|Profession|Ride|Spellcraft|Spot|Survival|Swim",
        "Knowledge (nature)|Handle Animal|Survival|Concentration","Improved Initiative","Quarterstaff|Leather armor|Mistletoe","Divine prepared caster; companion and spells need review."),
    "Fighter": spec(10,2,"Climb|Craft|Handle Animal|Intimidate|Jump|Ride|Swim",
        "Ride|Climb|Intimidate","Power Attack|Cleave","Longsword|Chainmail|Heavy shield"),
    "Monk": spec(8,4,"Balance|Climb|Concentration|Craft|Diplomacy|Escape Artist|Hide|Jump|Knowledge (arcana)|Knowledge (religion)|Listen|Move Silently|Perform|Profession|Sense Motive|Spot|Swim|Tumble",
        "Tumble|Jump|Balance|Listen","Improved Initiative","Quarterstaff|Sling|Monk outfit"),
    "Paladin": spec(10,2,"Concentration|Craft|Diplomacy|Handle Animal|Heal|Knowledge (nobility)|Knowledge (religion)|Profession|Ride|Sense Motive",
        "Ride|Diplomacy|Heal","Power Attack","Longsword|Chainmail|Shield|Holy symbol"),
    "Ranger": spec(8,6,"Climb|Concentration|Craft|Handle Animal|Heal|Hide|Jump|Knowledge (dungeoneering)|Knowledge (geography)|Knowledge (nature)|Listen|Move Silently|Profession|Ride|Search|Spot|Survival|Swim|Use Rope",
        "Survival|Hide|Move Silently|Spot|Listen","Point Blank Shot","Longbow|Short sword|Studded leather|Arrows"),
    "Rogue": spec(6,8,"Appraise|Balance|Bluff|Climb|Craft|Decipher Script|Diplomacy|Disable Device|Disguise|Escape Artist|Forgery|Gather Information|Hide|Intimidate|Jump|Knowledge (local)|Listen|Move Silently|Open Lock|Perform|Profession|Search|Sense Motive|Sleight of Hand|Spot|Swim|Tumble|Use Magic Device|Use Rope",
        "Disable Device|Open Lock|Search|Hide|Move Silently|Tumble|Spot|Listen",
        "Improved Initiative","Rapier|Leather armor|Thieves' tools"),
    "Sorcerer": spec(4,2,"Bluff|Concentration|Craft|Knowledge (arcana)|Profession|Spellcraft",
        "Concentration|Spellcraft|Knowledge (arcana)","Improved Initiative",
        "Quarterstaff|Light crossbow|Spell component pouch","Arcane spontaneous caster; choose spells manually."),
    "Wizard": spec(4,2,"Concentration|Craft|Decipher Script|Knowledge (arcana)|Knowledge (history)|Knowledge (religion)|Knowledge (the planes)|Profession|Spellcraft",
        "Spellcraft|Concentration|Knowledge (arcana)","Improved Initiative",
        "Quarterstaff|Spellbook|Spell component pouch","Arcane prepared caster; spellbook, school and spells need review."),
}
# Expanded classes are *editable templates*. They do not grant unverified
# special features, bonus feats or spellcasting by default.
_EXTRA_CLASS_DATA = {
    "Artificer": (6,4,"Craft|Disable Device|Knowledge (arcana)|Search|Use Magic Device","Craft|Use Magic Device|Search"),
    "Beguiler": (6,6,"Bluff|Concentration|Disable Device|Disguise|Hide|Move Silently|Spellcraft|Use Magic Device","Bluff|Hide|Spellcraft"),
    "Dragon Shaman": (10,2,"Climb|Craft|Diplomacy|Intimidate|Knowledge (arcana)|Listen|Search|Spot","Diplomacy|Intimidate"),
    "Duskblade": (8,2,"Climb|Concentration|Craft|Knowledge (arcana)|Ride|Spellcraft|Swim","Concentration|Spellcraft"),
    "Favored Soul": (8,2,"Concentration|Craft|Diplomacy|Heal|Knowledge (religion)|Profession|Spellcraft","Concentration|Heal"),
    "Hexblade": (10,2,"Bluff|Concentration|Craft|Intimidate|Knowledge (arcana)|Ride|Spellcraft","Intimidate|Concentration"),
    "Knight": (12,2,"Climb|Diplomacy|Handle Animal|Intimidate|Knowledge (nobility)|Ride|Swim","Ride|Diplomacy"),
    "Ninja": (6,6,"Balance|Bluff|Climb|Disguise|Escape Artist|Hide|Jump|Listen|Move Silently|Search|Spot|Tumble","Hide|Move Silently|Tumble"),
    "Psion": (4,2,"Concentration|Craft|Knowledge (psionics)|Profession|Psicraft","Concentration|Knowledge (psionics)"),
    "Psychic Warrior": (8,2,"Autohypnosis|Climb|Concentration|Jump|Ride|Swim","Concentration|Climb"),
    "Samurai": (10,2,"Climb|Craft|Diplomacy|Intimidate|Ride|Swim","Intimidate|Ride"),
    "Scout": (8,8,"Balance|Climb|Craft|Disable Device|Escape Artist|Hide|Jump|Knowledge (nature)|Listen|Move Silently|Search|Spot|Survival|Tumble","Hide|Move Silently|Spot|Survival"),
    "Soulknife": (10,4,"Autohypnosis|Climb|Concentration|Hide|Jump|Move Silently|Spot|Tumble","Tumble|Spot"),
    "Spellthief": (6,6,"Bluff|Concentration|Disable Device|Hide|Knowledge (arcana)|Move Silently|Open Lock|Search|Spellcraft|Tumble","Hide|Move Silently|Disable Device"),
    "Spirit Shaman": (8,4,"Concentration|Craft|Diplomacy|Handle Animal|Heal|Knowledge (nature)|Listen|Spellcraft|Survival","Concentration|Knowledge (nature)"),
    "Swashbuckler": (10,4,"Balance|Bluff|Climb|Diplomacy|Escape Artist|Jump|Profession|Sense Motive|Swim|Tumble","Tumble|Balance|Bluff"),
    "Warlock": (6,2,"Bluff|Concentration|Craft|Disguise|Intimidate|Knowledge (arcana)|Knowledge (the planes)|Profession|Sense Motive|Spellcraft|Use Magic Device","Concentration|Use Magic Device"),
    "Warmage": (6,2,"Concentration|Craft|Intimidate|Knowledge (arcana)|Knowledge (the planes)|Profession|Spellcraft","Concentration|Spellcraft"),
    "Wilder": (6,4,"Autohypnosis|Bluff|Concentration|Craft|Intimidate|Knowledge (psionics)|Profession|Psicraft","Concentration|Autohypnosis"),
}
for _name, (_hd, _sp, _skills, _favored) in _EXTRA_CLASS_DATA.items():
    TEMPLATES[_name] = spec(_hd, _sp, _skills, _favored, "Improved Initiative",
        "Traveler's outfit|Backpack|Basic adventuring kit",
        "Supplemental class: manually review special abilities and spell/power progression.",
        extra=True)
SKILLS = tuple(dict.fromkeys(SKILLS + ("Autohypnosis", "Knowledge (psionics)", "Psicraft")))

# NPC base classes from the 3.5 SRD. Expert chooses 10 class skills,
# entered by the DM through the additional-class-skills field.
NPC_CLASS_TEMPLATES = {
    "Adept": spec(6,2,
      "Concentration|Craft|Handle Animal|Heal|Profession|Spellcraft|Survival|"+"|".join(K_ALL),
      "Concentration|Heal|Spellcraft", "Alertness", "Quarterstaff|Common clothes",
      "Divine adept; spell selection remains manual."),
    "Aristocrat": spec(8,4,
      "Appraise|Bluff|Diplomacy|Disguise|Forgery|Gather Information|Handle Animal|Intimidate|Listen|Perform|Ride|Sense Motive|Speak Language|Spot|Swim|Survival|"+"|".join(K_ALL),
      "Diplomacy|Sense Motive|Bluff|Ride", "Skill Focus", "Fine clothing|Rapier"),
    "Commoner": spec(4,2,
      "Climb|Craft|Handle Animal|Jump|Listen|Profession|Ride|Spot|Swim|Use Rope",
      "Profession|Craft|Listen", "Skill Focus", "Work clothing|Simple tool"),
    "Expert": spec(6,6,
      "Craft|Profession|Appraise|Diplomacy|Knowledge (local)|Search|Spot|Listen|Use Rope|Heal",
      "Craft|Profession|Appraise|Search", "Skill Focus", "Professional tools",
      "Choose exactly 10 class skills; edit the class-skill selections manually."),
    "Warrior": spec(8,2,
      "Climb|Craft|Handle Animal|Intimidate|Jump|Ride|Swim",
      "Climb|Intimidate|Ride", "Power Attack", "Longsword|Chainmail|Shield"),
}
TEMPLATES.update(NPC_CLASS_TEMPLATES)


DEFAULT_FEATS = ("Alertness","Blind-Fight","Combat Casting","Combat Expertise",
                 "Dodge","Endurance","Improved Initiative","Iron Will",
                 "Lightning Reflexes","Point Blank Shot","Power Attack",
                 "Skill Focus","Toughness","Weapon Finesse","Weapon Focus",
                 "Great Fortitude","Track","Cleave")
ALIGNMENTS = ("Lawful Good","Neutral Good","Chaotic Good","Lawful Neutral",
              "True Neutral","Chaotic Neutral","Lawful Evil","Neutral Evil","Chaotic Evil")

def class_specs(name: str, manual_hd: int = 8, manual_sp: int = 4) -> ClassTemplate:
    if name in TEMPLATES:
        return TEMPLATES[name]
    if not 4 <= manual_hd <= 20 or not 1 <= manual_sp <= 20:
        raise ValueError("Custom class hit die/skill point values out of range.")
    return ClassTemplate(manual_hd, manual_sp, (), (), (), (),
                         "Homebrew class: rules and progression are GM-defined.", True)

def skill_budget(class_name: str, intelligence: int, race: str,
                 custom_hd: int = 8, custom_sp: int = 4) -> int:
    template = class_specs(class_name, custom_hd, custom_sp)
    base = max(1, template.skill_points + ability_modifier(intelligence))
    return base * 4 + (4 if race == "Human" else 0)

def allocate_default_skills(template: ClassTemplate, budget: int) -> dict[str,int]:
    """Give class skills up to four first-level ranks, budget permitting."""
    ranks = {name:0 for name in SKILLS}
    suggested = [name for name in dict.fromkeys(template.suggested_skills)
                 if name in ranks and name in template.class_skill_set]
    remaining = [name for name in template.class_skills
                 if name in ranks and name not in suggested]
    left = budget
    # Always prioritize class-specific suggested training first.
    for group in (suggested, remaining):
        while left and any(ranks[name] < 8 for name in group):
            for name in group:
                if left == 0: break
                if ranks[name] < 8:
                    ranks[name] += 2
                    left -= 1
    return {k:v for k,v in ranks.items() if v}

def validate_allocations(ranks: dict[str,int], template: ClassTemplate,
                         budget: int, manual_skills: frozenset[str] = frozenset()
                         ) -> int:
    spent = 0
    for name, rank in ranks.items():
        if not isinstance(name,str) or not isinstance(rank,int) or rank < 0:
            raise ValueError("Skill ranks must be nonnegative whole numbers.")
        in_class = name in template.class_skill_set or name in manual_skills
        # Half-rank cross-class spends a point: saved as half-unit ticks.
        max_ticks = 8 if in_class else 4
        if rank > max_ticks:
            raise ValueError(f"{name}: exceeds first-level skill rank limit.")
        # Ranks are stored as half-rank ticks. Class skill 1 rank costs 1,
        # cross-class half-rank costs 1.
        if in_class and rank % 2:
            raise ValueError(f"{name}: class skill ranks must be whole.")
        spent += rank // 2 if in_class else rank
    if spent > budget:
        raise ValueError(f"Skill allocation spends {spent}, budget is {budget}.")
    return spent

def build_sheet(*, character: Creature, class_name: str, ranks: dict[str,int],
                feats: list[str], equipment: list[str], alignment: str,
                deity: str, languages: list[str], appearance: str,
                personality: str, background: str, custom_hd: int = 8,
                custom_sp: int = 4, custom_class_skills: list[str] | None = None,
                class_features: list[str] | None = None,
                spell_notes: str = "", extra_notes: str = "",
                spellbook: dict | None = None, inventory: list[dict] | None = None,
                strict_feats: bool = False) -> Creature:
    """Attach validated structured selections without discarding base rolls."""
    from dataclasses import replace
    if alignment not in ALIGNMENTS:
        raise ValueError("Choose a valid alignment.")
    t = class_specs(class_name, custom_hd, custom_sp)
    if class_name == "Expert":
        selected = list(dict.fromkeys(custom_class_skills or []))
        if len(selected) != 10 or any(name not in SKILLS for name in selected):
            raise ValueError("Expert must choose exactly 10 distinct supported class skills.")
        from dataclasses import replace as _replace
        t = _replace(t,class_skills=tuple(selected))
    budget = skill_budget(class_name, character.intelligence, character.race_type,
                          custom_hd, custom_sp)
    spent = validate_allocations(ranks,t,budget,frozenset(custom_class_skills or []))
    if len(feats) > 30 or len(equipment) > 150:
        raise ValueError("Too many feats or equipment lines.")
    if any(len(x)>180 for x in feats+equipment+languages):
        raise ValueError("One or more entries are too long.")
    from .build_rules import feat_review, inventory_from_text
    from .spell_rules import validate_spellbook
    score_values = {ability:getattr(character,ability) for ability in ABILITIES}
    # This is opt-in strict for the guided and AI paths. Existing character
    # sheets and supplemental classes remain editable, with warnings.
    feat_warnings = feat_review(
        feats,score_values,class_name=class_name,race=character.race_type,
        bab=1 if class_name in ("Fighter","Barbarian","Ranger","Paladin") else 0,
        strict=strict_feats and class_name in CORE_CLASSES)
    validated_spells = (
        validate_spellbook(class_name, score_values, spellbook)
        if spellbook is not None else None
    )
    structured_inventory = (inventory if inventory is not None else
                            inventory_from_text("\n".join(equipment)))
    if not isinstance(structured_inventory,list) or len(structured_inventory)>150:
        raise ValueError("Invalid inventory entries.")
    data = {
        "version": 1, "class": class_name,
        "supplemental_template": t.supplement,
        "custom_hd": custom_hd, "custom_skill_points": custom_sp,
        "custom_class_skills": custom_class_skills or [],
        "skills_half_ranks": {key:value for key,value in ranks.items() if value},
        "skill_budget": budget, "skill_spent": spent,
        "feats": [x.strip() for x in feats if x.strip()],
        "equipment": [x.strip() for x in equipment if x.strip()],
        "alignment": alignment, "deity": deity.strip(),
        "languages": [x.strip() for x in languages if x.strip()],
        "appearance": appearance.strip(), "personality": personality.strip(),
        "background": background.strip(), "class_features": class_features or [],
        "spell_notes": spell_notes.strip(), "extra_notes": extra_notes.strip(),
        "spellbook":validated_spells, "inventory":structured_inventory,
        "feat_review_warnings":feat_warnings,
        "validation": "Skill budget checked; feat and equipment eligibility require GM review.",
    }
    return replace(character, character_class=class_name,
                   max_hit_points=max(1,t.hit_die+ability_modifier(character.constitution)),
                   sheet_json=json.dumps(data,ensure_ascii=False,sort_keys=True))

def load_sheet(creature:Creature) -> dict:
    return json.loads(creature.sheet_json) if creature.sheet_json else {}
