"""Check deterministic D&D naming families and read-only v2.4 compatibility."""
import random
from contextlib import closing
import sqlite3
import tempfile
import unittest
from pathlib import Path

from dndgm4.namegen import (
    ALL_KINDS, BANKS, CORE_RACES, EXPANDED_RACES, FAMILY_ALIASES,
    GENDERS, MONSTER_RACES, NameEngine, UnsupportedCreature,
    family_for, read_v24_bank,
)


class NamingRulesTests(unittest.TestCase):
    def test_every_listed_race_and_monster_is_covered(self):
        for race in ALL_KINDS:
            with self.subTest(race=race):
                self.assertIn(family_for(race), BANKS)
                self.assertTrue(NameEngine(
                    namegen_v24_db="/nonexistent/v24.sqlite",
                    rng=random.Random(42)
                ).generate(race, count=5))

    def test_shared_creature_families(self):
        for race in ("Lizardfolk", "Draconian", "Yuan-ti", "Kobold", "Dragonborn"):
            self.assertEqual(family_for(race), "Draconic")
        for race in ("Ogre", "Skullcrusher Ogre", "Troll", "Giant", "Goliath"):
            self.assertEqual(family_for(race), "Giantkin")
        for race in ("Orc", "Half-orc", "Gnoll"):
            self.assertEqual(family_for(race), "Orc")
        for race in ("Goblin", "Bugbear", "Hobgoblin"):
            self.assertEqual(family_for(race), "Goblinoid")
        self.assertEqual(family_for("  LIZARDFOLK  "), "Draconic")

    def test_curated_names_stable_and_unique(self):
        first = NameEngine("/nonexistent/v24.sqlite", random.Random(444))
        second = NameEngine("/nonexistent/v24.sqlite", random.Random(444))
        one = first.generate("Elf", count=8)
        self.assertEqual(one, second.generate("Elf", count=8))
        self.assertEqual(len(set(one)), 8)
        self.assertTrue(all(len(x.split()) == 2 for x in one))
        dragon = NameEngine("/nonexistent/v24.sqlite", random.Random(22))
        self.assertTrue(dragon.generate("Draconian", monster=True))
        for name in one:
            self.assertNotIn("(", name)

    def test_gendered_curated_bank_preserves_style(self):
        from dndgm4.namegen import GENDER_BANKS
        for family in GENDER_BANKS:
            engine = NameEngine("/nonexistent/v24.sqlite", random.Random(41))
            masculine = engine.generate(family, gender="Masculine", count=5, surname=False)
            self.assertTrue(set(masculine) <= set(GENDER_BANKS[family]["Masculine"].split()))
            neutral = engine.generate(family, gender="Nonbinary", count=5, surname=False)
            self.assertTrue(set(neutral) <= set(GENDER_BANKS[family]["Neutral"].split()))

    def test_no_nonsense_for_unrecognised_race(self):
        with self.assertRaises(UnsupportedCreature):
            family_for("unknown specimen 123")
        with self.assertRaises(UnsupportedCreature):
            NameEngine("/nonexistent/x.db").generate("unknown specimen 123")
        with self.assertRaises(ValueError):
            NameEngine().generate("Human", count=101)

    def test_v24_schema_read_only_without_creating_missing_database(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "namegenie_v24.sqlite3"
            with closing(sqlite3.connect(p)) as db:
                db.executescript("""
                    CREATE TABLE entries(id INTEGER PRIMARY KEY, name TEXT, role TEXT);
                    CREATE TABLE tags(entry_id INTEGER, facet TEXT, value TEXT);
                    INSERT INTO entries VALUES (1, 'V24OriginalName', 'Given');
                    INSERT INTO entries VALUES (2, 'OtherGenre', 'Given');
                    INSERT INTO entries VALUES (3, 'CorrectSurname', 'Family');
                    INSERT INTO tags VALUES (1,'Genre','Fantasy');
                    INSERT INTO tags VALUES (1,'Species','Elf');
                    INSERT INTO tags VALUES (1,'Gender','Masculine');
                    INSERT INTO tags VALUES (2,'Genre','Modern');
                    INSERT INTO tags VALUES (2,'Species','Elf');
                    INSERT INTO tags VALUES (3,'Genre','Fantasy');
                    INSERT INTO tags VALUES (3,'Species','Elf');
                """)
                db.commit()
            before = p.read_bytes()
            self.assertEqual(read_v24_bank(p,"Elf","Given","Masculine"),
                             ["V24OriginalName"])
            self.assertEqual(read_v24_bank(p,"Elf","Given","Feminine"), [])
            names = NameEngine(p,random.Random(1)).generate("Elf",gender="Masculine")
            self.assertTrue(names)
            self.assertEqual(p.read_bytes(), before)
            missing = Path(d) / "missing.sqlite3"
            self.assertEqual(read_v24_bank(missing, "Elf", "Given"), [])
            self.assertFalse(missing.exists())


if __name__ == "__main__":
    unittest.main()
