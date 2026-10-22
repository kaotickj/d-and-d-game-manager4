"""Actual map/handout assets retain public boundaries after portable recovery."""
from copy import deepcopy
from importlib.util import find_spec
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
import zipfile


@unittest.skipUnless(find_spec("PyQt6"), "Image workflows require PyQt6")
class PlayerAssetsCompletionWorkflowTests(unittest.TestCase):
    def test_managed_assets_encounter_links_and_player_projection_survive_restore(self):
        from PyQt6.QtGui import QColor, QImage
        from dndgm4.battle_rules import fighter_from_record
        from dndgm4.campaigns import CampaignRepository
        from dndgm4.handouts import HandoutRepository
        from dndgm4.maps import MapRepository, TOKEN_COLORS, player_map_image, player_map_state
        from dndgm4.models import Creature
        from dndgm4.recovery import create_backup, restore_backup
        from dndgm4.storage import CreatureRepository
        from dndgm4.world import WorldRepository

        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            library = CreatureRepository(root / "live" / "library.sqlite3")
            hero = library.save(Creature(name="Ember", notes="SECRET patron", max_hit_points=12))
            campaigns = CampaignRepository(library.path)
            campaign = campaigns.create_campaign("SECRET campaign title")
            session = campaigns.create_session(campaign.id, "Bridge")
            encounter = campaigns.create_encounter(session.id, "SECRET encounter")
            battle = campaigns.load_battle(encounter.id)
            fighter = fighter_from_record(hero)
            battle.add(fighter)
            campaigns.save_battle(encounter.id, battle)
            handout = WorldRepository(library.path).create(campaign.id, "handout", "SECRET handout title",
                summary="SECRET summary", dm_notes="SECRET ambush", details={"player_text": "Follow the marked road."})
            source = root / "SECRET-original-name.png"
            image = QImage(100, 100, QImage.Format.Format_ARGB32)
            image.fill(QColor("#c33146"))
            image.setText("Private", "SECRET image metadata")
            self.assertTrue(image.save(str(source)))
            source_bytes = source.read_bytes()

            handouts = HandoutRepository(library)
            attached = handouts.import_image(campaign.id, handout.id, source)
            payload = handouts.public_payload(campaign.id, handout.id)
            self.assertEqual(payload.text, "Follow the marked road.")
            self.assertNotIn(b"SECRET", payload.image_png)
            self.assertEqual(QImage.fromData(payload.image_png).textKeys(), [])
            export = root / "public.zip"
            handouts.export_payload(payload, export)
            with zipfile.ZipFile(export) as archive:
                self.assertEqual(set(archive.namelist()), {"handout.txt", "image.png"})
                self.assertEqual(archive.read("handout.txt").decode(), payload.text)
                self.assertEqual(archive.read("image.png"), payload.image_png)
            self.assertEqual(source.read_bytes(), source_bytes)

            maps = MapRepository(library)
            record = maps.import_image(campaign.id, source, "SECRET map title")
            state = deepcopy(record.state)
            state["units_per_cell"] = 5
            state["revealed"] = [[0, 0]]
            state["tokens"] = [
                {"id": "linked-player-token", "label": "Ember", "x": 25, "y": 25, "visible": True,
                 "color": TOKEN_COLORS[0], "link": {"encounter_id": encounter.id, "fighter_uid": fighter.uid}},
                {"id": "private-token", "label": "SECRET spy", "x": 30, "y": 30, "visible": False, "color": TOKEN_COLORS[1]},
            ]
            state["annotations"] = [
                {"id": "public-note", "text": "Road", "x": 20, "y": 20, "color": TOKEN_COLORS[0], "visible": True},
                {"id": "private-note", "text": "SECRET trap", "x": 20, "y": 20, "color": TOKEN_COLORS[1], "visible": False},
                {"id": "unrevealed-note", "text": "SECRET destination", "x": 75, "y": 75, "color": TOKEN_COLORS[2], "visible": True},
            ]
            record = maps.save_state(record.id, state, campaign_id=campaign.id, expected_state=record.state)
            source.unlink()
            archive_path = root / "assets.dndbackup"
            create_backup(library, archive_path)
            restored_path = restore_backup(archive_path, root / "recovered")
            restored_library = CreatureRepository(restored_path)
            restored_handouts = HandoutRepository(restored_library)
            self.assertEqual(restored_handouts.get_image(campaign.id, handout.id, attached.id).sha256, attached.sha256)
            self.assertEqual(restored_handouts.public_payload(campaign.id, handout.id), payload)
            restored_maps = MapRepository(restored_library)
            restored_map = restored_maps.get(record.id, campaign_id=campaign.id)
            self.assertEqual(restored_map.state, record.state)
            public = player_map_state(restored_map.state)
            self.assertEqual([token["label"] for token in public["tokens"]], ["Ember"])
            self.assertEqual([note["text"] for note in public["annotations"]], ["Road"])
            self.assertNotIn("SECRET", json.dumps(public))
            self.assertNotIn("link", public["tokens"][0])
            self.assertNotIn(encounter.id, json.dumps(public))
            public_image = player_map_image(restored_maps.load_image(restored_map), restored_map.state)
            self.assertEqual(public_image.pixelColor(25, 25), QColor("#c33146"))
            self.assertEqual(public_image.pixelColor(75, 75), QColor("#000000"))
            self.assertEqual(public_image.textKeys(), [])
            self.assertEqual(CampaignRepository(restored_path).load_battle(encounter.id).fighters[0].uid, fighter.uid)
            self.assertEqual(restored_library.get(hero.id), hero)
