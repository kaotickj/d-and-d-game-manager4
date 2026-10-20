"""D&D 3.5 SRD spell list indexer.

Opt-in download on first use from d20srd.org. The index stores names, class,
level and reference URLs, not non-OGL sourcebook text or proprietary art.
Once indexed, lookup works entirely offline. No auto-network access.
"""
from __future__ import annotations
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urljoin, urlsplit
from urllib.request import Request, urlopen
import json
import os
import re
import tempfile

BASE = "https://www.d20srd.org"
LISTS = {
    "Bard": "/srd/spellLists/bardSpells.htm",
    "Cleric": "/srd/spellLists/clericSpells.htm",
    "Druid": "/srd/spellLists/druidSpells.htm",
    "Paladin": "/srd/spellLists/paladinSpells.htm",
    "Ranger": "/srd/spellLists/rangerSpells.htm",
    "Sorcerer/Wizard": "/srd/spellLists/sorcererWizardSpells.htm",
}
LEVEL = re.compile(r"\b([0-9])(?:st|nd|rd|th)?-Level\b", re.I)


class SpellListParser(HTMLParser):
    def __init__(self, class_name, source):
        super().__init__(convert_charrefs=True)
        self.class_name = class_name
        self.source = source
        self.level = None
        self.heading = None
        self.heading_buffer = []
        self.anchor_href = None
        self.anchor_buffer = []
        self.spells = []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag in ("h2", "h3", "h4", "h5"):
            self.heading = tag
            self.heading_buffer = []
        if tag == "a" and self.level is not None:
            href = attrs.get("href", "")
            full = urljoin(self.source, href)
            if (urlsplit(full).hostname in ("www.d20srd.org", "d20srd.org")
                    and "/srd/spells/" in urlsplit(full).path.lower()):
                self.anchor_href = full
                self.anchor_buffer = []

    def handle_data(self, data):
        if self.heading:
            self.heading_buffer.append(data)
        if self.anchor_href is not None:
            self.anchor_buffer.append(data)

    def handle_endtag(self, tag):
        if self.heading == tag:
            match = LEVEL.search(" ".join(self.heading_buffer))
            if match:
                self.level = int(match[1])
            self.heading = None
            self.heading_buffer = []
        if tag == "a" and self.anchor_href is not None:
            name = re.sub(r"\s+", " ", "".join(self.anchor_buffer)).strip(" .:,")
            if name and len(name) <= 110 and not name.lower().startswith("see "):
                self.spells.append({
                    "name": name, "class": self.class_name,
                    "level": self.level, "url": self.anchor_href,
                })
            self.anchor_href = None
            self.anchor_buffer = []


def parse_spell_list(html, class_name, source):
    parser = SpellListParser(class_name, source)
    parser.feed(html)
    result = {}
    for spell in parser.spells:
        result[(spell["name"].casefold(), spell["class"], spell["level"])] = spell
    return sorted(result.values(), key=lambda s: (s["level"], s["name"].casefold()))


def download_srd_catalog(fetch=None):
    """Return the complete class spell lists, fetching only the six pinned URLs.

    Each spell on two class lists has two rows so filtering works. Core cleric
    domains and prestige class lists are separate and not implied included.
    """
    spells = []
    for class_name, relative in LISTS.items():
        url = BASE + relative
        if fetch is not None:
            body = fetch(url)
        else:
            req = Request(url, headers={"User-Agent": "DnDGM4-SRD-SpellIndexer/1.0"})
            with urlopen(req, timeout=20) as response:
                body = response.read(900000)
        if isinstance(body, bytes):
            body = body.decode("utf-8", errors="replace")
        entries = parse_spell_list(body, class_name, url)
        if len(entries) < 5:
            raise ValueError(f"No useful spells parsed from {class_name}; the source may have changed.")
        spells.extend(entries)
    return spells


class SpellCatalog:
    def __init__(self, database_path):
        self.path = Path(database_path).with_name("srd35_spells.json")
        self.spells = self.load()

    def load(self):
        if not self.path.exists():
            return []
        if self.path.stat().st_size > 2000000:
            raise ValueError("Spell index is unexpectedly large.")
        data = json.loads(self.path.read_text(encoding="utf-8"))
        if not isinstance(data, list) or len(data) > 8000:
            raise ValueError("Invalid spell index.")
        for spell in data:
            if not isinstance(spell, dict) or set(spell) != {"name", "class", "level", "url"}:
                raise ValueError("Invalid indexed spell.")
            if (not isinstance(spell["name"], str) or
                spell["class"] not in LISTS or
                type(spell["level"]) is not int or not 0 <= spell["level"] <= 9 or
                not isinstance(spell["url"], str) or
                not spell["url"].startswith(BASE + "/srd/spells/")):
                raise ValueError("Untrusted index data.")
        return data

    def build(self, fetch=None):
        entries = download_srd_catalog(fetch=fetch)
        self.store(entries)
        return entries

    def store(self, entries):
        content = json.dumps(entries, ensure_ascii=False, indent=1)
        if len(content.encode("utf-8")) > 2000000:
            raise ValueError("Spell index exceeds maximum size.")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        name = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w", encoding="utf-8", dir=self.path.parent,
                prefix=".spells-", suffix=".tmp", delete=False
            ) as fh:
                name = fh.name
                fh.write(content)
                fh.flush()
                os.fsync(fh.fileno())
            os.replace(name, self.path)
            self.spells = self.load()
        finally:
            if name and os.path.exists(name):
                os.unlink(name)

    def search(self, phrase="", class_name="", level=None):
        phrase = phrase.casefold().strip()
        return [s for s in self.spells
                if (not phrase or phrase in s["name"].casefold())
                and (not class_name or class_name == s["class"])
                and (level is None or level == s["level"])]
