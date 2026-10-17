"""Database tests run without requiring a Qt display or PyQt installation."""
from dataclasses import replace
from pathlib import Path
from tempfile import TemporaryDirectory
import sqlite3
import unittest

from dndgm4.models import Creature
from dndgm4.storage import CreatureRepository


class CreatureRepositoryTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = TemporaryDirectory()
        self.path = Path(self.temp_dir.name) / "library.sqlite3"
        self.repo = CreatureRepository(self.path)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_persistence(self):
        c = self.repo.save(Creature(
            name="Alara", kind="pc", race_type="Elf",
            character_class="Ranger", level=4, strength=14))
        m = self.repo.save(Creature(
            name="Cave Troll", kind="monster",
            challenge_rating="5", max_hit_points=63))
        reopened = CreatureRepository(self.path)
        self.assertEqual(reopened.get(c.id).strength, 14)
        self.assertEqual(reopened.get(m.id).max_hit_points, 63)
        self.assertNotEqual(c.id, m.id)

    def test_search_and_type_filter(self):
        self.repo.save(Creature(name="Orc Captain", kind="monster"))
        self.repo.save(Creature(name="Orc Scout", kind="npc"))
        self.repo.save(Creature(name="Ayla", kind="pc", notes="Friend of the orcs"))
        self.assertEqual(len(self.repo.list(query="orc")), 3)
        self.assertEqual(len(self.repo.list(query="orc", kind="monster")), 1)
        self.assertEqual(self.repo.list(query="%"), [])
        self.assertEqual(len(self.repo.list(kind="pc")), 1)

    def test_edit_duplicate_and_archive(self):
        first = self.repo.save(Creature(name="Goblin", kind="monster", max_hit_points=6))
        changed = self.repo.save(replace(first, max_hit_points=9))
        duplicate = self.repo.save(changed.duplicate())
        self.assertNotEqual(first.id, duplicate.id)
        self.assertEqual(self.repo.get(first.id).max_hit_points, 9)
        self.assertEqual(self.repo.get(duplicate.id).name, "Goblin (Copy)")
        self.assertTrue(self.repo.set_archived(first.id, True))
        self.assertEqual(len(self.repo.list()), 1)
        self.assertEqual(len(self.repo.list(include_archived=True)), 2)
        self.assertTrue(self.repo.set_archived(first.id, False))
        self.assertEqual(len(self.repo.list()), 2)

    def test_validation(self):
        for bad in (
            Creature(name="  "), Creature(name="No", kind="dragon"),
            Creature(name="No", level=-1),
            Creature(name="No", strength=100),
        ):
            with self.subTest(bad=bad):
                with self.assertRaises(ValueError):
                    self.repo.save(bad)
        self.assertEqual(self.repo.list(), [])

    def test_refuse_newer_schema(self):
        with sqlite3.connect(self.path) as db:
            db.execute("PRAGMA user_version = 99")
        with self.assertRaises(RuntimeError):
            CreatureRepository(self.path)


if __name__ == "__main__":
    unittest.main()
