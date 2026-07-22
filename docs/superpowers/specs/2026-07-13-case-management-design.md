# Case management — design

**Date:** 2026-07-13
**Status:** approved (design); ready for implementation plan

## Context

Today the upload flow processes one PDF into an **in-memory** job whose files live
in a **temp dir**: nothing survives a backend restart, there's no list of past
uploads, and the reviewer's approve/reject decisions aren't saved (they're local
React state). To let a user upload multiple submissions and come back to review
them over time, we add **persistence + a case list + saved per-packet decisions**.

Decided with the user:
- A **case = one submission** (one uploaded PDF, a batch of ~32 CTV packets).
  Packets are nested inside a case; the case tracks review progress.
- **Per-packet decisions persist** (duyệt / từ chối / chưa xem) so a reviewer can
  stop mid-batch and resume where they left off.

## Goal

Turn the one-shot upload flow into a durable, resumable workflow: a landing **case
list**, a **"new case"** upload path, a **case-detail** view showing each packet's
decision + progress, and packet review whose **duyệt/từ chối decisions are saved**
to disk and reflected in the list.

## Non-goals (YAGNI for the prototype)

- Single local user; no authentication or multi-tenant separation.
- Decisions at the **packet** level only — no per-field checkmarks.
- No rename / search / filter / sort of cases (a simple **delete** is included).
- JSON-on-disk persistence (not a database).
- No case-level "submit/export approval" step — just per-packet decisions + progress.

## Persistence — JSON-on-disk case store

A durable data root `server/data/cases/<case_id>/` per case:
- `case.json` — metadata + packet decisions (the source of truth for the list/detail).
- `packets/<i>/manifest.json` — the packet's CtvFolder (fields, docs).
- `packets/<i>/page/pg*.png` — rendered pages.

The backend loads all `case.json` files on startup into an in-memory index (for
fast listing) and writes through to disk on every change. Chosen over SQLite for
prototype simplicity, no new dependency, and human-inspectability. (SQLite is the
production upgrade if scale/querying grows.)

## Data model

```
Case {
  id: string                 # uuid hex
  name: string               # submission label (default: PDF filename)
  createdAt: string          # ISO; stamped by the backend at creation
  status: 'processing' | 'ready' | 'in_review' | 'done' | 'error'
  pdfName: string
  rosterName: string | null
  summary: { found, rosterN, autoMerged } | null   # filled when processing completes
  error: string | null
  packets: PacketMeta[]
}
PacketMeta {
  index: number
  name: string | null        # roster-matched CTV name
  pages: [number, number]    # 1-based inclusive
  confidence: 'green' | 'amber'
  flags: string[]
  decision: 'pending' | 'approved' | 'rejected'
  rejectReason: string | null
  reviewedAt: string | null
}
```
- Case `status`: `processing` during the pipeline; `ready` when done with 0
  decisions; `in_review` when some but not all packets decided; `done` when every
  packet has a decision; `error` on pipeline failure.
- Progress (derived): decided / total, plus a flagged (amber) count.

## Backend (`server/`)

Replace the in-memory `JobStore` with a **persistent `CaseStore`** over `data/cases/`.
The processing "job" becomes a case in `processing` status; the worker writes packet
manifests/pages into the case dir (durable, not temp) and updates `case.json`.

Endpoints:
- `POST /api/cases` — multipart (pdf required, roster optional). Create a case
  (persist metadata, `status=processing`), start the pipeline worker, return
  `{ case_id }`.
- `GET /api/cases` — list all cases (id, name, createdAt, status, progress
  {decided, total, flagged}). Newest first.
- `GET /api/cases/{id}` — full case (metadata + `packets[]` incl. decisions +
  progress). During processing also returns `{ progress: {stage, done, total, detail} }`.
- `GET /api/cases/{id}/packets/{i}/manifest.json` and `…/page/{name}.png` — as today,
  keyed by case id.
- `PUT /api/cases/{id}/packets/{i}/decision` — body `{ decision, rejectReason? }`.
  Update the packet's decision + `reviewedAt`, recompute case status, persist. Returns
  the updated packet + case progress.
- `DELETE /api/cases/{id}` — remove the case dir + index entry.

CORS/localhost/PII unchanged. On startup, scan `data/cases/` → rebuild the index.

## Frontend

The "Tải hồ sơ" mode becomes a small router over these screens:
- **Case list** (landing) — cards/rows per case: name, date, status pill, progress
  ("12/32 đã duyệt · 3 cần xem"), open + delete. A **"+ Tải hồ sơ mới"** button.
- **Upload** — the existing `UploadScreen` (PDF + optional roster).
- **Processing** — the existing `ProcessingScreen`, polling `GET /api/cases/{id}`.
- **Case detail** — the split-result grid, each packet card now showing its
  **decision badge** (chưa xem / đã duyệt / từ chối) alongside the confidence dot,
  plus a case progress header. Clicking a card opens the packet.
- **Packet review** — the existing `FolderReview` + loupe. **Duyệt / Từ chối now
  calls `PUT …/decision`** to persist; on success, return to case detail (progress
  updates) — or advance to the next unreviewed packet.

State: the flow tracks `screen`, `caseId`, `packetIndex`. Resuming = open a case
from the list → case detail shows saved decisions → continue. The `?job=<id>` resume
hook generalizes to `?case=<id>`.

## Data flow

```
Upload → POST /api/cases → case dir created (status processing) → pipeline writes
  packets + case.json → status ready → appears in GET /api/cases
Open case → GET /api/cases/{id} → detail (packets + decisions)
Open packet → GET …/manifest.json (+ pages) → FolderReview
Duyệt/Từ chối → PUT …/decision → case.json updated → status recomputed → list/detail reflect it
```

## Error handling

- Pipeline failure → case `status=error` with a message; the list shows it; detail
  offers delete/retry (retry = re-POST; out of scope to auto-retry).
- Backend down (frontend) → the existing friendly "chạy backend ở cổng 8000" message.
- Decision write failure → surface inline, keep the packet's prior decision.
- Corrupt/partial `case.json` on startup → skip that case, log, don't crash the index.

## Testing & verification

- **Backend (pure/unit):** `CaseStore` create/list/get/update-decision/delete +
  status recomputation (pending→in_review→done) with a temp data dir and a fake
  pipeline; `case.json` round-trips; startup index rebuild from disk; decision
  persistence survives a store reload (simulates restart).
- **Frontend (pure/unit, vitest):** the API client (list/get/decision), progress
  formatting, decision-badge mapping.
- **End-to-end (browser):** upload → case appears in list → open → decide a packet →
  it persists (reload the page / restart the backend → decision still there) →
  case progress updates → delete a case.

## Success criterion

Upload two submissions; both appear in the case list with correct progress. Open
one, approve/reject several packets, leave, **restart the backend**, return: the
case list and the packet decisions are exactly as left, and the reviewer resumes at
the next unreviewed packet. No PII committed (data root is gitignored).

## Notes / migration

- `data/cases/` is gitignored (contains real PII). The processing pipeline's output
  target changes from `tempfile.mkdtemp()` to the case dir.
- Existing `/api/jobs*` endpoints are replaced by `/api/cases*`; the frontend upload
  flow is refactored onto the case router. Synthetic CTV/flight/receipt modes are
  untouched.
