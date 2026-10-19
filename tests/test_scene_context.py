"""Tests for explicit mixed record selection and complete scene context."""
from pathlib import Path
from tempfile import TemporaryDirectory
import json
import unittest

from dndgm4.models import Creature
from dndgm4.scene_context import (
    SceneStore, blank_scene, add_records, record_details,
    build_scribe_context, validate_scene,
)


def make_records():
    player = Creature(
        id="pc-1", name="Eldrin", kind="pc", race_type="Elf",
        character_class="Wizard", level=3,
        intelligence=18, strength=8,
        sheet_json=json.dumps({
            "background": "Raised near Hollowford.",
            "skills_half_ranks": {"Knowledge (arcana)": 10},
            "feats": ["Combat Casting"],
            "equipment": ["Quarterstaff", "Spellbook"],
            "spell_notes": "Magic Missile, Mage Armor",
            "personality": "Cautious",
        }),
        notes="Secret map carried in a cloak.",
    )
    npc = Creature(
        id="npc-1", name="Marta", kind="npc", race_type="Human",
        character_class="Expert",
        sheet_json=json.dumps({"background":"Keeps the Fox and Fiddle Inn."}),
    )
    monster = Creature(
        id="m-1", name="Bog Sentry", kind="monster",
        race_type="Original Bog Sentry", character_class="Plant",
        challenge_rating="2", constitution=12, intelligence=0,
        sheet_json=json.dumps({
            "monster_type": "Plant",
            "null_abilities": ["intelligence"],
            "special_attacks": "Vine lash",
            "special_qualities": "Tremorsense",
            "computed": {"hd": 4, "fort": 5, "bab": 3},
            "biography": "Dwells beneath black roots.",
        })
    )
    return player, npc, monster


class SceneContextTests(unittest.TestCase):
    def test_persistent_scene_roster_deduplicates_and_retains_locations(self):
        with TemporaryDirectory() as d:
            store = SceneStore(Path(d) / "library.sqlite3")
            scene = blank_scene()
            scene["title"] = "Night Watch"
            scene["location"] = "Hollowford"
            scene["places"] = "Fox and Fiddle Inn"
            scene["time_conditions"] = "Heavy rain and dense fog"
            scene = add_records(scene, ["pc-1","npc-1","pc-1"])
            store.save(scene)
            loaded = SceneStore(Path(d) / "library.sqlite3").load()
            self.assertEqual(loaded["record_ids"], ["pc-1", "npc-1"])
            self.assertIn("Fox and Fiddle", loaded["places"])
            self.assertEqual(loaded["location"], "Hollowford")

    def test_full_pc_npc_monster_details_in_scribe_context(self):
        pc, npc, monster = make_records()
        scene = blank_scene()
        scene["places"] = "Fox and Fiddle Inn, Lantern Bridge"
        scene["scenery"] = "A ruined marsh footpath"
        prompt = build_scribe_context(scene, [pc,npc,monster],
                                      mode="selection")
        for part in ("Eldrin", "Marta", "Bog Sentry", "Combat Casting",
                     "Knowledge (arcana)", "Magic Missile", "Spellbook",
                     "Raised near Hollowford", "Fox and Fiddle Inn",
                     "Hollowford", "Vine lash", "Tremorsense", 
                     "Dwells beneath black roots", "Heavy"):
            if part == "Heavy":
                continue
            self.assertIn(part, prompt)
        self.assertIn("3", prompt)
        self.assertIn("18", prompt)
        self.assertIn("null_abilities", prompt)
        self.assertIn("Explicitly loaded records: 3", prompt)
        self.assertEqual(prompt.count('"name": "Eldrin"'), 1)

    def test_large_context_is_rejected_without_silent_truncation(self):
        pc, *_ = make_records()
        from dataclasses import replace
        giant = replace(pc, notes="A" * 6200)
        with self.assertRaisesRegex(ValueError, "No character details"):
            build_scribe_context(blank_scene(), [giant])
        self.assertEqual(len(giant.notes), 6200)

    def test_manual_scene_validations_and_corruption(self):
        with self.assertRaisesRegex(ValueError, "Scene roster"):
            validate_scene({**blank_scene(), "record_ids": [None]})
        with TemporaryDirectory() as d:
            store=SceneStore(Path(d)/"library.sqlite3")
            store.path.write_text("{invalid", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "Could not read"):
                store.load()
            self.assertEqual(store.path.read_text(encoding="utf-8"),"{invalid")

    def test_record_details_does_not_silently_lose_nested_sheet(self):
        pc, _, monster = make_records()
        self.assertIn('"spell_notes"', record_details(pc))
        self.assertIn('"skills_half_ranks"', record_details(pc))
        self.assertIn('"computed"', record_details(monster))
        self.assertIn('"null_abilities"', record_details(monster))


if __name__ == "__main__":
    unittest.main()
