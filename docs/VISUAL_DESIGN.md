# The Compendium visual design

The desktop application uses obsidian surfaces, crimson actions and selections,
ember borders, and warm parchment text. The existing dragon/d20 banner and the
dragon and Name Genie crests remain the primary fantasy illustrations. The
palette is shared by the stylesheet and native Qt controls, including transient
menus and dialogs.

| Purpose | Color |
| --- | --- |
| Workspace | `#09070a` |
| Panels | `#1a1117` |
| Primary action | `#ad2943` |
| Selected item | `#76243a` |
| Ember ornament | `#ed6276` |
| Main text | `#f1e6d5` |
| Secondary text | `#c3adb8` |
| Keyboard focus | `#f5c985` |

Crimson indicates actions and selections; it is not a validation result by
itself. Keep error messages explicit. Keyboard focus uses a bright gold outline
that remains visible on selected navigation and primary or destructive buttons.
Disabled controls retain readable text. Normal, selected, secondary, tooltip,
and disabled text pairs meet a contrast ratio of at least 4.5:1. A packaged,
original SVG checkmark makes checkbox state visible without relying on color.
Matching vector chevrons make dropdowns and numeric steppers discoverable on
dark backgrounds.

Serif headings use available system fonts, preferring Palatino, Book Antiqua,
Georgia, or Garamond, with Bitstream Charter, DejaVu Serif, and Liberation Serif
as Linux alternatives. Body text uses Segoe UI, Aptos, Noto Sans, DejaVu Sans,
or Arial. Do not bundle proprietary fonts.

The artwork banner keeps its existing crop-to-fill behavior and 166-pixel main
window height. Thin angular corner strokes and small compass-like lozenges are
drawn by Qt over the banner, so they remain sharp on high DPI displays. The
original artwork files and cached image pixels are unchanged. No new downloaded
art or AI-generated raster assets are required by this theme.

The main window dimensions, sidebar width, control spacing, and responsive
square ability tiles are unchanged. Compact windows retain their scrollable
workspace. Future tools should reuse `panel`, `sectionTitle`, `muted`,
`primaryButton`, and `dangerButton` object names to match the application.

Visual QA covers the main window at 1551 × 924 and 895 × 640, campaign/session
management, the naming chamber, and focused, checked, selected, and disabled
controls. Automated regressions verify contrast, native palette coverage,
visible keyboard outlines, checkbox glyphs, artwork loading, banner sizing,
and responsive ability tiles.

Available local graphics tools were confirmed as GIMP 3.0.4 and ImageMagick
7.1.1-43. The current pass uses Qt rendering and an original SVG, preserving
the existing illustration source files without raster editing.
