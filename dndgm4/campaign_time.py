"""Campaign calendar, reviewed clock changes and persisted original weather rolls.

This is a campaign clock, not a character or combat automation engine. Travel
speed and resource rates are DM inputs. Rest never heals, refreshes spells or
advances an encounter. World-desk events are projected onto this clock without
changing their saved status.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from contextlib import closing
from decimal import Decimal, InvalidOperation, ROUND_CEILING
from hashlib import sha256
import json
import re
from pathlib import Path
from secrets import randbelow
import sqlite3
from uuid import uuid4

from .campaigns import CampaignRepository

MAX_MINUTES = 1000000000000
MAX_HISTORY_JSON = 4 * 1024 * 1024
DEFAULT_MONTHS = tuple((f"Month {index}", 30) for index in range(1, 13))

SCHEMA_STATEMENTS = (
    """CREATE TABLE IF NOT EXISTS campaign_time_settings (
        campaign_id TEXT PRIMARY KEY REFERENCES campaigns(id),
        calendar_json TEXT NOT NULL, revision INTEGER NOT NULL DEFAULT 0)""",
    """CREATE TABLE IF NOT EXISTS campaign_time_details (
        change_id TEXT PRIMARY KEY REFERENCES time_changes(id), payload_json TEXT NOT NULL)""",
    """CREATE TABLE IF NOT EXISTS campaign_timeline (
        id TEXT PRIMARY KEY, campaign_id TEXT NOT NULL REFERENCES campaigns(id),
        at_minutes INTEGER NOT NULL CHECK(at_minutes >= 0), title TEXT NOT NULL,
        notes TEXT NOT NULL DEFAULT '', cancelled INTEGER NOT NULL DEFAULT 0)""",
    """CREATE INDEX IF NOT EXISTS campaign_timeline_date
        ON campaign_timeline(campaign_id,at_minutes)""",
    """CREATE TABLE IF NOT EXISTS campaign_weather (
        campaign_id TEXT NOT NULL REFERENCES campaigns(id), day INTEGER NOT NULL,
        description TEXT NOT NULL, roll INTEGER, request_id TEXT NOT NULL,
        PRIMARY KEY(campaign_id,day))""",
)


def initialize_schema(db):
    """Integrator hook; additive tables live in the main library backup."""
    for statement in SCHEMA_STATEMENTS:
        db.execute(statement)


def _text(value, label, maximum=2000, *, required=False):
    if not isinstance(value, str) or len(value) > maximum or "\x00" in value:
        raise ValueError(f"{label} must be text of at most {maximum:,} characters.")
    try:
        value.encode("utf-8")
    except UnicodeError as exc:
        raise ValueError(f"{label} contains invalid Unicode.") from exc
    if required and not value.strip():
        raise ValueError(f"{label} is required.")
    return value.strip() if required else value


def _integer(value, label, maximum=MAX_MINUTES, minimum=0):
    if type(value) is not int or not minimum <= value <= maximum:
        raise ValueError(f"{label} must be a whole number between {minimum:,} and {maximum:,}.")
    return value


def _decimal(value, label, *, positive=False):
    if isinstance(value, bool) or not isinstance(value, (str, int, Decimal)):
        raise ValueError(f"{label} must be a decimal number.")
    try:
        result = Decimal(value)
    except InvalidOperation as exc:
        raise ValueError(f"{label} must be a decimal number.") from exc
    if not result.is_finite() or result < 0 or result > 1000000000 or (positive and result == 0):
        raise ValueError(f"{label} must be {'positive' if positive else 'nonnegative'} and at most 1,000,000,000.")
    if result.as_tuple().exponent < -6:
        raise ValueError(f"{label} supports at most six decimal places.")
    return result


def _json(data):
    return json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _strict_json(text, label, maximum):
    _text(text, label, maximum, required=True)
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError(f"{label} contains duplicate fields.")
            result[key] = value
        return result
    def invalid_constant(_):
        raise ValueError(f"{label} contains a nonfinite JSON number.")
    try:
        return json.loads(text, object_pairs_hook=pairs, parse_constant=invalid_constant)
    except (ValueError, TypeError, RecursionError) as exc:
        raise ValueError(f"{label} contains invalid JSON: {exc}") from exc


@dataclass(frozen=True, slots=True)
class CalendarSpec:
    name: str = "Campaign calendar"
    months: tuple[tuple[str, int], ...] = DEFAULT_MONTHS
    hours_per_day: int = 24
    epoch_year: int = 1

    def __post_init__(self):
        _text(self.name, "Calendar name", 120, required=True)
        _integer(self.hours_per_day, "Hours per day", 48, 1)
        _integer(self.epoch_year, "Starting year", 1000000, 0)
        if not isinstance(self.months, tuple) or not 1 <= len(self.months) <= 48:
            raise ValueError("A calendar needs between one and 48 months.")
        names = set()
        for month in self.months:
            if not isinstance(month, tuple) or len(month) != 2:
                raise ValueError("Each month needs a name and a number of days.")
            name, days = month
            clean = _text(name, "Month name", 80, required=True)
            if clean.casefold() in names:
                raise ValueError("Month names must be unique.")
            names.add(clean.casefold())
            _integer(days, "Days per month", 1000, 1)

    @property
    def minutes_per_day(self):
        return self.hours_per_day * 60

    @property
    def days_per_year(self):
        return sum(days for _, days in self.months)

    def to_json(self):
        return _json(asdict(self))

    @classmethod
    def from_json(cls, text):
        _text(text, "Calendar definition", 15000, required=True)
        try:
            data = _strict_json(text, "Calendar definition", 15000)
            if not isinstance(data, dict) or set(data) != {"name", "months", "hours_per_day", "epoch_year"}:
                raise ValueError("Unsupported calendar fields.")
            if not isinstance(data["months"], list):
                raise ValueError("Calendar months must be a list.")
            return cls(data["name"], tuple(tuple(item) for item in data["months"]),
                       data["hours_per_day"], data["epoch_year"])
        except (ValueError, TypeError, KeyError) as exc:
            raise ValueError(f"Invalid calendar definition: {exc}") from exc

    def date_parts(self, minutes):
        _integer(minutes, "Campaign minutes")
        day, within = divmod(minutes, self.minutes_per_day)
        year, year_day = divmod(day, self.days_per_year)
        for month, count in self.months:
            if year_day < count:
                hour, minute = divmod(within, 60)
                return self.epoch_year + year, month, year_day + 1, hour, minute
            year_day -= count
        raise AssertionError("Calendar conversion failed")

    def format(self, minutes):
        year, month, day, hour, minute = self.date_parts(minutes)
        return f"Year {year}, {month} {day} · {hour:02d}:{minute:02d}"


@dataclass(frozen=True, slots=True)
class ClockState:
    campaign_id: str
    minutes: int
    revision: int
    calendar: CalendarSpec


@dataclass(frozen=True, slots=True)
class TimelineEvent:
    id: str
    at_minutes: int
    title: str
    notes: str = ""
    source: str = "timeline"


@dataclass(frozen=True, slots=True)
class AdvancePreview:
    id: str
    campaign_id: str
    revision: int
    before_minutes: int
    after_minutes: int
    reason: str
    kind: str
    details_json: str
    events: tuple[TimelineEvent, ...]
    consequences: tuple[str, ...]
    fingerprint: str


@dataclass(frozen=True, slots=True)
class WeatherPreview:
    campaign_id: str
    day: int
    description: str
    roll: int
    request_id: str
    revision: int
    previous_json: str


class CampaignTimeRepository:
    def __init__(self, database_path: str | Path):
        self.campaigns = CampaignRepository(database_path)
        self.library = self.campaigns.library
        self.path = self.library.path
        with self.library._connection() as db:
            initialize_schema(db)

    def _ensure(self, db, campaign_id):
        self.campaigns._require(db, "campaigns", campaign_id, "Campaign")
        db.execute("INSERT OR IGNORE INTO campaign_clock(campaign_id) VALUES(?)", (campaign_id,))
        if db.execute("SELECT 1 FROM campaign_time_settings WHERE campaign_id=?", (campaign_id,)).fetchone() is None:
            legacy = db.execute("SELECT * FROM campaign_clock WHERE campaign_id=?", (campaign_id,)).fetchone()
            months = _integer(legacy["months_per_year"], "Saved months per year", 48, 1)
            days = _integer(legacy["days_per_month"], "Saved days per month", 1000, 1)
            calendar = CalendarSpec(legacy["calendar_name"], tuple((f"Month {index}", days) for index in range(1, months + 1)))
            db.execute("INSERT INTO campaign_time_settings(campaign_id,calendar_json) VALUES(?,?)",
                       (campaign_id, calendar.to_json()))

    def _state(self, db, campaign_id):
        self._ensure(db, campaign_id)
        row = db.execute("SELECT c.minutes,s.revision,s.calendar_json FROM campaign_clock c "
                         "JOIN campaign_time_settings s ON s.campaign_id=c.campaign_id WHERE c.campaign_id=?",
                         (campaign_id,)).fetchone()
        return ClockState(campaign_id, _integer(row["minutes"], "Saved campaign minutes"),
                          _integer(row["revision"], "Saved clock revision"), CalendarSpec.from_json(row["calendar_json"]))

    def get_clock(self, campaign_id):
        with self.library._connection() as db:
            return self._state(db, campaign_id)

    def configure_calendar(self, campaign_id, calendar, *, expected_revision):
        if not isinstance(calendar, CalendarSpec):
            raise ValueError("Choose a valid calendar definition.")
        with self.library._connection() as db:
            db.execute("BEGIN IMMEDIATE")
            state = self._state(db, campaign_id)
            if state.revision != expected_revision:
                raise ValueError("The campaign clock changed. Reload before saving the calendar.")
            # Refuse a day-length change that would make saved World Desk
            # event times impossible, rather than breaking the next timeline read.
            self._events(db, ClockState(campaign_id, state.minutes, state.revision, calendar))
            db.execute("UPDATE campaign_time_settings SET calendar_json=?,revision=revision+1 WHERE campaign_id=?",
                       (calendar.to_json(), campaign_id))
            # These compatibility fields are informational; the JSON definition
            # is authoritative for unequal month lengths and custom names.
            db.execute("UPDATE campaign_clock SET calendar_name=?,days_per_month=?,months_per_year=? WHERE campaign_id=?",
                       (calendar.name, calendar.months[0][1], len(calendar.months), campaign_id))
            return self._state(db, campaign_id)

    def add_event(self, campaign_id, at_minutes, title, notes=""):
        _integer(at_minutes, "Event time")
        title = _text(title, "Event title", 200, required=True)
        notes = _text(notes, "Event notes", 20000)
        identity = str(uuid4())
        with self.library._connection() as db:
            self._ensure(db, campaign_id)
            db.execute("INSERT INTO campaign_timeline(id,campaign_id,at_minutes,title,notes) VALUES(?,?,?,?,?)",
                       (identity, campaign_id, at_minutes, title, notes))
        return TimelineEvent(identity, at_minutes, title, notes)

    def cancel_event(self, campaign_id, event_id):
        with self.library._connection() as db:
            self._ensure(db, campaign_id)
            if db.execute("UPDATE campaign_timeline SET cancelled=1 WHERE campaign_id=? AND id=?",
                          (campaign_id, event_id)).rowcount != 1:
                raise ValueError("Choose a timeline event from this campaign.")

    def _events(self, db, state, start=0, end=MAX_MINUTES):
        events = []
        for row in db.execute("SELECT * FROM campaign_timeline WHERE campaign_id=?", (state.campaign_id,)):
            _integer(row["cancelled"], "Saved event cancelled flag", 1)
            if row["cancelled"]:
                continue
            identity = _text(row["id"], "Saved event identifier", 200, required=True)
            when = _integer(row["at_minutes"], "Saved event time")
            title = _text(row["title"], "Saved event title", 200, required=True)
            notes = _text(row["notes"], "Saved event notes", 20000)
            if start <= when <= end:
                events.append(TimelineEvent(identity, when, title, notes))
        # World events retain numbered campaign days and are never marked
        # completed by clock advancement. Their private notes stay in this DM UI.
        for row in db.execute("SELECT * FROM world_records WHERE campaign_id=? AND kind='event' "
                              "AND archived=0 AND status NOT IN ('cancelled','completed')", (state.campaign_id,)):
            from .world import parse_details
            details = parse_details("event", row["details_json"])
            hour, minute = (map(int, details["time"].split(":")) if details["time"] else (0, 0))
            if hour >= state.calendar.hours_per_day:
                raise ValueError(f"World event '{row['name']}' has a time outside this calendar's day.")
            when = details["day"] * state.calendar.minutes_per_day + hour * 60 + minute
            if start <= when <= end:
                events.append(TimelineEvent("world:" + row["id"], when, row["name"], row["summary"], "world"))
        return tuple(sorted(events, key=lambda event: (event.at_minutes, event.title.casefold(), event.id)))

    def timeline(self, campaign_id, *, start=0, end=MAX_MINUTES):
        _integer(start, "Timeline start")
        _integer(end, "Timeline end")
        if start > end:
            raise ValueError("Timeline end must follow its start.")
        with self.library._connection() as db:
            state = self._state(db, campaign_id)
            return self._events(db, state, start, end)

    def _preview(self, db, campaign_id, duration, reason, kind, details, identity):
        _integer(duration, "Elapsed minutes", minimum=1)
        reason = _text(reason, "Reason", 2000, required=True)
        if kind not in ("advance", "travel", "rest"):
            raise ValueError("Unsupported time-change type.")
        state = self._state(db, campaign_id)
        after = _integer(state.minutes + duration, "Resulting campaign minutes")
        if not isinstance(details, dict) or len(_json(details)) > 20000:
            raise ValueError("Invalid time-change details.")
        events = self._events(db, state, state.minutes + 1, after)
        consequences = [f"Advance {duration:,} minutes; {len(events)} scheduled event(s) crossed.",
                        "Event statuses, character sheets, resources and encounters remain unchanged."]
        if kind == "rest":
            consequences.append("Review rest eligibility, interruptions, healing and spell recovery with the DM; nothing is replenished automatically.")
        if kind == "travel":
            consequences.append("Review terrain, fatigue, encounters, rations and water; travel speed is the DM's chosen effective speed.")
            if "ration_days" in details:
                consequences.append(f"Resource planning estimate: {details['ration_days']} traveler-days of supplies; no inventory is spent.")
        payload = {"state": {"minutes": state.minutes, "revision": state.revision,
                              "calendar": state.calendar.to_json()},
                   "after": after, "reason": reason, "kind": kind, "details": details,
                   "events": [asdict(event) for event in events], "consequences": consequences}
        fingerprint = sha256(_json(payload).encode("utf-8")).hexdigest()
        return AdvancePreview(identity, campaign_id, state.revision, state.minutes, after,
                              reason, kind, _json(details), events, tuple(consequences), fingerprint)

    def preview_advance(self, campaign_id, minutes, reason):
        with self.library._connection() as db:
            return self._preview(db, campaign_id, minutes, reason, "advance", {}, str(uuid4()))

    def preview_rest(self, campaign_id, hours="8", reason="Rest"):
        hours = _decimal(hours, "Rest hours", positive=True)
        minutes = int((hours * 60).to_integral_value(rounding=ROUND_CEILING))
        with self.library._connection() as db:
            return self._preview(db, campaign_id, minutes, reason, "rest", {"hours": str(hours)}, str(uuid4()))

    def preview_travel(self, campaign_id, distance_miles, miles_per_hour, *, travelers=1, reason="Travel",
                       encounter_roll=False, roller=None):
        distance = _decimal(distance_miles, "Distance", positive=True)
        speed = _decimal(miles_per_hour, "Effective miles per hour", positive=True)
        travelers = _integer(travelers, "Travelers", 10000, 1)
        duration = int((distance / speed * 60).to_integral_value(rounding=ROUND_CEILING))
        with self.library._connection() as db:
            state = self._state(db, campaign_id)
            details = {"distance_miles": str(distance), "miles_per_hour": str(speed), "travelers": travelers,
                       "ration_days": str((Decimal(duration) * travelers / state.calendar.minutes_per_day).quantize(Decimal("0.001")))}
            if type(encounter_roll) is not bool:
                raise ValueError("Encounter roll must be a checkbox value.")
            if encounter_roll:
                roll = _integer((roller or (lambda: randbelow(20) + 1))(), "Travel d20 roll", 20, 1)
                details["encounter_d20"] = roll
                details["encounter_note"] = "Original travel prompt roll; DM decides its meaning."
            return self._preview(db, campaign_id, duration, reason, "travel", details, str(uuid4()))

    def apply_preview(self, preview):
        if not isinstance(preview, AdvancePreview):
            raise ValueError("Preview the time change before applying it.")
        with self.library._connection() as db:
            db.execute("BEGIN IMMEDIATE")
            prior = db.execute("SELECT t.*,d.payload_json FROM time_changes t JOIN campaign_time_details d ON d.change_id=t.id "
                               "WHERE t.id=?", (preview.id,)).fetchone()
            payload = _json(asdict(preview))
            _text(payload, "Time-change history", MAX_HISTORY_JSON, required=True)
            if prior is not None:
                if prior["campaign_id"] != preview.campaign_id or prior["payload_json"] != payload:
                    raise ValueError("This time-change identifier was already used for different content.")
                return self._state(db, preview.campaign_id)
            state = self._state(db, preview.campaign_id)
            if (state.minutes, state.revision) != (preview.before_minutes, preview.revision):
                raise ValueError("The campaign clock changed. Create a fresh preview.")
            try:
                details = json.loads(preview.details_json)
            except (ValueError, TypeError) as exc:
                raise ValueError("Invalid time-change preview.") from exc
            current = self._preview(db, preview.campaign_id, preview.after_minutes - preview.before_minutes,
                                    preview.reason, preview.kind, details, preview.id)
            if current != preview:
                raise ValueError("The timeline or preview changed. Create a fresh preview.")
            db.execute("INSERT INTO time_changes(id,campaign_id,before_minutes,after_minutes,reason) VALUES(?,?,?,?,?)",
                       (preview.id, preview.campaign_id, preview.before_minutes, preview.after_minutes, preview.reason))
            db.execute("INSERT INTO campaign_time_details(change_id,payload_json) VALUES(?,?)", (preview.id, payload))
            db.execute("UPDATE campaign_clock SET minutes=? WHERE campaign_id=?", (preview.after_minutes, preview.campaign_id))
            db.execute("UPDATE campaign_time_settings SET revision=revision+1 WHERE campaign_id=?", (preview.campaign_id,))
            return self._state(db, preview.campaign_id)

    def history(self, campaign_id):
        with self.library._connection() as db:
            self._ensure(db, campaign_id)
            return [dict(row) for row in db.execute("SELECT t.*,d.payload_json FROM time_changes t "
                    "LEFT JOIN campaign_time_details d ON d.change_id=t.id WHERE campaign_id=? ORDER BY t.rowid DESC",
                    (campaign_id,))]

    def weather(self, campaign_id, day):
        _integer(day, "Campaign day", MAX_MINUTES)
        with self.library._connection() as db:
            self._ensure(db, campaign_id)
            row = db.execute("SELECT * FROM campaign_weather WHERE campaign_id=? AND day=?", (campaign_id, day)).fetchone()
            return self._weather_row(row)

    @staticmethod
    def _weather_row(row):
        if row is None:
            return None
        _integer(row["day"], "Saved weather day")
        _integer(row["roll"], "Saved weather d20 roll", 20, 1)
        _text(row["description"], "Saved weather description", 2000, required=True)
        _text(row["request_id"], "Saved weather request identifier", 200, required=True)
        return dict(row)

    def preview_weather(self, campaign_id, day, *, roller=None):
        _integer(day, "Campaign day", MAX_MINUTES)
        state = self.get_clock(campaign_id)
        roll = _integer((roller or (lambda: randbelow(20) + 1))(), "Weather d20 roll", 20, 1)
        descriptions = ("Clear and still", "Cloudy with a light breeze", "Rain or snow, chosen for the region",
                        "Strong wind and changing skies", "Severe weather; the DM chooses local effects")
        description = descriptions[min((roll - 1) // 4, 4)]
        return WeatherPreview(campaign_id, day, description, roll, str(uuid4()), state.revision,
                              _json(self.weather(campaign_id, day)))

    def apply_weather(self, preview):
        if not isinstance(preview, WeatherPreview):
            raise ValueError("Preview weather before saving it.")
        _text(preview.description, "Weather description", 2000, required=True)
        _integer(preview.day, "Campaign day")
        _integer(preview.roll, "Weather d20 roll", 20, 1)
        with self.library._connection() as db:
            db.execute("BEGIN IMMEDIATE")
            state = self._state(db, preview.campaign_id)
            row = db.execute("SELECT * FROM campaign_weather WHERE campaign_id=? AND day=?",
                             (preview.campaign_id, preview.day)).fetchone()
            previous = self._weather_row(row)
            if previous and previous["request_id"] == preview.request_id:
                if previous["roll"] == preview.roll and previous["description"] == preview.description:
                    return previous
                raise ValueError("Weather request identifier was already used.")
            if state.revision != preview.revision or _json(previous) != preview.previous_json:
                raise ValueError("The clock or saved weather changed. Create a fresh weather preview.")
            db.execute("INSERT INTO campaign_weather(campaign_id,day,description,roll,request_id) VALUES(?,?,?,?,?) "
                       "ON CONFLICT(campaign_id,day) DO UPDATE SET description=excluded.description,roll=excluded.roll,request_id=excluded.request_id",
                       (preview.campaign_id, preview.day, preview.description, preview.roll, preview.request_id))
        return self.weather(preview.campaign_id, preview.day)


def _saved_details(payload, row):
    """Validate historical preview data without reinterpreting its old calendar."""
    expected = {"id", "campaign_id", "revision", "before_minutes", "after_minutes", "reason", "kind",
                "details_json", "events", "consequences", "fingerprint"}
    if not isinstance(payload, dict) or set(payload) != expected:
        raise ValueError("Saved time-change details have unsupported or missing fields.")
    for key in ("id", "campaign_id", "before_minutes", "after_minutes", "reason"):
        if payload[key] != row[key] or type(payload[key]) is not type(row[key]):
            raise ValueError(f"Saved time-change details disagree with the history's {key.replace('_', ' ')}.")
    revision = _integer(payload["revision"], "Saved time-change revision")
    fingerprint = _text(payload["fingerprint"], "Saved preview fingerprint", 64, required=True)
    if not re.fullmatch(r"[0-9a-f]{64}", fingerprint):
        raise ValueError("Saved preview fingerprint must be a SHA-256 hexadecimal value.")
    kind = payload["kind"]
    if kind not in ("advance", "rest", "travel"):
        raise ValueError("Saved time-change kind is unsupported.")
    details = _strict_json(payload["details_json"], "Saved time-change parameters", 20000)
    if not isinstance(details, dict):
        raise ValueError("Saved time-change parameters must be an object.")
    duration = row["after_minutes"] - row["before_minutes"]
    if kind == "advance":
        if details:
            raise ValueError("A saved simple clock change cannot contain travel/rest parameters.")
    elif kind == "rest":
        if set(details) != {"hours"} or not isinstance(details["hours"], str):
            raise ValueError("Saved rest parameters must contain decimal hours as text.")
        hours = _decimal(details["hours"], "Saved rest hours", positive=True)
        if int((hours * 60).to_integral_value(rounding=ROUND_CEILING)) != duration:
            raise ValueError("Saved rest hours disagree with elapsed campaign minutes.")
    else:
        required = {"distance_miles", "miles_per_hour", "travelers", "ration_days"}
        optional = {"encounter_d20", "encounter_note"}
        if set(details) not in (required, required | optional):
            raise ValueError("Saved travel parameters have unsupported or missing fields.")
        for key in ("distance_miles", "miles_per_hour", "ration_days"):
            if not isinstance(details[key], str):
                raise ValueError("Saved travel decimal parameters must be text.")
        distance = _decimal(details["distance_miles"], "Saved travel distance", positive=True)
        speed = _decimal(details["miles_per_hour"], "Saved travel speed", positive=True)
        _integer(details["travelers"], "Saved travelers", 10000, 1)
        _text(details["ration_days"], "Saved supply estimate", 100, required=True)
        try:
            estimate = Decimal(details["ration_days"])
        except InvalidOperation as exc:
            raise ValueError("Saved supply estimate must be a decimal number.") from exc
        if not estimate.is_finite() or not 0 <= estimate <= Decimal("1e18") or estimate.as_tuple().exponent < -6:
            raise ValueError("Saved supply estimate is outside the supported range.")
        if int((distance / speed * 60).to_integral_value(rounding=ROUND_CEILING)) != duration:
            raise ValueError("Saved travel distance/speed disagree with elapsed campaign minutes.")
        if optional <= set(details):
            _integer(details["encounter_d20"], "Saved travel d20 roll", 20, 1)
            _text(details["encounter_note"], "Saved encounter prompt note", 2000, required=True)
    events = payload["events"]
    if not isinstance(events, list):
        raise ValueError("Saved crossed events must be a list.")
    identities = set()
    for event in events:
        if not isinstance(event, dict) or set(event) != {"id", "at_minutes", "title", "notes", "source"}:
            raise ValueError("Saved crossed event has unsupported or missing fields.")
        identity = _text(event["id"], "Saved crossed event identifier", 210, required=True)
        if identity in identities:
            raise ValueError("Saved crossed events repeat an identifier.")
        identities.add(identity)
        when = _integer(event["at_minutes"], "Saved crossed event time")
        if not row["before_minutes"] < when <= row["after_minutes"]:
            raise ValueError("Saved crossed event lies outside the recorded time interval.")
        _text(event["title"], "Saved crossed event title", 200, required=True)
        _text(event["notes"], "Saved crossed event notes", 20000)
        if event["source"] not in ("timeline", "world"):
            raise ValueError("Saved crossed event source is unsupported.")
    consequences = payload["consequences"]
    if not isinstance(consequences, list) or not 1 <= len(consequences) <= 20:
        raise ValueError("Saved time-change consequences must be a nonempty list.")
    for consequence in consequences:
        _text(consequence, "Saved time-change consequence", 2000, required=True)
    return revision


def validate_saved_state(database_path):
    """Read-only recovery check of every campaign's time data, including archives.

    Legacy libraries may have clocks/history without the later optional tables.
    No missing settings are filled in, no calendar is changed, and World Desk
    event hours are not compared with a custom day length: those are repairable
    planning choices, rather than malformed time storage.
    """
    counts = {name: 0 for name in ("campaign_clock", "campaign_time_settings", "time_changes",
                                  "campaign_time_details", "campaign_timeline", "campaign_weather")}
    try:
        path = Path(database_path).resolve()
        with closing(sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)) as db:
            db.row_factory = sqlite3.Row
            db.execute("BEGIN")
            tables = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            campaigns = {row[0] for row in db.execute("SELECT id FROM campaigns")} if "campaigns" in tables else set()
            def rows(name):
                if name not in tables:
                    return []
                result = db.execute(f"SELECT * FROM {name}").fetchall()
                counts[name] = len(result)
                return result
            def campaign(identity):
                _text(identity, "Saved time campaign identifier", 200, required=True)
                if identity not in campaigns:
                    raise ValueError("Saved time state references a missing campaign.")
            clocks = {}
            for row in rows("campaign_clock"):
                identity = row["campaign_id"]
                campaign(identity)
                _integer(row["minutes"], "Saved campaign minutes")
                _text(row["calendar_name"], "Saved calendar name", 120, required=True)
                _integer(row["days_per_month"], "Saved days per month", 1000, 1)
                _integer(row["months_per_year"], "Saved months per year", 48, 1)
                clocks[identity] = row
            settings = {}
            for row in rows("campaign_time_settings"):
                identity = row["campaign_id"]
                campaign(identity)
                if identity not in clocks:
                    raise ValueError("Saved calendar settings have no campaign clock.")
                _integer(row["revision"], "Saved clock revision")
                calendar = CalendarSpec.from_json(row["calendar_json"])
                clock = clocks[identity]
                if (calendar.name, calendar.months[0][1], len(calendar.months)) != (
                        clock["calendar_name"], clock["days_per_month"], clock["months_per_year"]):
                    raise ValueError("Saved custom calendar disagrees with its clock metadata.")
                settings[identity] = row
            changes = {}
            last_after = {}
            # rowid reflects append order, while timestamps can share a second.
            history = rows("time_changes")
            if history:
                history = db.execute("SELECT * FROM time_changes ORDER BY rowid").fetchall()
            for row in history:
                identity = row["campaign_id"]
                campaign(identity)
                if identity not in clocks:
                    raise ValueError("Saved time history has no campaign clock.")
                _text(row["id"], "Saved time-change identifier", 200, required=True)
                before = _integer(row["before_minutes"], "Saved history starting minutes")
                after = _integer(row["after_minutes"], "Saved history ending minutes")
                if after <= before:
                    raise ValueError("Saved time history must advance the campaign clock.")
                if identity in last_after and before != last_after[identity]:
                    raise ValueError("Saved time history contains a gap or overlapping changes.")
                last_after[identity] = after
                _text(row["reason"], "Saved time-change reason", 2000, required=True)
                _text(row["created_at"], "Saved time-change timestamp", 100, required=True)
                changes[row["id"]] = row
            for identity, after in last_after.items():
                if clocks[identity]["minutes"] != after:
                    raise ValueError("Saved campaign clock disagrees with its time history.")
            for row in rows("campaign_time_details"):
                identity = _text(row["change_id"], "Saved detailed time-change identifier", 200, required=True)
                if identity not in changes:
                    raise ValueError("Saved time-change details reference missing history.")
                payload = _strict_json(row["payload_json"], "Saved time-change details", MAX_HISTORY_JSON)
                revision = _saved_details(payload, changes[identity])
                setting = settings.get(changes[identity]["campaign_id"])
                if setting is None or revision >= setting["revision"]:
                    raise ValueError("Saved time-change revision disagrees with the current calendar settings.")
            for row in rows("campaign_timeline"):
                campaign(row["campaign_id"])
                if row["campaign_id"] not in clocks:
                    raise ValueError("Saved campaign timeline has no clock.")
                _text(row["id"], "Saved timeline identifier", 200, required=True)
                _integer(row["at_minutes"], "Saved timeline event time")
                _text(row["title"], "Saved timeline event title", 200, required=True)
                _text(row["notes"], "Saved timeline event notes", 20000)
                _integer(row["cancelled"], "Saved timeline cancelled flag", 1)
            for row in rows("campaign_weather"):
                campaign(row["campaign_id"])
                if row["campaign_id"] not in clocks:
                    raise ValueError("Saved campaign weather has no clock.")
                CampaignTimeRepository._weather_row(row)
            db.rollback()
        return counts
    except (ValueError, sqlite3.Error, TypeError, KeyError, IndexError, RecursionError, OverflowError) as exc:
        raise ValueError(f"Campaign time data failed validation: {exc}") from exc
