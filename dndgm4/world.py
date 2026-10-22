"""Typed campaign world records and relationships, without game-state side effects.

These are the DM's records. An item is an inventory entry, and a reward is a
reward journal entry; saving either never modifies a creature, grants XP, or
distributes money. Only a handout's explicitly authored player_text is exported.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, fields
from decimal import Decimal, InvalidOperation
import json
from pathlib import Path
import re
from uuid import uuid4

from .campaigns import CampaignRepository


@dataclass(frozen=True, slots=True)
class DetailField:
    key: str
    label: str
    type: str = "text"
    default: str | int | tuple = ""
    maximum: int = 20000
    places: int = 3


KIND_LABELS = {
    "quest": "Quest", "location": "Location", "faction": "Faction",
    "handout": "Player handout", "event": "Calendar event",
    "route": "Travel route", "item": "Inventory / treasure",
    "reward": "Reward journal", "note": "Lore / note",
}
KINDS = tuple(KIND_LABELS)
STATUSES = {
    "quest": ("planned", "active", "completed", "failed"),
    "location": ("active", "abandoned", "destroyed"),
    "faction": ("active", "allied", "neutral", "hostile", "disbanded"),
    "handout": ("draft", "ready", "shared"),
    "event": ("planned", "active", "completed", "cancelled"),
    "route": ("planned", "open", "blocked"),
    "item": ("available", "reserved", "depleted"),
    "reward": ("planned", "recorded"),
    "note": ("active", "resolved"),
}
DETAIL_FIELDS = {
    "quest": (
        DetailField("objectives", "Objectives", "multiline"),
        DetailField("reward", "Proposed reward", "multiline"),
        DetailField("assigned_ids", "Assigned characters / NPCs", "creatures", ()),
    ),
    "location": (
        DetailField("region", "Region"),
        DetailField("landmarks", "Landmarks and features", "multiline"),
        DetailField("map_notes", "Map reference / notes", "multiline"),
    ),
    "faction": (
        DetailField("goals", "Goals and motives", "multiline"),
        DetailField("contacts_ids", "Contacts", "creatures", ()),
        DetailField("influence", "Influence / territory", "multiline"),
    ),
    "handout": (DetailField("player_text", "Player text (the entire export)", "multiline", maximum=100000),),
    "event": (
        DetailField("day", "Campaign day", "integer", 0, 1000000000),
        DetailField("time", "Time (HH:MM or blank)", "time"),
        DetailField("duration_minutes", "Duration in minutes", "integer", 0, 52560000),
        DetailField("participants_ids", "Participants", "creatures", ()),
    ),
    "route": (
        DetailField("from_id", "From location", "location"),
        DetailField("to_id", "To location", "location"),
        DetailField("distance_miles", "Distance in miles", "decimal", "0"),
        DetailField("pace", "Pace / travel method"),
        DetailField("encounter_notes", "Travel encounters and hazards", "multiline"),
    ),
    "item": (
        DetailField("quantity", "Quantity", "integer", 1, 1000000000),
        DetailField("unit_value_gp", "Value per item (gp)", "decimal", "0", places=2),
        DetailField("unit_weight_lb", "Weight per item (lb)", "decimal", "0"),
        DetailField("owner_ids", "Owners / custodians", "creatures", ()),
        DetailField("container", "Container / storage location"),
    ),
    "reward": (
        DetailField("xp", "XP recorded", "integer", 0, 1000000000),
        DetailField("gp", "Gold recorded (gp)", "decimal", "0", places=2),
        DetailField("recipient_ids", "Recipients", "creatures", ()),
        DetailField("source", "Source / allocation notes", "multiline"),
    ),
    "note": (DetailField("body", "Lore / notes", "multiline", maximum=100000),),
}


@dataclass(frozen=True, slots=True)
class WorldRecord:
    id: str
    campaign_id: str
    kind: str
    name: str
    status: str = "active"
    summary: str = ""
    dm_notes: str = ""
    details_json: str = "{}"
    archived: bool = False
    created_at: str = ""
    updated_at: str = ""

    @property
    def details(self) -> dict:
        return parse_details(self.kind, self.details_json)


@dataclass(frozen=True, slots=True)
class WorldLink:
    id: str
    campaign_id: str
    source_id: str
    target_id: str
    relation: str
    notes: str = ""
    created_at: str = ""
    updated_at: str = ""


def _text(value, label, maximum=100000, *, required=False):
    if not isinstance(value, str) or len(value) > maximum:
        raise ValueError(f"{label} must be text of at most {maximum:,} characters.")
    try:
        value.encode("utf-8")
    except UnicodeError as exc:
        raise ValueError(f"{label} contains invalid Unicode.") from exc
    if "\x00" in value:
        raise ValueError(f"{label} contains an invalid null character.")
    if required and not value.strip():
        raise ValueError(f"{label} is required.")
    return value.strip() if required else value


def _identity(value, label="Identifier"):
    return _text(value, label, 200, required=True)


def _kind(kind):
    if not isinstance(kind, str) or kind not in KIND_LABELS:
        raise ValueError("Choose a supported campaign entry type.")
    return kind


def default_details(kind: str) -> dict:
    return {field.key: list(field.default) if field.type == "creatures" else field.default
            for field in DETAIL_FIELDS[_kind(kind)]}


def _decimal(value, field):
    if isinstance(value, (int, Decimal)) and not isinstance(value, bool):
        value = str(value)
    if not isinstance(value, str) or not re.fullmatch(
            rf"[0-9]{{1,12}}(?:\.[0-9]{{1,{field.places}}})?", value.strip()):
        raise ValueError(f"{field.label} must be a nonnegative decimal with at most {field.places} decimal places.")
    try:
        number = Decimal(value.strip())
    except InvalidOperation as exc:
        raise ValueError(f"{field.label} must be a valid decimal.") from exc
    if not number.is_finite() or number > Decimal("1000000000"):
        raise ValueError(f"{field.label} must be between 0 and 1,000,000,000.")
    result = format(number, "f")
    return result.rstrip("0").rstrip(".") if "." in result else result


def validate_details(kind: str, details: dict) -> dict:
    """Return canonical typed fields; refuse unknown fields rather than drop them."""
    _kind(kind)
    if not isinstance(details, dict):
        raise ValueError("Campaign entry details must be an object.")
    allowed = {field.key for field in DETAIL_FIELDS[kind]}
    if set(details) - allowed:
        raise ValueError("Campaign entry contains unsupported detail fields.")
    clean = default_details(kind)
    for field in DETAIL_FIELDS[kind]:
        value = details.get(field.key, clean[field.key])
        if field.type == "integer":
            if type(value) is not int or not 0 <= value <= field.maximum:
                raise ValueError(f"{field.label} must be a whole number between 0 and {field.maximum:,}.")
        elif field.type == "decimal":
            value = _decimal(value, field)
        elif field.type == "creatures":
            if not isinstance(value, list) or len(value) > 250:
                raise ValueError(f"{field.label} must contain at most 250 library references.")
            value = list(dict.fromkeys(_identity(identity, field.label + " ID") for identity in value))
        elif field.type == "location":
            value = _text(value, field.label, 200)
            if value:
                value = _identity(value, field.label)
        elif field.type == "time":
            value = _text(value, field.label, 5)
            if value and not re.fullmatch(r"(?:[01][0-9]|2[0-3]):[0-5][0-9]", value):
                raise ValueError("Event time must be HH:MM on a 24-hour clock or blank.")
        else:
            value = _text(value, field.label, field.maximum)
        clean[field.key] = value
    return clean


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Campaign entry details contain duplicate fields.")
        result[key] = value
    return result


def _invalid_constant(value):
    raise ValueError("Campaign entry details contain an invalid JSON number.")


def parse_details(kind, text):
    _text(text, "Campaign entry details", 300000)
    try:
        details = json.loads(text, object_pairs_hook=_unique_object,
                             parse_constant=_invalid_constant)
    except (TypeError, ValueError, RecursionError) as exc:
        raise ValueError("Campaign entry details contain invalid JSON.") from exc
    return validate_details(kind, details)


def details_json(kind, details):
    return json.dumps(validate_details(kind, details), ensure_ascii=False, sort_keys=True)


def _record_values(record):
    if not isinstance(record, WorldRecord) or type(record.archived) is not bool:
        raise ValueError("Choose a valid campaign entry with an archived checkbox value.")
    _identity(record.id, "Campaign entry ID")
    _identity(record.campaign_id, "Campaign ID")
    _kind(record.kind)
    if record.status not in STATUSES[record.kind]:
        raise ValueError("Choose a valid status for this entry type.")
    return (_text(record.name, "Entry name", 200, required=True), record.status,
            _text(record.summary, "Public summary", 20000),
            _text(record.dm_notes, "DM-only notes"),
            details_json(record.kind, record.details), int(record.archived))


class WorldRepository:
    """Campaign-owned world data, sharing the library's transactional database."""

    def __init__(self, database_path: str | Path):
        self.campaigns = CampaignRepository(database_path)
        self.library = self.campaigns.library
        self.path = self.library.path

    def _connection(self):
        return self.library._connection()

    @staticmethod
    def _require(db, table, identity, label):
        _identity(identity, label + " ID")
        row = db.execute(f"SELECT * FROM {table} WHERE id=?", (identity,)).fetchone()
        if row is None:
            raise ValueError(f"{label} no longer exists.")
        return row

    @staticmethod
    def _from_row(row):
        if row is None:
            return None
        values = {field.name: row[field.name] for field in fields(WorldRecord)}
        if values["archived"] not in (0, 1):
            raise ValueError("Stored campaign entry has an invalid archive value.")
        values["archived"] = bool(values["archived"])
        record = WorldRecord(**values)
        _record_values(record)
        return record

    @staticmethod
    def _check_references(db, campaign_id, kind, details):
        for field in DETAIL_FIELDS[kind]:
            if field.type == "creatures":
                for identity in details[field.key]:
                    WorldRepository._require(db, "creatures", identity, field.label + " library record")
            elif field.type == "location" and details[field.key]:
                location = WorldRepository._require(db, "world_records", details[field.key], field.label)
                if location["campaign_id"] != campaign_id or location["kind"] != "location":
                    raise ValueError(f"{field.label} must be a location in this campaign.")

    def create(self, campaign_id: str, kind: str, name: str, *, status=None,
               summary="", dm_notes="", details=None) -> WorldRecord:
        _kind(kind)
        candidate = WorldRecord(str(uuid4()), campaign_id, kind, name,
                                STATUSES[kind][0] if status is None else status,
                                summary, dm_notes, details_json(kind, {} if details is None else details))
        values = _record_values(candidate)
        with self._connection() as db:
            db.execute("BEGIN IMMEDIATE")
            self._require(db, "campaigns", campaign_id, "Campaign")
            self._check_references(db, campaign_id, kind, candidate.details)
            db.execute("INSERT INTO world_records(id,campaign_id,kind,name,status,summary,dm_notes,details_json,archived) "
                       "VALUES(?,?,?,?,?,?,?,?,?)", (candidate.id, campaign_id, kind, *values))
            row = self._require(db, "world_records", candidate.id, "Campaign entry")
        return self._from_row(row)

    def save(self, record: WorldRecord) -> WorldRecord:
        values = _record_values(record)
        with self._connection() as db:
            db.execute("BEGIN IMMEDIATE")
            current = self._require(db, "world_records", record.id, "Campaign entry")
            if current["campaign_id"] != record.campaign_id or current["kind"] != record.kind:
                raise ValueError("A saved entry cannot change its campaign or type.")
            self._require(db, "campaigns", record.campaign_id, "Campaign")
            self._check_references(db, record.campaign_id, record.kind, record.details)
            db.execute("UPDATE world_records SET name=?,status=?,summary=?,dm_notes=?,details_json=?,archived=?, "
                       "updated_at=CURRENT_TIMESTAMP WHERE id=?", (*values, record.id))
            row = self._require(db, "world_records", record.id, "Campaign entry")
        return self._from_row(row)

    def get(self, record_id: str) -> WorldRecord | None:
        _identity(record_id, "Campaign entry ID")
        with self._connection() as db:
            row = db.execute("SELECT * FROM world_records WHERE id=?", (record_id,)).fetchone()
        return self._from_row(row)

    def list(self, campaign_id: str, *, kind=None, status=None, query="",
             include_archived=False) -> list[WorldRecord]:
        if kind is not None:
            _kind(kind)
        if status is not None and (not isinstance(status, str) or status not in
                                   (STATUSES[kind] if kind else {s for values in STATUSES.values() for s in values})):
            raise ValueError("Choose a valid campaign entry status filter.")
        if type(include_archived) is not bool:
            raise ValueError("Include archived must be true or false.")
        query = _text(query, "Search", 500)
        clauses, parameters = ["campaign_id=?"], [campaign_id]
        if not include_archived:
            clauses.append("archived=0")
        if kind is not None:
            clauses.append("kind=?")
            parameters.append(kind)
        if status is not None:
            clauses.append("status=?")
            parameters.append(status)
        with self._connection() as db:
            self._require(db, "campaigns", campaign_id, "Campaign")
            rows = db.execute("SELECT * FROM world_records WHERE " + " AND ".join(clauses)
                              + " ORDER BY name COLLATE NOCASE,id", parameters).fetchall()
        records = [self._from_row(row) for row in rows]
        if query:
            # Search authored values, not JSON field names such as assigned_ids.
            # Casefold also makes non-ASCII names searchable without SQLite ICU.
            needle = query.casefold()
            records = [record for record in records if needle in "\n".join(
                [record.name, record.summary, record.dm_notes]
                + [" ".join(value) if isinstance(value, list) else str(value)
                   for value in record.details.values()]).casefold()]
        return records

    def set_archived(self, record_id: str, archived: bool) -> WorldRecord:
        if type(archived) is not bool:
            raise ValueError("Archived must be true or false.")
        with self._connection() as db:
            db.execute("BEGIN IMMEDIATE")
            self._from_row(self._require(db, "world_records", record_id, "Campaign entry"))
            db.execute("UPDATE world_records SET archived=?,updated_at=CURRENT_TIMESTAMP WHERE id=?",
                       (int(archived), record_id))
            row = self._require(db, "world_records", record_id, "Campaign entry")
        return self._from_row(row)

    def create_link(self, campaign_id: str, source_id: str, target_id: str,
                    relation: str, notes: str = "") -> WorldLink:
        relation = _text(relation, "Relationship", 120, required=True)
        notes = _text(notes, "Relationship DM notes", 20000)
        if source_id == target_id:
            raise ValueError("Choose two different campaign entries for a relationship.")
        identity = str(uuid4())
        with self._connection() as db:
            db.execute("BEGIN IMMEDIATE")
            self._require(db, "campaigns", campaign_id, "Campaign")
            for other_id in (source_id, target_id):
                other = self._require(db, "world_records", other_id, "Related campaign entry")
                if other["campaign_id"] != campaign_id:
                    raise ValueError("Relationships must stay within one campaign.")
            if db.execute("SELECT 1 FROM world_links WHERE campaign_id=? AND source_id=? "
                          "AND target_id=? AND relation=?", (campaign_id, source_id, target_id, relation)).fetchone():
                raise ValueError("This relationship is already recorded.")
            db.execute("INSERT INTO world_links(id,campaign_id,source_id,target_id,relation,notes) VALUES(?,?,?,?,?,?)",
                       (identity, campaign_id, source_id, target_id, relation, notes))
            row = self._require(db, "world_links", identity, "Relationship")
        return WorldLink(**dict(row))

    def list_links(self, campaign_id: str, record_id: str | None = None) -> list[WorldLink]:
        with self._connection() as db:
            self._require(db, "campaigns", campaign_id, "Campaign")
            parameters = [campaign_id]
            clause = "campaign_id=?"
            if record_id is not None:
                record = self._require(db, "world_records", record_id, "Campaign entry")
                if record["campaign_id"] != campaign_id:
                    raise ValueError("The selected entry belongs to another campaign.")
                clause += " AND (source_id=? OR target_id=?)"
                parameters.extend([record_id, record_id])
            rows = db.execute("SELECT * FROM world_links WHERE " + clause + " ORDER BY relation COLLATE NOCASE,id",
                              parameters).fetchall()
            for row in rows:
                for identity in (row["source_id"], row["target_id"]):
                    linked = self._require(db, "world_records", identity, "Related campaign entry")
                    if linked["campaign_id"] != campaign_id:
                        raise ValueError("A stored relationship crosses campaign boundaries. Review the database before editing.")
        return [WorldLink(**dict(row)) for row in rows]

    def delete_link(self, link_id: str, *, campaign_id: str) -> None:
        with self._connection() as db:
            db.execute("BEGIN IMMEDIATE")
            row = self._require(db, "world_links", link_id, "Relationship")
            if row["campaign_id"] != campaign_id:
                raise ValueError("The relationship belongs to another campaign.")
            db.execute("DELETE FROM world_links WHERE id=?", (link_id,))

    def player_handout(self, record_id: str) -> str:
        record = self.get(record_id)
        if record is None or record.kind != "handout":
            raise ValueError("Select a saved player handout.")
        # Deliberately do not fall back to a title, summary, or private notes.
        return record.details["player_text"]

    def export_player_handout(self, record_id: str, destination: str | Path) -> None:
        text = self.player_handout(record_id)
        if not text.strip():
            raise ValueError("Write player text before exporting this handout.")
        with self.library._output_path(destination) as staging:
            staging.write_text(text, encoding="utf-8")


def build_world_context(repository: WorldRepository, record_id: str, *, max_chars=6000) -> str:
    """Load one complete saved entry explicitly; related records are not implied."""
    if type(max_chars) is not int or max_chars < 1:
        raise ValueError("The Scribe context limit must be a positive whole number.")
    record = repository.get(record_id)
    if record is None:
        raise ValueError("The selected campaign entry no longer exists.")
    campaign = repository.campaigns.get_campaign(record.campaign_id)
    if campaign is None:
        raise ValueError("The selected entry's campaign no longer exists.")
    data = asdict(record)
    data["details"] = record.details
    del data["details_json"]
    links = [asdict(link) for link in repository.list_links(record.campaign_id, record.id)]
    context = (
        "D&D 3.5 SELECTED CAMPAIGN WORLD ENTRY / DM CONTEXT\n"
        "This is one explicitly selected saved entry. Related entry and creature IDs are references; "
        "their records are not loaded. Do not invent their details. Entries can describe plans, "
        "possibilities, or recorded outcomes; do not infer played events, rewards awarded, dice "
        "results, or character changes. Keep DM-only notes and relationship notes out of player narration.\n"
        f"Campaign: {campaign.name}\n"
        "COMPLETE SELECTED ENTRY (dm_notes and typed details may contain secrets)\n"
        + json.dumps(data, ensure_ascii=False, sort_keys=True)
        + "\nRELATIONSHIPS / DM-ONLY NOTES\n"
        + json.dumps(links, ensure_ascii=False, sort_keys=True)
    )
    if len(context) > max_chars:
        raise ValueError(f"Complete selected entry context needs {len(context):,} characters; "
                         f"the Scribe limit is {max_chars:,}. No saved data was shortened or changed.")
    return context
