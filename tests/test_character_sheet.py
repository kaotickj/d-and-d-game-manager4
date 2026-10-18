"""Character-sheet rules and safe schema migration regression tests."""
import json
import sqlite3
import unittest
from contextlib import closing
from pathlib import Path
from tempfile import TemporaryDirectory

from dndgm4.creation import ABILITIES, build_character
from dndgm4.character_sheet import (
    SKILLS,TEMPLATES,ALIGNMENTS,allocate_default_skills,
    build_sheet, skill_budget, validate_allocations, load_sheet
)
from dndgm4.models import Creature
from dndgm4.storage import CreatureRepository, SCHEMA_VERSION


class CharacterSheetRulesTests(unittest.TestCase):
    def test_all_core_and_extra_classes_have_preset(self):
        self.assertGreaterEqual(len(TEMPLATES),25)
        for name,t in TEMPLATES.items():
            with self.subTest(name=name):
                self.assertGreaterEqual(t.hit_die,4)
                self.assertTrue(t.suggested_skills)
                self.assertTrue(t.suggested_equipment)
                self.assertTrue(all(s in SKILLS for s in t.suggested_skills))

    def test_automatic_and_manual_allocations(self):
        fighter=TEMPLATES["Fighter"]
        self.assertEqual(skill_budget("Fighter",12,"Human"),16)
        automatic=allocate_default_skills(fighter,16)
        self.assertEqual(validate_allocations(automatic,fighter,16),16)
        self.assertEqual(automatic["Ride"],8)  # 4 ranks, in half-rank ticks
        with self.assertRaises(ValueError):
            validate_allocations({"Tumble":5},fighter,16)  # cross-class max 2 ranks
        with self.assertRaises(ValueError):
            validate_allocations({"Ride":7},fighter,16)  # class whole-rank only
        with self.assertRaises(ValueError):
            validate_allocations({"Ride":8,"Climb":8,"Jump":8},fighter,8)

    def test_default_and_manual_sheet_roundtrip(self):
        base=dict.fromkeys(ABILITIES,12)
        char=build_character(name="Ashen",race="Human",character_class="Fighter",
                             base=base,method="manual")
        t=TEMPLATES["Fighter"]
        budget=skill_budget("Fighter",char.intelligence,"Human")
        allocation=allocate_default_skills(t,budget)
        result=build_sheet(
            character=char,class_name="Fighter",ranks=allocation,
            feats=["Power Attack","Cleave"],equipment=["Longsword","Armor"],
            alignment="Neutral Good",deity="Kord",languages=["Common"],
            appearance="Scarred",personality="Determined",
            background="From a coastal village.",spell_notes="")
        data=load_sheet(result)
        self.assertEqual(data["feats"],["Power Attack","Cleave"])
        self.assertEqual(data["alignment"],"Neutral Good")
        self.assertEqual(data["background"],"From a coastal village.")
        self.assertEqual(data["skill_budget"],budget)
        with TemporaryDirectory() as d:
            repo=CreatureRepository(Path(d)/"library.sqlite3")
            saved=repo.save(result)
            reopened=CreatureRepository(Path(d)/"library.sqlite3").get(saved.id)
            self.assertEqual(load_sheet(reopened)["equipment"],["Longsword","Armor"])
            self.assertEqual(reopened.name,"Ashen")

    def test_custom_class_without_fabricated_rules(self):
        base=dict.fromkeys(ABILITIES,10)
        char=build_character(name="Vex",race="Elf",character_class="Rune Knight",
                             base=base,method="manual",custom_hit_die=10,
                             custom_skill_points=4)
        self.assertEqual(char.max_hit_points,9)
        sheet=build_sheet(
            character=char,class_name="Rune Knight",
            ranks={"Spellcraft":8},feats=["Custom ward feat"],
            equipment=["Worn armor"],alignment="Lawful Neutral",
            deity="",languages=["Common","Elven"],
            appearance="",personality="",background="",
            custom_hd=10,custom_sp=4,custom_class_skills=["Spellcraft"],
            class_features=["Runic ward (DM-defined)"])
        self.assertEqual(load_sheet(sheet)["class_features"],["Runic ward (DM-defined)"])

    def test_migration_preserves_v1_saved_records(self):
        with TemporaryDirectory() as d:
            path=Path(d)/"old.sqlite3"
            # Create real database in current schema then simulate the v1
            # shape by building it explicitly (ALTER DROP unsupported on old SQLite).
            with closing(sqlite3.connect(path)) as db:
                db.executescript("""
                    CREATE TABLE creatures (
                    id TEXT PRIMARY KEY,name TEXT NOT NULL,kind TEXT NOT NULL,
                    race_type TEXT NOT NULL,character_class TEXT NOT NULL,
                    level INTEGER NOT NULL,challenge_rating TEXT NOT NULL,
                    armor_class INTEGER NOT NULL,max_hit_points INTEGER NOT NULL,
                    strength INTEGER NOT NULL,dexterity INTEGER NOT NULL,
                    constitution INTEGER NOT NULL,intelligence INTEGER NOT NULL,
                    wisdom INTEGER NOT NULL,charisma INTEGER NOT NULL,
                    notes TEXT NOT NULL,archived INTEGER NOT NULL,
                    created_at TEXT NOT NULL,updated_at TEXT NOT NULL);
                    INSERT INTO creatures VALUES (
                    'old','Legacy hero','pc','Human','Rogue',1,'',13,8,
                    10,12,10,14,10,10,'my old notes',0,
                    CURRENT_TIMESTAMP,CURRENT_TIMESTAMP);
                    PRAGMA user_version=1;
                """)
                db.commit()
            repo=CreatureRepository(path)
            old=repo.get("old")
            self.assertEqual(old.notes,"my old notes")
            self.assertEqual(old.sheet_json,"")
            self.assertEqual(old.name,"Legacy hero")
            with closing(sqlite3.connect(path)) as db:
                self.assertEqual(db.execute("PRAGMA user_version").fetchone()[0],2)
            # Second open must be idempotent.
            self.assertEqual(CreatureRepository(path).get("old").name,"Legacy hero")


if __name__=="__main__":
    unittest.main()
