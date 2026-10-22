# Campaign time, travel and rest

Open **Campaign Time & Travel** for a saved campaign. The fictional calendar is
independent of the real-world dates stored in session journals. Opening this
desk does not switch the active campaign/session/encounter workspace.

## Clock and reviewed changes

The campaign starts at elapsed minute 0, campaign day 0, on day 1 of its first
month. A calendar supports 1–48 uniquely named months with independently chosen
lengths of 1–1,000 days, 1–48 hours per day, and a starting year. Each hour has
60 minutes. There are no leap years or intercalary days in this first calendar
implementation.

Use **Preview Time Change**, **Preview Travel**, or **Preview Rest** to inspect
the before/after dates, crossed events and consequences. Only **Apply Reviewed
Time Change** changes the saved clock. Editing an input invalidates its review.
An event at the starting time is not crossed again; events strictly after the
start and at or before the new time are included. Cancelled, completed and
archived World Desk events are excluded. The timeline never marks events
completed automatically.

A review becomes stale when another window changes the clock/calendar or a
crossed event is added, cancelled or edited. Apply then asks for a fresh review.
Changes are transactional and request IDs prevent a repeated apply from
advancing time twice. Failed saves preserve the old clock and history.

## Travel and rest

Travel takes the DM's effective distance and miles/hour after terrain, roads,
weather, load, breaks and travel limits have been considered. Elapsed minutes
are distance / speed × 60, rounded up to a whole minute. The preview includes a
traveler-day supply estimate using the campaign's day length. This is a planning
estimate; no food, water or money is consumed. An optional original d20 travel
prompt is retained with the committed journal entry. The DM interprets its
meaning; it is not an automatic encounter-probability rule.

Rest uses an explicitly chosen duration, rounded up to a whole minute. The
preview reminds the DM to review eligibility, interruptions, healing and spell
recovery. Applying rest advances the campaign clock only. It does not heal
characters, refresh spells, remove conditions or advance a combat encounter.

These helpers perform reviewed calendar arithmetic. They do not claim to
implement SRD overland movement, forced marches, survival, climate tables or
class-specific rest mechanics.

## Timeline, weather and custom calendars

The Timeline tab lists this campaign's own timed entries and active World Desk
events. Add an event at a numbered campaign day/hour/minute; cancel a timeline
entry to retain its record while excluding it from future reviews. Manage World
Desk event statuses in the World Desk. Event notes are part of the DM desk and
are not a player-facing export.

Weather uses an original d20 prompt table: clear, cloudy, precipitation, strong
wind, or severe weather. **Roll Weather Preview** does not persist a roll;
**Save Reviewed Weather** stores its outcome for the selected campaign day.
Reopening shows the same saved outcome. Concurrent changes to the same day's
weather or to the clock require another review before replacement.

Review a calendar definition before saving it. Elapsed minutes and timeline
minute offsets stay fixed when the definition changes. Changing hours per day
reinterprets World Desk entries that use numbered campaign days. A World Desk
event whose hour lies outside a shorter custom day is reported so the DM can
correct it; it is never silently moved. Unsaved calendar edits survive clock
refreshes and require save/discard/cancel on closing.

## Persistence and integration

`CampaignTimeDialog(database_path, campaign_id, parent=None)` is the GUI entry
point. `CampaignTimeRepository` reuses the main library's `campaign_clock` and
`time_changes` tables. Additional custom calendar/revision, detailed history,
timeline and weather tables are created by the idempotent
`campaign_time.initialize_schema(db)` hook. The repository calls it on opening,
and the main storage migration can call the same hook. It does not alter
`PRAGMA user_version` itself. All data lives in the library SQLite file and is
included in normal library and portable backups.

Recovery can call `campaign_time.validate_saved_state(database_path)` on its
staged SQLite copy. This hook opens a read-only transaction, validates every
campaign's clocks, calendars, history, detailed JSON, timeline and weather
(including archived campaigns), and returns row counts. It does not create
missing optional tables/settings or normalize invalid data. Repairable World
Desk scheduling choices are kept separate from malformed time storage.

Focused tests cover custom-calendar round trips, events from both desks,
campaign isolation, failed SQL rollback, stale reviews, repeated apply, saved
dice, unchanged character/resource state, corrupted event preservation, and the
explicit GUI review/save workflow. Windows runtime checks remain part of the
application's release acceptance.
