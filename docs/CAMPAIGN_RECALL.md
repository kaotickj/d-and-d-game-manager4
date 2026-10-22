# Campaign Recall and reviewed Scribe sources

Campaign Recall searches saved evidence for the selected campaign session and lets the DM inspect exactly which excerpts will enter Scribe. It does not generate text, infer missing events, update the campaign, or train a model. Generation remains a separate explicit action using the existing local Scribe setup.

## Search, inspect, preview, load

Open **Campaign Tools → Recall Campaign Sources…** with a saved session selected. The Scribe also offers campaign recall and can prefill its search query from the DM request. Prefilling does not run a search.

1. Choose **DM** or **Player-facing** and enter a query. Search accepts 1–32 words within 240 characters.
2. Choose **Search**. The dialog displays up to 20 matching excerpts with their kind, title, classification, and citation.
3. Select a row to inspect its full text and provenance: source ID, source field, source SHA-256 digest, URL, and version. Text is displayed literally, including any markup in a saved record.
4. Check the excerpts to include, then choose **Preview selected context**. Read the complete context before proceeding.
5. Choose **Load reviewed sources into Scribe**. Acceptance verifies the selection against a fresh search, then loads the reviewed context and its audience. Choose **Generate Locally** separately when ready.

Changing the query or audience clears the previous results, source preview, and context. Changing selected excerpts invalidates the reviewed context. Neither a prefilled query nor editing a control automatically searches, generates, or writes anything.

The source context and optional DM request together must fit Scribe's 6,000-character limit. Complete paragraphs/passages are retained; oversized selections are rejected rather than shortened or silently omitted. Select fewer excerpts or shorten the separate request. The search query itself is not inserted into the source context.

## Which saved evidence is searched

DM recall is scoped to the selected campaign. It can retrieve:

- Campaign description and notes.
- World entries such as NPC references, quests, locations, events, and handouts, including their saved summaries, details, and DM notes.
- The selected session and eligible earlier completed sessions: saved scene preparation, recaps, session-note excerpts, and recorded encounter log lines.
- Saved creature identities and biographies referenced through that campaign's party, world records, or eligible scenes. It does not search every unrelated library creature by name.
- Matching D&D 3.5 passages from the existing local rules database, when one is available.

Retrieval uses explicit saved text and query matches. A prepared NPC does not become present in a scene merely because recall found it. A quest status or calendar entry does not prove an event happened. A recorded engine action does not establish every narrative consequence. Missing or archived referenced records produce an error requiring repair instead of an invented replacement.

Each excerpt carries a classification identifying preparation, DM-supplied notes, recorded encounter actions, recap material, or rules evidence. Proposal-marked session-note paragraphs are excluded. World preparation and other saved material must still be reviewed as preparation or proposals unless the DM has explicitly recorded the outcome. Rules authored as orientation summaries are labeled as such; retrieving one does not make it a complete rule or resolve its exceptions.

## DM secrets and player-facing output

**DM** recall can include private notes, biography fields, encounter logs, and preparation. It is intended for planning, advice, and recap review.

**Player-facing** recall filters permitted fields before query matching and ranking. Private text cannot reveal its presence by producing a match or changing the order of public results. Eligible fields are limited to:

- Explicit public summaries on non-handout world entries.
- A handout's explicit `player_text` field.
- D&D 3.5 rule passages.

Private creature biographies, campaign/session notes, recaps, encounter logs, scene fields, and handout DM text are excluded from player retrieval. World record names are replaced by generic public source titles; player context also uses sanitized public metadata. The context builder independently checks permitted source kinds and fields, so changing only a hit's public flag cannot authorize a private field.

Public summaries and player text must themselves be suitable for players. These are explicit visibility fields, not an AI redaction guarantee. The DM also remains responsible for the separate user-authored request and any manually entered prompt.

Scribe labels loaded source context by audience. Loading player-facing recall selects player narration. Private saved DM sources cannot generate player narration merely by changing the task or editing the context text. To begin a separate public prompt, use **Clear Sources / Write a New Prompt**; this clears both the loaded context and the separate request. A manually authored prompt then requires the DM's own sharing review.

Loading sources keeps any existing generated draft. It neither regenerates nor reclassifies that draft as safe for the new audience. Draft audience is labeled separately, and editable output still requires review before sharing or saving through the existing reviewed-draft workflow.

## Provenance and source freshness

A `MemoryHit` is immutable and records `citation`, `kind`, `source_id`, `field`, `title`, `text`, `digest`, `source_url`, `source_version`, `classification`, and `public`. Context includes stable citation identifiers, source SHA-256 digests, field locations, and available rule URLs/version metadata. Local campaign records are labeled as local saved evidence. These identifiers let the DM inspect the evidence behind an answer; they do not prove that the saved claim is true.

The load action repeats the same bounded search for the same query and audience. Every checked source must still match all its reviewed fields, including its text, citation, and digest. A source edited or removed elsewhere, or no longer present in the current result set, blocks loading. Search failures also block loading. The existing source/context draft remains inspectable; run **Search** and preview again to review the current records.

The context instructs Scribe to treat saved passages as evidence rather than instructions, cite supplied identifiers, distinguish plans from recorded outcomes, and avoid inventing player decisions, awards, dice results, or missing facts. These instructions support review; they do not replace it. No source load authorizes automatic campaign changes.

## Integration contract and storage behavior

The pure retrieval entry point is:

```python
search_campaign_memory(
    campaigns, library, world, rules, session_id, query,
    audience="dm", limit=20,
) -> list[MemoryHit]
```

The context builder is:

```python
build_recall_context(hits, audience="dm", max_chars=6000) -> str
```

Both keyword options are passed by keyword in application code. Retrieval validates audience, session/campaign scope, query, and result limits. The builder accepts 1–20 selected hits and a context bound from 500 through 6,000 characters; it independently validates source metadata and player visibility. Conflicting citations and oversized complete excerpts are rejected.

`CampaignRecallDialog(search_provider, context_builder, parent=None, query='', audience='dm')` receives callbacks rather than opening repositories itself. Only explicit successful acceptance exposes `result_context` and `result_audience`. A caller can reserve room for the separate request by reducing the builder's context budget.

The main-window integration opens an existing rules database in read-only mode and passes no rules repository if that database is absent. Recall does not seed, import, download, train, or modify rules. It does not write campaign data or turn the selected evidence into canonical campaign state. Saving a generated proposal or recorded outcome remains a separate reviewed action.
