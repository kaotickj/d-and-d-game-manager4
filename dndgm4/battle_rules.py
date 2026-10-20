"""Battle Trakker: D&D 3.5 encounter state, initiative, HP and conditions.

Separate *encounter instances* from permanent creature records. The encounter
is a local snapshot: applying damage MUST NEVER overwrite a character's
permanent maximum HP or mutate SQLite sheets. No PyQt dependency here.

Durations are tracked in rounds and decrement at the END of the afflicted
combatant's turn. Conditions applied before that turn can expire at that
turn's end, so the DM can edit the countdown for effects with other timing.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from uuid import uuid4
import copy
import json
import os
import tempfile

from .dice import ability_modifier, roll_dice

CONDITIONS = (
    "Blinded", "Confused", "Cowering", "Dazed", "Dazzled", "Deafened",
    "Disabled", "Entangled", "Exhausted", "Fascinated", "Fatigued",
    "Flat-Footed", "Frightened", "Grappling", "Helpless",
    "Invisible", "Nauseated", "Panicked", "Paralyzed", "Petrified",
    "Pinned", "Prone", "Shaken", "Sickened", "Staggered", "Stunned",
    "Unconscious", "Other",
)
MAX_COMBATANTS = 120
MAX_HISTORY = 350
MAX_LOG = 400


@dataclass
class Fighter:
    uid: str
    name: str
    kind: str = "npc"
    source_id: str = ""  # can be shared by multiple independent enemies
    max_hp: int = 1
    hp: int = 1
    temp_hp: int = 0
    ac: int = 10
    dex_mod: int = 0
    init_mod: int = 0
    initiative: int | None = None
    initiative_roll: int | None = None
    surprised: bool = False
    active: bool = True
    conditions: list[dict] = field(default_factory=list)
    notes: str = ""
    cr: str = ""

    def status(self) -> str:
        if self.hp <= -10:
            return "At -10 HP (typically dead)"
        if self.hp < 0:
            return "Below 0 HP (typically dying)"
        if self.hp == 0:
            return "At 0 HP (disabled)"
        return "Active"


def _check_int(value, name, low, high):
    if type(value) is not int or not low <= value <= high:
        raise ValueError(f"{name} must be a whole number from {low} to {high}.")
    return value


def _check_str(value, name, limit=200):
    if not isinstance(value, str) or len(value) > limit:
        raise ValueError(f"{name} must be text under {limit} characters.")
    return value


def fighter_from_record(record, *, name: str | None = None) -> Fighter:
    """Read initiative + ability/feat details from PC, NPC or monster sheet."""
    sheet = {}
    if record.sheet_json:
        try:
            sheet = json.loads(record.sheet_json)
        except (TypeError, ValueError):
            sheet = {}
    if not isinstance(sheet, dict):
        sheet = {}
    dex = ability_modifier(record.dexterity)
    feat_bonus = 4 if "Improved Initiative" in sheet.get("feats", []) else 0
    calculated = sheet.get("computed", {})
    if not isinstance(calculated, dict):
        calculated = {}
    known = calculated.get("initiative")
    modifier = known if type(known) is int and -100 <= known <= 100 else dex + feat_bonus
    maximum = max(1, record.max_hit_points)
    return Fighter(
        uid=str(uuid4()), source_id=record.id,
        name=_check_str(name if name is not None else record.name, "Name"),
        kind=record.kind, max_hp=maximum, hp=maximum,
        ac=record.armor_class, dex_mod=dex, init_mod=modifier,
        notes=record.notes[:2000], cr=record.challenge_rating,
    )


@dataclass
class Battle:
    title: str = "New Encounter"
    scene: str = ""
    round: int = 0
    phase: str = "setup"  # setup, surprise, combat, finished
    current_id: str = ""
    fighters: list[Fighter] = field(default_factory=list)
    log: list[str] = field(default_factory=list)
    _history: list[dict] = field(default_factory=list, repr=False, compare=False)

    def snapshot(self) -> dict:
        # Do not serialize _history: asdict(self) would deeply copy every
        # previous snapshot and make long encounters quadratically expensive.
        return {
            "title": self.title, "scene": self.scene, "round": self.round,
            "phase": self.phase, "current_id": self.current_id,
            "fighters": [asdict(member) for member in self.fighters],
            "log": list(self.log),
        }

    def _remember(self):
        self._history.append(copy.deepcopy(self.snapshot()))
        if len(self._history) > MAX_HISTORY:
            del self._history[0]

    def undo(self) -> bool:
        if not self._history:
            return False
        state = self._history.pop()
        restored = Battle.from_dict(state)
        for key in ("title", "scene", "round", "phase", "current_id",
                    "fighters", "log"):
            setattr(self, key, getattr(restored, key))
        return True

    def note(self, entry: str):
        self.log.append(f"R{self.round} {self.phase}: {entry}")
        if len(self.log) > MAX_LOG:
            del self.log[:-MAX_LOG]

    def get(self, uid: str) -> Fighter:
        for fighter in self.fighters:
            if fighter.uid == uid:
                return fighter
        raise ValueError("Combatant not found in this encounter.")

    def add(self, fighter: Fighter):
        if len(self.fighters) >= MAX_COMBATANTS:
            raise ValueError(f"Encounters support at most {MAX_COMBATANTS} combatants.")
        if any(f.uid == fighter.uid for f in self.fighters):
            raise ValueError("Combatant instance ID is already in this encounter.")
        self._remember()
        self.fighters.append(copy.deepcopy(fighter))
        self.note(f"Added {fighter.name}.")

    def remove(self, uid: str):
        fighter = self.get(uid)
        self._remember()
        self.fighters = [f for f in self.fighters if f.uid != uid]
        if self.current_id == uid:
            remaining = self.order()
            self.current_id = remaining[0].uid if remaining else ""
        self.note(f"Removed {fighter.name}.")

    def order(self) -> list[Fighter]:
        pool = [f for f in self.fighters if f.active and
                (self.phase != "surprise" or not f.surprised)]
        # D&D 3.5 ties: highest DEX modifier first; remaining equal ties
        # maintain manual insertion order (the DM may edit initiative).
        return sorted(pool, key=lambda f: (
            -(f.initiative if f.initiative is not None else -999),
            -f.dex_mod
        ))

    def set_initiative(self, uid: str, total: int):
        fighter = self.get(uid)
        _check_int(total, "Initiative total", -999, 999)
        self._remember()
        fighter.initiative = total
        fighter.initiative_roll = None
        self.note(f"{fighter.name}: initiative manually set to {total}.")

    def roll_initiatives(self, *, rng=None):
        if not self.fighters:
            raise ValueError("Add at least one combatant before rolling initiative.")
        self._remember()
        for fighter in self.fighters:
            dice = roll_dice(1, 20, fighter.init_mod, rng=rng)
            fighter.initiative_roll = dice.faces[0]
            fighter.initiative = dice.total
            self.note(f"{fighter.name}: {dice.notation} {dice.detail}.")
        if self.phase == "setup":
            self.current_id = ""

    def begin(self, *, rng=None):
        if not self.fighters or not any(f.active for f in self.fighters):
            raise ValueError("Add at least one active combatant.")
        if self.phase not in ("setup", "finished"):
            raise ValueError("Encounter is already underway.")
        if any(f.initiative is None for f in self.fighters if f.active):
            self.roll_initiatives(rng=rng)
        self._remember()
        active = [f for f in self.fighters if f.active]
        has_surprise = (any(f.surprised for f in active)
                        and any(not f.surprised for f in active))
        self.phase = "surprise" if has_surprise else "combat"
        self.round = 0 if has_surprise else 1
        ordered = self.order()
        self.current_id = ordered[0].uid
        self.note(f"Combat begins. {'Surprise round' if has_surprise else 'Round 1'}.")
        return self.get(self.current_id)

    def advance(self) -> Fighter:
        if self.phase not in ("surprise", "combat"):
            raise ValueError("Start the encounter before advancing turns.")
        previous = self.get(self.current_id)
        self._remember()
        # Duration ticks at END of the afflicted combatant's own turn.
        expired = []
        for condition in previous.conditions:
            if condition["rounds"] is not None:
                condition["rounds"] -= 1
                if condition["rounds"] <= 0:
                    expired.append(condition)
        for condition in expired:
            previous.conditions.remove(condition)
            self.note(f"{previous.name}: {condition['name']} expires.")
        ordered = self.order()
        ids = [f.uid for f in ordered]
        if not ids:
            self.phase = "finished"
            self.current_id = ""
            raise ValueError("No active combatants remain.")
        current_index = ids.index(previous.uid) if previous.uid in ids else -1
        if current_index < 0 or current_index == len(ids) - 1:
            if self.phase == "surprise":
                self.phase = "combat"
                self.round = 1
            else:
                self.round += 1
            ordered = self.order()
            self.current_id = ordered[0].uid
            self.note(f"Round {self.round} begins.")
        else:
            self.current_id = ordered[current_index + 1].uid
        self.note(f"Turn: {self.get(self.current_id).name}.")
        return self.get(self.current_id)

    def change_hp(self, uid: str, amount: int, *, heal=False) -> Fighter:
        fighter = self.get(uid)
        _check_int(amount, "HP amount", 0, 999999)
        if not amount:
            return fighter
        self._remember()
        if heal:
            fighter.hp = min(fighter.max_hp, fighter.hp + amount)
            self.note(f"{fighter.name} heals {amount}; HP {fighter.hp}/{fighter.max_hp}.")
        else:
            blocked = min(fighter.temp_hp, amount)
            fighter.temp_hp -= blocked
            fighter.hp = max(-999999, fighter.hp - (amount - blocked))
            self.note(f"{fighter.name} takes {amount} damage"
                      + (f" ({blocked} absorbed by temporary HP)" if blocked else "")
                      + f"; HP {fighter.hp}/{fighter.max_hp}.")
        return fighter

    def set_hp(self, uid: str, hp: int):
        _check_int(hp, "Current HP", -999999, 999999)
        fighter = self.get(uid)
        self._remember()
        fighter.hp = hp
        self.note(f"{fighter.name}: current HP manually set to {hp}.")

    def set_temp_hp(self, uid: str, hp: int):
        _check_int(hp, "Temporary HP", 0, 999999)
        fighter = self.get(uid)
        self._remember()
        fighter.temp_hp = hp
        self.note(f"{fighter.name}: temporary HP set to {hp}.")

    def set_active(self, uid: str, active: bool):
        fighter = self.get(uid)
        self._remember()
        fighter.active = bool(active)
        if not active and self.current_id == uid:
            order = self.order()
            self.current_id = order[0].uid if order else ""
        self.note(f"{fighter.name} {'rejoined' if active else 'left'} active combat.")

    def set_surprised(self, uid: str, surprised: bool):
        fighter = self.get(uid)
        self._remember()
        fighter.surprised = bool(surprised)
        self.note(f"{fighter.name}: surprised = {fighter.surprised}.")

    def set_condition(self, uid: str, name: str, rounds: int | None):
        fighter = self.get(uid)
        name = _check_str(name.strip(), "Condition", 80)
        if not name:
            raise ValueError("Choose a condition.")
        if rounds is not None:
            _check_int(rounds, "Condition duration", 1, 9999)
        self._remember()
        matches = [c for c in fighter.conditions if c["name"] == name]
        if matches:
            matches[0]["rounds"] = rounds
        else:
            fighter.conditions.append({"name": name, "rounds": rounds})
        self.note(f"{fighter.name}: {name} applied"
                  + (f" for {rounds} turn(s)." if rounds else " (indefinite)."))

    def clear_condition(self, uid: str, name: str):
        fighter = self.get(uid)
        if not any(c["name"] == name for c in fighter.conditions):
            return
        self._remember()
        fighter.conditions = [c for c in fighter.conditions if c["name"] != name]
        self.note(f"{fighter.name}: {name} removed.")

    def finish(self):
        self._remember()
        self.phase = "finished"
        self.current_id = ""
        self.note("Encounter ended. Snapshot preserved.")

    @classmethod
    def from_dict(cls, data: dict) -> "Battle":
        if not isinstance(data, dict):
            raise ValueError("Battle record must be an object.")
        if data.get("version", 1) != 1:
            raise ValueError("Unsupported Battle Trakker save version.")
        title = _check_str(data.get("title", "New Encounter"), "Encounter title", 200)
        scene = _check_str(data.get("scene", ""), "Scene notes", 12000)
        phase = data.get("phase", "setup")
        if phase not in ("setup", "surprise", "combat", "finished"):
            raise ValueError("Invalid encounter phase.")
        round_no = _check_int(data.get("round", 0), "Round", 0, 100000)
        members = data.get("fighters", [])
        if not isinstance(members, list) or len(members) > MAX_COMBATANTS:
            raise ValueError("Invalid combatant roster.")
        ids = set()
        fighters = []
        for raw in members:
            if not isinstance(raw, dict):
                raise ValueError("Invalid combatant entry.")
            uid = _check_str(raw.get("uid"), "Combatant ID", 128)
            if not uid or uid in ids:
                raise ValueError("Duplicate or missing combatant ID.")
            ids.add(uid)
            values = {
                "uid": uid,
                "name": _check_str(raw.get("name"), "Name", 200),
                "kind": _check_str(raw.get("kind", "npc"), "Kind", 30),
                "source_id": _check_str(raw.get("source_id", ""), "Source ID", 128),
                "notes": _check_str(raw.get("notes", ""), "Notes", 3000),
                "cr": _check_str(raw.get("cr", ""), "CR", 30),
            }
            if not values["name"].strip() or values["kind"] not in ("pc", "npc", "monster", "custom"):
                raise ValueError("Invalid combatant name or kind.")
            for key, low, high in (
                ("max_hp", 1, 999999), ("hp", -999999, 999999),
                ("temp_hp", 0, 999999), ("ac", -999, 999),
                ("dex_mod", -99, 99), ("init_mod", -100, 100)
            ):
                values[key] = _check_int(raw.get(key), key, low, high)
            for key in ("initiative", "initiative_roll"):
                val = raw.get(key)
                values[key] = (None if val is None else
                               _check_int(val, key, -999 if key=="initiative" else 1,
                                          999 if key=="initiative" else 20))
            for key in ("surprised", "active"):
                val = raw.get(key, key=="active")
                if type(val) is not bool:
                    raise ValueError(f"{key} must be a yes/no value.")
                values[key] = val
            conditions = raw.get("conditions", [])
            if not isinstance(conditions, list) or len(conditions) > 24:
                raise ValueError("Invalid combatant conditions.")
            seen = set()
            cleaned = []
            for condition in conditions:
                if not isinstance(condition, dict):
                    raise ValueError("Malformed condition.")
                name = _check_str(condition.get("name"), "Condition", 80)
                if not name or name in seen:
                    raise ValueError("Duplicate or invalid condition name.")
                seen.add(name)
                rounds = condition.get("rounds")
                if rounds is not None:
                    rounds = _check_int(rounds, "Condition rounds", 1, 9999)
                cleaned.append({"name": name, "rounds": rounds})
            values["conditions"] = cleaned
            fighters.append(Fighter(**values))
        log = data.get("log", [])
        if (not isinstance(log, list) or len(log) > MAX_LOG or
                any(not isinstance(x, str) or len(x)>6000 for x in log)):
            raise ValueError("Invalid combat log.")
        current = _check_str(data.get("current_id", ""), "Current combatant ID", 128)
        if current and current not in ids:
            raise ValueError("Saved current combatant is missing.")
        return cls(title=title, scene=scene, round=round_no, phase=phase,
                   current_id=current, fighters=fighters, log=list(log))


class BattleStore:
    """Atomic, local autosaves beside SQLite, independent of library rows."""

    def __init__(self, database_path):
        self.path = Path(database_path).with_name("battle_trakker.json")

    def load(self) -> Battle:
        if not self.path.is_file():
            return Battle()
        if self.path.stat().st_size > 1500000:
            raise ValueError("Battle Trakker save is larger than 1.5 MB.")
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError, UnicodeError) as exc:
            raise ValueError("Saved battle file is unreadable; it was not overwritten.") from exc
        return Battle.from_dict(data)

    def save(self, battle: Battle):
        data = {"version":1, **battle.snapshot()}
        # Same strict validation path on writes, without touching the
        # existing encounter save until a safe replacement is staged.
        Battle.from_dict(data)
        content = json.dumps(data, ensure_ascii=False, indent=2)
        if len(content.encode("utf-8")) > 1500000:
            raise ValueError("Combat log is too large to save.")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temp = None
        try:
            with tempfile.NamedTemporaryFile(
                    mode="w", encoding="utf-8", dir=self.path.parent,
                    prefix=".battle_", suffix=".tmp", delete=False) as output:
                temp = Path(output.name)
                output.write(content)
                output.flush()
                os.fsync(output.fileno())
            os.replace(temp, self.path)
        finally:
            if temp is not None:
                temp.unlink(missing_ok=True)
