# Dungeons & Dragons Game Manager 4

Modern Python and PyQt6 continuation of **Dungeons & Dragons Game Manager
3.08**, originally designed and coded by **Kaotick Jay** in Liberty BASIC
(likely 4.03). Original source header credits Copyright 2001–2025
**Kaosium Interactive**.

## Status: v0.9.0, D&D 3.5 Encounter Command

The **Compendium** provides a searchable, persistent SQLite library for player characters, NPCs and monster templates. **Battle Trakker** adds an independent live-combat encounter manager (Ctrl+B), and **Encounter Command** adds SRD 3.5 attacks, checks, saves, condition clocks, action budgets, and spell-slot tracking. Combat never mutates permanent creature templates.

This remains **a partial D&D 3.5 rules engine**, not a full implementation. See
[the roadmap](docs/ROADMAP.md) for the next milestones.

## Development: level up and prepare a session

Select an active PC or NPC and click **Level Up…**. Choose a guided build or
**Apply Class Defaults**, roll the class Hit Die with the built-in roller (or
enter a tabletop result), and pick skills, feats, class options, and an ability
increase when due. Review the resulting level, HP, BAB, and base saves before
**Save Level Up**. Defaults fill editable choices and never roll or save on their
own. Each level stores its dice and choices in the character's level history.

The eleven core classes and five NPC classes have numeric progressions through
level 20. Every existing class template has a default training strategy.
Supplemental and homebrew classes first collect a DM-confirmed progression
profile, which is remembered for later levels. Spell choices beyond the starter
catalog, unmodeled class features, and situational effects remain reviewed
entries. Multiclass advancement is a later milestone. See
[the advancement rules and scope](docs/ADVANCEMENT_RULES.md).

**The Scribe / DM Assistant** supports scene narration, campaign planning,
session preparation, advice during play, and session recaps. Load a scene or
selected records, choose the task, and add a request. **Discuss Current Battle
with Scribe** loads the current encounter's HP, initiative, conditions, effects,
and history for advice. Generated text stays editable and can be copied or
saved as a text/Markdown draft. Only **Generate Locally** starts inference; an
existing local GGUF model/llama.cpp runtime or Ollama installation is required.
Plans and advice do not change saved statistics or decide player actions.

**Roll a Random Encounter** prepares an editable scene, creature group, motives,
hook, complication, and read-aloud text, with an auditable roll log. Use active
NPC/monster templates or roll original creature baselines even in an empty
library. Original creatures roll abilities and HP; saved templates retain their
statistics. Choose a count such as `1d4`, `2d6`, or a fixed number from 1 to 12,
and optionally roll initiative. Review the creatures and scene before saving as
the current scene, adding independent copies to Battle Trakker, or opening the
proposal in the Scribe. Battle handoff adds to the current encounter; combat
starts separately. Original creatures have no assigned CR, and encounter balance
is reviewed by the DM. Reopen the generator to reuse its last roll and edits for
another handoff during the same app session. Templates are never changed by
encounter generation.

The Scribe currently accepts 6,000 characters of context plus request. Oversized
context is reported before generation, without silently truncating saved facts.

## Campaigns and sessions

Open **Campaigns & Sessions…** to create a campaign, choose its party, keep
session notes and reviewed recaps, and create named encounters. Select a session
and encounter, then click **Open Selected Session / Encounter**. The active
campaign/session/encounter is shown above the Compendium and restored on restart.
Each session owns its scene; each encounter owns its HP, initiative, conditions,
effects, and combat history. Switching saves the old workspace before opening
the next one. **Add Campaign Party to Scene** explicitly marks the saved party
as present; membership alone does not put anyone into a scene or combat.

The manager can send campaign and session context to the Scribe, including prior
completed recaps and the selected party/scene records. **Plan Campaign in Scribe**
also works before the first session exists. Plans and scene descriptions are
kept distinct from evidence about events that actually happened.

Existing local saves remain available through **Standalone Workspace**.
**Import Standalone Scene/Battle** copies them into a new campaign session and
encounter without changing the originals. Journal saves commit campaign edits,
party membership, and session notes together. See
[campaign workflows and backup scope](docs/CAMPAIGNS.md).

## Installation (Python 3.11+)

Clone the repository, then run:

```sh
python -m venv .venv
# On Linux: source .venv/bin/activate
# On Windows: .venv\Scripts\activate
python -m pip install -e .
python -m dndgm4
```

The SQLite database is created in the user application data directory,
**not** in the Git checkout:
- Windows: %LOCALAPPDATA%/DnDGameManager4/library.sqlite3
- Linux: ~/.local/share/DnDGameManager4/library.sqlite3 (or XDG_DATA_HOME)
- macOS: ~/Library/Application Support/DnDGameManager4/library.sqlite3

Back up this file before switching to a future application version.

Use **Library → Back Up Library…** to save a consistent SQLite snapshot while
the app is running. **Library → Export Library as JSON…** exports all permanent
PC, NPC, and monster records, including archived records and character sheets.
Both commands write complete files before replacing an existing destination and
refuse to overwrite the active database. The **SQLite backup includes campaigns,
parties, session journals and scenes, named encounter state, and the active
workspace**. JSON export/import covers creature records only. Standalone
`current_scene.json` and `battle_trakker.json` are separate and are not included
in a SQLite backup; import them into a campaign to capture their copied state.
To restore a SQLite backup, close the app, preserve the current database, and
copy the backup to the database location listed above.

**Library → Import Library from JSON…** opens a preview of a DnDGM4 JSON export.
Records match by their saved IDs, including archived records; matching names
alone do not count as duplicates. Choose one policy for matching IDs:

- **Skip existing records** (default) keeps the local version.
- **Keep both as separate records** adds matching records under fresh IDs,
  retaining their imported names, sheets, and archived status.
- **Replace existing records** overwrites the saved fields of matching records,
  including notes, sheets, and archived status. Local creation dates are retained.

The preview shows counts and each record's action before you click **Import**.
Cancel leaves the library unchanged. The entire file is validated first, and
the batch is committed together; a failure rolls back all changes. Import accepts
version 1 UTF-8 exports up to 32 MiB and 10,000 records. It rejects unknown fields,
invalid record values, and repeated IDs within the same file. Original IDs and
timestamps are retained for new records; copies receive new timestamps.
Legacy `.crs` files and scene/encounter state are not imported by this command.

Run tests without installing Qt:

```sh
python -m unittest discover -s tests -v
```

After installing the project dependencies, run the same suite with
`QT_QPA_PLATFORM=offscreen` to include the Qt interface tests on headless Linux.

## Historical source

The original `DnDGM308.bas` is **Liberty BASIC**, not Commodore BASIC.
Its source header explicitly says **DO NOT ALTER THIS CODE**.
The file is being kept separately until it can be archived in this
repository **verbatim**. Do not edit or overwrite it during migration.

Dungeons & Dragons is a trademark of its respective rights holders.
This is an independently developed management utility.

## RPG Name Genie 2.4 integration (v0.4.0)

**Character Forge**: Generate Name opens a themed naming chamber with core and selected expanded D&D 3.5 races.
**Monster Maker / NPC editor**: Generate Name selects a creature and naming tradition, produces eight candidates, and can fill the race/type when previously blank. Re-roll suggestions without changing the original records.

This uses **RPG Name Genie 2.4's original curated-name design**, not the v2.4.1 experimental name mixing. When `%LOCALAPPDATA%/NameGenie/namegenie_v24.sqlite3` exists, its original Fantasy entries and categories are read via a SQLite *read-only* connection. Original Name Genie files are not copied, migrated, overwritten or modified. On machines without it, a small bundled curated starter vocabulary provides fully offline naming without new dependencies. Non-core creature naming extends the v2.4 model with shared lizardkin/draconic, orc, goblinoid, giantkin, undead, fiendish, celestial, fey, construct, elemental and aberration families. Unknown species receive a clear prompt rather than arbitrary phonetic output.

3.5 creature/race categories are **labels for generating names**, not published game stat blocks, and expanded race mechanics are not automatically applied. The Character Forge's existing D&D 3.5 core-race calculations remain unchanged; expanded race choices in the naming chamber only affect its suggested names. The program does not ship copyrighted sourcebook prose or illustrations.

## Name Genie access (v0.4.1)

On the **main window** click **Generate Names** in the header, or **RPG NAME GENIE / Generate Names** in the left sidebar. **Ctrl+G** opens the same standalone Name Genie directly. It works when the character library is empty. Generate names, click one, and use **Copy Selected Name** (or double-click) to copy it to your clipboard. The generator has race / creature, gender, naming style and the original v2.4 Class, Culture and Tone classification selectors. Class/Culture/Tone narrow the read-only v2.4 database's tagged entries when that separate DB is available; built-in curated fallback names remain available even with no external DB.

**Generate Name** also appears in the *Character Forge*, and the *New NPC / New Monster* or *Edit Record* dialog. You need not save a character or create a record to use the standalone generator.

The previous v0.4.0 build incorrectly hid the Name Genie behind the create/edit dialogs, so users saw no Name Genie control on the main window. v0.4.1 fixes that UI failure. It does not yet reproduce all standalone Name Genie 2.4 features (editing, managing, and importing custom name dictionaries and pattern templates), which remain a later expansion.

## Fantasy artwork and interface (v0.5.0)

The Compendium now includes a self-contained illustrated fantasy header (dragon, d20 and distant stronghold), a matching dragon/d20 emblem for the sidebar and Windows executable, and a dedicated quill/scroll/d20 crest in RPG Name Genie. The assets live in `dndgm4/assets/`, are packaged into wheels and PyInstaller bundles, and do not require an internet connection. The images were created specifically for this application; no official D&D sourcebook or brand logos are embedded.

The **topmost Generate Names action was removed** from the main content header. Name generation is still found under **RPG NAME GENIE / Generate Names** in the sidebar and with **Ctrl+G**, and within character/monster editors. The UI uses warmer bronze panel edges, subtler slate backgrounds and high-contrast parchment-colored focus borders. Original SQLite data and mechanics were not changed.


## v0.5.0: Complete starter character sheets and optional local AI

**Character Forge** retains original 3d6/4d6 ability generation and adds editable
class builds, first-level skills, feats, equipment, background and spells/powers.
Core 3.5 base classes receive recommended starting builds. Selected supplemental
classes (Scout, Warlock, Hexblade, Favored Soul, Duskblade, Ninja, Artificer and
more) use GM-editable templates, NOT complete sourcebook class feature and spell
implementations. Choose a recommended, custom, or blank sheet; custom homebrew
classes have editable hit dice and skill-point rates. The Skills tab tracks
first-level points, class/cross-class costs and rank caps. Feats, equipment,
special features, languages, appearance and personality are freely editable.
Feat prerequisites, spells, equipment prices, and multi-level advancement remain
GM-reviewed, not automatically calculated.

Characters now save a structured v2 JSON sheet in the existing SQLite library.
Older v1 libraries migrate in place, preserving existing saved records and notes.
New first-level character sheets can be reopened and edited in the Forge.

**The Scribe** can suggest character bios, original names, and DM narration.
It runs only when a user presses Generate, against a Qwen3 text language model
at 127.0.0.1:11434 using Ollama's local /api/generate endpoint. Default model
name is qwen3:4b; the model name is editable. The app does not download or bundle
models or send requests over the internet. Qwen3-TTS from Plague's Voice Studio
is a speech model, not a prose generation model; an Ollama-compatible Qwen3 LLM
must already be available locally for text generation. Generated drafts are
editable and must be reviewed before use. No cloud account is required.

Current scope: first-level character creation; full multiclass progression,
expanded feats, skills and equipment mechanics are future milestones.


## v0.5.2: Restore the original banner and layout

Reverts the v0.5.1 changes to the main illustration's presentation. The
original fixed-height (166px) crop-to-fill banner and its single subtitle line
are restored. Removes the banner hide/show and full-artwork buttons, returns
the original dashboard spacing and default window dimensions, and retains
the classic visual styling. No artwork or character data files were replaced.

**Kept deliberately:** compact window support and the adaptive record/detail
splitter so all six ability scores remain visible. At narrow widths the record
preview moves below the table and both can scroll; at regular widths the
classic side-by-side library preview remains. No D&D mechanics or database
changes are part of this release.

## v0.5.3: Fixed square ability-score tiles

The six preview tiles (STR, DEX, CON, INT, WIS, CHA) now always occupy
76×76-pixel squares, centered in the existing three-column grid. They no
longer flatten vertically when the application is unmaximized or the
records/preview splitter changes orientation. The original 166px main
illustration, fonts, window geometry and other layout elements are unchanged.


## v0.5.4: Reuse existing Goodneighbor Blues GGUF text models

The Scribe defaults to the **Existing GGUF models (llama.cpp)** backend.
Two presets point to text models already downloaded for Goodneighbor Blues:

- Qwen3: ~/.goodneighbor_blues_dj/ai_writer/models/Qwen3-4B-Instruct-2507-Q4_K_M.gguf
- Gemma Writer: ~/.goodneighbor_blues_dj/ai_writer/models/Gemma-The-Writer-Mighty-Sword-9B-D_AU-Q4_k_m.gguf

On Windows, ~ means the home folder, e.g. C:/Users/warha_fx.
Model weights are never downloaded, imported, copied, moved, or packaged.
Gemma is suggested for character biographies and DM scenes, and Qwen3 for
names; the user can select either model for every writing task. Custom model
paths can be browsed in The Scribe.

**Inference engine:** GGUF is a model file format, not an executable.
A separate llama.cpp **llama-server** executable must exist on the machine.
The Scribe discovers it on PATH or some conventional local installation paths;
otherwise use the executable Browse picker to select llama-server.exe.
The desktop installer does not include or automatically download this
third-party engine. Install/build llama.cpp separately under its own license
if necessary. When the user explicitly clicks Generate, the app launches
the selected engine on 127.0.0.1 using a temporary local port, loads the
existing GGUF weights without modifying them. In v0.6.1, the user can
optionally keep the engine loaded between requests and unload it on demand.

By default GPU layers are 0 (portable CPU mode). Higher GPU offload requires
a compatible llama.cpp runtime such as a Vulkan-enabled build for supported AMD
GPUs and adequate GPU memory; adjust the optional GPU layers control if
appropriate. Models can require several GB of RAM.

**Alternative:** Ollama localhost remains available as an explicit backend
option for already registered Ollama model names. Ollama cannot treat a
GGUF file path as a model registry name without importing it. Importing may
consume additional storage, so direct GGUF/llama.cpp is preferred when the
goal is to share model files already used in the Goodneighbor writer.

Drafts remain editable. No changes were made to the main fantasy banner,
six ability-score squares, database, character rules, or other GUI layout.

## v0.5.5: Fluid, readable square ability-score frames

The v0.5.3 quick fix made all six ability-score boxes a tiny fixed 76x76.
That prevented stretching but cramped the actual STR/DEX/CON/INT/WIS/CHA
display. v0.5.5 replaces it with a small dedicated ability-score grid:
the cards remain exactly **1:1 square** and grow/shrink with the available
preview width within a legible **80-112 logical pixel** range. Each card
keeps its full abbreviation and numerical value.

When the available panel height is small, **only the Selected Record
preview's content scrolls** rather than crushing the ability cards to
make room for Notes and buttons. The original banner, sidebar, overall
window layout, record data, and D&D mechanics remain unchanged.


## v0.6.0: NPC Forge and D&D 3.5 Monster Forge (first rules milestone)

**NPCs use the Character Forge.** The + New NPC sidebar action now opens
the same ability rolling, manual ability entry, Name Genie, class build, skills,
feats, equipment, background and AI biography flow as Player Characters.
NPC records save as type NPC (not PC), and can reopen and edit their saved
level-one sheet.

NPCs may choose from a broad naming ancestry list, and can enter a completely
custom race. The initial *mechanically verified* ancestry profiles are the
seven original core races plus **Goblin, Orc, Kobold and Hobgoblin**. Their
racial ability modifiers and supported size adjustments are applied correctly.
Every other listed ancestry remains selectable but **requires explicit DM
confirmation and manual racial modifiers**. Its racial HD, level adjustment,
unique traits, natural armor, skill bonuses etc. are *not* automatically
provided. For creatures with 2+ racial HD use the Monster Forge to handle
their monster statistics instead of pretending a one-level humanoid NPC is
a complete creature. Known racial LA and selected traits are recorded
alongside structured ancestry data.

The five D&D 3.5 **NPC classes** (Adept, Aristocrat, Commoner, Expert, Warrior)
are in the class menu with hit dice, skill rates and editable skill/feat/gear
starter templates. Expert chooses ten class skills; the template starts with
ten editable suggestions, which can be replaced by the DM. The previous
Player Character core and supplemental class options remain intact.

**Monster Forge:** + New Monster opens the new dedicated monster builder,
with any species name, all **15 D&D 3.5 SRD creature types**, nine size
categories, subtype and racial Hit Dice, 6 editable abilities, absent CON
for constructs/undead and absent INT for mindless creatures, average/rolled/
manual HP, size-dependent construct bonus HP, base attack bonus, base saves,
natural/armor/shield AC, size and grapple modifiers, initiative, melee/ranged
attack bonuses, racial skill points and feat count. Elemental good saves
depend on Air/Fire or Earth/Water subtypes; Humanoid's one good save is
explicitly selectable. Select standard/elite/nonelite ability arrays or
enter abilities directly. Specify optional DM CR (including fractions),
natural attack routines, special attacks/qualities, skills, feats, speed,
alignment, environment, treasure, organization and more. The exact resulting
stat data is stored in the existing SQLite library's structured sheet JSON
and can be reopened and edited without overwriting unrelated notes.

**Not yet automatic:** species-specific monster stat blocks, monster levels
combined with class levels, multi-template application, natural weapon damage
tables, spell-like abilities, spell lists, detailed immunities, selected feat
prerequisites, level adjustment verification, and fully validated CR. **CR
is deliberately a DM-entered number**: D&D 3.5 increases from associated vs.
nonassociated levels, extra HD, size changes, templates and special abilities
cannot reliably be inferred from HD alone. The ability to create every
published monster is a multi-release content and rules project, not something
claimed complete by this build.

Rules references (D&D 3.5 SRD, Open Game Content):
- https://www.d20srd.org/srd/typesSubtypes.htm
- https://www.d20srd.org/srd/improvingMonsters.htm
- https://www.d20srd.org/srd/monstersAsRaces.htm
- https://www.d20srd.org/srd/npcClasses/
- https://www.d20srd.org/srd/monsters/goblin.htm
- https://www.d20srd.org/srd/monsters/kobold.htm
- https://www.d20srd.org/srd/monsters/orc.htm
- https://www.d20srd.org/srd/monsters/hobgoblin.htm

This release changes no main banner artwork, ability-score presentation or
existing data schema. The old generic record editor remains available for
legacy monster records.


## v0.6.1: faster Scribe generation with native CPU threading

In The Scribe's **Performance settings**, the decoding thread count and
prompt-processing (batch) thread count can be configured separately.
Both are passed to the installed llama.cpp executable as
`--threads` and `--threads-batch`. The conservative initial suggestion
is half the detected logical CPU count, capped at 16; e.g. a machine with
12 logical threads starts at 6. Increasing thread counts past the physical
core count can **reduce** output speed due to oversubscription. Benchmark
your own CPU, GGUF model and GPU-offload settings with the displayed total
generation time. Ollama manages its own threads and is unaffected.

The optional **Keep the selected model loaded** setting (enabled by default)
caches one llama-server process after generation, so the next name, character
bio or DM narration with the same model and settings doesn't have to reload
multiple GB of weights. Changing model, GPU offload or CPU thread settings
restarts the cached engine safely. Requests are serialized to avoid launching
multiple memory-heavy 9B copies. **Unload Model** releases the memory on
demand; quitting Game Manager also terminates the owned engine. Disabling the
checkbox restores the original start-for-one-request-and-stop behavior. While
loaded, the server only listens on loopback (127.0.0.1), never a LAN/public
interface. No model files are modified or copied.

Generation still runs off the Qt GUI thread, and The Scribe now shows elapsed
seconds including loading overhead. CPU threading can help inference but
does not promise a specific acceleration factor. A compatible GPU-enabled
llama.cpp build may offer a larger speed improvement than more CPU threads,
especially for the Gemma 9B model.


## v0.6.2: 30-pixel window and sidebar adjustment

The default main window is **1410 × 840** (previously 1380 × 840).
The left navigation pane is **276 pixels** wide (previously 246).
The minimum main window width is **830 pixels** (previously 800),
so the workspace retains its previous minimum space. Sidebar labels and
buttons are not renamed or removed. The original hero banner and
square ability-score tiles remain unchanged.


## v0.6.3: Gemma/Qwen3 biographies for characters, NPCs and monsters

The Scribe now has three **distinct, editable biography tasks**, all
available with either of the existing local Goodneighbor Blues text GGUF models:

- **Player characters:** In Character Forge, choose *Generate Character
  Biography*. The draft reflects name, race, class, alignment, ability scores,
  existing personality, appearance and DM notes, then fills the sheet's
  existing background field when **Use Draft** is selected.
- **NPCs:** In NPC Forge, choose *Generate NPC Biography*. This uses an
  NPC-specific prompt for personal history, relationships, occupation/faction,
  motives, secrets and campaign hooks. The draft saves in that NPC's existing
  character-sheet background field.
- **Monsters:** In Monster Forge, use *Generate Monster Biography*. This
  includes species, creature type/subtype, size, racial Hit Dice, attributes
  (including absent INT or CON), environment, attacks, qualities, alignment
  and DM notes as writing context. It asks for original bestiary lore,
  ecology, behavior, sightings and adventure hooks, not invented combat rules.
  The Monster Forge has a separate editable *Bestiary biography* field stored
  in its structured JSON. Existing DM notes are never replaced.

**Safeguards:** Generation is strictly opt-in. Drafts are edited and explicitly
accepted before being copied into the relevant biography field. Replacing a
nonempty biography requires a separate confirmation. Dismissing the AI dialog
does not change the record. Biographies appear in the selected-record
preview, independently of the original DM or creation notes. Saving/reopening
a creature preserves the biography without changing its monster statistics.

**Model selection:** Gemma The Writer 9B is offered as the prose default and
Qwen3 4B Instruct can be selected via the preset dropdown for *every* mode.
They reuse the same existing GGUF model files and local llama.cpp runtime,
including native CPU threading and the optional warm-model cache added in
v0.6.1. There are no model downloads or cloud API requirements. This
milestone does not alter the main window layout, sidebar, banner, ability
score tiles, character stats, monster arithmetic or database schema.


## v0.6.4: Restore reliable local AI and separate narrator window

**Restored the v0.6.0 single-request GGUF generation path.** Native
`--threads` / `--threads-batch` overrides, model caching, reuse and the
background persistent llama-server manager from v0.6.1 are removed because
they caused failures on some Windows setups. The Scribe now starts a local
llama-server on 127.0.0.1 per request, generates the text, and always
terminates that engine afterward, including when inference fails.
The model selector, existing Gemma/Qwen3 files, optional GPU layers,
NPC/monster/player biography modes and Ollama option are retained.
The existing PyQt background worker remains so generating text doesn't freeze
the GUI; that does *not* change llama.cpp's CPU threading configuration.

**Closing The Scribe narrator no longer closes D&D Game Manager 4.** The
sidebar narrator uses a separately shown nonmodal dialog, with the main
window owning its lifetime. Closing the narrator returns to the visible
Compendium. The narrator window explicitly disables the Qt close-to-quit
attribute, and reopening the narrator focuses its existing window instead
of creating a second one. Other generation dialogs continue to behave
normally. No D&D rules, character data, monster calculations or main
window artwork/layout was modified.

Regression coverage includes single-use launch arguments, no cached model,
cleanup on errors, and Windows GUI tests to assert that the main window
remains visible after the Scribe is closed. The v0.6.1 Performance settings
and warm-model instructions above are **superseded** by this rollback.

## v0.6.5: Select several records for a scenario or The Scribe

The **All Records** table now supports standard Ctrl-click, Shift-click and
Ctrl+A selection. Select PCs, NPCs and monsters together, without needing to
create duplicate records. Multiple selected rows cannot accidentally trigger
single-record Edit, Duplicate or Archive actions.

Under Records:
* **Load Selection into Scribe:** sends all explicitly selected records to
  the existing narrator, including their saved ability scores, class, levels,
  feats, skills, equipment, spells, backgrounds, monster HD, special abilities,
  ecology, lore, and DM notes when present. The source is each record's full
  SQLite data and decoded structured sheet JSON. Already-open Scribe windows
  receive the new prompt when you explicitly select this action.
* **Add Selected to Scene:** saves each selected record into the current
  scenario roster without duplicates. You can add PCs from the PC tab, NPCs
  from NPCs and monsters from Bestiary, then use All Records to review them.
* **Edit Scene:** defines the actual people and creatures present alongside
  scene title, location, conditions, scenery, named settlements/inns/taverns
  and campaign continuity. The roster is editable with checkboxes.
* **Load Scene into Scribe:** sends the saved scene plus the complete sheets
  of explicitly included members. Archived/missing roster members trigger
  an actionable error rather than being silently omitted.

The active scene persists atomically as current_scene.json beside the user's
existing local library.sqlite3; no schema migration is required. The full
creature library is **not** assumed to be present at an encounter by default.
The Scribe still uses local Gemma/Qwen3 GGUF inference only. AI narration does
not modify game statistics, creature saves or the database.

**Context size matters:** the current lightweight local inference mode accepts
at most 6,000 input characters. If all selected character sheets cannot fit,
the application shows a precise error and asks you to reduce the number of
records or shorten scene notes, rather than quietly truncating important
character or monster fields. This is a foundation for future multi-pass
context retrieval and persistent campaigns.

**Windows reliability:** each major child dialog is marked not to quit
the main app when closed. The startup icon loader gracefully survives a
missing asset, and the Windows installer workflow now verifies that the
PyInstaller package contains dragon_crest.png, app_banner.jpg and
name_genie_crest.png before publishing. The original fantasy artwork and
ability-score layouts are otherwise untouched. The previous v0.6.4
one-request GGUF backend remains unchanged; the multithreading discussion
will be handled separately after measuring actual memory usage.


## v0.7.0: Character Forge three-route foundation, spellbooks and inventory

The **first-level** PC/NPC Character Forge now begins with three user-facing
creation routes:
1. **Class Default**, with editable SRD-inspired class/race starting presets
   for legal first-level spellbooks, feats, skills, special abilities,
   equipment and starter inventory. Starter feats that fail implemented
   prerequisites fall back to universal alternatives.
2. **AI Generated**, using the existing local Gemma Writer or Qwen3 GGUF model
   via The Scribe. The model proposes a complete structured first-level build
   (base abilities, class, race, skills, feats, gear, inventory, spellbook and
   biography). The app *never* imports the JSON directly as game mechanics:
   `ai_character.py` validates record type, selected race/class, six base
   scores, skill spending, encoded feat prerequisites/count and spell lists.
   Invalid AI JSON or rules are rejected and the unsaved character remains
   unchanged; valid selections populate the **editable** Forge.
3. **Custom Guided**, a seven-step navigation sequence covering identity,
   ability-score rolling/manual input, feats/class abilities, allocated skills,
   spells and spellbooks, inventory, and story/review. It uses deterministic
   skill, spell and encoded feat validation at save. It is a structured
   interface to the existing Forge, not a wholesale replacement of its GUI.

New **Spells & Spellbook** tab: a curated first-level D&D 3.5 SRD list for
Wizard, Sorcerer, Cleric, Druid, Bard and NPC Adept. Spell lists separate
spontaneous *spells known* from prepared daily spells and the Wizard's
permanent spellbook. Core first-level spell slots and bonus slots come from
the class and casting ability. A Wizard's starting book includes all
0-level wizard spells and **3 + INT modifier** first-level spells; daily
prepared spells are validated against that book. Clerics have an additional
first-level domain slot separate from ordinary prepared spell slots.
Wizard specialization, prohibited schools and cleric domains are stored,
with manual rules review required until the full specialization/domain spell
catalog is implemented. Other base and supplemental classes do not receive
invented first-level spellcasting.

New **Inventory** tab: persistent quantity-aware carrying list with
`3 x Torch` notation. Inventory, spells known/prepared, spellbook and
class feature suggestions are stored as structured JSON in the existing
`sheet_json` field, no SQLite migration required. Existing records
and the historic freeform spell notes remain readable/editable.

**Scope and remaining work:** This milestone is a rules-checked first-level
foundation, NOT complete PHB/expanded-book character generation. We still
need exhaustive SRD feat and spell tables/descriptions/prerequisites,
cleric domain restrictions, wizard specialization rules, selection of
alternative class features, full class-based leveling to 20, multiclass
levels, equipment costs/weight/encumbrance/proficiencies, and wealth-by-level
options. Supplemental classes remain editable DM-reviewed templates.
Unverified feat prerequisites and unusual spells are never silently
certified as valid. Automated tests cover core spell limits, class
compatibility, feat prerequisites, data persistence, all three GUI modes
and AI proposal validation. The existing one-shot local GGUF inference
engine, artwork, windows, scene-loading workflow and record layout are
preserved unchanged.

Open Game Content rules reference: 3.5 SRD class/spell/feat pages at
https://www.d20srd.org/srd/classes/sorcererWizard.htm ,
https://www.d20srd.org/srd/classes/bard.htm ,
https://www.d20srd.org/srd/classes/cleric ,
https://www.d20srd.org/srd/classes/druid.htm ,
https://www.d20srd.org/srd/feats.htm


## v0.7.1: age and gender identity for all three character types

**Characters and NPCs:** On the Story tab, select or enter a gender
(Unspecified/Female/Male/Nonbinary/Genderless/Other or a custom description)
and enter a character age or life stage. Both are saved as independent
`gender` and `age` fields in the structured sheet, available to The Scribe
and on subsequent edits. Previous v0.7.0 sheets kept age inside
`extra_notes` as `Age: ...`; the Forge now recognizes and moves that value
into the dedicated age field on editing, without losing other notes.

**Monsters:** Monster Forge now also has editable gender and age/life stage,
including suitable values such as Genderless, Ancient, Ageless or a numerical
age. Those values are stored separately alongside creature type, racial
Hit Dice, lore and other monster properties, and are preserved on reopening
a monster. Monster biography generation uses both attributes in its prompt.

**AI creation:** The complete Gemma/Qwen first-level character generator
requests gender and age and validates the returned strings. If the user
sets either in advance, the AI cannot silently change it; when left
unspecified, the model may propose values. Character/NPC biography writing
also receives the current gender and age.

These identity entries are descriptive and **do not automatically trigger
D&D 3.5 age penalties or bonuses**. Such calculations require an
individual species' age categories, which remain a separate rules milestone.
The existing creature SQLite schema and ability-score/banner layout are
unchanged. Regression tests cover PC/NPC/monster round trips and migration
from old age notes.


## v0.7.2: child-dialog and AI Use Draft lifecycle hotfix

Fixes a reported Windows regression where closing a secondary window,
particularly pressing **Use Draft** in the AI character generator, terminated
the entire manager. The app now disables Qt's implicit *quit when the last
window closes* behavior, and quits explicitly only when the Compendium main
window itself closes. This applies to Character Forge, NPC Forge, Monster
Forge, The Scribe and other child windows.

The AI character generation route now catches unexpected errors while applying
a reviewed draft and shows an error rather than letting exceptions escape
the Qt button callback. No character is automatically saved by Use Draft;
the editable Forge remains the source of truth.

The regression test runs a real `QApplication.exec()` in a separate process,
opens the true `MainWindow.create("pc")` path, opens The Scribe in a nested
`QDialog.exec()`, clicks its actual **Use Draft** button with a validated
AI proposal, then checks both the Forge and the Compendium are still visible.
This is not merely a mock returning `Accepted`. No model is executed during
the GUI regression. Windows runtime tests are required before merge.

The existing 3.5 rules calculations, stored characters, persistent scenes,
fantasy banner, ability-score layout and previous one-request GGUF model
runtime are unchanged.

## v0.7.3: Larger main desktop window and wider navigation

The Compendium opens at **1551 × 924 pixels**, exactly 10% larger in both
dimensions than its previous 1410 × 840 default. The left navigation
pane is **326 pixels** wide (up from 276) to give its existing labels
more room. The content workspace gains another 91 pixels of width.

Only the outer main-window size and sidebar width change. Existing
fonts, controls, hero banner height (166 px), square ability-score
tiles, buttons, menus and child-dialog sizes are preserved. The
compact minimum window dimensions remain 830 × 540.

The local Gemma/Qwen3 GGUF inference engine is **unchanged**. The user
confirmed that the recent writer failure was due to memory pressure
from other running applications, not a newly introduced model-access
regression.


## v0.8.0: Battle Trakker, live D&D 3.5 combat / encounter manager

Open **Battle Trakker / Combat Manager** in the Compendium sidebar, press
**Ctrl+B**, or multi-select records in All Records and choose **Load Selected
into Battle Trakker**. It is a separate reusable non-modal window and never
closes the main program.

- Import players, NPCs and monsters from the existing library, with as many
  separately tracked copies of a monster as required. **Add Scene Roster**
  uses the checked members from the Compendium's saved scene and captures
  scene notes/conditions. **Add from Library** offers bulk selection and
  a copy count. **+ Custom** adds ad-hoc allies, foes and hazards.
- **Initiative:** roll unbiased d20 plus the record's Dexterity modifier
  and the stored **Improved Initiative** bonus, or use the saved monster
  computed initiative field when available. Manually override initiative,
  preserve Dexterity-based tie ordering, and mark surprised creatures. A
  surprise round (round 0) includes only eligible combatants, followed by
  the normal round 1 in initiative order. Adjust active participant status.
- **Hit points:** current/max HP, damage, healing capped to normal maximum,
  separately assigned temporary HP (absorbed before damage), direct HP edits,
  and reminders at zero or negative HP. The manager makes no universal
  assumptions about special creature death rules.
- **D&D 3.5 conditions:** select named SRD conditions or write custom ones.
  Track each with a number of turns or leave it indefinite. Countdowns
  decrement at the **end of the affected combatant's own turn**; the DM
  remains responsible for special timing such as "until the start of the
  caster's next turn", saving throws, durations in minutes, or magical
  effects requiring separate adjudication.
- **Combat workflow:** Start Encounter, Next Turn, End Encounter, combat
  status and color-coded initiative roster, freeform DM event notes,
  chronological log, and in-session Undo Last Action (history is deliberately
  not serialized with saved encounters). Real-time table updates.
- **Persistence:** automatic, atomic save to `battle_trakker.json` alongside
  `library.sqlite3` after each action. Closing or reopening the window and
  restarting the application restores the encounter (round, current actor,
  health, statuses, log, etc.). A malformed or corrupted battle file is
  reported and left untouched, not silently replaced. Create a fresh
  encounter only after a confirmation prompt.

**Important separation:** Every combatant is an *encounter instance*.
Tracking damage, conditions or initiative never edits the library's
permanent PC/NPC/monster character sheets or maximum hit points. Species
copies have independent IDs, HP and turns. No SQLite schema migration,
cloud requests or AI model changes. The main Compendium banner, size,
left sidebar width, 1:1 ability tiles and desktop styling remain intact.

**Not yet automatic:** D&D 3.5 attacks of opportunity, readied/delayed
actions, full attack sequence adjudication, feats/effects changing AC and
bonuses dynamically, automatic spell duration at caster-specific timing,
critical confirmation, challenge-rating/encounter-level/XP tables, treasure
allocation, and advanced battle maps. These remain DM responsibilities
until their dedicated rules engines and UI are implemented.

Rules reference: D&D 3.5 SRD, Combat,
https://www.d20srd.org/srd/combat/initiative.htm ,
https://www.d20srd.org/srd/conditionSummary.htm and
https://www.d20srd.org/srd/combat/injuryandDeath.htm .

## v0.9.0: SRD 3.5 Encounter Command

This milestone extends Battle Trakker v0.8.0 (which remains available with Ctrl+B) with an optional **Encounter Command** combat desk.

- Initiative-anchored spell/effect clocks, six-second in-game rounds, independent opt-in wall-clock countdowns, and persistence compatible with v0.8 encounter snapshots.
- Standard, move, full-round, swift, immediate and free action budgets, with explicit DM override for exceptions.
- Deterministic attack and skill/save adjudication, including natural 1/20 behavior where the SRD specifies it, threat/critical confirmation, weapon damage, cover, concealment, damage reduction and optional application of damage.
- Spell slot and casting history tracking, plus opt-in indexing of six SRD class spell lists, cached locally for subsequent offline use.
- SRD combat reference and scene-aware local Scribe narration. AI narration does not determine game mechanics or modify combat statistics.

**Limits:** This is not an exhaustive D&D 3.5 combat engine. Spell-specific effects, non-SRD sourcebooks, prestige-class spells, tactical movement and attacks of opportunity, nuanced feat/equipment stacking, precision damage, grappling/trip/disarm and other advanced rulings remain for the DM to review. The optional spell index importer needs a deliberate initial online operation; normal combat tracking needs no internet.

The Windows installer and portable ZIP are built by GitHub Actions. For an up-to-date test build, open the most recent successful **Windows installer** run on the `main` branch and download its `DnDGameManager4-Windows-*` artifact. Installer versions are read from `pyproject.toml`.
