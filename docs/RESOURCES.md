# Campaign resources and rewards

Open **Resources & Rewards** for the selected campaign. Create a shared store
(party treasury, wagon, safe house) or a personal wallet linked to a saved
creature. Each wallet starts empty; creatures can have one wallet per campaign.
Select the source session/encounter and enter a reason before recording a
reward, expense, transfer, newly found item, or item use. Review the displayed
command before confirming it. The audit history retains its request ID, reason,
source, inputs, and result.

Money uses integer copper pieces: 10 cp = 1 sp and 100 cp = 1 gp. Reward/deposit
adds money, expense removes it, and a transfer debits and credits two wallets in
one transaction. Negative balances are refused. Replaying a command with the
same request ID returns its original result without granting it again. A changed
command cannot reuse the same ID. Concurrent identical submissions serialize
under a SQLite write lock. A failed recipient, capacity check or SQL write rolls
back the entire command, including its audit entry.

Inventory entries are actual item instances with quantities, value, precise
weight, ownership, optional container, and notes. A partial transfer creates a
new recipient stack and reduces the original stack by the same quantity; a full
transfer retains the instance ID. Use/removal reduces quantity and keeps a
depleted instance available to the audit trail. Containers add empty weight and
can enforce a maximum contents weight. Zero capacity means no specified limit.
Containers are flat; nesting and moving a filled container as one operation are
not implemented. Move its item instances explicitly.

The carrying panel uses the D&D 3.5 SRD strength thresholds, biped/quadruped size
multipliers, and tremendous-strength rule. It reports load, maximum Dexterity
bonus, check penalty, and movement for a normal 30-foot base speed. The domain
also reports the 20-foot movement rate. Armor/load penalties use the worse value
and are not added together; apply armor and exceptional carrying abilities with
DM review. These are advisory values and never rewrite a character or encounter.
Record all carried/worn gear here to count it. A wallet stores monetary value,
not coin denominations, so enter actual coin weight as an inventory instance.
Do not duplicate it in another item. [Rules source: D&D 3.5 SRD, Carrying Capacity](https://www.d20srd.org/srd/carryingCapacity.htm).

XP is awarded to a personal PC/NPC wallet as **pending XP**. It does not edit the
character until **Review & Apply Pending XP** is confirmed. The preview shows
the current, pending, and resulting XP. Application writes the shared character
sheet's `experience_points` field, preserves other fields and statistics, and
marks the exact reward ledger entries as applied. Other campaigns that reference
that creature see its shared sheet. A stale preview is refused. Repeated
application cannot count an award twice. A legacy ambiguous `xp` field must be
reviewed before application. XP application never automatically increases levels;
use guided advancement to review the actual level-up choices.

The campaign resource inventory is independent of the permanent character's
equipment list and the World Desk's item/reward journal entries. Saving a world
journal does not spend or grant resources. Adding an inventory item does not
automatically pay its listed value. Record a payment as an explicit expense.
Inventory and payment are separate reviewed commands; shops and atomic purchase
orders are outside this milestone. Reward amounts and division remain DM choices.

## Integration and storage

`ResourceRepository(path)` reuses the central `resource_operations` and
`resource_ledger` tables. `resources.ensure_schema(db)` executes the exported
`SCHEMA_SQL` statements to add wallets, containers, item instances, and reward
application links in the caller's transaction. The repository invokes this hook
with `IF NOT EXISTS` and never changes the central schema-version pragma. The
central migration can call the same hook. All data lives in `library.sqlite3`
and is included in SQLite snapshots and portable campaign backups.

Open `ResourcesDialog(database_path, campaign_id, parent=None)`. Connect
`character_changed(str)` to refresh the library preview after XP application;
`resources_changed()` reports committed ledger/inventory commands. Opening or
refreshing the desk does not create wallets or change the active workspace.

`resources.validate_saved_state(library_repository_or_path)` uses a read-only
SQLite connection to verify wallet/item/container ownership, exact numeric
values, command metadata, ledger agreement, balances, source references and
applied XP links before staged recovery is published. It does not inspect or
normalize legacy character XP fields and never applies a reward during recovery.
