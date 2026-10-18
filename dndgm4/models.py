"""Saved library definitions. Encounter instances will be separate models."""
from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Literal

CreatureKind = Literal["pc", "npc", "monster"]
KINDS = ("pc", "npc", "monster")
KIND_LABELS = {"pc": "Player Character", "npc": "NPC", "monster": "Monster"}


@dataclass(frozen=True, slots=True)
class Creature:
    name: str
    kind: CreatureKind = "pc"
    id: str = ""
    race_type: str = ""
    character_class: str = ""
    level: int = 1
    challenge_rating: str = ""
    armor_class: int = 10
    max_hit_points: int = 1
    strength: int = 10
    dexterity: int = 10
    constitution: int = 10
    intelligence: int = 10
    wisdom: int = 10
    charisma: int = 10
    notes: str = ""
    sheet_json: str = ""
    archived: bool = False
    created_at: str = ""
    updated_at: str = ""

    def duplicate(self) -> "Creature":
        return replace(self, id="", name=f"{self.name} (Copy)",
                       archived=False, created_at="", updated_at="")
