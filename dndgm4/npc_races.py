"""D&D 3.5 NPC ancestry registry and supported racial modifiers.

Only source-verified, class-level humanoids have automatic mechanical traits.
Every other listed NPC ancestry remains selectable for DM-defined modifiers.
High-racial-HD creatures should be built in the Monster Forge first.
"""
from __future__ import annotations
from dataclasses import dataclass
from .creation import RACIAL_ADJUSTMENTS
from .namegen import EXPANDED_RACES, MONSTER_RACES

@dataclass(frozen=True)
class Ancestry:
    ability_adjustments: dict[str,int]
    size: str = "Medium"
    level_adjustment: int = 0
    racial_hit_dice: int = 0
    traits: tuple[str,...] = ()

# These are ancestry modifiers, not complete species stat blocks.
# References: D&D 3.5 SRD monster character sections for each entry.
NPC_RACES: dict[str,Ancestry] = {
    **{name: Ancestry(dict(mods), size="Small" if name in ("Gnome","Halfling") else "Medium")
       for name,mods in RACIAL_ADJUSTMENTS.items()},
    "Goblin": Ancestry({"strength":-2,"dexterity":2,"charisma":-2},
                      "Small",0,0,("Darkvision 60 ft.","+4 Hide size bonus","+4 Move Silently","+4 Ride")),
    "Kobold": Ancestry({"strength":-4,"dexterity":2,"constitution":-2},
                      "Small",0,0,("Darkvision 60 ft.","+1 natural armor","Light sensitivity")),
    "Orc": Ancestry({"strength":4,"intelligence":-2,"wisdom":-2,"charisma":-2},
                   "Medium",0,0,("Darkvision 60 ft.","Light sensitivity")),
    "Hobgoblin": Ancestry({"dexterity":2,"constitution":2},
                         "Medium",1,0,("Darkvision 60 ft.","+4 Move Silently")),
}
# Names in this list are a source-index for *manual* ancestry creation,
# not an assertion that a character with this name has zero racial HD.
NPC_RACE_NAMES = tuple(dict.fromkeys(tuple(NPC_RACES) +
                      EXPANDED_RACES + MONSTER_RACES + ("Custom / Unlisted",)))
