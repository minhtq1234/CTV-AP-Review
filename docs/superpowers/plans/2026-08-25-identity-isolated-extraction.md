# Identity-Isolated Extraction Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Prevent field comparison from combining evidence belonging to different participants, and preserve versioned, navigable observations when automatic assignment is impossible.

**Architecture:** Convert document-level OCR hits into explicit observations and identity candidates, resolve exactly one roster target before projecting participant fields, and gate `evalField` on an extraction status. A resolved packet receives only sources assigned to its participant; conflicts remain inspectable but produce internal `cannot_assess`, mapped to the existing user-facing `Cần review` state.

**Tech Stack:** Python 3, pytesseract, PyMuPDF, pytest, React 18, TypeScript, Vitest.

**Spec:** `docs/superpowers/specs/2026-08-20-packet-boundary-safety-and-correction-design.md`

**Depends on:** `docs/superpowers/plans/2026-08-25-boundary-proposal-and-revision.md`

## Global Constraints

- Work only in `/Users/lap16603/Documents/New project/work/CTV_APReview-v1` on branch `ver1`.
- Do not let OCR confidence select between conflicting participant identities.
- Require a unique roster target before field comparison becomes `ready`.
- Permit page/document OCR for proposal evidence before resolution, but do not
  project roster values or compare fields unless the packet boundary is clear
  or came from reviewer-confirmed starts.
- Preserve document ID, relative page, bounding box, candidate value, confidence, and extractor version for every observation.
- Do not log or expose names, CCCD values, raw OCR text, or source paths in aggregate APIs.
- `cannot_assess` is an internal extraction state; the existing three-state dashboard maps it to `review` with `Không thể đánh giá tự động`.
- Existing legacy manifests remain readable, but unresolved mixed packets stay review-only.
- Exact CCCD match precedes normalized-name fallback; duplicate roster keys are ambiguous, not first-wins.

---

### Task 1: Add pure participant-assignment rules

**Files:**
- Create: `server/participant_assignment.py`
- Create: `server/participant_assignment_test.py`

**Interfaces:**
- Consumes: document identity candidates and canonical roster rows.
- Produces: `roster_target_key(workbook_sha256, row_index) -> str`; `resolve_participant(identity_candidates, roster_rows, workbook_sha256) -> dict`.

- [ ] **Step 1: Write failing assignment tests**

```python
def test_conflicting_exact_identities_cannot_assess_even_when_one_is_higher_confidence():
    candidates = [
        {"docId": "contract-0", "name": "Person A", "cccd": "000000000001", "confidence": .91},
        {"docId": "contract-1", "name": "Person B", "cccd": "000000000002", "confidence": .99},
    ]
    rows = [
        {"name": "Person A", "cccd": "000000000001"},
        {"name": "Person B", "cccd": "000000000002"},
    ]
    result = resolve_participant(candidates, rows, "a" * 64)
    assert result["status"] == "cannot_assess"
    assert result["identityConflict"] is True
    assert result["rosterTargetKey"] is None
```

Also cover one unique exact CCCD, one unique sufficiently specific normalized
name, one single-token/short name that must abstain, duplicate roster CCCDs,
duplicate normalized names, empty candidates, and several documents agreeing
on one target.

- [ ] **Step 2: Run tests and verify failure**

Run: `python3 -m pytest -q server/participant_assignment_test.py`

Expected: FAIL because `participant_assignment.py` does not exist.

- [ ] **Step 3: Implement stable target keys and duplicate-safe indexes**

```python
def roster_target_key(workbook_sha256: str, row_index: int) -> str:
    if not re.fullmatch(r"[0-9a-f]{64}", workbook_sha256) or row_index < 0:
        raise ValueError("roster-target-invalid")
    return f"{workbook_sha256}:{row_index}"

def _unique_index(rows, key_fn):
    index: dict[str, list[int]] = {}
    for row_index, row in enumerate(rows):
        key = key_fn(row)
        if key:
            index.setdefault(key, []).append(row_index)
    return index
```

An index entry resolves only when it contains exactly one row index.
Name fallback is eligible only when the existing normalized form contains at
least two non-empty tokens and at least five alphanumeric characters; exact
CCCD matching has precedence. This deterministic floor prevents a unique but
underspecified short OCR fragment from selecting a participant.

- [ ] **Step 4: Implement conflict-first resolution**

```python
def resolve_participant(identity_candidates, roster_rows, workbook_sha256):
    candidate_targets = _candidate_target_indexes(identity_candidates, roster_rows)
    unique_targets = sorted(set(target for target in candidate_targets if target is not None))
    conflict = len(unique_targets) > 1
    if conflict or not unique_targets:
        return {
            "status": "cannot_assess" if conflict else "review",
            "rosterTargetKey": None,
            "rowIndex": None,
            "matchedBy": "unmatched",
            "identityConflict": conflict,
            "documentIds": [],
        }
    row_index = unique_targets[0]
    return {
        "status": "ready",
        "rosterTargetKey": roster_target_key(workbook_sha256, row_index),
        "rowIndex": row_index,
        "matchedBy": _strongest_match_for(row_index, candidate_targets),
        "identityConflict": False,
        "documentIds": sorted(_documents_for_target(row_index, candidate_targets)),
    }
```

Do not use confidence to remove a conflicting target.

- [ ] **Step 5: Run tests and commit**

Run: `python3 -m pytest -q server/participant_assignment_test.py`

Expected: PASS.

```bash
git add server/participant_assignment.py server/participant_assignment_test.py
git commit -m "feat: resolve unique participant targets"
```

---

### Task 2: Emit versioned observations and per-document identities

**Files:**
- Modify: `server/ocr_extract.py:691-762,928-1012`
- Modify: `server/ocr_extract_test.py`

**Interfaces:**
- Consumes: existing document segmentation and field hits.
- Produces: `EXTRACTOR_VERSION = 'ctv-ocr/2.0'`; `observation_records(fields) -> list[dict]`; `ocr_packet` keys `identityCandidates`, `observations`, `extractorVersion`, and `boundaryEvidence`.

- [ ] **Step 1: Write failing OCR shape tests**

```python
def test_ocr_packet_keeps_identities_separate_by_contract(monkeypatch, tmp_path):
    _install_two_contract_ocr(monkeypatch)
    result = ocr_packet("synthetic.pdf", 0, 3, str(tmp_path))
    assert result["extractorVersion"] == "ctv-ocr/2.0"
    assert [item["docId"] for item in result["identityCandidates"]] == ["contract-0", "contract-1"]
    assert result["identityCandidates"][0]["cccd"] != result["identityCandidates"][1]["cccd"]
    assert all(set(item) == {
        "fieldKey", "docId", "page", "bbox", "value", "confidence", "extractorVersion"
    } for item in result["observations"])
```

Add coverage that `boundaryEvidence.contractStarts` contains relative pages and derived identity keys but no raw page text.

- [ ] **Step 2: Run tests and verify failure**

Run: `python3 -m pytest -q server/ocr_extract_test.py`

Expected: FAIL because the new result fields do not exist.

- [ ] **Step 3: Flatten existing sources into observations**

```python
EXTRACTOR_VERSION = "ctv-ocr/2.0"

def observation_records(fields: list[dict]) -> list[dict]:
    return [
        {
            "fieldKey": field["key"],
            "docId": source["docId"],
            "page": source["page"],
            "bbox": dict(source["bbox"]),
            "value": source["value"],
            "confidence": source["confidence"],
            "extractorVersion": EXTRACTOR_VERSION,
        }
        for field in fields
        for source in field.get("sources", [])
        if source.get("docId")
    ]
```

- [ ] **Step 4: Derive identity per document instead of packet-wide max confidence**

For each segmented document, run the existing field extraction on only that document's words, derive its best name/CCCD, and emit one candidate with its `docId`. Keep the legacy packet `identity` key temporarily for read compatibility, but set it only when all non-empty document candidates agree; otherwise return empty values.

```python
identity_candidates = []
for doc_id, doc_words in words_by_doc.items():
    doc_fields = extract_fields({doc_id: doc_words}, {})
    by_key = {field["key"]: field for field in doc_fields}
    identity_candidates.append({
        "docId": doc_id,
        "cccd": _best_value(by_key["cccd"]),
        "name": _best_value(by_key["hoten"]),
        "confidence": _identity_confidence(by_key),
    })
identity = _agreed_identity(identity_candidates)
```

Emit boundary evidence shaped as:

```python
{
    "contractStarts": [
        {"relativePage": 0, "docId": "contract-0", "identityKey": "cccd:000000000001"},
        {"relativePage": 2, "docId": "contract-1", "identityKey": "cccd:000000000002"},
    ]
}
```

The private `identityKey` is `cccd:` plus normalized digits when present,
otherwise `name:` plus the existing normalized-name key, otherwise empty. It
is used only to detect a change between document starts, never returned through
case-list/proposal APIs or logs.

- [ ] **Step 5: Run tests and commit**

Run: `python3 -m pytest -q server/ocr_extract_test.py`

Expected: PASS.

```bash
git add server/ocr_extract.py server/ocr_extract_test.py
git commit -m "feat: preserve versioned OCR observations"
```

---

### Task 3: Project fields only from the resolved participant

**Files:**
- Modify: `server/participant_assignment.py`
- Modify: `server/participant_assignment_test.py`
- Modify: `server/pipeline.py:219-332`
- Modify: `server/pipeline_test.py`
- Modify: `server/roster_workbook.py`
- Modify: `server/roster_workbook_test.py`

**Interfaces:**
- Consumes: packet boundary assessment/source, `ocr_packet.identityCandidates`, observations, canonical roster rows, and SHA-256 of the roster workbook.
- Produces: `project_participant_fields(fields, allowed_doc_ids, roster_row) -> list[dict]`; private packet fields `packetRevision`, `extractionStatus`, `extractorVersion`, `rosterTargetKey`, `identityConflict`; manifest fields `packetRevision`, `comparisonReady`, `extractorVersion`, `observations`.

- [ ] **Step 1: Write failing projection and pipeline tests**

```python
def test_projection_excludes_other_participant_documents():
    fields = [_field("cccd", sources=[
        _source("contract-0", "000000000001"),
        _source("contract-1", "000000000002"),
    ])]
    projected = project_participant_fields(fields, {"contract-0"}, {"cccd": "000000000001"})
    assert [source["docId"] for source in projected[0]["sources"]] == ["contract-0"]
    assert projected[0]["expected"] == "000000000001"
```

Add a pipeline test where two exact roster targets produce `cannot_assess`, no
`rosterTargetKey`, `comparisonReady: false`, the inherited `packetRevision`,
and no field `expected` values. Add a resolved test that filters out the other
document and remains `ready`. Add a single-identity packet with a blocking
boundary assessment: it may retain observations for the proposal/reviewer, but
must remain `review` with `comparisonReady: false`. The same range processed
from reviewer-confirmed starts may become `ready`.

- [ ] **Step 2: Run tests and verify failure**

Run:

```bash
python3 -m pytest -q server/participant_assignment_test.py server/pipeline_test.py server/roster_workbook_test.py
```

Expected: FAIL because projection and extraction metadata do not exist.

- [ ] **Step 3: Add deterministic roster workbook hashing**

Add `sha256_source(xlsx_source) -> str` that hashes bytes while restoring the original file position. File paths are opened read-only; uploaded streams are rewound. Test that the same bytes produce the same digest and the caller's stream position is preserved.

```python
def sha256_source(xlsx_source) -> str:
    if isinstance(xlsx_source, (str, os.PathLike)):
        with open(xlsx_source, "rb") as handle:
            return _sha256_stream(handle)
    position = xlsx_source.tell()
    try:
        xlsx_source.seek(0)
        return _sha256_stream(xlsx_source)
    finally:
        xlsx_source.seek(position)
```

- [ ] **Step 4: Implement participant projection and pipeline gating**

```python
boundary_ready = (
    packet_boundary["status"] in {"clear", "accepted"}
    or boundary_source == "reviewer-confirmed"
)
assignment = resolve_participant(
    result["identityCandidates"],
    roster_rows,
    roster_digest,
)
if boundary_ready and assignment["status"] == "ready":
    row = roster_rows[assignment["rowIndex"]]
    fields = project_participant_fields(
        result["folder"]["fields"],
        set(assignment["documentIds"]),
        row,
    )
else:
    row = None
    fields = project_participant_fields(result["folder"]["fields"], set(), None)
```

Persist observations for reviewer inspection, but set `comparisonReady: false`
and leave all expected values empty unless both `boundary_ready` and assignment
status are `ready`. A boundary-review packet's extraction status remains
`review`; an identity conflict remains `cannot_assess`. Never call the old
packet-wide highest-confidence identity matcher for a conflicting packet.

- [ ] **Step 5: Run tests and commit**

Run:

```bash
python3 -m pytest -q server/participant_assignment_test.py server/pipeline_test.py server/roster_workbook_test.py server/ocr_extract_test.py
```

Expected: PASS.

```bash
git add server/participant_assignment.py server/participant_assignment_test.py server/pipeline.py server/pipeline_test.py server/roster_workbook.py server/roster_workbook_test.py
git commit -m "fix: isolate extraction by participant identity"
```

---

### Task 4: Expose safe extraction status and provenance

**Files:**
- Modify: `server/cases.py:114-122`
- Modify: `server/cases_test.py`
- Modify: `server/app.py:90-111,239-256,343-354`
- Modify: `server/app_test.py`
- Modify: `src/upload/api.ts:87-145,252-267`
- Modify: `src/upload/api.test.ts`
- Modify: `src/ctv/types.ts`

**Interfaces:**
- Consumes: packet extraction metadata and manifest provenance.
- Produces: API-safe `ExtractionStatus = 'ready' | 'review' | 'cannot_assess'`; manifest `comparisonReady`; no internal roster key or observation values in the case-list/detail response.

- [ ] **Step 1: Write failing API privacy and migration tests**

```python
def test_case_detail_exposes_status_but_not_observation_values(tmp_path, monkeypatch):
    client, cid = _case_with_private_observations(monkeypatch, tmp_path)
    payload = client.get(f"/api/cases/{cid}").json()
    packet = payload["packets"][0]
    assert packet["extractionStatus"] == "cannot_assess"
    assert packet["identityConflict"] is True
    assert "observations" not in packet
    assert "private-marker" not in json.dumps(payload)
```

Add response-derivation tests for legacy packets: unresolved boundaries remain
`review`; a legacy manifest is `ready` only when it contains one
participant-compatible source set. Keep persisted legacy defaults conservative
because `CaseStore` does not load packet manifests.

- [ ] **Step 2: Run tests and verify failure**

Run: `python3 -m pytest -q server/cases_test.py server/app_test.py`

Expected: FAIL because extraction status is absent.

- [ ] **Step 3: Add packet defaults and response filtering**

```python
out.setdefault("extractionStatus", "review")
out.setdefault("extractorVersion", "legacy")
out.setdefault("identityConflict", False)
```

Keep `rosterTargetKey` only in the private manifest and pipeline result. In
`_packet_for_response`, load the manifest and boundary assessment, derive the
safe legacy status, and return only `extractionStatus`, `extractorVersion`, and
`identityConflict`. Keep observations inside the packet manifest endpoint only.
`rewrite_manifest_urls` continues to rewrite page paths without altering
observation data.

- [ ] **Step 4: Add frontend types and normalization**

```ts
export type ExtractionStatus = 'ready' | 'review' | 'cannot_assess'

export interface PacketMeta {
  // existing fields
  extractionStatus: ExtractionStatus
  extractorVersion: string
  identityConflict: boolean
}
```

Add `comparisonReady`, `extractionStatus`, `extractorVersion`, and optional
`observations` to `CtvFolder`; keep defaults migration-safe for existing
manifests.

```ts
export interface CtvFolder {
  // existing fields
  comparisonReady?: boolean
  extractionStatus?: ExtractionStatus
  extractorVersion?: string
  observations?: CtvObservation[]
}
```

Define `CtvObservation` in `src/ctv/types.ts` with exactly `fieldKey`, `docId`,
`page`, `bbox`, `value`, `confidence`, and `extractorVersion`, matching the
backend observation record from Task 2.

- [ ] **Step 5: Run tests and commit**

Run:

```bash
python3 -m pytest -q server/cases_test.py server/app_test.py
npm test -- --run src/upload/api.test.ts
```

Expected: PASS.

```bash
git add server/cases.py server/cases_test.py server/app.py server/app_test.py src/upload/api.ts src/upload/api.test.ts src/ctv/types.ts
git commit -m "feat: expose safe extraction provenance"
```

---

### Task 5: Gate field and packet verdicts on extraction readiness

**Files:**
- Modify: `src/ctv/checks.ts:43-105`
- Modify: `src/ctv/checks.test.ts`
- Modify: `src/logic/packetEvidenceSummary.ts:17-54`
- Modify: `src/logic/packetEvidenceSummary.test.ts`
- Modify: `src/logic/packetGrid.ts:41-68`
- Modify: `src/logic/packetGrid.test.ts`
- Modify: `src/components/PacketGrid.tsx`
- Modify: `src/components/FolderReview.tsx`
- Modify: `src/components/reviewPresentation.test.tsx`

**Interfaces:**
- Consumes: `folder.comparisonReady` and packet `extractionStatus`.
- Produces: internal non-comparable field result; dashboard maps `cannot_assess` to `review`; grid shows unassigned evidence without match/mismatch.

- [ ] **Step 1: Write failing verdict tests**

```ts
it('does not compare observations when participant assignment is unresolved', () => {
  const folder = makeFolder({ comparisonReady: false, extractionStatus: 'cannot_assess' })
  expect(rankFolder(folder).every(result => result.verdict === 'review')).toBe(true)
  expect(summarizePacketEvidence(folder).aiResult).toBe('review')
  expect(buildPacketGrid(folder).rows[0].cells[0].status).toBe('review')
})
```

Add tests that no `Khớp` or `Không khớp` copy appears for unresolved observations and that the reason `Không thể đánh giá tự động` is displayed.

- [ ] **Step 2: Run tests and verify failure**

Run:

```bash
npm test -- --run src/ctv/checks.test.ts src/logic/packetEvidenceSummary.test.ts src/logic/packetGrid.test.ts src/components/reviewPresentation.test.tsx
```

Expected: FAIL because checks ignore extraction readiness.

- [ ] **Step 3: Add the comparison gate**

At the top of `evalField`, return a review result whose `actual` is `—` and
whose `sources` maps every source to verdict `unread` when
`folder.comparisonReady === false`. Thread `folder` into the compare-field
branch rather than changing numeric/date normalization.

In `summarizePacketEvidence`, extraction/boundary review takes precedence over missing documents and mismatches. In `buildPacketGrid`, unresolved observations render as `review`, never `match` or `mismatch`.

```ts
export function evalField(f: CtvField, folder: CtvFolder): CheckResult {
  if (folder.comparisonReady === false) {
    return {
      verdict: 'review',
      actual: '—',
      sources: f.sources.map(source => ({ source, verdict: 'unread' })),
    }
  }
  // existing check switch remains unchanged
}
```

- [ ] **Step 4: Render the approved explanation**

Display an amber message above the grid:

> **Không thể đánh giá tự động**<br>
> Phát hiện nhiều danh tính hoặc chưa xác định được đúng người. Hãy xác nhận ranh giới hồ sơ trước khi đối chiếu.

Keep document focus available so reviewers can inspect the evidence.

- [ ] **Step 5: Run frontend verification and commit**

Run:

```bash
npm test -- --run src/ctv/checks.test.ts src/logic/packetEvidenceSummary.test.ts src/logic/packetGrid.test.ts src/components/reviewPresentation.test.tsx
npm run build
```

Expected: PASS and build exits 0.

```bash
git add src/ctv/checks.ts src/ctv/checks.test.ts src/logic/packetEvidenceSummary.ts src/logic/packetEvidenceSummary.test.ts src/logic/packetGrid.ts src/logic/packetGrid.test.ts src/components/PacketGrid.tsx src/components/FolderReview.tsx src/components/reviewPresentation.test.tsx
git commit -m "fix: abstain on unresolved participant identity"
```

---

### Task 6: Add integrated mixed-packet regression coverage

**Files:**
- Create: `server/identity_isolation_acceptance_test.py`
- Modify: `server/pipeline_test.py`
- Modify: `src/components/FolderReview.interaction.test.tsx`

**Interfaces:**
- Consumes: all identity-isolation interfaces from Tasks 1-5.
- Produces: a permanent regression proving mixed identities never produce a clear participant verdict.

- [ ] **Step 1: Write the backend acceptance fixture**

Create a synthetic two-contract OCR result containing different exact CCCDs and names, two roster rows, and one current packet range. Drive `run_pipeline` with mocked raster/OCR I/O but real observation, assignment, projection, manifest, and case-response logic.

Assert:

```python
assert packet["extractionStatus"] == "cannot_assess"
assert packet["packetRevision"] == manifest["packetRevision"]
assert packet["rosterTargetKey"] is None
assert packet["identityConflict"] is True
assert manifest["comparisonReady"] is False
assert all(field["expected"] == "" for field in manifest["fields"])
assert {source["docId"] for field in manifest["fields"] for source in field["sources"]} == {
    "contract-0", "contract-1"
}
```

- [ ] **Step 2: Write the frontend interaction regression**

Load the unresolved manifest, click each review cell, and assert document focus still works while no cell or packet summary renders `Khớp` or `Không khớp`.

- [ ] **Step 3: Run the new tests and verify they pass**

Run:

```bash
python3 -m pytest -q server/identity_isolation_acceptance_test.py server/pipeline_test.py
npm test -- --run src/components/FolderReview.interaction.test.tsx
```

Expected: PASS.

- [ ] **Step 4: Run the complete server/frontend suites**

Run:

```bash
python3 -m pytest -q server
npm test -- --run
npm run build
```

Expected: all tests PASS and build exits 0. If an unrelated baseline test fails, record the exact pre-existing failure and do not weaken the identity-isolation assertions.

- [ ] **Step 5: Commit**

```bash
git add server/identity_isolation_acceptance_test.py server/pipeline_test.py src/components/FolderReview.interaction.test.tsx
git commit -m "test: prevent cross-person extraction contamination"
```
