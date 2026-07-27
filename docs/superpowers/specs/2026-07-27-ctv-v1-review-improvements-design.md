# CTV v1 Review Improvements Design

**Status:** Approved for implementation

## Goal

Improve the historical v1 packet-review screen without changing its field-keyed
review model, ranking, evidence data, persistence contract, processed cases, or
completion/report behavior.

The work is confined to the detached v1 checkout at
`/Users/lap16603/Documents/New project/work/CTV_APReview-v1`. The v2 checkout is
visual reference material only. V1 continues to use frontend port 5174 and
backend port 8001.

## Review Shell

Replace the separate packet navigation bar and expanded identity header with one
sticky, compact top row. From left to right it contains:

- a back-to-case action;
- the eyebrow `HỒ SƠ CTV`;
- the CTV name;
- product and packet page range;
- one mapping-status pill;
- previous packet, current packet position, and next packet controls.

The exact mapping labels are:

- `Khớp theo CCCD`;
- `Khớp theo họ tên`;
- `Chưa khớp bảng kê`;
- `Không có bảng kê`.

The row never renders the OCR-versus-roster identity comparison table. It must
remain usable at normal desktop widths by allowing the identity block to shrink
and truncate while keeping navigation controls reachable.

## Flat Field Panel

Keep the existing ranked field rows, status chips, expected roster value, seen
state, selection behavior, flag editor, and keyboard/source navigation logic.
Remove the repeated per-row `Đối chiếu` source-chip block from the visual panel.
The underlying `field.sources` arrays remain unchanged and continue to drive:

- first-source focus when selecting a field;
- left/right source stepping;
- document-tab selection;
- active document/page changes;
- evidence highlight and roster-value callout.

Each row exposes a larger right-aligned flag button. Inactive copy is
`⚑ Đánh dấu`; active copy is `Bỏ đánh dấu`. The active control uses a strong
warning treatment and continues to open the existing reason/note editor for the
selected field.

## Document Viewer

Expose exactly two manual modes:

- `1 trang`: every page of the active document appears in one vertical column;
- `2 trang`: every page appears in vertically stacked rows, with up to two pages
  side by side in each row.

Both modes use one native vertically scrollable document container. Neither mode
replaces the document with only the current page or current pair. Document tabs
remain above the viewer.

Each page is a relatively positioned surface containing its image and optional
overlays. The selected field's bbox is converted to percentages of its natural
page size, so the highlight remains aligned at every responsive width and zoom.
The roster-value callout remains attached to the same target page. Selecting a
field or source updates the active document/page and scrolls the target page into
view unless view lock is active. Changing document tabs moves to page one when
the selected field has no source in that document.

Zoom changes the rendered document width within the native scroll surface. Fit
returns it to 100%. Pan mode provides click-drag scrolling, while ordinary
wheel/trackpad scrolling remains available. Lock preserves the current scroll
position across focus changes.

## Toolbar

Render one floating, high-contrast white rounded toolbar over the bottom of the
document area. Targets are at least 36 px high, use consistent spacing, and have
visible hover/focus and active states.

All existing v1 tools remain visible without overflow:

- fit;
- zoom out, percentage, and zoom in, visually ordered as `− 100% +` at default;
- highlight toggle;
- roster-value toggle;
- pan toggle;
- view lock;
- keyboard-shortcut help.

Existing shortcuts remain unchanged: field/source arrows, `F`, `B`, `V`,
Option/Alt+`P`, Option/Alt+`−`/`+`, and `?`.

## State and Contracts

No backend payload or saved review shape changes. `PacketReview.fields`, seen
state, flags, `done`, ranking, autosave calls, report derivation, and manifest
assets remain untouched. No local packet content or real PII is copied into
tests, docs, fixtures, screenshots, or source.

The compact shell receives page range and packet-navigation data already present
in the case-detail packet metadata. The offline demo supplies synthetic range and
navigation data through the same presentation component.

## Testing and QA

Focused tests cover:

- exactly two view-mode labels and complete page grouping in both modes;
- percentage overlay geometry and target-page clamping;
- absence of repeated source pills while field selection remains available;
- inactive and active flag labels;
- all four mapping-pill labels and absence of the identity table;
- compact header content and packet navigation states;
- viewer markup containing every active-document page and every toolbar action.

Tests are written and observed failing before production changes. After focused
tests pass, run the full v1 Vitest suite and production build.

Browser QA at `http://127.0.0.1:5174/` covers both scroll modes, field/source
focus, highlight and roster callout, document tabs, flag toggle/editor, compact
header navigation, desktop responsiveness, and console/page errors. QA uses only
the app's existing data and does not record PII in the handoff.

## Self-Review

- No placeholders or deferred decisions remain.
- The two view modes both render the complete active document and differ only in
  page grouping.
- Removing source chips does not remove source data or source-navigation paths.
- The compact header has one mapping pill and no identity comparison table.
- All five approved requirements have an implementation and verification path.
