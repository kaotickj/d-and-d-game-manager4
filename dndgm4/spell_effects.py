"""Pure suggestions for three explicitly reviewed SRD spell effects.

An effect's display name never activates a rule. Callers supply fresh equipment
statistics and explicitly reviewed mechanics attached to individual timers.
This module does not cast spells, spend resources, write sheets or alter timers.
"""
from __future__ import annotations

from copy import deepcopy


STACKING_SOURCE = "https://www.d20srd.org/srd/theBasics.htm#stacking"
CATALOG = {
    "Bless": {
        "source": "https://www.d20srd.org/srd/spells/bless.htm",
        "description": "+1 morale on attacks and saves against fear only.",
        "bonus_type": "morale", "bonus": 1,
        "unsupported": "Fear eligibility, area/ally selection and interaction with bane require DM review.",
    },
    "Mage Armor": {
        "source": "https://www.d20srd.org/srd/spells/mageArmor.htm",
        "description": "+4 armor bonus; competes with worn armor rather than adding to it.",
        "bonus_type": "armor", "bonus": 4,
        "unsupported": "Force protection against incorporeal attacks requires separate DM adjudication.",
    },
    "Shield": {
        "source": "https://www.d20srd.org/srd/spells/shield.htm",
        "description": "+4 shield bonus; competes with an equipped shield.",
        "bonus_type": "shield", "bonus": 4,
        "unsupported": "Magic missile negation and force protection against incorporeal touch attacks are not resolved here.",
    },
}


def validate_mechanics(payload) -> dict:
    """Accept only the versioned, bounded, explicit spell-mechanics envelope."""
    if not isinstance(payload, dict) or set(payload) != {"version", "spell"}:
        raise ValueError("Spell mechanics require only version and spell fields.")
    if type(payload["version"]) is not int or payload["version"] != 1:
        raise ValueError("Unsupported spell mechanics version.")
    if not isinstance(payload["spell"], str) or payload["spell"] not in CATALOG:
        raise ValueError("Choose a supported reviewed spell effect.")
    return {"version": 1, "spell": payload["spell"]}


def preview_effects(stats: dict, effects: list[dict], target_id: str) -> dict:
    """Return new effective statistics without mutating input or saved state.

    ``stats`` must be fresh equipment-calculator output, not this function's
    previous result. Only live, explicitly targeted mechanics participate.
    Ordinary touch AC is unchanged; force/incorporeal exceptions stay manual.
    Bless's conditional fear-save modifier is separate from the base saves.
    """
    if not isinstance(stats, dict) or not isinstance(effects, list):
        raise ValueError("Spell preview needs equipment statistics and effect timers.")
    if not isinstance(target_id, str):
        raise ValueError("Select a combatant ID for spell suggestions.")
    result = deepcopy(stats)
    for key in ("ac", "touch_ac", "flat_footed_ac", "armor_bonus", "shield_bonus"):
        if type(result.get(key)) is not int:
            raise ValueError(f"Equipment statistics need an integer {key}.")
    if result.get("attack_bonus") is not None and type(result["attack_bonus"]) is not int:
        raise ValueError("Attack suggestions must be an integer or unavailable.")
    for key in ("warnings", "sources"):
        if not isinstance(result.get(key, []), list):
            raise ValueError(f"Equipment {key} must be a list.")
        result.setdefault(key, [])
    result["active_effects"] = []
    result["suppressed_effects"] = []
    result["fear_save_bonus"] = 0
    seen = set()
    for effect in effects:
        if not isinstance(effect, dict):
            raise ValueError("Invalid effect timer.")
        if "mechanics" not in effect:
            continue
        mechanics = validate_mechanics(effect["mechanics"])
        if (not target_id or effect.get("target_id") != target_id
                or type(effect.get("remaining")) is not int or effect["remaining"] <= 0):
            continue
        name = mechanics["spell"]
        rule = CATALOG[name]
        descriptor = {"id": effect.get("id", ""), "spell": name,
                      "bonus_type": rule["bonus_type"], "bonus": rule["bonus"],
                      "applied_delta": 0, "source": rule["source"]}
        for source in (rule["source"], STACKING_SOURCE):
            if source not in result["sources"]:
                result["sources"].append(source)
        if rule["unsupported"] not in result["warnings"]:
            result["warnings"].append(rule["unsupported"])
        if name in seen:
            descriptor["reason"] = "Duplicate spell bonuses do not stack."
            result["suppressed_effects"].append(descriptor)
            continue
        seen.add(name)
        if name == "Bless":
            if type(result.get("attack_bonus")) is int:
                result["attack_bonus"] += rule["bonus"]
            result["fear_save_bonus"] = rule["bonus"]
            descriptor["applied_delta"] = rule["bonus"]
            result["active_effects"].append(descriptor)
            continue
        key = "armor_bonus" if name == "Mage Armor" else "shield_bonus"
        delta = max(result[key], rule["bonus"]) - result[key]
        descriptor["applied_delta"] = delta
        if not delta:
            descriptor["reason"] = "An equal or larger equipped bonus of this type already applies."
            result["suppressed_effects"].append(descriptor)
            continue
        result[key] += delta
        result["ac"] += delta
        result["flat_footed_ac"] += delta
        result["active_effects"].append(descriptor)
    return result
