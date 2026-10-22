# Grimoire: higher-level spell management

The Grimoire calculates daily slots for Wizard, Sorcerer, Cleric, Druid, Bard,
Paladin, Ranger and Adept class levels 1–20. It uses the numeric D&D 3.5 SRD
class tables, casting-ability requirements and bonus spells. A dash differs
from zero base slots: zero permits bonus slots once that spell level is gained.
Cleric domain slots are shown and prepared separately. Bonus spells do not add
cantrips or spells known. Bard and Sorcerer known limits use their own tables.
Learning a new spell requires the class's minimum casting ability. Previously
learned spells remain recorded after an ability loss; unavailable daily slots
still prevent preparation. Malformed saved groups are rejected before editing,
without dropping unsupported levels or turning text into a list of letters.

Select a saved character and casting class, then a spell level. Edit known
spells, daily preparation, the Wizard spellbook or Cleric domain preparation.
Prepared spells may repeat; each repetition uses another slot. A lower-level
spell may occupy a higher regular slot. Wizards must have the spell recorded in
their book. Partial selections are allowed, so the DM can complete them later.

The local SRD spell index supplies higher-level names after its explicit import
in Encounter Command. Core first-level names are available offline immediately.
Unindexed and custom names require a DM source-review note and remain marked as
custom entries. Domain eligibility also requires that review. School restrictions,
specialist bonus slots, metamagic, divine alignment restrictions, acquisition
costs, replacement timing and supplemental spellcasting remain DM decisions.

Review the choices and click **Save Reviewed Spell Plan** to commit. Saving
updates only `sheet.spell_progression[casting_class]`; the original first-level
spellbook, biography, inventory, statistics and encounter casting state are
preserved. Plans include their source, calculated profile, review note and
revision. A changed character is rejected under the same database transaction
used for saving; unsaved text remains available. No model or network operation
runs when opening or saving this desk.

Structured `class_levels` histories use each class's level independently. This
does not create or advance multiclass histories. Ambiguous or inconsistent
histories require review before spell management.

Sources: [Wizard/Sorcerer](https://www.d20srd.org/srd/classes/sorcererWizard.htm),
[Cleric](https://www.d20srd.org/srd/classes/cleric.htm),
[Druid](https://www.d20srd.org/srd/classes/druid.htm),
[Bard](https://www.d20srd.org/srd/classes/bard.htm),
[Paladin](https://www.d20srd.org/srd/classes/paladin.htm),
[Ranger](https://www.d20srd.org/srd/classes/ranger.htm),
[Adept](https://www.d20srd.org/srd/npcClasses/adept.htm), and
[ability bonus spells](https://www.d20srd.org/srd/theBasics.htm#abilitiesAndSpellcasters).

Integration: `SpellProgressionDialog(library_repository, creature_id, parent=None)`.
Refresh the main creature list after the dialog closes. No new schema is needed.
