"""Managed handout illustrations and an allowlisted public export snapshot."""
from __future__ import annotations

from contextlib import closing
from dataclasses import dataclass
from hashlib import sha256
import os
from pathlib import Path, PurePosixPath
import re
import sqlite3
from uuid import UUID, uuid4
import zipfile

from .world import WorldRepository

MAX_IMAGE_BYTES = 25 * 1024 * 1024
MAX_IMAGE_EDGE = 8192
MAX_IMAGE_PIXELS = 16_000_000
SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS handout_assets (
    id TEXT PRIMARY KEY,
    campaign_id TEXT NOT NULL REFERENCES campaigns(id),
    handout_id TEXT NOT NULL REFERENCES world_records(id),
    image_path TEXT NOT NULL,
    width INTEGER NOT NULL CHECK(width > 0),
    height INTEGER NOT NULL CHECK(height > 0),
    sha256 TEXT NOT NULL,
    selected INTEGER NOT NULL DEFAULT 0 CHECK(selected IN (0,1)),
    archived INTEGER NOT NULL DEFAULT 0 CHECK(archived IN (0,1)),
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CHECK(NOT(selected=1 AND archived=1))
);
CREATE INDEX IF NOT EXISTS handout_assets_campaign ON handout_assets(campaign_id,handout_id);
CREATE UNIQUE INDEX IF NOT EXISTS handout_one_selected_image ON handout_assets(handout_id) WHERE selected=1;
"""


def ensure_schema(db):
    """Add tables inside the central migration's transaction, without versioning."""
    for statement in SCHEMA_SQL.split(";"):
        if statement.strip():
            db.execute(statement)


def _text(value, label, maximum=200, *, required=True):
    if not isinstance(value, str) or len(value) > maximum or "\x00" in value:
        raise ValueError(f"{label} must be text of at most {maximum:,} characters.")
    try:
        value.encode("utf-8")
    except UnicodeError as exc:
        raise ValueError(f"{label} contains invalid Unicode.") from exc
    if required and not value.strip():
        raise ValueError(f"{label} is required.")
    return value


def _dimensions(width, height):
    if (type(width) is not int or type(height) is not int
            or not 1 <= width <= MAX_IMAGE_EDGE or not 1 <= height <= MAX_IMAGE_EDGE
            or width * height > MAX_IMAGE_PIXELS):
        raise ValueError("Handout images must be at most 8,192 pixels per edge and 16 million pixels total.")


def sanitize_image(payload: bytes) -> tuple[bytes, int, int]:
    """Decode one raster frame and paint it into fresh, metadata-free PNG data."""
    from PyQt6.QtCore import QByteArray, QBuffer, QIODevice, QPoint, Qt
    from PyQt6.QtGui import QImage, QImageReader, QImageWriter, QPainter
    if not isinstance(payload, bytes) or not 0 < len(payload) <= MAX_IMAGE_BYTES:
        raise ValueError("Choose an image no larger than 25 MB.")
    source = QBuffer()
    source.setData(QByteArray(payload))
    source.open(QIODevice.OpenModeFlag.ReadOnly)
    reader = QImageReader(source)
    reader.setAutoTransform(True)
    if not reader.canRead() or bytes(reader.format()).lower() not in (b"png", b"jpeg", b"jpg", b"webp"):
        raise ValueError("Choose a readable PNG, JPEG, or WebP handout image.")
    size = reader.size()
    _dimensions(size.width(), size.height())
    image = reader.read()
    if image.isNull():
        raise ValueError("The handout image could not be decoded.")
    _dimensions(image.width(), image.height())
    # QImage.copy() retains image text/profile metadata. Painting into an empty
    # image deliberately retains only raster pixels, including transparency.
    fresh = QImage(image.width(), image.height(), QImage.Format.Format_ARGB32)
    if fresh.isNull():
        raise ValueError("The handout image is too large to prepare.")
    fresh.fill(Qt.GlobalColor.transparent)
    painter = QPainter(fresh)
    if not painter.isActive():
        raise ValueError("The handout image could not be prepared.")
    painter.drawImage(QPoint(0, 0), image)
    painter.end()
    output = QByteArray()
    sink = QBuffer(output)
    sink.open(QIODevice.OpenModeFlag.WriteOnly)
    writer = QImageWriter(sink, b"png")
    if not writer.write(fresh):
        raise ValueError("The sanitized handout image could not be encoded.")
    clean = bytes(output)
    if len(clean) > MAX_IMAGE_BYTES:
        raise ValueError("The sanitized PNG exceeds 25 MB; resize the source image before importing it.")
    return clean, fresh.width(), fresh.height()


@dataclass(frozen=True, slots=True)
class HandoutAsset:
    id: str
    campaign_id: str
    handout_id: str
    image_path: str
    width: int
    height: int
    sha256: str
    selected: bool
    archived: bool
    created_at: str


@dataclass(frozen=True, slots=True)
class PublicHandout:
    """This object is the complete player payload; private identifiers stay out."""
    text: str
    image_png: bytes | None = None


def _asset(row):
    if row is None:
        raise ValueError("The image was not found for this handout in this campaign.")
    identity = _text(row["id"], "Saved image ID")
    try:
        if str(UUID(identity)) != identity:
            raise ValueError("Noncanonical image ID.")
    except (ValueError, AttributeError) as exc:
        raise ValueError("The saved handout image ID is invalid.") from exc
    _text(row["campaign_id"], "Saved campaign ID")
    _text(row["handout_id"], "Saved handout ID")
    _dimensions(row["width"], row["height"])
    if type(row["selected"]) is not int or row["selected"] not in (0, 1) or type(row["archived"]) is not int or row["archived"] not in (0, 1) or (row["selected"] and row["archived"]):
        raise ValueError("The saved handout image selection/archive flags are invalid.")
    if not isinstance(row["sha256"], str) or not re.fullmatch("[0-9a-f]{64}", row["sha256"]):
        raise ValueError("The saved handout image checksum is invalid.")
    expected = f"assets/handouts/{identity}.png"
    if not isinstance(row["image_path"], str) or row["image_path"] != expected:
        raise ValueError("The saved handout image path is invalid.")
    _text(row["created_at"], "Saved image date", 100)
    return HandoutAsset(identity, row["campaign_id"], row["handout_id"], expected,
                        row["width"], row["height"], row["sha256"],
                        bool(row["selected"]), bool(row["archived"]), row["created_at"])


def _managed_path(library_path: Path, asset: HandoutAsset, *, require_file=True):
    root = library_path.parent.resolve() / "assets" / "handouts"
    path = library_path.parent.resolve().joinpath(*PurePosixPath(asset.image_path).parts)
    if (root.parent.is_symlink() or root.is_symlink() or path.is_symlink()
            or path.resolve().parent != root or path.name != f"{asset.id}.png"):
        raise ValueError("Handout images must remain inside the managed handout assets folder without symbolic links.")
    if require_file and not path.is_file():
        raise ValueError("The handout image is missing; restore its managed assets from a complete backup.")
    return path


def _image_bytes(library_path: Path, asset: HandoutAsset):
    path = _managed_path(library_path, asset)
    with path.open("rb") as stream:
        payload = stream.read(MAX_IMAGE_BYTES + 1)
    if len(payload) > MAX_IMAGE_BYTES or sha256(payload).hexdigest() != asset.sha256:
        raise ValueError("The saved handout image changed or is too large; restore or reimport it before showing players.")
    clean, width, height = sanitize_image(payload)
    if (width, height) != (asset.width, asset.height):
        raise ValueError("The handout image dimensions no longer match its saved metadata.")
    return clean


class HandoutRepository:
    def __init__(self, library_repository):
        self.library = library_repository
        self.path = Path(self.library.path)
        self.world = WorldRepository(self.path)
        self.assets_root = self.path.parent.resolve() / "assets" / "handouts"
        with self.library._connection() as db:
            db.execute("BEGIN IMMEDIATE")
            ensure_schema(db)

    @staticmethod
    def _handout(db, campaign_id, handout_id):
        _text(campaign_id, "Campaign ID")
        _text(handout_id, "Handout ID")
        row = db.execute("SELECT * FROM world_records WHERE id=? AND campaign_id=? AND kind='handout'", (handout_id, campaign_id)).fetchone()
        if row is None:
            raise ValueError("Select a saved handout from this campaign in the World & Campaign Desk.")
        record = WorldRepository._from_row(row)
        if record.archived:
            raise ValueError("Restore the archived world handout before managing or displaying its images.")
        return record

    @staticmethod
    def _require_image(db, campaign_id, handout_id, image_id):
        _text(image_id, "Handout image ID")
        return _asset(db.execute("SELECT * FROM handout_assets WHERE id=? AND campaign_id=? AND handout_id=?", (image_id, campaign_id, handout_id)).fetchone())

    def list_handouts(self, campaign_id):
        return self.world.list(campaign_id, kind="handout")

    def list_images(self, campaign_id, handout_id, *, include_archived=False):
        if type(include_archived) is not bool:
            raise ValueError("Image archive selection must be a checkbox value.")
        with self.library._connection() as db:
            self._handout(db, campaign_id, handout_id)
            rows = db.execute("SELECT * FROM handout_assets WHERE campaign_id=? AND handout_id=? AND (? OR archived=0) ORDER BY created_at,rowid", (campaign_id, handout_id, include_archived)).fetchall()
        return [_asset(row) for row in rows]

    def get_image(self, campaign_id, handout_id, image_id):
        with self.library._connection() as db:
            self._handout(db, campaign_id, handout_id)
            return self._require_image(db, campaign_id, handout_id, image_id)

    def import_image(self, campaign_id, handout_id, source_path):
        with self.library._connection() as db:
            self._handout(db, campaign_id, handout_id)
        source = Path(source_path)
        if not source.is_file():
            raise ValueError("Choose a local PNG, JPEG, or WebP image file.")
        with source.open("rb") as stream:
            payload = stream.read(MAX_IMAGE_BYTES + 1)
        clean, width, height = sanitize_image(payload)
        identity = str(uuid4())
        image_path = f"assets/handouts/{identity}.png"
        staged = HandoutAsset(identity, campaign_id, handout_id, image_path, width, height,
                              sha256(clean).hexdigest(), True, False, "pending")
        destination = _managed_path(self.path, staged, require_file=False)
        self.assets_root.mkdir(parents=True, exist_ok=True)
        created = False
        try:
            with destination.open("xb") as output:
                created = True
                output.write(clean)
            with self.library._connection() as db:
                db.execute("BEGIN IMMEDIATE")
                self._handout(db, campaign_id, handout_id)
                db.execute("UPDATE handout_assets SET selected=0 WHERE handout_id=?", (handout_id,))
                db.execute("INSERT INTO handout_assets(id,campaign_id,handout_id,image_path,width,height,sha256,selected) VALUES(?,?,?,?,?,?,?,1)",
                           (identity, campaign_id, handout_id, image_path, width, height, staged.sha256))
        except Exception:
            if created:
                destination.unlink(missing_ok=True)
            raise
        return self.get_image(campaign_id, handout_id, identity)

    def select_image(self, campaign_id, handout_id, image_id=None):
        with self.library._connection() as db:
            db.execute("BEGIN IMMEDIATE")
            self._handout(db, campaign_id, handout_id)
            if image_id is not None:
                image = self._require_image(db, campaign_id, handout_id, image_id)
                if image.archived:
                    raise ValueError("Restore an archived image before selecting it for players.")
                _image_bytes(self.path, image)
            db.execute("UPDATE handout_assets SET selected=0 WHERE handout_id=?", (handout_id,))
            if image_id is not None:
                db.execute("UPDATE handout_assets SET selected=1 WHERE id=?", (image_id,))

    def set_archived(self, campaign_id, handout_id, image_id, archived=True):
        if type(archived) is not bool:
            raise ValueError("Image archive state must be a checkbox value.")
        with self.library._connection() as db:
            db.execute("BEGIN IMMEDIATE")
            self._handout(db, campaign_id, handout_id)
            self._require_image(db, campaign_id, handout_id, image_id)
            if archived:
                db.execute("UPDATE handout_assets SET selected=0,archived=1 WHERE id=?", (image_id,))
            else:
                db.execute("UPDATE handout_assets SET archived=0 WHERE id=?", (image_id,))
        return self.get_image(campaign_id, handout_id, image_id)

    def public_payload(self, campaign_id, handout_id):
        with self.library._connection() as db:
            db.execute("BEGIN")
            record = self._handout(db, campaign_id, handout_id)
            selected = db.execute("SELECT * FROM handout_assets WHERE campaign_id=? AND handout_id=? AND selected=1", (campaign_id, handout_id)).fetchall()
            if len(selected) > 1:
                raise ValueError("The saved handout has conflicting selected images; preserve the database for recovery.")
            asset = _asset(selected[0]) if selected else None
        text = record.details["player_text"]
        image = _image_bytes(self.path, asset) if asset else None
        if not text.strip() and image is None:
            raise ValueError("Write Player text in the World Desk or attach an image before previewing this handout.")
        return PublicHandout(text, image)

    def export_payload(self, payload: PublicHandout, destination):
        """Publish the exact reviewed public snapshot with generic ZIP member names."""
        if not isinstance(payload, PublicHandout):
            raise ValueError("Review a public handout snapshot before exporting it.")
        _text(payload.text, "Public handout text", 100000, required=False)
        if payload.image_png is not None:
            clean, _, _ = sanitize_image(payload.image_png)
            if clean != payload.image_png:
                raise ValueError("The image snapshot is not sanitized; review a new player preview before exporting.")
        elif not payload.text.strip():
            raise ValueError("The public handout snapshot is empty.")
        target = Path(destination).expanduser().resolve()
        database = self.path.resolve()
        databases = {database, database.with_name("rules.sqlite3")}
        protected = {*(database.with_name(name) for name in ("current_scene.json", "battle_trakker.json", "srd35_spells.json")), *databases}
        for live in databases:
            protected.update(live.with_name(live.name + suffix) for suffix in ("-wal", "-shm", "-journal"))
        if target in protected or (target.exists() and any(live.exists() and os.path.samefile(target, live) for live in protected)):
            raise ValueError("Choose an export destination outside active library/rules databases, scene/battle saves, and their journal files.")
        managed = database.parent / "assets"
        if self.assets_root.parent.is_symlink() or self.assets_root.is_symlink() or managed == target or managed in target.parents:
            raise ValueError("Save player exports outside managed campaign assets.")
        with self.library._output_path(target) as staging:
            with zipfile.ZipFile(staging, "w") as archive:
                def write(name, data):
                    info = zipfile.ZipInfo(name, (1980, 1, 1, 0, 0, 0))
                    info.compress_type = zipfile.ZIP_DEFLATED
                    info.create_system = 0
                    archive.writestr(info, data)
                write("handout.txt", payload.text.encode("utf-8"))
                if payload.image_png is not None:
                    write("image.png", payload.image_png)


def validate_saved_state(library_repository_or_path):
    """Read-only recovery check of every attachment, link, and managed image."""
    path = Path(getattr(library_repository_or_path, "path", library_repository_or_path)).resolve()
    with closing(sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)) as db:
        db.row_factory = sqlite3.Row
        tables = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if "handout_assets" not in tables:
            return
        selected = set()
        for row in db.execute("SELECT * FROM handout_assets"):
            asset = _asset(row)
            handout = db.execute("SELECT * FROM world_records WHERE id=?", (asset.handout_id,)).fetchone()
            if handout is None or handout["kind"] != "handout" or handout["campaign_id"] != asset.campaign_id:
                raise ValueError("A saved handout image references a missing/foreign handout.")
            WorldRepository._from_row(handout)
            if db.execute("SELECT id FROM campaigns WHERE id=?", (asset.campaign_id,)).fetchone() is None:
                raise ValueError("A saved handout image references a missing campaign.")
            if asset.selected:
                if asset.handout_id in selected:
                    raise ValueError("A handout has more than one selected image.")
                selected.add(asset.handout_id)
            _image_bytes(path, asset)
