# Campaign manager completion plan

The current app is an offline D&D 3.5 campaign tool. Completion is measured by
the acceptance checks below, not by the presence of a menu or an AI-generated
paragraph. AI assistance does not mean that a model has been trained on the SRD.
Searchable, attributed rule documents and reviewed mechanical implementations
remain distinct work.

## Delivered foundation

- Persistent creature library, guided single-class advancement, dice, naming,
  character/monster creation, local Scribe, scenes, and encounter generation.
- Campaigns, party references, session journals/recaps, independent named
  encounters, restartable workspace selection, and SQLite snapshots.
- The World & Campaign Desk adds typed quests/objectives/assigned characters,
  locations, factions/contacts, player handouts, numbered campaign-day events,
  travel routes, inventory/treasure entries, reward journals, and lore notes.
  Records support search, type/status filters, archive/restore, and directed
  relationships inside one campaign. Creature and route-location references
  are selected from saved records, rather than requiring pasted JSON.
- Public summaries and private DM notes are distinct fields. Player handout
  preview and text export include **only** the explicitly authored Player text;
  titles, summaries, DM notes, relationships, and other metadata are excluded.
- Loading a saved world entry into Scribe is explicit, bounded, and read-only.
  Referenced records are identified as not loaded. Oversized context is rejected
  without silently shortening or editing the saved entry.

World journal entries record plans and references. Actual item transfers,
wallet balances, weight/encumbrance and reviewed XP application live in the
Treasure & XP Ledger. Campaign Time previews travel/rest, clock changes, events
and saved weather; rest does not silently heal characters or refresh spells.
The separate map desk manages grid calibration, rulers, encounter-linked tokens,
annotations, fog and filtered player output. The Handout Gallery manages image
attachments and reviewed public packages. See [the play guide](PLAY_GUIDE.md).

## Delivered campaign tools and acceptance scope

| Milestone | Implementation | Acceptance |
| --- | --- | --- |
| Rules reference | Import the approved 3.5 open rule corpus with source/license metadata; offline full-text search; excerpts and citations; optional Scribe retrieval | Queries find inspectable source passages; unsupported rules are identified; no claim of model training; bundled citations and license are retained |
| Recovery | Portable backup/restore of the SQLite library, standalone files, and future managed assets | Restore to a new folder preserves campaigns, scenes, combat, creatures, rules and assets; corrupt/newer backups leave the running library intact |
| Campaign time | Fictional calendar definition, clock, event timeline, weather, travel/rest previews, persisted dice outcomes | Advancing time previews affected events/resources; real-world session dates remain separate; custom calendars round-trip; no silent character/encounter changes |
| Resources | Item instances/containers, copper-based wallets, shared stores, audited transfer/reward commands, weight/encumbrance rules | Atomic balanced transfers; no double awards on repeated submission; source session/encounter recorded; XP changes enter guided advancement only when explicitly applied |
| Player presentation | Player display, reviewed public projections, handout assets and export | Player output excludes secrets by construction; private fields never enter exported payloads; preview matches exported content |
| Maps and table aids | Managed maps, grid calibration, tokens tied to encounter instances, measurements, annotations, persisted reveal state | Reload preserves map/token/reveal state; creature templates remain unchanged; unrevealed areas and DM overlays do not reach player output |
| Rules depth | Multiclass history, higher-level spells, feats/class choices, equipment, conditions, and resolved combat edge cases | Each supported rule has a cited implementation and focused tests; custom/unsupported cases remain explicit GM decisions |
| Reviewed AI changes | Selected factual context, source-backed rules advice, reviewable world/session draft changes, encounter scene proposals | Proposals remain separate from established history; no automatic dice/awards/saves; DM reviews field changes before commit; completed session recaps cite recorded outcomes |
| Windows acceptance | Build, install, upgrade, restart, backup/restore, compact-window and player-display checks on Windows | CI runs tests and packaged startup/recovery checks on Windows; install/reinstall and old-schema migration are checked separately; interactive prior-installer upgrade and second-monitor acceptance remain manual checks |

## Architecture and ownership

`storage.py` owns additive schema migrations and schema versioning. All campaign
world records and relationships are part of the same SQLite database, so normal
SQLite snapshots include them. `world.py` owns typed validation and transactions;
`world_ui.py` owns explicit journal editing and player handout output. The main
window owns workspace activation and Scribe handoff. Rules ingestion/search,
campaign resource commands, time calculation, maps, and recovery should have
separate domain modules and focused GUI adapters.

Only one integrator should edit shared migrations and main-window integration
at a time. Other agents can independently work on domain modules, interfaces
against agreed contracts, licensed rules ingestion, visual assets, or validation.
Each milestone ends with passing focused tests, affected regression checks,
documented limits, and a reviewable diff before a Windows release.

## State boundaries that every milestone must preserve

- Permanent creature templates, campaign membership, explicit scene presence,
  and combat instances are different state. Updating one must not imply another.
- References and relationships must stay inside the selected campaign, except
  explicit references to the shared creature library. Saved entries cannot move
  to another campaign or change their type accidentally.
- Failed reads, invalid drafts, failed migrations, and SQL failures must not
  overwrite saved data or erase unsaved edits. Corrupt data remains available
  for recovery instead of being replaced by a blank fallback.
- AI suggestions, session plans, recorded events, and confirmed recaps remain
  distinct. Status or party membership is not evidence that an event occurred.
- Player output uses an allowlist of public fields. Prompt instructions alone
  are not a privacy boundary.
- No online service or model download is required to use saved campaign tools.
