# Reviewed multiclass history and advancement

**Multiclass History & Advancement** works with saved PCs and class-based NPCs
through total character level 20. It supports the eleven core classes and the
five SRD NPC classes. Prestige classes, racial Hit Dice, level adjustment and
epic progression are outside this class-only workflow.

## Confirm existing history

Enter the character's existing per-class totals. Their sum must equal the saved
total level. An optional chronological list records one class per character
level; leave it blank when the old order is unknown. The program does not
invent missing acquisition order, HP rolls or past choices.

Confirm explicitly that the total includes class levels only, without racial
Hit Dice or level adjustment. Known nonzero racial-HD/LA fields and a different
effective character level are rejected. Record the DM's history/restriction
review, preview the result, then approve the exact before/after display to save.
This confirmation updates the class label and derived base BAB/saves; it keeps
existing HP, ranks, feats, spellbooks and unrelated sheet data.

Expert requires ten explicitly chosen class skills. Existing additional class
skills are retained for their originating class. Bard and Wizard include all
supported ordinary Knowledge specializations. Saved Expert selections cannot
silently change during later advancement.

## Add one class level

Choose the class being advanced, roll or enter its Hit Die, assign all new skill
points, select required general/class-bonus feats, and record class features,
spell choices and DM review notes. A new class grants an ordinary additional
level's skill budget and rolled HP; it does not grant the initial character's
quadrupled skills or automatically maximize HP.

- BAB and base saves are calculated independently for each class, rounded at
  that class's level, then summed. Fractional-BAB/save house rules are not used.
- HP gain is the chosen class die plus current CON modifier, minimum one. A
  level-based CON modifier increase also adjusts HP for prior character levels.
- Ability increases use total levels divisible by four; general feats use total
  levels divisible by three. Class-bonus feat schedules use the chosen class's
  own level. Automatic class feats do not consume discretionary choices.
- A skill point buys one rank for the current class's class skills, or half a
  rank otherwise. The rank cap uses the union of all the character's classes:
  total level + 3 for a skill in any class, half that otherwise. An old half-rank
  remains valid when training that skill as a current-class skill.
- Intelligence increases affect this level's budget and future levels, without
  retroactively granting old skill points. The Human extra point is retained.
- Encoded feat prerequisites use the combined BAB and updated ability scores.
  Monk bonus feat choices retain their class-specific prerequisite exception.
  Weapon Focus requires an explicit weapon and DM-reviewed proficiency.

Supported feat selections use the existing bounded feat catalog. Unmodeled
feat choices and their mechanical effects are not accepted as automatically
validated. Class feature labels, special interactions, equipment effects,
alignment restrictions, monk/paladin class re-entry restrictions, favored-class
XP penalties, prestige prerequisites and XP/milestone eligibility require the
explicit DM review recorded for each level.

The desk displays `experience_points` when recorded. It does not infer legacy
`xp` fields, change XP, apply XP penalties or grant a level merely because an
XP threshold is reached. The resource ledger's reviewed XP application and
advancement are distinct actions.

Each casting class keeps its own structured `class_levels` entry. The separate
Spell Progression desk can use those class levels for slots and plans. Existing
spellbooks and spell plans are preserved by advancement; spell-review notes
record choices requiring follow-up in that desk.

## Review, save and integration

History and level changes first produce immutable candidates. The Review & Save
tab shows class history, total level, maximum HP, base BAB/saves, ability changes,
new feats and all review notes. A separate acknowledgment approves that exact
preview. Editing any input invalidates it. No operation changes live encounter
HP, conditions, combat state, campaign membership or inventory.

Save reconstructs the candidate from its recorded operation, compares the
entire original character under a SQLite write lock, and writes atomically.
Concurrent character edits require reopening the desk. Failed SQL leaves the
old record intact. Existing advancement entries and unrelated sheet metadata
are preserved; new records append auditable class-level choices and HP rolls.

Integration entry: `MulticlassDialog(library_repository, creature_id, parent=None)`
in `multiclass_ui.py`. It exposes `record_saved(object)` and `result_creature`.
Domain helpers are `establish_history`, `multiclass_requirements`,
`advance_multiclass`, and `save_multiclass_candidate`. There is no schema change.

## Rule sources

The numeric rules were checked against the D&D 3.5 open SRD:

- [Multiclass character rules](https://www.d20srd.org/srd/classes/multiclass.htm)
- [Skill costs and multiclass rank caps](https://www.d20srd.org/srd/skills/skillsSummary.htm)
- [Ability modifiers, Constitution HP and Intelligence changes](https://www.d20srd.org/srd/theBasics.htm)
- [Fighter class table and bonus feats](https://www.d20srd.org/srd/classes/fighter.htm)
- [Monk class table, bonus feats and re-entry restrictions](https://www.d20srd.org/srd/classes/monk.htm)
- [Ranger class features](https://www.d20srd.org/srd/classes/ranger.htm)
- [Sorcerer and Wizard class rules](https://www.d20srd.org/srd/classes/sorcererWizard.htm)
- [Aristocrat class table and class skills](https://www.d20srd.org/srd/npcClasses/aristocrat.htm)

These sources support the listed calculations. They do not imply exhaustive
automation of every class feature or rule interaction.
