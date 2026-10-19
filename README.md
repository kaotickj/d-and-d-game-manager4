# Dungeons & Dragons Game Manager 4

Modern Python and PyQt6 continuation of **Dungeons & Dragons Game Manager
3.08**, originally designed and coded by **Kaotick Jay** in Liberty BASIC
(likely 4.03). Original source header credits Copyright 2001–2025
**Kaosium Interactive**.

## Status: early development, v0.2.0

Current milestone: **The Compendium**, a themed Character & Monster Library, backed by SQLite.
Create, search, edit, duplicate, archive and restore player characters,
NPCs and monster templates. Records persist between application launches.

This is **not yet a complete D&D 3.5 rules engine**. See
[the roadmap](docs/ROADMAP.md) for the next milestones.

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

Run tests without installing Qt:

```sh
python -m unittest discover -s tests -v
```

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
