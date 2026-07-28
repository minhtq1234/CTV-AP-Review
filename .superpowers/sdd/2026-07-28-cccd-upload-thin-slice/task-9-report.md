# Task 9 report — CCCD regression, privacy audit, and browser fixture

## Scope and characterization

Started from `401ddd2` on `codex/cccd-mapping-spike`. This task adds only a
PII-free smoke backend and a pipeline failure-isolation regression test.

`test_cccd_error_result_keeps_pdf_packets_reviewable` passed immediately when
first added: Task 6 already preserves the PDF-derived packets and returns an
`invalid-workbook` CCCD result as data. It is therefore a characterization
test; no production correction was made.

### Fix round 1 — import guard ordering

The initial fixture imported `app` before reading `CTV_CCCD_SMOKE_ROOT`, which
could initialize the normal default store before the fixture rejected a missing
root. `cccd_smoke_app_test.py` was added first as an isolated subprocess test
that blocks any `app` import; it failed with that import-order defect. The
fixture now reads the required environment variable immediately after stdlib
imports, before Pillow or any application module. The new test passes and the
fixture still imports with an explicit disposable root.

### Fix round 2 — live CCCD progress label

Controller browser verification found that `CaseList` preferred generic packet
progress whenever a live stage had a nonzero total. A CCCD callback of
`{stage: "cccd", done: 1, total: 1, detail: ""}` therefore rendered `gói 1/1`
instead of the required `Đọc và ghép ảnh CCCD…`. Scope expands to
`CaseList.tsx` and `CaseList.test.ts` because this is an acceptance defect in
the completed upload slice. The focused static rendering regression failed
first, then passed after `cccd` was made an explicit stage-label exception;
OCR retains `gói n/N · detail` rendering.

## Verification

- Backend: `cd server && python3 -m pytest -q` — 295 passed, 6 existing
  dependency/runtime warnings.
- Frontend: `npx vitest run` — 13 files, 72 tests passed.
- Production build: `npm run build` — passed.
- Focused pipeline suite: `cd server && python3 -m pytest pipeline_test.py -q`
  — 15 passed.
- Import-order regression: `cd server && python3 -m pytest
  cccd_smoke_app_test.py -q` — 1 passed.
- Fixture import: requires `CTV_CCCD_SMOKE_ROOT`; with an explicit disposable
  root it imports and exposes the FastAPI app.
- `git diff --check` — passed.

## Privacy and boundary audit

- Case detail removes raw `cccdWorkbook` and derives `cccdSummary` through
  `compact_cccd_summary`; the list endpoint exposes neither workbook metadata
  nor mappings.
- The browser contract carries only aggregate CCCD summary data. Packet-level
  identity remains available only to the reviewer flow, not the case summary.
- `server/cccd_ingest.py`, `server/cccd_workbook.py`, and `server/cccd_ocr.py`
  contain no `print`, logger, or logging calls.
- `cccd_spike` has no production `server/` or `src/` import/call path.
- The fixture contains only deliberate synthetic values (`000000000001`,
  `Synthetic Reviewer`) and creates all generated PNGs beneath the disposable
  smoke root. It neither imports nor calls `cccd_ingest`.
- The existing `CaseDetail` redaction test intentionally seeds a synthetic
  `/private/source/000000000001.png` path and asserts that neither it nor the
  synthetic identity reaches the detail response. It is test-only and not a
  real attachment path.

## Controller browser handoff

In terminal 1, create disposable placeholder uploads and run the fixture:

```bash
SMOKE_ROOT="$(mktemp -d)"
touch "$SMOKE_ROOT/input.pdf" "$SMOKE_ROOT/roster.xlsx" "$SMOKE_ROOT/cards.xlsx"
CTV_CCCD_SMOKE_ROOT="$SMOKE_ROOT" \
  python3 -m uvicorn cccd_smoke_app:app --app-dir server \
  --host 127.0.0.1 --port 8000
```

In terminal 2:

```bash
npm run dev -- --host 127.0.0.1 --port 5173
```

Use only `$SMOKE_ROOT/input.pdf`, `$SMOKE_ROOT/roster.xlsx`, and
`$SMOKE_ROOT/cards.xlsx`; their contents are deliberately unused by the
fixture. The controller should complete the approved upload-blocker, live
`Đọc và ghép ảnh CCCD…`, summary, packet-tab, A1 reviewer-control, and
console-error checks. No browser interaction was performed in this task.
