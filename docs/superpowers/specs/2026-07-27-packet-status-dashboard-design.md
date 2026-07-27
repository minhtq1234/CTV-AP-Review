# CTV v1 Packet-Status Dashboard Design

**Date:** 2026-07-27  
**Status:** Approved product design; pending written-spec review

## Goal

Turn the v1 case-detail packet grid into a review dashboard whose cards expose
one mutually exclusive reviewer lifecycle, optional system attention, accurate
counts, local status filters, and a reversible attention-first sort.

This work is confined to:

`/Users/lap16603/Documents/New project/work/CTV_APReview-v1`

The v2 checkout at
`/Users/lap16603/Documents/New project/work/CTV_APReview` is out of scope. V1
continues to use frontend port 5174 and backend port 8001. The completed compact
review layout and packet-level rejection behavior remain unchanged.

## Non-Goals

- No new review action, write endpoint, status field, database field, or status
  migration.
- No change to the persisted `PacketReview` shape or to field/rejection save
  ordering.
- No change to case-level completion, progress, resubmission, or report rules.
- No change to packet splitting, OCR, manifest content, review ranking, evidence
  focus, packet navigation, rejection editing, or report export.
- No use of weak roster matches or pipeline warnings as reviewer lifecycle
  states.
- No copying real packet names, identifiers, values, manifests, screenshots, or
  other PII into source, tests, documentation, or QA evidence.

## Chosen Architecture

Keep the dashboard as a derived frontend presentation over the latest
`PacketMeta[]`. A focused pure module owns lifecycle derivation, attention
derivation, counts, filtering, and stable priority ordering. `CaseDetail`
owns only the selected filter and attention-first toggle, then renders the
derived collection.

This is preferred to either persisting a display status or overloading the
existing `packetNeedsResubmit` helper. Persisting status could drift from saved
reviews, while `packetNeedsResubmit` intentionally mixes reviewer actions with
weak identity matching for report behavior. The dashboard instead creates a
separate, explicit lifecycle boundary without changing existing report
semantics.

## Reviewer Lifecycle

The internal type is exactly:

```ts
type PacketDashboardStatus =
  | 'unseen'
  | 'reviewing'
  | 'completed'
  | 'flagged'
```

`packetDashboardStatus(packet)` derives one and only one state from the saved
review:

1. `flagged` when `review.rejection` is non-null or any
   `review.fields[*].flag` is non-null. This rule has precedence over all other
   rules, including `review.done`.
2. `completed` when `review.done` is true and the packet has neither an overall
   rejection nor a field flag.
3. `reviewing` when `review.done` is false, at least one saved field has
   `seen: true`, and the packet has neither kind of reviewer flag.
4. `unseen` otherwise: `review.done` is false, no saved field has `seen: true`,
   and there is no reviewer flag.

The Vietnamese labels are fixed:

| Internal state | Label |
| --- | --- |
| `unseen` | `Chưa xem` |
| `reviewing` | `Đang xem` |
| `completed` | `Đã xong` |
| `flagged` | `Flagged` |

`matchedBy`, split confidence, and pipeline flags never participate in this
function. In particular, a name-only or roster-unmatched packet remains
`unseen`, `reviewing`, or `completed` until the reviewer flags or rejects it.
This dashboard status does not replace or alter the existing server and report
definition of `needs_resubmit`.

## System Attention

System attention is orthogonal metadata derived by
`attentionReasons(packet): string[]`. An empty array means no attention.
A non-empty array adds a visible amber `!` marker and reason copy but never
changes lifecycle state, lifecycle count, lifecycle color, report inclusion, or
case progress.

Reasons are deduplicated and returned in this stable order:

1. `matchedBy === "name"` → `Chỉ khớp theo tên`
2. `matchedBy === "unmatched"` → `Không khớp bảng kê`
3. packet flag `auto-merged` → `Cần xác nhận ranh giới`
4. packet flag `near-threshold` → `Ranh giới gần ngưỡng`
5. packet flag `length-out-of-range` → `Số trang bất thường`
6. packet flag `no-roster-match` or `roster-unmatched` →
   `Không khớp bảng kê`, unless that reason is already present
7. any other non-empty pipeline flag → `Cần kiểm tra xử lý`

The generic fallback keeps a newly introduced actionable pipeline warning
visible without exposing a raw internal code. Multiple unknown flags produce
only one fallback reason.

The card renders the first reason next to the amber `!`. When more reasons
exist, it appends `+N` and exposes the complete reason list through an
accessible label/title. This keeps the grid compact while preserving every
signal. Attention styling is limited to this marker and copy; it must not
recolor the card background or lifecycle border.

## Read-Only Progress Metadata

The saved review records seen fields but packet metadata does not currently
contain the total number of reviewable fields. Accurate reviewing progress
therefore requires one additive read-only property:

```ts
interface PacketMeta {
  // existing properties unchanged
  reviewFieldCount: number
}
```

The backend derives `reviewFieldCount` from
`len(manifest["fields"])` for the packet's existing manifest. It adds the value
to packet copies returned by `GET /api/cases/{id}` and by the existing
`PUT /api/cases/{id}/packets/{i}/review` response. It does not write the value
to `case.json`, the manifest, or the review request. A missing or unreadable
manifest yields `0` rather than failing the case-detail request.

The frontend normalizes a missing value to `0` for backward compatibility.
Reviewing progress is:

```ts
const seen = Object.values(packet.review.fields)
  .filter(field => field.seen).length
```

When `reviewFieldCount > 0`, the card displays
`<seen>/<reviewFieldCount> đã xem`. The defensive fallback for zero is
`<seen> trường đã xem`. This response-only addition keeps the feature
read/derive-only while making progress accurate for future manifest schemas
instead of hard-coding the current six fields.

## Counts, Filters, and Ordering

The case-detail filter bar contains exactly:

- `Tất cả`
- `Chưa xem`
- `Đang xem`
- `Đã xong`
- `Flagged`

Each of the four status controls shows the count from
`packetDashboardCounts(packets)`. The helper initializes all four keys to zero,
derives exactly one status per packet, and increments only that key. Therefore:

```ts
unseen + reviewing + completed + flagged === packets.length
```

`Tất cả` shows `packets.length`. Attention counts are not shown in these
controls. Selecting a status filters the latest packet array locally; it never
fetches or mutates data. If the active status has zero packets after a review
save, the filter remains selected and the grid shows an explicit empty message
rather than silently switching filters.

`Cần chú ý trước` is a toggle adjacent to the filters, not a fifth status
filter. The data pipeline is:

```text
latest packets in server/base order
  -> lifecycle filter
  -> optional stable attention partition
  -> cards
```

When enabled, `prioritizeAttention(packets)` returns all packets whose
`attentionReasons` are non-empty followed by all remaining packets. It preserves
the original relative order within both groups and never mutates the source
array. Turning it off renders the filtered base order again, so no separate
"restore order" snapshot can become stale.

## Card Presentation

Every card remains a semantic button and opens its packet exactly as today.
Lifecycle state owns the card class and primary status presentation:

| State | Presentation |
| --- | --- |
| `unseen` | neutral gray |
| `reviewing` | blue plus reviewed-field progress |
| `completed` | green |
| `flagged` | pink/red |

The primary status area always contains the lifecycle label. Its secondary
summary follows these exact rules:

- `unseen`: no secondary summary.
- `reviewing`: the progress string defined above.
- `completed`: no secondary summary.
- `flagged` with an overall rejection:
  `Đã từ chối · <reason labels>`, using the existing canonical Vietnamese
  rejection labels and order. The optional rejection note remains available in
  the packet review and is not repeated on the compact card.
- `flagged` without an overall rejection:
  `<N> trường đã đánh dấu`, where `N` is the number of field reviews whose
  `flag` is non-null.
- `flagged` with both rejection and field flags: the rejection summary remains
  primary; the field-flag count is not added to the compact card.

If the same flagged packet has system attention, the amber `!` reason renders
as a separate element after the lifecycle summary. Split confidence is no
longer used as a whole-card class; existing confidence/pipeline information is
represented by the explicit attention element.

At desktop widths the controls remain on one wrapping toolbar and cards retain
the current responsive grid. At narrower desktop widths the filter controls may
wrap, but labels, counts, the attention toggle, card summaries, and clickable
targets remain visible without horizontal page overflow.

## Return-from-Review Data Flow

The existing `UploadFlow.applyReviewResult` replaces the matching packet in
`detail.packets` with the response from every successful field review,
completion, flag, rejection, edit, or undo save. Returning from the review
screen therefore exposes the latest saved packet array to `CaseDetail`.

Because status, counts, filtering, summaries, and priority order are computed
from that array on render:

- the card moves to its new lifecycle immediately;
- all four status counts update;
- the card disappears from an old active filter or appears in the matching one;
- field-flag and rejection summaries update;
- attention remains unchanged unless the server packet metadata changed.

No extra save, status synchronization effect, or case-detail refetch is added.
Failed saves continue to leave the last successfully persisted dashboard state
in place under the existing save behavior.

## Components and Responsibilities

- `src/logic/packetDashboard.ts`: lifecycle type and labels, status derivation,
  seen/flag counts, attention-reason mapping, mutually exclusive counts,
  lifecycle filtering, and stable attention partition.
- `src/logic/packetDashboard.test.ts`: pure derivation, precedence, orthogonality,
  count invariant, filtering, stable ordering, and base-order restoration.
- `src/upload/api.ts`: additive `reviewFieldCount` response type and
  backward-compatible normalization only; existing write body and
  `packetNeedsResubmit` behavior remain unchanged.
- `server/app.py`: derive `reviewFieldCount` from the existing manifest for case
  detail and review responses without mutating stored packets.
- `server/app_test.py`: read-response field-count coverage plus existing endpoint
  regressions.
- `src/components/CaseDetail.tsx`: local filter/sort state, filter bar, empty
  state, derived card collection, lifecycle summaries, and separate attention
  rendering.
- `src/components/caseDetail.test.tsx`: component-level labels, counts, filter
  behavior, classes, progress, rejection summary, field-flag count, attention
  copy, card clickability, and sort toggle behavior.
- `src/styles.css`: filter toolbar, active controls, four lifecycle treatments,
  attention marker, empty state, and responsive wrapping.

Existing files may be split only if the implementation plan confirms an equally
focused boundary. No unrelated component or styling refactor is part of this
feature.

## Testing Strategy

Implementation starts only after this written spec is approved and follows
test-driven development. Each behavior is first expressed as a focused failing
test and observed failing for the expected missing behavior.

### Pure frontend tests

- no seen fields and not done/flagged → `unseen`;
- at least one seen field and not done/flagged → `reviewing`;
- done without reviewer flags → `completed`;
- field flag → `flagged`, whether done or not;
- overall rejection → `flagged`, whether done or not;
- rejection/field flags override reviewing and completed;
- name-only, roster-unmatched, boundary, and other pipeline attention reasons do
  not change lifecycle;
- every packet contributes to exactly one lifecycle count and counts sum to the
  total;
- each lifecycle filter returns only its state;
- attention-first ordering is a stable partition;
- disabling priority uses the unchanged base order.

### Component tests

Synthetic packet fixtures cover:

- exact filter labels and mutually exclusive counts;
- selecting every filter and the filtered empty state;
- gray, blue, green, and pink/red lifecycle classes;
- reviewing progress with a non-zero total and its defensive zero-total
  fallback;
- `Đã từ chối · …` taking precedence over a field-flag count;
- `<N> trường đã đánh dấu` without a rejection;
- separate amber `!` attention copy on any lifecycle color;
- `Cần chú ý trước` stable ordering and off-state restoration;
- every visible card remains a clickable packet opener;
- rerendering with a newly saved review moves the card/filter membership and
  updates counts without remount-only state.

### Backend and regression tests

- `GET /api/cases/{id}` and a successful review `PUT` return the manifest-derived
  `reviewFieldCount` without adding it to stored `case.json`;
- missing manifest returns `reviewFieldCount: 0`;
- existing case status, `progress.done`, `progress.flagged`,
  `packetNeedsResubmit`, packet rejection, report grouping, Markdown, and CSV
  behavior remain unchanged;
- the complete frontend Vitest suite, complete backend unittest suite, splitter
  suite, and production build pass.

## Browser QA

Run the isolated v1 backend on `127.0.0.1:8001` and frontend on
`127.0.0.1:5174`. Use only existing in-app data and record no PII in screenshots,
logs, notes, or the handoff.

Verify:

1. all five filter controls, labels, counts, and empty states;
2. the four card lifecycle treatments and reviewing progress;
3. field-flag and packet-rejection summaries;
4. attention marker/reason independent of lifecycle color;
5. attention-first stable order and exact base-order restoration;
6. open a packet, save review/flag/rejection changes, return, and observe the
   card, counts, and active-filter membership update;
7. cards remain reopenable from every filter;
8. the dashboard remains usable at normal and narrow desktop widths;
9. no browser console errors, uncaught page errors, failed frontend requests, or
   port crossover to v2.

## Self-Review

- No duplicate lifecycle value is persisted; all four states come from saved
  review data with explicit flagged precedence.
- System attention is a separate derived list and cannot affect lifecycle,
  lifecycle counts, filters, or card color.
- The four counts are exhaustive and mutually exclusive by construction.
- Priority ordering is a non-mutating stable partition over filtered base order,
  so disabling it restores the current base order without stale snapshots.
- Accurate progress uses manifest-derived response metadata and does not alter
  the review request or any stored file.
- Rejection summary precedence, field-flag count, progress fallback, unknown
  warning handling, zero-result filters, and return-from-review updates are
  unambiguous.
- Existing case progress and report semantics remain explicitly separate and
  covered by regression tests.
- The feature is one focused implementation plan spanning a pure derivation
  module, one case-detail presentation, a small read-response addition, tests,
  styles, and QA.
- No placeholders, deferred product decisions, or PII-bearing examples remain.
