"""Ledger commands conserve money/items and survive retries and stale reviews."""
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
import json
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
import unittest

from dndgm4.models import Creature
from dndgm4.resources import (
    ResourceRepository, carrying_capacity, encumbrance, pounds_to_millilb, validate_saved_state,
)


class ResourceTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.path = Path(self.temp.name) / "library.sqlite3"
        self.repo = ResourceRepository(self.path)
        self.campaign = self.repo.campaigns.create_campaign("Ash Road")
        self.other = self.repo.campaigns.create_campaign("Glass Coast")
        self.hero = self.repo.library.save(Creature(name="Arden", level=3, sheet_json='{"background":"keep this","experience_points":3000}'))
        self.party = self.repo.create_wallet(self.campaign.id, "Party treasury")
        self.purse = self.repo.create_wallet(self.campaign.id, "Arden", self.hero.id)
        self.foreign = self.repo.create_wallet(self.other.id, "Other treasury")

    def tearDown(self):
        self.temp.cleanup()

    def fund(self, copper=1000, request="fund"):
        return self.repo.adjust_money(self.campaign.id, self.party.id, copper, "Starting treasury", request)

    def test_transfer_conserves_funds_persists_and_replay_is_idempotent(self):
        self.fund()
        args = self.campaign.id, self.party.id, self.purse.id, 325, "Supplies", "transfer"
        first = self.repo.transfer_money(*args)
        self.assertEqual(first, self.repo.transfer_money(*args))
        reopened = ResourceRepository(self.path)
        self.assertEqual(reopened.get_wallet(self.campaign.id, self.party.id).copper, 675)
        self.assertEqual(reopened.get_wallet(self.campaign.id, self.purse.id).copper, 325)
        self.assertEqual(len(reopened.operations(self.campaign.id)), 2)
        with self.repo._connection() as db:
            rows = db.execute("SELECT cp_delta FROM resource_ledger WHERE operation_id='transfer'").fetchall()
        self.assertEqual(sum(row[0] for row in rows), 0)

    def test_insufficient_funds_and_late_sql_failure_roll_back_whole_command(self):
        self.fund(100)
        with self.assertRaises(ValueError):
            self.repo.transfer_money(self.campaign.id, self.party.id, self.purse.id, 101, "Too much", "failed")
        with self.repo._connection() as db:
            db.execute("CREATE TRIGGER reject_recipient BEFORE INSERT ON resource_ledger WHEN NEW.account_id='" + self.purse.id + "' BEGIN SELECT RAISE(ABORT,'test rejection'); END")
        with self.assertRaises(sqlite3.IntegrityError):
            self.repo.transfer_money(self.campaign.id, self.party.id, self.purse.id, 50, "Atomic", "failed-sql")
        self.assertEqual(self.repo.get_wallet(self.campaign.id, self.party.id).copper, 100)
        self.assertEqual(len(self.repo.operations(self.campaign.id)), 1)

    def test_same_request_with_different_payload_or_campaign_is_rejected(self):
        self.fund()
        with self.assertRaises(ValueError):
            self.repo.adjust_money(self.campaign.id, self.party.id, 5, "Different", "fund")
        with self.assertRaises(ValueError):
            self.repo.adjust_money(self.other.id, self.foreign.id, 1000, "Starting treasury", "fund")

    def test_corrupt_operation_metadata_reports_error_and_preserves_every_saved_row(self):
        self.fund()
        invalid = ("[]", "null", "{}", '{"request":{},"result":{}}',
                   '{"request":{"command":"adjust_money"}}',
                   '{"request":{},"request":{},"result":{"copper":1}}',
                   "[" * 1100 + "0" + "]" * 1100)
        for payload in invalid:
            with self.subTest(payload=payload[:60]):
                with self.repo._connection() as db:
                    db.execute("UPDATE resource_operations SET payload_json=? WHERE id='fund'", (payload,))
                with self.assertRaisesRegex(ValueError, "damaged"):
                    self.fund()
                self.assertEqual(self.repo.get_wallet(self.campaign.id, self.party.id).copper, 1000)
                self.assertEqual(self.repo.operations(self.campaign.id)[0]["payload_json"], payload)

    def test_sqlite_real_copper_corruption_is_refused_without_new_operations(self):
        self.fund(10)
        with self.repo._connection() as db:
            db.execute("UPDATE resource_ledger SET cp_delta=10.5 WHERE operation_id='fund'")
        with self.assertRaisesRegex(ValueError, "whole number"):
            self.repo.get_wallet(self.campaign.id, self.party.id)
        with self.assertRaisesRegex(ValueError, "whole number"):
            self.repo.adjust_money(self.campaign.id, self.party.id, 1, "Refused", "invalid-copper")
        with self.repo._connection() as db:
            self.assertEqual(db.execute("SELECT cp_delta FROM resource_ledger WHERE operation_id='fund'").fetchone()[0], 10.5)
        self.assertEqual(len(self.repo.operations(self.campaign.id)), 1)

    def test_sqlite_real_xp_and_item_corruption_do_not_reach_sheets_or_inventory_commands(self):
        self.repo.award(self.campaign.id, [{"wallet_id": self.purse.id, "copper": 0, "xp": 10}], "Reward", "award")
        item = self.repo.add_item(self.campaign.id, self.purse.id, "Ration", 2, 1000, "Found", "food")
        with self.repo._connection() as db:
            db.execute("UPDATE resource_ledger SET xp_delta=10.5 WHERE operation_id='award'")
            db.execute("UPDATE resource_items SET quantity=1.5 WHERE id=?", (item["item_id"],))
        with self.assertRaisesRegex(ValueError, "whole number"):
            self.repo.preview_xp(self.campaign.id, self.purse.id)
        with self.assertRaisesRegex(ValueError, "whole number"):
            self.repo.consume_item(self.campaign.id, item["item_id"], 1, "Refused", "invalid-item")
        with self.assertRaisesRegex(ValueError, "whole number"):
            self.repo.carried_weight(self.campaign.id, self.purse.id)
        self.assertEqual(self.repo.library.get(self.hero.id), self.hero)
        self.assertEqual(len(self.repo.operations(self.campaign.id)), 2)

    def test_simultaneous_retries_credit_only_once(self):
        def submit(_):
            repo = ResourceRepository(self.path)
            return repo.award(self.campaign.id, [{"wallet_id": self.purse.id, "copper": 200, "xp": 50}], "Defeated the guard", "same-award")
        with ThreadPoolExecutor(max_workers=4) as pool:
            results = list(pool.map(submit, range(4)))
        self.assertTrue(all(result == results[0] for result in results))
        self.assertEqual(self.repo.get_wallet(self.campaign.id, self.purse.id).copper, 200)
        self.assertEqual(self.repo.preview_xp(self.campaign.id, self.purse.id).pending, 50)

    def test_reward_sources_are_checked_and_failed_recipient_undoes_prior_credit(self):
        session = self.repo.campaigns.create_session(self.other.id, "Foreign session")
        with self.assertRaises(ValueError):
            self.repo.award(self.campaign.id, [{"wallet_id": self.purse.id, "copper": 10, "xp": 0}], "Invalid source", "foreign-source", session_id=session.id)
        with self.assertRaises(ValueError):
            self.repo.award(self.campaign.id, [
                {"wallet_id": self.purse.id, "copper": 10, "xp": 0},
                {"wallet_id": self.foreign.id, "copper": 10, "xp": 0},
            ], "Invalid recipient", "foreign-target")
        self.assertEqual(self.repo.get_wallet(self.campaign.id, self.purse.id).copper, 0)
        self.assertEqual(self.repo.operations(self.campaign.id), [])

    def test_session_encounter_provenance_is_persisted(self):
        session = self.repo.campaigns.create_session(self.campaign.id, "Rescue")
        encounter = self.repo.campaigns.create_encounter(session.id, "The bridge")
        self.repo.award(self.campaign.id, [{"wallet_id": self.purse.id, "copper": 10, "xp": 100}], "Bridge rescue", "rescue", encounter_id=encounter.id)
        payload = json.loads(self.repo.operations(self.campaign.id)[0]["payload_json"])
        self.assertEqual(payload["request"]["encounter_id"], encounter.id)
        with self.repo._connection() as db:
            row = db.execute("SELECT session_id FROM resource_ledger WHERE operation_id='rescue'").fetchone()
        self.assertEqual(row[0], session.id)

    def test_xp_remains_pending_until_explicit_apply_and_never_levels_character(self):
        self.repo.award(self.campaign.id, [{"wallet_id": self.purse.id, "copper": 100, "xp": 5000}], "Dragon reward", "dragon")
        self.assertEqual(self.repo.library.get(self.hero.id), self.hero)
        preview = self.repo.preview_xp(self.campaign.id, self.purse.id)
        self.assertEqual((preview.current, preview.pending, preview.target), (3000, 5000, 8000))
        result = self.repo.apply_xp(preview, "apply-dragon")
        self.assertEqual(result, self.repo.apply_xp(preview, "apply-dragon"))
        saved = self.repo.library.get(self.hero.id)
        self.assertEqual(saved.level, 3)
        self.assertEqual(saved.max_hit_points, self.hero.max_hit_points)
        self.assertEqual(json.loads(saved.sheet_json), {"background": "keep this", "experience_points": 8000})
        self.assertEqual(self.repo.preview_xp(self.campaign.id, self.purse.id).pending, 0)
        with self.assertRaises(ValueError):
            self.repo.apply_xp(preview, "stale-second-apply")

    def test_stale_xp_review_is_rejected_without_losing_other_character_edits(self):
        self.repo.award(self.campaign.id, [{"wallet_id": self.purse.id, "copper": 0, "xp": 100}], "First", "first")
        old = self.repo.preview_xp(self.campaign.id, self.purse.id)
        self.repo.award(self.campaign.id, [{"wallet_id": self.purse.id, "copper": 0, "xp": 50}], "Second", "second")
        with self.assertRaises(ValueError):
            self.repo.apply_xp(old, "stale")
        edited = replace(self.hero, notes="Fresh DM note")
        self.repo.library.save(edited)
        self.repo.apply_xp(self.repo.preview_xp(self.campaign.id, self.purse.id), "fresh")
        self.assertEqual(self.repo.library.get(self.hero.id).notes, "Fresh DM note")

    def test_items_split_transfer_without_changing_creature_template(self):
        sack = self.repo.create_container(self.campaign.id, self.purse.id, "Sack", tare_millilb=500, capacity_millilb=5000)
        item = self.repo.add_item(self.campaign.id, self.party.id, "Rations", 10, 1000, "Provisioner", "rations", unit_cp=50)
        args = self.campaign.id, item["item_id"], self.purse.id, 3, "Supplies", "split"
        result = self.repo.transfer_item(*args, container_id=sack.id)
        self.assertEqual(result, self.repo.transfer_item(*args, container_id=sack.id))
        self.assertEqual(self.repo.list_items(self.campaign.id, self.party.id)[0].quantity, 7)
        self.assertEqual(self.repo.list_items(self.campaign.id, self.purse.id)[0].quantity, 3)
        self.assertEqual(self.repo.carried_weight(self.campaign.id, self.purse.id), 3500)
        self.assertEqual(self.repo.library.get(self.hero.id), self.hero)
        self.assertEqual(ResourceRepository(self.path).list_containers(self.campaign.id, self.purse.id), [sack])

    def test_capacity_foreign_container_and_overspend_leave_inventory_intact(self):
        sack = self.repo.create_container(self.campaign.id, self.purse.id, "Small sack", capacity_millilb=1000)
        item = self.repo.add_item(self.campaign.id, self.party.id, "Rations", 4, 1000, "Provisioner", "rations")
        for count in (2, 5):
            with self.assertRaises(ValueError):
                self.repo.transfer_item(self.campaign.id, item["item_id"], self.purse.id, count, "Move", "move" + str(count), container_id=sack.id)
        with self.assertRaises(ValueError):
            self.repo.add_item(self.campaign.id, self.party.id, "Arrow", 1, 10, "Found", "bad-container", container_id=sack.id)
        self.assertEqual(self.repo.list_items(self.campaign.id, self.party.id)[0].quantity, 4)
        self.assertEqual(self.repo.list_items(self.campaign.id, self.purse.id), [])

    def test_consumption_is_audited_idempotent_and_keeps_depleted_entry(self):
        item = self.repo.add_item(self.campaign.id, self.purse.id, "Potion", 1, 100, "Found", "potion")
        args = self.campaign.id, item["item_id"], 1, "Healing", "drink"
        self.repo.consume_item(*args)
        self.repo.consume_item(*args)
        self.assertEqual(self.repo.list_items(self.campaign.id, self.purse.id), [])
        self.assertEqual(self.repo.list_items(self.campaign.id, self.purse.id, include_depleted=True)[0].quantity, 0)
        self.assertEqual(len(self.repo.operations(self.campaign.id)), 2)

    def test_invalid_numbers_and_foreign_reads_are_rejected(self):
        for value in (True, -1, 1.1, "10"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                self.repo.award(self.campaign.id, [{"wallet_id": self.purse.id, "copper": value, "xp": 0}], "Invalid", "bad")
        for method in (self.repo.get_wallet, self.repo.list_items, self.repo.list_containers, self.repo.carried_weight):
            with self.assertRaises(ValueError):
                method(self.campaign.id, self.foreign.id)
        with self.assertRaises(ValueError):
            self.repo.create_wallet(self.campaign.id, "Duplicate purse", self.hero.id)

    def test_readonly_recovery_validator_accepts_history_and_does_not_normalize_sheets(self):
        self.fund()
        self.repo.transfer_money(self.campaign.id, self.party.id, self.purse.id, 50, "Share", "transfer")
        self.repo.award(self.campaign.id, [{"wallet_id": self.purse.id, "copper": 0, "xp": 100}], "Reward", "award")
        self.repo.apply_xp(self.repo.preview_xp(self.campaign.id, self.purse.id), "apply")
        self.repo.add_item(self.campaign.id, self.purse.id, "Rations", 3, 1000, "Found", "rations")
        # Old sheet XP formats do not stop restoring otherwise valid history.
        saved = self.repo.library.get(self.hero.id)
        self.repo.library.save(replace(saved, sheet_json='{"xp":"legacy note"}'))
        before = self.path.read_bytes()
        validate_saved_state(self.path)
        self.assertEqual(self.path.read_bytes(), before)
        self.assertEqual(self.repo.library.get(self.hero.id).sheet_json, '{"xp":"legacy note"}')

    def test_recovery_validator_rejects_foreign_container_and_malformed_ledger(self):
        self.fund()
        bag = self.repo.create_container(self.campaign.id, self.purse.id, "Bag")
        self.repo.add_item(self.campaign.id, self.purse.id, "Ration", 1, 1000, "Found", "ration", container_id=bag.id)
        with self.repo._connection() as db:
            db.execute("UPDATE resource_containers SET wallet_id=? WHERE id=?", (self.foreign.id, bag.id))
        before = self.path.read_bytes()
        with self.assertRaises(ValueError):
            validate_saved_state(self.path)
        self.assertEqual(self.path.read_bytes(), before)
        with self.repo._connection() as db:
            db.execute("UPDATE resource_containers SET wallet_id=? WHERE id=?", (self.purse.id, bag.id))
            db.execute("UPDATE resource_ledger SET cp_delta=999 WHERE operation_id='fund'")
        with self.assertRaisesRegex(ValueError, "disagree"):
            validate_saved_state(self.path)

    def test_recovery_validator_checks_applied_xp_links_and_stored_command_shapes(self):
        self.repo.award(self.campaign.id, [{"wallet_id": self.purse.id, "copper": 0, "xp": 50}], "Reward", "award")
        self.repo.apply_xp(self.repo.preview_xp(self.campaign.id, self.purse.id), "apply")
        with self.repo._connection() as db:
            db.execute("DELETE FROM resource_xp_applied")
        with self.assertRaisesRegex(ValueError, "applied reward"):
            validate_saved_state(self.path)
        with self.repo._connection() as db:
            db.execute("UPDATE resource_operations SET payload_json='[]' WHERE id='apply'")
        with self.assertRaisesRegex(ValueError, "metadata is damaged"):
            validate_saved_state(self.path)


class CarryingTests(unittest.TestCase):
    def test_srd_table_and_size_tremendous_strength_multipliers(self):
        self.assertEqual(carrying_capacity(10), (33, 66, 100))
        self.assertEqual(carrying_capacity(18), (100, 200, 300))
        self.assertEqual(carrying_capacity(30), (532, 1064, 1600))
        self.assertEqual(carrying_capacity(10, "Small"), (24.75, 49.5, 75))
        self.assertEqual(carrying_capacity(10, quadruped=True), (49.5, 99, 150))

    def test_boundaries_and_exact_fractional_weights(self):
        self.assertEqual(pounds_to_millilb("0.125"), 125)
        self.assertEqual(encumbrance(33000, 10)["load"], "light")
        self.assertEqual(encumbrance(33001, 10)["load"], "medium")
        self.assertEqual(encumbrance(66001, 10)["max_dex"], 1)
        self.assertEqual(encumbrance(100001, 10)["load"], "overloaded")
        for value in ("NaN", "Infinity", "-1", "0.0001", "oops"):
            with self.assertRaises(ValueError):
                pounds_to_millilb(value)
