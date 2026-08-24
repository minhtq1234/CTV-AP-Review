# Boundary Proposal and Revision Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Complete the current boundary safety guard and let a reviewer confirm or correct ambiguous packet ranges through an immutable case revision.

**Architecture:** Keep the existing visual splitter as a candidate producer, add a pure proposal layer that fuses stored packet flags and contract starts, and require explicit reviewer resolution before corrected ranges are processed. `keep-current` records an auditable acceptance on the source case; `create-revision` copies immutable source inputs into a new case and reruns the existing pipeline with validated starts.

**Tech Stack:** Python 3, FastAPI, Pydantic v2, PyMuPDF, pytest, React 18, TypeScript, Vitest.

**Spec:** `docs/superpowers/specs/2026-08-20-packet-boundary-safety-and-correction-design.md`

## Global Constraints

- Work only in `/Users/lap16603/Documents/New project/work/CTV_APReview-v1` on branch `ver1`.
- Preserve the original PDF, roster, CCCD workbook, manifests, packet reviews, and unrelated local changes.
- Do not mutate packet page ranges in place; corrected ranges create a new linked case revision.
- Do not transfer field reviews across changed boundaries.
- Do not expose OCR text, names, CCCD values, or source paths in list/proposal responses or logs.
- Candidate and API pages are zero-based; the UI displays one-based pages.
- A roster count may rank candidates but must never invent or force a boundary.
- Keep boundary rewrites reviewer-confirmed; no unattended auto-split is introduced.
- Existing unresolved cases remain readable and review-only.
- The legacy review API currently has no prepared-package publication endpoint;
  `publicationBlocked` is the server-owned fail-closed contract for that future
  integration. Do not alter the separate intake CLI/package-builder workflow,
  which does not consume these case records.

---

### Task 1: Complete the case-level safety and report guard

**Files:**
- Modify: `server/boundary_assessment.py:34-56`
- Modify: `server/boundary_assessment_test.py`
- Modify: `server/report.py:66-121`
- Modify: `server/report_test.py`
- Modify: `server/app.py:90-111,239-256,305-318`
- Modify: `server/app_test.py`
- Modify: `src/upload/api.ts:40-145`
- Modify: `src/upload/api.test.ts`

**Interfaces:**
- Consumes: existing `assess_packet_boundary(packet, manifest, case_summary) -> dict`.
- Produces: additive `resolution=None` parameter on `assess_packet_boundary`; `assess_case_boundaries(case: dict, manifests: dict[int, dict]) -> dict` with `{status, packetIndexes, reasons}`; case API field `boundaryStatus`; report field `boundaryWarnings`.

- [ ] **Step 1: Write failing backend tests for the case guard**

```python
def test_case_boundary_status_blocks_only_review_packets():
    case = {
        "summary": {"found": 2, "roster_n": 2},
        "packets": [
            {"index": 0, "pages": [0, 7], "flags": []},
            {"index": 1, "pages": [8, 23], "flags": ["length-out-of-range"]},
        ],
    }
    manifests = {
        0: {"docs": [{"kind": "contract", "pages": [{"src": "pg0.png"}]}]},
        1: {"docs": [
            {"kind": "contract", "pages": [{"src": "pg0.png"}]},
            {"kind": "contract", "pages": [{"src": "pg8.png"}]},
        ]},
    }
    assert assess_case_boundaries(case, manifests) == {
        "status": "review",
        "packetIndexes": [1],
        "reasons": ["length-out-of-range", "multiple-contract-starts"],
    }
```

Add a report test asserting that `boundaryWarnings` contains packet 2 and that the ordinary resubmission `groups` remain unchanged. Add an app test asserting `GET /api/cases/{cid}` returns `publicationBlocked: true` and `POST /report` retains the warning instead of treating it as a participant resubmission.

- [ ] **Step 2: Run the focused tests and verify failure**

Run:

```bash
python3 -m pytest -q server/boundary_assessment_test.py server/report_test.py server/app_test.py
```

Expected: FAIL because `assess_case_boundaries`, `boundaryStatus`, `publicationBlocked`, and `boundaryWarnings` do not exist.

- [ ] **Step 3: Implement the minimal case guard**

```python
def assess_case_boundaries(case: dict, manifests: dict[int, dict]) -> dict:
    resolution = case.get("boundaryResolution")
    if resolution and resolution.get("action") == "keep-current":
        return {"status": "accepted", "packetIndexes": [], "reasons": resolution["reasons"]}
    reasons: list[str] = []
    packet_indexes: list[int] = []
    for packet in case.get("packets", []):
        assessment = assess_packet_boundary(
            packet,
            manifests.get(packet["index"]),
            case.get("summary"),
            resolution,
        )
        if assessment["status"] != "review":
            continue
        packet_indexes.append(packet["index"])
        for reason in assessment["reasons"]:
            if reason not in reasons:
                reasons.append(reason)
    return {
        "status": "review" if packet_indexes else "clear",
        "packetIndexes": packet_indexes,
        "reasons": reasons,
    }
```

In `get_case`, derive `boundaryStatus` from loaded manifests and set `publicationBlocked = boundaryStatus["status"] == "review"`. Pass the same result into `build_report`; render a top-level Markdown warning and a CSV warning row without adding it to `groups` or the participant `Cần gửi lại` count.

- [ ] **Step 4: Add and normalize the frontend contract**

```ts
export interface CaseBoundaryStatus {
  status: 'clear' | 'review' | 'accepted'
  packetIndexes: number[]
  reasons: BoundaryReason[]
}

export interface CaseDetail {
  // existing fields
  boundaryStatus: CaseBoundaryStatus
  publicationBlocked: boolean
}
```

Add an API normalization test for legacy responses that defaults to a clear status but never overrides an explicit server review status.

- [ ] **Step 5: Run tests and commit**

Run:

```bash
python3 -m pytest -q server/boundary_assessment_test.py server/report_test.py server/app_test.py
npm test -- --run src/upload/api.test.ts
```

Expected: PASS.

```bash
git add server/boundary_assessment.py server/boundary_assessment_test.py server/report.py server/report_test.py server/app.py server/app_test.py src/upload/api.ts src/upload/api.test.ts
git commit -m "fix: block publication on unresolved boundaries"
```

---

### Task 2: Build deterministic boundary proposals

**Files:**
- Create: `server/boundary_proposal.py`
- Create: `server/boundary_proposal_test.py`

**Interfaces:**
- Consumes: case packet metadata, packet manifests, and total PDF page count.
- Produces: `build_boundary_proposal(case, manifests, total_pages) -> dict`; `validate_revision_starts(starts, total_pages, first_packet_start) -> tuple[int, ...]`.

- [ ] **Step 1: Write failing proposal tests**

```python
def test_proposal_fuses_contract_and_cadence_without_forcing_roster_count():
    case = {
        "id": "source-case",
        "summary": {"found": 2, "roster_n": 3},
        "packets": [
            {"index": 0, "pages": [0, 7], "flags": []},
            {"index": 1, "pages": [8, 23], "flags": ["length-out-of-range"]},
        ],
    }
    manifests = {
        0: _manifest(0),
        1: _manifest(0, 8),
    }
    proposal = build_boundary_proposal(case, manifests, total_pages=24)
    assert proposal["status"] == "review_required"
    assert proposal["expectedPacketCount"] == 3
    assert [candidate["page"] for candidate in proposal["candidateStarts"]] == [0, 8, 16]
    assert proposal["candidateStarts"][2]["signals"] == ["contract-title", "cadence"]
    assert proposal["candidateStarts"][2]["packetIndex"] == 1
    assert proposal["candidateStarts"][2]["relativePage"] == 8
```

Also test that a visual/current start alone is `medium`, a contract start plus cadence is `high`, candidates are sorted and deduplicated, and a roster count of four does not manufacture a fourth start.

Add a private-evidence test where two consecutive non-empty document identity
keys differ: the later contract start receives `identity-change` and becomes
`high` even when cadence is absent. Empty identity keys never create that
signal.

Write validation tests for duplicates, unsorted starts, negative/out-of-range starts, a start before the source preamble boundary, and an empty final range.

- [ ] **Step 2: Run tests and verify failure**

Run: `python3 -m pytest -q server/boundary_proposal_test.py`

Expected: FAIL because `boundary_proposal.py` does not exist.

- [ ] **Step 3: Implement candidate fusion**

```python
def build_boundary_proposal(case, manifests, total_pages):
    candidates: dict[int, set[str]] = {}
    affected: list[int] = []
    for packet in case.get("packets", []):
        start, _end = packet["pages"]
        candidates.setdefault(start, set()).add("visual")
        assessment = assess_packet_boundary(packet, manifests.get(packet["index"]), case.get("summary"))
        for page in assessment["candidateStarts"]:
            candidates.setdefault(page, set()).add("contract-title")
        if assessment["status"] == "review":
            affected.append(packet["index"])
    cadence = _median_packet_length(case.get("packets", []))
    _add_cadence_signals(candidates, cadence)
    _add_identity_change_signals(candidates, case, manifests)
    starts = [
        _serialize_candidate(page, signals, _packet_location(case, page))
        for page, signals in sorted(candidates.items())
    ]
    return {
        "status": "review_required" if affected else "not_needed",
        "sourceCaseId": case["id"],
        "expectedPacketCount": (case.get("summary") or {}).get("roster_n"),
        "currentPacketCount": len(case.get("packets", [])),
        "candidateStarts": starts,
        "affectedPacketIndexes": affected,
}
```

`_add_cadence_signals` marks a non-first candidate when its gap from the prior
candidate differs from the median current packet length by no more than
`max(2, round(median * 0.5))`. `_serialize_candidate` returns `high` only for
`contract-title` plus either `identity-change` or `cadence`; `visual` alone is
`medium`. `_add_identity_change_signals` walks private `boundaryEvidence`
records in absolute page order and marks only the later start when two
consecutive non-empty identity keys differ. It never returns or logs the keys.
`_packet_location`
returns only `{packetIndex, relativePage}` for the existing page endpoint. Do
not include names, CCCD values, OCR text, or local paths.

- [ ] **Step 4: Implement strict start validation**

```python
def validate_revision_starts(starts, total_pages, first_packet_start):
    if not starts or any(type(page) is not int for page in starts):
        raise ValueError("boundary-starts-invalid")
    if starts != sorted(set(starts)):
        raise ValueError("boundary-starts-invalid")
    if starts[0] != first_packet_start:
        raise ValueError("boundary-preamble-invalid")
    if starts[-1] >= total_pages or any(page < 0 for page in starts):
        raise ValueError("boundary-starts-out-of-range")
    return tuple(starts)
```

```python
def _add_cadence_signals(candidates, median_length):
    ordered = sorted(candidates)
    tolerance = max(2, round(median_length * .5))
    for previous, page in zip(ordered, ordered[1:]):
        if abs((page - previous) - median_length) <= tolerance:
            candidates[page].add("cadence")
```

- [ ] **Step 5: Run tests and commit**

Run: `python3 -m pytest -q server/boundary_proposal_test.py server/boundary_assessment_test.py`

Expected: PASS.

```bash
git add server/boundary_proposal.py server/boundary_proposal_test.py
git commit -m "feat: derive deterministic boundary proposals"
```

---

### Task 3: Persist boundary resolutions and revision linkage

**Files:**
- Modify: `server/cases.py:125-293`
- Modify: `server/cases_test.py`

**Interfaces:**
- Consumes: validated proposal/resolution dictionaries.
- Produces: `CaseStore.set_boundary_resolution(cid, resolution) -> dict | None`; `CaseStore.create_revision(source_cid, now) -> str`; additive case fields `sourceCaseId`, `revisionIds`, `revisionNumber`, `boundaryResolution`.

- [ ] **Step 1: Write failing persistence tests**

```python
def test_create_revision_links_cases_without_copying_reviews(tmp_path):
    store = CaseStore(str(tmp_path))
    source = store.create("batch.pdf", "batch.pdf", "roster.xlsx", "2026-08-25T00:00:00Z")
    store.set_result(source, {"found": 1, "roster_n": 2}, [_packet_with_review()])
    revision = store.create_revision(source, "2026-08-25T00:01:00Z")
    assert store.get(revision)["sourceCaseId"] == source
    assert store.get(revision)["revisionNumber"] == 1
    assert store.get(source)["revisionIds"] == [revision]
    assert store.get(revision)["packets"] == []
    assert store.get(revision)["boundaryResolution"] is None
```

Add restart/load coverage and a test that `set_boundary_resolution` preserves
packet reviews byte-for-byte. Add deletion tests proving deletion is
non-cascading: deleting a revision leaves its source intact; deleting a source
leaves the revision usable with the original `sourceCaseId` string.

- [ ] **Step 2: Run tests and verify failure**

Run: `python3 -m pytest -q server/cases_test.py`

Expected: FAIL because the revision methods and additive defaults do not exist.

- [ ] **Step 3: Add migration-safe defaults**

```python
case.setdefault("sourceCaseId", None)
case.setdefault("revisionIds", [])
case.setdefault("revisionNumber", 0)
case.setdefault("boundaryResolution", None)
```

Add the same fields in `create`. `create_revision` must create a new processing
case with copied filenames, `revisionNumber = source.revisionNumber + 1`, empty
packets/reviews, and append only the new ID to the source's `revisionIds`.

- [ ] **Step 4: Add resolution persistence**

```python
def set_boundary_resolution(self, cid: str, resolution: dict) -> dict | None:
    case = self._idx.get(cid)
    if case is None:
        return None
    case["boundaryResolution"] = dict(resolution)
    self._write(case)
    return case
```

Keep accepted page starts and `resolvedAt`; do not persist a reviewer name.

- [ ] **Step 5: Run tests and commit**

Run: `python3 -m pytest -q server/cases_test.py`

Expected: PASS.

```bash
git add server/cases.py server/cases_test.py
git commit -m "feat: persist boundary revision lineage"
```

---

### Task 4: Run the pipeline with reviewer-confirmed starts

**Files:**
- Modify: `server/pipeline.py:200-332`
- Modify: `server/pipeline_test.py`

**Interfaces:**
- Consumes: `confirmed_starts: tuple[int, ...] | None` already validated by `validate_revision_starts`.
- Produces: additive final parameter `confirmed_starts: tuple[int, ...] | None = None` on `run_pipeline(pdf_path, roster_path, job_dir, progress_cb, cccd_xlsx_path=None, confirmed_starts=None)`; result summary field `boundary_source: 'detected' | 'reviewer-confirmed'`.

- [ ] **Step 1: Write a failing confirmed-start test**

```python
def test_confirmed_starts_bypass_visual_cover_selection(monkeypatch, tmp_path):
    _install_fake_detection(monkeypatch)
    monkeypatch.setattr(pl.dp, "covers_from_scores", lambda *_: (_ for _ in ()).throw(AssertionError()))
    result = pl.run_pipeline(
        str(tmp_path / "input.pdf"),
        None,
        str(tmp_path),
        lambda *args: None,
        confirmed_starts=(0, 3),
    )
    assert result["summary"]["boundary_source"] == "reviewer-confirmed"
    assert [packet["pages"] for packet in result["packets"]] == [[0, 2], [3, 5]]
```

Add a detected-path regression test asserting the existing splitter calls and output remain unchanged when `confirmed_starts` is `None`.

- [ ] **Step 2: Run tests and verify failure**

Run: `python3 -m pytest -q server/pipeline_test.py`

Expected: FAIL because `run_pipeline` rejects `confirmed_starts`.

- [ ] **Step 3: Implement the optional boundary source**

```python
if confirmed_starts is None:
    scores, seed = dp.seed_scores(bands)
    threshold = dp.derive_threshold(scores)
    cover_pages = dp.covers_from_scores(scores, threshold)
    kept_covers, merged_covers = dp.prune_excess_covers(cover_pages, scores, roster_n)
    boundary_source = "detected"
else:
    kept_covers = list(confirmed_starts)
    merged_covers = []
    scores = [1.0 if page in confirmed_starts else 0.0 for page in range(n)]
    threshold = 0.0
    boundary_source = "reviewer-confirmed"
```

Build bounds and continue through the existing OCR/roster/CCCD flow. Add `boundary_source` to the summary without renaming existing keys.

- [ ] **Step 4: Run the focused and splitter tests**

Run:

```bash
python3 -m pytest -q server/pipeline_test.py splitter/detect_packets_test.py
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add server/pipeline.py server/pipeline_test.py
git commit -m "feat: process reviewer-confirmed packet starts"
```

---

### Task 5: Add boundary proposal and resolution endpoints

**Files:**
- Modify: `server/app.py:165-231,239-367`
- Modify: `server/app_test.py`
- Modify: `server/README.md`

**Interfaces:**
- Consumes: `build_boundary_proposal`, `validate_revision_starts`, CaseStore revision methods, and the exact `run_pipeline` signature from Task 4.
- Produces: `GET /api/cases/{cid}/boundary-proposal`; `POST /api/cases/{cid}/boundary-proposal/resolve`; strict opt-in `CTV_BOUNDARY_CORRECTION_ENABLED=1` for mutation while proposal GET remains available in shadow mode.

- [ ] **Step 1: Write failing API tests**

```python
def test_keep_current_records_resolution_without_reprocessing(tmp_path, monkeypatch):
    client, cid = _ready_ambiguous_case(monkeypatch, tmp_path)
    response = client.post(
        f"/api/cases/{cid}/boundary-proposal/resolve",
        json={"action": "keep-current"},
    )
    assert response.status_code == 200
    assert response.json()["caseId"] == cid
    assert appmod.store.get(cid)["boundaryResolution"]["action"] == "keep-current"
```

Add tests for unknown cases, invalid/duplicate/unsorted starts, no source-file
mutation, new revision linkage, input copying, empty reviews, and `run_pipeline`
receiving the exact validated starts. With the flag disabled, GET still returns
the proposal with `correctionEnabled: false`, while both resolution actions
return HTTP 409 without mutation; enable the module setting in mutation tests.

- [ ] **Step 2: Run tests and verify failure**

Run: `python3 -m pytest -q server/app_test.py`

Expected: FAIL with 404 because the endpoints do not exist.

- [ ] **Step 3: Add validated request models**

```python
class BoundaryResolutionBody(BaseModel):
    action: Literal["keep-current", "create-revision"]
    starts: list[int] | None = None

    @field_validator("starts")
    @classmethod
    def starts_are_plain_integers(cls, starts):
        if starts is not None and any(type(page) is not int for page in starts):
            raise ValueError("boundary-starts-invalid")
        return starts
```

Reject missing starts for `create-revision` and supplied starts for `keep-current` with HTTP 422.

Parse the environment once at startup with only the exact value `1` enabling
mutation. Return `correctionEnabled` in the proposal and reject resolve before
creating/copying anything when disabled. Document the local opt-in in
`server/README.md`; production remains shadow-only until proposal accuracy
meets the pilot tolerance.

- [ ] **Step 4: Implement immutable revision creation**

For `create-revision`: validate against the source PDF page count, create the revision metadata, copy `input.pdf`, optional `roster.xlsx`, and optional `cccd.xlsx` with `shutil.copy2`, then start `_run_case` with the confirmed start tuple. If copying fails, mark only the revision as error; never change the source case.

```python
def _copy_revision_inputs(source_dir: str, revision_dir: str) -> tuple[str, str | None, str | None]:
    copied: list[str | None] = []
    for name in ("input.pdf", "roster.xlsx", "cccd.xlsx"):
        source = os.path.join(source_dir, name)
        if os.path.isfile(source):
            target = os.path.join(revision_dir, name)
            shutil.copy2(source, target)
            copied.append(target)
        else:
            copied.append(None)
    if copied[0] is None:
        raise ValueError("boundary-source-pdf-missing")
    return copied[0], copied[1], copied[2]
```

Thread the starts through the existing background runner without changing
current callers:

```python
def _run_case(
    cid: str,
    pdf_path: str,
    roster_path: str | None,
    cccd_path: str | None = None,
    confirmed_starts: tuple[int, ...] | None = None,
) -> None:
    result = run_pipeline(
        pdf_path,
        roster_path,
        store.case_dir(cid),
        cb,
        cccd_xlsx_path=cccd_path,
        confirmed_starts=confirmed_starts,
    )
```

The first implementation deliberately reprocesses every reviewer-confirmed
range in the revision. It may reuse immutable rendered-page assets later, but
must never copy field observations or review decisions across changed ranges.
Before `store.set_result`, stamp each result packet and private manifest with
the case's persisted `revisionNumber` as `packetRevision`.

For `keep-current`: rebuild the current proposal and persist
`{action, starts, reasons, resolvedAt}` on the source case. The packet and
case assessments return `accepted` while retaining reasons for audit/display.
Return without rerunning OCR.

`GET /boundary-proposal` returns `accepted_current` after `keep-current` and
`superseded` after a revision is created. Revision creation also records the
new revision ID in the source resolution so repeat submissions cannot create
parallel revisions from the same accepted proposal.

- [ ] **Step 5: Run tests and commit**

Run:

```bash
python3 -m pytest -q server/app_test.py server/cases_test.py server/boundary_proposal_test.py server/pipeline_test.py
```

Expected: PASS.

```bash
git add server/app.py server/app_test.py server/README.md
git commit -m "feat: resolve packet boundaries through revisions"
```

---

### Task 6: Build the exception-first boundary review screen

**Files:**
- Create: `src/components/BoundaryReviewScreen.tsx`
- Create: `src/components/BoundaryReviewScreen.test.tsx`
- Modify: `src/upload/api.ts:131-277`
- Modify: `src/upload/api.test.ts`
- Modify: `src/components/CaseDetail.tsx:1-260`
- Modify: `src/components/caseDetail.test.tsx`
- Modify: `src/components/UploadFlow.tsx:1-259`
- Modify: `src/styles.css`

**Interfaces:**
- Consumes: proposal GET and resolution POST endpoints.
- Produces: `BoundaryProposal`, `getBoundaryProposal`, `resolveBoundaryProposal`; a screen that edits zero-based starts while displaying one-based pages.

- [ ] **Step 1: Add failing API and component tests**

```ts
it('displays one-based candidate pages but posts zero-based starts', async () => {
  render(<BoundaryReviewScreen proposal={proposalWithPages([0, 8, 16])} onResolve={onResolve} onBack={() => {}} />)
  expect(screen.getByText('Trang 9')).toBeTruthy()
  expect(screen.getByText('Trang 17')).toBeTruthy()
  await userEvent.click(screen.getByRole('button', { name: 'Tạo phiên bản đã sửa' }))
  expect(onResolve).toHaveBeenCalledWith({ action: 'create-revision', starts: [0, 8, 16] })
})
```

Add tests for affected ranges only, adding/removing candidate starts, `Giữ ranh giới hiện tại`, Back with no mutation, disabled submit for invalid starts, navigation to the returned revision case, and the accepted source label `Ranh giới đã xác nhận`.

- [ ] **Step 2: Run tests and verify failure**

Run:

```bash
npm test -- --run src/upload/api.test.ts src/components/BoundaryReviewScreen.test.tsx src/components/caseDetail.test.tsx
```

Expected: FAIL because the types, API calls, and component do not exist.

- [ ] **Step 3: Implement the API contract**

```ts
export interface BoundaryCandidate {
  page: number
  packetIndex: number
  relativePage: number
  signals: Array<'visual' | 'contract-title' | 'identity-change' | 'cadence'>
  confidence: 'high' | 'medium'
}

export interface BoundaryProposal {
  status: 'not_needed' | 'review_required' | 'accepted_current' | 'superseded'
  sourceCaseId: string
  expectedPacketCount: number | null
  currentPacketCount: number
  candidateStarts: BoundaryCandidate[]
  affectedPacketIndexes: number[]
  correctionEnabled: boolean
}
```

`resolveBoundaryProposal` returns `{caseId: string, sourceCaseId: string, status: string}` and throws on non-2xx responses.

- [ ] **Step 4: Implement the screen and navigation**

Add `boundary` to `UploadFlow`'s `Screen` union. `CaseDetail` shows `Kiểm tra ranh giới` only when `boundaryStatus.status === 'review'`. The new screen shows compact thumbnails for the affected packet ranges, signal labels without identity values, editable starts, and the three approved actions. When `correctionEnabled` is false, keep the view read-only with `Đang chạy thử đề xuất ranh giới`; Back remains active and no mutation control is enabled. On revision creation, poll/open the returned case ID; on keep-current, refresh the source case.

```tsx
const previewSrc = (caseId: string, candidate: BoundaryCandidate) => (
  `${API_BASE}/api/cases/${caseId}/packets/${candidate.packetIndex}/page/pg${candidate.relativePage}.png`
)

<button disabled={!validStarts} onClick={() => onResolve({
  action: 'create-revision',
  starts: selectedStarts,
})}>
  Tạo phiên bản đã sửa
</button>
```

- [ ] **Step 5: Run frontend and production-build verification**

Run:

```bash
npm test -- --run src/upload/api.test.ts src/components/BoundaryReviewScreen.test.tsx src/components/caseDetail.test.tsx src/components/reviewPresentation.test.tsx
npm run build
```

Expected: tests PASS and production build exits 0.

- [ ] **Step 6: Run the complete stage verification and commit**

Run:

```bash
python3 -m pytest -q server/boundary_assessment_test.py server/boundary_proposal_test.py server/pipeline_test.py server/cases_test.py server/report_test.py server/app_test.py
npm test -- --run
```

Expected: all tests PASS. Verify manually with sanitized fixtures that the original case files and reviews remain byte-identical after revision creation.

```bash
git add src/components/BoundaryReviewScreen.tsx src/components/BoundaryReviewScreen.test.tsx src/upload/api.ts src/upload/api.test.ts src/components/CaseDetail.tsx src/components/caseDetail.test.tsx src/components/UploadFlow.tsx src/styles.css
git commit -m "feat: review and correct packet boundaries"
```
