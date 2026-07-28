# CCCD v1-Native Port Design

**Status:** Approved, 2026-07-28

## Purpose

Add the tested CCCD Excel upload and automatic packet attachment flow to CTV
v1 without replacing v1's packet overview, lifecycle statuses, rejection flow,
field review, or document-view behavior.

This specification supersedes
`2026-07-27-cccd-image-to-packet-mapping-design.md` for the first release.
The earlier manual mapping panel, manual assign/reassign/detach operations, and
packet-level missing-CCCD attention flags remain deferred.

This work applies only to:

`/Users/lap16603/Documents/New project/work/CTV_APReview-v1`

The v2 checkout remains reference material only. V1 continues to use frontend
port `5174` and backend port `8001`.

## Product Decisions

1. V1 receives a selective port of the CCCD processing modules and minimal UI
   hooks. V2 review components and styles are not merged into v1.
2. The upload screen adds an optional CCCD `.xlsx` input.
3. Selecting a CCCD workbook requires a roster workbook. The browser and server
   both block submission without one.
4. Extraction and OCR run locally.
5. Only a located, exact 12-digit CCCD with OCR confidence `>= 0.85`, a unique
   roster identity, and exactly one packet target may attach automatically.
6. Name-only, fuzzy, 9-digit CMND, ambiguous, conflicting, or low-confidence
   results never attach.
7. Unresolved candidates remain persisted with provenance but appear only as
   an aggregate count in this release.
8. Safely attached front/back images become documents in the existing v1
   viewer.
9. CCCD processing failure never makes an otherwise usable packet case fail.
10. No post-creation CCCD upload and no manual mapping UI are included.

## User Experience

### Upload

The existing v1 upload card adds:

`Chọn file ảnh CCCD Excel (tuỳ chọn)`

Helper text:

`Nên dùng ảnh gốc hoặc ảnh độ phân giải cao, được chèn trực tiếp trong file .xlsx.`

Rules:

- PDF remains required.
- Roster remains optional when no CCCD workbook is selected.
- CCCD accepts `.xlsx` only.
- CCCD without roster disables `Bắt đầu xử lý` and shows:
  `Cần bảng kê để tự động ghép CCCD.`
- Removing the CCCD selection restores the existing roster-optional flow.

### Processing

After packet creation and roster alignment, progress emits:

```text
stage: cccd
label: Đọc và ghép ảnh CCCD…
```

### Case Detail

When a CCCD workbook was supplied, v1's case dashboard shows:

`CCCD: <attached> đã gắn · <unresolved> chưa ghép`

If workbook processing failed:

`CCCD: Không xử lý được file ảnh`

The summary contains no names, full CCCD values, OCR text, workbook
coordinates, or filesystem paths.

### Packet Review

An automatically attached candidate adds tabs to the existing v1
`EvidenceViewer`:

- `CCCD (Excel) · Mặt trước`
- `CCCD (Excel) · Mặt sau`, when safely paired

The images participate in v1's existing scrolling, zoom, one-page/two-page
view, annotation, overview, and field-source navigation. They do not change
packet lifecycle status, review completion, packet rejection, or reporting.

## Backend Architecture

The port reuses the proven v2 module boundaries but integrates them into v1's
contracts:

- `server/ooxml.py` safely traverses OOXML relationships.
- `server/roster_workbook.py` reads normalized roster identities with duplicate
  detection.
- `server/cccd_workbook.py` extracts and validates embedded PNG/JPEG drawing
  instances.
- `server/cccd_ocr.py` classifies sides and locates identity evidence.
- `server/cccd_pairing.py` creates conservative, one-to-one front/back
  candidates.
- `server/cccd_matching.py` resolves only exact, unique roster matches.
- `server/cccd_ingest.py` orchestrates extraction, OCR, pairing, matching, and
  atomic evidence attachment.

The orchestrator receives normalized roster rows, processed v1 packets, packet
manifest paths, and a case-owned asset directory. It returns updated packet
metadata plus durable `cccdWorkbook` metadata. It never reads or writes
`case.json`.

`CaseStore.set_result` remains the owner of `case.json`.

## OCR Reliability Fix

The v2 test showed that Tesseract could read real 12-digit CCCD values while
the adapter discarded them when the printed `Số` label was misread. V1
includes the following conservative repair:

1. Keep label-anchored number location as the preferred path.
2. If it fails, accept a full-image OCR word only when it contains exactly 12
   digits, has a real Tesseract bounding box, and is the sole best candidate.
3. Re-OCR that bounding box using the digits-only crop. The crop supplies the
   final number and confidence.
4. Classify a front structurally only when a unique recovered 12-digit number
   and a front marker are both present.
5. Classify a back from a strong CCCD MRZ signature or strong back marker.
6. Conflicting front/back signals remain `unknown`.

Dates, shorter/longer digit runs, arbitrary OCR text, and multiple competing
12-digit regions never qualify as fallback identity regions.

These changes do not relax the exact unique roster match, confidence
threshold, pairing margin, duplicate-candidate, or single-packet-target gates.

## API and Persistence

Extend case creation:

```http
POST /api/cases
pdf=<required PDF>
roster=<optional XLSX>
cccd=<optional XLSX>
```

Validation:

- `cccd` without `roster`: HTTP 422, `cccd-requires-roster`
- invalid CCCD extension: HTTP 422, `invalid-cccd-workbook`
- CCCD over 100 MB: HTTP 413, `cccd-workbook-too-large`
- failed synchronous validation creates no case directory or index entry

Extend pipeline compatibly:

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

Existing calls that omit `cccd_xlsx_path` behave unchanged.

`case.json` gains additive nullable fields:

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

Every attached and unresolved mapping persists its stable candidate ID,
front/back metadata, case-relative asset paths, anchor, normalized OCR
identity and confidence, number bounding box, resolution state, attached
packet index or null, match method, and safe issue codes.

`GET /api/cases/{id}` exposes only:

```ts
interface CccdSummary {
  status: "ready" | "partial" | "error"
  candidates: number
  attached: number
  unresolved: number
  errorCode?: string
}
```

Existing cases normalize missing CCCD fields to `null`.

## Evidence Attachment

Use stable document IDs:

- `cccd-excel-<candidate-id>-front`
- `cccd-excel-<candidate-id>-back`

For a confirmed candidate:

1. copy accepted images into the target packet directory with
   server-generated filenames;
2. append one-page `id_front`/`id_back` documents to the existing manifest;
3. preserve validated natural image dimensions;
4. add the located front CCCD number as a source for v1's `cccd` review field;
5. write the manifest atomically; and
6. mark the mapping attached only after all evidence writes succeed.

Re-running ingest is idempotent. Existing PDF-derived evidence, expected
values, review state, rejection state, and unrelated field sources are never
removed.

## Limits, Privacy, and Failure Handling

- Process locally; no CCCD images or OCR text leave the workstation.
- Do not log names, CCCD numbers, OCR text, workbook contents, or image bytes.
- Store all source and derived assets under the case directory.
- Limit CCCD workbooks to 100 MB, 500 drawings, 25 MB per image, 500 MB total
  accepted uncompressed image bytes, and 40 megapixels per decoded image.
- Accept only relationship-resolved embedded PNG/JPEG drawings.
- Reject external relationships, traversal paths, unsupported media, malformed
  drawings, and invalid images safely.
- Workbook-level failure returns a safe `error` summary.
- Per-image failures produce `partial` and preserve every usable candidate.
- Evidence write failure leaves no false attached mapping.
- Tests and committed fixtures use synthetic PII-free data only.

## Compatibility

- PDF-only and PDF-plus-roster upload behavior remains unchanged.
- Existing cases load without migration.
- V1 packet overview, attention/filter logic, lifecycle statuses, rejection
  flow, field review, progress counts, and reports keep their meanings.
- The case-list response remains unchanged.
- The v2 checkout and its ports/data remain untouched.

## Acceptance Criteria

1. V1 can submit PDF, roster, and CCCD workbook together.
2. CCCD submission without roster is blocked in browser and API.
3. Only exact, high-confidence, unique 12-digit roster matches with one packet
   target attach.
4. OCR recovers a uniquely located real-shaped 12-digit region even when the
   `Số` label is misread, without admitting dates or ambiguous digit regions.
5. Safely attached front/back images appear in the correct v1 packet viewer.
6. Unresolved candidates attach nowhere and appear only in the case aggregate.
7. CCCD processing failure leaves the packet case reviewable.
8. Existing v1 review, status, rejection, and reporting tests remain green.
9. Persistence survives backend restart and deletion removes all CCCD assets.
10. Full frontend tests, backend/splitter tests, production build, and browser
    smoke at `http://127.0.0.1:5174/` pass without real PII.
