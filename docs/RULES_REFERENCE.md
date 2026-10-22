# Rules Compendium

The Rules Compendium searches D&D 3.5 reference material locally. It starts with
12 concise, original reference summaries so common lookups work while offline.
These are labelled **Authored reference summary** and link to the corresponding
3.5 SRD rules. They are orientation notes rather than a complete rules corpus.

Open the compendium from the main window, enter a few search words, and select a
result. Every search word must appear in the result's title, section or passage.
Results include the matching passage, its source and edition. **Read Whole
Document** provides surrounding rules and exceptions. **Open Source** opens the
reference URL only when clicked.

**Use in Scribe** passes the selected passage and its provenance to the local
writing assistant. The Scribe is instructed to cite `[R1]` evidence, distinguish
summaries from source passages, identify missing evidence and keep house rulings
separate from published rules. Reference text is treated as data rather than
instructions. A local language model can still make mistakes, so its answer is
reviewable against the displayed passage and linked source.

This is a retrieval knowledge base. It does not fine-tune model weights or claim
that the installed model has been trained on the SRD. Looking up a rule does not
start model generation.

## Adding the revised SRD

Choose a section and click **Download SRD Section**. One listed HTML page is
downloaded into the local library; opening the dialog and searching never access
the network. Downloads run in a background worker, use a time limit, and are
limited to 4 MiB per document. Failed downloads leave the current library intact.

The curated catalog includes the revised SRD's classes, skills, feats, spells,
equipment, magic items, combat, exploration, environments, traps, treasure,
monsters and monster-building rules. This includes optional epic material,
explicitly titled **Epic Levels**. Downloaded sections remain available offline.
Downloading an updated copy of the same source and section replaces that
document and its search passages atomically.

Downloads are restricted to exact, listed 3.5 section URLs on `www.d20srd.org`
and `www.darkshire.net`. Redirects outside this list are rejected before they are
followed. This downloader does not crawl either site or fetch arbitrary URLs,
5e content, Pathfinder content, books, images or model files. A curated page may
become unavailable; another listed section or a local import can still be used.

## Importing local documents

**Import Document…** accepts UTF-8 `.txt`, `.md`, `.html` and `.htm` files, up to
4 MiB each. Enter the document title, section, source URL and version before
committing the import. The import is labelled as user-supplied D&D 3.5 material.
Edition declarations and known 5e/Pathfinder source URLs are checked; the app
cannot independently establish the edition of an arbitrary local file.

HTML is converted to plain text using Python's standard library. Scripts,
styles, forms, navigation and embedded frames are discarded. HTML is never
rendered or executed. The source file is not changed. A PDF can first be
converted to a UTF-8 text file using an existing document extraction tool; PDF
parsing is not an app dependency.

The compendium is intended for SRD references and the DM's own campaign rules.
No proprietary sourcebook corpus is included in this repository or installer.
Imported house rules remain labelled local imports instead of being attributed
to the SRD.

## Provenance and storage

`RulesRepository(path)` uses a separate `rules.sqlite3` file beside the main
library. It stores canonical document text, bounded passages and:

- Source and document titles, URL, edition, document identifier and section.
- Source version as supplied, or an explicit note that the web page supplies no
  revision identifier.
- Import time in UTC, origin and SHA-256 of canonical text.
- SHA-256 of original downloaded/imported bytes when available.
- The OGL reference URL and original SRD copyright notice for curated downloads.

The canonical-text digest describes what is actually searched; the original-file
digest identifies the fetched/imported bytes before conversion. Neither digest
is a claim of publisher authenticity. Authored summaries have a canonical digest
and no downloaded-file digest.

SQLite FTS5 ranks matching title/section/body text when available. A ranked,
case-folded plain SQLite search provides a fallback on builds without FTS5.
Queries are bounded and converted to literal words rather than accepting SQL or
FTS operators. Search results are limited to 50 passages per call, 20 in the UI.
`rebuild_index()` recreates the FTS index from the retained canonical documents
without downloading anything. Keep the entire rules database when backing up
imported material; deleting it also deletes canonical imports, even though the
starter summaries can be recreated.

The compendium does not change the main creature-library database schema.

## Source research and content notices

Source links checked on 2026-10-22:

- [Wizards' legacy revised SRD page](https://www.wizards.com/D20/article.asp?x=srd35)
  now redirects to the Wizards corporate site. The
  [historical archive URL](https://archive.wizards.com/default.asp?x=d20/article/srd35)
  was inaccessible during verification. These are recorded for historical
  provenance rather than offered as working download endpoints.
- [The Hypertext d20 SRD](https://www.d20srd.org/index.htm) identifies its core
  reference as version 3.5 and labels its rules-page text as Open Game Content
  under [Open Game License v1.0a](https://www.d20srd.org/extras/d20/ogl.html).
- [Darkshire's revised SRD HTML index](https://www.darkshire.net/jhkim/rpg/srd/srd_revised_html/index.html)
  identifies its documents as revised v3.5 and links the original RTF source.
  Its [legal information](https://www.darkshire.net/jhkim/rpg/srd/srd_revised_html/Legal.html)
  reproduces the original content designation and license notice.

Only original concise summaries and source links are bundled here. Downloaded
SRD text stays in the user's rules database, with the source notice and license
reference preserved. The original legal notices distinguish Open Game Content
from reserved names and other Product Identity; this feature does not import
publisher artwork or imply publisher affiliation. Redistribution of an imported
corpus is a separate content-publishing step and should retain its applicable
license and notices.

The curated-download attribution stored with each SRD source is:

> System Reference Document Copyright 2000-2003, Wizards of the Coast, Inc.; Authors
> Jonathan Tweet, Monte Cook, Skip Williams, Rich Baker, Andy Collins, David Noonan,
> Rich Redman, Bruce R. Cordell, John D. Rateliff, Thomas Reid, James Wyatt, based on
> original material by E. Gary Gygax and Dave Arneson.

## Development interface

`RulesRepository` provides `import_document`, `import_file`, `fetch_source`,
`search`, `get_document`, `list_documents` and `rebuild_index`. `RulesDocument`
retains full canonical text; `RuleHit` includes a bounded passage, snippet,
ranking and source metadata. The `passage` property aliases `RuleHit.text`.

`RulesReferenceDialog(reference_store, parent=None)` emits
`context_requested(str)` only after **Use in Scribe**. `build_rules_context`
creates source-labelled evidence from explicitly supplied results and rejects
oversized context rather than dropping citations or truncating exceptions. The
maximum handoff is 6,000 characters.

Focused verification:

```sh
.venv/bin/python -m unittest tests.test_rules_reference tests.test_rules_ui -v
```

Tests cover offline starter content, literal search, ranking, non-FTS fallback,
canonical/raw digests, idempotent import, transactional rollback, HTML conversion,
edition/source filtering, bounded downloads, redirect rejection, explicit UI
actions and citation handoff. A live single-section fetch of **The Basics** was
also verified on 2026-10-22, followed by offline search, in a temporary database.
