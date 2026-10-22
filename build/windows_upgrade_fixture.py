"""Seed/check isolated pre-upgrade data; never open the normal user library.

Usage: python build/windows_upgrade_fixture.py seed|check ROOT REPORT
ROOT is the test process's LOCALAPPDATA. REPORT must be outside ROOT.
The check path uses only read-only SQLite and never performs migrations.
"""
from __future__ import annotations

import argparse
from contextlib import closing
from hashlib import sha256
import json
from pathlib import Path
import sqlite3
import struct
import sys
import zlib

FORMAT = "dndgm4-windows-upgrade-fixture"
CORE_TABLES = ("creatures", "campaigns", "campaign_members", "sessions", "encounters", "workspace")
LIBRARY = "DnDGameManager4/library.sqlite3"
MAX_BYTES = 8 * 1024 * 1024
MAX_FILES = 32


def _snapshot(root: Path) -> dict:
    if not root.is_dir() or root.is_symlink():
        raise ValueError("The isolated fixture ROOT is missing or is a symbolic link.")
    data_root = root / "DnDGameManager4"
    if not data_root.is_dir() or data_root.is_symlink():
        raise ValueError("The isolated DnDGameManager4 data directory is missing or is a symbolic link.")
    files, total = {}, 0
    for path in sorted(data_root.rglob("*")):
        if path.is_symlink():
            raise ValueError(f"Unexpected symbolic link: {path}")
        if path.is_dir():
            continue
        if not path.is_file():
            raise ValueError(f"Unexpected fixture entry: {path}")
        total += path.stat().st_size
        if total > MAX_BYTES or len(files) >= MAX_FILES:
            raise ValueError("Fixture exceeds its bounded file/size limit.")
        payload = path.read_bytes()
        files[path.relative_to(root).as_posix()] = {"size": len(payload), "sha256": sha256(payload).hexdigest()}
    database = root / LIBRARY
    if LIBRARY not in files:
        raise ValueError("Fixture library.sqlite3 is missing.")
    # immutable prevents SQLite from creating journals/sidecars during checks.
    with closing(sqlite3.connect(database.as_uri() + "?mode=ro&immutable=1", uri=True)) as db:
        db.row_factory = sqlite3.Row
        version = db.execute("PRAGMA user_version").fetchone()[0]
        if version != 3:
            raise ValueError(f"Fixture schema changed: expected 3, found {version}.")
        if db.execute("PRAGMA integrity_check").fetchone()[0] != "ok" or db.execute("PRAGMA foreign_key_check").fetchone():
            raise ValueError("Fixture database integrity/references failed.")
        tables = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")}
        if tables != set(CORE_TABLES):
            raise ValueError("Fixture core schema-3 tables changed.")
        records = {table: [dict(row) for row in db.execute(f"SELECT * FROM {table} ORDER BY rowid")]
                   for table in CORE_TABLES}
        if any(not rows for rows in records.values()):
            raise ValueError("Fixture campaign, party, session, encounter, or workspace is missing.")
    return {"schema_version": version, "files": files, "records": records}


def seed(root: Path, report: Path) -> dict:
    if root.exists() or root.is_symlink():
        raise ValueError("Seed refuses an existing ROOT; choose a new isolated directory.")
    if report.exists() or report.is_symlink():
        raise ValueError("Seed refuses an existing REPORT; preserve the original baseline.")
    if report == root or root in report.parents:
        raise ValueError("REPORT must be outside the isolated ROOT.")
    # These core domain modules use the standard library only: no Qt, inference,
    # network, global settings, or default-user paths are loaded.
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from dndgm4.battle_rules import fighter_from_record
    from dndgm4.campaigns import CampaignRepository
    from dndgm4.models import Creature
    from dndgm4.scene_context import SceneStore, blank_scene
    from dndgm4.storage import CreatureRepository, SCHEMA_VERSION

    root.mkdir(parents=True, exist_ok=False)
    library = CreatureRepository(root / LIBRARY)
    hero = library.save(Creature(name="Upgrade sentinel", level=3, max_hit_points=24,
        notes="Keep this pre-install character and its campaign exactly as saved."))
    campaigns = CampaignRepository(library.path)
    campaign = campaigns.create_campaign("Installer preservation campaign", notes="Private fixture notes")
    campaigns.set_party(campaign.id, [hero.id])
    session = campaigns.create_session(campaign.id, "Before the upgrade", "2026-10-22")
    scene = blank_scene()
    scene.update(title="The old watchtower", location="Ash Coast", record_ids=[hero.id])
    campaigns.save_scene(session.id, scene)
    encounter = campaigns.create_encounter(session.id, "Saved watchtower encounter")
    battle = campaigns.load_battle(encounter.id)
    battle.add(fighter_from_record(hero))
    campaigns.save_battle(encounter.id, battle)
    campaigns.activate(campaign.id, session.id, encounter.id)
    SceneStore(library.path).save(scene)
    asset = library.path.parent / "assets" / "installer-fixture.png"
    asset.parent.mkdir()
    def png_chunk(kind, payload):
        return struct.pack(">I", len(payload)) + kind + payload + struct.pack(">I", zlib.crc32(kind + payload))
    asset.write_bytes(b"\x89PNG\r\n\x1a\n" +
        png_chunk(b"IHDR", struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0)) +
        png_chunk(b"IDAT", zlib.compress(b"\0\x44\x55\x66")) + png_chunk(b"IEND", b""))
    # Retain genuine core records/DDL, removing later optional domain tables.
    with closing(sqlite3.connect(library.path)) as db:
        db.execute("PRAGMA foreign_keys=OFF")
        tables = [row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")]
        for table in tables:
            if table not in CORE_TABLES:
                db.execute('DROP TABLE "' + table.replace('"', '""') + '"')
        db.execute("PRAGMA user_version=3")
        db.commit()
    baseline = {"format": FORMAT, "version": 1, "root": str(root),
                "created_by_app_schema": SCHEMA_VERSION,
                "ids": {"hero": hero.id, "campaign": campaign.id, "session": session.id, "encounter": encounter.id},
                **_snapshot(root)}
    report.parent.mkdir(parents=True, exist_ok=True)
    with report.open("x", encoding="utf-8") as stream:
        json.dump(baseline, stream, indent=2, ensure_ascii=False)
        stream.write("\n")
    return baseline


def check(root: Path, report: Path) -> dict:
    if not report.is_file() or report.stat().st_size > MAX_BYTES:
        raise ValueError("Fixture REPORT is missing or too large.")
    baseline = json.loads(report.read_text(encoding="utf-8"))
    if (not isinstance(baseline, dict) or baseline.get("format") != FORMAT or baseline.get("version") != 1
            or baseline.get("root") != str(root) or baseline.get("schema_version") != 3):
        raise ValueError("REPORT does not describe this isolated schema-3 ROOT.")
    actual = _snapshot(root)
    expected_files = baseline.get("files", {})
    if not isinstance(expected_files, dict):
        raise ValueError("REPORT has invalid file metadata.")
    for name in sorted(set(expected_files) | set(actual["files"])):
        if expected_files.get(name) != actual["files"].get(name):
            raise ValueError(f"Installer changed, removed, or added fixture file: {name}")
    if actual["records"] != baseline.get("records"):
        raise ValueError("Installer changed the original saved campaign records.")
    return baseline


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("seed", "check"))
    parser.add_argument("root", type=Path)
    parser.add_argument("report", type=Path)
    args = parser.parse_args(argv)
    try:
        baseline = (seed if args.action == "seed" else check)(args.root.resolve(), args.report.resolve())
    except (OSError, ValueError, sqlite3.Error, KeyError, TypeError) as exc:
        print(f"Upgrade fixture {args.action} FAILED: {exc}", file=sys.stderr)
        return 1
    print(json.dumps({"status": "passed", "action": args.action, "schema_version": 3,
                      "files": len(baseline["files"]), "root": baseline["root"]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
