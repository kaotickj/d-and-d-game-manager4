"""Portable campaign backups, restored to a new folder before activation.

All SQLite connections are short-lived. A restore never replaces a running
library: the validated copy is selected for the next application launch.
"""
from __future__ import annotations

from contextlib import closing
from datetime import datetime, timezone
from hashlib import sha256
import json
import os
from pathlib import Path, PurePosixPath
import sqlite3
import tempfile
import zipfile

from .storage import CreatureRepository, SCHEMA_VERSION

FORMAT = "dndgm4-backup"
VERSION = 1
MAX_TOTAL = 300 * 1024 * 1024
MAX_FILES = 5000
FIXED_FILES = {"library.sqlite3", "rules.sqlite3", "current_scene.json", "battle_trakker.json",
               "srd35_spells.json"}


def _check_name(name: str) -> None:
    path = PurePosixPath(name)
    reserved = {"con", "prn", "aux", "nul", *(f"com{i}" for i in range(1,10)),
                *(f"lpt{i}" for i in range(1,10))}
    if (not name or "\\" in name or path.is_absolute() or
            any(part in (".", "..") or ":" in part for part in name.split("/")) or
            "//" in name or name.endswith("/") or
            any(part.endswith((".", " ")) or part.split(".")[0].casefold() in reserved or
                any(char in part for char in '<>"|?*') for part in path.parts)):
        raise ValueError("Backup contains an unsafe file path.")
    if name not in FIXED_FILES and not (name.startswith("assets/") and len(path.parts) > 1):
        raise ValueError(f"Unsupported backup file: {name}")


def _check_database(path: Path, *, library: bool = False) -> None:
    with closing(sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)) as db:
        if db.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            raise ValueError("Backup database failed its integrity check.")
        if library:
            version = db.execute("PRAGMA user_version").fetchone()[0]
            if not 1 <= version <= SCHEMA_VERSION:
                raise ValueError(f"Unsupported library schema {version}; this app supports up to {SCHEMA_VERSION}.")
            if db.execute("PRAGMA foreign_key_check").fetchone() is not None:
                raise ValueError("Backup has broken database references.")
            db.execute("SELECT id, name, kind FROM creatures LIMIT 1")


def _snapshot(source: Path, destination: Path) -> None:
    with closing(sqlite3.connect(source.as_uri() + "?mode=ro", uri=True)) as db:
        with closing(sqlite3.connect(destination)) as target:
            db.backup(target)


def _validate_state(folder: Path) -> None:
    from .scene_context import SceneStore
    from .battle_advanced import AdvancedBattleStore
    _check_database(folder / "library.sqlite3", library=True)
    # Migrate only this staged copy. The live data and the archive are untouched.
    library = CreatureRepository(folder / "library.sqlite3")
    _check_database(folder / "library.sqlite3", library=True)
    from .storage import validate
    from .campaigns import CampaignRepository
    from .world import WorldRepository
    from .maps import MapRepository
    for record in library.list(include_archived=True):
        validate(record)
    campaigns = CampaignRepository(library.path)
    world = WorldRepository(library.path)
    maps = MapRepository(library)
    for campaign in campaigns.list_campaigns(include_archived=True):
        world.list(campaign.id, include_archived=True)
        for record in maps.list(campaign.id):
            # Decode the managed image and check its saved dimensions. Stale
            # encounter links remain intact for the DM to repair after recovery.
            maps.load_image(record)
        for session in campaigns.list_sessions(campaign.id):
            campaigns.load_scene(session.id)
            for encounter in campaigns.list_encounters(session.id):
                campaigns.load_battle(encounter.id)
    from .campaign_time import validate_saved_state as validate_time_state
    from .resources import validate_saved_state as validate_resource_state
    from .handouts import validate_saved_state as validate_handout_state
    validate_time_state(library.path)
    validate_resource_state(library.path)
    validate_handout_state(library.path)
    if (folder / "rules.sqlite3").exists():
        _check_database(folder / "rules.sqlite3")
    if (folder / "srd35_spells.json").exists():
        from .srd35_spells import SpellCatalog
        SpellCatalog(library.path)
    SceneStore(folder / "library.sqlite3").load()
    AdvancedBattleStore(folder / "library.sqlite3").load()


def create_backup(library: CreatureRepository, destination: str | Path) -> dict:
    """Snapshot library, standalone state, rule references and managed assets."""
    target = Path(destination).resolve()
    sources = {"library.sqlite3": library.path.resolve()}
    for name in FIXED_FILES - {"library.sqlite3"}:
        candidate = library.path.with_name(name)
        if candidate.exists():
            if candidate.is_symlink() or not candidate.is_file():
                raise ValueError(f"Backup source must be a regular file: {name}")
            sources[name] = candidate.resolve()
    asset_root = library.path.parent / "assets"
    if asset_root.exists():
        if asset_root.is_symlink() or not asset_root.is_dir():
            raise ValueError("Managed assets must be a regular directory.")
        for candidate in asset_root.rglob("*"):
            if candidate.is_symlink():
                raise ValueError("Managed assets cannot contain symbolic links.")
            if candidate.is_file():
                sources[candidate.relative_to(library.path.parent).as_posix()] = candidate.resolve()
    if len(sources) > MAX_FILES:
        raise ValueError("Too many files for one backup.")
    if any(target == source or (target.exists() and os.path.samefile(target, source)) for source in sources.values()):
        raise ValueError("Choose a backup destination outside the saved state files.")
    if asset_root.resolve() in target.parents:
        raise ValueError("Save the backup outside managed assets.")
    with tempfile.TemporaryDirectory(prefix=".dndgm4-backup-", dir=target.parent) as temporary:
        stage = Path(temporary)
        payload = stage / "payload"
        payload.mkdir()
        copied_size = 0
        manifest = {"format": FORMAT, "version": VERSION,
                    "created_at": datetime.now(timezone.utc).isoformat(),
                    "schema_version": SCHEMA_VERSION, "files": {}}
        for name, source in sorted(sources.items()):
            _check_name(name)
            output = payload / name
            output.parent.mkdir(parents=True, exist_ok=True)
            if name.endswith(".sqlite3"):
                _snapshot(source, output)
            else:
                size = source.stat().st_size
                if size + copied_size > MAX_TOTAL:
                    raise ValueError("Backup exceeds the 300 MB limit.")
                output.write_bytes(source.read_bytes())
            copied_size += output.stat().st_size
            if copied_size > MAX_TOTAL:
                raise ValueError("Backup exceeds the 300 MB limit.")
        _validate_state(payload)
        # Validation can migrate the staged library. Bind the manifest and
        # final size limit to those resulting bytes, never the pre-migration copy.
        total = 0
        for name in sorted(sources):
            data = (payload / name).read_bytes()
            total += len(data)
            if total > MAX_TOTAL:
                raise ValueError("Backup exceeds the 300 MB limit.")
            manifest["files"][name] = {"size": len(data), "sha256": sha256(data).hexdigest()}
        archive_path = stage / "backup.zip"
        with zipfile.ZipFile(archive_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2))
            for name in manifest["files"]:
                archive.write(payload / name, name)
        os.replace(archive_path, target)
    return manifest


def _read_manifest(archive: zipfile.ZipFile) -> dict:
    entries = archive.infolist()
    names = [entry.filename for entry in entries]
    if len(names) > MAX_FILES + 1 or len({name.casefold() for name in names}) != len(names):
        raise ValueError("Backup contains too many files or duplicate names.")
    if "manifest.json" not in names or archive.getinfo("manifest.json").file_size > 1024 * 1024:
        raise ValueError("Missing or oversized backup manifest.")
    try:
        manifest = json.loads(archive.read("manifest.json"))
    except (ValueError, UnicodeError) as exc:
        raise ValueError("Backup manifest is unreadable.") from exc
    if (not isinstance(manifest, dict) or manifest.get("format") != FORMAT or
            type(manifest.get("version")) is not int or manifest["version"] != VERSION or
            type(manifest.get("schema_version")) is not int or
            not 1 <= manifest["schema_version"] <= SCHEMA_VERSION):
        raise ValueError("Unsupported backup format or newer application schema.")
    created_at = manifest.get("created_at")
    if not isinstance(created_at, str) or len(created_at) > 128:
        raise ValueError("Invalid backup creation date.")
    try:
        datetime.fromisoformat(created_at)
    except ValueError as exc:
        raise ValueError("Invalid backup creation date.") from exc
    files = manifest.get("files")
    if not isinstance(files, dict) or "library.sqlite3" not in files or set(names) != {"manifest.json", *files}:
        raise ValueError("Backup files do not match its manifest.")
    total = 0
    for name, metadata in files.items():
        _check_name(name)
        if (not isinstance(metadata, dict) or type(metadata.get("size")) is not int or
                not 0 <= metadata["size"] <= MAX_TOTAL or not isinstance(metadata.get("sha256"), str)):
            raise ValueError("Invalid backup file metadata.")
        entry = archive.getinfo(name)
        if entry.file_size != metadata["size"] or entry.flag_bits & 1 or (entry.external_attr >> 16) & 0o170000 == 0o120000:
            raise ValueError("Unsupported or mismatched backup entry.")
        total += entry.file_size
    if total > MAX_TOTAL:
        raise ValueError("Backup exceeds the 300 MB limit.")
    return manifest


def inspect_backup(source: str | Path) -> dict:
    """Read bounded manifest metadata for a restore preview."""
    try:
        with zipfile.ZipFile(source) as archive:
            return _read_manifest(archive)
    except (zipfile.BadZipFile, RuntimeError, KeyError) as exc:
        raise ValueError("Backup archive is unreadable.") from exc


def restore_backup(source: str | Path, destination_folder: str | Path) -> Path:
    """Validate all data, then atomically publish a new recovery folder."""
    target = Path(destination_folder).absolute()
    if target.exists():
        raise ValueError("Restore requires a new folder; existing saved games are never replaced.")
    try:
        with zipfile.ZipFile(source) as archive:
            manifest = _read_manifest(archive)
            with tempfile.TemporaryDirectory(prefix=".dndgm4-restore-", dir=target.parent) as temporary:
                stage = Path(temporary) / "recovered"
                stage.mkdir()
                for name, metadata in manifest["files"].items():
                    data = archive.read(name)
                    if len(data) != metadata["size"] or sha256(data).hexdigest() != metadata["sha256"]:
                        raise ValueError(f"Backup checksum failed: {name}")
                    output = stage / name
                    output.parent.mkdir(parents=True, exist_ok=True)
                    output.write_bytes(data)
                _validate_state(stage)
                # rename fails if another operation has populated this path.
                os.rename(stage, target)
    except (zipfile.BadZipFile, RuntimeError, KeyError, sqlite3.DatabaseError) as exc:
        raise ValueError(f"Backup could not be restored: {exc}") from exc
    return target / "library.sqlite3"
