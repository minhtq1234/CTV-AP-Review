# CTV v1 Packet Overview Review Design

**Date:** 2026-07-27
**Status:** Approved interaction design; pending written-spec review

## Goal

Add a clean packet-level Overview to the historical CTV v1 reviewer so a
reviewer can scan the documents before beginning field-by-field verification.
The Overview separates two distinct tasks:

1. deciding whether the document package is complete and credible enough to
   review; and
2. comparing individual roster fields with focused document evidence.

Every packet opens on Overview. Overview presents one document at a time at
100% zoom in the existing two-page layout, without bbox highlights or roster
value callouts. A reviewer can reject an obviously invalid packet from this
screen or continue into the existing detailed-field workflow.

This work is confined to:

`/Users/lap16603/Documents/New project/work/CTV_APReview-v1`

The v2 checkout at
`/Users/lap16603/Documents/New project/work/CTV_APReview` is out of scope. V1
continues to use frontend port 5174 and backend port 8001. No work is pushed.

## Design Rationale

The current screen selects the first ranked field as soon as a packet opens.
That immediately adds field-focused overlays and marks the first field as seen,
even when the reviewer only intends to inspect the document package as a whole.
The large packet-rejection button also competes visually with the documents.

Overview creates a deliberate review flow:

`Clean packet scan → early rejection if necessary → detailed field checks → Xong`

The clean scan reduces field-level tunnel vision, avoids counting a field as
reviewed merely because the packet opened, and keeps rejection available without
making it the dominant first action.

## Approved Scope

### In scope

- A virtual Overview row before the detailed fields.
- Overview as the initial selection whenever a packet is opened or reopened.
- A clean, tabbed, one-document-at-a-time viewer preset.
- A smaller packet-rejection action inside the Overview area.
- Existing rejection create, edit, undo, persistence, report, and status
  behavior.
- Existing detailed-field focus, seen tracking, flags, completion, report, and
  packet lifecycle behavior.

### Out of scope

- Rendering every document in one continuous cross-document scroll.
- A new accept endpoint or a direct accept action from Overview.
- Marking Overview as seen, completed, accepted, or rejected.
- Persisting Overview selection, document position, zoom, view mode, or scroll.
- Adding Overview to field counts, progress counts, packet statuses, or reports.
- Changing processed manifests, OCR data, roster data, comparison results, or
  saved review shapes.
- Changing packet navigation, case progress, or report semantics.
- Changing v2.

## Left Review Panel

The large full-width `Từ chối gói hồ sơ` button is removed. In its place, the
left panel renders a normal selectable row before the first ranked data field:

- primary label: `Tổng quan`;
- secondary description: `Xem nhanh toàn bộ chứng từ`;
- compact outlined-danger action: `Từ chối hồ sơ`.

The Overview row uses the same selected-row treatment as a data field so the
reviewer can understand which viewer mode is active. It is a virtual
presentation item, not a `CtvField`.

The existing summary remains based only on real ranked fields:

- `N mục kiểm tra` excludes Overview;
- `N/N đã xem` excludes Overview;
- selecting Overview never changes a field's `seen` value.

When `review.rejection` is non-null, the Overview area replaces the compact
create action with the existing persisted rejection summary:

- `Đã từ chối`;
- selected reason labels in canonical order;
- the optional note;
- `Sửa lý do`.

The detailed fields remain visible and interactive below the summary, matching
the existing rejection behavior.

## Initial and Re-entry Behavior

Opening or reopening any packet selects Overview, including packets that are
incomplete, completed, flagged, or rejected. Packet open must not call
`onReview`, enqueue a review save, or mark the first ranked field as seen.

Every time Overview is selected, it resets to the cheapest predictable preset:

- the first document in the existing manifest order;
- page one as the active page;
- `2 trang` view mode;
- 100% zoom;
- no bbox focus;
- no roster-value callout;
- no automatic field-focus scroll.

Overview does not preserve a separate document, zoom, or scroll history. Manual
viewer changes made after the reset remain usable until the reviewer selects
Overview again or leaves the packet.

## Document Viewer

Overview reuses the existing document tabs and page renderer. It does not add a
second viewer or a cross-document document model.

While Overview is selected:

- the active document's complete page list is rendered in the existing
  two-page rows;
- every document tab remains clickable;
- selecting a document tab opens page one of that document without introducing
  a bbox or roster callout;
- native vertical scrolling remains available;
- zoom, fit, one-page/two-page selection, pan, view lock, and keyboard-help
  controls remain available;
- field overlays are suppressed regardless of the current highlight and roster
  toggle values.

Suppressing overlays is presentation-only. It does not overwrite the user's
highlight or roster-toggle preferences. When a real field is selected, the
existing source focus, bbox highlight, roster-value callout, autofocus, and
document/page selection resume.

The selected field may remain in either one-page or two-page mode after leaving
Overview. Autofocus continues to choose an appropriate zoom for the bbox using
the current view mode. The design does not maintain a separate field-view mode,
which avoids additional state and preserves the existing manual controls.

## Selection and Keyboard Navigation

Review selection is represented explicitly as either:

- Overview; or
- a real field key plus the existing source index.

A sentinel string that could collide with a manifest field key is not used.

Selecting a real field:

1. marks only that field as seen using the existing review update path;
2. selects its first source;
3. activates its source document and page;
4. restores the bbox and roster callout presentation.

Selecting Overview performs only the presentation reset and creates no review
write.

Overview participates in vertical review navigation:

- Arrow Down from Overview selects the first ranked field.
- Arrow Up from the first ranked field returns to Overview.
- Arrow Up while Overview is selected does nothing.
- The existing field-to-field Arrow Up/Down behavior remains unchanged.
- Arrow Left/Right while Overview is selected does nothing; document tabs are
  the Overview document-navigation control.
- Existing Arrow Left/Right source navigation remains unchanged for real
  fields.

Field flag shortcut `F` has no effect while Overview is selected because
Overview is not flaggable. Viewer shortcuts and manual viewer controls remain
available.

## Completion and Rejection

Overview does not provide a direct accept action. Normal acceptance remains the
existing bottom `✓ Xong` action and still requires every real detailed field to
be seen.

The action bar continues to display real-field progress while Overview is
selected. It remains disabled until the existing `allSeen(review, fieldKeys)`
condition succeeds.

The compact `Từ chối hồ sơ` action opens the existing rejection dialog. The
dialog's reason validation, optional note, saving state, retry behavior, edit
mode, undo behavior, and serialized review-save ordering remain unchanged.
Rejecting still forces `review.done = true` and has precedence in the derived
packet lifecycle. Overview introduces no new rejection data or write endpoint.

## State and Data Boundaries

Overview state is renderer-local and ephemeral:

- no duplicate display status is persisted;
- no `overview` field is added to `PacketReview.fields`;
- no new property is added to the review API;
- no report item is generated for visiting Overview;
- no case or packet progress is incremented;
- no manifest asset or bbox is altered.

The saved review continues to contain only `done`, real field reviews, and the
optional packet rejection. Existing derived status, attention metadata, case
counts, report generation, and return-to-case behavior continue to consume that
saved review unchanged.

## Component Responsibilities

### `FolderReview`

- Own the explicit Overview-versus-field selection.
- Initialize every packet on Overview without the current first-field
  mount-seed review update.
- Reset active document, page, source index, and bbox when Overview is selected.
- Preserve existing field selection, seen updates, flags, rejection commits, and
  completion handling.
- Guard field-only keyboard actions when Overview is selected.

### `FolderFieldsPanel`

- Render the selectable Overview row before the ranked fields.
- Keep Overview outside field totals and seen counts.
- Render the compact rejection entry point or persisted rejection summary inside
  the Overview area.
- Preserve every existing data-field row and flag editor.

### `EvidenceViewer`

- Accept an explicit Overview presentation state.
- Reset to the approved 100% two-page preset on Overview entry.
- Suppress field overlays and autofocus while Overview is active.
- Keep existing tabs, page rendering, scrolling, toolbar, pan, lock, and help
  behavior.
- Resume existing field-focused behavior without changing saved review data.

### Backend and report code

No changes are expected. Existing backend and report tests are rerun as
regressions.

## Error and Edge Behavior

- Overview itself performs no write and therefore has no save-error state.
- If a packet has documents but no ranked fields, Overview still opens and
  permits document inspection or packet rejection; `✓ Xong` follows the existing
  empty-field behavior.
- If a field has no source, selecting it retains the existing behavior of
  clearing the bbox while keeping the field selected and seen.
- Rejection save failures leave the dialog open and the last persisted rejection
  summary unchanged, as today.
- Reopening a rejected packet starts on Overview and exposes the rejection
  summary without disabling detailed fields.

## Testing

Tests are written and observed failing before production changes.

### Selection and progress

- A packet initially selects Overview.
- Initial render does not call `onReview`.
- The first field remains unseen until explicitly selected.
- Overview appears before the first field.
- Overview is excluded from `N mục kiểm tra` and `N/N đã xem`.
- Selecting a field marks only that field as seen.
- Arrow Down enters the first field; Arrow Up returns to Overview.
- `F` does not flag a field while Overview is active.

### Viewer presentation

- Overview entry selects the first document and page one.
- Overview entry resets view mode to `2 trang` and zoom to 100%.
- No bbox highlight or roster callout renders in Overview.
- No autofocus is scheduled in Overview.
- Document tabs work and keep page one/no-overlay behavior.
- Manual zoom, mode, scrolling, pan, lock, and help controls remain rendered and
  usable.
- Selecting a field restores its source document, page, bbox, roster value, and
  autofocus behavior.

### Completion and rejection

- Overview alone never enables or completes `✓ Xong`.
- Completion still requires every real field to be seen.
- The compact `Từ chối hồ sơ` control opens the existing dialog.
- Rejection summary, edit, undo, validation, retry, and save ordering continue
  to work.
- Rejection and field flags continue to produce the existing flagged lifecycle.

### Regression verification

- Packet dashboard status/count tests remain green.
- Case progress and report tests remain green.
- Frontend test suite passes.
- Backend and splitter test suites pass.
- Production build succeeds.
- `git diff --check` is clean.

## Browser QA

Browser QA runs at `http://127.0.0.1:5174/` with the v1 backend on port 8001 and
uses existing app data without recording or copying PII.

QA covers:

- opening incomplete, completed, flagged, and rejected packets on Overview;
- confirming that opening a packet does not increase the seen count;
- first-document, 100%, two-page reset;
- clean pages with no bbox or roster callout;
- every document tab;
- manual one-page/two-page, zoom, scroll, pan, and lock controls;
- Overview-to-field and field-to-Overview keyboard and pointer navigation;
- field autofocus after leaving Overview;
- compact rejection create/edit/undo flows;
- completion after every real field is seen;
- desktop responsiveness;
- console and page errors.

## Acceptance Criteria

The feature is complete when:

1. every packet opens on a clean Overview without mutating review data;
2. Overview resets to the first document at 100% in two-page mode;
3. document tabs and viewer controls remain usable;
4. field overlays are absent from Overview and return for real fields;
5. the packet rejection action is smaller but retains the full existing
   workflow;
6. Overview does not affect field counts, lifecycle state, reports, or normal
   completion;
7. all focused and regression verification passes in the isolated v1 checkout;
8. v2 remains untouched and no branch is pushed.

## Self-Review

- No placeholders or deferred product decisions remain.
- Overview is consistently presentation-only across interaction, data, status,
  reporting, and testing sections.
- The chosen tabbed approach does not imply a cross-document continuous viewer.
- The 100% two-page requirement is a reset preset, not a restriction on manual
  viewer controls.
- Acceptance and rejection remain distinct: Overview permits early rejection,
  while acceptance still requires all real fields to be reviewed.
- Existing rejection, packet lifecycle, case progress, and report contracts are
  explicitly preserved.
