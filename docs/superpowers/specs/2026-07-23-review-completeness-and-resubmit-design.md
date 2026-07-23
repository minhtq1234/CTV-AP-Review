# Design — review-to-completeness + consolidated resubmission report

**Date:** 2026-07-23
**Status:** approved (pending written-spec review)

## Overview

Reframe the reviewer's terminal action. Today a reviewer **approves or rejects**
each packet. In reality an AP reviewer does not gate-keep approval — they **skim
every field with their own eyes**, **flag the ones that don't reconcile** with the
bảng kê, and hand a **consolidated list of problems back to the form owner(s)** for
resubmission.

So the flow becomes:

1. **Skim to completeness.** Every field a reviewer focuses is marked *seen*
   automatically. A packet can only be marked **Done** once *all* its fields have
   been seen — the app enforces "validate with your own eyes."
2. **Flag as you go.** Any field that doesn't reconcile gets flagged with an
   optional note, anchored to the document/page it came from.
3. **Export one report.** At the submission level, the server generates **one
   consolidated resubmission report** (Markdown + CSV), grouped by CTV, listing
   every flagged field — the artifact AP staff forwards to the form owner(s).

A second, related improvement: **make the roster↔packet match key visible** so a
reviewer can spot a mis-matched packet (the dangerous failure mode — comparing
against the wrong person's expected values).

## Goals

- Track per-field **seen** state (auto on focus) and gate **Done** on all-seen.
- Surface the **match key** (matched by CCCD / by name / unmatched) per packet, with
  an eyeball-able identity comparison; a weak/failed match is itself flaggable.
- **Flag** non-reconciled fields with an optional reason + note, anchored to the
  field's document + page.
- Server **generates + persists** one consolidated report (Markdown + CSV), grouped
  by CTV, and the app previews / copies / downloads it.
- **Pin the roster value onto the doc view**, next to the focused field, so the
  roster-vs-document comparison happens at the point of gaze.
- **Remove** approve/reject semantics.

## Non-goals (YAGNI)

- Actually sending email/Zalo/messages — the app produces the report; a human
  forwards it.
- Tracking resubmission rounds, versioning, or re-ingesting corrected files.
- Inline editing / correcting OCR values.
- Auth, multi-user concurrency.

## Data model

Per-packet review state, persisted in `case.json` (replaces `decision` /
`rejectReason`):

```jsonc
"review": {
  "done": false,
  "fields": {
    "<fieldKey>": {                 // fieldKey = CtvFolder field.key (name/cccd/mst/…)
      "seen": true,
      "flag": null                  // or { "reason": "sai" | "thiếu" | "mờ" | "", "note": "…" }
    }
  }
}
```

Identity / match info persisted on the packet meta (populated at pipeline time, see
below) so the UI and report can show it without re-running OCR:

```jsonc
"matchedBy": "cccd" | "name" | "unmatched" | "no-roster",
"ocrIdentity":    { "cccd": "…", "name": "…" },   // read from the documents
"rosterIdentity": { "cccd": "…", "name": "…" }    // from the matched bảng kê row (null if unmatched)
```

**Derived values** (not stored):

- `seenCount` / `total` — from `review.fields`.
- **Packet status:** `chưa xem` (0 seen) → `đang xem` (some seen, not done) →
  `xong · sạch` (done, no flags) or `xong · cần gửi lại` (done, ≥1 flag).
- A **weak match** (`matchedBy` = `name` or `unmatched`) contributes a synthetic
  packet-level issue to the report ("đối chiếu định danh — cần xác minh"), even with
  no field flags.

## Match-key visibility (idea #1)

**Packet card (case-detail grid):** a badge —
`Khớp theo CCCD` (strong) · `Khớp theo tên` (amber, warning) · `Chưa khớp bảng kê`
(red) — from `matchedBy`.

**Review header:** an **identity strip** with two columns the reviewer can eyeball:

| | Từ chứng từ (OCR) | Từ bảng kê (roster) |
|---|---|---|
| CCCD | `ocrIdentity.cccd` | `rosterIdentity.cccd` |
| Tên | `ocrIdentity.name` | `rosterIdentity.name` |

Mismatched cells are highlighted. A name-only or unmatched result renders a warning
and is carried into the report.

## Review UI (idea completeness + flagging)

**Fields panel (`FolderFieldsPanel`):**
- A **progress meter** at the top: "4/6 đã xem".
- Each field row shows a **seen dot** that fills once the field has been focused.
- Each field row has a **flag toggle (⚑)**; toggling on opens a small popover with
  2–3 quick reasons (`sai` / `thiếu` / `mờ, không đọc được`) and an optional
  free-text note. A flagged field is styled "cần gửi lại".

**Seen tracking:** focusing a field (click, or `↑/↓`) — the existing action that
auto-focuses the document to the field's location — sets `seen = true`. No extra
interaction.

**ActionBar:** approve/reject buttons are **removed**. In their place:
- **`✓ Xong`** — disabled until `seenCount === total`; disabled tooltip: "Còn N
  trường chưa xem". Clicking sets `review.done = true`.
- Hotkey **`F`** toggles the flag on the focused field. The hint line is updated.

**Persistence:** the client holds the packet's review state and `PUT`s the full
object (see backend) on meaningful changes — flag toggled, Done clicked — and
flushes seen-progress when navigating away from the packet (Back / prev-next /
Danh sách). This avoids a network call per arrow-key while keeping resume accurate.

## Roster value pinned to the field (doc view)

The reviewer's primary act is comparing the **bảng kê value** against what the
**document** actually says. Today the roster value lives in the left fields panel, so
comparing means eye-travel between panes. Instead, pin the roster value onto the doc
view, at the point of gaze:

- When a field is focused, a **floating callout** on the doc view shows that field's
  **roster (bảng kê) value** — two lines: a small `Bảng kê — <field label>` header
  over the **big, high-contrast value**. It shows the roster value **only**, never
  the OCR'd doc value: the reviewer reads the actual document with their eyes and
  compares (showing the OCR guess big would bias that).
- It is **anchored to the highlighted field box** and **tracks it** on zoom/pan,
  sitting just **above** the box (flips **below** when near the top edge), offset so
  it never covers the value being read. **Text size is viewport-fixed** — always
  legible regardless of document zoom.
- **Fallback (unlocated / handwritten "cần xem" fields, no box on the active doc):**
  the roster value renders as a **fixed chip in a corner** of the doc pane, so it is
  still on screen while the reviewer hunts for the value by eye.
- Only shown when the focused field has a non-empty roster value.
- **Toggle:** a doc-toolbar button + hotkey **`V`** (default on), **independent** of
  the box toggle (`B`); added to the `?` hotkey legend and the ActionBar hint.
- **Implementation:** in `EvidenceViewer` (which already computes the box's viewport
  rect via `boxToViewport` and owns the toolbar + hotkey pattern). `FolderReview`
  passes the focused field's `expected` value + label down as props.

## Submission level + the consolidated report (idea #2)

**Case-detail screen:**
- A **summary line**: "32 gói · 5 cần gửi lại · 11 trường có vấn đề".
- An **`Xuất báo cáo gửi lại`** button → calls the report endpoint, then opens a
  **preview panel**: rendered Markdown, a **Copy** button, and **download** links for
  the `.md` and `.csv` (served from the backend).

**Report contents** — grouped by CTV, including only packets that have field flags
*or* a weak/failed identity match. For each CTV:
- Header: CTV name + identity (and a "định danh cần xác minh" note if `matchedBy` is
  weak).
- One row per flagged item: **field label · document + page · giá trị bảng kê vs.
  giá trị đọc được (or "cần xem") · reviewer reason + note**.

## Backend

- **Store (`server/cases.py`):** replace `set_decision` with `set_review(case_id,
  index, review)` persisting the packet's `review` object; recompute case
  `progress` (decided → done count; flagged count) and `status` (any packet touched
  → `in_review`; all packets `done` → `done`). Populate `matchedBy` / `ocrIdentity`
  / `rosterIdentity` on packet meta during pipeline (`server/pipeline.py` already
  computes `identity` + matched `row`).
- **Endpoints (`server/app.py`):**
  - `PUT /api/cases/{id}/packets/{i}/review` — body `{ done, fields }`; persists,
    returns updated packet meta + case progress/status. (Replaces `…/decision`.)
  - `POST /api/cases/{id}/report` — builds the consolidated report from persisted
    review state, **writes `report.md` + `report.csv` to the case dir**, returns
    structured JSON + the Markdown text.
  - `GET /api/cases/{id}/report.md` and `…/report.csv` — serve the persisted files.
- **Report builder** — a **pure function** `build_report(case) -> {groups, markdown,
  csv}` (grouping + formatting), unit-tested independently of FastAPI.

## Report format (decided)

Server generates **both** renderings of the same data, persisted to the case dir:
- **Markdown** — human-readable, for the in-app preview + copy + `.md` download
  (what AP staff pastes/forwards).
- **CSV** — one row per flagged item (`CTV, CCCD, field, document, page, roster
  value, doc value, reason, note`) for spreadsheet tracking.

## Migration

Existing cases store the old `decision` / `rejectReason`. This is a throwaway
prototype: on load, packets in the old shape are migrated to
`review = { done: false, fields: {} }` (reset) — per-field seen/flag can't be
reconstructed, and there are only a handful of test cases. Noted, not preserved.

## Testing

- **Pure logic (unit):** packet status derivation from review state; the Done gate
  (`done` allowed iff all seen) as a pure helper; `build_report` grouping + Markdown
  + CSV rendering (server).
- **Browser verification:** skim a packet (progress fills, Done unlocks only at
  full), flag a field with a note, mark Done → status `cần gửi lại`, export report →
  check grouping and that a `Khớp theo tên` packet shows the identity warning and
  appears in the report. Confirm the **roster callout** pins next to the focused
  field, tracks it on zoom/pan, stays legible zoomed out, falls back to a corner chip
  for an unlocated field, and toggles with `V` independently of `B`.

## Out of scope

Resubmission round-tripping, actual message sending, OCR-value editing, auth.
