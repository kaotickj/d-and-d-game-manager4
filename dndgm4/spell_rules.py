"""D&D 3.5 SRD first-level spellbook and spell-selection foundation.

Core classes only. Higher spell levels, special domains, school
specialization and supplemental classes are explicitly not guessed.
All descriptions and spell references can be expanded from Open Game Content.
"""
from __future__ import annotations

from .dice import ability_modifier

# Curated SRD names, grouped by class and spell level; not 5e spell slots.
ARCANE_0 = ("Acid Splash","Arcane Mark","Dancing Lights","Daze",
    "Detect Magic","Detect Poison","Disrupt Undead","Flare","Ghost Sound",
    "Light","Mage Hand","Mending","Message","Open/Close","Prestidigitation",
    "Ray of Frost","Read Magic","Resistance","Touch of Fatigue")
ARCANE_1 = ("Burning Hands","Charm Person","Color Spray","Comprehend Languages",
    "Detect Secret Doors","Disguise Self","Endure Elements",
    "Enlarge Person","Expeditious Retreat","Feather Fall","Floating Disk",
    "Grease","Hold Portal","Identify","Jump","Mage Armor","Magic Missile",
    "Magic Weapon","Mount","Obscuring Mist","Protection from Evil",
    "Ray of Enfeeblement","Shield","Silent Image","Sleep",
    "Summon Monster I","True Strike","Unseen Servant","Ventriloquism")
CLERIC_0 = ("Create Water","Cure Minor Wounds","Detect Magic","Detect Poison",
    "Guidance","Inflict Minor Wounds","Light","Mending",
    "Purify Food and Drink","Read Magic","Resistance","Virtue")
CLERIC_1 = ("Bane","Bless","Bless Water","Cause Fear","Command",
    "Comprehend Languages","Cure Light Wounds","Curse Water","Deathwatch",
    "Detect Chaos","Detect Evil","Detect Good","Detect Law","Detect Undead",
    "Divine Favor","Doom","Endure Elements","Entropic Shield","Hide from Undead",
    "Inflict Light Wounds","Magic Stone","Magic Weapon",
    "Obscuring Mist","Protection from Evil","Remove Fear","Sanctuary",
    "Shield of Faith","Summon Monster I")
DRUID_0 = ("Create Water","Cure Minor Wounds","Detect Magic","Detect Poison",
    "Flare","Guidance","Know Direction","Light","Mending",
    "Purify Food and Drink","Read Magic","Resistance","Virtue")
DRUID_1 = ("Calm Animals","Charm Animal","Cure Light Wounds","Detect Animals or Plants",
    "Detect Snares and Pits","Endure Elements","Entangle","Faerie Fire",
    "Goodberry","Hide from Animals","Jump","Longstrider","Magic Fang",
    "Obscuring Mist","Pass without Trace","Produce Flame","Shillelagh",
    "Speak with Animals","Summon Nature's Ally I")
BARD_0 = ("Dancing Lights","Daze","Detect Magic","Flare","Ghost Sound",
    "Know Direction","Light","Lullaby","Mage Hand","Mending","Message",
    "Open/Close","Prestidigitation","Read Magic","Resistance","Summon Instrument")
BARD_1 = ("Alarm","Animate Rope","Cause Fear","Charm Person",
    "Comprehend Languages","Cure Light Wounds","Detect Secret Doors",
    "Disguise Self","Erase","Expeditious Retreat","Feather Fall",
    "Grease","Hideous Laughter","Hypnotism","Identify","Magic Mouth",
    "Obscure Object","Remove Fear","Silent Image","Sleep",
    "Summon Monster I","Undetectable Alignment","Unseen Servant")
ADEPT_0 = ("Create Water","Cure Minor Wounds","Detect Magic","Guidance",
    "Light","Mending","Purify Food and Drink","Read Magic","Resistance")
ADEPT_1 = ("Bless","Burning Hands","Cause Fear","Command",
    "Comprehend Languages","Cure Light Wounds","Detect Evil","Detect Good",
    "Endure Elements","Obscuring Mist","Protection from Evil","Sleep")

SPELL_LISTS = {
    "Wizard": {0: ARCANE_0, 1: ARCANE_1},
    "Sorcerer": {0: ARCANE_0, 1: ARCANE_1},
    "Cleric": {0: CLERIC_0, 1: CLERIC_1},
    "Druid": {0: DRUID_0, 1: DRUID_1},
    "Bard": {0: BARD_0, 1: BARD_1},
    "Adept": {0: ADEPT_0, 1: ADEPT_1},
}
CASTERS = {
    # ability, casting mode, base 0/1 slots, 0/1 spells known limit
    "Wizard": ("intelligence","prepared",(3,1),None),
    "Sorcerer": ("charisma","spontaneous",(5,3),(4,2)),
    "Cleric": ("wisdom","prepared",(3,1),None),
    "Druid": ("wisdom","prepared",(3,1),None),
    "Bard": ("charisma","spontaneous",(2,0),(4,0)),
    "Adept": ("wisdom","prepared",(3,1),None),
}
# Only classes with 1st-level spellcasting are included: ranger/paladin
# don't gain their normal spellcasting until later levels.

DEFAULTS = {
    "Wizard": {0: ("Detect Magic","Read Magic","Light"),
               1: ("Mage Armor","Magic Missile","Sleep")},
    "Sorcerer": {0: ("Detect Magic","Light","Mage Hand","Read Magic"),
                 1: ("Mage Armor","Magic Missile")},
    "Cleric": {0: ("Detect Magic","Guidance","Light"),
               1: ("Bless","Cure Light Wounds")},
    "Druid": {0: ("Create Water","Detect Magic","Guidance"),
              1: ("Entangle","Cure Light Wounds")},
    "Bard": {0: ("Dancing Lights","Detect Magic","Light","Prestidigitation"),
             1: ()},
    "Adept": {0: ("Detect Magic","Light","Mending"),
              1: ("Bless",)},
}


def bonus_slots(score: int, level: int) -> int:
    """3.5 Table: Ability Modifiers and Bonus Spells, only level >= 1."""
    if level <= 0:
        return 0
    modifier = ability_modifier(score)
    if modifier < level:
        return 0
    return 1 + (modifier - level) // 4


def spell_profile(class_name: str, scores: dict[str,int]) -> dict:
    if class_name not in CASTERS:
        return {"class":class_name,"mode":"none","slots":{"0":0,"1":0},
                "limits":{"0":0,"1":0}, "stat":None}
    stat,mode,slots,limits=CASTERS[class_name]
    ability=scores[stat]
    if ability < 11 and class_name != "Bard":
        raise ValueError(f"{class_name} needs {stat.title()} 11+ to cast 1st-level spells.")
    day1=slots[1]+(bonus_slots(ability,1) if slots[1] > 0 else 0)
    if class_name=="Bard":
        # Bard 1 receives 0 base 1st-level slots and knows no 1st spells.
        day1=0
    return {
        "class":class_name,"mode":mode,"stat":stat,
        "spell_dc_0":10+ability_modifier(ability),
        "spell_dc_1":11+ability_modifier(ability),
        "slots":{"0":slots[0],"1":day1},
        "limits":{"0":limits[0] if limits else 0,
                  "1":limits[1] if limits else 0},
        "domain_slot_1":1 if class_name=="Cleric" else 0,
        "catalog":{"0":list(SPELL_LISTS[class_name][0]),
                   "1":list(SPELL_LISTS[class_name][1])},
    }


def default_spellbook(class_name: str, scores: dict[str,int]) -> dict:
    profile=spell_profile(class_name,scores)
    data={"version":1,"casting_class":class_name,
          "known":{"0":[],"1":[]},"prepared":{"0":[],"1":[]},
          "spellbook":{"0":[],"1":[]},"domains":[],
          "specialization":"","prohibited_schools":[]}
    if class_name not in CASTERS:
        return data
    catalog=SPELL_LISTS[class_name]
    starter=DEFAULTS[class_name]
    if class_name=="Wizard":
        data["spellbook"]["0"]=list(catalog[0])
        max_first=min(len(catalog[1]),3+max(0,ability_modifier(scores["intelligence"])))
        ordered=list(dict.fromkeys(starter[1]+catalog[1]))
        data["spellbook"]["1"]=ordered[:max_first]
        data["prepared"]["0"]=list(starter[0])[:3]
        data["prepared"]["1"]=list(starter[1])[:profile["slots"]["1"]]
    elif profile["mode"]=="spontaneous":
        data["known"]["0"]=list(starter[0])[:profile["limits"]["0"]]
        data["known"]["1"]=list(starter[1])[:profile["limits"]["1"]]
    else:
        data["prepared"]["0"]=list(starter[0])[:profile["slots"]["0"]]
        data["prepared"]["1"]=list(starter[1])[:profile["slots"]["1"]]
    return data


def validate_spellbook(class_name: str, scores: dict[str,int],
                       data: dict, *, strict: bool = True) -> dict:
    """Validate first-level SRD class slots/known lists with real spell IDs.

    Prepared lists may be shorter than capacity; no arbitrary model-invented
    spells are silently accepted. Domain spells/specializations need separate
    verification in later milestones, so are preserved but flagged.
    """
    profile=spell_profile(class_name,scores)
    if not isinstance(data,dict):
        raise ValueError("Spellbook must be structured data.")
    result={"version":1, "casting_class":class_name}
    for key in ("known","prepared","spellbook"):
        source=data.get(key,{})
        if not isinstance(source,dict):
            raise ValueError(f"{key} must map spell levels to lists.")
        groups={}
        for level in ("0","1"):
            spell_names=source.get(level,[])
            if not isinstance(spell_names,list) or len(spell_names)>100:
                raise ValueError(f"{key} level {level} must be a spell list.")
            if any(not isinstance(n,str) or len(n)>100 for n in spell_names):
                raise ValueError("Spell names must be short strings.")
            if len(spell_names)!=len(set(spell_names)) and key!="prepared":
                raise ValueError(f"Duplicate spells in {key} level {level}.")
            if class_name not in SPELL_LISTS and spell_names:
                raise ValueError("This class has no validated first-level spellcasting.")
            allowed=SPELL_LISTS.get(class_name,{}).get(int(level),())
            unknown=[name for name in spell_names if name not in allowed]
            if unknown:
                raise ValueError(f"{class_name} cannot use level-{level} spell(s): {', '.join(unknown)}")
            groups[level]=list(spell_names)
        result[key]=groups
    if class_name in CASTERS:
        for level in ("0","1"):
            if len(result["prepared"][level]) > profile["slots"][level]:
                raise ValueError(f"Too many level-{level} prepared spells.")
            limit=profile["limits"][level]
            if limit and len(result["known"][level])>limit:
                raise ValueError(f"Too many level-{level} spells known.")
        if profile["mode"]=="spontaneous" and any(result["prepared"].values()):
            raise ValueError("Spontaneous casters do not prepare daily spell lists.")
        if class_name=="Wizard":
            cap=3+max(0,ability_modifier(scores["intelligence"]))
            if len(result["spellbook"]["1"])>cap:
                raise ValueError(f"First-level wizard spellbook has room for {cap} level-1 spells.")
            for level in ("0","1"):
                missing=set(result["prepared"][level])-set(result["spellbook"][level])
                if missing and missing != {"Read Magic"}:
                    raise ValueError("A wizard cannot prepare spells missing from their spellbook.")
        elif any(result["spellbook"].values()):
            raise ValueError("Only Wizards use the spellbook field at 1st level.")
        if profile["mode"]=="prepared" and any(result["known"].values()):
            raise ValueError("Prepared casters use prepared spells, not spells known.")
    domains=data.get("domains",[])
    if not isinstance(domains,list) or len(domains)>2 or any(
            not isinstance(x,str) or len(x)>100 for x in domains):
        raise ValueError("Select at most two divine domains.")
    if class_name!="Cleric" and domains:
        raise ValueError("Only Clerics use domain selection.")
    result["domains"]=domains
    result["specialization"]=str(data.get("specialization",""))[:90]
    result["prohibited_schools"]=list(data.get("prohibited_schools",[]))[:4]
    if class_name!="Wizard" and (result["specialization"] or result["prohibited_schools"]):
        raise ValueError("School specialization belongs to Wizards.")
    result["review_required"]=bool(domains or result["specialization"] or result["prohibited_schools"])
    return result
