"""Public handout snapshots exclude secrets and preserve managed/live files."""
from dataclasses import asdict, replace
from importlib.util import find_spec
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch
import zipfile

from dndgm4.handouts import HandoutRepository, PublicHandout, validate_saved_state
from dndgm4.storage import CreatureRepository
from dndgm4.world import WorldRepository


@unittest.skipUnless(find_spec("PyQt6"), "PyQt6 is not installed")
class HandoutTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.library = CreatureRepository(self.root / "library.sqlite3")
        self.repo = HandoutRepository(self.library)
        self.world = WorldRepository(self.library.path)
        self.campaign = self.world.campaigns.create_campaign("SECRET campaign")
        self.other = self.world.campaigns.create_campaign("Other")
        self.handout = self.world.create(self.campaign.id, "handout", "SECRET handout title", summary="SECRET summary", dm_notes="SECRET DM notes", details={"player_text": "Find the tower.\nBring a lantern. Élara"})
        self.foreign = self.world.create(self.other.id, "handout", "Foreign", details={"player_text": "Other players"})
        self.quest = self.world.create(self.campaign.id, "quest", "Not a handout")
        from PyQt6.QtGui import QColor, QImage
        self.source = self.root / "SECRET-original-location.png"
        image = QImage(120, 80, QImage.Format.Format_ARGB32)
        image.fill(QColor("#884433"))
        image.setText("Description", "SECRET hidden image metadata C:/Private/location.png")
        self.assertTrue(image.save(str(self.source), "PNG"))
        self.original = self.source.read_bytes()

    def tearDown(self):
        self.temp.cleanup()

    def attach(self):
        return self.repo.import_image(self.campaign.id, self.handout.id, self.source)

    def test_import_copies_sanitized_pixels_and_keeps_original_untouched(self):
        from PyQt6.QtGui import QImage
        asset = self.attach()
        self.assertTrue(asset.selected)
        self.assertEqual((asset.width, asset.height), (120, 80))
        self.assertEqual(self.source.read_bytes(), self.original)
        self.assertNotIn("SECRET", asset.image_path)
        payload = self.repo.public_payload(self.campaign.id, self.handout.id)
        self.assertEqual(set(asdict(payload)), {"text", "image_png"})
        self.assertEqual(payload.text, self.handout.details["player_text"])
        self.assertNotIn(b"SECRET", payload.image_png)
        self.assertEqual(QImage.fromData(payload.image_png, b"PNG").textKeys(), [])
        self.assertEqual(QImage.fromData(payload.image_png, b"PNG").pixelColor(30, 30).name(), "#884433")
        self.assertEqual(HandoutRepository(CreatureRepository(self.library.path)).public_payload(self.campaign.id, self.handout.id), payload)

    def test_export_contains_only_reviewed_text_and_generic_image_member(self):
        self.attach()
        payload = self.repo.public_payload(self.campaign.id, self.handout.id)
        output = self.root / "public.zip"
        self.repo.export_payload(payload, output)
        with zipfile.ZipFile(output) as archive:
            self.assertEqual(archive.namelist(), ["handout.txt", "image.png"])
            self.assertEqual(archive.read("handout.txt"), payload.text.encode("utf-8"))
            self.assertEqual(archive.read("image.png"), payload.image_png)
            for member in archive.infolist():
                self.assertEqual(member.date_time, (1980, 1, 1, 0, 0, 0))
                self.assertEqual(member.comment, b"")
            combined = b"".join(archive.read(name) for name in archive.namelist())
        for secret in (b"SECRET", self.handout.id.encode(), self.campaign.id.encode(), str(self.source).encode()):
            self.assertNotIn(secret, combined)

    def test_text_only_and_image_only_are_valid_but_empty_is_refused(self):
        output = self.root / "text.zip"
        self.repo.export_payload(self.repo.public_payload(self.campaign.id, self.handout.id), output)
        with zipfile.ZipFile(output) as archive:
            self.assertEqual(archive.namelist(), ["handout.txt"])
        blank = self.world.create(self.campaign.id, "handout", "Private name")
        with self.assertRaises(ValueError):
            self.repo.public_payload(self.campaign.id, blank.id)
        self.repo.import_image(self.campaign.id, blank.id, self.source)
        image_only = self.repo.public_payload(self.campaign.id, blank.id)
        self.assertEqual(image_only.text, "")
        self.assertIsNotNone(image_only.image_png)

    def test_foreign_campaign_handout_and_wrong_kind_are_refused_without_files(self):
        for handout_id in (self.foreign.id, self.quest.id, "missing"):
            with self.subTest(handout=handout_id), self.assertRaises(ValueError):
                self.repo.import_image(self.campaign.id, handout_id, self.source)
        self.assertFalse(self.repo.assets_root.exists())
        asset = self.attach()
        for call in (
            lambda: self.repo.get_image(self.other.id, self.handout.id, asset.id),
            lambda: self.repo.select_image(self.other.id, self.foreign.id, asset.id),
            lambda: self.repo.public_payload(self.other.id, self.handout.id),
        ):
            with self.assertRaises(ValueError):
                call()
        self.assertEqual(self.repo.public_payload(self.campaign.id, self.handout.id).text, self.handout.details["player_text"])

    def test_selection_archive_restore_keeps_files_and_one_selected_image(self):
        first, second = self.attach(), self.attach()
        images = self.repo.list_images(self.campaign.id, self.handout.id)
        self.assertEqual([asset.id for asset in images if asset.selected], [second.id])
        self.repo.select_image(self.campaign.id, self.handout.id, first.id)
        archived = self.repo.set_archived(self.campaign.id, self.handout.id, first.id)
        self.assertTrue(archived.archived)
        self.assertFalse(archived.selected)
        self.assertTrue((self.root / first.image_path).is_file())
        self.assertIsNone(self.repo.public_payload(self.campaign.id, self.handout.id).image_png)
        with self.assertRaises(ValueError):
            self.repo.select_image(self.campaign.id, self.handout.id, first.id)
        restored = self.repo.set_archived(self.campaign.id, self.handout.id, first.id, False)
        self.assertFalse(restored.selected)
        self.repo.select_image(self.campaign.id, self.handout.id, first.id)
        self.assertIsNotNone(self.repo.public_payload(self.campaign.id, self.handout.id).image_png)

    def test_failed_import_rolls_back_selection_and_removes_only_new_file(self):
        first = self.attach()
        before = sorted(self.repo.assets_root.iterdir())
        with self.library._connection() as db:
            db.execute("CREATE TRIGGER reject_handout_asset BEFORE INSERT ON handout_assets BEGIN SELECT RAISE(ABORT,'test failure'); END")
        with self.assertRaises(sqlite3.IntegrityError):
            self.attach()
        self.assertEqual(sorted(self.repo.assets_root.iterdir()), before)
        self.assertTrue(self.repo.get_image(self.campaign.id, self.handout.id, first.id).selected)

    def test_filename_collision_never_unlinks_existing_managed_image(self):
        asset = self.attach()
        managed = self.root / asset.image_path
        original = managed.read_bytes()
        with patch("dndgm4.handouts.uuid4", return_value=asset.id), self.assertRaises(FileExistsError):
            self.attach()
        self.assertEqual(managed.read_bytes(), original)
        self.assertEqual(len(self.repo.list_images(self.campaign.id, self.handout.id)), 1)

    def test_invalid_or_oversized_raster_does_not_create_managed_files(self):
        source = self.root / "wrong.png"
        source.write_text("<svg>not a raster</svg>")
        with self.assertRaises(ValueError):
            self.repo.import_image(self.campaign.id, self.handout.id, source)
        with patch("dndgm4.handouts.MAX_IMAGE_BYTES", 10), self.assertRaises(ValueError):
            self.attach()
        self.assertFalse(self.repo.assets_root.exists())

    def test_export_refuses_all_live_state_files_and_managed_assets(self):
        asset = self.attach()
        payload = self.repo.public_payload(self.campaign.id, self.handout.id)
        paths = [self.library.path, self.root / asset.image_path, self.root / "assets" / "new.zip"]
        for name in ("rules.sqlite3", "current_scene.json", "battle_trakker.json", "srd35_spells.json", "rules.sqlite3-wal", "rules.sqlite3-shm", "rules.sqlite3-journal", "library.sqlite3-wal", "library.sqlite3-shm", "library.sqlite3-journal"):
            path = self.root / name
            path.write_bytes(b"saved state")
            paths.append(path)
        for path in paths:
            before = path.read_bytes() if path.is_file() else None
            with self.subTest(path=path.name), self.assertRaises(ValueError):
                self.repo.export_payload(payload, path)
            self.assertEqual(path.read_bytes() if path.is_file() else None, before)

    def test_symlinked_managed_folder_or_image_is_refused(self):
        outside = self.root / "outside"
        outside.mkdir()
        (self.root / "assets").symlink_to(outside, target_is_directory=True)
        with self.assertRaises(ValueError):
            self.attach()
        self.assertEqual(list(outside.iterdir()), [])
        (self.root / "assets").unlink()
        asset = self.attach()
        managed = self.root / asset.image_path
        managed.unlink()
        managed.symlink_to(self.source)
        with self.assertRaises(ValueError):
            self.repo.public_payload(self.campaign.id, self.handout.id)

    def test_failed_export_preserves_existing_destination(self):
        payload = self.repo.public_payload(self.campaign.id, self.handout.id)
        target = self.root / "existing.zip"
        target.write_bytes(b"keep old export")
        with patch("dndgm4.handouts.zipfile.ZipFile.writestr", side_effect=OSError("Disk error")), self.assertRaises(OSError):
            self.repo.export_payload(payload, target)
        self.assertEqual(target.read_bytes(), b"keep old export")
        self.assertEqual(list(self.root.glob(".dndgm4-*")), [])

    def test_recovery_validator_rejects_foreign_links_real_dimensions_and_missing_archived_assets(self):
        asset = self.attach()
        validate_saved_state(self.library)
        for field, value in (("handout_id", self.foreign.id), ("width", 120.5), ("image_path", "../../private.png")):
            with self.library._connection() as db:
                db.execute(f"UPDATE handout_assets SET {field}=? WHERE id=?", (value, asset.id))
            with self.subTest(field=field), self.assertRaises(ValueError):
                validate_saved_state(self.library.path)
            with self.library._connection() as db:
                db.execute(f"UPDATE handout_assets SET {field}=? WHERE id=?", (getattr(asset, field), asset.id))
        self.repo.set_archived(self.campaign.id, self.handout.id, asset.id, True)
        (self.root / asset.image_path).unlink()
        before = self.library.path.read_bytes()
        with self.assertRaises(ValueError):
            validate_saved_state(self.library.path)
        self.assertEqual(self.library.path.read_bytes(), before)

    def test_modified_managed_image_is_refused_and_preserved(self):
        asset = self.attach()
        managed = self.root / asset.image_path
        modified = managed.read_bytes() + b"SECRET injected chunk"
        managed.write_bytes(modified)
        with self.assertRaisesRegex(ValueError, "changed"):
            self.repo.public_payload(self.campaign.id, self.handout.id)
        self.assertEqual(managed.read_bytes(), modified)
