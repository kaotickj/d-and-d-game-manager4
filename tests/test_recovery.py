"""Complete backups preserve independent game state and fail without data loss."""
from contextlib import closing
from hashlib import sha256
from importlib.util import find_spec
import json
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
import unittest
import zipfile

from dndgm4.campaigns import CampaignRepository
from dndgm4.models import Creature
from dndgm4.recovery import create_backup, inspect_backup, restore_backup
from dndgm4.scene_context import SceneStore, blank_scene
from dndgm4.storage import CreatureRepository, SCHEMA_VERSION


class RecoveryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.path = self.root / "live" / "library.sqlite3"
        self.repo = CreatureRepository(self.path)
        self.hero = self.repo.save(Creature(name="Lost heir", notes="Private clue"))
        self.campaigns = CampaignRepository(self.path)
        self.campaign = self.campaigns.create_campaign("Ash Coast")
        self.campaigns.set_party(self.campaign.id, [self.hero.id])
        self.session = self.campaigns.create_session(self.campaign.id, "First voyage")
        self.archive = self.root / "game.dndbackup"

    def tearDown(self):
        self.tmp.cleanup()

    def test_round_trip_campaign_sidecars_assets_and_rules_database(self):
        scene = blank_scene()
        scene.update(title="A separate standalone scene", record_ids=[self.hero.id])
        SceneStore(self.path).save(scene)
        asset = self.path.parent / "assets" / "maps" / "coast.dat"
        asset.parent.mkdir(parents=True)
        asset.write_bytes(b"original map bytes")
        rules = self.path.with_name("rules.sqlite3")
        with closing(sqlite3.connect(rules)) as db:
            db.execute("CREATE TABLE evidence (text TEXT)")
            db.execute("INSERT INTO evidence VALUES ('source passage')")
            db.commit()
        from dndgm4.srd35_spells import SpellCatalog
        spells = [{"name": "Light", "class": "Bard", "level": 0,
                   "url": "https://www.d20srd.org/srd/spells/light.htm"}]
        SpellCatalog(self.path).store(spells)
        manifest = create_backup(self.repo, self.archive)
        self.assertEqual(manifest, inspect_backup(self.archive))
        self.repo.save(Creature(name="After the snapshot"))
        restored = restore_backup(self.archive, self.root / "recovered")
        result = CreatureRepository(restored)
        self.assertEqual(result.list(), [self.hero])
        self.assertEqual(CampaignRepository(restored).party(self.campaign.id), [self.hero])
        self.assertEqual(SceneStore(restored).load(), scene)
        self.assertEqual(restored.with_name("assets").joinpath("maps/coast.dat").read_bytes(), b"original map bytes")
        with closing(sqlite3.connect(restored.with_name("rules.sqlite3"))) as db:
            self.assertEqual(db.execute("SELECT text FROM evidence").fetchone()[0], "source passage")
        self.assertEqual(SpellCatalog(restored).search("light"), spells)
        self.assertEqual(restored.with_name("srd35_spells.json").read_bytes(),
                         self.path.with_name("srd35_spells.json").read_bytes())
        self.assertEqual(len(self.repo.list()), 2)

    def rewrite_archive(self, mutate):
        with zipfile.ZipFile(self.archive) as archive:
            data = {name: archive.read(name) for name in archive.namelist()}
        mutate(data)
        with zipfile.ZipFile(self.archive, "w") as archive:
            for name, content in data.items():
                archive.writestr(name, content)

    def test_modified_file_fails_checksum_without_publishing_recovery(self):
        create_backup(self.repo, self.archive)
        self.rewrite_archive(lambda data: data.__setitem__("library.sqlite3", b"bad" + data["library.sqlite3"][3:]))
        with self.assertRaisesRegex(ValueError, "checksum"):
            restore_backup(self.archive, self.root / "bad")
        self.assertFalse((self.root / "bad").exists())
        self.assertEqual(self.repo.get(self.hero.id), self.hero)

    def test_newer_schema_duplicate_names_and_path_traversal_rejected(self):
        create_backup(self.repo, self.archive)
        original = self.archive.read_bytes()
        for change in ("newer", "traversal", "extra"):
            self.archive.write_bytes(original)
            def mutate(data):
                manifest = json.loads(data["manifest.json"])
                if change == "newer":
                    manifest["schema_version"] = SCHEMA_VERSION + 1
                elif change == "traversal":
                    manifest["files"]["../escape"] = {"size": 1, "sha256": "x"}
                    data["../escape"] = b"x"
                else:
                    data["extra"] = b"x"
                data["manifest.json"] = json.dumps(manifest).encode()
            self.rewrite_archive(mutate)
            with self.assertRaises(ValueError):
                restore_backup(self.archive, self.root / change)
            self.assertFalse((self.root / change).exists())
        self.assertFalse((self.root / "escape").exists())

    def test_restore_existing_folder_and_live_backup_target_rejected(self):
        create_backup(self.repo, self.archive)
        with self.assertRaisesRegex(ValueError, "new folder"):
            restore_backup(self.archive, self.path.parent)
        with self.assertRaises(ValueError):
            create_backup(self.repo, self.path)
        self.assertEqual(self.repo.get(self.hero.id), self.hero)

    def test_windows_filename_aliases_and_reserved_names_are_rejected(self):
        create_backup(self.repo, self.archive)
        original = self.archive.read_bytes()
        for additions in (("assets/Map.txt", "assets/map.txt"), ("assets/NUL.txt",), ("assets/trailing.",)):
            self.archive.write_bytes(original)
            def mutate(data):
                manifest = json.loads(data["manifest.json"])
                for name in additions:
                    data[name] = b"x"
                    manifest["files"][name] = {"size": 1, "sha256": sha256(b"x").hexdigest()}
                data["manifest.json"] = json.dumps(manifest).encode()
            self.rewrite_archive(mutate)
            with self.assertRaises(ValueError):
                restore_backup(self.archive, self.root / "unsafe")
            self.assertFalse((self.root / "unsafe").exists())

    def test_invalid_campaign_scene_is_rejected_even_with_valid_sqlite_and_checksum(self):
        create_backup(self.repo, self.archive)
        before = self.archive.read_bytes()
        with closing(sqlite3.connect(self.path)) as db:
            db.execute("UPDATE sessions SET scene_json='{}' WHERE id=?", (self.session.id,))
            db.commit()
        with self.assertRaisesRegex(ValueError, "session scene"):
            create_backup(self.repo, self.archive)
        self.assertEqual(self.archive.read_bytes(), before)
        corrupt = self.path.read_bytes()
        def mutate(data):
            manifest = json.loads(data["manifest.json"])
            data["library.sqlite3"] = corrupt
            manifest["files"]["library.sqlite3"] = {"size": len(corrupt), "sha256": sha256(corrupt).hexdigest()}
            data["manifest.json"] = json.dumps(manifest).encode()
        self.rewrite_archive(mutate)
        with self.assertRaisesRegex(ValueError, "session scene"):
            restore_backup(self.archive, self.root / "corrupt")
        self.assertFalse((self.root / "corrupt").exists())

    def test_corrupt_sidecar_does_not_replace_existing_backup(self):
        create_backup(self.repo, self.archive)
        original = self.archive.read_bytes()
        self.path.with_name("current_scene.json").write_text("{broken", encoding="utf-8")
        with self.assertRaises(ValueError):
            create_backup(self.repo, self.archive)
        self.assertEqual(self.archive.read_bytes(), original)

    def assert_corrupt_domain_refused(self, message, name="library.sqlite3"):
        before = self.archive.read_bytes()
        source_path = self.path.parent / name
        source = source_path.read_bytes()
        library_before = self.path.read_bytes()
        with self.assertRaisesRegex(ValueError, message):
            create_backup(self.repo, self.archive)
        self.assertEqual(self.archive.read_bytes(), before)
        def corrupt_with_valid_checksum(data):
            manifest = json.loads(data["manifest.json"])
            data[name] = source
            manifest["files"][name] = {"size": len(source), "sha256": sha256(source).hexdigest()}
            data["manifest.json"] = json.dumps(manifest).encode()
        self.rewrite_archive(corrupt_with_valid_checksum)
        destination = self.root / "invalid-domain-recovery"
        with self.assertRaisesRegex(ValueError, message):
            restore_backup(self.archive, destination)
        self.assertFalse(destination.exists())
        self.assertEqual(source_path.read_bytes(), source)
        self.assertEqual(self.path.read_bytes(), library_before)

    def test_untrusted_spell_cache_is_rejected_during_backup_and_restore(self):
        from dndgm4.srd35_spells import SpellCatalog
        catalog = SpellCatalog(self.path)
        catalog.store([{"name": "Light", "class": "Bard", "level": 0,
                        "url": "https://www.d20srd.org/srd/spells/light.htm"}])
        create_backup(self.repo, self.archive)
        catalog.path.write_text(json.dumps([{"name": "Light", "class": "Bard", "level": 0,
            "url": "https://example.com/untrusted.htm"}]), encoding="utf-8")
        self.assert_corrupt_domain_refused("Untrusted index data", "srd35_spells.json")

    def create_managed_map(self):
        from PyQt6.QtGui import QImage
        from dndgm4.maps import MapRepository
        source = self.root / "original-map.png"
        image = QImage(100, 100, QImage.Format.Format_RGB32)
        image.fill(0xFF445566)
        self.assertTrue(image.save(str(source)))
        maps = MapRepository(self.repo)
        return maps, maps.import_image(self.campaign.id, source, "Coastal ruins")

    @unittest.skipUnless(find_spec("PyQt6") is not None, "PyQt6 unavailable")
    def test_damaged_map_images_are_rejected_during_backup_and_restore(self):
        from PyQt6.QtGui import QImage
        maps, record = self.create_managed_map()
        managed = maps.image_path(record)
        original = managed.read_bytes()
        create_backup(self.repo, self.archive)
        archive = self.archive.read_bytes()
        for damage in ("unreadable", "dimensions"):
            with self.subTest(damage=damage):
                self.archive.write_bytes(archive)
                managed.write_bytes(original)
                if damage == "unreadable":
                    managed.write_bytes(b"broken map image")
                    message = "(?i)image"
                else:
                    image = QImage(50, 50, QImage.Format.Format_RGB32)
                    image.fill(0xFF445566)
                    self.assertTrue(image.save(str(managed)))
                    message = "dimensions"
                self.assert_corrupt_domain_refused(message, record.image_path)

    @unittest.skipUnless(find_spec("PyQt6") is not None, "PyQt6 unavailable")
    def test_repairable_stale_map_links_survive_backup_and_restore_unchanged(self):
        from dndgm4.maps import MapRepository
        maps, record = self.create_managed_map()
        state = dict(record.state)
        state["tokens"] = [{"id": "hero", "label": "Lost heir", "x": 25, "y": 25,
            "color": "#ed6276", "visible": True,
            "link": {"encounter_id": "retired-encounter", "fighter_uid": "retired-fighter"}}]
        saved_json = json.dumps(state, indent=2)
        with closing(sqlite3.connect(self.path)) as db:
            db.execute("UPDATE maps SET state_json=? WHERE id=?", (saved_json, record.id))
            db.commit()
        source = self.path.read_bytes()
        create_backup(self.repo, self.archive)
        restored = restore_backup(self.archive, self.root / "repairable-map")
        recovered = MapRepository(CreatureRepository(restored)).get(record.id)
        self.assertEqual(recovered.state, state)
        with closing(sqlite3.connect(restored)) as db:
            self.assertEqual(db.execute("SELECT state_json FROM maps WHERE id=?", (record.id,)).fetchone()[0], saved_json)
        self.assertEqual(self.path.read_bytes(), source)

    def test_invalid_saved_calendar_is_rejected_during_backup_and_restore(self):
        from dndgm4.campaign_time import CampaignTimeRepository
        CampaignTimeRepository(self.path).get_clock(self.campaign.id)
        create_backup(self.repo, self.archive)
        with closing(sqlite3.connect(self.path)) as db:
            db.execute("UPDATE campaign_time_settings SET calendar_json='{}' WHERE campaign_id=?", (self.campaign.id,))
            db.commit()
        self.assert_corrupt_domain_refused("(?i)calendar")

    def test_real_and_blob_core_fields_are_rejected_before_backup_or_restore(self):
        create_backup(self.repo, self.archive)
        archive_bytes = self.archive.read_bytes()
        source_bytes = self.path.read_bytes()
        for column, value, message in (("strength", 13.5, "whole number"),
                                       ("sheet_json", b'{}', "must be text")):
            with self.subTest(column=column):
                self.archive.write_bytes(archive_bytes)
                self.path.write_bytes(source_bytes)
                with closing(sqlite3.connect(self.path)) as db:
                    db.execute(f"UPDATE creatures SET {column}=? WHERE id=?", (value,self.hero.id))
                    db.commit()
                self.assert_corrupt_domain_refused(message)

    def test_damaged_resource_command_is_rejected_during_backup_and_restore(self):
        from dndgm4.resources import ResourceRepository
        resources = ResourceRepository(self.path)
        wallet = resources.create_wallet(self.campaign.id, "Party treasury")
        resources.adjust_money(self.campaign.id, wallet.id, 100, "Initial funds", "initial-funds")
        create_backup(self.repo, self.archive)
        with closing(sqlite3.connect(self.path)) as db:
            db.execute("UPDATE resource_operations SET payload_json='[]' WHERE id='initial-funds'")
            db.commit()
        self.assert_corrupt_domain_refused("(?i)resource|damaged")

    def test_missing_handout_asset_is_rejected_during_backup_and_restore(self):
        from uuid import uuid4
        from dndgm4.handouts import HandoutRepository
        from dndgm4.world import WorldRepository
        HandoutRepository(self.repo)
        handout = WorldRepository(self.path).create(self.campaign.id, "handout", "Sealed letter")
        create_backup(self.repo, self.archive)
        identity = str(uuid4())
        with closing(sqlite3.connect(self.path)) as db:
            db.execute("""INSERT INTO handout_assets(id,campaign_id,handout_id,image_path,width,height,sha256,selected)
                VALUES(?,?,?,?,?,?,?,1)""", (identity, self.campaign.id, handout.id,
                    f"assets/handouts/{identity}.png", 1, 1, "a" * 64))
            db.commit()
        self.assert_corrupt_domain_refused("(?i)handout image is missing")

    def downgrade_to_schema_three(self):
        original_tables = {"creatures", "campaigns", "campaign_members", "sessions", "encounters", "workspace"}
        with closing(sqlite3.connect(self.path)) as db:
            db.execute("PRAGMA foreign_keys=OFF")
            tables = [row[0] for row in db.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")]
            for table in tables:
                if table not in original_tables:
                    db.execute('DROP TABLE "' + table.replace('"', '""') + '"')
            db.execute("PRAGMA user_version=3")
            db.commit()

    def test_backup_migrates_only_staged_copy_and_hashes_final_database(self):
        self.downgrade_to_schema_three()
        source_bytes = self.path.read_bytes()
        manifest = create_backup(self.repo, self.archive)
        self.assertEqual(manifest["schema_version"], SCHEMA_VERSION)
        with zipfile.ZipFile(self.archive) as archive:
            for name, metadata in manifest["files"].items():
                data = archive.read(name)
                self.assertEqual(metadata["size"], len(data))
                self.assertEqual(metadata["sha256"], sha256(data).hexdigest())
            staged = self.root / "archived.sqlite3"
            staged.write_bytes(archive.read("library.sqlite3"))
        with closing(sqlite3.connect(staged)) as db:
            self.assertEqual(db.execute("PRAGMA user_version").fetchone()[0], SCHEMA_VERSION)
        restored = restore_backup(self.archive, self.root / "upgraded-recovery")
        self.assertEqual(CreatureRepository(restored).get(self.hero.id), self.hero)
        self.assertEqual(CampaignRepository(restored).get_session(self.session.id), self.session)
        with closing(sqlite3.connect(restored)) as db:
            self.assertEqual(db.execute("PRAGMA user_version").fetchone()[0], SCHEMA_VERSION)
        self.assertEqual(self.path.read_bytes(), source_bytes)
        with closing(sqlite3.connect(self.path)) as db:
            self.assertEqual(db.execute("PRAGMA user_version").fetchone()[0], 3)

    def test_schema_three_migrates_without_changing_records_and_rollback_is_atomic(self):
        from unittest.mock import patch
        self.downgrade_to_schema_three()
        real_connect = sqlite3.connect
        class Failing(sqlite3.Connection):
            def execute(self, sql, *args):
                if "CREATE TABLE world_links" in sql:
                    raise sqlite3.OperationalError("interrupted")
                return super().execute(sql, *args)
        with patch("dndgm4.storage.sqlite3.connect", side_effect=lambda *a, **kw: real_connect(*a, factory=Failing, **kw)):
            with self.assertRaises(sqlite3.OperationalError):
                CreatureRepository(self.path)
        with closing(real_connect(self.path)) as db:
            self.assertEqual(db.execute("PRAGMA user_version").fetchone()[0], 3)
            self.assertEqual(db.execute("SELECT COUNT(*) FROM sqlite_master WHERE name='world_records'").fetchone()[0], 0)
        self.assertEqual(CreatureRepository(self.path).get(self.hero.id), self.hero)
        self.assertEqual(CampaignRepository(self.path).get_session(self.session.id), self.session)
