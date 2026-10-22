# Reviewed Scribe drafts

The Reviewed Drafts desk applies text only after the DM reviews a complete
replacement. Select a saved session or world entry in the chosen campaign, then
choose the field. Session notes and private world notes are the defaults. Paste
or write a draft, or explicitly open the existing local Scribe and retrieve its
editable result. Opening the desk or Scribe does not start inference.

Click **Prepare Before / After Review** to inspect the exact saved text and exact
replacement, including the planning label or recap source appendix. Check the
field and click **Apply Reviewed Field** to commit. Summary and handout player
text also require a separate confirmation that the complete public text contains
no DM secrets. Public Scribe context contains only that selected public field
and the editable request, never the entry's private notes, title, or metadata.
Player text is saved only in the handout's explicit `player_text` field; the
existing player export continues to use its allowlist.

## Recaps and recorded evidence

Recaps require selected saved evidence from the same session's notes or named
encounter logs. Inspect the full excerpts and explicitly confirm that they
describe recorded outcomes rather than plans. Notes are not automatically
classified as facts. Saved planning drafts from this desk carry a visible
`[REVIEWED PLAN / PROPOSAL - not a recorded event]` label and are excluded from
recap evidence. Scene preparation, rosters, session status, earlier recaps, and
other sessions' records are not offered as evidence.

Use **Insert Checked Evidence Citations** to insert the selected stable
`[E-…]` identifiers. Every recap paragraph must cite selected evidence; unknown
identifiers are rejected. The saved recap retains the cited source text, source
ID, excerpt number, and digest in a DM-reviewed source appendix. This makes the
support inspectable even if source notes are later edited. Selected notes and
combat logs can themselves contain errors or plans. Citation checking cannot
establish that prose is true or that every claim follows from the source: the DM
must review those claims before applying the recap.

## Persistence and limits

The desk takes an immutable snapshot and SHA-256 digest of the complete selected
row. Apply starts one SQLite write transaction, rereads that target and selected
recap sources under the same lock, rejects stale or foreign data, then updates
only selected allowlisted text fields. A SQL or validation failure rolls back
the write and keeps the editable draft. Reload Saved Target retains its text but
requires a new review. Changing targets or fields asks before discarding an
unsaved draft. Public confirmation is cleared whenever draft text changes.

Allowed session fields are `notes` and `recap`. Allowed world fields are
`dm_notes`, `summary`, and, for handouts only, `player_text`. Names, statuses,
relationships, typed numeric details, campaign ownership, character sheets,
rewards, dice, and active encounter state cannot be changed through this API.
World and session planning fields retain their visible proposal label.

Drafts are held in memory until applied or copied elsewhere. There is no new
database table or migration. The saved text carries its planning classification
or recap provenance; this feature does not introduce a separate durable draft
audit log. The existing Scribe still supports saving a text draft to a file.
At most 100 evidence excerpts may support one proposal. Recaps and private notes
are bounded to 100,000 characters, summaries to 20,000. Scribe context remains
bounded to 6,000 characters and is rejected instead of silently truncated.

## Integration

```python
dialog = ReviewedDraftsDialog(database_path, campaign_id, parent=None)
dialog.load_scribe_draft(text, task="session_plan", session_id=None)
dialog.exec()
```

`load_scribe_draft(text, task='session_plan', session_id=None) -> bool` populates
editable proposed text only. A named session must belong to the dialog's
campaign. Recap tasks select its recap field; other tasks select session notes,
or the selected world's private DM notes when no session is requested. Recap
evidence selection and factual confirmation remain explicit user actions.

`ReviewedDraftsRepository(database_path, campaign_id)` supplies `list_targets`,
`snapshot`, `load_evidence`, `prepare`, and `apply`. `prepare` accepts a dictionary
of several field drafts; `apply(selected_fields=...)` can apply a reviewed subset
in one transaction. The standalone dialog presents one complete field at a time.

Focused checks:

```sh
QT_QPA_PLATFORM=offscreen .venv/bin/python -m unittest tests.test_reviewed_drafts tests.test_reviewed_drafts_ui -v
```
