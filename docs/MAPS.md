# Campaign map desk

Open the Cartographer's Desk for the active campaign. Import a local PNG, JPEG,
WebP, or BMP map. The application copies its original bytes into the library's
`assets/maps/` folder under a generated ID; moving or deleting the source file
does not affect the imported map. The DM can rename the map in the desk.

New maps start fully hidden from the player view. The DM sees a translucent
fog overlay so unexplored areas remain available for planning. Choose **Reveal /
Conceal Cells**, then click grid cells to toggle their revealed state. **Reveal
Entire Map** disables fog; **Hide Entire Map** restores fog and clears all
revealed cells. Changing grid size also clears individual reveals, preventing
old cell coordinates from exposing a larger region accidentally.

Use the mouse wheel to zoom, drag empty space to pan, and choose **Fit Map** to
frame the image. Set **Distance per grid cell** and the unit label to calibrate
the map; the default is 5 ft per grid cell. Choose **Straight-line Ruler**, then
drag between two points. Both the drawn ruler and its result show the configured
units. Measurements use straight-line geometry; they do not calculate D&D's
diagonal movement cost or movement around obstacles. **Clear Ruler** removes the
temporary measurement. Calibration is saved with the map; ruler lines are local
to the DM's current view.

Tokens start visible only to the DM. Drag a token to move it;
grid snapping is optional. Select a token in the list or canvas to change its
player visibility or remove it. Positions, grid settings, visibility, and fog
save automatically after changes. Token dragging saves once on mouse release.

**Add Encounter Token** offers saved fighter instances from this campaign's
session encounters. The current encounter is preferred when it belongs to this
campaign. A linked marker stores the encounter ID and fighter instance UUID;
moving or changing its map visibility does not modify the encounter, character
sheet, creature template, HP, or initiative. A fighter can have one linked marker
on each map. **Unlink Selected Token** retains the marker as an independent
token. If its saved fighter or encounter is later removed, unlink or remove the
marker before saving further map changes. **Unlink All Encounter Tokens** keeps
all markers while clearing their links, including when several saved fighters
have been removed together.

**Add Note** creates a private annotation. Drag notes to place them, select a
note to edit or remove it, and use **Selected note visible to players** only when
its contents should be public. Notes remain private unless explicitly shared;
shared notes must also stand in a revealed cell while fog is enabled. Annotation
text is plain text. The scrollable tool pane keeps all tools available in compact
windows.

Automatic saves compare the editor's loaded state with the current stored state.
If another window changed the map, the stale save is rejected and the status
reports that it was not saved. Use **Reload Map** to review the current state
before making more changes.

**Open Player View** opens a separate local window suitable for a second display
or a shared window capture. It displays revealed map areas and tokens that the
DM marked visible and that stand in revealed cells. Hidden and unexplored token
labels and private annotation objects are removed before public scene items are
created. Encounter references are also stripped from the public state. Hidden
source pixels are replaced with opaque black before a public image or pixmap is
constructed; fog overlays provide an additional display mask. Live updates copy
newly revealed pixels from the DM desk's source image. The player window
does not include the DM's map title, campaign title, source filename, controls,
or campaign notes. It has no map editing controls. Closing or dismissing the DM
desk closes its player window.

The desk is a local tabletop display. It does not create a network game, infer
line of sight, calculate movement costs, or replace combat rules. Grid size is
measured in image pixels; saved calibration determines the game distance
represented by a cell.

## Storage and limits

Map metadata and validated state are stored in schema 5's `maps` table, scoped
to a campaign. Images use relative paths such as
`assets/maps/<map-id>.png`; absolute paths, traversal, foreign filenames, and
symbolic links outside managed assets are rejected. Import rejects unreadable
content, unsupported formats, files larger than 25 MB, edges larger than 10,000
pixels, and images containing more than 40 million pixels. Decoded dimensions
are checked before the full image is read. Failed database inserts remove their
staged image files.

Each map supports 250 tokens, 250 annotations, 20,000 individually revealed cells, and a maximum
1 MB state document. Grid edges range from 16 to 512 pixels. Token positions
must be finite and inside the image. Saving a map never modifies a creature
record, campaign journal, or another campaign's map. Linked encounters and fighter
UUIDs are checked against this campaign's saved encounter roster during the same
transaction that saves the map.

Map state uses version 2. Existing version 1 maps load with 5 ft calibration and
an empty annotation list, retaining their grid, fog, and tokens. Saving writes
version 2 so older applications reject the expanded state rather than silently
dropping new metadata. Unknown future versions and malformed state are rejected.

Use a complete backup that includes both the SQLite library and its sibling
`assets` folder. A database-only copy preserves map state but does not include
image bytes. Missing images are reported without deleting their saved map
metadata.

## Integration

`MapDeskDialog(library, campaign_id, parent=None)` opens the desk, where `library`
is an initialized `CreatureRepository`. `MapRepository(library)` provides
`import_image`, `list`, `get`, `image_path`, `load_image`, `save_state`, and
`rename`, and `encounter_actors`. Pass `campaign_id=` to `get`, `save_state`, and
`rename` when handling an explicitly selected campaign. Pass `expected_state=` to
`save_state` to reject stale edits atomically; the desk always supplies its loaded
baseline. `MapConflictError` reports a conflict. `map_distance` returns calibrated
straight-line distance. `player_map_state` returns an explicit public field
allowlist, and `player_map_image` copies only revealed pixels into an opaque
public image. `PlayerMapWindow.update_map(image, state)` accepts the current DM
source and refreshes its public canvas without retaining private source pixels.

Tests cover persistent imports and state, campaign isolation, invalid image and
state rejection, path confinement, rollback cleanup, grid changes, automatic UI
saving, calibrated ruler dragging, annotation dragging and visibility, encounter
actor ownership and template isolation, optimistic save conflicts, redacted
source pixels, public object filtering, compact layout, and player-window
lifecycle. Only the focused map tests are required for this packet.
