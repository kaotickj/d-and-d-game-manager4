"""Campaign-clock transactions preserve game records and reject stale reviews."""
from dataclasses import replace
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from dndgm4.campaign_time import CalendarSpec, CampaignTimeRepository, validate_saved_state
from dndgm4.models import Creature
from dndgm4.world import WorldRepository


class CampaignTimeTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.path = Path(self.temp.name) / "library.sqlite3"
        self.repo = CampaignTimeRepository(self.path)
        self.campaign = self.repo.campaigns.create_campaign("Ash Road")
        self.other = self.repo.campaigns.create_campaign("Other campaign")
        self.hero = self.repo.library.save(Creature(name="Élara", kind="pc", max_hit_points=12))
        self.world = WorldRepository(self.path)

    def tearDown(self):
        self.temp.cleanup()

    def test_custom_calendar_round_trip_unequal_months_year_and_hour_boundaries(self):
        calendar = CalendarSpec("Ember reckoning", (("Thaw", 2), ("Ember", 3)), 10, 400)
        self.assertEqual(CalendarSpec.from_json(calendar.to_json()), calendar)
        self.assertEqual(calendar.date_parts(2 * 600 + 61), (400, "Ember", 1, 1, 1))
        self.assertEqual(calendar.date_parts(5 * 600), (401, "Thaw", 1, 0, 0))
        state = self.repo.configure_calendar(self.campaign.id, calendar, expected_revision=0)
        self.assertEqual(state.minutes, 0)
        reopened = CampaignTimeRepository(self.path).get_clock(self.campaign.id)
        self.assertEqual(reopened, state)
        self.assertEqual(self.repo.get_clock(self.other.id).calendar, CalendarSpec())

    def test_invalid_calendars_and_elapsed_values_fail_without_clock_change(self):
        for months in ((), (("Month", 0),), (("Same", 2), ("same", 4))):
            with self.assertRaises(ValueError):
                CalendarSpec(months=months)
        for value in (True, -1, 0, "60", 1.5):
            with self.subTest(value=value), self.assertRaises(ValueError):
                self.repo.preview_advance(self.campaign.id, value, "Wait")
        self.assertEqual(self.repo.get_clock(self.campaign.id).minutes, 0)
        self.assertEqual(self.repo.history(self.campaign.id), [])

    def test_legacy_calendar_is_preserved_and_incompatible_day_length_is_rejected(self):
        with self.repo.library._connection() as db:
            db.execute("INSERT INTO campaign_clock(campaign_id,minutes,calendar_name,days_per_month,months_per_year) VALUES(?,?,?,?,?)",
                       (self.campaign.id, 123, "Old calendar", 20, 10))
        state = self.repo.get_clock(self.campaign.id)
        self.assertEqual(state.calendar.name, "Old calendar")
        self.assertEqual(state.calendar.days_per_year, 200)
        self.assertEqual(state.minutes, 123)
        self.world.create(self.campaign.id, "event", "Late watch", details={"day": 1, "time": "23:00"})
        with self.assertRaisesRegex(ValueError, "outside this calendar"):
            self.repo.configure_calendar(self.campaign.id, CalendarSpec(hours_per_day=10), expected_revision=0)
        self.assertEqual(self.repo.get_clock(self.campaign.id), state)

    def test_preview_crosses_world_and_timeline_events_without_changing_any_state(self):
        earlier = self.repo.add_event(self.campaign.id, 0, "Already at this time")
        event = self.repo.add_event(self.campaign.id, 60, "Courier arrives")
        self.repo.add_event(self.other.id, 30, "Secret other campaign")
        world = self.world.create(self.campaign.id, "event", "Moonrise", details={"day": 0, "time": "01:30"})
        cancelled = self.world.create(self.campaign.id, "event", "Cancelled", status="cancelled", details={"day": 0, "time": "00:30"})
        preview = self.repo.preview_advance(self.campaign.id, 120, "Wait for the courier")
        self.assertEqual([e.title for e in preview.events], ["Courier arrives", "Moonrise"])
        self.assertEqual(self.repo.get_clock(self.campaign.id).minutes, 0)
        self.assertEqual(self.world.get(world.id).status, "planned")
        self.assertEqual(self.repo.library.get(self.hero.id), self.hero)
        self.assertEqual(self.repo.history(self.campaign.id), [])
        result = self.repo.apply_preview(preview)
        self.assertEqual(result.minutes, 120)
        self.assertEqual(self.world.get(world.id).status, "planned")
        self.assertEqual(self.repo.library.get(self.hero.id), self.hero)
        self.assertEqual(self.repo.get_clock(self.other.id).minutes, 0)

    def test_stale_clock_calendar_or_crossed_events_require_another_review(self):
        preview = self.repo.preview_advance(self.campaign.id, 60, "Wait")
        self.repo.add_event(self.campaign.id, 30, "New urgent event")
        with self.assertRaisesRegex(ValueError, "timeline or preview changed"):
            self.repo.apply_preview(preview)
        self.assertEqual(self.repo.get_clock(self.campaign.id).minutes, 0)
        preview = self.repo.preview_advance(self.campaign.id, 60, "Wait")
        self.repo.configure_calendar(self.campaign.id, CalendarSpec(name="New calendar"), expected_revision=0)
        with self.assertRaisesRegex(ValueError, "clock changed"):
            self.repo.apply_preview(preview)
        preview = self.repo.preview_advance(self.campaign.id, 60, "Wait")
        self.repo.apply_preview(self.repo.preview_advance(self.campaign.id, 10, "Move first"))
        with self.assertRaisesRegex(ValueError, "clock changed"):
            self.repo.apply_preview(preview)

    def test_double_apply_is_idempotent_and_changed_request_payload_is_rejected(self):
        preview = self.repo.preview_advance(self.campaign.id, 45, "Explore")
        first = self.repo.apply_preview(preview)
        second = self.repo.apply_preview(preview)
        self.assertEqual(first, second)
        self.assertEqual(len(self.repo.history(self.campaign.id)), 1)
        with self.assertRaisesRegex(ValueError, "different content"):
            self.repo.apply_preview(replace(preview, reason="Alter history"))
        self.assertEqual(self.repo.get_clock(self.campaign.id).minutes, 45)

    def test_travel_and_rest_preserve_dice_and_never_grant_recovery_or_spend_supplies(self):
        preview = self.repo.preview_travel(self.campaign.id, "10", "3", travelers=4,
                                          encounter_roll=True, roller=lambda: 17)
        self.assertEqual(preview.after_minutes, 200)
        self.assertEqual(json.loads(preview.details_json)["encounter_d20"], 17)
        self.assertIn("0.556", " ".join(preview.consequences))
        self.repo.apply_preview(preview)
        rest = self.repo.preview_rest(self.campaign.id, "8.5", "Camp behind the ridge")
        self.assertEqual(rest.after_minutes, 710)
        self.repo.apply_preview(rest)
        history = self.repo.history(self.campaign.id)
        travel_payload = json.loads(history[1]["payload_json"])
        self.assertEqual(json.loads(travel_payload["details_json"])["encounter_d20"], 17)
        self.assertEqual(self.repo.library.get(self.hero.id), self.hero)
        with self.repo.library._connection() as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM resource_ledger").fetchone()[0], 0)
        for distance, speed in (("NaN", "3"), ("1", "0"), ("-1", "3"), (True, "3")):
            with self.assertRaises(ValueError):
                self.repo.preview_travel(self.campaign.id, distance, speed)

    def test_weather_preview_save_reopen_and_stale_overwrite_protection(self):
        preview = self.repo.preview_weather(self.campaign.id, 3, roller=lambda: 19)
        other = self.repo.preview_weather(self.campaign.id, 3, roller=lambda: 2)
        self.assertIsNone(self.repo.weather(self.campaign.id, 3))
        saved = self.repo.apply_weather(preview)
        self.assertEqual(saved["roll"], 19)
        self.assertEqual(self.repo.apply_weather(preview), saved)
        self.assertEqual(CampaignTimeRepository(self.path).weather(self.campaign.id, 3), saved)
        with self.assertRaisesRegex(ValueError, "saved weather changed"):
            self.repo.apply_weather(other)
        self.assertIsNone(self.repo.weather(self.other.id, 3))

    def test_wrong_campaign_cancel_and_failed_sql_leave_clock_and_history_intact(self):
        event = self.repo.add_event(self.campaign.id, 60, "A warning")
        with self.assertRaises(ValueError):
            self.repo.cancel_event(self.other.id, event.id)
        self.assertEqual(len(self.repo.timeline(self.campaign.id)), 1)
        self.repo.cancel_event(self.campaign.id, event.id)
        self.assertEqual(self.repo.timeline(self.campaign.id), ())
        preview = self.repo.preview_advance(self.campaign.id, 60, "Wait")
        with self.repo.library._connection() as db:
            db.execute("CREATE TRIGGER reject_time BEFORE INSERT ON campaign_time_details BEGIN SELECT RAISE(ABORT,'simulated failure'); END")
        import sqlite3
        with self.assertRaises(sqlite3.IntegrityError):
            self.repo.apply_preview(preview)
        self.assertEqual(self.repo.get_clock(self.campaign.id).minutes, 0)
        self.assertEqual(self.repo.history(self.campaign.id), [])

    def test_corrupt_world_event_is_reported_without_erasing_it_or_advancing(self):
        event = self.world.create(self.campaign.id, "event", "Unreadable event")
        with self.repo.library._connection() as db:
            db.execute("UPDATE world_records SET details_json='not json' WHERE id=?", (event.id,))
        with self.assertRaisesRegex(ValueError, "invalid JSON"):
            self.repo.preview_advance(self.campaign.id, 60, "Wait")
        self.assertEqual(self.repo.get_clock(self.campaign.id).minutes, 0)
        with self.repo.library._connection() as db:
            self.assertEqual(db.execute("SELECT details_json FROM world_records WHERE id=?", (event.id,)).fetchone()[0], "not json")

    def test_corrupt_clock_revision_is_reported_without_advancing_or_replacing_it(self):
        self.repo.get_clock(self.campaign.id)
        with self.repo.library._connection() as db:
            db.execute("UPDATE campaign_time_settings SET revision='broken' WHERE campaign_id=?", (self.campaign.id,))
        with self.assertRaisesRegex(ValueError, "Saved clock revision"):
            self.repo.preview_advance(self.campaign.id, 60, "Wait")
        with self.repo.library._connection() as db:
            self.assertEqual(db.execute("SELECT revision FROM campaign_time_settings WHERE campaign_id=?", (self.campaign.id,)).fetchone()[0], "broken")
            self.assertEqual(db.execute("SELECT minutes FROM campaign_clock WHERE campaign_id=?", (self.campaign.id,)).fetchone()[0], 0)
            self.assertEqual(db.execute("SELECT COUNT(*) FROM time_changes").fetchone()[0], 0)

    def test_corrupt_timeline_time_is_reported_before_sql_can_omit_it(self):
        event = self.repo.add_event(self.campaign.id, 5, "A warning")
        with self.repo.library._connection() as db:
            db.execute("UPDATE campaign_timeline SET at_minutes='broken' WHERE id=?", (event.id,))
        with self.assertRaisesRegex(ValueError, "Saved event time"):
            self.repo.preview_advance(self.campaign.id, 10, "Wait")
        with self.repo.library._connection() as db:
            self.assertEqual(db.execute("SELECT at_minutes FROM campaign_timeline WHERE id=?", (event.id,)).fetchone()[0], "broken")
            self.assertEqual(db.execute("SELECT minutes FROM campaign_clock WHERE campaign_id=?", (self.campaign.id,)).fetchone()[0], 0)
            self.assertEqual(db.execute("SELECT COUNT(*) FROM time_changes").fetchone()[0], 0)

    def test_corrupt_weather_is_reported_and_not_replaced_by_a_new_roll(self):
        preview = self.repo.preview_weather(self.campaign.id, 0, roller=lambda: 5)
        self.repo.apply_weather(preview)
        with self.repo.library._connection() as db:
            db.execute("UPDATE campaign_weather SET roll='broken' WHERE campaign_id=? AND day=0", (self.campaign.id,))
        with self.assertRaisesRegex(ValueError, "Saved weather d20"):
            self.repo.preview_weather(self.campaign.id, 0, roller=lambda: 10)
        with self.repo.library._connection() as db:
            self.assertEqual(db.execute("SELECT roll FROM campaign_weather WHERE campaign_id=? AND day=0", (self.campaign.id,)).fetchone()[0], "broken")

    def _populate_for_validation(self):
        self.repo.add_event(self.campaign.id, 30, "A courier")
        cancelled = self.repo.add_event(self.campaign.id, 500, "Cancelled patrol")
        self.repo.cancel_event(self.campaign.id, cancelled.id)
        self.repo.apply_preview(self.repo.preview_travel(self.campaign.id, "3", "3", travelers=2,
                                                       encounter_roll=True, roller=lambda: 7))
        self.repo.apply_preview(self.repo.preview_rest(self.campaign.id, "1"))
        self.repo.apply_preview(self.repo.preview_advance(self.campaign.id, 30, "Wait"))
        self.repo.apply_weather(self.repo.preview_weather(self.campaign.id, 2, roller=lambda: 19))
        self.repo.campaigns.save_campaign(replace(self.other, archived=True))
        self.repo.get_clock(self.other.id)
        return cancelled

    @staticmethod
    def _database_dump(path):
        from contextlib import closing
        import sqlite3
        with closing(sqlite3.connect(path)) as db:
            return tuple(db.iterdump())

    def test_recovery_validation_is_read_only_for_complete_history_and_archived_campaigns(self):
        self._populate_for_validation()
        before = self._database_dump(self.path)
        raw_before = self.path.read_bytes()
        counts = validate_saved_state(self.path)
        self.assertEqual(counts["campaign_clock"], 2)
        self.assertEqual(counts["campaign_time_settings"], 2)
        self.assertEqual(counts["time_changes"], 3)
        self.assertEqual(counts["campaign_time_details"], 3)
        self.assertEqual(counts["campaign_timeline"], 2)
        self.assertEqual(counts["campaign_weather"], 1)
        self.assertEqual(self._database_dump(self.path), before)
        self.assertEqual(self.path.read_bytes(), raw_before)

    def test_recovery_validation_does_not_initialize_missing_optional_tables_or_clocks(self):
        from dndgm4.campaigns import CampaignRepository
        legacy_path = Path(self.temp.name) / "legacy.sqlite3"
        campaigns = CampaignRepository(legacy_path)
        campaigns.create_campaign("Never opened a clock")
        before = self._database_dump(legacy_path)
        counts = validate_saved_state(legacy_path)
        self.assertTrue(all(count == 0 for count in counts.values()))
        self.assertEqual(self._database_dump(legacy_path), before)

    def test_recovery_validation_preserves_repairable_world_event_calendar_planning(self):
        self.repo.configure_calendar(self.campaign.id, CalendarSpec(hours_per_day=10), expected_revision=0)
        event = self.world.create(self.campaign.id, "event", "A late-world event", details={"day": 100, "time": "23:00"})
        before = self._database_dump(self.path)
        validate_saved_state(self.path)
        self.assertEqual(self.world.get(event.id).details["time"], "23:00")
        self.assertEqual(self._database_dump(self.path), before)

    def test_recovery_validation_rejects_corruption_in_every_time_table_without_normalizing_it(self):
        self._populate_for_validation()
        import sqlite3
        from contextlib import closing
        cases = (
            ("UPDATE campaign_clock SET minutes='broken' WHERE campaign_id=?", "Saved campaign minutes"),
            ("UPDATE campaign_clock SET days_per_month=0 WHERE campaign_id=?", "days per month"),
            ("UPDATE campaign_time_settings SET revision=0.5 WHERE campaign_id=?", "clock revision"),
            ("UPDATE campaign_time_settings SET calendar_json='[]' WHERE campaign_id=?", "calendar"),
            ("UPDATE time_changes SET before_minutes='broken' WHERE campaign_id=?", "starting minutes"),
            ("UPDATE time_changes SET after_minutes=0 WHERE campaign_id=?", "advance"),
            ("UPDATE campaign_time_details SET payload_json='[]' WHERE change_id IN (SELECT id FROM time_changes WHERE campaign_id=?)", "details"),
            ("UPDATE campaign_timeline SET at_minutes='broken' WHERE campaign_id=? AND cancelled=1", "event time"),
            ("UPDATE campaign_timeline SET cancelled=0.5 WHERE campaign_id=?", "cancelled flag"),
            ("UPDATE campaign_weather SET roll=21 WHERE campaign_id=?", "d20 roll"),
            ("UPDATE campaign_weather SET day='broken' WHERE campaign_id=?", "weather day"),
            ("UPDATE campaign_weather SET description='' WHERE campaign_id=?", "weather description"),
        )
        for index, (sql, message) in enumerate(cases):
            with self.subTest(sql=sql):
                staged = Path(self.temp.name) / f"staged-{index}.sqlite3"
                with closing(sqlite3.connect(self.path)) as source, closing(sqlite3.connect(staged)) as destination:
                    source.backup(destination)
                    destination.execute(sql, (self.campaign.id,))
                    destination.commit()
                before = self._database_dump(staged)
                with self.assertRaisesRegex(ValueError, message):
                    validate_saved_state(staged)
                self.assertEqual(self._database_dump(staged), before)

    def test_recovery_validation_checks_archived_campaigns_and_detail_json_nested_types(self):
        self._populate_for_validation()
        with self.repo.library._connection() as db:
            db.execute("UPDATE campaign_clock SET minutes=0.5 WHERE campaign_id=?", (self.other.id,))
        with self.assertRaisesRegex(ValueError, "Saved campaign minutes"):
            validate_saved_state(self.path)
        with self.repo.library._connection() as db:
            db.execute("UPDATE campaign_clock SET minutes=0 WHERE campaign_id=?", (self.other.id,))
            row = db.execute("SELECT change_id,payload_json FROM campaign_time_details LIMIT 1").fetchone()
            original = json.loads(row["payload_json"])
            original["events"] = [{"id": "bad", "at_minutes": True, "title": "Bad event", "notes": "", "source": "timeline"}]
            db.execute("UPDATE campaign_time_details SET payload_json=? WHERE change_id=?", (json.dumps(original), row["change_id"]))
        before = self._database_dump(self.path)
        with self.assertRaisesRegex(ValueError, "crossed event time"):
            validate_saved_state(self.path)
        self.assertEqual(self._database_dump(self.path), before)

    def test_recovery_validation_rejects_duplicate_calendar_keys_and_orphan_history_details(self):
        self.repo.get_clock(self.campaign.id)
        original = CalendarSpec().to_json()
        duplicate = original[:-1] + ',"hours_per_day":12}'
        with self.repo.library._connection() as db:
            db.execute("UPDATE campaign_time_settings SET calendar_json=? WHERE campaign_id=?", (duplicate, self.campaign.id))
        with self.assertRaisesRegex(ValueError, "duplicate fields"):
            validate_saved_state(self.path)
        import sqlite3
        from contextlib import closing
        with closing(sqlite3.connect(self.path)) as db:
            db.execute("UPDATE campaign_time_settings SET calendar_json=? WHERE campaign_id=?", (original, self.campaign.id))
            db.execute("INSERT INTO campaign_time_details(change_id,payload_json) VALUES('missing','{}')")
            db.commit()
        before = self._database_dump(self.path)
        with self.assertRaisesRegex(ValueError, "missing history"):
            validate_saved_state(self.path)
        self.assertEqual(self._database_dump(self.path), before)
