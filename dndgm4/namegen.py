"""D&D 3.5 naming adapter to RPG Name Genie 2.4's curated-name model.

Uses the stable v2.4 roles (Given/Family/Mononym/Clan) and exact read-only
SQLite tag schema when a v2.4 database exists. NEVER opens the Name Genie
database for writing. Built-in curated fallback is available offline for
machines without Name Genie installed. Avoids the v2.4.1 linguistic changes.
"""
from __future__ import annotations

import os
import random
import sqlite3
from pathlib import Path

# Race and creature names are taxonomy only. They are not mechanical rules.
# Core races are first; expanded creatures include a selected set of 3.5
# Races of Stone / Wild / Destiny / Dragon, Eberron, and Monster Manuals.
CORE_RACES = ("Human", "Dwarf", "Elf", "Gnome", "Half-elf", "Half-orc", "Halfling")
EXPANDED_RACES = (
    "Aasimar", "Air Genasi", "Aquatic Elf", "Catfolk", "Changeling",
    "Chaos Gnome", "Deep Gnome", "Dragonborn", "Drow", "Duergar",
    "Earth Genasi", "Elan", "Fire Genasi", "Goliath", "Goblin",
    "Half-giant", "Hobgoblin", "Illumian", "Kalashtar", "Kenku",
    "Kobold", "Lizardfolk", "Orc", "Raptoran", "Shifter", "Spellscale",
    "Tiefling", "Warforged", "Water Genasi", "Whisper Gnome", "Xeph",
)
MONSTER_RACES = (
    "Aboleth", "Angel", "Archon", "Bugbear", "Demon", "Devil",
    "Draconian", "Dracotaur", "Dragon", "Dryad", "Elemental", "Ettin",
    "Fey", "Flind", "Gargoyle", "Ghoul", "Giant", "Gnoll", "Goblin",
    "Golem", "Harpy", "Hobgoblin", "Kobold", "Lich", "Lizardfolk",
    "Mind Flayer", "Minotaur", "Naga", "Ogre", "Ogre Mage",
    "Orc", "Rakshasa", "Sahuagin", "Skeleton", "Skullcrusher Ogre",
    "Specter", "Ssvaklor", "Troll", "Troglodyte", "Vampire",
    "Warforged", "Wight", "Wraith", "Yuan-ti", "Zombie",
    "Lizardkin", "Reptilian", "Dragonkin", "Orckin", "Ogrekin", "Goblinoid",
)
ALL_KINDS = tuple(dict.fromkeys(CORE_RACES + EXPANDED_RACES + MONSTER_RACES))
GENDERS = ("Unspecified", "Masculine", "Feminine", "Neutral", "Nonbinary")

# Curated aliases share coherent name components. No arbitrary phoneme soup.
# Keys MUST be explicit; unknown inputs fall back to Human only when selected
# by the user, never silently map random creature types to something unrelated.
FAMILY_ALIASES = {
    "human": "Human", "half-elf": "Elf", "elf": "Elf", "drow": "Elf",
    "aquatic elf": "Elf", "dryad": "Elf", "fey": "Elf",
    "dwarf": "Dwarf", "duergar": "Dwarf", "goliath": "Giantkin",
    "half-giant": "Giantkin", "giant": "Giantkin", "ettin": "Giantkin",
    "ogre": "Giantkin", "ogrekin": "Giantkin",
    "ogre mage": "Giantkin",
    "skullcrusher ogre": "Giantkin", "troll": "Giantkin",
    "gnome": "Gnome", "deep gnome": "Gnome", "chaos gnome": "Gnome",
    "whisper gnome": "Gnome", "halfling": "Halfling",
    "orc": "Orc", "orckin": "Orc", "orc-kin": "Orc",
    "half-orc": "Orc", "flind": "Orc",
    "gnoll": "Orc", "bugbear": "Goblinoid", "goblin": "Goblinoid",
    "hobgoblin": "Goblinoid", "goblinoid": "Goblinoid",
    "lizardkin": "Draconic", "reptilian": "Draconic",
    "dragonkin": "Draconic", "kobold": "Draconic",
    "dragon": "Draconic", "dragonborn": "Draconic",
    "draconian": "Draconic", "dracotaur": "Draconic",
    "lizardfolk": "Draconic", "troglodyte": "Draconic",
    "yuan-ti": "Draconic", "naga": "Draconic", "ssvaklor": "Draconic",
    "sahuagin": "Draconic", "spellscale": "Draconic",
    "tiefling": "Infernal", "demon": "Infernal",
    "devil": "Infernal", "rakshasa": "Infernal",
    "aasimar": "Celestial", "angel": "Celestial", "archon": "Celestial",
    "lich": "Undead", "ghoul": "Undead", "skeleton": "Undead",
    "specter": "Undead", "wight": "Undead", "wraith": "Undead",
    "zombie": "Undead", "vampire": "Undead",
    "warforged": "Construct", "golem": "Construct", "gargoyle": "Construct",
    "mind flayer": "Aberration", "aboleth": "Aberration",
    "elemental": "Elemental",
    "air genasi": "Elemental", "earth genasi": "Elemental",
    "fire genasi": "Elemental", "water genasi": "Elemental",
    "shifter": "Human", "changeling": "Human", "kalashtar": "Human",
    "illumian": "Human", "elan": "Human", "xeph": "Human",
    "catfolk": "Human", "kenku": "Human", "raptoran": "Elf",
    "minotaur": "Giantkin", "harpy": "Fey",
}
# Stable v2.4 source species for each naming family. Never load original
# profiles with an incompatible selection (e.g. 2.4.1's nonsense mixer).
V24_SPECIES = {
    "Human": "Human", "Elf": "Elf", "Dwarf": "Dwarf",
    "Gnome": "Gnome", "Halfling": "Halfling", "Orc": "Orc",
    "Draconic": "Dragonborn", "Infernal": "Tiefling",
}
# Original 2.4 curated vocabulary serves as a portable fallback. These
# are name components rather than generated random syllables.
BANKS = {
    "Human": {
        "Given": "Aldric Cedric Garrick Eamon Leoric Tristan Ronan Edric Elara Isolde Mira Rowena Tamsin Briony Seraphine Lyanna Ash Rowan Arden Wren",
        "Family": "Blackwood Hawthorne Vale Mercer Ashford Thornfield Greycastle Fairward Duskmere Westreach",
    },
    "Elf": {
        "Given": "Aelira Elowen Liraeth Sylvara Naevys Thalira Elaria Mirelle Faelar Theron Aerendil Caelion Valen Lethar Eryndor Ithilien Aeris Saelis Vael Elian Meris Lior",
        "Family": "Moonwhisper Starbough Silverleaf Dawnweaver Nightbrook Windglade Thornsong Brightgrove",
    },
    "Dwarf": {
        "Given": "Borin Durnan Thorek Baldrin Korrin Grumdir Barund Odrik Brynja Hilda Dagna Torhild Runa Astrid Freydis Gudra Keld Brenn Torren",
        "Family": "Ironbeard Stonehelm Deepforge Coppervein Oathhammer Coalbraid Flintmantle",
        "Clan": "Ironhammer Stoneward Emberdelve",
    },
    "Halfling": {
        "Given": "Pip Tilly Merrin Bess Rowan Bram Jory Nell Odo Fina",
        "Family": "Underhill Bramblefoot Greenbottle Goodbarrel Proudfern Swiftwhistle",
    },
    "Gnome": {
        "Given": "Nim Pippa Fizzwick Tinker Jinx Bix Rolo Wizzle Cogo Fen Kello Zanna",
        "Family": "Gearwhistle Copperspark Tumblesprocket Wobblewick Sparkspinner",
    },
    "Orc": {
        "Given": "Gorak Thurog Makhar Urgoth Brogar Kargun Drokh Grasha Mogha Urzha Korga Draga Shurka Rukh Thrak Ghor Vash Zog",
        "Family": "Bonecleaver Ashfang Bloodtusk Ironscar Grimjaw Doomtusk",
    },
    "Draconic": {
        "Given": "Arjhan Balasar Rhogar Medrash Kriv Akra Nala Torinn Bharash Ghesh Surina Varan",
        "Family": "Flamescale Stormcrest Embermaw Brightclaw Thunderjaw Sunscale",
    },
    "Goblinoid": {
        "Given": "Grib Skrit Vrakk Dreg Nix Ruk Tazh Skrag Keth Zik Mogg Rix Vruk",
        "Family": "Mudfang Blacktooth Ashclaw Grimnose Ragscar Thornhide",
    },
    "Giantkin": {
        "Given": "Brundar Gorrum Halgrun Thogar Urmak Orren Vuldar Kragga Mogrum Grenda Hroth Vorn",
        "Family": "Boulderbreaker Skycrag Stoneshoulder Ironfist Thunderfoot Hillcrusher",
    },
    "Infernal": {
        "Given": "Vesper Nyx Zephyr Ravyn Sable Azriel Ember Malice Malphas Raziel Zareth Azura",
        "Family": "Ashborne Nightveil Cinderfall Duskmantle Ashveil Dreadmoor",
    },
    "Celestial": {
        "Given": "Aureliel Sereniel Caelora Valenor Ishara Elyra Vaeriel Solanar Orriel",
        "Family": "Dawnward Starwatch Lightweaver Brightward Sunsong",
    },
    "Undead": {
        "Given": "Mordren Velis Caldris Thren Morvain Xareth Vesper Noctis Eryss",
        "Family": "Graveborn Nightshroud Bleakthorn Hollowmantle Dreadmoor",
    },
    "Construct": {
        "Given": "Aegis Rook Sentinel Ember Forge Bastion Varn Cobalt",
        "Family": "Ironward Brassheart Stonebound Gearwright",
    },
    "Aberration": {
        "Given": "Xelari Thriix Vornax Qirel Zenthra Ulorix Nyrax Thuun",
        "Family": "Zorath Kheltar Varruun Syrix",
    },
    "Fey": {
        "Given": "Liraeth Saelis Eiryn Vaela Thornwyn Selyra Niviel Aster",
        "Family": "Mossbriar Willowmere Dewthorn Starpetal Moonbrook",
    },
    "Elemental": {
        "Given": "Ember Ashen Pyra Cinder Zephra Skyr Ilvar Umber Solan",
        "Family": "Stormborn Ashveil Stonewake Flameward Tiderun",
    },
}
# All non-core families are original extension material, not copied game text.
MONSTER_EPITHETS = {
    "Draconic": ("the Coil", "of the Scales", "the Flame-Tongued", "the Marsh Stalker"),
    "Orc": ("the Ironfang", "the Blooded", "the Raider"),
    "Goblinoid": ("the Sneak", "the Redcap", "the Tunnel-Lord"),
    "Giantkin": ("the Mountain", "the Stonebreaker", "the Ravager"),
    "Undead": ("the Hollow", "the Deathless", "of the Crypt"),
    "Infernal": ("the Oathbreaker", "the Ashen", "the Fell"),
    "Aberration": ("the Unseen", "the Whisperer", "the Unblinking"),
    "Construct": ("the Unyielding", "the Watcher", "the Forged"),
    "Fey": ("of the Thorns", "the Moonlit", "the Wayward"),
    "Elemental": ("the Living Storm", "of the Deep", "the Burning"),
}
class UnsupportedCreature(ValueError):
    pass


def family_for(race: str) -> str:
    """Exact and case-insensitive. Never fabricate an unknown race's names."""
    key = " ".join(race.strip().casefold().split()).replace("_", " ")
    if key in FAMILY_ALIASES:
        return FAMILY_ALIASES[key]
    for group in BANKS:
        if key == group.casefold():
            return group
    raise UnsupportedCreature(f"No naming profile for {race!r}. Choose a related family.")


def default_v24_path() -> Path:
    base = Path(os.environ.get("LOCALAPPDATA") or Path.home() / ".local" / "share")
    return base / "NameGenie" / "namegenie_v24.sqlite3"


def read_v24_bank(path: Path, species: str, role: str, gender: str = "Unspecified"
                  ) -> list[str]:
    """Fetch originals with readonly SQLite; reject malformed/other schemas."""
    if not path.is_file():
        return []
    # SQLite URI mode=ro prevents creating or changing an original database.
    from urllib.parse import quote
    uri = "file:" + quote(str(path.resolve()).replace("\\", "/"), safe="/:") + "?mode=ro"
    db = sqlite3.connect(uri, uri=True)
    try:
        found = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if not {"entries", "tags"} <= found:
            return []
        rows = db.execute(
            """SELECT DISTINCT e.name FROM entries e
            WHERE e.role = ?
              AND EXISTS (SELECT 1 FROM tags t WHERE t.entry_id=e.id
                          AND t.facet='Genre' AND t.value='Fantasy')
              AND EXISTS (SELECT 1 FROM tags t WHERE t.entry_id=e.id
                          AND t.facet='Species' AND t.value=?)
              AND NOT EXISTS (SELECT 1 FROM tags t WHERE t.entry_id=e.id
                          AND t.facet='Gender' AND t.value <> ?)
            ORDER BY e.name""",
            (role, species, gender),
        ).fetchall()
        return [r[0] for r in rows if r[0].strip()]
    finally:
        db.close()


class NameEngine:
    """Selection-based v2.4 naming, extended with taxonomy for 3.5 creatures."""

    def __init__(self, namegen_v24_db: str | Path | None = None,
                 rng: random.Random | None = None):
        self.db_path = Path(namegen_v24_db) if namegen_v24_db else default_v24_path()
        self.rng = rng if rng is not None else random.SystemRandom()

    def _bank(self, family: str, role: str, gender: str) -> list[str]:
        names = list(dict.fromkeys(BANKS[family].get(role, "").split()))
        source = V24_SPECIES.get(family)
        if source:
            try:
                from_original = read_v24_bank(self.db_path, source, role, gender)
                # v2.4 curated names take precedence; builtin names fill coverage.
                if from_original:
                    return list(dict.fromkeys(from_original + names))
            except (OSError, sqlite3.DatabaseError):
                pass
        return names

    def generate(self, race: str, *, gender: str = "Unspecified",
                 monster: bool = False, count: int = 8,
                 surname: bool | None = None) -> list[str]:
        if gender not in GENDERS:
            raise ValueError("Unsupported gender preference.")
        if not 1 <= count <= 100:
            raise ValueError("Request between 1 and 100 names.")
        family = family_for(race)
        # Default formatting: named humanoids normally have family names;
        # monsters prefer individual names/epithets, not human surnames.
        use_family = (not monster) if surname is None else surname
        given = self._bank(family, "Given", gender)
        if not given:
            raise UnsupportedCreature(f"No given names in {family!r}.")
        family_bank = (self._bank(family, "Clan", gender) if family == "Dwarf"
                       else self._bank(family, "Family", gender))
        family_bank = family_bank or self._bank(family, "Family", gender)
        output = []
        seen = set()
        attempts = 0
        while len(output) < count and attempts < count * 100:
            attempts += 1
            first = self.rng.choice(given)
            if use_family and family_bank:
                candidate = first + " " + self.rng.choice(family_bank)
            elif monster and family in MONSTER_EPITHETS and self.rng.random() < 0.45:
                candidate = first + " " + self.rng.choice(MONSTER_EPITHETS[family])
            else:
                candidate = first
            if candidate.casefold() not in seen:
                seen.add(candidate.casefold())
                output.append(candidate)
            if len(seen) >= len(given) and not use_family and (not monster or family not in MONSTER_EPITHETS):
                break
        return output
