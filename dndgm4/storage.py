"""SQLite library storage, independent of the GUI."""
from __future__ import annotations

import os
import sqlite3
import sys
from contextlib import contextmanager
from dataclasses import fields
from pathlib import Path
from typing import Iterator
from uuid import uuid4

from .models import Creature, KINDS

SCHEMA_VERSION = 1
WRITE_COLUMNS = (
    "name", "kind", "race_type", "character_class", "level",
    "challenge_rating", "armor_class", "max_hit_points",
    "strength", "dexterity", "constitution", "intelligence",
    "wisdom", "charisma", "notes", "archived",
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
    for attr in ("strength", "dexterity", "constitution",
                 "intelligence", "wisdom", "charisma"):
        if not 0 <= getattr(creature, attr) <= 99:
            raise ValueError(f"{attr.title()} must be between 0 and 99.")


class CreatureRepository:
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
                        archived INTEGER NOT NULL DEFAULT 0 CHECK(archived IN (0,1)),
                        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                        updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                    );
                    CREATE INDEX IF NOT EXISTS idx_creatures_kind_name
                        ON creatures(kind, name COLLATE NOCASE);
                    CREATE INDEX IF NOT EXISTS idx_creatures_archived
                        ON creatures(archived);
                    PRAGMA user_version = 1;
                """)

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
        values[-1] = int(creature.archived)
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
