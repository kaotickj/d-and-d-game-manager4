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

## Next development milestones

- Library protection: SQLite snapshots, complete JSON exports, and validated,
  transactional JSON import with a preview and skip/copy/replace policies are
  implemented. Extend backup/restore to scene and encounter state next.
- Campaign management: persistent campaigns, sessions, party membership, and
  encounters linked to campaigns.
- Character advancement: guided single-class levels, editable default builds,
  numeric core/NPC progression, and reviewed supplemental-class profiles are
  implemented. Next add structured higher-level spell selection, wider feat and
  class-feature rules, reusable custom build plans, and multiclass histories.
- Release readiness: keep storage and Qt suites passing in CI, test packaged
  Windows builds, and document backup/restore for all local state.

## Current development additions

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
