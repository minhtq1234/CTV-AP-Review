# CCCD Upload and Automatic Attachment Thin Slice

**Status:** Approved design, 2026-07-28

## Purpose

Add an optional CCCD image workbook to case creation and use the completed
local extraction/OCR/matching modules to attach only high-confidence,
unambiguous CCCD evidence to the correct packet.

This is a production thin slice of
`2026-07-27-cccd-image-to-packet-mapping-design.md`. It intentionally omits
the manual mapping panel while preserving server-side mapping provenance for
that later workflow.

Where the full design differs, this thin-slice spec governs this release:
CCCD upload requires a roster, only exact automatic attachment is exposed,
and manual mapping plus missing-CCCD checklist attention remain deferred.

The real Phase 0 viability run remains pending because its corresponding
roster and reviewer ground truth were not supplied. The user elected to
continue with this thin slice and improve OCR input quality by requesting
larger source images. This does not relax any automatic-attachment safety
rule.

## Decisions

1. The case upload screen adds an optional CCCD `.xlsx` input.
2. Selecting a CCCD workbook requires a roster workbook.
3. The browser and server both block a CCCD submission without a roster.
4. Processing is local-only.
5. Production orchestration reuses the tested CCCD workbook, OCR, pairing,
   and exact-matching modules. It does not invoke the audit CLI.
6. Only a located, exact 12-digit, confidence `>= 0.85`, unique roster match
   may attach automatically.
7. The matched roster identity must resolve to exactly one processed packet.
8. Confirmed front/back images become packet document tabs.
9. Unresolved candidates remain stored with provenance but appear only as an
   aggregate count in this slice.
10. CCCD failure does not make an otherwise usable packet case fail.
11. There is no post-creation CCCD upload and no manual mapping UI in this
    slice.

## Goals

- Let the user submit the packet PDF, roster, and CCCD image workbook in one
  case-creation action.
- Preserve original/high-resolution embedded PNG/JPEG images.
- Attach only safely resolved CCCD evidence.
- Show a compact attached/unresolved result in case detail.
- Keep existing PDF-only and PDF-plus-roster flows unchanged.
- Persist enough mapping provenance to add manual confirmation later without
  re-extracting the workbook.

## Non-Goals

- Manual confirm, assign, reassign, replace, or detach actions.
- A CCCD mapping panel or candidate thumbnails outside the packet viewer.
- Uploading or replacing a CCCD workbook after case creation.
- Backfilling existing cases.
- G-DOC missing-CCCD attention.
- Name-only, fuzzy, CMND, position-based, order-based, or packet-OCR-only
  automatic attachment.
- Authenticity, expiry, tampering, face, QR, liveness, or government lookup.
- External/cloud OCR.
- Treating OCR as a reviewer verdict.

## User Experience

### Upload

`UploadScreen` adds a third chooser:

`Chọn file ảnh CCCD Excel (tuỳ chọn)`

Helper text:

`Nên dùng ảnh gốc hoặc ảnh độ phân giải cao, được chèn trực tiếp trong file .xlsx.`

Rules:

- PDF remains required.
- Roster remains optional when no CCCD workbook is selected.
- CCCD workbook is optional and accepts `.xlsx` only.
- When CCCD is selected without a roster, `Bắt đầu xử lý` is disabled.
- The inline validation message is:

  `Cần bảng kê để tự động ghép CCCD.`

Removing the CCCD file immediately restores the existing roster-optional
behavior.

### Processing

After packet OCR, progress uses:

```text
stage: cccd
label: Đọc và ghép ảnh CCCD…
```

CCCD progress counts candidate image sets, not raw OCR words or identities.

### Case Detail

When a CCCD workbook was supplied, show one compact line:

`CCCD: <attached> đã gắn · <unresolved> chưa ghép`

When CCCD processing failed:

`CCCD: Không xử lý được file ảnh`

No names, full CCCD values, workbook coordinates, or raw OCR text appear in
this summary.

### Packet Review

An automatically attached candidate adds document tabs:

- `CCCD (Excel) · Mặt trước`
- `CCCD (Excel) · Mặt sau`, when a safe pair exists

The existing document viewer supplies scrolling, zoom, and page switching.
A1 points to the mapped front image and its located number box but keeps
`autostatus: "review"`; OCR never becomes the reviewer verdict.

## Upload API

Extend the existing multipart request:

```http
POST /api/cases
pdf=<required PDF>
roster=<optional XLSX>
cccd=<optional XLSX>
```

The successful response remains:

```json
{ "case_id": "..." }
```

Validation:

- `cccd` without `roster` returns HTTP 422 with safe code
  `cccd-requires-roster`.
- A CCCD filename not ending in `.xlsx` returns HTTP 422 with
  `invalid-cccd-workbook`.
- A CCCD upload over 100 MB returns HTTP 413 with
  `cccd-workbook-too-large`.
- Failed synchronous upload validation leaves no case directory or case index
  entry.

Routine errors contain no names, CCCD values, workbook cells, or OCR text.

## Frontend Contract

Extend:

```ts
createCase(pdf: File, roster?: File, cccd?: File)
```

When `cccd` exists, append it to the multipart form as `cccd`.

Extend the live progress labels with `cccd`.

Add a compact nullable summary to case detail:

```ts
interface CccdSummary {
  status: "ready" | "partial" | "error"
  candidates: number
  attached: number
  unresolved: number
  errorCode?: string
}
```

`CaseDetail` gains:

```ts
cccdName: string | null
cccdSummary: CccdSummary | null
```

The case-list response remains unchanged in this slice.

## Backend Boundaries

### Case Creation

`server/app.py` accepts the optional CCCD upload, validates the cross-field
rule and file limits, and stores it as:

`<case-dir>/cccd.xlsx`

`CaseStore.create` records `cccdName`. `_run_case` receives the optional path
and passes it to the pipeline.

### Pipeline

Extend compatibly:

```python
run_pipeline(
    pdf_path,
    roster_path,
    job_dir,
    progress_cb,
    cccd_xlsx_path=None,
) -> {
    "summary": ...,
    "packets": ...,
    "cccdWorkbook": ...,
}
```

Calls omitting `cccd_xlsx_path` behave exactly as they do now.

The PDF pipeline finishes packet creation and roster matching before CCCD
ingest. If a CCCD path exists, it emits the `cccd` progress stage and calls
the production orchestrator.

The pipeline may write packet manifests and CCCD assets under the case
directory. It never reads or writes `case.json`.

### Production Orchestrator

Create `server/cccd_ingest.py`. It reuses:

- `cccd_workbook.extract_drawings`
- `cccd_ocr.analyze_drawing`
- `cccd_pairing.pair_drawings`
- `cccd_matching.resolve_candidates`

It does not call `cccd_spike.run_spike` and does not require reviewer ground
truth.

Inputs:

- CCCD workbook path
- normalized roster rows
- processed packet metadata
- packet manifest paths
- case-owned CCCD asset directory
- progress callback

Outputs:

- updated packet metadata/manifests
- durable `cccdWorkbook` metadata

## Automatic Attachment Algorithm

1. Extract supported embedded PNG/JPEG drawing instances through OOXML
   relationships.
2. Analyze orientation, side, labeled number region, digits, name, and
   confidence locally.
3. Pair only safe mutual-nearest opposite sides.
4. Resolve candidates against duplicate-aware roster indexes.
5. Consider only resolutions with `state == "exact"`.
6. Convert the opaque `roster-N` key back to that normalized roster row.
7. Normalize the roster row's 12-digit CCCD.
8. Find processed packets whose `rosterIdentity.cccd` exactly equals that
   roster CCCD.
9. Attach only when exactly one packet matches.
10. If zero or multiple packets match, keep the candidate unresolved.

Automatic attachment is forbidden for:

- no located number region
- fewer or more than 12 digits
- OCR confidence below `0.85`
- fuzzy or edit-distance digits
- 9-digit CMND
- name-only match
- no roster
- duplicate roster CCCD or name
- conflicting name and CCCD
- ambiguous side pairing
- multiple candidate claims
- zero or multiple packet targets

## Evidence Attachment

Use stable document IDs:

- `cccd-excel-<candidate-id>-front`
- `cccd-excel-<candidate-id>-back`

For every confirmed candidate:

1. Copy the accepted image into the target packet directory using a
   server-generated filename.
2. Add a one-page `id_front` or `id_back` document to the packet manifest.
3. Record width and height from the validated image.
4. For the front, add the located CCCD source/bbox to the existing `cccd`
   field and route A1 to that evidence.
5. Rebuild checklist items with A1 still in reviewer-controlled state.
6. Write the manifest atomically.

Re-running the same ingest is idempotent: documents owned by the same stable
candidate ID are replaced, not duplicated. Existing PDF-derived documents
and sources are never removed.

## Persistent Data

`case.json` gains:

```json
{
  "cccdName": "CCCD.xlsx",
  "cccdWorkbook": {
    "status": "ready",
    "summary": {
      "candidates": 27,
      "attached": 24,
      "unresolved": 3
    },
    "mappings": []
  }
}
```

The server persists all attached and unresolved mappings. Each mapping keeps:

- stable candidate ID
- front/back image metadata and case-relative paths
- sheet anchor
- OCR identity and confidences
- number bbox
- state
- attached packet index or null
- match method
- issue codes

`GET /api/cases/{id}` returns `cccdName` and only the compact
`cccdSummary`. It does not inline mappings, OCR values, image paths, or
anchors.

`CaseStore.set_result` receives `cccd_workbook` from the pipeline and owns the
`case.json` write:

```python
CaseStore.set_result(
    cid,
    summary=result.get("summary"),
    packets=result.get("packets", []),
    cccd_workbook=result.get("cccdWorkbook"),
)
```

Existing cases normalize missing `cccdName` and `cccdWorkbook` to `null`.
Deleting a case removes the source workbook, extracted images, packet copies,
and metadata because they remain under the case directory.

## Status and Error Handling

Workbook status:

- `ready` — every candidate processed; unresolved may still exist
- `partial` — one or more per-image extraction/OCR/pairing failures occurred
- `error` — workbook-level ingest could not produce a usable result

Rules:

- Workbook-level or individual CCCD failures do not fail the packet case.
- The orchestrator catches CCCD-specific failures and returns a safe
  `cccdWorkbook` error/partial result.
- A malformed, unsupported, ambiguous, low-confidence, duplicate, or
  conflicting candidate attaches nothing.
- An attachment/manifest write failure leaves no false confirmed mapping.
- The packet case remains reviewable with its PDF-derived evidence.
- There is no retry/replacement action in this slice; the user may delete and
  recreate the case.

Safe error codes include:

- `invalid-workbook`
- `no-supported-images`
- `extraction-incomplete`
- `ocr-unavailable`
- `attachment-failed`

Raw exception messages do not enter list/detail API responses.

## Privacy and Security

- All CCCD extraction and OCR run on the local backend.
- No CCCD image, name, number, OCR text, or workbook content is sent to
  GreenNode or another external service.
- Do not log full names, CCCD numbers, OCR text, image bytes, image paths, or
  workbook cells.
- Use server-generated file names and case-relative stored paths.
- Never resolve a client-provided filesystem path.
- Enforce existing limits: 100 MB workbook, 500 drawing instances, 25 MB per
  image, 500 MB accepted uncompressed image bytes, and 40 megapixels per
  decoded image.
- Tests, snapshots, docs, and committed fixtures use synthetic PII-free data.

## Compatibility

- Existing multipart clients that omit `cccd` remain valid.
- Existing pipeline calls that omit `cccd_xlsx_path` remain valid.
- Existing `CaseStore.create` and `set_result` callers use optional defaults.
- Existing cases normalize new properties without rewriting unrelated review
  state.
- Existing manifests without mapped CCCD evidence keep current A1 behavior.
- Review completion, flagging, packet progress, and reports retain their
  current meaning.

## Test Strategy

### Frontend

- Third chooser accepts `.xlsx`.
- Selecting CCCD without roster disables submit and shows the exact message.
- Removing CCCD restores roster-optional behavior.
- `createCase` includes multipart `cccd`.
- `cccd` progress label renders.
- Case detail renders ready, partial, and error summaries.

### API and Store

- PDF-only and PDF-plus-roster requests remain unchanged.
- CCCD-plus-roster persists both source files and names.
- CCCD without roster returns 422 and creates no case.
- Invalid extension returns 422; oversized workbook returns 413.
- `_run_case` passes the CCCD path and persists the pipeline result.
- Restart reloads `cccdName`, compact summary, and mappings.
- Legacy cases normalize missing properties.
- Case deletion removes every CCCD artifact.

### Orchestrator

- Exact 12-digit unique high-confidence candidate attaches.
- Confidence `0.84`, fuzzy digits, CMND, no region, name-only, duplicate
  roster values, conflicting evidence, ambiguous pairing, duplicate claims,
  and non-unique packet target do not attach.
- Attached front/back documents use stable IDs.
- A1 points to the front number bbox and remains reviewer-controlled.
- Re-running is idempotent.
- Per-image failure produces `partial`; workbook failure produces `error`.
- Manifest failure rolls back the candidate attachment.
- Only aggregate counts leave the orchestrator through case detail.

### Regression and Browser Smoke

- Full backend and frontend suites pass.
- Production frontend build passes.
- Browser smoke verifies the third chooser, roster requirement, progress
  stage, case summary, and attached document tabs.
- Smoke data is synthetic and contains no real CCCD.

## Acceptance Criteria

1. The user can select PDF, roster, and CCCD workbook in one upload.
2. Submission is blocked when CCCD is selected without a roster.
3. The server independently enforces the same rule.
4. Processing remains entirely local.
5. Only a high-confidence exact unique roster match with one packet target
   attaches.
6. Confirmed front/back images are visible in that packet.
7. Unresolved candidates attach nowhere and appear only in the aggregate
   count.
8. CCCD failure leaves the packet case usable.
9. Existing uploads and cases remain compatible.
10. No real PII enters committed artifacts or routine logs.
