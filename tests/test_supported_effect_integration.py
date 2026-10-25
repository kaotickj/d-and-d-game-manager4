"""Supported spell timers and per-roll AC preserve encounter/library boundaries."""
from copy import deepcopy
from dataclasses import asdict
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from dndgm4.battle_advanced import AdvancedBattle, AdvancedBattleStore
from dndgm4.battle_rules import fighter_from_record
from dndgm4.models import Creature
from dndgm4.storage import CreatureRepository
from tests.test_battle_advanced import encounter, FixedRoller
from tests.test_spell_effects import statistics
from dndgm4.spell_effects import preview_effects


class SupportedEffectIntegrationTests(unittest.TestCase):
    def add(self, battle, spell="Shield", **changes):
        kwargs = {"target_id": "ogre", "anchor_id": "mage", "duration": 2,
                  "mechanics": {"version": 1, "spell": spell}}
        kwargs.update(changes)
        return battle.add_effect(spell, **kwargs)

    def test_save_load_retains_explicit_mechanics_uuid_and_duplicate_instances(self):
        battle = encounter()
        first, second = self.add(battle), self.add(battle)
        self.assertNotEqual(first, second)
        self.assertEqual([effect["id"] for effect in battle.effects], [first, second])
        with TemporaryDirectory() as folder:
            store = AdvancedBattleStore(Path(folder) / "library.sqlite3")
            store.save(battle)
            loaded = store.load()
            self.assertEqual(loaded.snapshot(), battle.snapshot())
            self.assertEqual(loaded.effects[0]["mechanics"], {"version": 1, "spell": "Shield"})
            preview = preview_effects(statistics(), loaded.effects, "ogre")
            self.assertEqual(preview["ac"], 18)
            self.assertEqual(len(preview["active_effects"]), 1)
            self.assertEqual(len(preview["suppressed_effects"]), 1)

    def test_cancel_undo_and_anchored_expiry_keep_the_surviving_instance(self):
        battle = encounter()
        first = self.add(battle, "Bless", duration=1)
        second = self.add(battle, "Bless", duration=3)
        before_cancel = battle.snapshot()
        battle.cancel_effect(first)
        self.assertEqual([effect["id"] for effect in battle.effects], [second])
        self.assertTrue(battle.undo())
        self.assertEqual(battle.snapshot(), before_cancel)
        battle.advance()  # target's turn is not the originating initiative count
        self.assertEqual([effect["remaining"] for effect in battle.effects], [1, 3])
        before_expiry = battle.snapshot()
        battle.advance()  # caster's next initiative expires the first instance
        self.assertEqual([(effect["id"], effect["remaining"]) for effect in battle.effects], [(second, 2)])
        self.assertEqual(preview_effects(statistics(), battle.effects, "ogre")["attack_bonus"], 6)
        self.assertTrue(battle.undo())
        self.assertEqual(battle.snapshot(), before_expiry)
        self.assertEqual(battle.effects[0]["mechanics"], {"version": 1, "spell": "Bless"})

    def test_legacy_version_one_named_timer_remains_descriptive(self):
        battle = encounter()
        uid = battle.add_effect("Shield", target_id="ogre", anchor_id="mage", duration=2)
        loaded = AdvancedBattle.from_dict({"version": 1, **battle.snapshot()})
        self.assertEqual(loaded.effects[0]["id"], uid)
        self.assertNotIn("mechanics", loaded.effects[0])
        self.assertEqual(preview_effects(statistics(), loaded.effects, "ogre")["ac"], 16)
        old = {"version": 1, **battle.snapshot()}
        for key in ("effects", "action_state", "spell_slots", "had_surprise"):
            old.pop(key)
        self.assertEqual(AdvancedBattle.from_dict(old).effects, [])

    def test_add_rejects_malformed_metadata_and_blank_target_without_any_mutation(self):
        battle = encounter()
        for changes in ({"mechanics": {}}, {"mechanics": {"version": True, "spell": "Shield"}},
                        {"mechanics": {"version": 1, "spell": "Fireball"}},
                        {"mechanics": {"version": 1, "spell": "Shield", "bonus": 99}},
                        {"target_id": ""}, {"target_id": "missing"}):
            before, history = battle.snapshot(), deepcopy(battle._history)
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                self.add(battle, **changes)
            self.assertEqual(battle.snapshot(), before)
            self.assertEqual(battle._history, history)

    def test_load_rejects_malformed_metadata_without_changing_existing_state_or_file(self):
        battle = encounter()
        self.add(battle)
        with TemporaryDirectory() as folder:
            store = AdvancedBattleStore(Path(folder) / "library.sqlite3")
            store.save(battle)
            saved_bytes = store.path.read_bytes()
            original = battle.snapshot()
            for metadata in (None, {}, {"version": 2, "spell": "Shield"}):
                raw = {"version": 1, **deepcopy(original)}
                raw["effects"][0]["mechanics"] = metadata
                with self.subTest(metadata=metadata), self.assertRaises(ValueError):
                    AdvancedBattle.from_dict(raw)
            raw = {"version": 1, **deepcopy(original)}
            raw["effects"][0]["target_id"] = ""
            with self.assertRaises(ValueError):
                AdvancedBattle.from_dict(raw)
            self.assertEqual(battle.snapshot(), original)
            self.assertEqual(store.path.read_bytes(), saved_bytes)

    def test_per_roll_target_ac_changes_hit_without_changing_encounter_ac(self):
        battle = encounter()
        baseline = battle.resolve_attack("mage", "ogre", bonus=0, damage="1d6", rng=FixedRoller([12]))
        self.assertFalse(baseline.hit)
        original_hp = battle.get("ogre").hp
        result = battle.resolve_attack("mage", "ogre", bonus=0, damage="1d6",
                                      target_ac_override=10, rng=FixedRoller([12, 2]))
        self.assertTrue(result.hit)
        self.assertEqual((result.target_ac, result.damage), (10, 2))
        self.assertEqual(battle.get("ogre").ac, 16)
        self.assertEqual(battle.get("ogre").hp, original_hp)
        self.assertTrue(any("saved encounter AC 16 unchanged" in entry for entry in battle.log))

    def test_invalid_ac_override_consumes_no_rng_and_changes_no_history_log_or_action(self):
        battle = encounter()
        battle.spend_action("move")
        for invalid in (True, False, 10.0, "10", -101, 1001, []):
            before, history = battle.snapshot(), deepcopy(battle._history)
            roller = FixedRoller([])  # Any attempted roll fails this test.
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                battle.resolve_attack("mage", "ogre", bonus=0, damage="1d6",
                                      target_ac_override=invalid, rng=roller)
            self.assertEqual(battle.snapshot(), before)
            self.assertEqual(battle._history, history)

    def test_supported_timers_and_reviewed_damage_do_not_modify_library_record(self):
        with TemporaryDirectory() as folder:
            repository = CreatureRepository(Path(folder) / "library.sqlite3")
            saved = repository.save(Creature(name="Permanent Hero", armor_class=16,
                                            max_hit_points=30, sheet_json='{"inventory":[]}'))
            before = asdict(repository.get(saved.id))
            battle = encounter()
            linked = fighter_from_record(saved)
            battle.add(linked)
            effect = self.add(battle, target_id=linked.uid)
            battle.resolve_attack("mage", linked.uid, bonus=0, damage="1d6",
                                  target_ac_override=10, apply_damage=True, rng=FixedRoller([12, 2]))
            self.assertEqual((battle.get(linked.uid).hp, battle.get(linked.uid).ac), (28, 16))
            battle.cancel_effect(effect)
            store = AdvancedBattleStore(repository.path)
            store.save(battle)
            self.assertEqual(asdict(repository.get(saved.id)), before)


if __name__ == "__main__":
    unittest.main()
