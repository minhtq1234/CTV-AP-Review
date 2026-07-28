# CCCD v1-Native Port Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add local CCCD Excel extraction, conservative exact matching, automatic evidence attachment, and aggregate results to CTV v1 while preserving all existing v1 review behavior.

**Architecture:** Port the proven v2 CCCD processing modules behind v1's existing pipeline and `CaseStore` boundaries; do not merge v2 UI or checklist code. `server/cccd_ingest.py` owns orchestration and atomic manifest evidence updates, the pipeline returns `cccdWorkbook`, and `CaseStore.set_result` alone persists it. React adds only a third upload control, a progress label, and a compact case-detail summary; attached documents render through v1's existing `EvidenceViewer`.

**Tech Stack:** Python 3, FastAPI, JSON-on-disk `CaseStore`, OOXML `zipfile`/`ElementTree`, Pillow, pytesseract, pytest, React 18, TypeScript 5, Vite 5, and Vitest 2. Approved design: `docs/superpowers/specs/2026-07-28-cccd-v1-native-port-design.md`.

## Global Constraints

- Work only in `/Users/lap16603/Documents/New project/work/CTV_APReview-v1` on branch `ver1`.
- Keep v1 ports `5174`/`8001`; do not modify or depend on the v2 runtime.
- Preserve v1 packet overview, status filters, rejection, field review, completion, and reporting semantics.
- Automatic attachment requires a located exact 12-digit CCCD, confidence `>= 0.85`, one unique roster identity, and one packet target.
- Name-only, fuzzy, CMND, low-confidence, ambiguous, conflicting, duplicate, or non-unique results never attach.
- CCCD without a roster is blocked in both browser and API.
- No manual mapping UI, post-creation upload, backfill, or packet-level missing-CCCD attention in this release.
- All OCR remains local. Never log or commit real names, CCCD values, OCR text, images, workbooks, manifests, or case data.
- Use synthetic PII-free fixtures in tests.
- Workbook limits: 100 MB archive, 500 drawings, 25 MB per image, 500 MB accepted uncompressed images, and 40 megapixels per decoded image.
- Do not push without an explicit user request.

---

### Task 1: Port the bounded OOXML and roster readers

**Files:**
- Create: `server/ooxml.py`
- Create: `server/roster_workbook.py`
- Create: `server/roster_workbook_test.py`
- Modify: `server/pipeline.py`
- Test: `server/pipeline_test.py`

**Interfaces:**
- Produces: `load_roster_rows(source) -> list[list]`
- Preserves: `all_roster_rows(rows) -> list[dict[str, str]]` as the normalized
  identity rows consumed by CCCD matching.
- Produces: duplicate-aware roster rows accepted by later CCCD matching.
- Preserves: v1 `all_roster_rows`, `build_roster_index`, `match_roster`, and existing pipeline results.

- [ ] **Step 1: Add failing safe-roster tests**

Port the PII-free tests from
`codex/cccd-mapping-spike:server/roster_workbook_test.py`, retaining these
exact named behaviors: declared shared-string part traversal, external
relationship rejection, traversal relationship rejection, zip-member and
uncompressed-byte limits, and duplicate-aware CCCD rows. Copy the concrete
synthetic OOXML builders and literal expectations with those tests.

Add a v1 pipeline regression whose production mutation is "the new loader
changes legacy PDF-plus-roster matching":

```python
def test_v1_identity_mapping_accepts_rows_from_safe_loader():
    rows = [["Họ và tên", "Số CCCD"], ["Synthetic A", "000000000001"]]
    assert pipeline.all_roster_rows(rows) == [{
        "name": "Synthetic A",
        "cccd": "000000000001",
        "mst": "",
        "ngaysinh": "",
        "tk": "",
        "phi": "",
        "product": "",
    }]
```

- [ ] **Step 2: Run tests and verify RED**

Run:

```bash
python3 -m pytest server/roster_workbook_test.py server/pipeline_test.py -q
```

Expected: collection/import failure because `roster_workbook` and
`pipeline.load_roster_rows` do not exist.

- [ ] **Step 3: Add the bounded readers and v1 adapter**

Port the final v2 implementations of `server/ooxml.py` and
`server/roster_workbook.py`. In `server/pipeline.py`, expose:

```python
from roster_workbook import load_roster_rows as _load_roster_rows


def load_roster_rows(source) -> list[list]:
    return _load_roster_rows(source)
```

Replace only `dp._roster_rows(roster_path)` with
`load_roster_rows(roster_path)`. Continue passing those rows through v1's
existing `extract_roster_names`, `build_roster_index`, and field-fill logic.

- [ ] **Step 4: Verify GREEN and legacy roster behavior**

Run:

```bash
python3 -m pytest server/roster_workbook_test.py server/pipeline_test.py -q
```

Expected: all selected tests pass.

- [ ] **Step 5: Commit the bounded roster foundation**

```bash
git add server/ooxml.py server/roster_workbook.py server/roster_workbook_test.py server/pipeline.py server/pipeline_test.py
git commit -m "feat: add bounded roster workbook reader"
```

---

### Task 2: Port safe CCCD drawing extraction

**Files:**
- Create: `server/cccd_workbook.py`
- Create: `server/cccd_workbook_test.py`

**Interfaces:**
- Produces: `extract_drawings(xlsx_path, output_dir) -> ExtractionResult`
- Produces: `EmbeddedDrawing` records with stable IDs, sheet anchors, validated
  dimensions, SHA-256, media type, and server-owned stored paths.
- Enforces: archive, relationship, drawing, image-byte, and decoded-pixel limits.

- [ ] **Step 1: Add failing extraction behavior tests**

Port the concrete PII-free fixtures and literal assertions from
`codex/cccd-mapping-spike:server/cccd_workbook_test.py` for these behaviors:
relationship order instead of media-filename order; repeated image bytes as
distinct drawing instances; external/traversal rejection; unsupported and
malformed part rejection; declared and actual uncompressed-byte bounds; total
accepted-image-byte enforcement before the next write; and the 40-megapixel
decoded-image bound.

Every expected drawing order, filename, dimension, hash, and issue code must
be a hand-derived literal.

- [ ] **Step 2: Run tests and verify RED**

Run:

```bash
python3 -m pytest server/cccd_workbook_test.py -q
```

Expected: import failure because `cccd_workbook` does not exist.

- [ ] **Step 3: Add the final safe extractor**

Port the final v2 `server/cccd_workbook.py` implementation, including:

```python
MAX_WORKBOOK_BYTES = 100 * 1024 * 1024
MAX_DRAWINGS = 500
MAX_IMAGE_BYTES = 25 * 1024 * 1024
MAX_TOTAL_IMAGE_BYTES = 500 * 1024 * 1024
MAX_IMAGE_PIXELS = 40_000_000
```

Use the Task 1 OOXML relationship helpers. Generate output filenames from
stable drawing IDs; never trust archive member names as filesystem paths.

- [ ] **Step 4: Verify GREEN**

Run:

```bash
python3 -m pytest server/cccd_workbook_test.py -q
```

Expected: all extraction and limit tests pass.

- [ ] **Step 5: Commit safe extraction**

```bash
git add server/cccd_workbook.py server/cccd_workbook_test.py
git commit -m "feat: extract embedded CCCD drawings safely"
```

---

### Task 3: Port OCR, pairing, and exact matching with the real-image recovery fix

**Files:**
- Create: `server/cccd_ocr.py`
- Create: `server/cccd_ocr_test.py`
- Create: `server/cccd_pairing.py`
- Create: `server/cccd_pairing_test.py`
- Create: `server/cccd_matching.py`
- Create: `server/cccd_matching_test.py`

**Interfaces:**
- Produces: `analyze_drawing(drawing) -> CccdImageOcr`
- Produces: `pair_drawings(analyzed) -> list[CardCandidate]`
- Produces: `resolve_candidates(candidates, roster_rows) -> ResolutionResult`
- Preserves: exact-only automatic resolution and conservative mutual-nearest
  pairing.

- [ ] **Step 1: Add failing OCR recovery tests**

Port the existing synthetic OCR tests, then add these regressions before
production changes:

```python
def test_recovers_unique_twelve_digit_region_when_number_label_is_misread():
    words = [
        OcrWord("CĂN", 0, 0, 45, 24, .96),
        OcrWord("CƯỚC", 50, 0, 55, 24, .96),
        OcrWord("CÔNG", 110, 0, 50, 24, .96),
        OcrWord("DÂN", 165, 0, 40, 24, .96),
        OcrWord("6s:", 20, 80, 30, 20, .71),
        OcrWord("000000000001", 70, 78, 220, 24, .93),
    ]
    assert locate_number_region(words, 400, 250) == {
        "x": 64, "y": 72, "width": 232, "height": 36,
    }


def test_does_not_recover_when_two_twelve_digit_regions_compete():
    words = [
        OcrWord("000000000001", 20, 80, 180, 20, .93),
        OcrWord("000000000002", 20, 120, 180, 20, .93),
    ]
    assert locate_number_region(words, 400, 250) is None


def test_does_not_treat_dates_or_short_tokens_as_number_regions():
    words = [
        OcrWord("01/02/2026", 20, 80, 120, 20, .99),
        OcrWord("123456789", 20, 120, 120, 20, .99),
    ]
    assert locate_number_region(words, 400, 250) is None
```

The tests stub only Tesseract calls; they exercise the real locator,
classifier, normalization, and crop-confidence logic. Add literal structural
classification fixtures for recovered-number-plus-front-marker => `front`,
CCCD MRZ signature => `back`, and simultaneous front/back signals =>
`unknown`.

- [ ] **Step 2: Add failing pairing and matching tests**

Port the concrete synthetic fixtures and literal assertions from
`codex/cccd-mapping-spike:server/cccd_pairing_test.py` and
`server/cccd_matching_test.py` for: accepted mutual-nearest pair; rejected
zero-distance tie; unresolved 20%-margin ambiguity; exact unique
high-confidence resolution; unresolved confidence `0.84`; unresolved
name-only and 9-digit CMND; unresolved duplicate roster/candidate claims; and
unresolved conflicting name/number.

- [ ] **Step 3: Run tests and verify RED**

Run:

```bash
python3 -m pytest server/cccd_ocr_test.py server/cccd_pairing_test.py server/cccd_matching_test.py -q
```

Expected: import failures because the three production modules do not exist.

- [ ] **Step 4: Add OCR analysis and conservative recovery**

Port the final v2 OCR implementation, then implement the approved fallback:

```python
def unique_twelve_digit_word(words):
    candidates = [
        word for word in words
        if len(re.sub(r"\D", "", word.text)) == 12 and valid_bbox(word.bbox)
    ]
    return candidates[0] if len(candidates) == 1 else None
```

`locate_number_region` tries the label path first, then this fallback.
`analyze_drawing` must re-OCR the returned crop with digits-only Tesseract
configuration and use that crop's number/confidence. It must not accept the
full-image word as the final identity.

Add structural side rules only after exact marker scoring:

```python
front = recovered_number is not None and has_front_marker(words)
back = has_cccd_mrz(words) or has_strong_back_marker(words)
side = "unknown" if front and back else "front" if front else "back" if back else "unknown"
```

- [ ] **Step 5: Add unchanged conservative pairing and matching**

Port final v2 `cccd_pairing.py` and `cccd_matching.py`. Keep:

- same-sheet eligibility;
- vertical-overlap/one-row eligibility;
- mutual nearest neighbor;
- 20% alternative margin;
- one-to-one candidates;
- exactly 12 digits and `>= 0.85`;
- duplicate-aware roster indexes;
- exact-only state;
- no fuzzy/name/CMND automatic state.

- [ ] **Step 6: Verify GREEN and mutation protection**

Run:

```bash
python3 -m pytest server/cccd_ocr_test.py server/cccd_pairing_test.py server/cccd_matching_test.py -q
```

Expected: all selected tests pass. Confirm mentally that removing the fallback,
lowering the threshold, accepting a tie, or converting a name match to exact
would fail at least one test.

- [ ] **Step 7: Commit analysis and matching**

```bash
git add server/cccd_ocr.py server/cccd_ocr_test.py server/cccd_pairing.py server/cccd_pairing_test.py server/cccd_matching.py server/cccd_matching_test.py
git commit -m "feat: analyze and match CCCD cards conservatively"
```

---

### Task 4: Build the v1-native ingest and atomic manifest attachment

**Files:**
- Create: `server/cccd_ingest.py`
- Create: `server/cccd_ingest_test.py`

**Interfaces:**
- Consumes: Task 2 extraction and Task 3 OCR/pairing/matching.
- Produces:

```python
ingest_cccd_workbook(
    xlsx_path: str,
    roster_rows: list[dict[str, str]],
    packets: list[dict],
    case_dir: str,
    packet_manifest_paths: dict[int, str],
    assets_dir: str,
    progress_cb,
) -> {
    "packets": list[dict],
    "cccdWorkbook": dict,
}
```

- Mutates: only mapping-owned packet image files and `docs`/`fields[].sources`
  in packet manifests.
- Does not import v2 `checklist.py` or write `case.json`.

- [ ] **Step 1: Add failing planning tests**

Port v2's resolution/provenance test fixtures and assert:

```python
assert mapping["state"] == "exact"
assert mapping["matchedBy"] == "cccd"
assert mapping["attachedPacketIndex"] is None
assert mapping["front"]["storedPath"].startswith("cccd/")
assert mapping["ocrIdentity"]["cccdConfidence"] >= 0.85
```

Add explicit tests for zero/multiple packet targets, duplicate candidate
claims, bool/non-integer packet indexes, unsafe paths, and no roster target.

- [ ] **Step 2: Add failing v1 manifest tests**

Create a synthetic v1 manifest containing `docs` and field-keyed `fields`.
Test the consumer-visible result:

```python
result = attach_planned_mapping(plan, packet, manifest_path, case_dir)
manifest = json.loads(manifest_path.read_text())

assert [doc["label"] for doc in manifest["docs"][-2:]] == [
    "CCCD (Excel) · Mặt trước",
    "CCCD (Excel) · Mặt sau",
]
cccd = next(field for field in manifest["fields"] if field["key"] == "cccd")
assert cccd["sources"][-1] == {
    "docId": f"cccd-excel-{candidate_id}-front",
    "page": 0,
    "value": "000000000001",
    "bbox": {"x": 70, "y": 78, "width": 220, "height": 24},
    "confidence": 0.93,
}
assert result["attachedPacketIndex"] == packet["index"]
```

Also test idempotent rerun, preservation of PDF documents/sources and v1 review
metadata, atomic manifest failure, copy failure, stale-file cleanup, and
partial extraction/OCR failure.

- [ ] **Step 3: Run tests and verify RED**

Run:

```bash
python3 -m pytest server/cccd_ingest_test.py -q
```

Expected: import failure because `cccd_ingest` does not exist.

- [ ] **Step 4: Port the orchestrator without v2 checklist coupling**

Port v2's candidate planning, safe case-relative path checks, stable IDs,
provenance serialization, atomic JSON write, rollback, cleanup, safe error
codes, and summary calculation.

Replace v2's checklist rebuild with v1 field-source attachment only:

```python
cccd_field = next(
    field for field in fields
    if isinstance(field, dict) and field.get("key") == "cccd"
)
cccd_field["sources"] = [
    source for source in cccd_field.get("sources", [])
    if source.get("docId") not in owned_ids
] + [{
    "docId": front_doc_id,
    "page": 0,
    "value": front.ocr.cccd,
    "bbox": front.ocr.number_bbox,
    "confidence": front.ocr.cccd_confidence,
}]
```

Do not modify `expected`, `prediction`, review fields, rejection, packet flags,
or packet lifecycle state.

- [ ] **Step 5: Verify GREEN**

Run:

```bash
python3 -m pytest server/cccd_ingest_test.py -q
```

Expected: all orchestrator and v1 manifest tests pass.

- [ ] **Step 6: Commit the v1 ingest boundary**

```bash
git add server/cccd_ingest.py server/cccd_ingest_test.py
git commit -m "feat: attach exact CCCD evidence to v1 packets"
```

---

### Task 5: Persist and redact CCCD workbook results in the v1 case store

**Files:**
- Modify: `server/cases.py`
- Test: `server/cases_test.py`

**Interfaces:**
- Produces: `compact_cccd_summary(workbook) -> dict | None`
- Extends:

```python
CaseStore.create(
    name: str,
    pdf_name: str,
    roster_name: str | None,
    now: str | None = None,
    cccd_name: str | None = None,
) -> str
CaseStore.set_result(
    cid: str,
    summary: dict | None,
    packets: list[dict],
    cccd_workbook: dict | None = None,
) -> None
```

- Preserves: v1 `normalize_review`, rejection state, field reviews,
  `reviewFieldCount`, status derivation, progress, reports, and case-list shape.

- [ ] **Step 1: Add failing store tests**

Add tests proving:

```python
cid = store.create("case", "packet.pdf", "roster.xlsx", cccd_name="cards.xlsx")
store.set_result(cid, summary, packets, cccd_workbook=workbook)
reloaded = CaseStore(root).get(cid)
assert reloaded["cccdName"] == "cards.xlsx"
assert reloaded["cccdWorkbook"] == workbook
```

Also assert:

- legacy case files normalize missing fields to `None`;
- normalization preserves packet rejection and field reviews;
- `compact_cccd_summary` returns only status/counts/safe error code;
- unknown error codes become `invalid-workbook`;
- `list()` remains byte-for-byte shape-compatible and exposes no CCCD data;
- deleting a case removes source and derived assets beneath its directory.

- [ ] **Step 2: Run tests and verify RED**

Run:

```bash
python3 -m pytest server/cases_test.py -q
```

Expected: missing keyword/signature/summary failures.

- [ ] **Step 3: Implement additive persistence**

Add:

```python
SAFE_CCCD_ERROR_CODES = (
    "invalid-workbook",
    "no-supported-images",
    "extraction-incomplete",
    "ocr-unavailable",
    "attachment-failed",
)
```

Normalize `cccdName`/`cccdWorkbook` in `_load` without changing existing review
migration. Extend `create` and `set_result` with trailing optional parameters.
Keep `compact_cccd_summary` numeric and safe.

- [ ] **Step 4: Verify GREEN**

Run:

```bash
python3 -m pytest server/cases_test.py -q
```

Expected: all store tests pass, including existing rejection tests.

- [ ] **Step 5: Commit persistence**

```bash
git add server/cases.py server/cases_test.py
git commit -m "feat: persist CCCD workbook results in v1 cases"
```

---

### Task 6: Run CCCD ingest after v1 packet creation

**Files:**
- Modify: `server/pipeline.py`
- Test: `server/pipeline_test.py`

**Interfaces:**
- Consumes: `ingest_cccd_workbook` and Task 1 normalized roster rows.
- Extends:

```python
run_pipeline(
    pdf_path,
    roster_path,
    job_dir,
    progress_cb,
    cccd_xlsx_path=None,
) -> dict
```

- Returns: existing `summary`/`packets` plus nullable `cccdWorkbook`.

- [ ] **Step 1: Add failing pipeline integration tests**

Add tests that monkeypatch only PDF/OCR and CCCD ingest boundaries:

```python
calls = []
pipeline.ingest_cccd_workbook = lambda *args: (
    calls.append(args) or ingest_result
)
def record_progress(stage, done, total, detail):
    progress.append((stage, done, total, detail))

result = run_pipeline(pdf, roster, job_dir, record_progress, cccd_xlsx_path=cccd)
assert len(calls) == 1
assert result["cccdWorkbook"] == synthetic_workbook
assert result["packets"] == ingest_result["packets"]
```

Also prove:

- no CCCD path never calls ingest and preserves existing return behavior;
- CCCD stage occurs after the last packet manifest exists;
- roster rows passed to ingest preserve all identity fields;
- `cccdWorkbook` stays absent or `None` for legacy calls;
- v1 packet metadata and manifests remain the input to the orchestrator.

- [ ] **Step 2: Run tests and verify RED**

Run:

```bash
python3 -m pytest server/pipeline_test.py -q
```

Expected: `run_pipeline` rejects `cccd_xlsx_path`.

- [ ] **Step 3: Extend the pipeline compatibly**

After the existing OCR loop and summary creation:

```python
result = {"summary": summary, "packets": packets_out}
if cccd_xlsx_path:
    progress_cb("cccd", 0, 0, "")
    manifests = {
        packet["index"]: os.path.join(
            job_dir, "packets", str(packet["index"]), "manifest.json"
        )
        for packet in packets_out
    }
    cccd_result = ingest_cccd_workbook(
        cccd_xlsx_path,
        all_roster_rows(roster_rows_raw or []),
        packets_out,
        job_dir,
        manifests,
        os.path.join(job_dir, "cccd"),
        progress_cb,
    )
    result["packets"] = cccd_result["packets"]
    result["cccdWorkbook"] = cccd_result["cccdWorkbook"]
return result
```

Keep all existing split/OCR/match/manifest behavior before this block.

- [ ] **Step 4: Verify GREEN**

Run:

```bash
python3 -m pytest server/pipeline_test.py -q
```

Expected: all pipeline tests pass.

- [ ] **Step 5: Commit pipeline integration**

```bash
git add server/pipeline.py server/pipeline_test.py
git commit -m "feat: run CCCD ingest in the v1 pipeline"
```

---

### Task 7: Accept and validate CCCD uploads in the v1 API

**Files:**
- Modify: `server/app.py`
- Test: `server/app_test.py`

**Interfaces:**
- Extends: `POST /api/cases` multipart with optional `cccd`.
- Extends: `_run_case(cid, pdf_path, roster_path, cccd_path=None)`.
- Extends: `GET /api/cases/{cid}` with `cccdName` and redacted `cccdSummary`.
- Preserves: v1 review body with `fields` and `rejection`.

- [ ] **Step 1: Add failing upload validation tests**

Add concrete API tests with synthetic multipart bodies for: CCCD without
roster returns 422 and creates no case; invalid CCCD extension returns safe
422; oversized CCCD returns safe 413; invalid roster is rejected before case
creation; valid PDF/roster/CCCD parts are saved under the case directory; and
`_run_case` passes the CCCD path and persists the returned workbook. Reuse the
bounded synthetic XLSX builder from the roster tests instead of arbitrary zip
bytes.

Use synthetic in-memory OOXML parts and assert safe response codes, case
directory count, stored basenames, and pipeline arguments. Never assert or log
real identity text.

- [ ] **Step 2: Add failing detail-redaction tests**

Persist a workbook with private mapping fields, then assert:

```python
body = client.get(f"/api/cases/{cid}").json()
assert body["cccdName"] == "cards.xlsx"
assert body["cccdSummary"] == {
    "status": "ready",
    "candidates": 3,
    "attached": 2,
    "unresolved": 1,
}
assert "cccdWorkbook" not in body
assert "mappings" not in json.dumps(body)
```

Also retain existing `reviewFieldCount`, rejection PUT, report, manifest, and
page-serving tests.

- [ ] **Step 3: Run tests and verify RED**

Run:

```bash
python3 -m pytest server/app_test.py -q
```

Expected: the route ignores `cccd`, validation codes are absent, and detail
does not expose `cccdSummary`.

- [ ] **Step 4: Implement synchronous safe validation**

Before `store.create`, enforce:

```python
if cccd is not None and roster is None:
    raise HTTPException(422, detail={"code": "cccd-requires-roster"})
if cccd is not None and not filename.casefold().endswith(".xlsx"):
    raise HTTPException(422, detail={"code": "invalid-cccd-workbook"})
if cccd is not None and upload_size(cccd) > MAX_WORKBOOK_BYTES:
    raise HTTPException(413, detail={"code": "cccd-workbook-too-large"})
```

Preflight roster workbooks through Task 1's bounded loader in a threadpool and
rewind the stream. Create the case only after every synchronous check passes.
Save the source as `cccd.xlsx`.

- [ ] **Step 5: Wire worker persistence and redacted detail**

Call:

```python
result = run_pipeline(
    pdf_path, roster_path, case_dir, cb, cccd_xlsx_path=cccd_path
)
store.set_result(
    cid,
    summary=result.get("summary"),
    packets=result.get("packets", []),
    cccd_workbook=result.get("cccdWorkbook"),
)
```

In detail response, remove `cccdWorkbook` and add
`compact_cccd_summary(case.get("cccdWorkbook"))`. Do not alter the v1
`PacketRejectionBody`, `ReviewBody`, `_packet_for_response`, or report routes.

- [ ] **Step 6: Verify GREEN**

Run:

```bash
python3 -m pytest server/app_test.py -q
```

Expected: all new and existing API tests pass.

- [ ] **Step 7: Commit API integration**

```bash
git add server/app.py server/app_test.py
git commit -m "feat: accept CCCD workbooks in the v1 API"
```

---

### Task 8: Add the v1 upload control and client contract

**Files:**
- Create: `src/upload/cccd.ts`
- Create: `src/upload/cccd.test.ts`
- Modify: `src/upload/api.ts`
- Test: `src/upload/api.test.ts`
- Modify: `src/components/UploadScreen.tsx`
- Create: `src/components/UploadScreen.test.tsx`
- Modify: `src/components/UploadFlow.tsx`
- Modify: `src/styles.css`

**Interfaces:**
- Extends: `createCase(pdf, roster?, cccd?)`.
- Extends: `UploadScreen.onStart(pdf, roster?, cccd?)`.
- Produces: pure `canStartUpload`, `cccdRequirementMessage`, and
  `formatCccdSummary`.

- [ ] **Step 1: Add failing pure eligibility tests**

Create:

```ts
expect(canStartUpload(true, false, true, false)).toBe(false)
expect(cccdRequirementMessage(false, true))
  .toBe('Cần bảng kê để tự động ghép CCCD.')
expect(canStartUpload(true, true, true, false)).toBe(true)
expect(canStartUpload(true, false, false, false)).toBe(true)
```

Also test busy/no-PDF and summary formatting for ready/partial/error.

- [ ] **Step 2: Add failing API and component tests**

In `src/upload/api.test.ts`, call `createCase` and inspect the real `FormData`:

```ts
expect(body.get('pdf')).toBe(pdf)
expect(body.get('roster')).toBe(roster)
expect(body.get('cccd')).toBe(cccd)
```

Add a Testing Library component test proving:

- the third input accepts `.xlsx`;
- selecting CCCD without roster shows the exact alert and disables submit;
- adding roster enables submit and passes all three `File` objects;
- clearing CCCD restores the roster-optional state.

- [ ] **Step 3: Run tests and verify RED**

Run:

```bash
npm test -- src/upload/cccd.test.ts src/upload/api.test.ts src/components/UploadScreen.test.tsx
```

Expected: missing module/signature/control failures.

- [ ] **Step 4: Implement the pure helper and API extension**

Add:

```ts
export const CCCD_ROSTER_REQUIRED = 'Cần bảng kê để tự động ghép CCCD.'

export function cccdRequirementMessage(hasRoster: boolean, hasCccd: boolean) {
  return hasCccd && !hasRoster ? CCCD_ROSTER_REQUIRED : null
}

export function canStartUpload(
  hasPdf: boolean, hasRoster: boolean, hasCccd: boolean, busy: boolean,
) {
  return hasPdf && !busy && cccdRequirementMessage(hasRoster, hasCccd) === null
}
```

Extend `createCase` and append `cccd` only when present. Add `cccd` to
`STAGE_LABELS` as `Đọc và ghép ảnh CCCD…`.

- [ ] **Step 5: Add the chooser without changing v1 flow ownership**

Add local `cccd` state, `.xlsx` input, high-resolution helper, clear button,
alert, and disabled-state calculation to `UploadScreen`. Extend only the
`onStart` plumbing in `UploadFlow`; keep its polling, navigation, packet
opening, and report behavior unchanged.

- [ ] **Step 6: Verify GREEN**

Run:

```bash
npm test -- src/upload/cccd.test.ts src/upload/api.test.ts src/components/UploadScreen.test.tsx
```

Expected: all selected frontend tests pass.

- [ ] **Step 7: Commit the upload UX**

```bash
git add src/upload/cccd.ts src/upload/cccd.test.ts src/upload/api.ts src/upload/api.test.ts src/components/UploadScreen.tsx src/components/UploadScreen.test.tsx src/components/UploadFlow.tsx src/styles.css
git commit -m "feat: add CCCD workbook upload to v1"
```

---

### Task 9: Show aggregate CCCD results on the v1 packet dashboard

**Files:**
- Modify: `src/upload/api.ts`
- Modify: `src/components/CaseDetail.tsx`
- Test: `src/components/caseDetail.test.tsx`
- Modify: `src/styles.css`

**Interfaces:**
- Adds: `CccdSummary`, `CaseDetail.cccdName`, and
  `CaseDetail.cccdSummary`.
- Consumes: `formatCccdSummary`.
- Preserves: v1 `PacketDashboardView`, lifecycle status filters, attention-first
  ordering, rejection summary, and export action.

- [ ] **Step 1: Add failing dashboard rendering tests**

Render v1 `CaseDetail` with:

```ts
cccdName: 'cards.xlsx',
cccdSummary: {
  status: 'ready',
  candidates: 3,
  attached: 2,
  unresolved: 1,
}
```

Assert visible copy `CCCD: 2 đã gắn · 1 chưa ghép`. Add partial and error
cases, and assert absent summary when `cccdName`/`cccdSummary` is null.

The same render must still expose the existing status filter buttons,
attention-first control, packet rejection count, and report action.

- [ ] **Step 2: Run tests and verify RED**

Run:

```bash
npm test -- src/components/caseDetail.test.tsx src/logic/packetDashboard.test.ts
```

Expected: no CCCD summary exists.

- [ ] **Step 3: Add types and compact presentation**

Add:

```ts
export interface CccdSummary {
  status: 'ready' | 'partial' | 'error'
  candidates: number
  attached: number
  unresolved: number
  errorCode?: string
}
```

Render one `cccd-summary` line between the split result banner and v1
`case-summary`. Use generic error copy and never interpolate `errorCode`.

- [ ] **Step 4: Verify GREEN**

Run:

```bash
npm test -- src/components/caseDetail.test.tsx src/logic/packetDashboard.test.ts
```

Expected: all selected tests pass.

- [ ] **Step 5: Commit the dashboard summary**

```bash
git add src/upload/api.ts src/components/CaseDetail.tsx src/components/caseDetail.test.tsx src/styles.css
git commit -m "feat: show CCCD attachment summary in v1"
```

---

### Task 10: Full regression, real-workbook safety check, and v1 browser smoke

**Files:**
- Modify only if a failing verification reveals a product defect.
- Do not add the real workbook, extracted images, OCR output, case data, or
  screenshots to git.

**Interfaces:**
- Verifies all acceptance criteria and v1 compatibility.

- [ ] **Step 1: Run the complete automated suites**

Run:

```bash
npm test
python3 -m pytest server splitter -q
npm run build
git diff --check
```

Expected: zero failures and build exit code 0.

- [ ] **Step 2: Run a local synthetic integration case**

Create a temporary synthetic packet/roster/CCCD fixture outside the repository
or under pytest's temp directory. Verify:

- one exact candidate attaches;
- one low-confidence or unmatched candidate remains unresolved;
- attached front/back documents load from v1 API page routes;
- the mapped front source routes v1's `cccd` field to the correct bbox;
- packet review/rejection survives the manifest change.

- [ ] **Step 3: Run the supplied workbook as an uncommitted diagnostic**

Use `/Users/lap16603/Downloads/CCCD_T2.xlsx` only locally with its matching
roster and processed packet inputs. Record aggregate counts in terminal output
only. Verify every attachment satisfies:

```text
12 digits AND confidence >= 0.85
AND unique roster identity
AND exactly one packet target
AND safe front/back pair
```

If no complete pair attaches, report the observed aggregate and keep every
candidate unresolved; do not relax a safety gate.

- [ ] **Step 4: Launch isolated v1 ports**

Run backend on `127.0.0.1:8001` and frontend on `127.0.0.1:5174`. Confirm both
health/navigation paths before browser interaction.

- [ ] **Step 5: Browser smoke the complete v1 flow**

At `http://127.0.0.1:5174/`, verify:

1. third chooser and high-resolution helper are visible;
2. CCCD without roster blocks submission with exact Vietnamese copy;
3. normal PDF-only behavior remains available after clearing CCCD;
4. processing shows `Đọc và ghép ảnh CCCD…`;
5. case detail retains all v1 filters/status/rejection controls and shows the
   compact CCCD summary;
6. an attached packet retains v1 Overview and displays CCCD front/back tabs;
7. viewer scrolling, zoom, one/two-page mode, source navigation, rejection,
   completion, and packet navigation still work; and
8. browser console contains no errors.

- [ ] **Step 6: Perform the privacy and scope audit**

Run:

```bash
git status --short
git diff --name-only
git diff --check
```

Confirm no file outside the approved v1 checkout changed, no real PII artifact
is tracked, no v2 UI/checklist code entered v1, and `server/data` remains
untracked/ignored.

- [ ] **Step 7: Commit only remediation, if any**

If verification required code changes, repeat the failing test's RED/GREEN
cycle and commit:

```bash
git add server/affected_file.py src/affected_file.ts
git commit -m "fix: harden CCCD v1 integration"
```

Replace the example paths with the exact files changed by the verified defect.
If no remediation was needed, create no empty commit.
