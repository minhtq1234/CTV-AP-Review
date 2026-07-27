# CTV v1 Packet-Level Rejection Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add durable, editable, undoable packet-level rejection to CTV v1 while preserving every field review and reporting the packet issue exactly once before field issues.

**Architecture:** Extend the full `PacketReview` snapshot additively with `rejection`, normalize the shape at the server/store and client boundaries, and enforce rejection-first derived status. Keep dialog draft state local, serialize full-review saves in `UploadFlow`, and publish create/edit/undo state only after persistence succeeds. The report stores packet rejection separately from field items and renders it first.

**Tech Stack:** React 18, TypeScript 5.5, Vitest 2, Vite 5, FastAPI, Pydantic, Python pytest, JSON-on-disk `CaseStore`.

## Global Constraints

- Work only in `/Users/lap16603/Documents/New project/work/CTV_APReview-v1`.
- Do not touch `/Users/lap16603/Documents/New project/work/CTV_APReview`.
- Preserve all settled v1 layout changes and the intentional backend API port `8001`.
- Do not expose or copy real PII into tests, fixtures, screenshots, docs, or output.
- Do not push.
- Rejection reasons are exactly `missing_documents`, `wrong_template`, and `missing_signature`.
- A rejection forces completion and `cần gửi lại`, but detailed fields remain editable.
- Undo preserves `review.fields` and derives `done` from whether every field is seen.
- Normal completion without rejection still requires every field to be seen.
- Packet rejection create/edit/undo must never publish false local state on save failure.
- Report the packet rejection once, before identity and field issues.

## File Structure

- Create `src/logic/packetRejection.ts`: reason constants/labels, draft validation and normalization, rejected/undo review builders.
- Create `src/logic/packetRejection.test.ts`: pure frontend rejection rules.
- Create `src/components/PacketRejectionDialog.tsx`: accessible controlled create/edit dialog.
- Create `src/components/packetRejectionDialog.test.tsx`: server-rendered dialog-state contract tests.
- Modify `src/upload/api.ts` and `src/upload/api.test.ts`: additive public types, response normalization, rejection-aware resubmission.
- Modify `src/logic/review.ts` and `src/logic/review.test.ts`: rejection-first status.
- Modify `src/components/FolderFieldsPanel.tsx`: rejection button or persistent summary above fields.
- Modify `src/components/FolderReview.tsx`: dialog ownership, candidate construction, transactional callback.
- Modify `src/components/UploadFlow.tsx`: serialized saves and transactional rejection persistence.
- Modify `src/components/reviewPresentation.test.tsx`: entry/summary rendering and field editability.
- Modify `src/styles.css`: outlined danger button, rejected summary, compact dialog and inline error.
- Modify `server/cases.py` and `server/cases_test.py`: additive migration/defaults, invariant, progress and persistence.
- Modify `server/app.py` and `server/app_test.py`: backward-compatible validated request shape.
- Modify `server/report.py` and `server/report_test.py`: dedicated packet entry before existing issues.

---

### Task 1: Additive Review Model and Store Invariants

**Files:**
- Modify: `server/cases_test.py`
- Modify: `server/app_test.py`
- Modify: `src/upload/api.test.ts`
- Modify: `server/cases.py`
- Modify: `server/app.py`
- Modify: `src/upload/api.ts`

**Interfaces:**
- Produces: `PacketRejectionReason`, `PacketRejection`, `normalizePacketReview(review)`, and `PacketReview.rejection`.
- Produces: Python `normalize_review(review: dict | None) -> dict`.
- Consumes: existing full-review `PUT /api/cases/{cid}/packets/{i}/review`.

- [ ] **Step 1: Write failing backend default, migration, round-trip, and validation tests**

Add tests proving:

```python
assert packet["review"] == {"done": False, "fields": {}, "rejection": None}

saved = store.set_review(cid, 0, {
    "done": False,
    "fields": {"name": {"seen": True, "flag": None}},
    "rejection": {
        "reasons": ["missing_signature", "missing_documents"],
        "note": "  bổ sung  ",
    },
})
assert saved["packets"][0]["review"] == {
    "done": True,
    "fields": {"name": {"seen": True, "flag": None}},
    "rejection": {
        "reasons": ["missing_documents", "missing_signature"],
        "note": "bổ sung",
    },
}
```

In `server/app_test.py`, assert an omitted `rejection` persists as `null`, an
empty/unknown reason list returns 422, and multiple valid reasons round-trip.

- [ ] **Step 2: Run backend tests and verify RED**

Run:

```bash
python3 -m pytest server/cases_test.py server/app_test.py -q
```

Expected: failures because saved/default reviews have no `rejection`, invalid
reasons are accepted, and rejection does not force `done`.

- [ ] **Step 3: Write failing frontend type/normalization tests**

In `src/upload/api.test.ts`, add:

```ts
expect(normalizePacketReview({ done: true, fields: {} }))
  .toEqual({ done: true, fields: {}, rejection: null })
expect(normalizePacketReview(undefined))
  .toEqual({ done: false, fields: {}, rejection: null })
```

Also assert `packetNeedsResubmit` returns true for a strong-match packet whose
only issue is `review.rejection`.

- [ ] **Step 4: Run frontend tests and verify RED**

Run:

```bash
npm test -- --run src/upload/api.test.ts
```

Expected: failure because `normalizePacketReview` and rejection-aware
resubmission do not exist.

- [ ] **Step 5: Implement backend normalization and validation**

In `server/cases.py`, define canonical reason order and normalization:

```python
REJECTION_REASON_ORDER = (
    "missing_documents",
    "wrong_template",
    "missing_signature",
)

def normalize_review(review: dict | None) -> dict:
    source = review or {}
    rejection = source.get("rejection")
    if rejection is not None:
        selected = set(rejection.get("reasons") or [])
        rejection = {
            "reasons": [r for r in REJECTION_REASON_ORDER if r in selected],
            "note": str(rejection.get("note") or "").strip(),
        }
    return {
        "done": True if rejection else bool(source.get("done", False)),
        "fields": source.get("fields", {}) or {},
        "rejection": rejection,
    }
```

Use it in `_ensure_packet_defaults`, startup migration for every packet, and
`set_review`. Persist only when normalization changes stored data.

In `server/app.py`, use a nested Pydantic model with a `Literal` reason list and
minimum length one, default `rejection=None`, then pass `body.model_dump()` on
Pydantic 2 or the repository-compatible equivalent to `set_review`.

- [ ] **Step 6: Implement frontend types and normalization**

In `src/upload/api.ts`, add:

```ts
export const PACKET_REJECTION_REASONS = [
  'missing_documents',
  'wrong_template',
  'missing_signature',
] as const
export type PacketRejectionReason = typeof PACKET_REJECTION_REASONS[number]
export interface PacketRejection {
  reasons: PacketRejectionReason[]
  note: string
}
```

Add `rejection: PacketRejection | null` to `PacketReview`, implement
`normalizePacketReview`, map every packet review returned by `getCase`, and
normalize `setReview`'s returned packet. Include rejection in
`packetNeedsResubmit`.

- [ ] **Step 7: Run focused backend/frontend tests and verify GREEN**

Run:

```bash
python3 -m pytest server/cases_test.py server/app_test.py -q
npm test -- --run src/upload/api.test.ts
```

Expected: all focused tests pass.

- [ ] **Step 8: Commit Task 1**

Stage only Task 1 files and commit:

```bash
git commit -m "feat: persist packet rejection state"
```

---

### Task 2: Rejection-First Status and Report Output

**Files:**
- Modify: `src/logic/review.test.ts`
- Modify: `server/cases_test.py`
- Modify: `server/report_test.py`
- Modify: `src/logic/review.ts`
- Modify: `server/cases.py`
- Modify: `server/report.py`
- Modify: `src/upload/api.ts`

**Interfaces:**
- Consumes: `PacketReview.rejection` and canonical reason codes from Task 1.
- Produces: `PacketRejectionReportEntry` and `ReportGroup.packetRejection`.
- Preserves: existing `ReportItem[]`, identity warnings, Markdown, and CSV field rows.

- [ ] **Step 1: Write failing status/progress tests**

Assert:

```ts
expect(packetStatus({
  matchedBy: 'cccd',
  review: {
    done: true,
    fields: {},
    rejection: { reasons: ['missing_documents'], note: '' },
  },
} as any)).toBe('needs_resubmit')
```

Add Python assertions that a rejected packet yields
`{"done": 1, "total": 1, "flagged": 1}` and remains counted once when it also
has a field flag.

- [ ] **Step 2: Write failing report ordering/content tests**

Build one synthetic packet with a rejection and a field flag. Assert:

```python
group = report["groups"][0]
assert group["packetRejection"]["reasonLabels"] == [
    "Thiếu chứng từ",
    "Thiếu chữ ký",
]
assert report["markdown"].index("Từ chối gói hồ sơ") < report["markdown"].index("Số CCCD")
rows = report["csv"].splitlines()
assert rows[1].find("Từ chối gói hồ sơ") >= 0
assert sum("Từ chối gói hồ sơ" in row for row in rows) == 1
```

Also test an empty optional note and ensure existing field output remains.

- [ ] **Step 3: Run focused tests and verify RED**

Run:

```bash
python3 -m pytest server/cases_test.py server/report_test.py -q
npm test -- --run src/logic/review.test.ts
```

Expected: rejection-only status/report tests fail.

- [ ] **Step 4: Implement rejection-first derivation**

Update client and server `needs_resubmit` helpers to check rejection before
field flags and weak identity. Keep progress counting packets, not issues.

- [ ] **Step 5: Implement dedicated report entry**

In `server/report.py`, define the Vietnamese label mapping, produce at most one
`packetRejection` object per group, render its Markdown line immediately after
the group heading, and write its CSV row before identity/field rows. Do not add
it to `_items_for`.

Update TypeScript report types:

```ts
export interface PacketRejectionReportEntry {
  reasons: PacketRejectionReason[]
  reasonLabels: string[]
  note: string
}
```

and `ReportGroup.packetRejection: PacketRejectionReportEntry | null`.

- [ ] **Step 6: Run focused tests and verify GREEN**

Run the Task 2 command again. Expected: all focused tests pass.

- [ ] **Step 7: Commit Task 2**

```bash
git commit -m "feat: report packet rejection"
```

---

### Task 3: Pure Rejection Rules and Dialog Contract

**Files:**
- Create: `src/logic/packetRejection.ts`
- Create: `src/logic/packetRejection.test.ts`
- Create: `src/components/PacketRejectionDialog.tsx`
- Create: `src/components/packetRejectionDialog.test.tsx`

**Interfaces:**
- Consumes: `PacketReview`, `PacketRejection`, and `PacketRejectionReason`.
- Produces: `PACKET_REJECTION_OPTIONS`, `normalizeRejectionDraft`,
  `rejectedReview`, and `undoRejectedReview`.
- Produces controlled component props:
  `rejection`, `saving`, `error`, `onCancel`, `onSubmit`, and optional `onUndo`.

- [ ] **Step 1: Write failing pure-rule tests**

Cover canonical multi-reason order, note trimming, no-reason validation, fields
preserved on reject/edit/undo, rejection forcing done, and undo deriving done
from all field keys.

```ts
expect(normalizeRejectionDraft(['missing_signature', 'missing_documents'], ' x '))
  .toEqual({
    reasons: ['missing_documents', 'missing_signature'],
    note: 'x',
  })
expect(() => normalizeRejectionDraft([], '')).toThrow('Chọn ít nhất một lý do')
```

- [ ] **Step 2: Write failing dialog markup tests**

Use `renderToStaticMarkup` to assert create/edit modes contain the exact titles,
three checkbox labels, `Ghi chú`, correct primary copy, `Hủy`, edit-only
`Hoàn tác từ chối`, inline errors, checked reasons, and saving-disabled actions.

- [ ] **Step 3: Run tests and verify RED**

Run:

```bash
npm test -- --run src/logic/packetRejection.test.ts src/components/packetRejectionDialog.test.tsx
```

Expected: modules do not exist.

- [ ] **Step 4: Implement pure review builders**

Implement:

```ts
export function rejectedReview(
  review: PacketReview,
  rejection: PacketRejection,
): PacketReview

export function undoRejectedReview(
  review: PacketReview,
  fieldKeys: string[],
): PacketReview
```

Both spread and preserve `review.fields`; undo sets `done` using `allSeen`.

- [ ] **Step 5: Implement controlled dialog**

Keep draft reasons/note in local state seeded whenever the dialog opens. Submit
validates before calling `onSubmit`; validation and parent save errors render in
the inline message area. Escape and backdrop call `onCancel` only while not
saving. Buttons/checkboxes use native semantics and `role="dialog"` has an
accessible label.

- [ ] **Step 6: Run focused tests and verify GREEN**

Run the Task 3 command again. Expected: all focused tests pass.

- [ ] **Step 7: Commit Task 3**

```bash
git commit -m "feat: add packet rejection dialog"
```

---

### Task 4: Review-Screen Integration and Transactional Saves

**Files:**
- Modify: `src/components/reviewPresentation.test.tsx`
- Create: `src/logic/reviewSaveQueue.ts`
- Create: `src/logic/reviewSaveQueue.test.ts`
- Modify: `src/components/FolderFieldsPanel.tsx`
- Modify: `src/components/FolderReview.tsx`
- Modify: `src/components/UploadFlow.tsx`
- Modify: `src/components/DemoFlow.tsx`
- Modify: `src/styles.css`

**Interfaces:**
- Consumes: Task 3 review builders and controlled dialog.
- Produces: `createReviewSaveQueue(save)` with `enqueue(context, review)`.
- `FolderReview` gains
  `onCommitReview: (review: PacketReview) => Promise<void>`.
- Preserves existing `onReview(review)` optimistic field behavior.

- [ ] **Step 1: Write failing presentation tests**

Assert the field panel renders `Từ chối gói hồ sơ` above the first field when
`rejection` is null. For a rejected review, assert `Đã từ chối`, all selected
Vietnamese labels, the optional note, and `Sửa lý do`, while the existing field
row and `⚑ Đánh dấu`/`Bỏ đánh dấu` controls still render.

- [ ] **Step 2: Write failing save-queue tests**

Use deferred promises to prove:

1. a second full-review save does not start before the first settles;
2. enqueue order is preserved after a failed save;
3. each call retains its captured `{caseId, packetIndex}`;
4. a response for packet A is not used as packet B's response.

- [ ] **Step 3: Run focused tests and verify RED**

Run:

```bash
npm test -- --run src/components/reviewPresentation.test.tsx src/logic/reviewSaveQueue.test.ts
```

Expected: rejected presentation and queue modules are absent.

- [ ] **Step 4: Implement entry point and persistent summary**

Extend `FolderFieldsPanel` props with `onOpenPacketRejection`. Render the
outlined-danger button or rejection summary directly after `.fields-summary`
and before `ranked.map`. Do not disable or alter field rows when rejected.

- [ ] **Step 5: Implement dialog ownership in `FolderReview`**

Track dialog open/save/error state. Create/edit/undo candidates with Task 3
helpers and call `onCommitReview`. Close only on resolve; on reject keep the
dialog open and set `Không lưu được. Vui lòng thử lại.` Do not call navigation.
Keep ordinary field `onReview` calls unchanged.

- [ ] **Step 6: Implement serialized save queue in `UploadFlow`**

Create one queue whose save function calls `setReview` with captured case/index.
For ordinary `onReview`, update local state optimistically and enqueue. For
`onCommitReview`, enqueue first, then update `review` and matching detail packet
from the successful result. Reject without changing rejection state. Guard all
response application by the captured case ID and packet index.

Normalize the initial review in `UploadFlow` and `DemoFlow` to include
`rejection: null`.

- [ ] **Step 7: Add focused styles**

Add scoped styles for:

- full-width outlined danger button;
- persistent red summary and `Sửa lý do`;
- fixed modal backdrop and compact dialog;
- checkbox reason list;
- textarea, saving state, inline validation/save error;
- edit-only undo action;
- visible keyboard focus.

Do not modify the settled document viewer/header/toolbar styles.

- [ ] **Step 8: Run focused tests and verify GREEN**

Run the Task 4 command again plus Task 3 tests. Expected: all pass.

- [ ] **Step 9: Commit Task 4**

```bash
git commit -m "feat: integrate packet rejection workflow"
```

---

### Task 5: Failure, Edit, Undo, and Full Regression Verification

**Files:**
- Modify focused test files only if a missing acceptance case is discovered.
- Do not alter production behavior unless a failing acceptance test identifies a defect.

**Interfaces:**
- Exercises the complete `PacketReview` flow from UI candidate through endpoint,
  store, derived status, reload, edit/undo, and report.

- [ ] **Step 1: Run every focused acceptance test**

Run:

```bash
npm test -- --run src/upload/api.test.ts src/logic/review.test.ts src/logic/packetRejection.test.ts src/logic/reviewSaveQueue.test.ts src/components/packetRejectionDialog.test.tsx src/components/reviewPresentation.test.tsx
python3 -m pytest server/cases_test.py server/app_test.py server/report_test.py -q
```

Expected: all pass, including save-failure no-false-state, multiple reasons,
optional note, validation, cancel markup, edit, undo, field preservation,
completion/resubmission, and report ordering.

- [ ] **Step 2: Run full frontend and backend suites**

Run:

```bash
npm test
python3 -m pytest server -q
```

Expected: all tests pass.

- [ ] **Step 3: Run production build and diff checks**

Run:

```bash
npm run build
git diff --check
git status --short
```

Expected: build exit 0, no whitespace errors, only intended v1 files changed,
and `src/upload/api.ts` still contains `http://127.0.0.1:8001`.

- [ ] **Step 4: Browser QA on isolated v1**

At `http://127.0.0.1:5174/`, use a local non-PII packet:

1. reject with two reasons and an optional note;
2. verify no auto-advance and `Đã từ chối`;
3. edit a field/flag while rejected;
4. reload and verify rejection plus field persistence;
5. edit reasons/note and verify replacement without duplication;
6. undo and verify fields remain plus normal completion recalculation;
7. generate the report and verify packet rejection precedes field issues;
8. check browser console/page errors.

If destructive cleanup of persisted QA data is blocked, do not bypass the
safeguard; report the exact side effect.

- [ ] **Step 5: Final verification commit**

Stage only packet-rejection implementation/test changes and commit:

```bash
git commit -m "test: verify packet rejection workflow"
```

Do not push.

## Plan Self-Review

- Every spec requirement maps to a task and explicit test or browser check.
- Backend/client types use the same reason codes and `rejection` property.
- Migration covers both missing `review` and existing reviews missing only
  `rejection`.
- Rejection creation/edit/undo use transactional publication; ordinary field
  edits remain optimistic.
- The save queue addresses full-snapshot ordering and packet-context capture.
- Report data keeps packet rejection separate from field `items` and renders it
  first exactly once.
- No placeholder steps, undefined helper names, extra reasons, v2 changes, port
  changes, or PII fixtures are present.

