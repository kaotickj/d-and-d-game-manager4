"""Versioned, validated Compendium exports; independent of Qt.

Only the app's JSON interchange format is accepted here. Legacy character files
and arbitrary SQLite databases require their own characterized importers.
"""
from __future__ import annotations

from dataclasses import dataclass, fields
import json
from pathlib import Path
from typing import Iterable

from .models import Creature
from .storage import validate

MAX_IMPORT_BYTES = 32 * 1024 * 1024
MAX_IMPORT_RECORDS = 10000
DUPLICATE_POLICIES = ("skip", "copy", "replace")
_INTEGER_FIELDS = frozenset(("level", "armor_class", "max_hit_points",
                             "strength", "dexterity", "constitution",
                             "intelligence", "wisdom", "charisma"))
_FIELDS = frozenset(field.name for field in fields(Creature))


@dataclass(frozen=True)
class ImportSummary:
    total: int = 0
    added: int = 0
    skipped: int = 0
    copied: int = 0
    replaced: int = 0


def _validate_record(record: Creature) -> None:
    for field in fields(Creature):
        value = getattr(record, field.name)
        expected = bool if field.name == "archived" else (
            int if field.name in _INTEGER_FIELDS else str)
        # bool is a subclass of int; accepting it would silently change stats.
        if type(value) is not expected:
            raise ValueError(f"{field.name} must be {expected.__name__}.")
        if expected is str:
            try:
                value.encode("utf-8")
            except UnicodeEncodeError as exc:
                raise ValueError(f"{field.name} contains invalid Unicode.") from exc
    if not record.id.strip() or len(record.id) > 200:
        raise ValueError("Record ID must contain 1–200 characters.")
    try:
        validate(record)
    except RecursionError as exc:
        raise ValueError("Character sheet JSON is nested too deeply.") from exc


def validate_import_records(records: Iterable[Creature]) -> tuple[Creature, ...]:
    """Validate the entire batch before repository writes or preview queries."""
    validated = []
    seen = set()
    for index, record in enumerate(records, 1):
        if index > MAX_IMPORT_RECORDS:
            raise ValueError(f"Import is limited to {MAX_IMPORT_RECORDS:,} records.")
        try:
            if not isinstance(record, Creature):
                raise ValueError("Each record must be a Creature.")
            _validate_record(record)
            if record.id in seen:
                raise ValueError(f"Duplicate record ID: {record.id}.")
        except ValueError as exc:
            raise ValueError(f"Record {index}: {exc}") from exc
        seen.add(record.id)
        validated.append(record)
    return tuple(validated)


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"Duplicate JSON field: {key}.")
        result[key] = value
    return result


def _invalid_constant(value):
    raise ValueError(f"Invalid JSON number: {value}.")


def read_library_export(path: str | Path) -> tuple[Creature, ...]:
    """Read one bounded UTF-8 export without changing the library."""
    with Path(path).open("rb") as source:
        contents = source.read(MAX_IMPORT_BYTES + 1)
    if len(contents) > MAX_IMPORT_BYTES:
        raise ValueError("Library export exceeds the 32 MiB import limit.")
    try:
        payload = json.loads(contents.decode("utf-8-sig"),
                             object_pairs_hook=_unique_object,
                             parse_constant=_invalid_constant)
    except (UnicodeError, json.JSONDecodeError, RecursionError) as exc:
        raise ValueError("Choose a valid UTF-8 library JSON export.") from exc
    if not isinstance(payload, dict) or set(payload) != {"format", "version", "creatures"}:
        raise ValueError("Expected a DnDGM4 library export with format, version, and creatures.")
    if payload["format"] != "dndgm4-library":
        raise ValueError("This file is not a DnDGM4 library export.")
    if type(payload["version"]) is not int or payload["version"] != 1:
        raise ValueError("Unsupported library export version; this app supports version 1.")
    rows = payload["creatures"]
    if not isinstance(rows, list):
        raise ValueError("The creatures field must be a list.")
    if len(rows) > MAX_IMPORT_RECORDS:
        raise ValueError(f"Import is limited to {MAX_IMPORT_RECORDS:,} records.")
    records = []
    for index, row in enumerate(rows, 1):
        if not isinstance(row, dict):
            raise ValueError(f"Record {index} must be an object.")
        unknown = set(row) - _FIELDS
        if unknown:
            raise ValueError(f"Record {index} has unsupported fields: {', '.join(sorted(unknown))}.")
        if "name" not in row or "id" not in row:
            raise ValueError(f"Record {index} requires a name and ID.")
        records.append(Creature(**row))
    return validate_import_records(records)


def summarize_import(records: tuple[Creature, ...], existing_ids: set[str],
                     duplicates: str) -> ImportSummary:
    if duplicates not in DUPLICATE_POLICIES:
        raise ValueError("Duplicate handling must be skip, copy, or replace.")
    conflicts = sum(record.id in existing_ids for record in records)
    return ImportSummary(total=len(records), added=len(records) - conflicts,
                         skipped=conflicts if duplicates == "skip" else 0,
                         copied=conflicts if duplicates == "copy" else 0,
                         replaced=conflicts if duplicates == "replace" else 0)
