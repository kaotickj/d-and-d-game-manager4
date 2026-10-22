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
- Character advancement: multi-level builds, prerequisites, and explicit
  separation of automated rules from GM overrides.
- Release readiness: keep storage and Qt suites passing in CI, test packaged
  Windows builds, and document backup/restore for all local state.

## Historical MVP limitations

This version provides manual entry, searching, editing, duplication, and
archiving, but not D&D 3.5 character calculations, campaign management,
import, dice rolls, or combat logic. Old .crs files must not be imported
until their exact format is characterized and tested.
