"""Persisted scene roster and lossless, size-checked context for The Scribe.

Only explicitly selected records or records placed in the scene are sent to
local inference. Complete structured sheets are preserved in their library;
the active prompt is rejected if it cannot fit, never silently truncated.
"""
from __future__ import annotations

from dataclasses import asdict
import json
import os
from pathlib import Path
import tempfile

SCENE_FIELDS = ("title", "location", "time_conditions", "scenery",
                "places", "campaign_notes")
MAX_CONTEXT = 6000


def blank_scene() -> dict:
    return {"version": 1, "record_ids": [],
            **{name: "" for name in SCENE_FIELDS}}


def validate_scene(data: dict) -> dict:
    if not isinstance(data, dict) or data.get("version") != 1:
        raise ValueError("Unknown scene format.")
    ids = data.get("record_ids", [])
    if (not isinstance(ids, list) or len(ids) > 250 or
            any(not isinstance(x, str) or not 1 <= len(x) <= 128 for x in ids)):
        raise ValueError("Scene roster must contain valid library identifiers.")
    clean = blank_scene()
    clean["record_ids"] = list(dict.fromkeys(ids))
    for field in SCENE_FIELDS:
        value = data.get(field, "")
        if not isinstance(value, str) or len(value) > 20000:
            raise ValueError(f"Invalid scene field: {field}")
        clean[field] = value
    return clean


class SceneStore:
    def __init__(self, database_path):
        self.path = Path(database_path).with_name("current_scene.json")

    def load(self) -> dict:
        if not self.path.exists():
            return blank_scene()
        if self.path.stat().st_size > 150000:
            raise ValueError("Scene file is too large.")
        try:
            return validate_scene(json.loads(self.path.read_text(encoding="utf-8")))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise ValueError("Could not read the saved scene file.") from exc

    def save(self, data: dict):
        scene = validate_scene(data)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(
                    mode="w", encoding="utf-8", dir=self.path.parent,
                    prefix=".scene_", suffix=".tmp", delete=False) as handle:
                temporary = Path(handle.name)
                json.dump(scene, handle, ensure_ascii=False, indent=2)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, self.path)
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)


def add_records(scene: dict, record_ids: list[str]) -> dict:
    updated = dict(validate_scene(scene))
    updated["record_ids"] = list(dict.fromkeys(
        updated["record_ids"] + record_ids))
    return validate_scene(updated)


def record_details(record) -> str:
    """Include every saved field and nested character/monster sheet field."""
    data = asdict(record)
    sheet = data.pop("sheet_json", "")
    if sheet:
        try:
            data["structured_sheet"] = json.loads(sheet)
        except (TypeError, ValueError):
            data["structured_sheet"] = {"unreadable_saved_sheet": sheet}
    values = {k: v for k, v in data.items()
              if v is not None and v != "" and v != []}
    return json.dumps(values, indent=2, ensure_ascii=False, sort_keys=True)


def build_scribe_context(scene: dict, records: list, *,
                         mode: str = "scene", max_chars: int = MAX_CONTEXT) -> str:
    """Build one readable prompt from full records; fail if too large.

    Records are resolved by the caller from selected table rows or the saved
    scene roster. Never silently drop details to fit the local model limit.
    """
    if mode not in ("scene", "selection"):
        raise ValueError("Context mode must be scene or selection.")
    checked = validate_scene(scene)
    parts = [
        "D&D 3.5 SESSION CONTEXT",
        "Use these SAVED details as factual campaign information. Do not "
        "change statistics, invent known traits, or assume absent people.",
        f"Source: {'selected library records' if mode == 'selection' else 'saved scene roster'}",
    ]
    for field in SCENE_FIELDS:
        if checked[field].strip():
            parts.append(f"{field.replace('_', ' ').title()}: {checked[field].strip()}")
    parts.append(f"Explicitly loaded records: {len(records)}")
    for index, record in enumerate(records, 1):
        parts.append(f"RECORD {index} / {record.name} ({record.kind})\n"
                     + record_details(record))
    result = "\n\n".join(parts)
    if len(result) > max_chars:
        raise ValueError(
            f"Complete context needs {len(result):,} characters, but the "
            f"local Scribe currently supports {max_chars:,}. "
            "Remove some records from the scene/selection or shorten the "
            "scene notes. No character details have been silently omitted."
        )
    return result
