"""SQLite library storage, independent of the GUI."""
from __future__ import annotations

import os
import json
import sqlite3
import sys
import tempfile
from contextlib import contextmanager
from dataclasses import asdict, fields, replace
from pathlib import Path
from typing import TYPE_CHECKING, Iterable, Iterator
from uuid import uuid4

from .models import Creature, KINDS

if TYPE_CHECKING:
    from .library_transfer import ImportSummary

SCHEMA_VERSION = 2
WRITE_COLUMNS = (
    "name", "kind", "race_type", "character_class", "level",
    "challenge_rating", "armor_class", "max_hit_points",
    "strength", "dexterity", "constitution", "intelligence",
    "wisdom", "charisma", "notes", "archived", "sheet_json",
)


def default_database_path() -> Path:
    if sys.platform == "win32":
        root = Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local")
    elif sys.platform == "darwin":
        root = Path.home() / "Library" / "Application Support"
    else:
        root = Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share")
    return root / "DnDGameManager4" / "library.sqlite3"


def validate(creature: Creature) -> None:
    if creature.kind not in KINDS:
        raise ValueError("Record type must be PC, NPC, or monster.")
    if not creature.name.strip():
        raise ValueError("A name is required.")
    if len(creature.name.strip()) > 200:
        raise ValueError("The name must not exceed 200 characters.")
    if not 0 <= creature.level <= 99:
        raise ValueError("Level must be between 0 and 99.")
    if not 0 <= creature.armor_class <= 999:
        raise ValueError("Armor class must be between 0 and 999.")
    if not 0 <= creature.max_hit_points <= 999999:
        raise ValueError("Maximum hit points must be between 0 and 999999.")
    if len(creature.sheet_json) > 262144:
        raise ValueError("Character sheet exceeds the maximum size.")
    if creature.sheet_json:
        import json
        try:
            sheet = json.loads(creature.sheet_json)
        except (ValueError, TypeError) as exc:
            raise ValueError("Character sheet must contain valid JSON.") from exc
        if not isinstance(sheet, dict):
            raise ValueError("Character sheet must be an object.")
    for attr in ("strength", "dexterity", "constitution",
                 "intelligence", "wisdom", "charisma"):
        if not 0 <= getattr(creature, attr) <= 99:
            raise ValueError(f"{attr.title()} must be between 0 and 99.")


class CreatureRepository:
    @contextmanager
    def _output_path(self, destination: str | Path) -> Iterator[Path]:
        """Publish complete files atomically; never replace the live database."""
        target = Path(destination).resolve()
        if target == self.path.resolve() or (
            target.exists() and os.path.samefile(target, self.path)
        ):
            raise ValueError("Choose a destination other than the live library.")
        descriptor, temporary = tempfile.mkstemp(dir=target.parent, prefix=".dndgm4-")
        os.close(descriptor)
        staging = Path(temporary)
        try:
            yield staging
            os.replace(staging, target)
        finally:
            staging.unlink(missing_ok=True)

    def backup(self, destination: str | Path) -> None:
        """Snapshot the SQLite library, including committed WAL transactions."""
        with self._output_path(destination) as staging:
            with self._connection() as source:
                target = sqlite3.connect(staging)
                try:
                    source.backup(target)
                finally:
                    target.close()

    def export_json(self, destination: str | Path) -> int:
        """Export every permanent record, including archives and character sheets."""
        records = self.list(include_archived=True)
        payload = {"format": "dndgm4-library", "version": 1,
                   "creatures": [asdict(record) for record in records]}
        with self._output_path(destination) as staging:
            staging.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
                               encoding="utf-8")
        return len(records)

    def preview_import(self, records: Iterable[Creature], *,
                       duplicates: str = "skip") -> ImportSummary:
        from .library_transfer import summarize_import, validate_import_records
        batch = validate_import_records(records)
        with self._connection() as db:
            existing = {row[0] for row in db.execute("SELECT id FROM creatures")}
        return summarize_import(batch, existing, duplicates)

    def import_records(self, records: Iterable[Creature], *,
                       duplicates: str = "skip") -> ImportSummary:
        """Commit the validated batch together, using IDs to resolve collisions.

        A write lock covers both conflict detection and insertion. Any validation
        or database error leaves all existing records unchanged.
        """
        from .library_transfer import summarize_import, validate_import_records
        batch = validate_import_records(records)
        columns = ("id",) + WRITE_COLUMNS + ("created_at", "updated_at")
        placeholders = ",".join(["?"] * (1 + len(WRITE_COLUMNS)) + [
            "COALESCE(NULLIF(?, ''), CURRENT_TIMESTAMP)",
            "COALESCE(NULLIF(?, ''), CURRENT_TIMESTAMP)"])
        set_clause = ", ".join(f"{column} = excluded.{column}" for column in WRITE_COLUMNS)
        sql = (f"INSERT INTO creatures ({','.join(columns)}) VALUES ({placeholders}) "
               f"ON CONFLICT(id) DO UPDATE SET {set_clause}, updated_at = CURRENT_TIMESTAMP")
        with self._connection() as db:
            db.execute("BEGIN IMMEDIATE")
            existing = {row[0] for row in db.execute("SELECT id FROM creatures")}
            summary = summarize_import(batch, existing, duplicates)
            reserved = existing | {record.id for record in batch}
            for record in batch:
                if record.id in existing:
                    if duplicates == "skip":
                        continue
                    if duplicates == "copy":
                        new_id = str(uuid4())
                        while new_id in reserved:
                            new_id = str(uuid4())
                        reserved.add(new_id)
                        record = replace(record, id=new_id, created_at="", updated_at="")
                values = [getattr(record, column) for column in columns]
                values[columns.index("archived")] = int(record.archived)
                db.execute(sql, values)
        return summary

    def __init__(self, database_path: str | Path):
        self.path = Path(database_path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    @contextmanager
    def _connection(self) -> Iterator[sqlite3.Connection]:
        db = sqlite3.connect(self.path)
        db.row_factory = sqlite3.Row
        try:
            db.execute("PRAGMA foreign_keys = ON")
            yield db
            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    def _initialize(self) -> None:
        with self._connection() as db:
            version = db.execute("PRAGMA user_version").fetchone()[0]
            if version > SCHEMA_VERSION:
                raise RuntimeError(
                    f"Database version {version} is newer than this app "
                    f"(supports up to {SCHEMA_VERSION})."
                )
            if version == 0:
                db.executescript("""
                    CREATE TABLE IF NOT EXISTS creatures (
                        id TEXT PRIMARY KEY,
                        name TEXT NOT NULL,
                        kind TEXT NOT NULL CHECK(kind IN ('pc','npc','monster')),
                        race_type TEXT NOT NULL DEFAULT '',
                        character_class TEXT NOT NULL DEFAULT '',
                        level INTEGER NOT NULL DEFAULT 1,
                        challenge_rating TEXT NOT NULL DEFAULT '',
                        armor_class INTEGER NOT NULL DEFAULT 10,
                        max_hit_points INTEGER NOT NULL DEFAULT 1,
                        strength INTEGER NOT NULL DEFAULT 10,
                        dexterity INTEGER NOT NULL DEFAULT 10,
                        constitution INTEGER NOT NULL DEFAULT 10,
                        intelligence INTEGER NOT NULL DEFAULT 10,
                        wisdom INTEGER NOT NULL DEFAULT 10,
                        charisma INTEGER NOT NULL DEFAULT 10,
                        notes TEXT NOT NULL DEFAULT '',
                        sheet_json TEXT NOT NULL DEFAULT '',
                        archived INTEGER NOT NULL DEFAULT 0 CHECK(archived IN (0,1)),
                        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                        updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                    );
                    CREATE INDEX IF NOT EXISTS idx_creatures_kind_name
                        ON creatures(kind, name COLLATE NOCASE);
                    CREATE INDEX IF NOT EXISTS idx_creatures_archived
                        ON creatures(archived);
                    PRAGMA user_version = 2;
                """)
            elif version == 1:
                db.execute("ALTER TABLE creatures ADD COLUMN sheet_json TEXT NOT NULL DEFAULT ''")
                db.execute("PRAGMA user_version = 2")

    @staticmethod
    def _from_row(row: sqlite3.Row) -> Creature:
        values = {field.name: row[field.name] for field in fields(Creature)}
        values["archived"] = bool(values["archived"])
        return Creature(**values)

    def get(self, record_id: str) -> Creature | None:
        with self._connection() as db:
            row = db.execute(
                "SELECT * FROM creatures WHERE id = ?", (record_id,)
            ).fetchone()
        return self._from_row(row) if row else None

    def list(self, *, kind: str | None = None, query: str = "",
             include_archived: bool = False) -> list[Creature]:
        if kind is not None and kind not in KINDS:
            raise ValueError("Invalid kind filter.")
        clauses: list[str] = []
        args: list[str] = []
        if not include_archived:
            clauses.append("archived = 0")
        if kind is not None:
            clauses.append("kind = ?")
            args.append(kind)
        if query.strip():
            clauses.append(
                "(instr(lower(name), lower(?)) > 0 OR "
                "instr(lower(race_type), lower(?)) > 0 OR "
                "instr(lower(character_class), lower(?)) > 0 OR "
                "instr(lower(notes), lower(?)) > 0)"
            )
            args.extend([query.strip()] * 4)
        where = " WHERE " + " AND ".join(clauses) if clauses else ""
        with self._connection() as db:
            rows = db.execute(
                f"SELECT * FROM creatures{where} ORDER BY name COLLATE NOCASE, id",
                args,
            ).fetchall()
        return [self._from_row(row) for row in rows]

    def save(self, creature: Creature) -> Creature:
        validate(creature)
        record_id = creature.id or str(uuid4())
        values = [getattr(creature, column) for column in WRITE_COLUMNS]
        values[WRITE_COLUMNS.index("archived")] = int(creature.archived)
        columns = ("id",) + WRITE_COLUMNS
        placeholders = ",".join("?" for _ in columns)
        set_clause = ", ".join(
            f"{column} = excluded.{column}" for column in WRITE_COLUMNS
        )
        with self._connection() as db:
            db.execute(
                f"INSERT INTO creatures ({','.join(columns)}) "
                f"VALUES ({placeholders}) "
                f"ON CONFLICT(id) DO UPDATE SET {set_clause}, "
                "updated_at = CURRENT_TIMESTAMP",
                [record_id, *values],
            )
            row = db.execute(
                "SELECT * FROM creatures WHERE id = ?", (record_id,)
            ).fetchone()
        assert row is not None
        return self._from_row(row)

    def set_archived(self, record_id: str, archived: bool) -> bool:
        with self._connection() as db:
            cursor = db.execute(
                "UPDATE creatures SET archived = ?, "
                "updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                (int(archived), record_id),
            )
            return cursor.rowcount > 0
