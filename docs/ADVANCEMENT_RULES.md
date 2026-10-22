# Guided D&D 3.5 advancement

Advance one class level at a time, through character level 20. The default build
for each class specifies an ability priority, preferred class skills, and feat
preferences. Defaults are editable. They propose choices; they do not save a
character, roll hit points, or acknowledge a rules review on the user's behalf.

## Numeric rules

- Roll one class Hit Die and add the current Constitution modifier, with a
  minimum gain of one hit point. A Constitution modifier increase also adjusts
  hit points for prior levels. Intelligence changes affect this level's skill
  points and future levels, without awarding points for past levels.
- Gain one ability point every fourth character level and one general feat
  every third character level. First-level racial and class bonus feats remain
  on the saved sheet.
- Skills use the existing half-rank storage: two ticks are one whole rank. Each
  class-skill point buys two ticks; a cross-class point buys one tick. At target
  level L, the caps are 2(L+3) class ticks or L+3 cross-class ticks. Allocate the
  complete new budget; no unspent points are carried forward.
- Base attack and saving throw progressions come from the SRD tables for the
  eleven core classes and five NPC classes. A full BAB is L; three-quarter BAB
  is floor(3L/4); half BAB is floor(L/2). Good base saves are 2+floor(L/2), and
  poor base saves are floor(L/3).

Sources: [abilities](https://www.d20srd.org/srd/theBasics.htm#theAbilities),
[class and cross-class ranks](https://www.d20srd.org/srd/classes/multiclass.htm),
[fighter](https://www.d20srd.org/srd/classes/fighter.htm),
[monk](https://www.d20srd.org/srd/classes/monk.htm),
[ranger](https://www.d20srd.org/srd/classes/ranger.htm),
[rogue](https://www.d20srd.org/srd/classes/rogue.htm),
[feats](https://www.d20srd.org/srd/feats.htm),
[sorcerer and wizard](https://www.d20srd.org/srd/classes/sorcererWizard.htm),
[adept](https://www.d20srd.org/srd/npcClasses/adept.htm).
These links describe D&D 3.5 SRD rules, not fifth-edition or Pathfinder rules.

## Choices and manual review

The engine counts general, fighter, monk, and wizard bonus feat slots and checks
its encoded prerequisite rules. Monk bonus choices use their class-specific
prerequisite exception. Known choices include ranger combat style and favored
enemy, and selected rogue special abilities. Feature labels are recorded; their
entire combat implementation is not implied by a label.

Every class can additionally record feature choices and DM adjustments in the
class notes field. These entries are appended to class features with their level
and preserved in the advancement history; they do not claim rules validation.

Class-granted feats are separate from selectable slots. Ranger Track at first
level and Endurance at third level do not consume a general feat choice.
Supported prerequisites include Dodge's Dexterity 13 requirement, using the
ability scores after any increase selected for that level.

Use [spell management](SPELL_PROGRESSION.md) for class-specific higher-level
spellbook, known, prepared and domain selections. The level-up form also accepts
reviewed spell notes and preserves existing structured spell data. Unsupported
feats are not silently accepted as validated choices.

Weapon Focus additionally gathers a chosen weapon and requires confirmation of
proficiency in the review. Core/NPC defaults suggest a weapon; manual profiles
must supply that choice. It is saved as a qualified feat, for example
`Weapon Focus (longsword)`, with the parameter also in level history. Repeated
instances for different weapons require a later feat-instance workflow.

Supplemental and homebrew classes use a GM-confirmed progression profile. The
form gathers hit die, skill rate, BAB progression, good saves, and class skills.
Existing template values provide starting points. The confirmed profile is
saved for the next advancement; features, extra bonus feats, and spell/power
progression remain explicit reviewed entries.

## Data preservation and limits

The engine returns a new immutable creature without database writes. It preserves
the record ID, notes, biography, inventory, archived state, and unrelated sheet
metadata, then appends an auditable history of HP rolls and selections. Permanent
maximum HP changes; live encounter HP and conditions are independent snapshots.
Armor Class is preserved because an armor's Dexterity cap and GM adjustments
cannot be inferred reliably from the current fields. Review AC when Dexterity
changes. Base saves are stored separately from ability and situational bonuses.

Use [Multiclass Advancement](MULTICLASS.md) to confirm class history and advance
core/SRD NPC class combinations. Once class history is established, Level Up
opens that workflow. Racial Hit Dice, level adjustment, prestige-class
qualification, automatic XP eligibility and advancement beyond level 20 remain
DM decisions outside these class-only tools. Inconsistent saved class or level
history is rejected with a review message.
