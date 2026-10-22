# Reviewed equipment and supported spell calculations

The equipment calculator provides a bounded D&D 3.5 calculation that the DM can inspect before using it. It keeps the saved manual character statistics, reviewed loadout, and encounter instances separate. It is not a complete rules adjudicator or an inventory ownership system.

## Review a character's loadout

Select a saved PC or class-based NPC in the Compendium and choose **Review Equipment & Modifiers…**, or use **Campaign Tools → Review Selected Character's Equipment…**.

1. Select ordinary armor, shield, weapon, and Small or Medium size.
2. Confirm the levels in each supported class. Their total must equal the saved character level, from 1 through 20. A valid saved class-level history can prefill the controls; the calculator never reconstructs multiclass history from a display name or previous computed statistics.
3. Confirm proficiency with the selected weapon, armor, and shield if appropriate. This starts unchecked for a new loadout. Without confirmation, attack and damage suggestions remain unavailable; the app does not invent a nonproficiency ruling.
4. Select the relevant owned Weapon Focus weapon or enable owned Weapon Finesse when applicable. Confirm any Monk or Paladin eligibility described below.
5. Choose **Review calculation**. Inspect the component breakdown, manual-versus-calculated AC, warnings, unsupported cases, and source URLs.
6. Choose **Save reviewed loadout** only after reviewing the calculation. Changing any choice invalidates the preview and requires another review. Cancel leaves the original record untouched.

The saved `combat_loadout` is versioned and records its review basis: character class, race, and level. A change to that basis requires another review; reopening a stale loadout resets the eligibility confirmations. Unknown loadout versions, unsupported profile fields, duplicate JSON keys, malformed sheets, and non-finite numbers are rejected instead of being rewritten. Other sheet metadata is preserved.

Saving a loadout does not replace the character's manual AC, update existing encounter combatants, spend coins, purchase items, or transfer equipment into or out of campaign inventory. Existing encounter AC remains under DM control.

## Current equipment and calculation scope

Supported armor is None, Padded, Leather, Studded leather, Chain shirt, Breastplate, and Full plate. Shields are None, light wooden, heavy wooden, and heavy steel. Weapons are Dagger, Sword, short, Longsword, Rapier, Greatsword, Greataxe, Longbow, and Crossbow, light. Only ordinary Small and Medium equipment is covered. The catalog uses the [3.5 SRD armor](https://www.d20srd.org/srd/equipment/armor.htm) and [weapon](https://www.d20srd.org/srd/equipment/weapons.htm) tables.

The preview includes normal, ordinary touch, and flat-footed AC; one normal attack bonus; a damage expression; critical threat and multiplier; Fortitude, Reflex, and Will modifiers; initiative; armor check penalty; and the armor's maximum Dexterity limit. It uses ability modifiers and the confirmed class tables. Multiclass base attack and base saves are added from each class separately. Flat-footed AC removes a positive Dexterity contribution while retaining a negative one. See [combat statistics](https://www.d20srd.org/srd/combat/combatStatistics.htm) and [multiclass characters](https://www.d20srd.org/srd/classes/multiclass.htm).

The calculator supports the eleven core classes and the SRD NPC classes Adept, Aristocrat, Commoner, Expert, and Warrior. Confirmed levels supply table progression; merely naming a class or entering prose does not grant additional mechanics.

## Supported feats and passive class benefits

Only these saved feat benefits are included in the equipment calculation:

| Saved feat | Supported contribution |
| --- | --- |
| Weapon Focus | +1 attack for the explicitly selected matching weapon. A qualified saved feat must match that weapon. |
| Weapon Finesse | Uses Dexterity for a supported finesse weapon's attack when selected; applies the equipped shield's armor check penalty to that attack. |
| Improved Initiative | +4 initiative once. |
| Great Fortitude | +2 Fortitude. |
| Lightning Reflexes | +2 Reflex. |
| Iron Will | +2 Will. |

Weapon Focus and Weapon Finesse require calculated base attack bonus of at least +1. Selecting these controls does not award a feat; the character must already have the corresponding saved feat. This calculator does not implement every feat interaction or replace the existing guided advancement review. Rules: [SRD feats](https://www.d20srd.org/srd/feats.htm).

**Monk AC:** confirm that the Monk is unencumbered, able to move, and not helpless. The calculator separately requires no equipped armor or shield and confirmed Monk levels. It includes the supported Wisdom AC bonus and level-based Monk AC bonus in normal, touch, and flat-footed AC. The checkbox is a DM confirmation, not an automatic condition or load check. Rules: [Monk](https://www.d20srd.org/srd/classes/monk.htm).

**Divine Grace:** confirm active eligibility and at least two Paladin levels before adding the supported Charisma bonus to the three saves. The app does not determine whether a Paladin has lost class features. Rules: [Paladin](https://www.d20srd.org/srd/classes/paladin.htm).

## Use reviewed suggestions in the Combat Desk

The attacker or target must link to a saved character with a current reviewed loadout. Open the Combat Desk's attack/save controls:

- **Review Character Attack Suggestion…** shows the calculation before copying supported attack bonus, damage, threat, and multiplier into the roll controls. Review range, actions, conditions, and other situational modifiers separately.
- **Review Target Defense…** lets the DM review normal, touch, or flat-footed AC. **Use reviewed AC for this roll** applies a roll-specific override; the encounter combatant's stored AC stays unchanged.
- **Review Character Save Suggestion…** supports Fortitude, Reflex, and Will. Concentration and skill/ability checks remain manual. Mark the fear checkbox only when the saving throw is actually against fear.

The app rechecks reviewed suggestions against the current character and supported effects before resolving a roll. A stale suggestion requires another review or deliberate manual entry. Reviewing a suggestion alone does not roll dice or apply damage. Applying damage remains governed by the existing explicit attack control.

## Three explicitly reviewed spell effects

In **Round & Effect Clocks**, select a target, initiative anchor, and duration. Choose Bless, Mage Armor, or Shield in the supported-spell selector, then **Review Supported Spell Effect…** and confirm the details. This creates a timer with explicit versioned mechanics metadata. Its contribution is included only while that timer is active and targets the specific combatant.

| Spell | Contribution to reviewed suggestions | Limits |
| --- | --- | --- |
| [Bless](https://www.d20srd.org/srd/spells/bless.htm) | +1 morale to attack and +1 to saves against fear. | The save bonus requires the fear checkbox; ordinary saves do not receive it. Ally/area selection and interactions with bane remain DM decisions. |
| [Mage Armor](https://www.d20srd.org/srd/spells/mageArmor.htm) | A +4 armor bonus, using the larger of it and the equipped armor bonus. | Ordinary touch AC is unchanged; incorporeal/force exceptions require manual adjudication. |
| [Shield](https://www.d20srd.org/srd/spells/shield.htm) | A +4 shield bonus, using the larger of it and the equipped shield bonus. | Ordinary touch AC is unchanged; magic missile negation and incorporeal/force exceptions require manual adjudication. |

Duplicate instances of the same supported spell do not add their bonuses together. Supported armor and shield bonuses compete with an equipped bonus of the same type rather than stacking. This is a bounded application of the [SRD stacking rules](https://www.d20srd.org/srd/theBasics.htm#stacking), not a general engine for every bonus source.

The DM supplies duration and anchor; the app does not infer caster level or valid targets. Spell slots, casting actions, and other resources are spent separately through their existing explicit commands. A plain timer named “Bless,” “Mage Armor,” or “Shield” remains descriptive unless it was created with reviewed mechanics. Existing timer dismissal, expiry, and undo behavior still governs the effect; source character sheets and stored encounter AC are not rewritten.

## Cases requiring manual adjudication

This increment does not calculate magic or masterwork equipment, special materials, natural armor, racial traits, racial Hit Dice, prestige classes, epic progression, ammunition, thrown weapon modes, movement or skill penalties, arcane spell failure, encumbrance penalties, or all conditions. Size outside Small and Medium is unsupported.

Full attacks, two-weapon fighting, flurry, rage, smite, sneak attack, uncanny dodge, and other unlisted class features remain manual. Flat-footed suggestions therefore require particular care for creatures retaining Dexterity through another feature. Dodge target selection, Power Attack, Cleave, Point Blank Shot, and other situational feat benefits are not included. Other spells and interactions with unrepresented effects remain manual. Inspect the displayed warnings and sources before copying a suggestion into a roll.
