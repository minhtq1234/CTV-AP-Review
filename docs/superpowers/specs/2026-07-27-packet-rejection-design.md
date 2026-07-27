# CTV v1 Packet-Level Rejection Design

**Date:** 2026-07-27  
**Status:** Approved product design; pending written-spec review

## Goal

Add an explicit overall-packet rejection path to the historical CTV v1 reviewer.
A reviewer can reject a packet for one or more document-level reasons without
discarding, locking, or replacing the existing field-by-field review.

This work is confined to:

`/Users/lap16603/Documents/New project/work/CTV_APReview-v1`

The v2 checkout at
`/Users/lap16603/Documents/New project/work/CTV_APReview` is out of scope. V1
continues to use frontend port 5174 and backend port 8001. The current uncommitted
v1 review-layout work and the intentional `src/upload/api.ts` port change are the
baseline and must be preserved.

## Non-Goals

- No new rejection reasons beyond the three approved choices.
- No attachments, messaging, resubmission workflow, history, audit log, or user
  attribution.
- No change to field ranking, evidence focus, document modes, field flags,
  keyboard shortcuts, or the existing field-level report entries.
- No automatic movement to the next packet.
- No lock on a rejected packet or its detailed fields.
- No changes to processed packet manifests or OCR data.

## Data Model and Invariants

The existing review model is extended additively:

```ts
type PacketRejectionReason =
  | 'missing_documents'
  | 'wrong_template'
  | 'missing_signature'

interface PacketRejection {
  reasons: PacketRejectionReason[]
  note: string
}

interface PacketReview {
  done: boolean
  fields: Record<string, FieldReview>
  rejection: PacketRejection | null
}
```

Reason codes have fixed Vietnamese labels and fixed display/report order:

| Code | Label |
| --- | --- |
| `missing_documents` | `Thiếu chứng từ` |
| `wrong_template` | `Chứng từ không đúng mẫu` |
| `missing_signature` | `Thiếu chữ ký` |

The following invariants apply in the frontend, endpoint validation, store, and
derived helpers:

1. `rejection: null` means the packet has no overall rejection.
2. A non-null rejection contains at least one reason. Duplicate or unknown reason
   codes are invalid.
3. Reasons are persisted and displayed in the canonical order above, regardless
   of click order. The optional note is stored as a string; surrounding
   whitespace is trimmed and an empty note is stored as `""`.
4. A non-null rejection forces `review.done = true`.
5. A rejected packet counts as completed and as `cần gửi lại`.
6. Rejection takes priority in derived packet status. A rejected packet is
   `needs_resubmit` even if it has no field flags and its roster match is strong.
7. Rejection does not alter `review.fields`. Field reviews remain visible,
   editable, and persist normally while the rejection is active.
8. Undo sets `rejection: null` and recomputes `done` as
   `allSeen(review, fieldKeys)`. It does not reuse the rejection-forced `done`
   value and does not remove or rewrite any field review.
9. Normal completion without a rejection continues to require every detailed
   field to be seen.

## Persistence and Migration

The existing endpoint remains:

`PUT /api/cases/{caseId}/packets/{index}/review`

Its body becomes `{ done, fields, rejection }`. `rejection` is optional at the
wire boundary for backward compatibility and normalizes to `null`. The endpoint
validates the reason codes, requires at least one reason for a non-null
rejection, normalizes reason order and note whitespace, and passes the complete
review object to the store. The store persists:

```json
{
  "done": true,
  "fields": {},
  "rejection": {
    "reasons": ["missing_documents", "missing_signature"],
    "note": "Bổ sung đủ bộ hồ sơ."
  }
}
```

The store enforces `done: true` whenever `rejection` is non-null, even if a
caller sends `done: false`.

Review normalization applies in both packet creation/defaulting and startup
loading:

- a packet with no `review` receives
  `{ "done": false, "fields": {}, "rejection": null }`;
- a packet with an existing `{ done, fields }` review receives
  `rejection: null` without changing its `done` or `fields`;
- a packet already containing `rejection` is preserved after validation and
  normalization.

The load migration is idempotent and writes the additive default back to
`case.json`, so subsequent reads and API responses always expose the complete
shape.

## Review UI

### Entry Point

In the left detailed-field pane, directly below the existing field summary and
above the first field row, show a full-width, prominent outlined-danger button:

`Từ chối gói hồ sơ`

The button remains available whether the normal field review is incomplete or
already complete. Selecting it does not mark any field as seen.

### Create Dialog

Selecting the button opens a compact modal dialog titled
`Từ chối gói hồ sơ`. It contains:

- three checkbox-style multi-select reasons, in canonical order;
- an optional textarea labeled `Ghi chú`;
- `Hủy`;
- the primary danger action `Xác nhận từ chối`;
- an inline message area for validation or save errors.

Multiple reasons may be selected. Submitting with no selected reason makes no
API call, keeps the dialog open, and shows
`Chọn ít nhất một lý do`. `Hủy` closes the dialog without changing or saving
the review.

While a save is running, the primary action is disabled and shows a saving
state. On success, the dialog closes, the current packet stays open, and no
previous/next navigation callback runs.

### Persistent Rejected State

After a successful save, the entry-point button is replaced by a persistent red
summary above the detailed fields. The summary contains:

- the heading `Đã từ chối`;
- every selected Vietnamese reason label in canonical order;
- the optional note when non-empty;
- the action `Sửa lý do`.

This summary is derived only from the last successfully persisted review. The
detailed field list and all field interactions remain enabled. The bottom action
bar may show the packet as completed, but must not cover or replace the rejection
summary.

### Edit and Undo

`Sửa lý do` opens the same dialog seeded from the persisted rejection. In edit
mode:

- the title is `Sửa lý do từ chối`;
- the primary action is `Lưu thay đổi`;
- validation rules are identical to creation;
- `Hủy` discards unsaved edits;
- a separate action `Hoàn tác từ chối` is available.

Saving edits replaces the prior rejection atomically. It never appends a second
rejection or creates duplicate reasons.

`Hoàn tác từ chối` persists a candidate review with `rejection: null` and
`done: allSeen(review, fieldKeys)`. On success the dialog and red summary close.
All `review.fields` entries, including seen state, flags, reasons, and notes,
remain unchanged. If every field is seen, the packet stays normally complete;
otherwise it returns to the appropriate incomplete state.

## Save Ordering and Error Behavior

The review endpoint accepts the full packet review snapshot, so writes for one
packet must be serialized in issue order. The existing field-review autosaves
and the new create/edit/undo operations share one per-packet save queue. This
prevents a slower earlier field save from overwriting a later rejection save.
Every queued operation captures its case ID, packet index, and complete review
candidate.

Field edits may retain their existing optimistic presentation. Packet rejection
create, edit, and undo are transactional:

- the UI does not publish the candidate rejection state until its save succeeds;
- create failure leaves the packet unrejected;
- edit failure leaves the previous persisted summary unchanged;
- undo failure leaves the packet rejected;
- the dialog remains open with the user's current selections/note;
- an inline retryable error `Không lưu được. Vui lòng thử lại.` appears;
- the primary or undo action can be retried;
- no global error screen replaces the review for these dialog operations.

Opening another packet resets the queue context; pending writes retain the case
ID and packet index they captured and must not apply their response to a
different packet's local state.

## Derived Status and Submission Summary

The client helpers and server helpers use the same precedence:

1. If `review.rejection` is non-null, the packet needs resubmission.
2. Otherwise, existing field flags or weak identity matching
   (`name`/`unmatched`) determine whether it needs resubmission.
3. If `review.done` is false, the packet is `untouched` or `in_review` from
   detailed seen state.
4. If `review.done` is true, the packet is `needs_resubmit` or `clear`.

Because a rejection forces `done: true`, its packet card displays
`Xong · cần gửi lại`. Server `progress.done` includes it, and
`progress.flagged` plus the case-detail `cần gửi lại` count include it exactly
once even when the same packet also has field flags or a weak identity match.
The existing count of `trường có vấn đề` remains field-flag-only; a packet
rejection is not a field.

## Report Model and Rendering

The structured report group is extended additively:

```ts
interface PacketRejectionReportEntry {
  reasons: PacketRejectionReason[]
  reasonLabels: string[]
  note: string
}

interface ReportGroup {
  // existing identity and field-item properties
  packetRejection: PacketRejectionReportEntry | null
  items: ReportItem[]
}
```

The report builder creates at most one `packetRejection` entry per packet,
directly from `review.rejection`. It remains separate from `items`, which
continue to represent field flags. A rejected packet is included even if it has
no field items and no identity issue.

Rendering order inside each CTV group is:

1. existing group heading;
2. packet-level rejection entry, when present;
3. existing identity warning, when present;
4. existing field-level items, unchanged.

The Markdown packet entry starts with `Từ chối gói hồ sơ`, lists all selected
Vietnamese reason labels, and includes `Ghi chú: …` only when the note is
non-empty.

The CSV contains one packet-level row before the packet's field rows. It uses
`Từ chối gói hồ sơ` in the existing `Trường` column, leaves field-specific
document/page/value columns empty, joins the Vietnamese reason labels with
`; ` in `Lý do`, and places the optional note in `Ghi chú`. Existing identity
and field rows keep their current behavior.

Separating `packetRejection` from `items` prevents duplication in the structured
JSON, Markdown, and CSV.

## Components and Responsibilities

- `src/upload/api.ts`: additive rejection and report types, backward-compatible
  review normalization for API reads, and rejection-aware client
  `packetNeedsResubmit`.
- `src/logic/review.ts`: rejection-first packet status and the normal
  all-fields-seen derivation used by undo.
- `src/components/PacketRejectionDialog.tsx`: local draft selections/note,
  create/edit labels, validation, saving state, inline errors, and undo action.
- `src/components/FolderReview.tsx`: candidate review construction, undo
  completion derivation, and placement above the detailed field list.
- `src/components/FolderFieldsPanel.tsx`: renders either the outlined rejection
  entry point or the persisted red summary before field rows; field behavior
  remains unchanged.
- `src/components/UploadFlow.tsx`: serializes full-review saves, distinguishes
  ordinary optimistic autosaves from transactional rejection mutations, and
  updates packet metadata only for matching case/packet responses.
- `server/app.py`: backward-compatible nested request validation.
- `server/cases.py`: additive defaults/migration, persistence invariants,
  completion/progress, and needs-resubmission derivation.
- `server/report.py`: one structured packet rejection entry and its
  Markdown/CSV rendering before existing problems.

File boundaries may be adjusted during the implementation plan if the current
layout offers an equally isolated existing component, but the state ownership,
transactional behavior, and data contract above must not change.

## Accessibility and Interaction Details

- The dialog uses semantic dialog labeling, moves focus inside when opened, and
  restores focus to the opening action when closed.
- Escape behaves like `Hủy` when no save is running.
- Reason controls expose checked state and can be operated by keyboard.
- Saving disables dialog dismissal that could conceal an in-flight result.
- Danger styling is not the only state cue: visible text always communicates
  `Từ chối` or `Đã từ chối`.
- Existing review hotkeys do not fire while focus is in the dialog, checkbox,
  button, input, or textarea.

## TDD and Verification

Implementation begins only after this written spec is approved. The
implementation plan must order work so each behavior is first demonstrated by a
failing focused test.

### Backend Tests

- packet defaults and creation include `rejection: null`;
- startup migration adds `rejection: null` to an existing `{ done, fields }`
  review without changing field data;
- full rejection persistence round-trip with multiple reasons and optional note;
- endpoint validation rejects an empty or unknown reason list;
- a rejection forces `done: true`;
- rejection counts as completed and needs resubmission exactly once;
- undo persists `rejection: null` and preserves fields;
- report structured data, Markdown, and CSV contain one packet-level rejection
  before identity/field issues with all Vietnamese labels and optional note;
- existing field-flag report tests remain green.

### Frontend Tests

- legacy API review data normalizes to `rejection: null`;
- create dialog opens, supports multiple reasons and an optional note;
- submitting no reason shows validation and performs no save;
- cancel performs no save;
- successful rejection stays on the current packet and publishes the red
  persisted summary;
- save failure keeps the dialog open, shows an inline retry path, and publishes
  no false rejected state;
- edit is seeded, saves a replacement once, and does not duplicate reasons;
- undo preserves fields and derives `done` from all fields seen;
- failed undo retains the rejected summary;
- rejected packets remain fully field-editable;
- packet status, case completion, and needs-resubmission helpers give rejection
  priority;
- normal completion without rejection still requires all fields seen;
- report client types/rendering accept the additive packet entry.

### Full Verification

- run the full frontend Vitest suite;
- run the full backend pytest suite;
- run the production frontend build;
- run `git diff --check`;
- confirm only the v1 checkout changed and the 8001 API base remains intact.

### Browser QA

At `http://127.0.0.1:5174/`, using only local synthetic or already-present data
without recording or copying PII:

1. Open a packet and reject it with multiple reasons plus a note.
2. Confirm the packet stays open and shows the red persisted summary.
3. Edit a detailed field while rejected and confirm it remains editable.
4. Reload and confirm rejection reasons, note, and field work persist.
5. Edit the reasons/note and confirm the summary replaces rather than
   duplicates the rejection.
6. Undo the rejection and confirm field work remains and normal completion is
   recalculated.
7. Verify the generated report places the packet rejection before field issues.
8. Check browser console and page errors throughout.

## Self-Review Checklist

- The design contains no placeholders or deferred product choices.
- The storage change is additive and explicitly covers both missing reviews and
  existing reviews missing only `rejection`.
- Create, edit, cancel, validation, retry, undo, and reload behavior are
  specified.
- Rejection-forced completion and undo-derived normal completion do not
  contradict each other.
- Rejected packets stay editable; field work is never deleted.
- Save ordering prevents full-snapshot autosaves from overwriting rejection
  changes.
- The report has one dedicated packet entry before existing problems and cannot
  duplicate it through field items.
- V1-only scope, ports, unrelated dirty work, no-push constraint, and PII safety
  are explicit.

