"""Extended 3.5 encounter manager layered over the v0.8 save format.

SRD durations expire immediately before the *originating* initiative count
returns (not at the end of the afflicted target's turn). 6 seconds per round.
Separate action, effect and slot state from permanent Compendium records.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from uuid import uuid4
from pathlib import Path
import copy
import json

from .battle_rules import Battle, BattleStore
from .battle_srd35 import duration_to_rounds, rounds_to_seconds, seconds_as_clock, attack, saving_throw, skill_check


@dataclass
class AdvancedBattle(Battle):
    effects: list[dict] = field(default_factory=list)
    action_state: dict = field(default_factory=dict)
    had_surprise: bool = False
    spell_slots: dict = field(default_factory=dict)

    def snapshot(self):
        data = super().snapshot()
        data.update(effects=copy.deepcopy(self.effects),
                    action_state=dict(self.action_state),
                    had_surprise=self.had_surprise,
                    spell_slots=copy.deepcopy(self.spell_slots))
        return data

    @classmethod
    def from_dict(cls, data):
        obj = super().from_dict(data)
        roster = {f.uid for f in obj.fighters}
        effects = data.get("effects", [])
        if not isinstance(effects, list) or len(effects) > 200:
            raise ValueError("Invalid effect clock roster.")
        seen = set()
        for item in effects:
            if not isinstance(item, dict):
                raise ValueError("Invalid effect entry.")
            fields = {"id", "name", "target_id", "anchor_id", "remaining", "original", "notes"}
            if set(item) not in (fields, fields | {"mechanics"}):
                raise ValueError("Unexpected effect fields.")
            if "mechanics" in item:
                from .spell_effects import validate_mechanics
                validate_mechanics(item["mechanics"])
                if not item["target_id"]:
                    raise ValueError("Supported spell mechanics require an explicitly selected target.")
            uid, name = item["id"], item["name"]
            if not isinstance(uid, str) or not uid or uid in seen:
                raise ValueError("Invalid or duplicate effect ID.")
            seen.add(uid)
            if not isinstance(name, str) or not 1 <= len(name) <= 100:
                raise ValueError("Invalid effect name.")
            if item["anchor_id"] not in roster or (
                item["target_id"] and item["target_id"] not in roster
            ):
                raise ValueError("Effect references a missing combatant.")
            if not isinstance(item["notes"], str) or len(item["notes"]) > 2000:
                raise ValueError("Invalid effect notes.")
            for key in ("remaining", "original"):
                if type(item[key]) is not int or not 1 <= item[key] <= 100000000:
                    raise ValueError("Invalid effect round count.")
        obj.effects = copy.deepcopy(effects)
        state = data.get("action_state", {})
        if not isinstance(state, dict) or len(state) > 10:
            raise ValueError("Invalid action tracker.")
        for action, count in state.items():
            if action not in ACTIONS or type(count) is not int or not 0 <= count <= 100:
                raise ValueError("Invalid action tracker data.")
        obj.action_state = dict(state)
        obj.had_surprise = data.get("had_surprise", False)
        if type(obj.had_surprise) is not bool:
            raise ValueError("Invalid surprise marker.")
        slots = data.get("spell_slots", {})
        if not isinstance(slots, dict) or len(slots) > 120:
            raise ValueError("Invalid spell slot roster.")
        for uid, levels in slots.items():
            if uid not in roster or not isinstance(levels, dict) or len(levels) > 10:
                raise ValueError("Invalid caster / spell levels.")
            for level, values in levels.items():
                if level not in [str(i) for i in range(10)] or (
                    not isinstance(values, list) or len(values) != 2 or
                    any(type(x) is not int or x < 0 or x > 100 for x in values)
                ) or values[1] > values[0]:
                    raise ValueError("Invalid spell slot budget.")
        obj.spell_slots = copy.deepcopy(slots)
        return obj

    def undo(self):
        if not self._history:
            return False
        state = self._history.pop()
        restored = type(self).from_dict(state)
        for key in ("title", "scene", "round", "phase", "current_id",
                    "fighters", "log", "effects", "action_state",
                    "had_surprise", "spell_slots"):
            setattr(self, key, getattr(restored, key))
        return True

    def remove(self, uid):
        super().remove(uid)
        self.effects = [e for e in self.effects if e["anchor_id"] != uid and e["target_id"] != uid]
        self.spell_slots.pop(uid, None)

    def begin(self, *, rng=None):
        result = super().begin(rng=rng)
        self.had_surprise = self.phase == "surprise"
        self.action_state = {}
        return result

    def advance(self):
        result = super().advance()
        self.action_state = {}
        self.tick_effects(result.uid)
        return result

    def tick_effects(self, entering_uid):
        for item in list(self.effects):
            if item["anchor_id"] != entering_uid:
                continue
            item["remaining"] -= 1
            if item["remaining"] == 0:
                self.effects.remove(item)
                if item["notes"] == "Timed condition (SRD)" and item["target_id"]:
                    creature = self.get(item["target_id"])
                    # Keep condition if another instance of the same named
                    # effect remains active (e.g. two overlapping casters).
                    if not any(e["notes"] == "Timed condition (SRD)" and
                               e["target_id"] == item["target_id"] and
                               e["name"] == item["name"] for e in self.effects):
                        creature.conditions = [
                            c for c in creature.conditions
                            if c["name"] != item["name"]]
                self.note(f"EXPIRED before initiative count: {item['name']}.")

    def elapsed_rounds(self):
        if self.phase in ("setup", "surprise"):
            return 0
        return max(0, self.round - 1) + int(self.had_surprise)

    def clock_label(self):
        return seconds_as_clock(rounds_to_seconds(self.elapsed_rounds()))

    def add_effect(self, name, *, target_id="", anchor_id="", duration=1,
                   unit="rounds", notes="", mechanics=None):
        if self.phase not in ("combat", "surprise"):
            raise ValueError("Start combat before timing an effect.")
        if not isinstance(name, str) or not 1 <= len(name.strip()) <= 100:
            raise ValueError("Enter an effect name (up to 100 characters).")
        if not isinstance(notes, str) or len(notes) > 2000:
            raise ValueError("Effect notes must be under 2000 characters.")
        anchor_id = anchor_id or self.current_id
        caster = self.get(anchor_id)
        if target_id:
            self.get(target_id)
        if mechanics is not None:
            from .spell_effects import validate_mechanics
            mechanics = validate_mechanics(mechanics)
            if not target_id:
                raise ValueError("Supported spell mechanics require an explicitly selected target.")
        if len(self.effects) >= 200:
            raise ValueError("Maximum of 200 active effects.")
        total = duration_to_rounds(duration, unit)
        self._remember()
        key = str(uuid4())
        self.effects.append(dict(id=key, name=name.strip(), target_id=target_id,
                                 anchor_id=anchor_id, original=total,
                                 remaining=total, notes=notes))
        if mechanics is not None:
            self.effects[-1]["mechanics"] = mechanics
        self.note(f"Started {name} ({duration} {unit}); "
                  f"expires at {caster.name}'s initiative count.")
        return key

    def adjust_effect(self, uid, rounds):
        if type(rounds) is not int or not 1 <= rounds <= 100000000:
            raise ValueError("Remaining rounds must be 1 to 100000000.")
        item = next((e for e in self.effects if e["id"] == uid), None)
        if item is None:
            raise ValueError("Effect no longer exists.")
        self._remember()
        item["remaining"] = rounds
        self.note(f"Updated {item['name']}: {rounds} rounds remaining.")

    def cancel_effect(self, uid):
        item = next((e for e in self.effects if e["id"] == uid), None)
        if item is None:
            raise ValueError("Select an active effect.")
        self._remember()
        self.effects.remove(item)
        self.note(f"Dismissed {item['name']}.")

    def spend_action(self, action):
        """Basic SRD economy with DM overrides via reset action budget."""
        if self.phase not in ("combat", "surprise") or not self.current_id:
            raise ValueError("Start combat before marking actions.")
        if action not in ACTIONS:
            raise ValueError("Unsupported action.")
        if action == "reset":
            self._remember()
            self.action_state = {}
            self.note("Turn action budget reset by DM.")
            return
        used = self.action_state
        standard = used.get("standard", 0)
        move = used.get("move", 0)
        full = used.get("full", 0)
        if self.phase == "surprise" and action in ("full", "5-foot step"):
            raise ValueError("Surprise round allows one standard or move action.")
        if action == "full" and (standard or move or full):
            raise ValueError("Full-round action conflicts with standard or move.")
        if action == "standard" and (standard or full or (
            self.phase == "surprise" and move)):
            raise ValueError("Standard action already spent.")
        if action == "move" and (full or move + standard >= 2 or (
            self.phase == "surprise" and (move or standard))):
            raise ValueError("Move action budget exhausted.")
        if action in ("swift", "immediate") and (
            used.get("swift", 0) + used.get("immediate", 0) >= 1
        ):
            raise ValueError("One swift/immediate action per turn, DM may reset.")
        if action == "5-foot step" and used.get(action):
            raise ValueError("5-foot step already used this turn.")
        self._remember()
        used[action] = used.get(action, 0) + 1
        self.note(f"{self.get(self.current_id).name} spends {action} action.")

    def set_condition(self, uid, name, rounds):
        """Conditions added during active combat share the SRD source clock.

        A condition set BEFORE combat retains legacy behavior because its
        originating initiative cannot yet be known. Those can be re-applied
        during combat from the correct caster's turn.
        """
        fighter = self.get(uid)
        if rounds is None or self.phase not in ("combat", "surprise"):
            super().set_condition(uid, name, rounds)
            if rounds is None:
                self.effects = [e for e in self.effects if not (
                    e["target_id"] == uid and e["name"] == name and
                    e["notes"] == "Timed condition (SRD)")]
            return
        if type(rounds) is not int or not 1 <= rounds <= 9999:
            raise ValueError("Condition duration must be 1-9999 rounds.")
        if not isinstance(name, str) or not 1 <= len(name.strip()) <= 80:
            raise ValueError("Choose a condition name.")
        self.add_effect(name.strip(), target_id=uid,
                        anchor_id=self.current_id, duration=rounds,
                        notes="Timed condition (SRD)")
        for condition in fighter.conditions:
            if condition["name"] == name.strip():
                condition["rounds"] = None
                break
        else:
            fighter.conditions.append({"name": name.strip(), "rounds": None})
        self.note(f"{fighter.name}: {name.strip()} status tied to caster initiative.")

    def clear_condition(self, uid, name):
        super().clear_condition(uid, name)
        self.effects = [e for e in self.effects if not (
            e["target_id"] == uid and e["name"] == name and
            e["notes"] == "Timed condition (SRD)")]

    def condition_remaining(self, uid, name):
        matches = [e["remaining"] for e in self.effects
                   if e["target_id"] == uid and e["name"] == name and
                   e["notes"] == "Timed condition (SRD)"]
        return min(matches) if matches else None

    def set_spell_slots(self, uid, level, total, used=0):
        self.get(uid)
        if any(type(x) is not int for x in (level, total, used)) or (
            not 0 <= level <= 9 or not 0 <= used <= total <= 100):
            raise ValueError("Spell level must be 0-9, slot values 0-100.")
        self._remember()
        self.spell_slots.setdefault(uid, {})[str(level)] = [total, used]
        self.note(f"Spell slots L{level}: {used}/{total} used for {self.get(uid).name}.")

    def use_spell_slot(self, uid, level, name):
        self.get(uid)
        key = str(level)
        values = self.spell_slots.get(uid, {}).get(key)
        if values is None:
            raise ValueError("Set the caster's daily slots for this level first.")
        if values[1] >= values[0]:
            raise ValueError("No slots remaining at this level.")
        self._remember()
        values[1] += 1
        self.note(f"{self.get(uid).name} casts {name} using spell slot L{level}; "
                  f"{values[1]}/{values[0]} used.")

    def resolve_attack(self, attacker_id, target_id, *, bonus, damage, threat_min=20,
                       multiplier=2, cover=0, concealment=0, situational=0,
                       damage_reduction=0, apply_damage=False, rng=None, target_ac_override=None):
        a, b = self.get(attacker_id), self.get(target_id)
        if target_ac_override is not None and (type(target_ac_override) is not int or not -100 <= target_ac_override <= 1000):
            raise ValueError("Reviewed target AC must be a whole number from -100 to 1000.")
        result = attack(attack_bonus=bonus, target_ac=b.ac if target_ac_override is None else target_ac_override, damage=damage,
                        threat_min=threat_min, multiplier=multiplier, cover=cover,
                        concealment=concealment, situational=situational,
                        damage_reduction=damage_reduction, rng=rng)
        self._remember()
        if target_ac_override is not None:
            self.note(f"DM-reviewed target AC {target_ac_override} for this roll; saved encounter AC {b.ac} unchanged.")
        self.note(f"{a.name} -> {b.name}: {result.description}.")
        if apply_damage and result.hit and result.damage:
            self.change_hp(target_id, result.damage)
        return result

    def resolve_check(self, uid, name, modifier, dc, *, save=True, rng=None):
        fighter = self.get(uid)
        result = (saving_throw if save else skill_check)(
            modifier=modifier, dc=dc, rng=rng)
        self._remember()
        self.note(f"{fighter.name} {name}: {result.text}")
        return result

ACTIONS = frozenset(("standard", "move", "full", "swift", "immediate",
                     "free", "5-foot step", "reset"))


class AdvancedBattleStore(BattleStore):
    def load(self):
        if not self.path.is_file():
            return AdvancedBattle()
        if self.path.stat().st_size > 1500000:
            raise ValueError("Battle save exceeds 1.5 MB.")
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            return AdvancedBattle.from_dict(data)
        except (OSError, UnicodeError, ValueError, KeyError, TypeError) as exc:
            raise ValueError("Encounter save is invalid and was not overwritten.") from exc

    def save(self, battle):
        # Validate advanced fields before the original atomic write.
        AdvancedBattle.from_dict({"version": 1, **battle.snapshot()})
        return super().save(battle)
