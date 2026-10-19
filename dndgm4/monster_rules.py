"""D&D 3.5 SRD monster-type baseline rules, independent of the GUI.

Provides the mathematical foundations for constructing *original* creatures.
No copyright-restricted monster stat blocks, species abilities, template chains
or Challenge Rating estimates are invented or shipped with this rules module.

Sources: 3.5 SRD Types & Subtypes, Improving Monsters, Monsters as Races.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from fractions import Fraction
from math import floor
from random import randint
import json

from .creation import ABILITIES
from .dice import ability_modifier
from .models import Creature
from .identity_rules import identity_text

SIZES = ("Fine","Diminutive","Tiny","Small","Medium",
         "Large","Huge","Gargantuan","Colossal")
SIZE_AC = dict(zip(SIZES,(8,4,2,1,0,-1,-2,-4,-8)))
SIZE_GRAPPLE = dict(zip(SIZES,(-16,-12,-8,-4,0,4,8,12,16)))
CONSTRUCT_BONUS_HP = dict(zip(SIZES,(0,0,0,10,20,30,40,60,80)))

@dataclass(frozen=True)
class TypeRules:
    die: int
    attack: str
    good: tuple[str,...]
    skill_points: int
    no_con: bool = False

# For Humanoid, pick one good save by subtype/species; for Elemental,
# choose the elemental subtype (air/fire=Ref, earth/water=Fort).
TYPES: dict[str,TypeRules] = {
    "Aberration": TypeRules(8,"medium",("Will",),2),
    "Animal": TypeRules(8,"medium",("Fort","Ref"),2),
    "Construct": TypeRules(10,"medium",(),2,True),
    "Dragon": TypeRules(12,"full",("Fort","Ref","Will"),6),
    "Elemental": TypeRules(8,"medium",(),2),
    "Fey": TypeRules(6,"poor",("Ref","Will"),6),
    "Giant": TypeRules(8,"medium",("Fort",),2),
    "Humanoid": TypeRules(8,"medium",(),2),
    "Magical Beast": TypeRules(10,"full",("Fort","Ref"),2),
    "Monstrous Humanoid": TypeRules(8,"full",("Ref","Will"),2),
    "Ooze": TypeRules(10,"medium",(),2),
    "Outsider": TypeRules(8,"full",("Fort","Ref","Will"),8),
    "Plant": TypeRules(8,"medium",("Fort",),2),
    "Undead": TypeRules(12,"poor",("Will",),4,True),
    "Vermin": TypeRules(8,"medium",("Fort",),2),
}

def base_attack(hit_dice: int, rate: str) -> int:
    if not 1 <= hit_dice <= 99: raise ValueError("Racial Hit Dice must be 1-99.")
    return {"full":hit_dice, "medium":3*hit_dice//4,
            "poor":hit_dice//2}[rate]

def base_save(hit_dice:int, good:bool) -> int:
    return 2+hit_dice//2 if good else hit_dice//3

def valid_cr(value: str) -> str:
    value = value.strip()
    if not value:
        return ""
    try:
        cr = Fraction(value)
    except (ValueError, ZeroDivisionError) as exc:
        raise ValueError("CR must be a number or fraction, e.g. 1/2 or 5.") from exc
    if not 0 <= cr <= 99:
        raise ValueError("Challenge Rating must be between 0 and 99.")
    return str(cr)

@dataclass
class MonsterBlueprint:
    name: str
    species: str
    creature_type: str
    hit_dice: int
    abilities: dict[str,int|None]
    size: str = "Medium"
    subtype: str = ""
    good_save: str = "Fort"  # Humanoids only; elemental subtype overrides
    natural_armor: int = 0
    armor_bonus: int = 0
    shield_bonus: int = 0
    speed: str = "30 ft."
    attacks: str = ""
    special_attacks: str = ""
    special_qualities: str = ""
    feats: list[str] = field(default_factory=list)
    skills: str = ""
    cr: str = ""
    alignment: str = ""
    environment: str = ""
    organization: str = ""
    treasure: str = ""
    advancement: str = ""
    level_adjustment: str = ""
    notes: str = ""
    biography: str = ""
    gender: str = ""
    age: str = ""
    hp_method: str = "average"
    manual_hit_points: int = 1

def _good_saves(b:MonsterBlueprint)->tuple[str,...]:
    spec=TYPES[b.creature_type]
    if b.creature_type=="Elemental":
        subtype=b.subtype.casefold()
        if "air" in subtype or "fire" in subtype:
            return ("Ref",)
        if "earth" in subtype or "water" in subtype:
            return ("Fort",)
        raise ValueError("Choose an elemental subtype: Air, Fire, Earth, or Water.")
    if b.creature_type=="Humanoid":
        if b.good_save not in ("Fort","Ref","Will"):
            raise ValueError("Choose the Humanoid's good saving throw.")
        return (b.good_save,)
    return spec.good

def _modifier(value:int|None)->int:
    return ability_modifier(value) if value is not None else 0

def compute_monster(b:MonsterBlueprint, *, roller=None)->dict:
    identity_text(b.gender, "Gender")
    identity_text(b.age, "Age")
    if not b.name.strip() or len(b.name.strip())>200:
        raise ValueError("A monster name (max 200 characters) is required.")
    if not b.species.strip():
        raise ValueError("Enter the species or monster name.")
    if b.creature_type not in TYPES:
        raise ValueError("Choose one of the 15 D&D 3.5 creature types.")
    if b.size not in SIZES:
        raise ValueError("Choose a supported D&D 3.5 size.")
    if not 1<=b.hit_dice<=99:
        raise ValueError("Racial Hit Dice must be 1-99.")
    if set(b.abilities) != set(ABILITIES):
        raise ValueError("Exactly six abilities are required.")
    for name,value in b.abilities.items():
        if value is not None and (not isinstance(value,int) or not 0<=value<=99):
            raise ValueError(f"{name} must be 0-99 or have no score.")
    spec=TYPES[b.creature_type]
    # No Con is a structural part of Construct/Undead, not a score of 0.
    if spec.no_con and b.abilities["constitution"] is not None:
        raise ValueError(f"{b.creature_type} must have no Constitution score.")
    if not spec.no_con and b.abilities["constitution"] is None:
        raise ValueError("Only Construct and Undead types omit Constitution.")
    if b.abilities["intelligence"] is None and b.creature_type not in (
        "Construct","Ooze","Plant","Undead","Vermin"):
        raise ValueError("Mindless (no INT) needs a compatible creature type.")
    if b.creature_type=="Animal" and b.abilities["intelligence"] not in (1,2):
        raise ValueError("Animal Intelligence must be 1 or 2.")
    if not -20<=b.natural_armor<=99 or not 0<=b.armor_bonus<=99 or not 0<=b.shield_bonus<=99:
        raise ValueError("Armor bonuses outside accepted ranges.")
    if b.hp_method not in ("average","rolled","manual"):
        raise ValueError("HP method must be average, rolled or manual.")
    if b.hp_method == "manual" and not 1 <= b.manual_hit_points <= 999999:
        raise ValueError("Manual hit points must be 1-999999.")
    good=_good_saves(b)
    cmod=_modifier(b.abilities["constitution"])
    dex=_modifier(b.abilities["dexterity"])
    strmod=_modifier(b.abilities["strength"])
    wis=_modifier(b.abilities["wisdom"])
    attack=base_attack(b.hit_dice,spec.attack)
    if b.hp_method=="rolled":
        rand=roller or randint
        hd_hp=sum(rand(1,spec.die) for _ in range(b.hit_dice))
    else:
        hd_hp=b.hit_dice*(spec.die+1)//2
    bonus=CONSTRUCT_BONUS_HP[b.size] if b.creature_type=="Construct" else 0
    hit_points=(b.manual_hit_points if b.hp_method=="manual" else
                max(1,hd_hp + b.hit_dice*cmod + bonus))
    fort=base_save(b.hit_dice,"Fort" in good)+cmod
    reflex=base_save(b.hit_dice,"Ref" in good)+dex
    will=base_save(b.hit_dice,"Will" in good)+wis
    intelligent=b.abilities["intelligence"] is not None
    # First racial HD uses x4 skill points; no score => no skills/feats.
    pts=max(1,spec.skill_points+_modifier(b.abilities["intelligence"]))
    skill_points=(pts*(b.hit_dice+3)) if intelligent else 0
    feats=(1+b.hit_dice//3) if intelligent else 0
    ac=10+dex+SIZE_AC[b.size]+b.natural_armor+b.armor_bonus+b.shield_bonus
    return dict(type=b.creature_type,subtype=b.subtype.strip(),size=b.size,
        hd=b.hit_dice,die=spec.die,hit_dice_notation=f"{b.hit_dice}d{spec.die}",
        hp_method=b.hp_method,hp=hit_points,bab=attack,
        fort=fort,ref=reflex,will=will,good_saves=good,
        initiative=dex,armor_class=max(0,ac),
        size_ac=SIZE_AC[b.size],grapple=attack+strmod+SIZE_GRAPPLE[b.size],
        melee=attack+strmod+SIZE_AC[b.size],
        ranged=attack+dex+SIZE_AC[b.size],
        skill_points=skill_points,feats_available=feats,
        construct_bonus_hp=bonus,
        warnings=[
          "CR is a DM-reviewed value, never inferred from racial HD alone."
          if not b.cr.strip() else
          "CR supplied by DM; verify species traits, special abilities and equipment.",
          "Monster class levels, templates and racial traits require separate review.",
        ])

def build_monster(b:MonsterBlueprint, *, roller=None)->Creature:
    stats=compute_monster(b,roller=roller)
    cr=valid_cr(b.cr)
    # Existing integer-based Creature schema keeps 0 as the persisted stand-in
    # for absent scores; original None semantics persist in monster JSON.
    values={name: (value if value is not None else 0)
            for name,value in b.abilities.items()}
    info=dict(version=1,monster_type=b.creature_type,subtype=b.subtype,
              species=b.species.strip(),size=b.size,hit_dice=b.hit_dice,
              hp_method=b.hp_method,manual_hit_points=b.manual_hit_points,
              computed=stats,
              null_abilities=[key for key,val in b.abilities.items() if val is None],
              natural_armor=b.natural_armor,armor_bonus=b.armor_bonus,
              shield_bonus=b.shield_bonus,speed=b.speed,
              attacks=b.attacks,special_attacks=b.special_attacks,
              special_qualities=b.special_qualities,
              feats=b.feats,skills=b.skills,
              alignment=b.alignment,environment=b.environment,
              organization=b.organization,treasure=b.treasure,
              advancement=b.advancement,level_adjustment=b.level_adjustment,
              manual_cr=cr,notes=b.notes,biography=b.biography.strip(),
              gender=identity_text(b.gender, "Gender"),
              age=identity_text(b.age, "Age"),
              rules_review="CR, natural attacks, species traits, class levels and templates are DM-reviewed.")
    return Creature(name=b.name.strip(),kind="monster",race_type=b.species.strip(),
                    character_class=b.creature_type,level=0,challenge_rating=cr,
                    armor_class=stats["armor_class"],max_hit_points=stats["hp"],
                    notes=b.notes.strip(),sheet_json=json.dumps(info,sort_keys=True),
                    **values)
