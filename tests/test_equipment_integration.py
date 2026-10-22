"""Reviewed character calculations reach combat without changing saved defenses."""
from dataclasses import replace
from importlib.util import find_spec
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch


@unittest.skipUnless(find_spec("PyQt6") is not None, "PyQt6 unavailable")
class EquipmentIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        from PyQt6.QtWidgets import QApplication
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        from dndgm4.models import Creature
        from dndgm4.storage import CreatureRepository
        from dndgm4.ui import MainWindow
        self.tmp = TemporaryDirectory()
        self.library = CreatureRepository(Path(self.tmp.name) / "library.sqlite3")
        self.hero = self.library.save(Creature(name="Bran", character_class="Fighter", race_type="Human",
            level=4, armor_class=27, max_hit_points=30, strength=16, dexterity=14,
            sheet_json='{"feats":[],"class_levels":{"Fighter":4},"custom":{"keep":true}}'))
        profile = dict(version=1, armor="Chain shirt", shield="None", weapon="Longsword", size="Medium",
            proficiency_confirmed=True, class_levels={"Fighter": 4}, weapon_focus_weapon="",
            weapon_finesse=False, monk_ac_eligible=False, paladin_grace_eligible=False,
            review_basis={})
        profile["review_basis"] = {"class": self.hero.character_class, "race": self.hero.race_type, "level": self.hero.level}
        sheet = json.loads(self.hero.sheet_json); sheet["combat_loadout"] = profile
        self.hero = self.library.save(replace(self.hero, sheet_json=json.dumps(sheet)))
        self.window = MainWindow(self.library)
        self.host = self.window._ensure_battle_tracker()
        self.host._run(lambda: self.host._add_records([self.hero, self.hero]))
        self.a, self.b = self.host.battle.fighters
        self.host.battle.set_initiative(self.a.uid, 20)
        self.host.battle.set_initiative(self.b.uid, 10)
        self.host.battle.begin()
        self.host.open_advanced()
        self.desk = self.host.advanced_desk
        self.desk.attack_actor.setCurrentIndex(self.desk.attack_actor.findData(self.a.uid))
        self.desk.attack_target.setCurrentIndex(self.desk.attack_target.findData(self.b.uid))

    def tearDown(self):
        self.desk.hide()
        self.host.hide()
        self.window.close()
        self.tmp.cleanup()

    def test_declining_review_preserves_roll_inputs_and_character(self):
        self.desk.attack_bonus.setValue(99)
        with patch.object(self.desk, "_confirm_calculation", return_value=False):
            self.desk.review_character_attack()
        self.assertEqual(self.desk.attack_bonus.value(), 99)
        self.assertEqual(self.library.get(self.hero.id), self.hero)
        self.assertEqual(self.a.ac, 27)

    def test_explicit_attack_and_target_defense_use_separate_calculated_values(self):
        with patch.object(self.desk, "_confirm_calculation", return_value=True):
            self.desk.review_character_attack()
            self.desk.review_target_defense()
        self.assertEqual(self.desk.attack_bonus.value(), 7)
        self.assertEqual(self.desk.attack_damage.text(), "1d8+3")
        self.assertTrue(self.desk.use_reviewed_defense.isChecked())
        with patch.object(self.host.battle, "resolve_attack", return_value=None) as resolve:
            self.desk.resolve_attack()
        self.assertEqual(resolve.call_args.kwargs["target_ac_override"], 16)
        self.assertEqual(self.b.ac, 27)
        self.assertEqual(self.library.get(self.hero.id), self.hero)

    def test_changed_actor_cannot_reuse_another_actors_reviewed_inputs(self):
        with patch.object(self.desk, "_confirm_calculation", return_value=True):
            self.desk.review_character_attack()
        self.desk.attack_actor.setCurrentIndex(self.desk.attack_actor.findData(self.b.uid))
        with patch("dndgm4.battle_desk_ui.QMessageBox.warning") as warning, patch.object(self.host.battle, "resolve_attack") as resolve:
            self.desk.resolve_attack()
        warning.assert_called_once()
        resolve.assert_not_called()

    def test_expired_supported_attack_requires_review_but_manual_edits_remain_available(self):
        key = self.host.battle.add_effect("Bless", target_id=self.a.uid, anchor_id=self.a.uid,
            duration=1, mechanics={"version": 1, "spell": "Bless"})
        with patch.object(self.desk, "_confirm_calculation", return_value=True):
            self.desk.review_character_attack()
        self.assertEqual(self.desk.attack_bonus.value(), 8)
        self.host.battle.cancel_effect(key)
        with patch("dndgm4.battle_desk_ui.QMessageBox.warning"), patch.object(self.host.battle, "resolve_attack") as resolve:
            self.desk.resolve_attack()
        resolve.assert_not_called()
        self.desk.attack_bonus.setValue(7)
        with patch.object(self.host.battle, "resolve_attack", return_value=None) as manual:
            self.desk.resolve_attack()
        manual.assert_called_once()

    def test_target_effect_expiration_never_leaves_permanent_elevated_ac(self):
        key = self.host.battle.add_effect("Shield", target_id=self.b.uid, anchor_id=self.a.uid,
            duration=1, mechanics={"version": 1, "spell": "Shield"})
        with patch.object(self.desk, "_confirm_calculation", return_value=True):
            self.desk.review_target_defense()
        self.assertEqual(self.desk._target_suggestion[2]["ac"], 20)
        self.host.battle.cancel_effect(key)
        with patch("dndgm4.battle_desk_ui.QMessageBox.warning"), patch.object(self.host.battle, "resolve_attack") as resolve:
            self.desk.resolve_attack()
        resolve.assert_not_called()
        self.assertEqual(self.b.ac, 27)

    def test_bless_fear_save_is_explicit_and_stale_copy_cannot_roll(self):
        self.desk.save_actor.setCurrentIndex(self.desk.save_actor.findData(self.a.uid))
        self.desk.save_kind.setCurrentText("Will")
        key = self.host.battle.add_effect("Bless", target_id=self.a.uid, anchor_id=self.a.uid,
            duration=1, mechanics={"version": 1, "spell": "Bless"})
        with patch.object(self.desk, "_confirm_calculation", return_value=True):
            self.desk.review_character_save()
            ordinary = self.desk.save_mod.value()
            self.desk.fear_save.setChecked(True)
            self.desk.review_character_save()
        self.assertEqual(self.desk.save_mod.value(), ordinary + 1)
        self.host.battle.cancel_effect(key)
        with patch("dndgm4.battle_desk_ui.QMessageBox.warning"), patch.object(self.host.battle, "resolve_check") as roll:
            self.desk.resolve_save()
        roll.assert_not_called()

    def test_supported_effect_review_is_required_and_uses_explicit_recipient(self):
        self.desk.supported_spell.setCurrentText("Mage Armor")
        self.desk.effect_target.setCurrentIndex(self.desk.effect_target.findData(self.a.uid))
        with patch.object(self.desk, "_confirm_calculation", return_value=False):
            self.desk.add_supported_effect()
        self.assertEqual(self.host.battle.effects, [])
        with patch.object(self.desk, "_confirm_calculation", return_value=True):
            self.desk.add_supported_effect()
        self.assertEqual(self.host.battle.effects[0]["mechanics"], {"version": 1, "spell": "Mage Armor"})
        self.assertEqual(self.host.battle.effects[0]["target_id"], self.a.uid)
        self.assertEqual(self.library.get(self.hero.id), self.hero)

    def test_first_level_editor_roundtrip_preserves_reviewed_profile(self):
        from dndgm4.roll_ui import _merge_edit_metadata
        original = replace(self.hero, level=1)
        edited = replace(original, sheet_json='{"feats":[],"equipment":["Dagger"]}')
        merged = _merge_edit_metadata(original, edited)
        self.assertEqual(json.loads(merged.sheet_json)["combat_loadout"], json.loads(original.sheet_json)["combat_loadout"])
        self.assertEqual(json.loads(merged.sheet_json)["custom"], {"keep": True})
