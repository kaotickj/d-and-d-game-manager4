"""Map persistence, validated local image import, and public state boundaries."""
from copy import deepcopy
from dataclasses import replace
from importlib.util import find_spec
import json
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from dndgm4.campaigns import CampaignRepository
from dndgm4.maps import (MapConflictError, MapRepository, blank_map_state, map_distance,
                         player_map_state, validate_map_state)
from dndgm4.storage import CreatureRepository


@unittest.skipUnless(find_spec("PyQt6") is not None, "PyQt6 unavailable")
class MapRepositoryTests(unittest.TestCase):
    def setUp(self):
        self.folder = TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.root = Path(self.folder.name)
        self.library = CreatureRepository(self.root / "library.sqlite3")
        campaigns = CampaignRepository(self.library.path)
        self.campaign = campaigns.create_campaign("The Crimson Marches")
        self.other = campaigns.create_campaign("Another Campaign")
        self.maps = MapRepository(self.library)
        self.source = self.root / "original.png"
        from PyQt6.QtGui import QColor, QImage
        image = QImage(200, 160, QImage.Format.Format_RGB32)
        image.fill(QColor("#448855"))
        self.assertTrue(image.save(str(self.source)))

    def import_map(self):
        return self.maps.import_image(self.campaign.id, self.source, "The ruined keep")

    def test_image_is_managed_and_state_survives_reopening(self):
        record = self.import_map()
        managed = self.maps.image_path(record)
        self.assertNotEqual(managed, self.source)
        self.assertEqual(managed.read_bytes(), self.source.read_bytes())
        self.assertTrue(record.state["fog_enabled"])
        self.assertEqual(record.state["revealed"], [])
        state = deepcopy(record.state)
        state["revealed"] = [[1, 1]]
        state["tokens"] = [dict(id="hero", label="Arden", x=75, y=75, color="#ed6276", visible=True)]
        self.maps.save_state(record.id, state, campaign_id=self.campaign.id)
        self.source.unlink()
        reopened = MapRepository(CreatureRepository(self.library.path))
        saved = reopened.get(record.id, campaign_id=self.campaign.id)
        self.assertEqual(saved.state, state)
        self.assertEqual(reopened.load_image(saved).width(), 200)

    def test_campaigns_cannot_read_or_update_one_anothers_maps(self):
        record = self.import_map()
        self.assertEqual(self.maps.list(self.other.id), [])
        for operation in (
            lambda: self.maps.get(record.id, campaign_id=self.other.id),
            lambda: self.maps.save_state(record.id, record.state, campaign_id=self.other.id),
            lambda: self.maps.rename(record.id, "Stolen", campaign_id=self.other.id),
        ):
            with self.assertRaises(ValueError):
                operation()
        self.assertEqual(self.maps.get(record.id).title, "The ruined keep")

    def test_bad_imports_do_not_create_records_or_managed_images(self):
        invalid = self.root / "not-an-image.png"
        invalid.write_text("<svg><script>not a map</script></svg>")
        with self.assertRaises(ValueError):
            self.maps.import_image(self.campaign.id, invalid)
        with patch("dndgm4.maps.MAX_IMAGE_BYTES", 10):
            with self.assertRaises(ValueError):
                self.import_map()
        with self.assertRaises(ValueError):
            self.maps.import_image("missing-campaign", self.source)
        self.assertEqual(self.maps.list(self.campaign.id), [])
        self.assertFalse(self.maps.assets_root.exists())

    def test_oversized_dimensions_are_rejected_before_image_import(self):
        from PyQt6.QtGui import QImage
        oversized = QImage(10001, 1, QImage.Format.Format_RGB32)
        self.assertTrue(oversized.save(str(self.source)))
        with self.assertRaises(ValueError):
            self.import_map()
        self.assertFalse(self.maps.assets_root.exists())

    def test_failed_database_insert_removes_the_staged_image(self):
        with self.library._connection() as db:
            db.executescript("CREATE TRIGGER reject_map BEFORE INSERT ON maps BEGIN SELECT RAISE(ABORT, 'test failure'); END;")
        with self.assertRaises(sqlite3.IntegrityError):
            self.import_map()
        self.assertEqual(list(self.maps.assets_root.iterdir()), [])
        self.assertEqual(self.maps.list(self.campaign.id), [])

    def test_managed_paths_cannot_escape_or_follow_symlinks(self):
        record = self.import_map()
        for invalid in ("../../original.png", "/tmp/original.png", "assets/maps/other.png"):
            with self.subTest(path=invalid), self.assertRaises(ValueError):
                self.maps.image_path(replace(record, image_path=invalid))
        managed = self.maps.image_path(record)
        managed.unlink()
        try:
            managed.symlink_to(self.source)
        except (OSError, NotImplementedError):
            self.skipTest("Symbolic links unavailable")
        with self.assertRaises(ValueError):
            self.maps.image_path(record)

    def test_invalid_states_do_not_replace_saved_state(self):
        record = self.import_map()
        for mutation in (
            lambda state: state.update(width=201),
            lambda state: state.update(grid_size=True),
            lambda state: state.update(revealed=[[-1, 0]]),
            lambda state: state.update(fog_enabled="no"),
            lambda state: state.update(tokens=[dict(id="a", label="Bad", x=float("nan"), y=0,
                                                    color="#ed6276", visible=True)]),
        ):
            state = deepcopy(record.state)
            mutation(state)
            with self.assertRaises(ValueError):
                self.maps.save_state(record.id, state)
            self.assertEqual(self.maps.get(record.id).state, record.state)

    def test_changing_grid_size_clears_reveals_before_validating_new_cells(self):
        record = self.import_map()
        state = deepcopy(record.state)
        state["revealed"] = [[3, 3]]
        self.maps.save_state(record.id, state)
        state["grid_size"] = 100
        saved = self.maps.save_state(record.id, state)
        self.assertEqual(saved.state["grid_size"], 100)
        self.assertEqual(saved.state["revealed"], [])

    def test_missing_or_replaced_image_does_not_break_saved_metadata(self):
        record = self.import_map()
        self.maps.image_path(record).unlink()
        self.assertEqual(self.maps.list(self.campaign.id)[0].id, record.id)
        with self.assertRaisesRegex(ValueError, "missing"):
            self.maps.load_image(record)

    def test_calibration_and_private_annotations_persist(self):
        record = self.import_map()
        state = deepcopy(record.state)
        state.update(units_per_cell=10.5, unit_label="yards")
        state["annotations"] = [dict(id="note", text="Secret door\nDC 20", x=25, y=25, color="#ed6276")]
        saved = self.maps.save_state(record.id, state, expected_state=record.state)
        loaded = MapRepository(CreatureRepository(self.library.path)).get(record.id)
        self.assertEqual(loaded.state["units_per_cell"], 10.5)
        self.assertEqual(loaded.state["unit_label"], "yards")
        self.assertEqual(loaded.state["annotations"][0]["text"], "Secret door\nDC 20")
        self.assertFalse(loaded.state["annotations"][0]["visible"])
        self.assertEqual(loaded.state, saved.state)

    def test_expected_state_prevents_a_stale_window_from_overwriting_newer_changes(self):
        record = self.import_map()
        first = deepcopy(record.state)
        first["annotations"] = [dict(id="note", text="New note", x=25, y=25, color="#ed6276", visible=False)]
        saved = self.maps.save_state(record.id, first, expected_state=record.state)
        stale = deepcopy(record.state)
        stale["fog_enabled"] = False
        with self.assertRaises(MapConflictError):
            self.maps.save_state(record.id, stale, expected_state=record.state)
        self.assertEqual(self.maps.get(record.id).state, saved.state)

    def test_saved_blob_json_is_rejected_as_value_error(self):
        record = self.import_map()
        with self.library._connection() as db:
            db.execute("UPDATE maps SET state_json=? WHERE id=?", (b"{}", record.id))
        with self.assertRaisesRegex(ValueError, "JSON text"):
            self.maps.get(record.id)

    def test_legacy_v1_maps_upgrade_without_losing_their_existing_state(self):
        record = self.import_map()
        legacy = {key: value for key, value in record.state.items()
                  if key not in {"units_per_cell", "unit_label", "annotations"}}
        legacy["version"] = 1
        legacy["revealed"] = [[1, 1]]
        with self.library._connection() as db:
            db.execute("UPDATE maps SET state_json=? WHERE id=?", (json.dumps(legacy), record.id))
        loaded = self.maps.get(record.id)
        self.assertEqual(loaded.state["version"], 2)
        self.assertEqual(loaded.state["units_per_cell"], 5)
        self.assertEqual(loaded.state["unit_label"], "ft")
        self.assertEqual(loaded.state["revealed"], [[1, 1]])
        saved = self.maps.save_state(record.id, loaded.state, expected_state=legacy)
        self.assertEqual(saved.state["version"], 2)

    def test_encounter_actor_links_are_campaign_scoped_and_do_not_mutate_sources(self):
        from dndgm4.battle_rules import fighter_from_record
        from dndgm4.models import Creature
        campaigns = CampaignRepository(self.library.path)
        creature = self.library.save(Creature(name="Arden", kind="pc", max_hit_points=24))
        local = campaigns.create_session(self.campaign.id, "Local session")
        foreign = campaigns.create_session(self.other.id, "Foreign session")
        local_encounter = campaigns.create_encounter(local.id, "Local encounter")
        foreign_encounter = campaigns.create_encounter(foreign.id, "Foreign encounter")
        roster = {}
        for encounter in (local_encounter, foreign_encounter):
            battle = campaigns.load_battle(encounter.id)
            battle.fighters = [fighter_from_record(creature)]
            campaigns.save_battle(encounter.id, battle)
            roster[encounter.id] = battle.fighters[0].uid
        choices = self.maps.encounter_actors(self.campaign.id)
        self.assertEqual([(choice.encounter_id, choice.fighter_uid) for choice in choices],
                         [(local_encounter.id, roster[local_encounter.id])])
        record = self.import_map()
        state = deepcopy(record.state)
        token = dict(id="linked", label="Arden", x=25, y=25, color="#ed6276", visible=False,
                     link=dict(encounter_id=local_encounter.id, fighter_uid=roster[local_encounter.id]))
        state["tokens"] = [token]
        before_battle = campaigns.load_battle(local_encounter.id).snapshot()
        before_creature = self.library.get(creature.id)
        saved = self.maps.save_state(record.id, state)
        moved = deepcopy(saved.state)
        moved["tokens"][0]["x"] = 125
        self.maps.save_state(record.id, moved, expected_state=saved.state)
        self.assertEqual(campaigns.load_battle(local_encounter.id).snapshot(), before_battle)
        self.assertEqual(self.library.get(creature.id), before_creature)
        for link in (
            dict(encounter_id=foreign_encounter.id, fighter_uid=roster[foreign_encounter.id]),
            dict(encounter_id=local_encounter.id, fighter_uid=roster[foreign_encounter.id]),
            dict(encounter_id="missing", fighter_uid=roster[local_encounter.id]),
        ):
            invalid = deepcopy(moved)
            invalid["tokens"][0]["link"] = link
            with self.assertRaises(ValueError):
                self.maps.save_state(record.id, invalid)
        self.assertEqual(self.maps.get(record.id).state, moved)


class MapStateTests(unittest.TestCase):
    def test_ruler_uses_saved_calibration_and_straight_line_geometry(self):
        state = blank_map_state(400, 400)
        self.assertAlmostEqual(map_distance(state, (0, 0), (150, 200)), 25)
        state.update(units_per_cell=2.5, unit_label="m")
        self.assertAlmostEqual(map_distance(state, (0, 0), (150, 200)), 12.5)

    def test_state_rejects_huge_nonfinite_and_boolean_coordinates_without_overflow(self):
        for value in (10 ** 10000, float("nan"), float("inf"), True):
            for field in ("tokens", "annotations"):
                state = blank_map_state(200, 160)
                point = dict(id="bad", x=value, y=25, color="#ed6276", visible=False)
                point["label" if field == "tokens" else "text"] = "Bad point"
                state[field] = [point]
                with self.assertRaises(ValueError):
                    validate_map_state(state)
            state = blank_map_state(200, 160)
            state["units_per_cell"] = value
            with self.assertRaises(ValueError):
                validate_map_state(state)
            with self.assertRaises(ValueError):
                map_distance(blank_map_state(200, 160), (value, 25), (25, 25))

    def test_new_version_requires_metadata_and_rejects_future_versions(self):
        state = blank_map_state(200, 160)
        state["version"] = 3
        with self.assertRaisesRegex(ValueError, "version"):
            validate_map_state(state)
        state["version"] = 2
        state.pop("annotations")
        with self.assertRaisesRegex(ValueError, "missing"):
            validate_map_state(state)

    def test_player_projection_drops_private_notes_and_all_actor_references(self):
        state = blank_map_state(200, 160)
        state["revealed"] = [[0, 0]]
        state["tokens"] = [dict(id="hero", label="Arden", x=25, y=25, color="#ed6276", visible=True,
                                link=dict(encounter_id="secret encounter", fighter_uid="secret fighter"))]
        state["annotations"] = [
            dict(id="private", text="Secret door", x=25, y=25, color="#ed6276"),
            dict(id="public", text="Town gate", x=25, y=25, color="#ed6276", visible=True),
            dict(id="unexplored", text="Dragon lair", x=125, y=125, color="#ed6276", visible=True),
        ]
        public = player_map_state(state)
        self.assertEqual([note["text"] for note in public["annotations"]], ["Town gate"])
        self.assertNotIn("link", public["tokens"][0])
        for secret in ("Secret door", "Dragon lair", "secret encounter", "secret fighter"):
            self.assertNotIn(secret, json.dumps(public))
    def test_public_state_omits_hidden_and_unexplored_tokens(self):
        state = blank_map_state(200, 160)
        state["revealed"] = [[0, 0]]
        state["tokens"] = [
            dict(id="public", label="Hero", x=25, y=25, color="#ed6276", visible=True),
            dict(id="secret", label="Secret ambush", x=25, y=25, color="#ed6276", visible=False),
            dict(id="unexplored", label="Unknown foe", x=125, y=125, color="#ed6276", visible=True),
        ]
        public = player_map_state(state)
        self.assertEqual([token["id"] for token in public["tokens"]], ["public"])
        self.assertNotIn("Secret ambush", json.dumps(public))
        public["revealed"].clear()
        self.assertEqual(state["revealed"], [[0, 0]])
        state["fog_enabled"] = False
        self.assertEqual(len(player_map_state(state)["tokens"]), 2)

    def test_state_rejects_duplicate_tokens_extra_secret_fields_and_boolean_coordinates(self):
        token = dict(id="same", label="Hero", x=25, y=25, color="#ed6276", visible=True)
        for tokens in ([token, token], [dict(token, notes="secret")], [dict(token, x=True)]):
            state = blank_map_state(200, 160)
            state["tokens"] = tokens
            with self.assertRaises(ValueError):
                validate_map_state(state)


if __name__ == "__main__":
    unittest.main()
