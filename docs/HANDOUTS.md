# Player handout illustrations and export

Create and save a **Player handout** in **World & Campaign Desk** first. Write
exactly what players should receive in its **Player text** field. Then open
**Player Handout Gallery**, choose that saved handout, and attach a PNG, JPEG,
or WebP illustration. The gallery keeps several images per handout, with one
image selected for player output. A newly attached image is selected. Highlight
another image and press **Use Selected Image** to replace it, or **Use Player
Text Only** to omit illustrations. The list marks the saved selection with
**[For players]**. Highlighting another row alone does not change that selection.

**Review Player Preview** opens the exact public snapshot: only Player text and
the selected sanitized illustration. The handout's name, campaign name, summary,
DM notes, relationships, private identifiers, source filename, and managed path
are excluded. Text is plain text and cannot execute HTML. An image-only handout
is supported; a completely empty handout is refused. **Open Reviewed Player
Display** opens a separate window for a second monitor or window capture, with
the same public content and no DM editing controls.

**Export Reviewed Handout ZIP** writes that same reviewed snapshot as generic
`handout.txt` and optional `image.png`. It adds no manifest, original filename,
private metadata, or author timestamp. The text and PNG bytes match the preview
payload exactly. Display/export deliberately use the last reviewed snapshot;
refresh and review again after editing the World Desk. Changing the handout or
image, archiving, or refreshing invalidates the previous review and closes its
public windows. Closing the gallery closes both preview and display windows.

Imports leave the source file untouched. A decoded raster is painted into a
fresh image and saved as PNG in `assets/handouts/<generated-uuid>.png`, stripping
source text, EXIF, filename and profile metadata. Transparency is preserved.
For animated source files, only the first decoded raster frame is imported.
Imports accept at most 25 MB, 8,192 pixels per edge, and 16 million pixels total;
the resulting sanitized PNG must also fit the 25 MB limit. Dimensions are
checked before decoding. Invalid or failed imports leave the previous selection
and managed files intact. Archiving retains the asset file, clears its player
selection, and supports restoration. Restored images require explicit selection.

The gallery refuses assets with unsafe paths, symbolic links, missing files,
changed checksums, or inconsistent dimensions. Export refuses the active library,
rules database, SQLite journals, standalone scene/battle files, offline spell
reference, and managed assets. A failed export preserves an existing destination.

## Integration and recovery

Open `HandoutGalleryDialog(library_repository, campaign_id, parent=None)`.
`HandoutRepository(library_repository)` owns attachment management and creates
`PublicHandout(text, image_png)` snapshots through `public_payload(campaign_id,
handout_id)`. `export_payload(snapshot, destination)` exports exactly that
snapshot. `PlayerHandoutWindow(snapshot, parent=None, preview=False)` receives
only public data. The gallery emits `assets_changed()` after attachment changes.

`handouts.ensure_schema(db)` executes the exported `SCHEMA_SQL` inside the
integrator's central migration. The repository safely invokes the same
`IF NOT EXISTS` hook without changing the schema-version pragma. Attachments
live in the main SQLite library's `handout_assets` table, linked to a saved
handout in the same campaign; their images live in managed assets. Complete
backups include active and archived files. A database-only backup has attachment
metadata but cannot restore image bytes.

`handouts.validate_saved_state(library_repository_or_path)` uses a read-only
SQLite connection and checks all attachment flags, types, campaign/handout
references, paths, image checksums, decoding and dimensions, including archived
images. It never repairs, normalizes or overwrites saved data. Recovery should
call it on a staged copy before publishing that recovered library.
