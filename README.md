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
