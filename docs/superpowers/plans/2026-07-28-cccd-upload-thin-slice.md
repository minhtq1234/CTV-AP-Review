# CCCD Upload and Automatic Attachment Thin Slice Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let a reviewer create a case with a packet PDF, roster workbook, and optional CCCD image workbook; attach only exact, high-confidence, unambiguous CCCD evidence to one packet; and show only aggregate CCCD results in case detail.

**Architecture:** Extend the existing case upload and persistence boundaries without changing the case-list contract. A new production `cccd_ingest` orchestrator reuses the Phase 0 OOXML extraction, local OCR, safe pairing, and exact matching modules, writes packet-owned image evidence and manifests atomically, and returns durable provenance to `CaseStore.set_result`; the API redacts that provenance to a compact summary. The React upload flow adds a third file input and the case detail adds one aggregate result line, while the existing packet viewer renders the attached front/back documents unchanged.

**Tech Stack:** Python 3, FastAPI, JSON-on-disk `CaseStore`, OOXML `zipfile` extraction, Pillow, pytesseract, pytest, React 18, TypeScript 5, Vite 5, and Vitest 2. Approved design: `docs/superpowers/specs/2026-07-28-cccd-upload-thin-slice-design.md`.

## Global Constraints

- CCCD upload remains optional; when supplied, a roster workbook is mandatory in both browser and API.
- Only a located, exact 12-digit CCCD read with confidence `>= 0.85`, a unique roster identity, and exactly one packet target may attach automatically.
- Name-only, fuzzy, 9-digit CMND, ambiguous, duplicate, conflicting, or low-confidence candidates never attach.
- All extraction and OCR remain local; do not call `cccd_spike.run_spike`, GreenNode, or another external service.
- Never log or return through case-list/detail APIs a CCCD number, name, OCR text, workbook cell, anchor, image path, or mapping record.
- Preserve the tested limits: 100 MB workbook, 500 drawing instances, 25 MB per image, 500 MB accepted uncompressed image bytes, and 40 megapixels per decoded image.
- Store source workbook, extracted assets, packet image copies, and mapping metadata below the case directory so case deletion removes them together.
- `run_pipeline` never reads or writes `case.json`; `CaseStore.set_result` remains the only owner of the result write.
- CCCD ingest failure must not fail or erase an otherwise reviewable PDF packet case.
- Existing PDF-only and PDF-plus-roster clients, pipeline calls, cases, review state, reports, and manifests remain compatible.
- A1 routes to the attached CCCD front number box but remains `autostatus: "review"`; OCR is evidence, not a reviewer verdict.
- No post-creation CCCD replacement, manual mapping panel, or G-DOC missing-CCCD rule is added in this slice.
- All committed fixtures and examples use synthetic PII-free values.

---

## File Structure and Interfaces

### Backend files

- Modify `server/cases.py`
  - Persist `cccdName` and full `cccdWorkbook`.
  - Normalize legacy cases.
  - Expose a pure `compact_cccd_summary()` redaction helper.
  - Keep `list()` unchanged.
- Modify `server/app.py`
  - Accept and synchronously validate multipart `cccd`.
  - Save it as `<case-dir>/cccd.xlsx`.
  - Pass the path through `_run_case`.
  - Return only `cccdName` and `cccdSummary` from case detail.
- Create `server/cccd_ingest.py`
  - Convert Phase 0 candidates/resolutions into safe packet targets.
  - Attach image documents and CCCD field evidence atomically and idempotently.
  - Return updated packet metadata plus durable `cccdWorkbook`.
- Modify `server/checklist.py`
  - Prefer mapped CCCD front evidence for A1 and force its automatic state to `review`.
- Modify `server/pipeline.py`
  - Run CCCD ingest after every PDF packet manifest exists.
  - Return `cccdWorkbook` without writing `case.json`.
- Create `server/cccd_smoke_app.py`
  - Provide a disposable synthetic backend for deterministic browser
    verification without touching production case data.
- Add or modify the matching backend tests:
  - `server/cases_test.py`
  - `server/app_test.py`
  - `server/cccd_ingest_test.py`
  - `server/checklist_test.py`
  - `server/pipeline_test.py`

### Frontend files

- Modify `src/upload/api.ts`
  - Add CCCD summary types, multipart upload, and progress label.
- Create `src/upload/cccd.ts`
  - Keep browser eligibility and summary copy as pure, unit-tested functions.
- Create `src/upload/cccd.test.ts`
  - Test roster requirement, restored eligibility, and ready/partial/error copy.
- Modify `src/components/UploadScreen.tsx`
  - Add the optional `.xlsx` chooser, helper text, and inline blocking message.
- Create `src/components/UploadScreen.test.ts`
  - Verify the third chooser and exact copy through static React rendering.
- Modify `src/components/UploadFlow.tsx`
  - Forward the optional CCCD file to `createCase`.
- Modify `src/components/CaseDetail.tsx`
  - Render the compact CCCD line without any identity data.
- Create `src/components/CaseDetail.test.ts`
  - Verify ready, partial, error, and absent summary rendering.
- Modify `src/styles.css`
  - Style the new helper, validation message, and compact summary line.

### Exact production interfaces

- `server/cases.py` exposes
  `compact_cccd_summary(workbook: dict | None) -> dict | None`.
- `CaseStore.create` has ordered parameters
  `name: str`, `pdf_name: str`, `roster_name: str | None`,
  `now: str | None = None`, `cccd_name: str | None = None`, and returns
  `str`.
- `CaseStore.set_result` has ordered parameters
  `cid: str`, `summary: dict | None`, `packets: list[dict]`,
  `cccd_workbook: dict | None = None`, and returns `None`.

```python
# server/cccd_ingest.py
class CccdIngestResult(TypedDict):
    packets: list[dict]
    cccdWorkbook: dict

@dataclass(frozen=True)
class PlannedMapping:
    candidate: CardCandidate
    resolution: CardResolution
    target_packet_index: int | None
    mapping: dict
```

- `plan_candidate_mappings` has ordered parameters
  `candidates: list[CardCandidate]`, `resolution_result: ResolutionResult`,
  `roster_rows: list[dict[str, str]]`, `packets: list[dict]`,
  `case_dir: str`, and returns `list[PlannedMapping]`.
- `ingest_cccd_workbook` has ordered parameters
  `xlsx_path: str`, `roster_rows: list[dict[str, str]]`,
  `packets: list[dict]`, `case_dir: str`,
  `packet_manifest_paths: dict[int, str]`, `assets_dir: str`,
  `progress_cb: Callable[[str, int, int, str], None]`, and returns
  `CccdIngestResult`.
- `server/pipeline.py` extends `run_pipeline` with the trailing optional
  `cccd_xlsx_path: str | None = None` and retains a `dict` return.

```ts
// src/upload/api.ts
export interface CccdSummary {
  status: 'ready' | 'partial' | 'error'
  candidates: number
  attached: number
  unresolved: number
  errorCode?: string
}

export async function createCase(
  pdf: File,
  roster?: File,
  cccd?: File,
): Promise<{ case_id: string }>
```

---

### Task 1: Persist CCCD metadata and define the compact redaction boundary

**Files:**
- Modify: `server/cases.py`
- Test: `server/cases_test.py`

**Interfaces:**
- Produces: `compact_cccd_summary(workbook)`, optional `cccd_name` on `CaseStore.create`, and optional `cccd_workbook` on `CaseStore.set_result`.
- Guarantees: full mappings remain in `case.json`; compact summary contains only `status`, counts, and optional safe `errorCode`; `CaseStore.list()` remains byte-for-byte shape compatible.

- [ ] **Step 1: Add failing persistence, reload, redaction, legacy, and list-contract tests**

Append tests that use synthetic values only:

```python
from cases import compact_cccd_summary


def _cccd_workbook(status="partial"):
    return {
        "status": status,
        "summary": {"candidates": 2, "attached": 1, "unresolved": 1},
        "errorCode": "extraction-incomplete" if status == "partial" else None,
        "mappings": [{
            "candidateId": "card-drawing-0001",
            "ocrIdentity": {"cccd": "000000000001", "name": "Synthetic A"},
            "attachedPacketIndex": 0,
        }],
    }


def test_cccd_metadata_roundtrips_but_list_stays_compact(tmp_path):
    store = CaseStore(str(tmp_path))
    cid = store.create(
        name="synthetic",
        pdf_name="input.pdf",
        roster_name="roster.xlsx",
        cccd_name="cards.xlsx",
    )
    store.set_result(
        cid,
        summary={"found": 1},
        packets=[_pkt(0)],
        cccd_workbook=_cccd_workbook(),
    )

    detail = CaseStore(str(tmp_path)).get(cid)
    assert detail["cccdName"] == "cards.xlsx"
    assert detail["cccdWorkbook"]["mappings"][0]["candidateId"] == "card-drawing-0001"
    assert "cccdName" not in store.list()[0]
    assert "cccdWorkbook" not in store.list()[0]


def test_compact_cccd_summary_redacts_mapping_and_identity():
    summary = compact_cccd_summary(_cccd_workbook())
    assert summary == {
        "status": "partial",
        "candidates": 2,
        "attached": 1,
        "unresolved": 1,
        "errorCode": "extraction-incomplete",
    }
    assert "mappings" not in summary
    assert "cccd" not in json.dumps(summary).casefold()


def test_legacy_case_normalizes_missing_cccd_properties(tmp_path):
    _write_raw_case(str(tmp_path), "legacy-cccd", status="ready")
    case = CaseStore(str(tmp_path)).get("legacy-cccd")
    assert case["cccdName"] is None
    assert case["cccdWorkbook"] is None


def test_delete_removes_cccd_workbook_assets_and_packet_copies(tmp_path):
    store = CaseStore(str(tmp_path))
    cid = store.create(
        name="synthetic",
        pdf_name="input.pdf",
        roster_name="roster.xlsx",
        cccd_name="cards.xlsx",
    )
    case_dir = Path(store.case_dir(cid))
    (case_dir / "cccd.xlsx").write_bytes(b"synthetic")
    (case_dir / "cccd-assets").mkdir()
    (case_dir / "cccd-assets" / "drawing-0001.png").write_bytes(b"synthetic")
    (case_dir / "packets" / "0").mkdir(parents=True)
    (case_dir / "packets" / "0" / "cccd-front.png").write_bytes(b"synthetic")

    store.delete(cid)

    assert not case_dir.exists()
    assert store.get(cid) is None
```

Add `from pathlib import Path` to `server/cases_test.py`.

- [ ] **Step 2: Run the focused tests and verify failure**

Run:

```bash
cd server && python3 -m pytest cases_test.py -q
```

Expected: failures report unknown `cccd_name` / `cccd_workbook` arguments and missing `compact_cccd_summary`.

- [ ] **Step 3: Implement optional schema fields and the pure redaction helper**

Implement the helper with an allow-list, not a copy-and-delete approach:

```python
def compact_cccd_summary(workbook: dict | None) -> dict | None:
    if not workbook:
        return None
    counts = workbook.get("summary") or {}
    out = {
        "status": workbook.get("status", "error"),
        "candidates": int(counts.get("candidates", 0)),
        "attached": int(counts.get("attached", 0)),
        "unresolved": int(counts.get("unresolved", 0)),
    }
    if workbook.get("errorCode"):
        out["errorCode"] = workbook["errorCode"]
    return out
```

Extend `create` and `set_result` using optional trailing parameters so existing callers remain valid:

```python
def create(
    self,
    name: str,
    pdf_name: str,
    roster_name: str | None,
    now: str | None = None,
    cccd_name: str | None = None,
) -> str:
    cid = uuid.uuid4().hex
    case = {
        "id": cid,
        "name": name,
        "createdAt": now,
        "status": "processing",
        "pdfName": pdf_name,
        "rosterName": roster_name,
        "cccdName": cccd_name,
        "summary": None,
        "cccdWorkbook": None,
        "error": None,
        "packets": [],
    }
    os.makedirs(os.path.join(self.root, cid), exist_ok=True)
    self._write(case)
    return cid


def set_result(
    self,
    cid: str,
    summary: dict | None,
    packets: list[dict],
    cccd_workbook: dict | None = None,
) -> None:
    case = self._idx.get(cid)
    if case is None:
        return
    filled = [_ensure_packet_defaults(packet) for packet in packets]
    case["summary"] = summary
    case["packets"] = filled
    case["cccdWorkbook"] = cccd_workbook
    case["status"] = case_status("ready", filled)
    self._write(case)
```

During `_load`, call `setdefault` for both new keys for every readable case and persist only when a key was missing. Do not reset packet reviews or rewrite an already present `cccdWorkbook`.

- [ ] **Step 4: Run the focused store tests**

Run:

```bash
cd server && python3 -m pytest cases_test.py -q
```

Expected: all store tests pass, including restart and legacy migration.

- [ ] **Step 5: Commit the store boundary**

```bash
git add server/cases.py server/cases_test.py
git commit -m "feat: persist CCCD workbook results"
```

---

### Task 2: Accept, validate, and safely expose the CCCD upload

**Files:**
- Modify: `server/app.py`
- Test: `server/app_test.py`

**Interfaces:**
- Consumes: optional store parameters and `compact_cccd_summary` from Task 1.
- Produces: multipart field `cccd`,
  `_run_case(cid, pdf_path, roster_path, cccd_path=None)`, safe HTTP validation
  codes, and a redacted case-detail response.
- Guarantees: cross-field, extension, and 100 MB checks execute before `store.create`; synchronous validation creates no case directory/index entry.

- [ ] **Step 1: Update the fake pipeline and add failing API tests**

Give the existing fake the compatible fifth parameter:

```python
def _fake_pipeline(pdf, roster, out_dir, cb, cccd_xlsx_path=None):
    cb("done", 1, 1, "")
    return {
        "summary": {"found": 1, "roster_n": 1, "matched": 1, "auto_merged": 0},
        "packets": [{
            "index": 0,
            "name": "P0",
            "pages": [8, 15],
            "confidence": "green",
            "flags": [],
            "labels": [],
        }],
        "cccdWorkbook": (
            {
                "status": "ready",
                "summary": {"candidates": 1, "attached": 1, "unresolved": 0},
                "mappings": [{"candidateId": "private-candidate"}],
            }
            if cccd_xlsx_path else None
        ),
    }
```

Add the following tests:

```python
def test_cccd_requires_roster_before_case_creation(tmp_path, monkeypatch):
    monkeypatch.setattr(appmod, "store", appmod.CaseStore(str(tmp_path)))
    response = TestClient(app).post("/api/cases", files={
        "pdf": ("input.pdf", b"%PDF-1.4", "application/pdf"),
        "cccd": ("cards.xlsx", b"xlsx", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"),
    })
    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "cccd-requires-roster"
    assert appmod.store.list() == []
    assert list(tmp_path.iterdir()) == []


def test_invalid_cccd_extension_creates_no_case(tmp_path, monkeypatch):
    monkeypatch.setattr(appmod, "store", appmod.CaseStore(str(tmp_path)))
    response = TestClient(app).post("/api/cases", files={
        "pdf": ("input.pdf", b"%PDF-1.4", "application/pdf"),
        "roster": ("roster.xlsx", b"roster", "application/octet-stream"),
        "cccd": ("cards.xls", b"old", "application/octet-stream"),
    })
    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "invalid-cccd-workbook"
    assert appmod.store.list() == []


def test_oversized_cccd_creates_no_case(tmp_path, monkeypatch):
    monkeypatch.setattr(appmod, "store", appmod.CaseStore(str(tmp_path)))
    monkeypatch.setattr(appmod, "MAX_CCCD_WORKBOOK_BYTES", 3)
    response = TestClient(app).post("/api/cases", files={
        "pdf": ("input.pdf", b"%PDF-1.4", "application/pdf"),
        "roster": ("roster.xlsx", b"roster", "application/octet-stream"),
        "cccd": ("cards.xlsx", b"four", "application/octet-stream"),
    })
    assert response.status_code == 413
    assert response.json()["detail"]["code"] == "cccd-workbook-too-large"
    assert appmod.store.list() == []


def test_cccd_upload_is_saved_passed_and_detail_is_redacted(tmp_path, monkeypatch):
    seen = {}

    def fake(pdf, roster, out_dir, cb, cccd_xlsx_path=None):
        seen["cccd"] = cccd_xlsx_path
        return _fake_pipeline(pdf, roster, out_dir, cb, cccd_xlsx_path)

    monkeypatch.setattr(appmod, "run_pipeline", fake)
    monkeypatch.setattr(appmod, "store", appmod.CaseStore(str(tmp_path)))
    client = TestClient(app)
    response = client.post("/api/cases", files={
        "pdf": ("input.pdf", b"%PDF-1.4", "application/pdf"),
        "roster": ("roster.xlsx", b"roster", "application/octet-stream"),
        "cccd": ("cards.xlsx", b"xlsx", "application/octet-stream"),
    })
    cid = response.json()["case_id"]
    for _ in range(100):
        detail = client.get(f"/api/cases/{cid}").json()
        if detail["status"] != "processing":
            break
        time.sleep(0.02)

    assert os.path.basename(seen["cccd"]) == "cccd.xlsx"
    assert os.path.isfile(os.path.join(appmod.store.case_dir(cid), "cccd.xlsx"))
    assert os.path.isfile(os.path.join(appmod.store.case_dir(cid), "roster.xlsx"))
    assert detail["cccdName"] == "cards.xlsx"
    assert detail["cccdSummary"] == {
        "status": "ready",
        "candidates": 1,
        "attached": 1,
        "unresolved": 0,
    }
    assert "cccdWorkbook" not in detail
    assert "private-candidate" not in json.dumps(detail)
```

Import `time` at module scope and keep the existing PDF-only `_ready_case` test unchanged to prove compatibility.

- [ ] **Step 2: Run the API tests and verify failure**

Run:

```bash
cd server && python3 -m pytest app_test.py -q
```

Expected: the new multipart field is ignored or rejected incorrectly, and the redacted fields are absent.

- [ ] **Step 3: Implement synchronous validation before `store.create`**

Import the tested workbook limit and compact helper:

```python
from cases import CaseStore, compact_cccd_summary, progress_of
from cccd_workbook import MAX_WORKBOOK_BYTES as MAX_CCCD_WORKBOOK_BYTES
```

Add safe helpers:

```python
def _upload_size(upload: UploadFile) -> int:
    upload.file.seek(0, os.SEEK_END)
    size = upload.file.tell()
    upload.file.seek(0)
    return size


def _validate_cccd_upload(
    roster: UploadFile | None,
    cccd: UploadFile | None,
) -> None:
    if cccd is None:
        return
    if roster is None:
        raise HTTPException(
            status_code=422,
            detail={"code": "cccd-requires-roster"},
        )
    if not (cccd.filename or "").casefold().endswith(".xlsx"):
        raise HTTPException(
            status_code=422,
            detail={"code": "invalid-cccd-workbook"},
        )
    if _upload_size(cccd) > MAX_CCCD_WORKBOOK_BYTES:
        raise HTTPException(
            status_code=413,
            detail={"code": "cccd-workbook-too-large"},
        )
```

Call `_validate_cccd_upload(roster, cccd)` before generating a case ID. Add `cccd: UploadFile | None = File(None)` to `post_case`, pass its original filename to `CaseStore.create`, and copy it only to `os.path.join(case_dir, "cccd.xlsx")`.

- [ ] **Step 4: Thread the path through processing and redact detail**

Use compatible optional parameters:

```python
def _run_case(
    cid: str,
    pdf_path: str,
    roster_path: str | None,
    cccd_path: str | None = None,
) -> None:
    case_dir = store.case_dir(cid)

    def cb(stage: str, done: int, total: int, detail: str) -> None:
        _progress[cid] = {
            "stage": stage,
            "done": done,
            "total": total,
            "detail": detail,
        }

    try:
        result = run_pipeline(
            pdf_path,
            roster_path,
            case_dir,
            cb,
            cccd_xlsx_path=cccd_path,
        )
        store.set_result(
            cid,
            summary=result.get("summary"),
            packets=result.get("packets", []),
            cccd_workbook=result.get("cccdWorkbook"),
        )
    except Exception as error:
        store.set_error(cid, str(error))
    finally:
        _progress.pop(cid, None)
```

For `GET /api/cases/{cid}`, build the response as an allow-listed transformation of the stored object:

```python
out = dict(case)
out.pop("cccdWorkbook", None)
out["cccdSummary"] = compact_cccd_summary(case.get("cccdWorkbook"))
```

Do not add either CCCD field to `list_cases`.

- [ ] **Step 5: Run API and store tests**

Run:

```bash
cd server && python3 -m pytest app_test.py cases_test.py -q
```

Expected: all tests pass; PDF-only upload still reaches `ready`.

- [ ] **Step 6: Commit the upload boundary**

```bash
git add server/app.py server/app_test.py
git commit -m "feat: accept CCCD workbook uploads"
```

---

### Task 3: Route A1 to mapped CCCD evidence without auto-verdict

**Files:**
- Modify: `server/checklist.py`
- Test: `server/checklist_test.py`

**Interfaces:**
- Consumes: a `cccd` field source whose `docId` starts with `cccd-excel-`.
- Produces: A1 with that source/doc and `autostatus: "review"`.
- Guarantees: all existing sources and A1 behavior remain unchanged when mapped evidence is absent.

- [ ] **Step 1: Add failing mapped and legacy A1 tests**

```python
def test_a1_prefers_mapped_cccd_front_and_stays_reviewer_controlled():
    fields = [{
        "key": "cccd",
        "label": "Số CCCD",
        "expected": "000000000001",
        "sources": [
            {
                "docId": "contract",
                "page": 0,
                "value": "000000000001",
                "bbox": {"x": 1, "y": 1, "width": 2, "height": 2},
                "confidence": .91,
            },
            {
                "docId": "cccd-excel-card-drawing-0001-front",
                "page": 0,
                "value": "000000000001",
                "bbox": {"x": 20, "y": 30, "width": 80, "height": 24},
                "confidence": .95,
            },
        ],
    }]
    docs = [
        *DOCS,
        {
            "id": "cccd-excel-card-drawing-0001-front",
            "kind": "id_front",
            "label": "CCCD (Excel) · Mặt trước",
            "pages": [],
        },
    ]
    a1 = _by_code(build_checklist(fields, MATCH, docs))["A1"]
    assert a1["evidenceDocId"] == "cccd-excel-card-drawing-0001-front"
    assert a1["source"]["bbox"]["x"] == 20
    assert a1["autostatus"] == "review"


def test_a1_without_mapped_cccd_keeps_existing_comparison():
    fields = [{
        "key": "cccd",
        "label": "Số CCCD",
        "expected": "000000000001",
        "sources": [{
            "docId": "contract",
            "page": 0,
            "value": "000000000001",
            "bbox": {"x": 1, "y": 1, "width": 2, "height": 2},
            "confidence": .91,
        }],
    }]
    a1 = _by_code(build_checklist(fields, MATCH, DOCS))["A1"]
    assert a1["evidenceDocId"] == "contract"
    assert a1["autostatus"] == "match"
```

- [ ] **Step 2: Run the checklist tests and verify failure**

Run:

```bash
cd server && python3 -m pytest checklist_test.py -q
```

Expected: mapped A1 still routes to `contract` and becomes `match`.

- [ ] **Step 3: Add a narrow mapped-source preference**

Inside the `_VALUE` loop, special-case only A1:

```python
mapped_cccd = (
    next(
        (
            source
            for source in sources
            if (source or {}).get("docId", "").startswith("cccd-excel-")
        ),
        None,
    )
    if code == "A1"
    else None
)
src = mapped_cccd or next(
    (source for source in sources if source and source.get("docId") == routed),
    None,
) or (sources[0] if sources else None)
autostatus = (
    "review"
    if code == "A1" and mapped_cccd is not None
    else _autostatus(f.get("expected", ""), src)
)
```

Use `autostatus` in the generated check. Do not change `_autostatus` globally.

- [ ] **Step 4: Run the checklist tests**

```bash
cd server && python3 -m pytest checklist_test.py -q
```

Expected: all checklist tests pass.

- [ ] **Step 5: Commit the evidence-routing rule**

```bash
git add server/checklist.py server/checklist_test.py
git commit -m "feat: route A1 to mapped CCCD evidence"
```

---

### Task 4: Plan exact-only packet mappings with complete provenance

**Files:**
- Create: `server/cccd_ingest.py`
- Create: `server/cccd_ingest_test.py`

**Interfaces:**
- Consumes: Phase 0 `CardCandidate`, `CardResolution`, `ResolutionResult`, normalized roster rows, packet metadata, and the case root.
- Produces: `PlannedMapping` values; only `resolution.state == "exact"` can have a non-null `target_packet_index`.
- Guarantees: zero or multiple packet targets resolve to no target; all candidate outcomes retain safe issue codes and case-relative provenance.

- [ ] **Step 1: Add synthetic candidate builders and failing target-safety tests**

Create `server/cccd_ingest_test.py` with PII-free values:

```python
from pathlib import Path

from cccd_ingest import plan_candidate_mappings
from cccd_matching import CardResolution, ResolutionResult
from cccd_ocr import CccdImageOcr
from cccd_pairing import AnalyzedDrawing, CardCandidate
from cccd_workbook import Anchor, EmbeddedDrawing


def analyzed(
    root: Path,
    drawing_id: str,
    side: str,
    cccd: str = "",
    confidence: float = 0.0,
):
    path = root / "cccd-assets" / "extracted" / f"{drawing_id}.png"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"synthetic-image")
    drawing = EmbeddedDrawing(
        id=drawing_id,
        anchor=Anchor("Sheet1", 1, 1, 5, 5),
        media_type="image/png",
        extension="png",
        width=1000,
        height=630,
        sha256=f"sha-{drawing_id}",
        stored_path=str(path),
    )
    return AnalyzedDrawing(
        drawing,
        CccdImageOcr(
            side=side,
            side_confidence=.99,
            cccd=cccd,
            cccd_confidence=confidence,
            name="Synthetic A",
            name_confidence=.9,
            number_bbox={"x": 20, "y": 30, "width": 200, "height": 40}
            if side == "front" else None,
        ),
    )


def candidate(root: Path):
    return CardCandidate(
        id="card-drawing-0001-drawing-0002",
        front=analyzed(root, "drawing-0001", "front", "000000000001", .95),
        back=analyzed(root, "drawing-0002", "back"),
        issues=(),
    )


def exact_resolution():
    return ResolutionResult(
        expected_mappable_identities=1,
        resolutions=[CardResolution(
            candidate_id="card-drawing-0001-drawing-0002",
            state="exact",
            roster_key="roster-0",
            matched_by="cccd",
            issues=(),
        )],
    )


def packet(index=0, cccd="000000000001"):
    return {
        "index": index,
        "rosterIdentity": {"cccd": cccd, "name": "Synthetic A"},
        "matchedBy": "cccd",
    }


def test_exact_resolution_targets_one_packet_and_serializes_relative_provenance(tmp_path):
    plans = plan_candidate_mappings(
        [candidate(tmp_path)],
        exact_resolution(),
        [{"name": "Synthetic A", "cccd": "000000000001"}],
        [packet()],
        str(tmp_path),
    )
    plan = plans[0]
    assert plan.target_packet_index == 0
    assert plan.mapping["state"] == "exact"
    assert plan.mapping["matchMethod"] == "cccd"
    assert plan.mapping["attachedPacketIndex"] is None
    assert plan.mapping["front"]["sourcePath"] == "cccd-assets/extracted/drawing-0001.png"
    assert plan.mapping["front"]["anchor"]["sheet"] == "Sheet1"
    assert plan.mapping["numberBbox"]["x"] == 20


def test_exact_resolution_with_zero_or_multiple_packet_targets_does_not_attach(tmp_path):
    for packets, issue in (
        ([], "packet-target-not-found"),
        ([packet(0), packet(1)], "non-unique-packet-target"),
    ):
        plan = plan_candidate_mappings(
            [candidate(tmp_path)],
            exact_resolution(),
            [{"name": "Synthetic A", "cccd": "000000000001"}],
            packets,
            str(tmp_path),
        )[0]
        assert plan.target_packet_index is None
        assert issue in plan.mapping["issues"]


def test_suggested_manual_and_conflict_resolutions_never_target_packet(tmp_path):
    card = candidate(tmp_path)
    for state in ("suggested", "manual", "conflict"):
        result = ResolutionResult(
            expected_mappable_identities=1,
            resolutions=[CardResolution(
                candidate_id=card.id,
                state=state,
                roster_key="roster-0" if state == "suggested" else None,
                matched_by="name" if state == "suggested" else None,
                issues=("synthetic-issue",),
            )],
        )
        plan = plan_candidate_mappings(
            [card],
            result,
            [{"name": "Synthetic A", "cccd": "000000000001"}],
            [packet()],
            str(tmp_path),
        )[0]
        assert plan.target_packet_index is None
        assert plan.mapping["attachedPacketIndex"] is None
```

- [ ] **Step 2: Run the new tests and verify failure**

Run:

```bash
cd server && python3 -m pytest cccd_ingest_test.py -q
```

Expected: import failure because `cccd_ingest.py` does not exist.

- [ ] **Step 3: Define typed results and deterministic serializers**

Create `server/cccd_ingest.py` with:

```python
from __future__ import annotations

from dataclasses import dataclass
import os
from typing import Callable, TypedDict

from cccd_matching import CardResolution, ResolutionResult
from cccd_pairing import CardCandidate


ProgressCallback = Callable[[str, int, int, str], None]


class CccdIngestResult(TypedDict):
    packets: list[dict]
    cccdWorkbook: dict


@dataclass(frozen=True)
class PlannedMapping:
    candidate: CardCandidate
    resolution: CardResolution
    target_packet_index: int | None
    mapping: dict
```

Add `_case_relative(case_dir, path)` that rejects a path outside the case root via `os.path.commonpath`, plus serializers for `Anchor`, `EmbeddedDrawing`, and front OCR. The persistent mapping shape is:

```python
{
    "candidateId": "card-drawing-0001-drawing-0002",
    "front": {
        "drawingId": "drawing-0001",
        "mediaType": "image/png",
        "width": 1000,
        "height": 630,
        "sha256": "synthetic-front-sha256",
        "sourcePath": "cccd-assets/extracted/drawing-0001.png",
        "packetPath": None,
        "anchor": {
            "sheet": "Sheet1",
            "fromRow": 1,
            "fromCol": 1,
            "toRow": 5,
            "toCol": 5,
        },
    },
    "back": {
        "drawingId": "drawing-0002",
        "mediaType": "image/png",
        "width": 1000,
        "height": 630,
        "sha256": "synthetic-back-sha256",
        "sourcePath": "cccd-assets/extracted/drawing-0002.png",
        "packetPath": None,
        "anchor": {
            "sheet": "Sheet1",
            "fromRow": 1,
            "fromCol": 6,
            "toRow": 5,
            "toCol": 10,
        },
    },
    "ocrIdentity": {"cccd": "000000000001", "name": "Synthetic A"},
    "ocrConfidence": {"cccd": 0.95, "name": 0.9},
    "numberBbox": {"x": 20, "y": 30, "width": 200, "height": 40},
    "state": "exact",
    "attachedPacketIndex": None,
    "matchMethod": "cccd",
    "issues": [],
}
```

Full OCR identity is permitted only in this local persistent mapping and must never be copied into the detail response.

- [ ] **Step 4: Implement exact-only roster-key and packet targeting**

Use these safety rules:

```python
def _digits(value: str | None) -> str:
    return "".join(character for character in value or "" if character.isdigit())


def _roster_index(roster_key: str | None) -> int | None:
    if not roster_key or not roster_key.startswith("roster-"):
        return None
    raw = roster_key.removeprefix("roster-")
    return int(raw) if raw.isdigit() else None


def _case_relative(case_dir: str, path: str) -> str:
    root = os.path.realpath(case_dir)
    candidate = os.path.realpath(path)
    if os.path.commonpath([root, candidate]) != root:
        raise ValueError("CCCD asset escaped case directory")
    return os.path.relpath(candidate, root).replace(os.sep, "/")


def _serialize_side(analyzed, case_dir: str) -> dict | None:
    if analyzed is None:
        return None
    drawing = analyzed.drawing
    anchor = drawing.anchor
    return {
        "drawingId": drawing.id,
        "mediaType": drawing.media_type,
        "width": drawing.width,
        "height": drawing.height,
        "sha256": drawing.sha256,
        "sourcePath": _case_relative(case_dir, drawing.stored_path),
        "packetPath": None,
        "anchor": {
            "sheet": anchor.sheet,
            "fromRow": anchor.from_row,
            "fromCol": anchor.from_col,
            "toRow": anchor.to_row,
            "toCol": anchor.to_col,
        },
    }


def _append_issue(issues: list[str], issue: str) -> None:
    if issue not in issues:
        issues.append(issue)


def plan_candidate_mappings(
    candidates: list[CardCandidate],
    resolution_result: ResolutionResult,
    roster_rows: list[dict[str, str]],
    packets: list[dict],
    case_dir: str,
) -> list[PlannedMapping]:
    candidate_by_id = {candidate.id: candidate for candidate in candidates}
    resolution_by_id = {
        resolution.candidate_id: resolution
        for resolution in resolution_result.resolutions
    }
    if (
        len(candidate_by_id) != len(candidates)
        or len(resolution_by_id) != len(resolution_result.resolutions)
        or set(candidate_by_id) != set(resolution_by_id)
    ):
        raise ValueError("candidate-resolution-mismatch")

    planned = []
    for candidate_id in sorted(candidate_by_id):
        candidate = candidate_by_id[candidate_id]
        resolution = resolution_by_id[candidate_id]
        front_ocr = candidate.front.ocr if candidate.front is not None else None
        issues = list(dict.fromkeys((*candidate.issues, *resolution.issues)))
        target_packet_index = None

        if resolution.state == "exact":
            roster_index = _roster_index(resolution.roster_key)
            if roster_index is None or roster_index >= len(roster_rows):
                _append_issue(issues, "invalid-roster-key")
            else:
                roster_cccd = _digits(roster_rows[roster_index].get("cccd"))
                if len(roster_cccd) != 12:
                    _append_issue(issues, "non-12-digit-roster-cccd")
                else:
                    targets = [
                        packet["index"]
                        for packet in packets
                        if _digits(
                            (packet.get("rosterIdentity") or {}).get("cccd")
                        ) == roster_cccd
                    ]
                    if len(targets) == 1:
                        target_packet_index = targets[0]
                    elif not targets:
                        _append_issue(issues, "packet-target-not-found")
                    else:
                        _append_issue(issues, "non-unique-packet-target")

        mapping = {
            "candidateId": candidate.id,
            "front": _serialize_side(candidate.front, case_dir),
            "back": _serialize_side(candidate.back, case_dir),
            "ocrIdentity": {
                "cccd": front_ocr.cccd if front_ocr is not None else "",
                "name": front_ocr.name if front_ocr is not None else "",
            },
            "ocrConfidence": {
                "cccd": (
                    front_ocr.cccd_confidence if front_ocr is not None else 0.0
                ),
                "name": (
                    front_ocr.name_confidence if front_ocr is not None else 0.0
                ),
            },
            "numberBbox": (
                front_ocr.number_bbox if front_ocr is not None else None
            ),
            "state": resolution.state,
            "attachedPacketIndex": None,
            "matchMethod": resolution.matched_by,
            "issues": issues,
        }
        planned.append(PlannedMapping(
            candidate=candidate,
            resolution=resolution,
            target_packet_index=target_packet_index,
            mapping=mapping,
        ))
    return planned
```

This implementation raises `ValueError("candidate-resolution-mismatch")` if
candidate and resolution IDs are missing, duplicated, or differ; the
orchestrator in Task 5 converts it to a safe workbook error.

- [ ] **Step 5: Run the mapping planner tests**

```bash
cd server && python3 -m pytest cccd_ingest_test.py -q
```

Expected: all planner tests pass.

- [ ] **Step 6: Commit the exact-only planner**

```bash
git add server/cccd_ingest.py server/cccd_ingest_test.py
git commit -m "feat: plan exact CCCD packet mappings"
```

---

### Task 5: Attach CCCD documents atomically and orchestrate resilient ingest

**Files:**
- Modify: `server/cccd_ingest.py`
- Modify: `server/cccd_ingest_test.py`

**Interfaces:**
- Consumes: `PlannedMapping`, packet manifests, `checklist.build_checklist`, and the four Phase 0 modules.
- Produces: an `ingest_cccd_workbook` result with exact keys `packets` and
  `cccdWorkbook`.
- Guarantees: stable document IDs, content-addressed server filenames, idempotency, existing PDF docs/sources preservation, rollback on manifest failure, ready/partial/error status, and aggregate summary counts.

- [ ] **Step 1: Add failing attachment and idempotency tests**

Extend the test manifest helper:

```python
import json


def write_manifest(path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({
        "id": "synthetic-packet",
        "name": "Synthetic A",
        "product": "",
        "heading": "Hồ sơ CTV",
        "status": "pending",
        "exempt": False,
        "docs": [{
            "id": "contract",
            "kind": "contract",
            "label": "Hợp đồng dịch vụ",
            "pages": [{"src": "page-0.png", "width": 1000, "height": 1400}],
        }],
        "fields": [{
            "key": "cccd",
            "label": "Số CCCD",
            "group": "Danh tính",
            "check": "compare",
            "kind": "text",
            "expected": "000000000001",
            "sources": [{
                "docId": "contract",
                "page": 0,
                "value": "",
                "bbox": {"x": 1, "y": 1, "width": 2, "height": 2},
                "confidence": 0.0,
            }],
        }],
    }), encoding="utf-8")


def test_attach_adds_front_back_a1_and_is_idempotent(tmp_path):
    from cccd_ingest import attach_planned_mapping

    manifest_path = tmp_path / "packets" / "0" / "manifest.json"
    write_manifest(manifest_path)
    plan = plan_candidate_mappings(
        [candidate(tmp_path)],
        exact_resolution(),
        [{"name": "Synthetic A", "cccd": "000000000001"}],
        [packet()],
        str(tmp_path),
    )[0]

    first = attach_planned_mapping(
        plan,
        packet(),
        str(manifest_path),
        str(tmp_path),
    )
    second = attach_planned_mapping(
        plan,
        packet(),
        str(manifest_path),
        str(tmp_path),
    )

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    owned = [doc for doc in manifest["docs"] if doc["id"].startswith("cccd-excel-")]
    assert [doc["kind"] for doc in owned] == ["id_front", "id_back"]
    assert [doc["label"] for doc in owned] == [
        "CCCD (Excel) · Mặt trước",
        "CCCD (Excel) · Mặt sau",
    ]
    assert len(owned) == 2
    assert manifest["docs"][0]["id"] == "contract"
    cccd_field = next(field for field in manifest["fields"] if field["key"] == "cccd")
    assert any(source["docId"] == owned[0]["id"] for source in cccd_field["sources"])
    assert cccd_field["sources"][0]["docId"] == "contract"
    a1 = next(check for check in manifest["checks"] if check["code"] == "A1")
    assert a1["evidenceDocId"] == owned[0]["id"]
    assert a1["source"]["bbox"] == {"x": 20, "y": 30, "width": 200, "height": 40}
    assert a1["autostatus"] == "review"
    assert first["attachedPacketIndex"] == second["attachedPacketIndex"] == 0
    assert first["front"]["packetPath"] == second["front"]["packetPath"]
```

The packet filename must be content-addressed and server-generated:

```text
cccd-<sha256(candidate-id)[:12]>-<image-sha256[:12]>-front.png
cccd-<sha256(candidate-id)[:12]>-<image-sha256[:12]>-back.png
```

- [ ] **Step 2: Add failing rollback and non-target tests**

```python
def test_attach_failure_keeps_original_manifest_and_unconfirmed_mapping(
    tmp_path,
    monkeypatch,
):
    import cccd_ingest as ingest

    manifest_path = tmp_path / "packets" / "0" / "manifest.json"
    write_manifest(manifest_path)
    before = manifest_path.read_bytes()
    plan = plan_candidate_mappings(
        [candidate(tmp_path)],
        exact_resolution(),
        [{"name": "Synthetic A", "cccd": "000000000001"}],
        [packet()],
        str(tmp_path),
    )[0]
    monkeypatch.setattr(
        ingest,
        "_atomic_json_write",
        lambda *args: (_ for _ in ()).throw(OSError("synthetic-write-failure")),
    )

    result = ingest.attach_planned_mapping(
        plan,
        packet(),
        str(manifest_path),
        str(tmp_path),
    )

    assert result["attachedPacketIndex"] is None
    assert "attachment-failed" in result["issues"]
    assert manifest_path.read_bytes() == before
    assert not list(manifest_path.parent.glob("cccd-*-front.png"))


def test_non_target_plan_never_mutates_manifest(tmp_path):
    from cccd_ingest import attach_planned_mapping

    manifest_path = tmp_path / "packets" / "0" / "manifest.json"
    write_manifest(manifest_path)
    before = manifest_path.read_bytes()
    plan = plan_candidate_mappings(
        [candidate(tmp_path)],
        exact_resolution(),
        [{"name": "Synthetic A", "cccd": "000000000001"}],
        [],
        str(tmp_path),
    )[0]
    result = attach_planned_mapping(plan, packet(), str(manifest_path), str(tmp_path))
    assert result["attachedPacketIndex"] is None
    assert manifest_path.read_bytes() == before
```

- [ ] **Step 3: Implement atomic, content-addressed packet attachment**

Add:

```python
def _atomic_json_write(path: str, payload: dict) -> None:
    directory = os.path.dirname(path)
    descriptor, temporary_path = tempfile.mkstemp(
        prefix=".manifest-",
        suffix=".json",
        dir=directory,
    )
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_path, path)
    finally:
        if os.path.exists(temporary_path):
            os.unlink(temporary_path)


def _owned_doc_id(candidate_id: str, side: str) -> str:
    return f"cccd-excel-{candidate_id}-{side}"


def _packet_filename(plan: PlannedMapping, analyzed, side: str) -> str:
    candidate_token = hashlib.sha256(
        plan.candidate.id.encode("utf-8")
    ).hexdigest()[:12]
    image_token = analyzed.drawing.sha256[:12]
    return (
        f"cccd-{candidate_token}-{image_token}-{side}."
        f"{analyzed.drawing.extension}"
    )


def _attachment_failure(plan: PlannedMapping) -> dict:
    mapping = deepcopy(plan.mapping)
    issues = list(mapping["issues"])
    _append_issue(issues, "attachment-failed")
    mapping["issues"] = issues
    mapping["attachedPacketIndex"] = None
    return mapping


def attach_planned_mapping(
    plan: PlannedMapping,
    packet: dict,
    manifest_path: str,
    case_dir: str,
) -> dict:
    if plan.target_packet_index is None:
        return deepcopy(plan.mapping)
    if packet.get("index") != plan.target_packet_index:
        return _attachment_failure(plan)

    created_files: list[str] = []
    try:
        with open(manifest_path, "r", encoding="utf-8") as handle:
            original = json.load(handle)
        updated = deepcopy(original)
        packet_dir = os.path.dirname(manifest_path)
        owned_ids = {
            _owned_doc_id(plan.candidate.id, "front"),
            _owned_doc_id(plan.candidate.id, "back"),
        }
        old_owned_docs = [
            document
            for document in updated.get("docs", [])
            if document.get("id") in owned_ids
        ]
        new_docs = []
        new_paths = set()
        mapping = deepcopy(plan.mapping)

        for side in ("front", "back"):
            analyzed = getattr(plan.candidate, side)
            if analyzed is None:
                continue
            filename = _packet_filename(plan, analyzed, side)
            destination = os.path.join(packet_dir, filename)
            if not os.path.exists(destination):
                shutil.copyfile(analyzed.drawing.stored_path, destination)
                created_files.append(destination)
            new_paths.add(os.path.realpath(destination))
            mapping[side]["packetPath"] = _case_relative(case_dir, destination)
            new_docs.append({
                "id": _owned_doc_id(plan.candidate.id, side),
                "kind": "id_front" if side == "front" else "id_back",
                "label": (
                    "CCCD (Excel) · Mặt trước"
                    if side == "front"
                    else "CCCD (Excel) · Mặt sau"
                ),
                "pages": [{
                    "src": destination,
                    "width": analyzed.drawing.width,
                    "height": analyzed.drawing.height,
                }],
            })

        updated["docs"] = [
            document
            for document in updated.get("docs", [])
            if document.get("id") not in owned_ids
        ] + new_docs
        cccd_field = next(
            field
            for field in updated.get("fields", [])
            if field.get("key") == "cccd"
        )
        cccd_field["sources"] = [
            source
            for source in cccd_field.get("sources", [])
            if source.get("docId") not in owned_ids
        ]
        front = plan.candidate.front
        if front is None or front.ocr.number_bbox is None:
            raise ValueError("exact attachment requires located front")
        cccd_field["sources"].append({
            "docId": _owned_doc_id(plan.candidate.id, "front"),
            "page": 0,
            "value": front.ocr.cccd,
            "bbox": front.ocr.number_bbox,
            "confidence": front.ocr.cccd_confidence,
        })
        updated["checks"] = checklist.build_checklist(
            updated.get("fields", []),
            {
                "matchedBy": packet.get("matchedBy", "no-roster"),
                "ocrIdentity": packet.get("ocrIdentity")
                or {"cccd": "", "name": ""},
                "rosterIdentity": packet.get("rosterIdentity"),
            },
            updated.get("docs", []),
        )
        _atomic_json_write(manifest_path, updated)

        mapping["attachedPacketIndex"] = plan.target_packet_index
        for document in old_owned_docs:
            for page in document.get("pages", []):
                old_path = os.path.realpath(page.get("src", ""))
                if (
                    os.path.dirname(old_path) == os.path.realpath(packet_dir)
                    and old_path not in new_paths
                    and os.path.basename(old_path).startswith("cccd-")
                    and os.path.isfile(old_path)
                ):
                    os.unlink(old_path)
        return mapping
    except Exception:
        for path in created_files:
            if os.path.isfile(path):
                os.unlink(path)
        return _attachment_failure(plan)
```

Add imports for `deepcopy`, `hashlib`, `json`, `shutil`, `tempfile`, and
`checklist` at the top of `cccd_ingest.py`.

Because filenames include image content hashes, a failed replacement cannot overwrite the prior manifest's referenced image. After a successful manifest replacement, remove stale prior image files referenced only by replaced CCCD-owned docs.

- [ ] **Step 4: Run attachment tests**

```bash
cd server && python3 -m pytest cccd_ingest_test.py -q
```

Expected: attachment, rollback, preservation, and idempotency tests pass.

- [ ] **Step 5: Add failing end-to-end orchestrator status tests**

Use monkeypatches only at the Phase 0 boundaries so the production coordinator itself remains real:

```python
def test_ingest_returns_ready_counts_and_durable_mappings(tmp_path, monkeypatch):
    import cccd_ingest as ingest
    from cccd_workbook import ExtractionResult

    card = candidate(tmp_path)
    drawings = [card.front.drawing, card.back.drawing]
    monkeypatch.setattr(
        ingest,
        "extract_drawings",
        lambda path, output: ExtractionResult(2, drawings, []),
    )
    analyzed_by_id = {
        card.front.drawing.id: card.front.ocr,
        card.back.drawing.id: card.back.ocr,
    }
    monkeypatch.setattr(
        ingest,
        "analyze_drawing",
        lambda drawing: analyzed_by_id[drawing.id],
    )
    manifest_path = tmp_path / "packets" / "0" / "manifest.json"
    write_manifest(manifest_path)
    progress = []

    result = ingest.ingest_cccd_workbook(
        "cards.xlsx",
        [{"name": "Synthetic A", "cccd": "000000000001"}],
        [packet()],
        str(tmp_path),
        {0: str(manifest_path)},
        str(tmp_path / "cccd-assets"),
        lambda *args: progress.append(args),
    )

    workbook = result["cccdWorkbook"]
    assert workbook["status"] == "ready"
    assert workbook["summary"] == {"candidates": 1, "attached": 1, "unresolved": 0}
    assert workbook["mappings"][0]["attachedPacketIndex"] == 0
    assert progress[-1][:3] == ("cccd", 1, 1)


def test_ingest_marks_extraction_issue_partial(tmp_path, monkeypatch):
    import cccd_ingest as ingest
    from cccd_workbook import ExtractionIssue, ExtractionResult

    card = candidate(tmp_path)
    monkeypatch.setattr(
        ingest,
        "extract_drawings",
        lambda path, output: ExtractionResult(
            3,
            [card.front.drawing, card.back.drawing],
            [ExtractionIssue("unsupported-media", "drawing-0003")],
        ),
    )
    analyzed_by_id = {
        card.front.drawing.id: card.front.ocr,
        card.back.drawing.id: card.back.ocr,
    }
    monkeypatch.setattr(ingest, "analyze_drawing", lambda d: analyzed_by_id[d.id])
    manifest_path = tmp_path / "packets" / "0" / "manifest.json"
    write_manifest(manifest_path)

    result = ingest.ingest_cccd_workbook(
        "cards.xlsx",
        [{"name": "Synthetic A", "cccd": "000000000001"}],
        [packet()],
        str(tmp_path),
        {0: str(manifest_path)},
        str(tmp_path / "cccd-assets"),
        lambda *args: None,
    )
    assert result["cccdWorkbook"]["status"] == "partial"
    assert result["cccdWorkbook"]["errorCode"] == "extraction-incomplete"


def test_ingest_workbook_failure_is_safe_error_and_keeps_packets(tmp_path, monkeypatch):
    import cccd_ingest as ingest
    from cccd_workbook import CccdWorkbookError

    monkeypatch.setattr(
        ingest,
        "extract_drawings",
        lambda *args: (_ for _ in ()).throw(CccdWorkbookError("private-detail")),
    )
    packets = [packet()]
    result = ingest.ingest_cccd_workbook(
        "cards.xlsx",
        [],
        packets,
        str(tmp_path),
        {},
        str(tmp_path / "cccd-assets"),
        lambda *args: None,
    )
    assert result["packets"] == packets
    assert result["cccdWorkbook"] == {
        "status": "error",
        "errorCode": "invalid-workbook",
        "summary": {"candidates": 0, "attached": 0, "unresolved": 0},
        "mappings": [],
    }
    assert "private-detail" not in json.dumps(result)


def test_ingest_without_supported_images_returns_safe_error(tmp_path, monkeypatch):
    import cccd_ingest as ingest
    from cccd_workbook import ExtractionResult

    monkeypatch.setattr(
        ingest,
        "extract_drawings",
        lambda *args: ExtractionResult(2, [], []),
    )
    result = ingest.ingest_cccd_workbook(
        "cards.xlsx",
        [{"name": "Synthetic A", "cccd": "000000000001"}],
        [packet()],
        str(tmp_path),
        {},
        str(tmp_path / "cccd-assets"),
        lambda *args: None,
    )
    workbook = result["cccdWorkbook"]
    assert workbook["status"] == "error"
    assert workbook["errorCode"] == "no-supported-images"
    assert workbook["summary"] == {"candidates": 0, "attached": 0, "unresolved": 0}


def test_ingest_with_no_usable_ocr_returns_safe_error(tmp_path, monkeypatch):
    import cccd_ingest as ingest
    from cccd_workbook import ExtractionResult

    card = candidate(tmp_path)
    monkeypatch.setattr(
        ingest,
        "extract_drawings",
        lambda *args: ExtractionResult(
            2,
            [card.front.drawing, card.back.drawing],
            [],
        ),
    )
    monkeypatch.setattr(
        ingest,
        "analyze_drawing",
        lambda drawing: (_ for _ in ()).throw(RuntimeError("private-ocr-detail")),
    )
    result = ingest.ingest_cccd_workbook(
        "cards.xlsx",
        [{"name": "Synthetic A", "cccd": "000000000001"}],
        [packet()],
        str(tmp_path),
        {},
        str(tmp_path / "cccd-assets"),
        lambda *args: None,
    )
    workbook = result["cccdWorkbook"]
    assert workbook["status"] == "error"
    assert workbook["errorCode"] == "ocr-unavailable"
    assert "private-ocr-detail" not in json.dumps(workbook)


def test_ingest_with_one_ocr_failure_is_partial(tmp_path, monkeypatch):
    import cccd_ingest as ingest
    from cccd_workbook import ExtractionResult

    card = candidate(tmp_path)
    monkeypatch.setattr(
        ingest,
        "extract_drawings",
        lambda *args: ExtractionResult(
            2,
            [card.front.drawing, card.back.drawing],
            [],
        ),
    )

    def analyze(drawing):
        if drawing.id == card.back.drawing.id:
            raise RuntimeError("private-back-ocr-detail")
        return card.front.ocr

    monkeypatch.setattr(ingest, "analyze_drawing", analyze)
    manifest_path = tmp_path / "packets" / "0" / "manifest.json"
    write_manifest(manifest_path)
    result = ingest.ingest_cccd_workbook(
        "cards.xlsx",
        [{"name": "Synthetic A", "cccd": "000000000001"}],
        [packet()],
        str(tmp_path),
        {0: str(manifest_path)},
        str(tmp_path / "cccd-assets"),
        lambda *args: None,
    )
    workbook = result["cccdWorkbook"]
    assert workbook["status"] == "partial"
    assert workbook["summary"]["candidates"] == 1
    assert "private-back-ocr-detail" not in json.dumps(workbook)


def test_ingest_attachment_failure_is_partial_and_unresolved(
    tmp_path,
    monkeypatch,
):
    import cccd_ingest as ingest
    from cccd_workbook import ExtractionResult

    card = candidate(tmp_path)
    monkeypatch.setattr(
        ingest,
        "extract_drawings",
        lambda *args: ExtractionResult(
            2,
            [card.front.drawing, card.back.drawing],
            [],
        ),
    )
    analyzed_by_id = {
        card.front.drawing.id: card.front.ocr,
        card.back.drawing.id: card.back.ocr,
    }
    monkeypatch.setattr(ingest, "analyze_drawing", lambda d: analyzed_by_id[d.id])
    monkeypatch.setattr(
        ingest,
        "_atomic_json_write",
        lambda *args: (_ for _ in ()).throw(OSError("private-write-detail")),
    )
    manifest_path = tmp_path / "packets" / "0" / "manifest.json"
    write_manifest(manifest_path)
    result = ingest.ingest_cccd_workbook(
        "cards.xlsx",
        [{"name": "Synthetic A", "cccd": "000000000001"}],
        [packet()],
        str(tmp_path),
        {0: str(manifest_path)},
        str(tmp_path / "cccd-assets"),
        lambda *args: None,
    )
    workbook = result["cccdWorkbook"]
    assert workbook["status"] == "partial"
    assert workbook["errorCode"] == "attachment-failed"
    assert workbook["summary"] == {"candidates": 1, "attached": 0, "unresolved": 1}
    assert workbook["mappings"][0]["attachedPacketIndex"] is None
    assert "private-write-detail" not in json.dumps(workbook)
```

- [ ] **Step 6: Implement production orchestration**

Import only the production modules:

```python
from cccd_matching import resolve_candidates
from cccd_ocr import analyze_drawing
from cccd_pairing import AnalyzedDrawing, pair_drawings
from cccd_workbook import extract_drawings


def _error_result(packets: list[dict], error_code: str) -> CccdIngestResult:
    return {
        "packets": packets,
        "cccdWorkbook": {
            "status": "error",
            "errorCode": error_code,
            "summary": {"candidates": 0, "attached": 0, "unresolved": 0},
            "mappings": [],
        },
    }


def ingest_cccd_workbook(
    xlsx_path: str,
    roster_rows: list[dict[str, str]],
    packets: list[dict],
    case_dir: str,
    packet_manifest_paths: dict[int, str],
    assets_dir: str,
    progress_cb: ProgressCallback,
) -> CccdIngestResult:
    try:
        extraction = extract_drawings(
            xlsx_path,
            os.path.join(assets_dir, "extracted"),
        )
    except Exception:
        return _error_result(packets, "invalid-workbook")
    if not extraction.drawings:
        return _error_result(packets, "no-supported-images")

    analyzed = []
    ocr_failures = 0
    for drawing in extraction.drawings:
        try:
            analyzed.append(AnalyzedDrawing(drawing, analyze_drawing(drawing)))
        except Exception:
            ocr_failures += 1
    if not analyzed:
        return _error_result(packets, "ocr-unavailable")

    try:
        candidates = pair_drawings(analyzed)
        resolution_result = resolve_candidates(candidates, roster_rows)
        plans = plan_candidate_mappings(
            candidates,
            resolution_result,
            roster_rows,
            packets,
            case_dir,
        )
    except Exception:
        return _error_result(packets, "invalid-workbook")

    packet_by_index = {packet["index"]: packet for packet in packets}
    mappings = []
    for done, plan in enumerate(plans, start=1):
        if plan.target_packet_index is None:
            mapping = deepcopy(plan.mapping)
        else:
            packet = packet_by_index.get(plan.target_packet_index)
            manifest_path = packet_manifest_paths.get(plan.target_packet_index)
            mapping = (
                attach_planned_mapping(
                    plan,
                    packet,
                    manifest_path,
                    case_dir,
                )
                if packet is not None and manifest_path is not None
                else _attachment_failure(plan)
            )
        mappings.append(mapping)
        progress_cb("cccd", done, len(plans), "")

    attached = sum(
        mapping["attachedPacketIndex"] is not None
        for mapping in mappings
    )
    summary = {
        "candidates": len(mappings),
        "attached": attached,
        "unresolved": len(mappings) - attached,
    }
    attachment_failed = any(
        "attachment-failed" in mapping["issues"]
        for mapping in mappings
    )
    if attachment_failed:
        error_code = "attachment-failed"
    elif extraction.issues:
        error_code = "extraction-incomplete"
    elif ocr_failures:
        error_code = "ocr-unavailable"
    else:
        error_code = None
    workbook = {
        "status": "partial" if error_code else "ready",
        "summary": summary,
        "mappings": mappings,
    }
    if error_code:
        workbook["errorCode"] = error_code
    return {"packets": packets, "cccdWorkbook": workbook}
```

The function above implements these status rules:

- `ready`: a usable result and no technical extraction/OCR/attachment failure.
- `partial`: at least one technical issue, while candidates/mappings remain usable.
- `error`: invalid workbook, no supported images, no usable OCR result, or coordinator invariant failure.
- Low confidence, manual, suggested, conflict, missing back, and no packet target remain ordinary unresolved mappings; they do not by themselves make the workbook `partial`.

Use only safe top-level error codes:

- malformed/unsafe workbook or invariant failure: `invalid-workbook`
- no valid drawings: `no-supported-images`
- some extraction issues: `extraction-incomplete`
- no usable OCR: `ocr-unavailable`
- any attachment failure: `attachment-failed`

Ensure `cccd_spike` is neither imported nor called.

- [ ] **Step 7: Run all CCCD module tests**

```bash
cd server && python3 -m pytest \
  cccd_workbook_test.py \
  cccd_ocr_test.py \
  cccd_pairing_test.py \
  cccd_matching_test.py \
  cccd_ingest_test.py \
  -q
```

Expected: all Phase 0 safety tests and production ingest tests pass.

- [ ] **Step 8: Commit the production orchestrator**

```bash
git add server/cccd_ingest.py server/cccd_ingest_test.py
git commit -m "feat: attach exact CCCD evidence to packets"
```

---

### Task 6: Integrate CCCD ingest after packet creation in the pipeline

**Files:**
- Modify: `server/pipeline.py`
- Modify: `server/pipeline_test.py`

**Interfaces:**
- Consumes: `ingest_cccd_workbook` from Task 5.
- Produces: a compatible trailing `cccd_xlsx_path=None` parameter on
  `run_pipeline` and result key `cccdWorkbook`.
- Guarantees: every packet manifest exists before ingest; no-CCCD calls retain existing behavior; CCCD result errors remain data, not pipeline exceptions.

- [ ] **Step 1: Add failing no-CCCD and CCCD integration tests**

Import the module so it can be monkeypatched:

```python
import cccd_ingest
```

Add:

```python
def test_pipeline_without_cccd_keeps_behavior_and_returns_null_workbook(
    tmp_path,
    monkeypatch,
):
    _install_fake_detection(monkeypatch)
    called = []
    monkeypatch.setattr(
        pl,
        "ingest_cccd_workbook",
        lambda *args, **kwargs: called.append(True),
    )
    result = pl.run_pipeline(
        str(tmp_path / "input.pdf"),
        None,
        str(tmp_path),
        lambda *args: None,
    )
    assert result["cccdWorkbook"] is None
    assert called == []


def test_pipeline_runs_cccd_after_manifests_and_returns_result(
    tmp_path,
    monkeypatch,
):
    _install_fake_detection(monkeypatch)
    monkeypatch.setattr(pl.dp, "_roster_rows", lambda path: _ROSTER_ROWS)
    seen = {}

    def fake_ingest(
        xlsx_path,
        roster_rows,
        packets,
        case_dir,
        packet_manifest_paths,
        assets_dir,
        progress_cb,
    ):
        assert all(os.path.isfile(path) for path in packet_manifest_paths.values())
        seen["rows"] = roster_rows
        seen["paths"] = packet_manifest_paths
        return {
            "packets": packets,
            "cccdWorkbook": {
                "status": "ready",
                "summary": {"candidates": 1, "attached": 1, "unresolved": 0},
                "mappings": [],
            },
        }

    monkeypatch.setattr(pl, "ingest_cccd_workbook", fake_ingest)
    progress = []
    result = pl.run_pipeline(
        str(tmp_path / "input.pdf"),
        "roster.xlsx",
        str(tmp_path),
        lambda *args: progress.append(args),
        cccd_xlsx_path="cards.xlsx",
    )
    assert seen["rows"][0]["cccd"] == "048091001309"
    assert set(seen["paths"]) == {0, 1}
    assert result["cccdWorkbook"]["summary"]["attached"] == 1
    assert ("cccd", 0, 0, "") in progress
```

- [ ] **Step 2: Run the pipeline tests and verify failure**

```bash
cd server && python3 -m pytest pipeline_test.py -q
```

Expected: `run_pipeline` rejects the fifth argument and does not return `cccdWorkbook`.

- [ ] **Step 3: Add the compatible parameter and normalized roster rows**

At roster load:

```python
roster_rows: list[dict[str, str]] = []
if roster_path:
    roster_rows_raw = dp._roster_rows(roster_path)
    roster_rows = all_roster_rows(roster_rows_raw)
    roster_names = dp.extract_roster_names(roster_rows_raw)
    by_cccd, by_name = build_roster_index(roster_rows_raw)
```

Import `ingest_cccd_workbook` directly in `pipeline.py` so tests can monkeypatch `pl.ingest_cccd_workbook`.

- [ ] **Step 4: Call ingest only after the packet loop**

After all packet metadata/manifests and the PDF summary exist:

```python
cccd_workbook = None
if cccd_xlsx_path is not None:
    progress_cb("cccd", 0, 0, "")
    packet_manifest_paths = {
        packet["index"]: os.path.join(
            job_dir,
            "packets",
            str(packet["index"]),
            "manifest.json",
        )
        for packet in packets_out
    }
    ingest_result = ingest_cccd_workbook(
        cccd_xlsx_path,
        roster_rows,
        packets_out,
        job_dir,
        packet_manifest_paths,
        os.path.join(job_dir, "cccd-assets"),
        progress_cb,
    )
    packets_out = ingest_result["packets"]
    cccd_workbook = ingest_result["cccdWorkbook"]

return {
    "summary": summary,
    "packets": packets_out,
    "cccdWorkbook": cccd_workbook,
}
```

The coordinator already converts CCCD-specific failures into a result. Do not add a `case.json` read/write here.

- [ ] **Step 5: Run pipeline, app, and ingest tests**

```bash
cd server && python3 -m pytest \
  pipeline_test.py \
  app_test.py \
  cccd_ingest_test.py \
  -q
```

Expected: all tests pass, including existing PDF-only pipeline tests.

- [ ] **Step 6: Commit pipeline integration**

```bash
git add server/pipeline.py server/pipeline_test.py
git commit -m "feat: run CCCD ingest in case pipeline"
```

---

### Task 7: Add the third upload chooser and browser-side blocking

**Files:**
- Create: `src/upload/cccd.ts`
- Create: `src/upload/cccd.test.ts`
- Modify: `src/upload/api.ts`
- Modify: `src/upload/api.test.ts`
- Modify: `src/components/UploadScreen.tsx`
- Create: `src/components/UploadScreen.test.ts`
- Modify: `src/components/UploadFlow.tsx`
- Modify: `src/styles.css`

**Interfaces:**
- Produces: `createCase(pdf, roster?, cccd?)`, `cccdRequirementMessage`, `canStartUpload`, and a third `.xlsx` chooser.
- Guarantees: selecting CCCD without roster disables submit and shows exactly `Cần bảng kê để tự động ghép CCCD.`; removing CCCD restores roster-optional behavior.

- [ ] **Step 1: Add failing pure validation and progress-label tests**

Create `src/upload/cccd.test.ts`:

```ts
import { describe, expect, it } from 'vitest'
import {
  canStartUpload,
  cccdRequirementMessage,
} from './cccd'

describe('CCCD upload eligibility', () => {
  it('blocks CCCD without a roster', () => {
    expect(canStartUpload(true, false, true, false)).toBe(false)
    expect(cccdRequirementMessage(false, true))
      .toBe('Cần bảng kê để tự động ghép CCCD.')
  })

  it('allows CCCD with roster and restores roster-optional flow after removal', () => {
    expect(canStartUpload(true, true, true, false)).toBe(true)
    expect(cccdRequirementMessage(true, true)).toBeNull()
    expect(canStartUpload(true, false, false, false)).toBe(true)
    expect(cccdRequirementMessage(false, false)).toBeNull()
  })

  it('still requires a PDF and respects busy state', () => {
    expect(canStartUpload(false, true, true, false)).toBe(false)
    expect(canStartUpload(true, true, true, true)).toBe(false)
  })
})
```

Add to `src/upload/api.test.ts`:

```ts
it('maps CCCD processing to the approved Vietnamese label', () => {
  expect(stageLabel('cccd')).toBe('Đọc và ghép ảnh CCCD…')
})
```

- [ ] **Step 2: Run the focused Vitest files and verify failure**

```bash
npx vitest run src/upload/cccd.test.ts src/upload/api.test.ts
```

Expected: missing module/functions and unmapped `cccd` stage.

- [ ] **Step 3: Implement pure eligibility and API types**

Create `src/upload/cccd.ts`:

```ts
export const CCCD_ROSTER_REQUIRED = 'Cần bảng kê để tự động ghép CCCD.'

export function cccdRequirementMessage(
  hasRoster: boolean,
  hasCccd: boolean,
): string | null {
  return hasCccd && !hasRoster ? CCCD_ROSTER_REQUIRED : null
}

export function canStartUpload(
  hasPdf: boolean,
  hasRoster: boolean,
  hasCccd: boolean,
  busy: boolean,
): boolean {
  return hasPdf && !busy && cccdRequirementMessage(hasRoster, hasCccd) === null
}
```

In `src/upload/api.ts`:

- Add `'cccd'` to the documented stage union.
- Add `cccd: 'Đọc và ghép ảnh CCCD…'` to `STAGE_LABELS`.
- Define `CccdSummary`.
- Add `cccdName: string | null` and `cccdSummary: CccdSummary | null` to `CaseDetail`.
- Change `createCase` to accept the third argument and append it as `cccd`.

- [ ] **Step 4: Add a failing multipart contract test**

Append to `src/upload/api.test.ts` and import `createCase`:

```ts
test('createCase appends the CCCD workbook to multipart form', async () => {
  const fetchMock = vi.fn(async (_url: string, init?: RequestInit) => {
    const form = init?.body as FormData
    expect((form.get('pdf') as File).name).toBe('input.pdf')
    expect((form.get('roster') as File).name).toBe('roster.xlsx')
    expect((form.get('cccd') as File).name).toBe('cards.xlsx')
    return new Response(JSON.stringify({ case_id: 'case-1' }), {
      status: 200,
      headers: { 'content-type': 'application/json' },
    })
  })
  vi.stubGlobal('fetch', fetchMock)

  await createCase(
    new File(['pdf'], 'input.pdf', { type: 'application/pdf' }),
    new File(['roster'], 'roster.xlsx'),
    new File(['cards'], 'cards.xlsx'),
  )

  expect(fetchMock).toHaveBeenCalledOnce()
  vi.unstubAllGlobals()
})
```

Add `vi` to the Vitest import.

- [ ] **Step 5: Run the API tests**

```bash
npx vitest run src/upload/api.test.ts src/upload/cccd.test.ts
```

Expected: all focused tests pass.

- [ ] **Step 6: Add a failing static render test for exact chooser copy**

Create `src/components/UploadScreen.test.ts` without adding a DOM dependency:

```ts
import { createElement } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { expect, test } from 'vitest'
import UploadScreen from './UploadScreen'

test('renders an optional xlsx CCCD chooser and high-resolution guidance', () => {
  const html = renderToStaticMarkup(createElement(UploadScreen, {
    busy: false,
    onStart: () => undefined,
  }))
  expect(html).toContain('Chọn file ảnh CCCD Excel (tuỳ chọn)')
  expect(html).toContain('Nên dùng ảnh gốc hoặc ảnh độ phân giải cao')
  expect((html.match(/accept="\.xlsx"/g) ?? []).length).toBe(2)
})
```

- [ ] **Step 7: Run the render test and verify failure**

```bash
npx vitest run src/components/UploadScreen.test.ts
```

Expected: the CCCD label/helper and second `.xlsx` input are absent.

- [ ] **Step 8: Implement the third chooser and flow forwarding**

Change the prop:

```ts
interface Props {
  onStart: (pdf: File, roster?: File, cccd?: File) => void
  busy: boolean
}
```

Add `cccd` state/ref, another `dropzone dropzone-sm` input with `accept=".xlsx"`, and exact copy:

```tsx
<span className="dropzone-label">
  {cccd ? cccd.name : 'Chọn file ảnh CCCD Excel (tuỳ chọn)'}
</span>
<span className="upload-helper">
  Nên dùng ảnh gốc hoặc ảnh độ phân giải cao, được chèn trực tiếp trong file .xlsx.
</span>
```

Compute:

```ts
const validationMessage = cccdRequirementMessage(!!roster, !!cccd)
const canStart = canStartUpload(!!pdf, !!roster, !!cccd, busy)
```

Provide an explicit removal action so the user does not have to reopen the
native picker:

```tsx
{cccd && (
  <button
    type="button"
    className="upload-file-clear"
    onClick={() => {
      setCccd(null)
      if (cccdInput.current) cccdInput.current.value = ''
    }}
  >
    Bỏ file CCCD
  </button>
)}
```

Render the inline message when non-null and call:

```ts
onStart(pdf, roster ?? undefined, cccd ?? undefined)
```

In `UploadFlow`:

```ts
const onStart = async (pdf: File, roster?: File, cccd?: File) => {
  setErr(null)
  setBusy(true)
  try {
    const { case_id } = await createCase(pdf, roster, cccd)
    setCaseId(case_id)
    setScreen('list')
    refreshList()
  } catch {
    setErr(CONN_ERR)
  } finally {
    setBusy(false)
  }
}
```

Add concise CSS:

```css
.upload-helper {
  color: var(--text-muted);
  font-size: 11px;
  line-height: 1.4;
}
.upload-validation {
  color: var(--danger);
  font-size: 12px;
  margin: -2px 0 10px;
}
.upload-file-clear {
  border: 0;
  background: transparent;
  color: var(--accent);
  cursor: pointer;
  font-size: 12px;
  margin: -6px 0 10px;
}
```

- [ ] **Step 9: Run frontend focused tests and type/build verification**

```bash
npx vitest run \
  src/upload/api.test.ts \
  src/upload/cccd.test.ts \
  src/components/UploadScreen.test.ts
npm run build
```

Expected: tests pass and production build succeeds.

- [ ] **Step 10: Commit the upload UI**

```bash
git add \
  src/upload/api.ts \
  src/upload/api.test.ts \
  src/upload/cccd.ts \
  src/upload/cccd.test.ts \
  src/components/UploadScreen.tsx \
  src/components/UploadScreen.test.ts \
  src/components/UploadFlow.tsx \
  src/styles.css
git commit -m "feat: add CCCD workbook upload control"
```

---

### Task 8: Render only the compact CCCD result in case detail

**Files:**
- Modify: `src/upload/cccd.ts`
- Modify: `src/upload/cccd.test.ts`
- Modify: `src/components/CaseDetail.tsx`
- Create: `src/components/CaseDetail.test.ts`
- Modify: `src/styles.css`

**Interfaces:**
- Consumes: `CaseDetail.cccdName` and redacted `CaseDetail.cccdSummary`.
- Produces: exact ready/partial count copy or exact error copy.
- Guarantees: no identity, mapping, path, anchor, or OCR values render; cases without CCCD render no CCCD line.

- [ ] **Step 1: Add failing summary-format tests**

Append to `src/upload/cccd.test.ts`:

```ts
import { formatCccdSummary } from './cccd'

it('formats ready and partial summaries as aggregate counts', () => {
  expect(formatCccdSummary({
    status: 'ready',
    candidates: 3,
    attached: 2,
    unresolved: 1,
  })).toBe('CCCD: 2 đã gắn · 1 chưa ghép')
  expect(formatCccdSummary({
    status: 'partial',
    candidates: 3,
    attached: 1,
    unresolved: 2,
    errorCode: 'extraction-incomplete',
  })).toBe('CCCD: 1 đã gắn · 2 chưa ghép')
})

it('uses generic copy for an ingest error', () => {
  expect(formatCccdSummary({
    status: 'error',
    candidates: 0,
    attached: 0,
    unresolved: 0,
    errorCode: 'invalid-workbook',
  })).toBe('CCCD: Không xử lý được file ảnh')
})
```

- [ ] **Step 2: Run the summary tests and verify failure**

```bash
npx vitest run src/upload/cccd.test.ts
```

Expected: missing `formatCccdSummary`.

- [ ] **Step 3: Implement the allow-listed formatter**

```ts
import type { CccdSummary } from './api'

export function formatCccdSummary(summary: CccdSummary): string {
  if (summary.status === 'error') {
    return 'CCCD: Không xử lý được file ảnh'
  }
  return `CCCD: ${summary.attached} đã gắn · ${summary.unresolved} chưa ghép`
}
```

The formatter never consumes `errorCode` beyond using the typed object and never accepts mapping data.

- [ ] **Step 4: Add failing static CaseDetail render tests**

Create `src/components/CaseDetail.test.ts`:

```ts
import { createElement } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { expect, test } from 'vitest'
import type { CaseDetail as CaseDetailT, CccdSummary } from '../upload/api'
import CaseDetail from './CaseDetail'

const base: Omit<CaseDetailT, 'cccdSummary'> = {
  id: 'case-1',
  name: 'Synthetic case',
  createdAt: null,
  status: 'ready' as const,
  pdfName: 'input.pdf',
  rosterName: 'roster.xlsx',
  cccdName: 'cards.xlsx',
  summary: { found: 0, roster_n: 0, matched: 0, auto_merged: 0 },
  error: null,
  packets: [],
  progress: { done: 0, total: 0, flagged: 0 },
}

function render(cccdSummary: CccdSummary | null) {
  return renderToStaticMarkup(createElement(CaseDetail, {
    detail: { ...base, cccdSummary },
    onOpenPacket: () => undefined,
    onBack: () => undefined,
    onExport: () => undefined,
  }))
}

test('renders only aggregate CCCD counts for ready or partial ingest', () => {
  const html = render({
    status: 'partial',
    candidates: 3,
    attached: 1,
    unresolved: 2,
    errorCode: 'extraction-incomplete',
  })
  expect(html).toContain('CCCD: 1 đã gắn · 2 chưa ghép')
  expect(html).not.toContain('000000000001')
  expect(html).not.toContain('candidateId')
})

test('renders generic CCCD error and omits line when no workbook exists', () => {
  expect(render({
    status: 'error',
    candidates: 0,
    attached: 0,
    unresolved: 0,
    errorCode: 'invalid-workbook',
  })).toContain('CCCD: Không xử lý được file ảnh')
  expect(render(null)).not.toContain('CCCD:')
})
```

- [ ] **Step 5: Run the CaseDetail test and verify failure**

```bash
npx vitest run src/components/CaseDetail.test.ts
```

Expected: the aggregate CCCD line is absent.

- [ ] **Step 6: Render the compact line and style it**

Import `formatCccdSummary`, then place this immediately below the existing result banner:

```tsx
{detail.cccdName && detail.cccdSummary && (
  <div className={`cccd-summary ${detail.cccdSummary.status}`}>
    {formatCccdSummary(detail.cccdSummary)}
  </div>
)}
```

Add:

```css
.cccd-summary {
  margin: -6px 0 16px;
  color: var(--text-muted);
  font-size: 13px;
}
.cccd-summary.error {
  color: var(--danger);
}
```

- [ ] **Step 7: Run focused frontend tests and production build**

```bash
npx vitest run \
  src/upload/cccd.test.ts \
  src/components/CaseDetail.test.ts \
  src/components/UploadScreen.test.ts \
  src/upload/api.test.ts
npm run build
```

Expected: all tests pass and TypeScript/build are clean.

- [ ] **Step 8: Commit case-detail summary**

```bash
git add \
  src/upload/cccd.ts \
  src/upload/cccd.test.ts \
  src/components/CaseDetail.tsx \
  src/components/CaseDetail.test.ts \
  src/styles.css
git commit -m "feat: show CCCD attachment summary"
```

---

### Task 9: Full regression, privacy audit, and browser smoke

**Files:**
- Create: `server/cccd_smoke_app.py`
- Modify only when verification exposes a defect in files already listed above.

**Interfaces:**
- Consumes: the completed backend and frontend thin slice.
- Produces: evidence that all acceptance criteria pass without real PII in committed artifacts.

- [ ] **Step 1: Run every backend test**

```bash
cd server && python3 -m pytest -q
```

Expected: all backend tests pass, including existing packet split, checklist, report, Phase 0, and new production-ingest coverage.

- [ ] **Step 2: Run every frontend test and the production build**

```bash
npx vitest run
npm run build
```

Expected: all Vitest tests pass and Vite produces `dist/`.

- [ ] **Step 3: Audit the detail/list boundary and routine logging**

Run:

```bash
rg -n "cccdWorkbook|mappings|ocrIdentity|sourcePath|packetPath" \
  server/app.py server/cases.py src
rg -n "print\\(|logger\\.|logging\\." \
  server/cccd_ingest.py server/cccd_workbook.py server/cccd_ocr.py
```

Verify:

- `server/app.py` removes `cccdWorkbook` and inserts only `compact_cccd_summary`.
- `CaseStore.list()` does not expose `cccdName`, `cccdWorkbook`, or mappings.
- No production logging prints identities, OCR text, workbook cells, or paths.
- Frontend types contain only the compact CCCD summary.

- [ ] **Step 4: Inspect repository changes for synthetic-only data**

```bash
git diff --check
git status --short
git diff --stat 59cf0e9..HEAD
rg -n "[0-9]{12}" \
  server/cccd_ingest_test.py \
  src/upload/cccd.test.ts \
  src/components/CaseDetail.test.ts
```

Expected: only deliberate synthetic values such as `000000000001`; no user names, real CCCD values, real workbook paths, or extracted image bytes are committed.

- [ ] **Step 5: Create a disposable synthetic browser backend**

Create `server/cccd_smoke_app.py`. It refuses to start without an explicit
disposable root, replaces `appmod.store`, and stubs only the heavy pipeline so
the real multipart API, persistence, redaction, manifest endpoint, and React UI
remain under test:

```python
"""PII-free browser fixture for the CCCD upload thin slice."""
from __future__ import annotations

import json
import os
import time

from PIL import Image

import app as appmod
import checklist
from cases import CaseStore


ROOT = os.environ["CTV_CCCD_SMOKE_ROOT"]
appmod.store = CaseStore(ROOT)


def _page(path: str, color: str) -> dict:
    Image.new("RGB", (1000, 630), color).save(path, format="PNG")
    return {"src": path, "width": 1000, "height": 630}


def _fake_pipeline(
    pdf_path,
    roster_path,
    job_dir,
    progress_cb,
    cccd_xlsx_path=None,
):
    packet_dir = os.path.join(job_dir, "packets", "0")
    os.makedirs(packet_dir, exist_ok=True)
    progress_cb("splitting", 1, 1, "")
    progress_cb("ocr", 1, 1, "")

    front_id = "cccd-excel-card-drawing-0001-drawing-0002-front"
    back_id = "cccd-excel-card-drawing-0001-drawing-0002-back"
    contract_path = os.path.join(packet_dir, "synthetic-contract.png")
    front_path = os.path.join(packet_dir, "synthetic-cccd-front.png")
    back_path = os.path.join(packet_dir, "synthetic-cccd-back.png")
    docs = [
        {
            "id": "contract",
            "kind": "contract",
            "label": "Hợp đồng dịch vụ",
            "pages": [_page(contract_path, "white")],
        },
        {
            "id": front_id,
            "kind": "id_front",
            "label": "CCCD (Excel) · Mặt trước",
            "pages": [_page(front_path, "lightblue")],
        },
        {
            "id": back_id,
            "kind": "id_back",
            "label": "CCCD (Excel) · Mặt sau",
            "pages": [_page(back_path, "lightgray")],
        },
    ]
    fields = [{
        "key": "cccd",
        "label": "Số CCCD",
        "group": "Danh tính",
        "check": "compare",
        "kind": "text",
        "expected": "000000000001",
        "sources": [{
            "docId": front_id,
            "page": 0,
            "value": "000000000001",
            "bbox": {"x": 160, "y": 260, "width": 360, "height": 70},
            "confidence": .95,
        }],
    }]
    packet = {
        "index": 0,
        "name": "Synthetic Reviewer",
        "pages": [0, 0],
        "n_pages": 1,
        "confidence": "green",
        "flags": [],
        "labels": [],
        "matchedBy": "cccd",
        "ocrIdentity": {"cccd": "000000000001", "name": "Synthetic Reviewer"},
        "rosterIdentity": {"cccd": "000000000001", "name": "Synthetic Reviewer"},
    }
    manifest = {
        "id": "synthetic-reviewer",
        "name": "Synthetic Reviewer",
        "product": "",
        "heading": "Hồ sơ CTV",
        "status": "pending",
        "exempt": False,
        "docs": docs,
        "fields": fields,
        "checks": checklist.build_checklist(fields, packet, docs),
    }
    with open(
        os.path.join(packet_dir, "manifest.json"),
        "w",
        encoding="utf-8",
    ) as handle:
        json.dump(manifest, handle, ensure_ascii=False, indent=2)

    if cccd_xlsx_path:
        progress_cb("cccd", 1, 1, "")
        time.sleep(1.8)
        workbook = {
            "status": "ready",
            "summary": {"candidates": 1, "attached": 1, "unresolved": 0},
            "mappings": [{"candidateId": "synthetic-candidate"}],
        }
    else:
        workbook = None
    return {
        "summary": {
            "found": 1,
            "roster_n": 1,
            "matched": 1,
            "auto_merged": 0,
        },
        "packets": [packet],
        "cccdWorkbook": workbook,
    }


appmod.run_pipeline = _fake_pipeline
app = appmod.app
```

This module contains only synthetic data and never imports `cccd_ingest`; Task
5's production-orchestrator tests remain the extraction, OCR, matching, and
attachment evidence.

- [ ] **Step 6: Launch the smoke backend and frontend**

In terminal 1, create a disposable directory and three empty upload files.
The smoke pipeline does not read their contents:

```bash
SMOKE_ROOT="$(mktemp -d)"
touch "$SMOKE_ROOT/input.pdf" "$SMOKE_ROOT/roster.xlsx" "$SMOKE_ROOT/cards.xlsx"
printf '%s\n' "$SMOKE_ROOT"
CTV_CCCD_SMOKE_ROOT="$SMOKE_ROOT" \
  python3 -m uvicorn cccd_smoke_app:app --app-dir server \
  --host 127.0.0.1 --port 8000
```

In terminal 2:

```bash
npm run dev -- --host 127.0.0.1 --port 5173
```

Open `http://127.0.0.1:5173/`.

- [ ] **Step 7: Verify the upload blocker in the browser**

Use the three files from the disposable smoke root:

1. Open `Tải hồ sơ`.
2. Select a synthetic PDF.
3. Select a synthetic `cards.xlsx` in the third chooser without selecting a roster.
4. Confirm `Bắt đầu xử lý` is disabled.
5. Confirm the exact inline text `Cần bảng kê để tự động ghép CCCD.`.
6. Click `Bỏ file CCCD` and confirm the button is enabled with the PDF alone.
7. Re-select CCCD and a synthetic roster; confirm the button is enabled.
8. Confirm the browser console has no errors.

- [ ] **Step 8: Verify processing, summary, and packet tabs**

Submit the three disposable files through `cccd_smoke_app.py`. Confirm:

1. Live progress renders `Đọc và ghép ảnh CCCD…`.
2. The completed case detail renders `CCCD: 1 đã gắn · 0 chưa ghép`.
3. Opening the matched packet shows `CCCD (Excel) · Mặt trước` and `CCCD (Excel) · Mặt sau`.
4. Selecting A1 opens the front image and focuses the located number box.
5. A1 remains reviewer-controlled and does not display an automatic pass verdict.
6. No identity appears in the case-level CCCD summary.

- [ ] **Step 9: Verify failure isolation with a backend test**

Add this focused API/pipeline test to `server/pipeline_test.py`; it is
deterministic and avoids relying on a real OCR read:

```python
def test_cccd_error_result_keeps_pdf_packets_reviewable(tmp_path, monkeypatch):
    _install_fake_detection(monkeypatch)
    monkeypatch.setattr(pl.dp, "_roster_rows", lambda path: _ROSTER_ROWS)
    monkeypatch.setattr(
        pl,
        "ingest_cccd_workbook",
        lambda xlsx, rows, packets, case_dir, paths, assets, cb: {
            "packets": packets,
            "cccdWorkbook": {
                "status": "error",
                "errorCode": "invalid-workbook",
                "summary": {"candidates": 0, "attached": 0, "unresolved": 0},
                "mappings": [],
            },
        },
    )
    result = pl.run_pipeline(
        str(tmp_path / "input.pdf"),
        "roster.xlsx",
        str(tmp_path),
        lambda *args: None,
        cccd_xlsx_path="malformed.xlsx",
    )
    assert len(result["packets"]) == 2
    assert result["cccdWorkbook"]["status"] == "error"
    assert result["cccdWorkbook"]["errorCode"] == "invalid-workbook"
```

Run:

```bash
cd server && python3 -m pytest pipeline_test.py -q
```

Then verify in the already-covered detail render test that an error summary
renders `CCCD: Không xử lý được file ảnh`. Together these prove:

- The case reaches a reviewable non-error packet state.
- Case detail displays `CCCD: Không xử lý được file ảnh`.
- Existing PDF-derived packet documents remain available.
- No raw exception text appears in the UI or API detail payload.

- [ ] **Step 10: Rerun full verification after the smoke fixture**

```bash
cd server && python3 -m pytest -q
cd .. && npx vitest run
npm run build
git diff --check
```

Expected: backend and frontend suites pass, the production build succeeds,
and the diff has no whitespace errors.

- [ ] **Step 11: Commit the synthetic smoke fixture**

When verification required no implementation correction:

```bash
git add server/cccd_smoke_app.py server/pipeline_test.py
git commit -m "test: add CCCD browser smoke coverage"
```

When verification required a correction, stage only the corrected files plus
`server/cccd_smoke_app.py` and `server/pipeline_test.py`, commit with
`fix: complete CCCD upload verification`, and rerun Step 10 before reporting
completion.

---

## Final Acceptance Checklist

- [ ] PDF-only and PDF-plus-roster uploads still work.
- [ ] CCCD without roster is blocked in browser and returns API 422 with `cccd-requires-roster`.
- [ ] Invalid extension returns 422; over 100 MB returns 413; neither creates a case.
- [ ] Source workbook is stored as `<case-dir>/cccd.xlsx`.
- [ ] Pipeline calls production ingest only after all packet manifests exist.
- [ ] Only exact, high-confidence, unique roster and packet matches attach.
- [ ] Front/back documents use stable IDs and content-addressed server filenames.
- [ ] A1 routes to the front number box and stays `review`.
- [ ] Re-running ingest duplicates neither documents nor sources.
- [ ] Manifest failure records no false attachment.
- [ ] Workbook or per-image failure leaves the packet case usable.
- [ ] Full mappings survive restart in `case.json`.
- [ ] Case detail exposes only the compact summary; case list remains unchanged.
- [ ] Case deletion removes the workbook and every CCCD artifact.
- [ ] Backend suite, frontend suite, production build, privacy audit, and browser smoke pass.
