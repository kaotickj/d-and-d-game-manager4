"""Campaign-owned map images and validated, persistent tabletop state."""
from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
import json
import math
from pathlib import Path, PurePosixPath
from uuid import uuid4

MAX_IMAGE_BYTES = 25 * 1024 * 1024
MAX_IMAGE_EDGE = 10000
MAX_IMAGE_PIXELS = 40000000
MAX_STATE_BYTES = 1024 * 1024
MAX_TOKENS = 250
MAX_ANNOTATIONS = 250
MAX_REVEALED_CELLS = 20000
TOKEN_COLORS = ("#ed6276", "#71b7da", "#d6b361", "#8ebc88", "#c59ae5", "#e3986e")
IMAGE_FORMATS = {"png": ".png", "jpeg": ".jpg", "jpg": ".jpg", "webp": ".webp", "bmp": ".bmp"}


class MapConflictError(ValueError):
    """A map changed after this editor loaded its baseline."""


@dataclass(frozen=True, slots=True)
class CampaignMap:
    id: str
    campaign_id: str
    title: str
    image_path: str
    state: dict
    created_at: str = ""
    updated_at: str = ""


@dataclass(frozen=True, slots=True)
class EncounterActor:
    encounter_id: str
    fighter_uid: str
    name: str
    session_title: str
    encounter_title: str


def _text(value, label, maximum=200):
    if (not isinstance(value, str) or not value.strip()
            or len(value) > maximum or "\x00" in value):
        raise ValueError(f"{label} must contain 1–{maximum} characters.")
    try:
        value.encode("utf-8")
    except UnicodeError as exc:
        raise ValueError(f"{label} contains invalid text.") from exc
    return value.strip()


def blank_map_state(width: int, height: int) -> dict:
    return {
        "version": 2, "width": width, "height": height, "grid_size": 50,
        "show_grid": True, "snap_to_grid": True, "fog_enabled": True,
        "revealed": [], "tokens": [], "units_per_cell": 5.0,
        "unit_label": "ft", "annotations": [],
    }


def validate_map_state(state: dict) -> dict:
    """Bound coordinates, image sizes, and state before storage or display."""
    optional = {"units_per_cell", "unit_label", "annotations"}
    keys = set(blank_map_state(1, 1))
    if (not isinstance(state, dict) or not (keys - optional).issubset(state)
            or not set(state).issubset(keys)):
        raise ValueError("Map state has an unsupported format.")
    version = state.get("version")
    if type(version) is not int or version not in (1, 2):
        raise ValueError("Map state has an unsupported version.")
    if version == 2 and set(state) != keys:
        raise ValueError("Version 2 map state is missing calibration or annotation fields.")
    # Existing version-1 maps acquire calibration and note defaults on read.
    state = dict(blank_map_state(1, 1), **state)
    state["version"] = 2
    for key in ("width", "height"):
        if type(state[key]) is not int or not 1 <= state[key] <= MAX_IMAGE_EDGE:
            raise ValueError("Map dimensions are outside the supported range.")
    if state["width"] * state["height"] > MAX_IMAGE_PIXELS:
        raise ValueError("Map images must contain at most 40 million pixels.")
    grid = state["grid_size"]
    if type(grid) is not int or not 16 <= grid <= 512:
        raise ValueError("Grid size must be between 16 and 512 pixels.")
    units = state["units_per_cell"]
    if type(units) not in (int, float) or not 0 < units <= 100000:
        raise ValueError("Distance per grid cell must be greater than zero and at most 100,000.")
    unit_label = _text(state["unit_label"], "Distance unit", 24)
    if any(character in unit_label for character in "\r\n\t"):
        raise ValueError("Distance units must fit on one line.")
    for key in ("show_grid", "snap_to_grid", "fog_enabled"):
        if type(state[key]) is not bool:
            raise ValueError("Map display choices must be checkbox values.")
    cells = state["revealed"]
    if not isinstance(cells, list) or len(cells) > MAX_REVEALED_CELLS:
        raise ValueError("A map supports at most 20,000 individually revealed cells.")
    clean_cells = set()
    for cell in cells:
        if (not isinstance(cell, (list, tuple)) or len(cell) != 2
                or any(type(value) is not int for value in cell)
                or not 0 <= cell[0] < math.ceil(state["width"] / grid)
                or not 0 <= cell[1] < math.ceil(state["height"] / grid)):
            raise ValueError("Revealed cells must lie inside the map grid.")
        clean_cells.add(tuple(cell))
    tokens = state["tokens"]
    if not isinstance(tokens, list) or len(tokens) > MAX_TOKENS:
        raise ValueError("A map supports at most 250 tokens.")
    clean_tokens, identities = [], set()
    for token in tokens:
        token_keys = {"id", "label", "x", "y", "color", "visible"}
        if (not isinstance(token, dict) or not token_keys.issubset(token)
                or not set(token).issubset(token_keys | {"link"})):
            raise ValueError("Map tokens have an unsupported format.")
        identity = _text(token["id"], "Token ID")
        label = _text(token["label"], "Token label", 80)
        if identity in identities:
            raise ValueError("Every map token must have a unique ID.")
        identities.add(identity)
        for axis, bound in (("x", state["width"]), ("y", state["height"])):
            value = token[axis]
            if type(value) not in (int, float) or not 0 <= value < bound:
                raise ValueError("Token positions must lie inside the map.")
        if token["color"] not in TOKEN_COLORS or type(token["visible"]) is not bool:
            raise ValueError("Choose a supported token color and visibility.")
        clean_token = dict(token, id=identity, label=label)
        if "link" in token:
            link = token["link"]
            if not isinstance(link, dict) or set(link) != {"encounter_id", "fighter_uid"}:
                raise ValueError("An encounter token must reference an encounter and a fighter instance.")
            clean_token["link"] = {key: _text(value, "Encounter token reference")
                                   for key, value in link.items()}
        clean_tokens.append(clean_token)
    annotations = state["annotations"]
    if not isinstance(annotations, list) or len(annotations) > MAX_ANNOTATIONS:
        raise ValueError("A map supports at most 250 annotations.")
    clean_annotations, note_ids = [], set()
    for note in annotations:
        note_keys = {"id", "text", "x", "y", "color"}
        if (not isinstance(note, dict) or not note_keys.issubset(note)
                or not set(note).issubset(note_keys | {"visible"})):
            raise ValueError("Map annotations have an unsupported format.")
        identity = _text(note["id"], "Annotation ID")
        if identity in note_ids:
            raise ValueError("Every map annotation must have a unique ID.")
        note_ids.add(identity)
        text = _text(note["text"], "Annotation", 300)
        for axis, bound in (("x", state["width"]), ("y", state["height"])):
            value = note[axis]
            if type(value) not in (int, float) or not 0 <= value < bound:
                raise ValueError("Annotation positions must lie inside the map.")
        visible = note.get("visible", False)
        if note["color"] not in TOKEN_COLORS or type(visible) is not bool:
            raise ValueError("Choose a supported annotation color and visibility.")
        clean_annotations.append(dict(note, id=identity, text=text, visible=visible))
    clean = dict(state, revealed=[list(cell) for cell in sorted(clean_cells)], tokens=clean_tokens,
                 annotations=clean_annotations, units_per_cell=float(units), unit_label=unit_label)
    if len(json.dumps(clean, ensure_ascii=False).encode("utf-8")) > MAX_STATE_BYTES:
        raise ValueError("Map state exceeds the 1 MB limit.")
    return clean


def token_is_revealed(state: dict, token: dict) -> bool:
    if not state["fog_enabled"]:
        return True
    grid = state["grid_size"]
    return [int(token["x"] // grid), int(token["y"] // grid)] in state["revealed"]


def player_map_state(state: dict) -> dict:
    """Remove private objects and actor references before public item creation."""
    clean = validate_map_state(state)
    public = {key: clean[key] for key in (
        "version", "width", "height", "grid_size", "show_grid", "snap_to_grid",
        "fog_enabled", "revealed", "units_per_cell", "unit_label",
    )}
    public["tokens"] = [{key: token[key] for key in ("id", "label", "x", "y", "color", "visible")}
                        for token in clean["tokens"]
                        if token["visible"] and token_is_revealed(clean, token)]
    public["annotations"] = [{key: note[key] for key in ("id", "text", "x", "y", "color", "visible")}
                             for note in clean["annotations"]
                             if note["visible"] and token_is_revealed(clean, note)]
    return deepcopy(public)


def map_distance(state: dict, start, end) -> float:
    """Calibrated straight-line distance; this is not a grid movement cost."""
    clean = validate_map_state(state)
    for point in (start, end):
        if (not isinstance(point, (tuple, list)) or len(point) != 2
                or any(type(value) not in (int, float) for value in point)
                or not 0 <= point[0] <= clean["width"]
                or not 0 <= point[1] <= clean["height"]):
            raise ValueError("Ruler points must lie inside the map.")
    return math.hypot(end[0] - start[0], end[1] - start[1]) / clean["grid_size"] * clean["units_per_cell"]


def player_map_image(image, state):
    """Copy only revealed source rectangles into an opaque public image."""
    from PyQt6.QtCore import QRect
    from PyQt6.QtGui import QImage, QPainter
    clean = player_map_state(state)
    if (image.width(), image.height()) != (clean["width"], clean["height"]):
        raise ValueError("The player image must match its map dimensions.")
    if not clean["fog_enabled"]:
        return image.copy()
    public = QImage(image.size(), QImage.Format.Format_ARGB32_Premultiplied)
    public.fill(0xff000000)
    painter = QPainter(public)
    edge = clean["grid_size"]
    for x, y in clean["revealed"]:
        rect = QRect(x * edge, y * edge, min(edge, clean["width"] - x * edge),
                     min(edge, clean["height"] - y * edge))
        painter.drawImage(rect, image, rect)
    painter.end()
    return public


def _read_image(payload: bytes):
    # QImageReader validates image content without creating a GUI or QPixmap.
    from PyQt6.QtCore import QByteArray, QBuffer, QIODevice
    from PyQt6.QtGui import QImageReader
    buffer = QBuffer()
    buffer.setData(QByteArray(payload))
    buffer.open(QIODevice.OpenModeFlag.ReadOnly)
    reader = QImageReader(buffer)
    reader.setAutoTransform(True)
    if not reader.canRead():
        raise ValueError("Choose a readable PNG, JPEG, WebP, or BMP image.")
    extension = IMAGE_FORMATS.get(bytes(reader.format()).decode("ascii", errors="replace").lower())
    if extension is None:
        raise ValueError("Choose a PNG, JPEG, WebP, or BMP image.")
    size = reader.size()
    validate_map_state(blank_map_state(size.width(), size.height()))
    image = reader.read()
    if image.isNull():
        raise ValueError("The map image could not be decoded.")
    validate_map_state(blank_map_state(image.width(), image.height()))
    return image, extension


class MapRepository:
    def __init__(self, library):
        self.library = library
        self.assets_root = library.path.parent.resolve() / "assets" / "maps"

    def _campaign(self, db, campaign_id):
        campaign_id = _text(campaign_id, "Campaign ID")
        if db.execute("SELECT 1 FROM campaigns WHERE id=?", (campaign_id,)).fetchone() is None:
            raise ValueError("The selected campaign no longer exists.")
        return campaign_id

    @staticmethod
    def _record(row):
        if row is None:
            raise ValueError("The map was not found in the selected campaign.")
        try:
            payload = row["state_json"]
            if not isinstance(payload, str):
                raise ValueError("The saved map state must contain JSON text.")
            if len(payload.encode("utf-8")) > MAX_STATE_BYTES:
                raise ValueError("Map state exceeds the 1 MB limit.")
            state = validate_map_state(json.loads(payload))
        except (TypeError, RecursionError, UnicodeError, json.JSONDecodeError) as exc:
            raise ValueError("The saved map state is unreadable.") from exc
        return CampaignMap(row["id"], row["campaign_id"], row["title"], row["image_path"],
                           state, row["created_at"], row["updated_at"])

    def encounter_actors(self, campaign_id: str) -> list[EncounterActor]:
        """Return saved fighter instances belonging to this campaign only."""
        from .campaigns import CampaignRepository
        with self.library._connection() as db:
            self._campaign(db, campaign_id)
        campaigns = CampaignRepository(self.library.path)
        choices = []
        for session in campaigns.list_sessions(campaign_id):
            for encounter in campaigns.list_encounters(session.id):
                for fighter in campaigns.load_battle(encounter.id).fighters:
                    choices.append(EncounterActor(encounter.id, fighter.uid, fighter.name,
                                                  session.title, encounter.title))
        return choices

    @staticmethod
    def _validate_links(db, campaign_id, tokens):
        from .campaigns import CampaignRepository
        rosters, seen = {}, set()
        for token in tokens:
            if "link" not in token:
                continue
            link = token["link"]
            encounter_id, fighter_uid = link["encounter_id"], link["fighter_uid"]
            if encounter_id not in rosters:
                row = db.execute("""SELECT e.battle_json FROM encounters e
                                    JOIN sessions s ON s.id=e.session_id
                                    WHERE e.id=? AND s.campaign_id=?""",
                                 (encounter_id, campaign_id)).fetchone()
                if row is None:
                    raise ValueError("Linked tokens must use a saved encounter from this campaign.")
                rosters[encounter_id] = {fighter.uid for fighter in
                                        CampaignRepository._read_battle(row["battle_json"]).fighters}
            if fighter_uid not in rosters[encounter_id]:
                raise ValueError("The linked fighter no longer exists in that encounter. Unlink its token before saving.")
            if (encounter_id, fighter_uid) in seen:
                raise ValueError("That encounter actor already has a linked token on this map.")
            seen.add((encounter_id, fighter_uid))

    def list(self, campaign_id: str) -> list[CampaignMap]:
        with self.library._connection() as db:
            self._campaign(db, campaign_id)
            rows = db.execute("SELECT * FROM maps WHERE campaign_id=? ORDER BY title COLLATE NOCASE,id",
                              (campaign_id,)).fetchall()
        return [self._record(row) for row in rows]

    def get(self, map_id: str, *, campaign_id: str | None = None) -> CampaignMap:
        identity = _text(map_id, "Map ID")
        with self.library._connection() as db:
            row = db.execute("SELECT * FROM maps WHERE id=?", (identity,)).fetchone()
        if row is not None and campaign_id is not None and row["campaign_id"] != campaign_id:
            row = None
        return self._record(row)

    def image_path(self, record: CampaignMap) -> Path:
        relative = PurePosixPath(record.image_path)
        expected = PurePosixPath("assets", "maps", relative.name)
        if (relative != expected or "\\" in record.image_path
                or relative.stem != record.id or relative.suffix not in IMAGE_FORMATS.values()):
            raise ValueError("The saved map image path is invalid.")
        path = self.library.path.parent.resolve().joinpath(*relative.parts)
        if (self.assets_root.parent.is_symlink() or self.assets_root.is_symlink()
                or path.is_symlink() or path.resolve().parent != self.assets_root):
            raise ValueError("Map images must remain inside the library's map assets folder.")
        if not path.is_file():
            raise ValueError("The map image is missing. Restore its assets folder from a complete backup.")
        return path

    def load_image(self, record: CampaignMap):
        path = self.image_path(record)
        with path.open("rb") as source:
            payload = source.read(MAX_IMAGE_BYTES + 1)
        if len(payload) > MAX_IMAGE_BYTES:
            raise ValueError("Map images must be at most 25 MB.")
        image, _ = _read_image(payload)
        if (image.width(), image.height()) != (record.state["width"], record.state["height"]):
            raise ValueError("The map image dimensions no longer match its saved grid.")
        return image

    def import_image(self, campaign_id: str, path: str | Path, title: str = "") -> CampaignMap:
        source = Path(path)
        title = _text(title or source.stem, "Map title")
        with self.library._connection() as db:
            self._campaign(db, campaign_id)
        if not source.is_file():
            raise ValueError("Choose a local image file.")
        with source.open("rb") as stream:
            payload = stream.read(MAX_IMAGE_BYTES + 1)
        if len(payload) > MAX_IMAGE_BYTES:
            raise ValueError("Map images must be at most 25 MB.")
        image, extension = _read_image(payload)
        state = validate_map_state(blank_map_state(image.width(), image.height()))
        if self.assets_root.parent.is_symlink() or self.assets_root.is_symlink():
            raise ValueError("The managed map assets folder cannot be a symbolic link.")
        self.assets_root.mkdir(parents=True, exist_ok=True)
        identity = str(uuid4())
        destination = self.assets_root / f"{identity}{extension}"
        try:
            with destination.open("xb") as output:
                output.write(payload)
            with self.library._connection() as db:
                self._campaign(db, campaign_id)
                db.execute("INSERT INTO maps (id,campaign_id,title,image_path,state_json) VALUES (?,?,?,?,?)",
                           (identity, campaign_id, title, f"assets/maps/{destination.name}",
                            json.dumps(state, ensure_ascii=False)))
        except Exception:
            destination.unlink(missing_ok=True)
            raise
        return self.get(identity, campaign_id=campaign_id)

    def save_state(self, map_id: str, state: dict, *, campaign_id: str | None = None,
                   expected_state: dict | None = None) -> CampaignMap:
        with self.library._connection() as db:
            db.execute("BEGIN IMMEDIATE")
            current = self._record(db.execute("SELECT * FROM maps WHERE id=?", (map_id,)).fetchone())
            if campaign_id is not None and current.campaign_id != campaign_id:
                raise ValueError("The map was not found in the selected campaign.")
            if expected_state is not None and validate_map_state(expected_state) != current.state:
                raise MapConflictError("This map changed in another window. Reload Map before saving further changes.")
            # Clear old cell coordinates before validating against the new grid.
            if isinstance(state, dict) and state.get("grid_size") != current.state["grid_size"]:
                state = dict(state, revealed=[])
            clean = validate_map_state(state)
            if (clean["width"], clean["height"]) != (current.state["width"], current.state["height"]):
                raise ValueError("A map's original image dimensions cannot be changed.")
            self._validate_links(db, current.campaign_id, clean["tokens"])
            db.execute("UPDATE maps SET state_json=?,updated_at=CURRENT_TIMESTAMP WHERE id=?",
                       (json.dumps(clean, ensure_ascii=False), map_id))
        return self.get(map_id, campaign_id=campaign_id)

    def rename(self, map_id: str, title: str, *, campaign_id: str | None = None) -> CampaignMap:
        title = _text(title, "Map title")
        with self.library._connection() as db:
            db.execute("BEGIN IMMEDIATE")
            current = self._record(db.execute("SELECT * FROM maps WHERE id=?", (map_id,)).fetchone())
            if campaign_id is not None and current.campaign_id != campaign_id:
                raise ValueError("The map was not found in the selected campaign.")
            db.execute("UPDATE maps SET title=?,updated_at=CURRENT_TIMESTAMP WHERE id=?", (title, map_id))
        return self.get(map_id, campaign_id=campaign_id)
