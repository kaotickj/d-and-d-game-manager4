# Development roadmap

This is a modernization of Kaotick Jay's Liberty BASIC 3.08 program,
initially targeting D&D 3.5. The original source identifies the program
as Copyright 2001–2025 Kaosium Interactive, designed and coded by Kaotick Jay.

## Priorities

1. Persistent characters, NPCs, and monster definitions. (Initial MVP)
2. Audit original Liberty BASIC handlers and mechanics, document behavior.
3. Expand record models for skills, feats, inventory, advancement, spells.
4. Monster templates, variants, stat blocks, and CR calculations.
5. Campaigns and encounters; preserve distinct encounter instances with
   independent temporary HP, conditions, initiative, and state.
6. Non-destructive import of legacy .crs and assorted INI records.
7. Dice, battle tracking, rules validation, help, backup/export, installers.

## Constraints

- Original .bas file remains unmodified. Do not rewrite old code in place.
- SQLite database is stored outside the Git checkout.
- Templates in the permanent library must never be altered by combat.
- Only D&D 3.5 initially. Avoid pretending incomplete fields are rules-checked.
- No cloud account required for local offline play.

## Implemented through v0.9.0

- Compendium persistent PC/NPC/monster templates, scene selection, Character/Monster Forges and The Scribe.
- Battle Trakker with independent encounter copies, initiative, surprise rounds, conditions, health, journaling and resumable autosaves.
- Encounter Command with SRD attack/save/check handling, caster-initiative effect clocks, action budgets and spell slots. Many advanced mechanics remain DM-adjudicated.

## Campaign tools delivered in v0.10.0

- Portable complete backups, isolated validated restore, and startup recovery.
- World/quest/faction/location journals, relationships, player handout assets,
  explicit public review and separate map/player windows.
- Calibrated map grids, rulers, encounter-linked tokens, annotations and fog.
- Campaign calendars, saved weather, event timeline and travel/rest previews.
- Audited wallets, inventory/containers, weight and reviewed XP application.
- Per-class higher-level spell plans and reviewed core/NPC multiclass histories.
- Rules reference search, attributed SRD imports and cited Scribe handoff.
- Explicit review of AI proposals, source-backed recap drafts and stale-edit
  protection across the new tools.

See [the play guide](PLAY_GUIDE.md) and [bounded scope](FULL_FEATURE_PLAN.md).
Further rules coverage includes prestige classes, racial HD/level adjustment,
more automatic feat/class-feature interactions and equipment effects. Complex
or unmodeled rulings remain explicit DM decisions.

## Current development additions

- Run Session dashboard shares the active party, live scene and combat
  controller, with explicit dice/combat actions and stale-safe quick notes in
  the existing session journal. See [Run Session](RUN_SESSION.md).
- Reviewed ordinary equipment calculates AC variants, attack/damage and saves
  from confirmed class levels, proficiency and bounded feat/class benefits.
  Encoded feats check complete prerequisite chains. Explicitly reviewed Bless,
  Mage Armor and Shield timers contribute to suggestions with stacking rules;
  named timers alone do not. See [equipment calculations](EQUIPMENT_CALCULATIONS.md).
- Campaign Recall retrieves relevant saved evidence with inspectable citations,
  field digests and source classifications. Public-field filtering happens
  before matching; stale selections cannot load. Saved private sources and
  private requests are blocked from player narration. See [campaign recall](CAMPAIGN_RECALL.md).

- Persistent campaign/session manager, party roster, session status/date, notes
  and reviewed recaps, and isolated saved encounters. Schema v3 adds tables
  without rewriting creature templates or modifying standalone saves.
- Explicit standalone-session import and active-workspace switching with save
  failure protection. Journal edits commit atomically. Campaign/session Scribe
  context includes prior completed recaps without treating plans as events.
- Guided level-up with explicit HP dice, skill/feat/ability/class choices,
  editable defaults for each template, and preserved advancement history.
- Scribe task modes for campaign planning, session preparation, scene narration,
  live DM advice, and evidence-based recaps. Current battle state can be loaded
  explicitly; editable drafts can be saved without changing game state.
- Random encounter drafts from saved templates or original generated baselines,
  including setting, scene prompts, motives, complications, stat review, optional
  initiative, and visible dice. Reviewed handoffs to scene, combat, and Scribe
  preserve permanent records.

Campaign direction: the DM can roll or request a prepared proposal, review it,
then use it during play. The assistant should gather missing build and campaign
choices, support player agency, keep DM secrets out of read-aloud narration,
and distinguish established events from suggested future events.

## Historical MVP limitations

This version provides manual entry, searching, editing, duplication, and
archiving, but not D&D 3.5 character calculations, campaign management,
import, dice rolls, or combat logic. Old .crs files must not be imported
until their exact format is characterized and tested.
