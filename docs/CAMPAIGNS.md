# Campaign and session workflow

Open **Campaigns & Sessions…** from the Compendium. Create a campaign, enter its
premise and DM notes, and choose members on the Party tab. Party membership links
to the permanent library; it never copies or changes a creature's statistics.
Archived members remain listed so they can be restored or explicitly removed.

Create a session, then record its title, optional `YYYY-MM-DD` date, status,
preparation/event notes, and reviewed recap. Save the journal before opening a
different workspace. Campaign edits, party changes, and session edits commit as
one transaction; validation or database failures preserve the previous journal
and leave the editor's changes available to correct or retry.

Create a named encounter when combat is needed. Select a session and encounter
and choose **Open Selected Session / Encounter**. If a session has no encounters,
opening Battle Trakker creates its first encounter. Each encounter stores its
own combat instances, including current HP, initiative, conditions, effects,
action state, spell slots, and history. Changing those instances never changes
permanent creature templates. The active workspace is remembered on restart.

Each session has a separate scene. Use **Add Campaign Party to Scene** when the
party is actually present, or edit the scene roster directly. Party membership
does not imply presence. The usual library selection and Battle Trakker tools
still decide which combatants to add. The random encounter generator saves its
reviewed scene to the active session or adds creatures to the active encounter.

Switching sessions or encounters saves the current scene and battle title/state
before opening the destination. A failed save keeps the current workspace open.
Unreadable destination state is reported and left intact.

## Planning and recaps with the Scribe

The manager offers **Plan Campaign in Scribe**, **Plan Session in Scribe**, and
**Recap in Scribe**. Campaign planning can begin before any session exists.
Session context contains the campaign notes, selected session journal/scene,
party and present records, and earlier completed session recaps. It distinguishes
party membership from scene presence and proposed situations from recorded
outcomes. Recaps use the DM's event evidence rather than assuming plans occurred.

Opening context does not run inference or rewrite a journal. Choose Generate
Locally, review and edit the draft, then copy useful material into the campaign
or session journal and save it. Current battle advice loads only the active
encounter. Archived/missing roster records and context beyond the current
6,000-character limit produce explicit messages; no history or stat blocks are
silently removed. For a narrower request, enter selected facts directly in the
Scribe's editable context. The app requires an existing local model/runtime.

## Existing standalone saves and backups

Standalone play still uses `current_scene.json` and `battle_trakker.json` next to
the library database. Choose **Standalone Workspace** to return to those saves.
**Import Standalone Scene/Battle** creates a new session and encounter in the
selected campaign, copying both saves in one transaction. It leaves the original
files untouched. Switching into a campaign does not import or overwrite them.

Schema v3 stores campaign data inside `library.sqlite3`, alongside the permanent
library. **Library → Back Up Library…** therefore includes all campaigns, party
links, journals, session scenes, named encounter state, and workspace selection.
Creature JSON export/import does not transfer campaign data. The standalone JSON
files remain outside a SQLite backup; copy them separately or explicitly import
them into a campaign before taking a database snapshot. Guided restore and a
complete standalone backup bundle remain future work.
