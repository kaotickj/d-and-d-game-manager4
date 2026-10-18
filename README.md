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
