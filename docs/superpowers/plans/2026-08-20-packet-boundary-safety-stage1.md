# Packet Boundary Safety Stage 1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Prevent any packet with unresolved boundary evidence from appearing valid, and surface the reason in both the Tổng hợp list and packet reviewer without changing packet ranges or participant resubmission counts.

**Architecture:** Add a pure backend boundary-assessment module that derives response-only evidence from stored packet metadata, batch counts, and manifests. Pass that additive assessment through the existing case API; the frontend gives unresolved boundary review precedence over document/field validity and renders a reusable warning. This Stage 1 plan does not rewrite boundaries; the Stage 2 proposal/revision workflow remains separately gated by shadow accuracy evidence.

**Tech Stack:** Python 3.14, FastAPI, pytest, React 18, TypeScript, Vitest, Vite

**Spec:** `docs/superpowers/specs/2026-08-20-packet-boundary-safety-and-correction-design.md`

## Global Constraints

- Work only in `/Users/lap16603/Documents/New project/work/CTV_APReview-v1` on branch `ver1`.
- Preserve unrelated dirty/untracked work, including `.DS_Store` and `.superpowers/`; stage only files owned by each task.
- Do not persist response-only `boundaryAssessment` into `case.json` or packet review snapshots.
- Do not mutate packet ranges, source PDFs, manifests, roster files, or existing reviews in Stage 1.
- Do not log names, CCCDs, OCR text, document images, or other participant PII.
- An unresolved boundary assessment must force `Kết quả AI = Cần review`; it must never produce `Hợp lệ`.
- Boundary anomalies affect attention ordering but never increase `Cần gửi lại` counts or the resubmission report.
- Keep the approved Vietnamese copy exactly: `Nghi ngờ nhiều hồ sơ trong một gói` and `AI phát hiện ranh giới hoặc danh tính không nhất quán. Hãy kiểm tra và xác nhận ranh giới trước khi kết luận hồ sơ.`
- The current v1 UI has no prepared-package publication action. Do not create a parallel publisher; Stage 1 supplies the unresolved state that the existing/future publication owner must fail closed on.
- Use TDD for every production behavior: write the test, run it and observe the expected failure, then implement the minimum change.

---

### Task 1: Pure backend packet-boundary assessment

**Files:**
- Create: `server/boundary_assessment.py`
- Create: `server/boundary_assessment_test.py`

**Interfaces:**
- Consumes: packet dictionaries with `pages`, `n_pages`, and `flags`; optional manifest dictionaries; optional case summary with `found` and `roster_n`.
- Produces: `assess_packet_boundary(packet: dict, manifest: dict | None, case_summary: dict | None) -> dict` with camelCase JSON fields `status`, `suspectedMultiplePackets`, `reasons`, and `candidateStarts`.

- [ ] **Step 1: Write failing tests for strong and weak boundary evidence**

```python
from boundary_assessment import assess_packet_boundary


def _manifest(*relative_contract_starts: int) -> dict:
    return {
        "docs": [
            {
                "id": f"contract-{i}",
                "kind": "contract",
                "pages": [{"src": f"/local/pg{page}.png"}],
            }
            for i, page in enumerate(relative_contract_starts)
        ],
    }


def test_multiple_contract_starts_require_boundary_review():
    packet = {"pages": [116, 131], "n_pages": 16, "flags": ["length-out-of-range"]}
    result = assess_packet_boundary(packet, _manifest(5, 13), {"found": 36, "roster_n": 41})
    assert result == {
        "status": "review",
        "suspectedMultiplePackets": True,
        "reasons": ["length-out-of-range", "multiple-contract-starts", "batch-count-mismatch"],
        "candidateStarts": [121, 129],
    }


def test_normal_single_contract_packet_is_clear():
    packet = {"pages": [20, 27], "n_pages": 8, "flags": []}
    assert assess_packet_boundary(packet, _manifest(0), {"found": 4, "roster_n": 4}) == {
        "status": "clear",
        "suspectedMultiplePackets": False,
        "reasons": [],
        "candidateStarts": [20],
    }


def test_batch_count_mismatch_does_not_stamp_normal_packet():
    packet = {"pages": [20, 27], "n_pages": 8, "flags": []}
    result = assess_packet_boundary(packet, _manifest(0), {"found": 3, "roster_n": 4})
    assert result["status"] == "clear"
    assert "batch-count-mismatch" not in result["reasons"]
```

- [ ] **Step 2: Run the focused tests and verify RED**

Run: `PYTHONPATH=server python3 -m pytest -q server/boundary_assessment_test.py`

Expected: collection fails with `ModuleNotFoundError: No module named 'boundary_assessment'`.

- [ ] **Step 3: Implement stable assessment and safe manifest parsing**

```python
from __future__ import annotations

import os
import re


_BLOCKING_FLAGS = ("length-out-of-range", "near-threshold", "auto-merged")
_PAGE_FILE = re.compile(r"^pg(\d+)\.(?:png|jpe?g)$", re.IGNORECASE)


def _contract_starts(packet: dict, manifest: dict | None) -> list[int]:
    if not isinstance(manifest, dict):
        return []
    packet_start = int((packet.get("pages") or [0])[0])
    starts = []
    for doc in manifest.get("docs") or []:
        if not isinstance(doc, dict) or doc.get("kind") != "contract":
            continue
        pages = doc.get("pages") or []
        if not pages or not isinstance(pages[0], dict):
            continue
        match = _PAGE_FILE.match(os.path.basename(str(pages[0].get("src") or "")))
        if match:
            starts.append(packet_start + int(match.group(1)))
    return sorted(set(starts))


def assess_packet_boundary(
    packet: dict,
    manifest: dict | None,
    case_summary: dict | None,
) -> dict:
    flags = set(packet.get("flags") or [])
    reasons = [flag for flag in _BLOCKING_FLAGS if flag in flags]
    starts = _contract_starts(packet, manifest)
    suspected_multiple = len(starts) >= 2
    if suspected_multiple:
        reasons.append("multiple-contract-starts")
    summary = case_summary or {}
    roster_n = summary.get("roster_n")
    if reasons and roster_n is not None and summary.get("found") != roster_n:
        reasons.append("batch-count-mismatch")
    return {
        "status": "review" if reasons else "clear",
        "suspectedMultiplePackets": suspected_multiple,
        "reasons": reasons,
        "candidateStarts": starts,
    }
```

- [ ] **Step 4: Run the focused tests and verify GREEN**

Run: `PYTHONPATH=server python3 -m pytest -q server/boundary_assessment_test.py`

Expected: 3 tests pass.

- [ ] **Step 5: Add edge-case tests and keep them green**

Add tests proving malformed/non-object manifests yield no candidates, duplicate contract starts are deduplicated, `near-threshold` and `auto-merged` independently require review, and unknown flags do not create boundary review.

Run: `PYTHONPATH=server python3 -m pytest -q server/boundary_assessment_test.py`

Expected: all boundary-assessment tests pass.

- [ ] **Step 6: Commit Task 1 only**

```bash
git add server/boundary_assessment.py server/boundary_assessment_test.py
git commit -m "feat: derive packet boundary review evidence"
```

---

### Task 2: Expose response-only boundary assessment through the case API

**Files:**
- Modify: `server/app.py`
- Modify: `server/app_test.py`

**Interfaces:**
- Consumes: `assess_packet_boundary` from Task 1 and the case's existing `summary`.
- Produces: every packet returned by `GET /api/cases/{cid}` and `PUT /api/cases/{cid}/packets/{i}/review` contains `boundaryAssessment`; stored `case.json` remains unchanged.

- [ ] **Step 1: Extend the existing response-only metadata test**

In `test_case_and_review_responses_derive_field_count_without_persisting`, replace the ready case result before writing the manifest:

```python
stored = appmod.store.get(cid)
packet = {
    **stored["packets"][0],
    "pages": [8, 23],
    "n_pages": 16,
    "flags": ["length-out-of-range"],
}
appmod.store.set_result(cid, stored["summary"], [packet], stored.get("cccdWorkbook"))
```

Write two contract docs beginning at `pg5.png` and `pg13.png`, then assert:

```python
assert detail["packets"][0]["boundaryAssessment"] == {
    "status": "review",
    "suspectedMultiplePackets": True,
    "reasons": ["length-out-of-range", "multiple-contract-starts"],
    "candidateStarts": [13, 21],
}
assert "boundaryAssessment" not in appmod.store.get(cid)["packets"][0]
assert updated["packet"]["boundaryAssessment"] == detail["packets"][0]["boundaryAssessment"]
```

This keeps the shared `_fake_pipeline` unchanged for all other API tests while making the absolute candidate starts deterministic for this test.

- [ ] **Step 2: Run the API test and verify RED**

Run: `PYTHONPATH=server python3 -m pytest -q server/app_test.py::test_case_and_review_responses_derive_field_count_without_persisting`

Expected: failure because `boundaryAssessment` is absent.

- [ ] **Step 3: Refactor manifest loading once and add the assessment**

Replace the tuple-only `_packet_manifest_summary` with a helper that returns
the parsed manifest plus existing counts, then call:

```python
from boundary_assessment import assess_packet_boundary


def _packet_for_response(cid: str, packet: dict, case_summary: dict | None = None) -> dict:
    manifest = _packet_manifest(cid, packet["index"])
    fields = manifest.get("fields") if isinstance(manifest, dict) else None
    docs = manifest.get("docs") if isinstance(manifest, dict) else None
    tax_commitment_detected = isinstance(docs, list) and any(
        isinstance(doc, dict) and doc.get("kind") == "commitment" for doc in docs
    )
    return {
        **packet,
        "reviewFieldCount": len(fields) if isinstance(fields, list) else 0,
        "taxCommitmentDetected": tax_commitment_detected,
        "boundaryAssessment": assess_packet_boundary(packet, manifest, case_summary),
    }
```

Pass `case.get("summary")` from both detail and review responses. Do not write the derived field to `CaseStore`.

- [ ] **Step 4: Run backend API and pure assessment tests**

Run: `PYTHONPATH=server python3 -m pytest -q server/boundary_assessment_test.py server/app_test.py`

Expected: all selected tests pass; only the known Starlette/SWIG deprecation warnings may remain.

- [ ] **Step 5: Commit Task 2 only**

```bash
git add server/app.py server/app_test.py
git commit -m "feat: expose packet boundary assessments"
```

---

### Task 3: Make boundary uncertainty override frontend AI validity

**Files:**
- Modify: `src/upload/api.ts`
- Modify: `src/upload/api.test.ts`
- Modify: `src/logic/packetEvidenceSummary.ts`
- Modify: `src/logic/packetEvidenceSummary.test.ts`

**Interfaces:**
- Consumes: backend `boundaryAssessment` from Task 2.
- Produces: exported TypeScript types `BoundaryReason` and `PacketBoundaryAssessment`; `summarizePacketEvidence(folder, boundaryAssessment?)` gives unresolved boundary review precedence.

- [ ] **Step 1: Write failing summary precedence tests**

Add this case to `packetEvidenceSummary.test.ts` using the existing `folder` helper:

```ts
it('forces review when packet boundaries are unresolved', () => {
  const result = summarizePacketEvidence(folder([
    'id_front', 'id_back', 'contract', 'bbnt', 'appendix',
  ]), {
    status: 'review',
    suspectedMultiplePackets: true,
    reasons: ['multiple-contract-starts'],
    candidateStarts: [121, 129],
  })
  expect(result.aiResult).toBe('review')
})
```

Add a second test whose folder is otherwise mismatched and assert unresolved boundary review still returns `review`, proving boundary uncertainty has first precedence.

- [ ] **Step 2: Run the summary test and verify RED**

Run: `npm test -- src/logic/packetEvidenceSummary.test.ts`

Expected: TypeScript/test failure because `summarizePacketEvidence` accepts one argument and does not inspect boundary state.

- [ ] **Step 3: Add the additive frontend types and minimal precedence rule**

In `src/upload/api.ts` add:

```ts
export type BoundaryReason =
  | 'length-out-of-range'
  | 'near-threshold'
  | 'auto-merged'
  | 'multiple-contract-starts'
  | 'multiple-identities'
  | 'batch-count-mismatch'

export interface PacketBoundaryAssessment {
  status: 'clear' | 'review' | 'accepted'
  suspectedMultiplePackets: boolean
  reasons: BoundaryReason[]
  candidateStarts: number[]
}
```

Add `boundaryAssessment: PacketBoundaryAssessment` to `PacketMeta`. Normalize a missing legacy response to `{ status: 'clear', suspectedMultiplePackets: false, reasons: [], candidateStarts: [] }` without persisting it.

Change the summary signature and first precedence branch:

```ts
export function summarizePacketEvidence(
  folder: CtvFolder,
  boundaryAssessment?: PacketBoundaryAssessment,
): PacketEvidenceSummary {
  // existing document and verdict derivation
  const aiResult: PacketAiResult = boundaryAssessment?.status === 'review'
    ? 'review'
    : missing.length > 0 || verdicts.includes('mismatch')
      ? 'mismatch'
      : verdicts.some(verdict => verdict === 'review' || verdict === 'low_conf' || verdict === 'fuzzy')
        ? 'review'
        : 'match'
  // existing return
}
```

Pass `packet.boundaryAssessment` from `getCase` when building `dashboardSummary`.

- [ ] **Step 4: Add API normalization coverage**

Extend `getCase normalizes missing and present review field counts` to assert a missing assessment becomes the exact clear default. Extend the ready-packet summary test with a review assessment and expect `dashboardSummary.aiResult === 'review'`.

- [ ] **Step 5: Run focused frontend logic/API tests**

Run: `npm test -- src/logic/packetEvidenceSummary.test.ts src/upload/api.test.ts`

Expected: both test files pass.

- [ ] **Step 6: Commit Task 3 only**

```bash
git add src/upload/api.ts src/upload/api.test.ts src/logic/packetEvidenceSummary.ts src/logic/packetEvidenceSummary.test.ts
git commit -m "feat: block AI clearance on boundary uncertainty"
```

---

### Task 4: Surface the boundary warning in Tổng hợp and packet review

**Files:**
- Create: `src/components/PacketBoundaryWarning.tsx`
- Modify: `src/components/CaseDetail.tsx`
- Modify: `src/components/UploadFlow.tsx`
- Modify: `src/logic/packetDashboard.ts`
- Modify: `src/components/caseDetail.test.tsx`
- Modify: `src/components/reviewPresentation.test.tsx`
- Modify: `src/logic/packetDashboard.test.ts`
- Modify: `src/upload/api.test.ts`
- Modify: `src/styles.css`

**Interfaces:**
- Consumes: `PacketBoundaryAssessment` from Task 3.
- Produces: `PacketBoundaryWarning({ assessment })`; strong list reason `Nghi ngờ nhiều hồ sơ trong một gói`; persistent packet-review warning; unchanged `packetNeedsResubmit` behavior.

- [ ] **Step 1: Write failing list and warning-component tests**

In `caseDetail.test.tsx`, give a packet this assessment:

```ts
boundaryAssessment: {
  status: 'review',
  suspectedMultiplePackets: true,
  reasons: ['length-out-of-range', 'multiple-contract-starts'],
  candidateStarts: [121, 129],
},
```

Assert the row contains both `Cần review` and `Nghi ngờ nhiều hồ sơ trong một gói`.

Update the shared packet helpers in `caseDetail.test.tsx` and
`packetDashboard.test.ts` to supply the clear default assessment so their
`PacketMeta` fixtures remain complete:

```ts
boundaryAssessment: {
  status: 'clear',
  suspectedMultiplePackets: false,
  reasons: [],
  candidateStarts: [],
},
```

In `reviewPresentation.test.tsx`, render `PacketBoundaryWarning` with the same assessment and assert the exact title and explanatory copy from Global Constraints. Add a clear assessment case and assert the component renders no markup.

- [ ] **Step 2: Run component tests and verify RED**

Run: `npm test -- src/components/caseDetail.test.tsx src/components/reviewPresentation.test.tsx`

Expected: failures because the warning component and strong attention reason do not exist.

- [ ] **Step 3: Implement the reusable warning and list reason**

Create `PacketBoundaryWarning.tsx`:

```tsx
import type { PacketBoundaryAssessment } from '../upload/api'

export default function PacketBoundaryWarning({
  assessment,
}: {
  assessment: PacketBoundaryAssessment | undefined
}) {
  if (assessment?.status !== 'review') return null
  return (
    <div className="packet-boundary-warning" role="alert">
      <strong>Nghi ngờ nhiều hồ sơ trong một gói</strong>
      <span>AI phát hiện ranh giới hoặc danh tính không nhất quán. Hãy kiểm tra và xác nhận ranh giới trước khi kết luận hồ sơ.</span>
    </div>
  )
}
```

Update `attentionReasons` to accept `boundaryAssessment` and place the strong warning first when `status === 'review' && suspectedMultiplePackets`. Preserve the current specific flag reasons after it.

- [ ] **Step 4: Mount the warning below the review header**

In `UploadFlow`, use the existing `meta` packet and render:

```tsx
<PacketBoundaryWarning assessment={meta?.boundaryAssessment} />
```

between `ReviewHeader` and `FolderReview`. Do not replace or hide `MatchKeyStrip`; the warning explains why a CCCD match is insufficient.

- [ ] **Step 5: Prove attention and resubmission counts remain separate**

Add a `packetDashboard.test.ts` assertion that the affected packet is prioritized and contains the strong attention reason. Extend `packetNeedsResubmit: field flag or weak match` with a boundary-only packet and assert `false`.

- [ ] **Step 6: Add warning styling without changing the reviewer layout contract**

Add an amber, full-width `.packet-boundary-warning` directly below `.review-header`, with a strong title and readable secondary line. Keep the existing evidence panes and first-load positioning unchanged at desktop and narrow widths.

- [ ] **Step 7: Run all focused Stage 1 frontend tests**

Run: `npm test -- src/components/caseDetail.test.tsx src/components/reviewPresentation.test.tsx src/logic/packetDashboard.test.ts src/logic/packetEvidenceSummary.test.ts src/upload/api.test.ts`

Expected: all selected test files pass.

- [ ] **Step 8: Commit Task 4 only**

```bash
git add src/components/PacketBoundaryWarning.tsx src/components/CaseDetail.tsx src/components/UploadFlow.tsx src/logic/packetDashboard.ts src/components/caseDetail.test.tsx src/components/reviewPresentation.test.tsx src/logic/packetDashboard.test.ts src/upload/api.test.ts src/styles.css
git commit -m "feat: warn reviewers about mixed packet boundaries"
```

---

### Task 5: Full verification and affected-case live QA

**Files:**
- Modify only if a verification failure reveals a Stage 1 defect; any fix must begin with a failing regression test in the owning task's test file.

**Interfaces:**
- Consumes: completed Stage 1 implementation from Tasks 1–4.
- Produces: fresh automated and live evidence that unresolved boundary packets cannot appear valid and do not count as participant resubmissions.

- [ ] **Step 1: Run the complete backend suites relevant to packet creation and API responses**

Run: `PYTHONPATH=server python3 -m pytest -q server/boundary_assessment_test.py server/app_test.py splitter/detect_packets_test.py`

Expected: zero failures; known dependency deprecation warnings are recorded separately from failures.

- [ ] **Step 2: Run the complete frontend suite**

Run: `npm test`

Expected: all Vitest files and tests pass.

- [ ] **Step 3: Build the production frontend and check the diff**

Run: `npm run build`

Expected: TypeScript and Vite build exit 0.

Run: `git diff --check`

Expected: no whitespace errors.

- [ ] **Step 4: Verify the affected local case through the running app**

Open the affected case at `http://127.0.0.1:5174/` using its local case ID without exposing participant identity values in logs or the final report. Verify:

- the 16-page packet row shows `Cần review`;
- it shows `Nghi ngờ nhiều hồ sơ trong một gói`;
- opening it keeps `Khớp theo CCCD` visible but adds the persistent amber warning;
- the AI column contains no `Hợp lệ` for that packet;
- the case's `cần gửi lại` count is unchanged from participant evidence/rejection logic;
- no new browser console error appears.

- [ ] **Step 5: Inspect persistence and git scope**

Run: `git status --short` and inspect the affected case's stored `case.json` read-only.

Expected: `boundaryAssessment` is absent from `case.json`; `.DS_Store`, `.superpowers/`, and unrelated user changes remain untouched; only planned source/test files differ.

- [ ] **Step 6: Close any verification failure through the owning TDD task**

If Steps 1–5 expose a defect, stop this task and return to the task that owns the failing behavior: Task 1 for assessment logic, Task 2 for API derivation, Task 3 for AI precedence/types, or Task 4 for UI/attention semantics. Add a failing regression test in that task's named test file, implement the minimum fix, rerun Tasks 5 Steps 1–5, and commit only the owning source/test files with message `fix: close packet boundary safety regression`. If there is no defect, create no additional commit.

## Stage 1 completion gate

Stage 1 is complete only when all of the following are simultaneously true:

- backend derives boundary assessment without persistence;
- frontend AI validity gives unresolved boundary review first precedence;
- list and packet reviewer show the approved warning;
- `Cần gửi lại` and resubmission report semantics are unchanged;
- full tests and build pass;
- the affected local packet is visibly blocked from `Hợp lệ`.

After this gate, collect reviewer-confirmed boundary examples in shadow mode before writing the separate Stage 2 boundary-proposal/revision implementation plan.
