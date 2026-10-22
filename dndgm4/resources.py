"""Campaign wallets, item instances, and reviewed rewards in one SQLite ledger.

Money is stored in copper pieces and weight in thousandths of a pound. A
request ID identifies one command: replay returns its original result; reusing
the ID for a different command is rejected. Commands never advance a level.
"""
from __future__ import annotations

from contextlib import closing
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
import json
from pathlib import Path
import sqlite3
from uuid import uuid4

from .campaigns import CampaignRepository

MAX_MONEY = 1_000_000_000_000
MAX_XP = 1_000_000_000
MAX_QUANTITY = 1_000_000
CARRYING_SOURCE = "https://www.d20srd.org/srd/carryingCapacity.htm"

# The integrator can run these statements in the central additive migration.
# IF NOT EXISTS also lets a repository opened on a pre-integration database work
# safely. This hook deliberately never changes PRAGMA user_version.
SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS resource_wallets (
    id TEXT PRIMARY KEY,
    campaign_id TEXT NOT NULL REFERENCES campaigns(id),
    name TEXT NOT NULL,
    creature_id TEXT REFERENCES creatures(id),
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(campaign_id,creature_id)
);
CREATE TABLE IF NOT EXISTS resource_containers (
    id TEXT PRIMARY KEY,
    campaign_id TEXT NOT NULL REFERENCES campaigns(id),
    wallet_id TEXT NOT NULL REFERENCES resource_wallets(id),
    name TEXT NOT NULL,
    tare_millilb INTEGER NOT NULL DEFAULT 0 CHECK(tare_millilb >= 0),
    capacity_millilb INTEGER NOT NULL DEFAULT 0 CHECK(capacity_millilb >= 0)
);
CREATE TABLE IF NOT EXISTS resource_items (
    id TEXT PRIMARY KEY,
    campaign_id TEXT NOT NULL REFERENCES campaigns(id),
    wallet_id TEXT NOT NULL REFERENCES resource_wallets(id),
    container_id TEXT REFERENCES resource_containers(id),
    name TEXT NOT NULL,
    quantity INTEGER NOT NULL CHECK(quantity >= 0),
    unit_millilb INTEGER NOT NULL CHECK(unit_millilb >= 0),
    unit_cp INTEGER NOT NULL DEFAULT 0 CHECK(unit_cp >= 0),
    notes TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS resource_items_wallet ON resource_items(campaign_id,wallet_id);
CREATE TABLE IF NOT EXISTS resource_xp_applied (
    ledger_id TEXT PRIMARY KEY REFERENCES resource_ledger(id),
    operation_id TEXT NOT NULL REFERENCES resource_operations(id)
);
"""


def ensure_schema(db: sqlite3.Connection) -> None:
    """Execute additive statements inside the caller's transaction."""
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
    return value.strip() if required else value


def _integer(value, label, maximum=MAX_MONEY, *, minimum=0):
    if type(value) is not int or not minimum <= value <= maximum:
        raise ValueError(f"{label} must be a whole number from {minimum:,} to {maximum:,}.")
    return value


def decode_operation(text):
    """Refuse malformed saved command metadata without attempting a replay."""
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("Duplicate saved command field.")
            result[key] = value
        return result

    def invalid_constant(value):
        raise ValueError("Invalid saved command number.")

    try:
        if not isinstance(text, str) or len(text) > 1_000_000:
            raise ValueError("Invalid saved command size.")
        payload = json.loads(text, object_pairs_hook=unique, parse_constant=invalid_constant)
        if (not isinstance(payload, dict) or set(payload) != {"request", "result"}
                or not isinstance(payload["request"], dict)
                or not isinstance(payload["result"], dict) or not payload["result"]
                or not isinstance(payload["request"].get("command"), str)):
            raise ValueError("Invalid saved command shape.")
        return payload
    except (ValueError, TypeError, RecursionError) as exc:
        raise ValueError("The saved resource command metadata is damaged. Preserve the database for recovery; this request cannot be replayed.") from exc


def pounds_to_millilb(value: str) -> int:
    """Parse a precise nonnegative weight; never round entered quantities."""
    if not isinstance(value, str):
        raise ValueError("Weight must be decimal text in pounds.")
    try:
        number = Decimal(value)
    except InvalidOperation as exc:
        raise ValueError("Enter a weight in pounds with at most three decimal places.") from exc
    if (not number.is_finite() or number < 0 or number > Decimal("1000000000")
            or number * 1000 != (number * 1000).to_integral_value()):
        raise ValueError("Weight must be nonnegative with at most three decimal places.")
    return int(number * 1000)


def money_label(cp: int) -> str:
    sign = "−" if cp < 0 else ""
    gp, remainder = divmod(abs(cp), 100)
    sp, copper = divmod(remainder, 10)
    return f"{sign}{gp:,} gp {sp} sp {copper} cp"


@dataclass(frozen=True, slots=True)
class Wallet:
    id: str
    campaign_id: str
    name: str
    creature_id: str | None
    copper: int


@dataclass(frozen=True, slots=True)
class Container:
    id: str
    campaign_id: str
    wallet_id: str
    name: str
    tare_millilb: int
    capacity_millilb: int


@dataclass(frozen=True, slots=True)
class Item:
    id: str
    campaign_id: str
    wallet_id: str
    container_id: str | None
    name: str
    quantity: int
    unit_millilb: int
    unit_cp: int
    notes: str


@dataclass(frozen=True, slots=True)
class XPPreview:
    campaign_id: str
    wallet_id: str
    creature_id: str
    name: str
    current: int
    pending: int
    ledger_ids: tuple[str, ...]

    @property
    def target(self):
        return self.current + self.pending


# Exact table thresholds, not thirds calculated from the rounded heavy column.
_LOADS = (
    (0, 0, 0), (3, 6, 10), (6, 13, 20), (10, 20, 30), (13, 26, 40),
    (16, 33, 50), (20, 40, 60), (23, 46, 70), (26, 53, 80), (30, 60, 90),
    (33, 66, 100), (38, 76, 115), (43, 86, 130), (50, 100, 150),
    (58, 116, 175), (66, 133, 200), (76, 153, 230), (86, 173, 260),
    (100, 200, 300), (116, 233, 350), (133, 266, 400), (153, 306, 460),
    (173, 346, 520), (200, 400, 600), (233, 466, 700), (266, 533, 800),
    (306, 613, 920), (346, 693, 1040), (400, 800, 1200), (466, 933, 1400),
)
_BIPED = {"Fine": Decimal(".125"), "Diminutive": Decimal(".25"),
          "Tiny": Decimal(".5"), "Small": Decimal(".75"), "Medium": Decimal(1),
          "Large": Decimal(2), "Huge": Decimal(4), "Gargantuan": Decimal(8), "Colossal": Decimal(16)}
_QUADRUPED = dict(zip(_BIPED, map(Decimal, (".25", ".5", ".75", "1", "1.5", "3", "6", "12", "24"))))


def carrying_capacity(strength: int, size="Medium", quadruped=False) -> tuple[Decimal, Decimal, Decimal]:
    _integer(strength, "Strength", 99, minimum=1)
    if size not in _BIPED or type(quadruped) is not bool:
        raise ValueError("Choose a supported size and biped/quadruped form.")
    row, factor = strength, 1
    if strength >= 30:
        row = 20 + strength % 10
        factor = 4 ** ((strength - row) // 10)
    multiplier = (_QUADRUPED if quadruped else _BIPED)[size] * factor
    return tuple(Decimal(value) * multiplier for value in _LOADS[row])


def encumbrance(weight_millilb: int, strength: int, size="Medium", quadruped=False) -> dict:
    _integer(weight_millilb, "Carried weight", 10**21)
    light, medium, heavy = carrying_capacity(strength, size, quadruped)
    weight = Decimal(weight_millilb) / 1000
    category = "light" if weight <= light else "medium" if weight <= medium else "heavy" if weight <= heavy else "overloaded"
    return {"load": category, "weight_lb": str(weight), "light_lb": str(light),
            "medium_lb": str(medium), "heavy_lb": str(heavy),
            "max_dex": {"light": None, "medium": 3, "heavy": 1, "overloaded": 0}[category],
            "check_penalty": {"light": 0, "medium": -3, "heavy": -6, "overloaded": None}[category],
            "speed_20_ft": 20 if category == "light" else 15 if category != "overloaded" else 5 if weight <= heavy * 2 else 0,
            "speed_30_ft": 30 if category == "light" else 20 if category != "overloaded" else 5 if weight <= heavy * 2 else 0,
            "run_multiplier": 4 if category in ("light", "medium") else 3 if category == "heavy" else 0,
            "source": CARRYING_SOURCE}


class ResourceRepository:
    def __init__(self, database_path: str | Path):
        self.campaigns = CampaignRepository(database_path)
        self.library = self.campaigns.library
        self.path = self.library.path
        with self.library._connection() as db:
            db.execute("BEGIN IMMEDIATE")
            ensure_schema(db)

    def _connection(self):
        return self.library._connection()

    @staticmethod
    def _campaign(db, campaign_id):
        _text(campaign_id, "Campaign ID")
        if db.execute("SELECT id FROM campaigns WHERE id=?", (campaign_id,)).fetchone() is None:
            raise ValueError("Choose a saved campaign.")

    @staticmethod
    def _row(db, table, identity, campaign_id, label):
        _text(identity, label + " ID")
        row = db.execute(f"SELECT * FROM {table} WHERE id=? AND campaign_id=?", (identity, campaign_id)).fetchone()
        if row is None:
            raise ValueError(f"{label} does not belong to this campaign or no longer exists.")
        ResourceRepository._validate_row(table, row)
        return row

    @staticmethod
    def _validate_row(table, row):
        if table not in ("resource_wallets", "resource_containers", "resource_items"):
            return
        _text(row["id"], "Saved resource ID")
        _text(row["campaign_id"], "Saved campaign ID")
        _text(row["name"], "Saved resource name")
        if table == "resource_wallets":
            if row["creature_id"] is not None:
                _text(row["creature_id"], "Saved creature ID")
        else:
            _text(row["wallet_id"], "Saved owner wallet ID")
        if table == "resource_containers":
            _integer(row["tare_millilb"], "Saved empty container weight")
            _integer(row["capacity_millilb"], "Saved container capacity")
        elif table == "resource_items":
            _integer(row["quantity"], "Saved item quantity", MAX_QUANTITY)
            _integer(row["unit_millilb"], "Saved item weight")
            _integer(row["unit_cp"], "Saved item value")
            _text(row["notes"], "Saved item notes", 20000, required=False)
            if row["container_id"] is not None:
                _text(row["container_id"], "Saved container ID")

    @staticmethod
    def _source(db, campaign_id, session_id, encounter_id):
        _text(session_id, "Session ID", required=False)
        _text(encounter_id, "Encounter ID", required=False)
        if session_id:
            ResourceRepository._row(db, "sessions", session_id, campaign_id, "Session")
        if encounter_id:
            _text(encounter_id, "Encounter ID")
            row = db.execute("SELECT e.session_id FROM encounters e JOIN sessions s ON s.id=e.session_id WHERE e.id=? AND s.campaign_id=?",
                             (encounter_id, campaign_id)).fetchone()
            if row is None or (session_id and row["session_id"] != session_id):
                raise ValueError("Encounter does not belong to the selected campaign/session.")
            session_id = row["session_id"]
        return session_id

    def _command(self, campaign_id, request_id, request, action):
        request_id = _text(request_id, "Request ID")
        serialized = json.dumps({"request": request}, ensure_ascii=False, sort_keys=True)
        if len(serialized) > 990000:
            raise ValueError("The resource command exceeds its saved metadata limit.")
        with self._connection() as db:
            db.execute("BEGIN IMMEDIATE")
            self._campaign(db, campaign_id)
            previous = db.execute("SELECT campaign_id,payload_json FROM resource_operations WHERE id=?", (request_id,)).fetchone()
            if previous:
                payload = decode_operation(previous["payload_json"])
                if previous["campaign_id"] != campaign_id or payload.get("request") != request:
                    raise ValueError("This request ID has already been used for a different command.")
                return payload["result"]
            db.execute("INSERT INTO resource_operations(id,campaign_id,payload_json) VALUES(?,?,?)",
                       (request_id, campaign_id, serialized))
            result = action(db, request_id)
            payload = json.dumps({"request": request, "result": result}, ensure_ascii=False, sort_keys=True)
            if len(payload) > 1000000:
                raise ValueError("The resource command exceeds its saved metadata limit.")
            db.execute("UPDATE resource_operations SET payload_json=? WHERE id=?",
                       (payload, request_id))
            return result

    @staticmethod
    def _balance(db, wallet_id):
        total = 0
        for row in db.execute("SELECT cp_delta FROM resource_ledger WHERE account_id=?", (wallet_id,)):
            total += _integer(row[0], "Saved copper ledger entry", minimum=-MAX_MONEY)
        return _integer(total, "Saved wallet balance")

    @staticmethod
    def _ledger(db, operation_id, campaign_id, wallet_id, cp, xp, reason, session_id):
        current = ResourceRepository._balance(db, wallet_id)
        if not 0 <= current + cp <= MAX_MONEY:
            raise ValueError("Wallet funds are insufficient or exceed the supported balance.")
        db.execute("INSERT INTO resource_ledger(id,operation_id,campaign_id,account_id,cp_delta,xp_delta,reason,session_id) VALUES(?,?,?,?,?,?,?,?)",
                   (str(uuid4()), operation_id, campaign_id, wallet_id, cp, xp, reason, session_id or None))

    def create_wallet(self, campaign_id, name, creature_id=None):
        name = _text(name, "Wallet name")
        if creature_id is not None:
            creature_id = _text(creature_id, "Creature ID")
        with self._connection() as db:
            db.execute("BEGIN IMMEDIATE")
            self._campaign(db, campaign_id)
            if creature_id is not None:
                if db.execute("SELECT id FROM creatures WHERE id=? AND archived=0", (creature_id,)).fetchone() is None:
                    raise ValueError("Choose a saved, active creature for this wallet.")
                if db.execute("SELECT id FROM resource_wallets WHERE campaign_id=? AND creature_id=?", (campaign_id, creature_id)).fetchone():
                    raise ValueError("This creature already has a wallet in the campaign.")
            identity = str(uuid4())
            db.execute("INSERT INTO resource_wallets(id,campaign_id,name,creature_id) VALUES(?,?,?,?)",
                       (identity, campaign_id, name, creature_id))
        return self.get_wallet(campaign_id, identity)

    def list_wallets(self, campaign_id):
        with self._connection() as db:
            self._campaign(db, campaign_id)
            rows = db.execute("SELECT * FROM resource_wallets WHERE campaign_id=? ORDER BY name COLLATE NOCASE,id", (campaign_id,)).fetchall()
            wallets = []
            for row in rows:
                self._validate_row("resource_wallets", row)
                wallets.append(Wallet(row["id"], row["campaign_id"], row["name"], row["creature_id"], self._balance(db, row["id"])))
        return wallets

    def get_wallet(self, campaign_id, wallet_id):
        with self._connection() as db:
            row = self._row(db, "resource_wallets", wallet_id, campaign_id, "Wallet")
            return Wallet(row["id"], campaign_id, row["name"], row["creature_id"], self._balance(db, wallet_id))

    def adjust_money(self, campaign_id, wallet_id, copper_delta, reason, request_id, *, session_id="", encounter_id=""):
        _integer(copper_delta, "Copper adjustment", MAX_MONEY, minimum=-MAX_MONEY)
        if copper_delta == 0:
            raise ValueError("Enter a nonzero adjustment.")
        reason = _text(reason, "Reason", 2000)
        request = dict(command="adjust_money", wallet_id=wallet_id, copper_delta=copper_delta, reason=reason, session_id=session_id, encounter_id=encounter_id)
        def action(db, operation):
            self._row(db, "resource_wallets", wallet_id, campaign_id, "Wallet")
            source = self._source(db, campaign_id, session_id, encounter_id)
            self._ledger(db, operation, campaign_id, wallet_id, copper_delta, 0, reason, source)
            return {"wallet_id": wallet_id, "copper": self._balance(db, wallet_id)}
        return self._command(campaign_id, request_id, request, action)

    def transfer_money(self, campaign_id, source_id, target_id, copper, reason, request_id, *, session_id="", encounter_id=""):
        _integer(copper, "Copper transfer", minimum=1)
        reason = _text(reason, "Reason", 2000)
        if source_id == target_id:
            raise ValueError("Choose two different wallets.")
        request = dict(command="transfer_money", source_id=source_id, target_id=target_id, copper=copper, reason=reason, session_id=session_id, encounter_id=encounter_id)
        def action(db, operation):
            for identity in (source_id, target_id):
                self._row(db, "resource_wallets", identity, campaign_id, "Wallet")
            source = self._source(db, campaign_id, session_id, encounter_id)
            self._ledger(db, operation, campaign_id, source_id, -copper, 0, reason, source)
            self._ledger(db, operation, campaign_id, target_id, copper, 0, reason, source)
            return {"source_copper": self._balance(db, source_id), "target_copper": self._balance(db, target_id)}
        return self._command(campaign_id, request_id, request, action)

    def award(self, campaign_id, allocations, reason, request_id, *, session_id="", encounter_id=""):
        """Award specified copper and pending XP; no automatic character edits."""
        reason = _text(reason, "Reward reason", 2000)
        if not isinstance(allocations, list) or not 1 <= len(allocations) <= 250:
            raise ValueError("Choose one to 250 reward recipients.")
        clean, seen = [], set()
        for entry in allocations:
            if not isinstance(entry, dict) or set(entry) != {"wallet_id", "copper", "xp"}:
                raise ValueError("Each allocation needs wallet_id, copper and xp.")
            wallet_id = _text(entry["wallet_id"], "Wallet ID")
            _integer(entry["copper"], "Reward copper")
            _integer(entry["xp"], "Reward XP", MAX_XP)
            if wallet_id in seen or not (entry["copper"] or entry["xp"]):
                raise ValueError("Choose distinct recipients with nonzero rewards.")
            seen.add(wallet_id)
            clean.append(dict(wallet_id=wallet_id, copper=entry["copper"], xp=entry["xp"]))
        request = dict(command="award", allocations=clean, reason=reason, session_id=session_id, encounter_id=encounter_id)
        def action(db, operation):
            source = self._source(db, campaign_id, session_id, encounter_id)
            for entry in clean:
                row = self._row(db, "resource_wallets", entry["wallet_id"], campaign_id, "Wallet")
                if entry["xp"]:
                    creature = db.execute("SELECT kind FROM creatures WHERE id=?", (row["creature_id"],)).fetchone()
                    if creature is None or creature["kind"] not in ("pc", "npc"):
                        raise ValueError("XP rewards require a wallet linked to a class-based PC or NPC.")
                    preview = self._preview_xp(db, campaign_id, entry["wallet_id"])
                    _integer(preview.target + entry["xp"], "Resulting experience points", MAX_XP)
                self._ledger(db, operation, campaign_id, entry["wallet_id"], entry["copper"], entry["xp"], reason, source)
            return {"recipients": len(clean), "copper": sum(x["copper"] for x in clean), "pending_xp": sum(x["xp"] for x in clean)}
        return self._command(campaign_id, request_id, request, action)

    @staticmethod
    def _sheet_xp(row):
        try:
            sheet = json.loads(row["sheet_json"]) if row["sheet_json"] else {}
        except (ValueError, RecursionError) as exc:
            raise ValueError("The saved character sheet could not be read; repair it before applying XP.") from exc
        if not isinstance(sheet, dict):
            raise ValueError("The saved character sheet must be an object.")
        if "xp" in sheet and "experience_points" not in sheet:
            raise ValueError("Review the legacy xp field before applying ledger XP.")
        points = sheet.get("experience_points", 0)
        _integer(points, "Saved experience points", MAX_XP)
        return sheet, points

    def _preview_xp(self, db, campaign_id, wallet_id):
        wallet = self._row(db, "resource_wallets", wallet_id, campaign_id, "Wallet")
        row = db.execute("SELECT * FROM creatures WHERE id=? AND kind IN ('pc','npc') AND archived=0", (wallet["creature_id"],)).fetchone()
        if row is None:
            raise ValueError("Apply XP to an active PC/NPC wallet.")
        _, current = self._sheet_xp(row)
        saved = db.execute("SELECT l.id,l.xp_delta,a.ledger_id applied FROM resource_ledger l LEFT JOIN resource_xp_applied a ON a.ledger_id=l.id WHERE l.campaign_id=? AND l.account_id=? ORDER BY l.id", (campaign_id, wallet_id)).fetchall()
        pending = []
        for entry in saved:
            _integer(entry["xp_delta"], "Saved reward XP", MAX_XP)
            if entry["xp_delta"] > 0 and entry["applied"] is None:
                pending.append(entry)
        total = sum(x["xp_delta"] for x in pending)
        _integer(current + total, "Resulting experience points", MAX_XP)
        return XPPreview(campaign_id, wallet_id, row["id"], row["name"], current, total, tuple(x["id"] for x in pending))

    def preview_xp(self, campaign_id, wallet_id):
        with self._connection() as db:
            return self._preview_xp(db, campaign_id, wallet_id)

    def apply_xp(self, preview: XPPreview, request_id):
        if not isinstance(preview, XPPreview) or not preview.pending:
            raise ValueError("Preview a nonzero pending XP award first.")
        _integer(preview.current, "Reviewed current XP", MAX_XP)
        _integer(preview.pending, "Reviewed pending XP", MAX_XP, minimum=1)
        request = dict(command="apply_xp", wallet_id=preview.wallet_id, creature_id=preview.creature_id, current=preview.current, pending=preview.pending, ledger_ids=list(preview.ledger_ids))
        def action(db, operation):
            live = self._preview_xp(db, preview.campaign_id, preview.wallet_id)
            if live != preview:
                raise ValueError("The character or pending awards changed. Review a new XP preview.")
            row = db.execute("SELECT * FROM creatures WHERE id=?", (preview.creature_id,)).fetchone()
            sheet, _ = self._sheet_xp(row)
            sheet["experience_points"] = preview.target
            text = json.dumps(sheet, ensure_ascii=False, sort_keys=True)
            if len(text) > 262144:
                raise ValueError("The resulting character sheet exceeds its size limit.")
            db.execute("UPDATE creatures SET sheet_json=?,updated_at=CURRENT_TIMESTAMP WHERE id=?", (text, preview.creature_id))
            for ledger_id in preview.ledger_ids:
                db.execute("INSERT INTO resource_xp_applied(ledger_id,operation_id) VALUES(?,?)", (ledger_id, operation))
            return {"creature_id": preview.creature_id, "experience_points": preview.target, "level": row["level"]}
        return self._command(preview.campaign_id, request_id, request, action)

    def create_container(self, campaign_id, wallet_id, name, *, tare_millilb=0, capacity_millilb=0):
        name = _text(name, "Container name")
        _integer(tare_millilb, "Empty container weight")
        _integer(capacity_millilb, "Container capacity")
        with self._connection() as db:
            db.execute("BEGIN IMMEDIATE")
            self._row(db, "resource_wallets", wallet_id, campaign_id, "Wallet")
            identity = str(uuid4())
            db.execute("INSERT INTO resource_containers(id,campaign_id,wallet_id,name,tare_millilb,capacity_millilb) VALUES(?,?,?,?,?,?)",
                       (identity, campaign_id, wallet_id, name, tare_millilb, capacity_millilb))
        return Container(identity, campaign_id, wallet_id, name, tare_millilb, capacity_millilb)

    def list_containers(self, campaign_id, wallet_id):
        with self._connection() as db:
            self._row(db, "resource_wallets", wallet_id, campaign_id, "Wallet")
            rows = db.execute("SELECT * FROM resource_containers WHERE campaign_id=? AND wallet_id=? ORDER BY name COLLATE NOCASE,id", (campaign_id, wallet_id)).fetchall()
            for row in rows:
                self._validate_row("resource_containers", row)
        return [Container(**dict(row)) for row in rows]

    def _container(self, db, campaign_id, wallet_id, container_id, added_weight):
        if container_id is None:
            return
        row = self._row(db, "resource_containers", container_id, campaign_id, "Container")
        if row["wallet_id"] != wallet_id:
            raise ValueError("Container belongs to another wallet.")
        contents = 0
        for item in db.execute("SELECT * FROM resource_items WHERE container_id=?", (container_id,)):
            self._validate_row("resource_items", item)
            if item["wallet_id"] != wallet_id or item["campaign_id"] != campaign_id:
                raise ValueError("Saved container contents have inconsistent ownership; preserve the database for recovery.")
            contents += item["quantity"] * item["unit_millilb"]
        if row["capacity_millilb"] and contents + added_weight > row["capacity_millilb"]:
            raise ValueError("The contents would exceed this container's weight capacity.")

    def add_item(self, campaign_id, wallet_id, name, quantity, unit_millilb, reason, request_id, *, unit_cp=0, container_id=None, notes="", session_id="", encounter_id=""):
        name = _text(name, "Item name")
        reason = _text(reason, "Item source / reason", 2000)
        notes = _text(notes, "Item notes", 20000, required=False)
        _integer(quantity, "Quantity", MAX_QUANTITY, minimum=1)
        _integer(unit_millilb, "Unit weight")
        _integer(unit_cp, "Unit value")
        request = dict(command="add_item", wallet_id=wallet_id, name=name, quantity=quantity, unit_millilb=unit_millilb, unit_cp=unit_cp, container_id=container_id, notes=notes, reason=reason, session_id=session_id, encounter_id=encounter_id)
        def action(db, operation):
            self._row(db, "resource_wallets", wallet_id, campaign_id, "Wallet")
            self._source(db, campaign_id, session_id, encounter_id)
            self._container(db, campaign_id, wallet_id, container_id, quantity * unit_millilb)
            identity = str(uuid4())
            db.execute("INSERT INTO resource_items(id,campaign_id,wallet_id,container_id,name,quantity,unit_millilb,unit_cp,notes) VALUES(?,?,?,?,?,?,?,?,?)",
                       (identity, campaign_id, wallet_id, container_id, name, quantity, unit_millilb, unit_cp, notes))
            return {"item_id": identity, "quantity": quantity}
        return self._command(campaign_id, request_id, request, action)

    def list_items(self, campaign_id, wallet_id, *, include_depleted=False):
        with self._connection() as db:
            self._row(db, "resource_wallets", wallet_id, campaign_id, "Wallet")
            rows = db.execute("SELECT * FROM resource_items WHERE campaign_id=? AND wallet_id=? AND (? OR quantity>0) ORDER BY name COLLATE NOCASE,id", (campaign_id, wallet_id, bool(include_depleted))).fetchall()
            for row in rows:
                self._validate_row("resource_items", row)
        return [Item(**dict(row)) for row in rows]

    def transfer_item(self, campaign_id, item_id, target_id, quantity, reason, request_id, *, container_id=None, session_id="", encounter_id=""):
        _integer(quantity, "Quantity", MAX_QUANTITY, minimum=1)
        reason = _text(reason, "Transfer reason", 2000)
        request = dict(command="transfer_item", item_id=item_id, target_id=target_id, quantity=quantity, container_id=container_id, reason=reason, session_id=session_id, encounter_id=encounter_id)
        def action(db, operation):
            row = self._row(db, "resource_items", item_id, campaign_id, "Item")
            self._row(db, "resource_wallets", target_id, campaign_id, "Destination wallet")
            self._source(db, campaign_id, session_id, encounter_id)
            if quantity > row["quantity"]:
                raise ValueError("The source does not contain that quantity.")
            if target_id == row["wallet_id"] and container_id == row["container_id"]:
                raise ValueError("Choose a different wallet or container.")
            self._container(db, campaign_id, target_id, container_id, quantity * row["unit_millilb"])
            if quantity == row["quantity"]:
                identity = item_id
                db.execute("UPDATE resource_items SET wallet_id=?,container_id=? WHERE id=?", (target_id, container_id, item_id))
            else:
                identity = str(uuid4())
                db.execute("UPDATE resource_items SET quantity=quantity-? WHERE id=?", (quantity, item_id))
                db.execute("INSERT INTO resource_items(id,campaign_id,wallet_id,container_id,name,quantity,unit_millilb,unit_cp,notes) VALUES(?,?,?,?,?,?,?,?,?)",
                           (identity, campaign_id, target_id, container_id, row["name"], quantity, row["unit_millilb"], row["unit_cp"], row["notes"]))
            return {"item_id": identity, "quantity": quantity, "source_item_id": item_id,
                    "source_wallet_id": row["wallet_id"], "source_container_id": row["container_id"],
                    "target_wallet_id": target_id, "target_container_id": container_id}
        return self._command(campaign_id, request_id, request, action)

    def consume_item(self, campaign_id, item_id, quantity, reason, request_id, *, session_id="", encounter_id=""):
        _integer(quantity, "Quantity", MAX_QUANTITY, minimum=1)
        reason = _text(reason, "Use / removal reason", 2000)
        request = dict(command="consume_item", item_id=item_id, quantity=quantity, reason=reason, session_id=session_id, encounter_id=encounter_id)
        def action(db, operation):
            row = self._row(db, "resource_items", item_id, campaign_id, "Item")
            self._source(db, campaign_id, session_id, encounter_id)
            if quantity > row["quantity"]:
                raise ValueError("The source does not contain that quantity.")
            db.execute("UPDATE resource_items SET quantity=quantity-? WHERE id=?", (quantity, item_id))
            return {"item_id": item_id, "quantity": row["quantity"] - quantity,
                    "wallet_id": row["wallet_id"], "item_name": row["name"]}
        return self._command(campaign_id, request_id, request, action)

    def carried_weight(self, campaign_id, wallet_id):
        with self._connection() as db:
            self._row(db, "resource_wallets", wallet_id, campaign_id, "Wallet")
            items = containers = 0
            for row in db.execute("SELECT * FROM resource_items WHERE campaign_id=? AND wallet_id=?", (campaign_id, wallet_id)):
                self._validate_row("resource_items", row)
                items += row["quantity"] * row["unit_millilb"]
            for row in db.execute("SELECT * FROM resource_containers WHERE campaign_id=? AND wallet_id=?", (campaign_id, wallet_id)):
                self._validate_row("resource_containers", row)
                containers += row["tare_millilb"]
        return items + containers

    def operations(self, campaign_id, limit=250):
        _integer(limit, "History limit", 1000, minimum=1)
        with self._connection() as db:
            self._campaign(db, campaign_id)
            rows = db.execute("SELECT * FROM resource_operations WHERE campaign_id=? ORDER BY created_at DESC,rowid DESC LIMIT ?", (campaign_id, limit)).fetchall()
        return [dict(row) for row in rows]


def validate_saved_state(library_repository_or_path):
    """Read-only recovery checks; never apply XP or normalize character sheets."""
    path = Path(getattr(library_repository_or_path, "path", library_repository_or_path)).resolve()
    with closing(sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)) as db:
        db.row_factory = sqlite3.Row
        tables = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        required = {"resource_wallets", "resource_containers", "resource_items", "resource_xp_applied", "resource_operations", "resource_ledger"}
        present = required & tables
        if present != required:
            if any(db.execute(f"SELECT 1 FROM {table} LIMIT 1").fetchone() for table in present):
                raise ValueError("The saved campaign resource tables are incomplete.")
            return
        campaigns = {row[0] for row in db.execute("SELECT id FROM campaigns")}
        creatures = {row["id"]: row for row in db.execute("SELECT id,kind FROM creatures")}
        wallets = {row["id"]: row for row in db.execute("SELECT * FROM resource_wallets")}
        containers = {row["id"]: row for row in db.execute("SELECT * FROM resource_containers")}
        items = {row["id"]: row for row in db.execute("SELECT * FROM resource_items")}

        def reference(rows, identity, campaign_id, label):
            _text(identity, label + " ID")
            row = rows.get(identity)
            if row is None or row["campaign_id"] != campaign_id:
                raise ValueError(f"Saved {label} reference is missing or belongs to another campaign.")
            return row

        for row in wallets.values():
            ResourceRepository._validate_row("resource_wallets", row)
            _text(row["created_at"], "Saved wallet date", 100)
            if row["campaign_id"] not in campaigns or (row["creature_id"] is not None and row["creature_id"] not in creatures):
                raise ValueError("A saved resource wallet has a missing campaign or creature.")
        contents = {}
        for row in containers.values():
            ResourceRepository._validate_row("resource_containers", row)
            reference(wallets, row["wallet_id"], row["campaign_id"], "container owner")
            contents[row["id"]] = 0
        for row in items.values():
            ResourceRepository._validate_row("resource_items", row)
            reference(wallets, row["wallet_id"], row["campaign_id"], "item owner")
            if row["container_id"] is not None:
                container = reference(containers, row["container_id"], row["campaign_id"], "item container")
                if container["wallet_id"] != row["wallet_id"]:
                    raise ValueError("An item and its saved container have different owners.")
                contents[container["id"]] += row["quantity"] * row["unit_millilb"]
        for identity, weight in contents.items():
            capacity = containers[identity]["capacity_millilb"]
            if capacity and weight > capacity:
                raise ValueError("Saved items exceed their container's weight capacity.")

        expected_keys = {
            "adjust_money": {"command", "wallet_id", "copper_delta", "reason", "session_id", "encounter_id"},
            "transfer_money": {"command", "source_id", "target_id", "copper", "reason", "session_id", "encounter_id"},
            "award": {"command", "allocations", "reason", "session_id", "encounter_id"},
            "apply_xp": {"command", "wallet_id", "creature_id", "current", "pending", "ledger_ids"},
            "add_item": {"command", "wallet_id", "name", "quantity", "unit_millilb", "unit_cp", "container_id", "notes", "reason", "session_id", "encounter_id"},
            "transfer_item": {"command", "item_id", "target_id", "quantity", "container_id", "reason", "session_id", "encounter_id"},
            "consume_item": {"command", "item_id", "quantity", "reason", "session_id", "encounter_id"},
        }
        operations, expected_ledgers = {}, {}
        for row in db.execute("SELECT * FROM resource_operations"):
            _text(row["id"], "Saved resource command ID")
            _text(row["created_at"], "Saved command date", 100)
            if row["campaign_id"] not in campaigns:
                raise ValueError("A saved resource command has a missing campaign.")
            payload = decode_operation(row["payload_json"])
            request, result = payload["request"], payload["result"]
            command = request["command"]
            if command not in expected_keys or set(request) != expected_keys[command]:
                raise ValueError("A saved resource command has unsupported fields.")
            campaign_id = row["campaign_id"]
            for key in ("wallet_id", "source_id", "target_id"):
                if key in request:
                    reference(wallets, request[key], campaign_id, "command wallet")
            if "item_id" in request:
                reference(items, request["item_id"], campaign_id, "command item")
            if "reason" in request:
                _text(request["reason"], "Saved command reason", 2000)
                session = ResourceRepository._source(db, campaign_id, request["session_id"], request["encounter_id"])
            else:
                session = ""
            ledger = []
            if command == "adjust_money":
                amount = _integer(request["copper_delta"], "Saved copper adjustment", minimum=-MAX_MONEY)
                if not amount:
                    raise ValueError("A saved money adjustment is zero.")
                ledger = [(request["wallet_id"], amount, 0, request["reason"], session or None)]
                _integer(result.get("copper"), "Saved resulting balance")
                if result.get("wallet_id") != request["wallet_id"]:
                    raise ValueError("Saved money adjustment result references another wallet.")
            elif command == "transfer_money":
                amount = _integer(request["copper"], "Saved money transfer", minimum=1)
                if request["source_id"] == request["target_id"]:
                    raise ValueError("A saved money transfer uses the same wallet twice.")
                ledger = [(request["source_id"], -amount, 0, request["reason"], session or None),
                          (request["target_id"], amount, 0, request["reason"], session or None)]
                _integer(result.get("source_copper"), "Saved resulting balance")
                _integer(result.get("target_copper"), "Saved resulting balance")
            elif command == "award":
                allocations = request["allocations"]
                if not isinstance(allocations, list) or not 1 <= len(allocations) <= 250:
                    raise ValueError("Saved reward recipients are invalid.")
                seen = set()
                for entry in allocations:
                    if not isinstance(entry, dict) or set(entry) != {"wallet_id", "copper", "xp"}:
                        raise ValueError("Saved reward allocation is invalid.")
                    owner = reference(wallets, entry["wallet_id"], campaign_id, "reward wallet")
                    _integer(entry["copper"], "Saved reward copper")
                    _integer(entry["xp"], "Saved reward XP", MAX_XP)
                    if owner["id"] in seen or not (entry["copper"] or entry["xp"]):
                        raise ValueError("Saved reward allocations are empty or repeated.")
                    seen.add(owner["id"])
                    if entry["xp"] and owner["creature_id"] not in creatures:
                        raise ValueError("Saved XP reward has no character recipient.")
                    ledger.append((owner["id"], entry["copper"], entry["xp"], request["reason"], session or None))
                for key, expected in (("recipients", len(allocations)), ("copper", sum(x["copper"] for x in allocations)), ("pending_xp", sum(x["xp"] for x in allocations))):
                    if type(result.get(key)) is not int or result[key] != expected:
                        raise ValueError("Saved reward result disagrees with its allocations.")
            elif command == "apply_xp":
                owner = wallets[request["wallet_id"]]
                if owner["creature_id"] != request["creature_id"] or request["creature_id"] not in creatures:
                    raise ValueError("Saved XP application references another character.")
                _integer(request["current"], "Saved XP before application", MAX_XP)
                _integer(request["pending"], "Saved applied XP", MAX_XP, minimum=1)
                ids = request["ledger_ids"]
                if not isinstance(ids, list) or not ids or any(not isinstance(value, str) for value in ids) or len(set(ids)) != len(ids):
                    raise ValueError("Saved XP application reward references are invalid.")
                if type(result.get("experience_points")) is not int or result["experience_points"] != request["current"] + request["pending"] or result.get("creature_id") != request["creature_id"]:
                    raise ValueError("Saved XP application result is inconsistent.")
                _integer(result["experience_points"], "Saved resulting XP", MAX_XP)
                _integer(result.get("level"), "Saved character level", 99)
            else:
                _integer(request["quantity"], "Saved item command quantity", MAX_QUANTITY, minimum=1)
                if command == "add_item":
                    _text(request["name"], "Saved item name")
                    _text(request["notes"], "Saved item notes", 20000, required=False)
                    _integer(request["unit_millilb"], "Saved item weight")
                    _integer(request["unit_cp"], "Saved item value")
                if request.get("container_id") is not None:
                    container = reference(containers, request["container_id"], campaign_id, "command container")
                    if container["wallet_id"] != request.get("target_id", request.get("wallet_id")):
                        raise ValueError("Saved item command references another wallet's container.")
                reference(items, result.get("item_id"), campaign_id, "resulting item")
                _integer(result.get("quantity"), "Saved resulting item quantity", MAX_QUANTITY)
            operations[row["id"]] = (campaign_id, request)
            expected_ledgers[row["id"]] = sorted(ledger)

        ledgers, actual_ledgers = {}, {identity: [] for identity in operations}
        for row in db.execute("SELECT * FROM resource_ledger"):
            _text(row["id"], "Saved ledger ID")
            _text(row["created_at"], "Saved ledger date", 100)
            _integer(row["cp_delta"], "Saved copper ledger entry", minimum=-MAX_MONEY)
            _integer(row["xp_delta"], "Saved reward XP", MAX_XP)
            _text(row["reason"], "Saved ledger reason", 2000)
            reference(wallets, row["account_id"], row["campaign_id"], "ledger wallet")
            if row["operation_id"] not in operations or operations[row["operation_id"]][0] != row["campaign_id"]:
                raise ValueError("Saved ledger entry references a missing/foreign command.")
            if row["session_id"] is not None:
                ResourceRepository._source(db, row["campaign_id"], row["session_id"], "")
            actual_ledgers[row["operation_id"]].append((row["account_id"], row["cp_delta"], row["xp_delta"], row["reason"], row["session_id"]))
            ledgers[row["id"]] = row
        for identity, expected in expected_ledgers.items():
            if sorted(actual_ledgers[identity]) != expected:
                raise ValueError("Saved resource command and its ledger entries disagree.")
        for wallet_id in wallets:
            ResourceRepository._balance(db, wallet_id)
        applied = {identity: [] for identity in operations}
        for row in db.execute("SELECT * FROM resource_xp_applied"):
            ledger = ledgers.get(row["ledger_id"])
            operation = operations.get(row["operation_id"])
            if ledger is None or not ledger["xp_delta"] or operation is None or operation[1]["command"] != "apply_xp" or operation[0] != ledger["campaign_id"] or operation[1]["wallet_id"] != ledger["account_id"]:
                raise ValueError("Saved applied XP references an invalid reward or command.")
            applied[row["operation_id"]].append(row["ledger_id"])
        for identity, (_, request) in operations.items():
            if request["command"] == "apply_xp":
                if sorted(applied[identity]) != sorted(request["ledger_ids"]) or sum(ledgers[value]["xp_delta"] for value in applied[identity]) != request["pending"]:
                    raise ValueError("Saved XP application does not match its applied reward entries.")
