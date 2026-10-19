"""Campaign continuity and validated AI drafts, independent of PyQt.

The AI writes suggestions. The existing 3.5 builder remains the sole source of
calculated combat statistics. No proposed encounter, chapter or creature is
saved without a separate user review/import action.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import secrets
import tempfile
from dataclasses import dataclass, field
from typing import Any

from .character_sheet import (
    ALIGNMENTS, TEMPLATES, allocate_default_skills, build_sheet, class_specs,
    skill_budget, SKILLS,
)
from .creation import ABILITIES, RACIAL_ADJUSTMENTS, build_character
from .models import Creature
from .monster_rules import MonsterBlueprint, TYPES, SIZES, build_monster
from .npc_races import NPC_RACES


FIELDS = ("title", "setting", "premise", "tone", "location", "scenery",
          "conditions", "settlements", "inns_taverns", "factions",
          "current_quests", "session_notes")
LIST_FIELDS = ("party_ids", "present_ids")
MAX_CHAPTERS = 100
MAX_ENCOUNTERS = 200


def fresh_campaign() -> dict:
    return {
        "version": 1,
        **{key: "" for key in FIELDS},
        **{key: [] for key in LIST_FIELDS},
        "encounters": [], "chapters": [],
        "outline": "",
    }


class CampaignStore:
    """Single active campaign: atomic local JSON alongside SQLite library.

    Intentionally avoids changing the v2 creature DB schema or the main app
    layout. Future campaign/party managers can migrate this standalone file.
    """
    def __init__(self, database_path: str | Path):
        db = Path(database_path)
        self.path = db.with_name("campaign_workspace.json")

    def load(self) -> dict:
        if not self.path.is_file():
            return fresh_campaign()
        if self.path.stat().st_size > 2_000_000:
            raise ValueError("Campaign workspace exceeds 2 MB; check the file.")
        try:
            content = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, ValueError) as exc:
            raise ValueError("Unable to read campaign workspace JSON.") from exc
        if not isinstance(content, dict) or content.get("version") != 1:
            raise ValueError("Unsupported campaign workspace version.")
        result = fresh_campaign()
        for field in FIELDS:
            value = content.get(field, "")
            if not isinstance(value, str) or len(value) > 20000:
                raise ValueError(f"Invalid campaign field: {field}")
            result[field] = value
        for field in LIST_FIELDS:
            value = content.get(field, [])
            if not isinstance(value, list) or len(value) > 150 or any(
                not isinstance(item, str) or len(item) > 128 for item in value
            ):
                raise ValueError(f"Invalid party/presence entries: {field}")
            result[field] = list(dict.fromkeys(value))
        for field, maximum in (("chapters", MAX_CHAPTERS),
                               ("encounters", MAX_ENCOUNTERS)):
            entries = content.get(field, [])
            if (not isinstance(entries, list) or len(entries) > maximum or
                    any(not isinstance(x, dict) for x in entries)):
                raise ValueError(f"Invalid saved {field}.")
            result[field] = entries
        outline = content.get("outline", "")
        if not isinstance(outline, str) or len(outline) > 100000:
            raise ValueError("Invalid campaign outline.")
        result["outline"] = outline
        return result

    def save(self, value: dict) -> None:
        if not isinstance(value, dict):
            raise ValueError("Campaign data must be an object.")
        # Validate using the same path as load, but never touch the live file
        # until the complete JSON has been checked and durably staged.
        candidate = json.dumps(value, ensure_ascii=False, indent=2)
        if len(candidate.encode("utf-8")) > 2_000_000:
            raise ValueError("Campaign workspace is over 2 MB.")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(
                    "w", encoding="utf-8", dir=self.path.parent,
                    prefix=".campaign-", suffix=".tmp", delete=False) as out:
                temporary = Path(out.name)
                out.write(candidate)
                out.flush()
                os.fsync(out.fileno())
            # The content is still checked before changing the live file.
            check = json.loads(temporary.read_text(encoding="utf-8"))
            if check.get("version") != 1:
                raise ValueError("Unsupported campaign workspace version.")
            os.replace(temporary, self.path)
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)


def campaign_context(campaign: dict, library: list[Creature], *,
                     selected: Creature | None = None,
                     max_chars: int = 5500) -> str:
    """Use only names and records actually selected by the DM.

    Arbitrary records in the entire library aren't presumed present at a scene.
    Sensitive DM notes are capped; this string goes to a local model only.
    """
    by_id = {c.id: c for c in library if c.id and not c.archived}
    segments = []
    for field in FIELDS:
        value = campaign.get(field, "")
        if isinstance(value, str) and value.strip():
            segments.append(f"{field.replace('_', ' ').title()}: {value.strip()[:800]}")
    for key, label in (("party_ids", "Adventuring party"),
                       ("present_ids", "Other people and creatures present")):
        matched = []
        for record_id in campaign.get(key, [])[:80]:
            creature = by_id.get(record_id)
            if creature:
                rating = (f"CR {creature.challenge_rating or 'unassigned'}"
                          if creature.kind == "monster" else
                          f"level {creature.level}")
                matched.append(f"{creature.name} ({creature.kind}, "
                               f"{creature.race_type} {creature.character_class}, "
                               f"{rating}; {creature.notes[:100]})")
        segments.append(f"{label}: " + ("; ".join(matched) if matched else
                                         "(no library members assigned)"))
    if selected:
        segments.append(f"Selected record: {selected.name}, {selected.kind}, "
                        f"{selected.race_type} {selected.character_class}.")
    return "\n".join(segments)[:max_chars]


def parse_model_json(raw: str) -> dict:
    """Accept fenced JSON or explanatory prefaces, reject malformed objects."""
    if not isinstance(raw, str) or len(raw) > 75000:
        raise ValueError("AI result is missing or too long.")
    decoder = json.JSONDecoder()
    for index, char in enumerate(raw):
        if char == "{":
            try:
                obj, _ = decoder.raw_decode(raw[index:])
            except ValueError:
                continue
            if isinstance(obj, dict):
                return obj
    raise ValueError("No valid JSON object found in the AI draft. "
                     "Edit the draft to valid JSON or generate again.")


def _plain(value: Any, name: str, *, maximum: int = 4000,
           required: bool = False) -> str:
    if not isinstance(value, str) or len(value) > maximum:
        raise ValueError(f"{name} must be text of at most {maximum} characters.")
    if required and not value.strip():
        raise ValueError(f"{name} is required.")
    return value.strip()


def _strings(value: Any, label: str, limit: int) -> list[str]:
    if not isinstance(value, list) or len(value) > limit:
        raise ValueError(f"{label} must be a list of up to {limit} strings.")
    return [_plain(item, label, maximum=180) for item in value if item]


def _scores(payload: Any, *, monster: bool = False) -> dict:
    if not isinstance(payload, dict) or set(payload) != set(ABILITIES):
        raise ValueError("Provide exactly STR, DEX, CON, INT, WIS and CHA as "
                         "full lowercase ability names.")
    scores = {}
    for name in ABILITIES:
        value = payload[name]
        if monster and value is None:
            scores[name] = None
        elif type(value) is not int or not (0 <= value <= 99 if monster
                                            else 3 <= value <= 18):
            raise ValueError(f"Invalid {name} ability score.")
        else:
            scores[name] = value
    return scores


def creature_from_ai_draft(payload: dict, expected_kind: str) -> Creature:
    """Transform a reviewed structured suggestion through existing builders.

    This isn't a comprehensive character engine: character level remains 1;
    feats/spells/equipment eligibility, monster CR and special qualities remain
    DM-reviewed. Unsupported NPC races and class rules are rejected, not guessed.
    """
    if expected_kind not in ("pc", "npc", "monster"):
        raise ValueError("Unknown generation kind.")
    if not isinstance(payload, dict) or payload.get("kind") != expected_kind:
        raise ValueError("AI draft kind does not match the selected creator.")
    name = _plain(payload.get("name"), "name", maximum=200, required=True)
    if expected_kind == "monster":
        species = _plain(payload.get("species"), "species", maximum=120,
                         required=True)
        creature_type = _plain(payload.get("creature_type"), "creature_type",
                               maximum=60, required=True)
        if creature_type not in TYPES:
            raise ValueError("Unsupported monster type; select an SRD 3.5 type.")
        raw_hd = payload.get("hit_dice")
        if type(raw_hd) is not int or not 1 <= raw_hd <= 30:
            raise ValueError("Generated monsters require 1-30 racial Hit Dice.")
        attrs = _scores(payload.get("abilities"), monster=True)
        if TYPES[creature_type].no_con:
            attrs["constitution"] = None
        elif attrs["constitution"] is None:
            raise ValueError("Only Constructs and Undead can omit CON.")
        if creature_type == "Animal" and attrs["intelligence"] not in (1, 2):
            raise ValueError("Animal Intelligence must be 1 or 2.")
        size = _plain(payload.get("size", "Medium"), "size", maximum=30)
        if size not in SIZES:
            raise ValueError("Unknown creature size.")
        monster = MonsterBlueprint(
            name=name, species=species, creature_type=creature_type,
            hit_dice=raw_hd, abilities=attrs, size=size,
            subtype=_plain(payload.get("subtype", ""), "subtype", maximum=180),
            good_save=_plain(payload.get("good_save", "Fort"),
                             "good_save", maximum=12),
            natural_armor=0,  # never trust arbitrary invented armor bonuses
            cr="",            # Challenge Rating requires DM determination
            speed=_plain(payload.get("speed", "30 ft."), "speed", maximum=80),
            alignment=_plain(payload.get("alignment", "Neutral"),
                             "alignment", maximum=50),
            environment=_plain(payload.get("environment", ""), "environment"),
            organization=_plain(payload.get("organization", ""), "organization"),
            attacks="", special_attacks="", special_qualities="",
            feats=[], skills="",
            biography=_plain(payload.get("biography", ""), "biography",
                             maximum=7000),
            notes=("AI-generated draft. DM must supply/verify CR, natural "
                   "attacks, special qualities, spell-like abilities, "
                   "equipment, skills and feats before play.\n"
                   + _plain(payload.get("notes", ""), "notes", maximum=2500))
        )
        return build_monster(monster)
    race = _plain(payload.get("race"), "race", maximum=100, required=True)
    class_name = _plain(payload.get("class"), "class", maximum=80, required=True)
    if class_name not in TEMPLATES:
        raise ValueError("Class is not a supported template; choose an "
                         "implemented class before importing.")
    attrs = _scores(payload.get("abilities"))
    profile = NPC_RACES.get(race) if expected_kind == "npc" else None
    if expected_kind == "pc" and race not in RACIAL_ADJUSTMENTS:
        raise ValueError("Player race not supported by the 3.5 Character Forge.")
    if expected_kind == "npc" and profile is None:
        raise ValueError("NPC ancestry lacks verified racial modifiers. "
                         "Create the custom ancestry through NPC Forge instead.")
    if expected_kind == "pc" and class_name in (
        "Adept", "Aristocrat", "Commoner", "Expert", "Warrior"
    ):
        raise ValueError("NPC classes aren't available to PCs in this import.")
    spec = class_specs(class_name)
    base = build_character(
        name=name, race=race, character_class=class_name,
        base=attrs, method="Local AI proposal; reviewed by DM",
        kind=expected_kind, custom_hit_die=spec.hit_die,
        custom_skill_points=spec.skill_points,
        racial_override=profile.ability_adjustments if profile else None,
        size_override=profile.size if profile else None,
    )
    custom_skills = list(spec.class_skills) if class_name == "Expert" else []
    if class_name == "Expert" and len(custom_skills) != 10:
        raise ValueError("Expert requires exactly ten class skills.")
    budget = skill_budget(class_name, base.intelligence, race)
    skill_template = spec
    ranks = allocate_default_skills(skill_template, budget)
    alignment = _plain(payload.get("alignment", "True Neutral"), "alignment",
                       maximum=30)
    if alignment not in ALIGNMENTS:
        raise ValueError("Choose one of the nine valid D&D 3.5 alignments.")
    feats = _strings(payload.get("feats", []), "feats", 8)
    equipment = _strings(payload.get("equipment", []), "equipment", 20)
    if not equipment:
        equipment = list(spec.suggested_equipment)
    if not feats:
        feats = list(spec.suggested_feats)
    record = build_sheet(
        character=base, class_name=class_name, ranks=ranks,
        feats=feats, equipment=equipment, alignment=alignment,
        deity=_plain(payload.get("deity", ""), "deity", maximum=100),
        languages=_strings(payload.get("languages", []), "languages", 12),
        appearance=_plain(payload.get("appearance", ""), "appearance",
                          maximum=2000),
        personality=_plain(payload.get("personality", ""), "personality",
                           maximum=2000),
        background=_plain(payload.get("biography", ""), "biography",
                          maximum=7000),
        custom_class_skills=custom_skills,
        spell_notes=_plain(payload.get("spell_notes", ""), "spell_notes",
                           maximum=2000),
        extra_notes=("Local AI draft. Level-1 template and recommended skill "
                     "ranks were calculated by the rules engine. DM review "
                     "required for feats, equipment, spells, class features "
                     "and the overall build."),
    )
    if expected_kind == "npc":
        from dataclasses import replace
        saved = json.loads(record.sheet_json)
        saved["npc_ancestry"] = {
            "race": race, "size": profile.size,
            "modifiers": profile.ability_adjustments,
            "level_adjustment": profile.level_adjustment,
            "racial_hit_dice": profile.racial_hit_dice,
            "verified_profile": True, "traits": list(profile.traits),
        }
        record = replace(record, sheet_json=json.dumps(saved,sort_keys=True))
    return record


def random_encounter_seed(library: list[Creature], *, maximum: int = 12) -> str:
    """Sample only real NPC/monster records, using system randomness."""
    candidates = [c for c in library if c.kind in ("monster", "npc") and
                  not c.archived and c.id]
    if not candidates:
        return "(no saved NPCs or monsters yet; create some first)"
    count = min(len(candidates), maximum)
    picks = secrets.SystemRandom().sample(candidates, count)
    return "\n".join(f"{c.id} | {c.name} | {c.kind} | "
                     f"CR {c.challenge_rating or 'unassigned'} | "
                     f"{c.race_type} {c.character_class}"
                     for c in picks)


def validate_encounter_draft(payload: dict, library: list[Creature]) -> dict:
    """Link encounters only to exact existing library IDs, never fake monsters."""
    if not isinstance(payload, dict):
        raise ValueError("Encounter proposal must be a JSON object.")
    active = {c.id: c for c in library
              if c.id and c.kind in ("monster", "npc") and not c.archived}
    entries = payload.get("participants")
    if not isinstance(entries, list) or len(entries) > 16:
        raise ValueError("Encounter participants must be a list of at most 16.")
    participants = []
    for item in entries:
        if not isinstance(item, dict) or not isinstance(item.get("record_id"), str):
            raise ValueError("Participants require existing record_id values.")
        record = active.get(item["record_id"])
        if record is None:
            raise ValueError("An encounter participant is not a saved NPC/monster "
                             "record. Choose only valid library IDs.")
        count = item.get("count", 1)
        if type(count) is not int or not 1 <= count <= 20:
            raise ValueError("Participant count must be 1-20.")
        participants.append({"record_id": record.id, "name": record.name,
                             "count": count, "kind": record.kind,
                             "cr": record.challenge_rating})
    result = {
        "title": _plain(payload.get("title", ""), "title", maximum=180,
                        required=True),
        "location": _plain(payload.get("location", ""), "location", maximum=250),
        "setup": _plain(payload.get("setup", ""), "setup", maximum=4000),
        "read_aloud": _plain(payload.get("read_aloud", ""), "read_aloud",
                             maximum=4000),
        "terrain": _plain(payload.get("terrain", ""), "terrain", maximum=1500),
        "stakes": _plain(payload.get("stakes", ""), "stakes", maximum=1500),
        "consequences": _plain(payload.get("consequences", ""), "consequences",
                               maximum=1500),
        "participants": participants,
        "gm_review": ("Encounter level, reward/XP, party balance, hazards, "
                      "treasure, tactics and special abilities require DM review."),
    }
    return result


def save_outline(campaign: dict, text: str) -> dict:
    if not isinstance(text, str) or not 5 <= len(text.strip()) <= 100000:
        raise ValueError("Campaign outline must be 5-100,000 characters.")
    draft = dict(campaign)
    draft["outline"] = text.strip()
    return draft


def append_chapter(campaign: dict, title: str, text: str) -> dict:
    chapters = list(campaign.get("chapters", []))
    if len(chapters) >= MAX_CHAPTERS:
        raise ValueError("This workspace has reached the chapter limit.")
    title = _plain(title, "chapter title", maximum=180, required=True)
    text = _plain(text, "chapter text", maximum=20000, required=True)
    chapters.append({"title": title, "text": text})
    return {**campaign, "chapters": chapters}
