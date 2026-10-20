"""Deterministic D&D 3.5 encounter engine and persistence regression tests."""
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from dndgm4.battle_rules import (
    Battle, BattleStore, Fighter, fighter_from_record,
)
from dndgm4.models import Creature
from dndgm4.storage import CreatureRepository


class FixedRoller:
    def __init__(self, faces):
        self.faces = iter(faces)

    def randint(self, low, high):
        return next(self.faces)


class EncounterEngineTests(unittest.TestCase):
    @staticmethod
    def fighter(uid, name, mod, *, dex=0, hp=10, surprised=False):
        return Fighter(uid=uid, name=name, hp=hp, max_hp=hp, init_mod=mod,
                       dex_mod=dex, surprised=surprised)

    def test_initial_initiative_improved_initiative_and_multiple_instances(self):
        record = Creature(
            id="fighter-one", kind="pc", name="Tarin", dexterity=16,
            max_hit_points=24, armor_class=17,
            sheet_json=json.dumps({"feats":["Improved Initiative"]}))
        creature = fighter_from_record(record)
        self.assertEqual(creature.init_mod, 7)
        self.assertEqual(creature.dex_mod, 3)
        self.assertEqual((creature.hp, creature.max_hp), (24, 24))
        another = fighter_from_record(record)
        self.assertNotEqual(creature.uid, another.uid)
        self.assertEqual(creature.source_id, another.source_id)
        battle = Battle()
        battle.add(creature)
        battle.add(another)
        battle.roll_initiatives(rng=FixedRoller([12, 4]))
        self.assertEqual(
            [f.initiative for f in battle.fighters], [19, 11])
        self.assertEqual(battle.order()[0].uid, creature.uid)

    def test_initiative_tie_uses_dex_modifier_and_stable_order(self):
        battle=Battle()
        battle.add(self.fighter("a","Sage",2,dex=2))
        battle.add(self.fighter("b","Bandit",1,dex=4))
        battle.add(self.fighter("c","Soldier",1,dex=4))
        for uid in ("a","b","c"):
            battle.set_initiative(uid,15)
        self.assertEqual([f.uid for f in battle.order()],["b","c","a"])
        battle.begin()
        self.assertEqual(battle.round,1)
        self.assertEqual(battle.current_id,"b")
        battle.advance()
        self.assertEqual(battle.current_id,"c")
        battle.advance()
        self.assertEqual(battle.current_id,"a")
        battle.advance()
        self.assertEqual((battle.round,battle.current_id),(2,"b"))

    def test_surprise_round_moves_into_normal_combat(self):
        battle=Battle()
        battle.add(self.fighter("a","Rogue",3))
        battle.add(self.fighter("b","Guard",2,surprised=True))
        battle.set_initiative("a",14)
        battle.set_initiative("b",20)
        turn=battle.begin()
        self.assertEqual(battle.phase,"surprise")
        self.assertEqual(battle.round,0)
        self.assertEqual(turn.uid,"a")
        self.assertEqual([f.uid for f in battle.order()],["a"])
        next_turn=battle.advance()
        self.assertEqual(battle.phase,"combat")
        self.assertEqual(battle.round,1)
        self.assertEqual(next_turn.uid,"b")  # high initiative now participates
        self.assertEqual(battle.advance().uid,"a")

    def test_durations_tick_on_affected_turn_and_undo(self):
        battle=Battle()
        battle.add(self.fighter("a","Goblin",2))
        battle.add(self.fighter("b","Wizard",1))
        battle.set_initiative("a",18)
        battle.set_initiative("b",10)
        battle.set_condition("b","Shaken",2)
        battle.set_condition("a","Poisoned",None)
        battle.begin()
        battle.advance()   # end A: Poisoned is indefinite
        self.assertEqual(battle.get("b").conditions[0]["rounds"],2)
        battle.advance()   # end B: 1 round
        self.assertEqual(battle.get("b").conditions[0]["rounds"],1)
        battle.advance()   # end A
        battle.advance()   # end B: expires
        self.assertFalse(battle.get("b").conditions)
        self.assertTrue(battle.undo())
        self.assertEqual(battle.get("b").conditions[0]["rounds"],1)
        self.assertEqual(battle.get("a").conditions[0]["rounds"],None)

    def test_temporary_hp_absorbs_damage_then_normal_hp_and_heal(self):
        battle=Battle()
        battle.add(self.fighter("a","Knight",0,hp=18))
        battle.set_temp_hp("a",8)
        battle.change_hp("a",5)
        self.assertEqual((battle.get("a").hp,battle.get("a").temp_hp),(18,3))
        battle.change_hp("a",7)
        self.assertEqual((battle.get("a").hp,battle.get("a").temp_hp),(14,0))
        battle.change_hp("a",22)
        self.assertEqual(battle.get("a").hp,-8)
        self.assertIn("dying",battle.get("a").status())
        battle.change_hp("a",9999,heal=True)
        self.assertEqual(battle.get("a").hp,18)
        battle.undo()
        self.assertEqual(battle.get("a").hp,-8)
        # Current HP changes do not mutate source PC records.

    def test_invalid_values_rejected_without_state_mutation(self):
        battle=Battle()
        battle.add(self.fighter("a","Goblin",0))
        before=battle.snapshot()
        for call in (
            lambda: battle.change_hp("a",-2),
            lambda: battle.set_temp_hp("a",-1),
            lambda: battle.set_initiative("a",1000),
            lambda: battle.set_condition("a","Dazed",0),
            lambda: battle.remove("missing"),
            lambda: battle.advance(),
        ):
            with self.assertRaises(ValueError):
                call()
        self.assertEqual(battle.snapshot(),before)

    def test_json_save_load_resume_and_no_library_hp_mutation(self):
        with TemporaryDirectory() as root:
            library=CreatureRepository(Path(root)/"library.sqlite3")
            pc=library.save(Creature(name="Aric",kind="pc",
                dexterity=14,max_hit_points=22,armor_class=16))
            foe=library.save(Creature(name="Goblin",kind="monster",
                max_hit_points=5,armor_class=15))
            state=Battle(title="Crossroads at Sundown",scene="Heavy fog.")
            state.add(fighter_from_record(pc))
            state.add(fighter_from_record(foe))
            state.roll_initiatives(rng=FixedRoller([17,9]))
            state.begin()
            state.change_hp(state.fighters[0].uid,10)
            state.set_condition(state.fighters[1].uid,"Entangled",3)
            store=BattleStore(library.path)
            store.save(state)
            reopened=store.load()
            self.assertEqual(reopened.title,"Crossroads at Sundown")
            self.assertEqual(reopened.current_id,state.current_id)
            self.assertEqual(reopened.phase,"combat")
            self.assertEqual(reopened.get(state.fighters[0].uid).hp,12)
            self.assertEqual(len(reopened.log),len(state.log))
            self.assertEqual(library.get(pc.id).max_hit_points,22)
            self.assertEqual(library.get(foe.id).max_hit_points,5)
            self.assertEqual(reopened._history,[])

    def test_corrupt_battle_is_not_overwritten_on_load(self):
        with TemporaryDirectory() as root:
            store=BattleStore(Path(root)/"library.sqlite3")
            store.path.write_text("{bad json",encoding="utf8")
            with self.assertRaisesRegex(ValueError,"unreadable"):
                store.load()
            self.assertEqual(store.path.read_text(encoding="utf8"),"{bad json")

    def test_snapshot_does_not_embed_action_undo_history(self):
        battle=Battle()
        battle.add(self.fighter("a","Scout",2))
        for _ in range(90):
            battle.change_hp("a",1)
        snap=battle.snapshot()
        self.assertNotIn("_history",snap)
        self.assertEqual(len(battle._history),91)
        self.assertLess(len(json.dumps(snap)),20000)


if __name__=="__main__":
    unittest.main()
