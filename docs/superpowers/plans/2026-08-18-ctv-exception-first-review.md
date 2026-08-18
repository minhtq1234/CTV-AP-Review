# CTV Exception-First Proposal Review Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the 540-item unit review with automatic deterministic organization, an exception-cluster queue, and one final approval while preserving exact unit coverage and the existing prepared-package contract.

**Architecture:** Capture bounded private matching facts during the existing local inspection pass without changing its public result. Build a deterministic roster and grouping projection over atomic units, expose only exception clusters and collapsed groups in the loopback review, then expand the approved groups back into the existing `ApprovedProposalSnapshot` consumed by the package writer and validator.

**Tech Stack:** Python 3.14, dataclasses, PyMuPDF, OpenPyXL, existing local OCR, `http.server`, static HTML/CSS/JavaScript, pytest, Node `vm` UI interaction tests, Vitest, Vite.

**Spec:** `docs/superpowers/specs/2026-08-18-ctv-exception-first-review-design.md`

## Global Constraints

- Source folders remain read-only; package output remains a separate explicitly selected directory.
- Public `inspect`, `proposal.review`, and `package.prepare` JSON envelopes retain their existing closed shapes.
- The v1 and v2 contract trees and both pin files remain byte-unchanged.
- No remote service, network dependency, new package dependency, or WP-bundled executable is introduced.
- Raw OCR text, cell values, participant values, source filenames, local paths, and tokens never enter public results, logs, default `repr`, or package validation diagnostics.
- Automatic organization is based on versioned deterministic checks, never an opaque confidence percentage alone.
- Every atomic unit is in exactly one included group, explicit exclusion, or unresolved exception until final approval.
- Final approval is impossible while any exception remains or source observation revalidation fails.
- Existing loopback Host, Origin, cookie, CSRF, content-type, request-size, route, timeout, and no-write controls remain in force.
- Preserve untracked `.DS_Store` and `.superpowers/`; stage only files owned by the current task.
- Each task uses strict RED/GREEN TDD, ends in a narrow local commit, and receives an independent review before the next task begins.

---

## File Structure

### New files

- `server/ctv_grouping_evidence.py` — bounded memory-only private text facts plus existing opaque exact-duplicate facts.
- `server/ctv_grouping_evidence_test.py` — privacy, bounds, lifecycle, and one-pass capture tests.
- `server/ctv_proposal_roster.py` — roster candidate parsing, scoring, automatic selection, and ambiguity facts.
- `server/ctv_proposal_roster_test.py` — generated roster candidate and privacy tests.
- `server/ctv_proposal_grouping.py` — immutable group/exception model, participant matching, grouping, eligibility, and exact coverage.
- `server/ctv_proposal_grouping_test.py` — generated grouping, exception, coverage, ordering, and bounds tests.
- `server/ctv_exception_review_acceptance_test.py` — generated end-to-end exception-first package acceptance.

### Existing files changed

- `server/ctv_inspection_media.py` — send already-bounded private text to an optional caller-owned sink before clearing it.
- `server/ctv_inspection.py` — bind the sink to evidence IDs and keep the public inspection result unchanged.
- `server/ctv_inspection_media_test.py` — prove one-pass capture and fixed failure behavior.
- `server/ctv_inspection_test.py` — prove public result and default inspect flows contain no private facts.
- `server/ctv_proposal.py` — own automatic roster/group state, exception resolutions, coverage, digest, approval, and exact expansion.
- `server/ctv_proposal_test.py` — proposal state, privacy, digest, undo, and approval tests.
- `server/ctv_package_assignment_test.py` — prove expanded automatic and user-resolved groups produce the unchanged v2 assignment contract.
- `server/ctv_proposal_review.py` — expose group/exception projections and strict exception actions over the existing loopback boundary.
- `server/ctv_proposal_review_test.py` — real HTTP boundary, lifecycle, preview, privacy, and terminal tests.
- `server/ctv_proposal_review_ui.py` — replace the flat unit UI with exception-first static assets.
- `server/ctv_proposal_review_ui_test.py` — static and executable UI interaction/accessibility tests.
- `server/ctv_intake_cli.py` — create and transfer the private grouping collector in proposal and package flows.
- `server/ctv_intake_cli_test.py` — CLI lazy-import, terminal-shape, failure, and privacy regressions.
- `server/ctv_package_acceptance_test.py` — preserve the existing complete package acceptance path with group expansion.
- `server/README.md` — document exception-first behavior and the bounded WP result.

---

### Task 1: Capture Bounded Private Grouping Facts in the Existing Inspection Pass

**Files:**
- Create: `server/ctv_grouping_evidence.py`
- Create: `server/ctv_grouping_evidence_test.py`
- Modify: `server/ctv_inspection_media.py:1115-1506`
- Modify: `server/ctv_inspection.py:136-248,263-349,402-445`
- Modify: `server/ctv_inspection_media_test.py`
- Modify: `server/ctv_inspection_test.py`

**Interfaces:**
- Produces: `GroupingEvidence.capture(evidence_id: str, unit_kind: str, unit_index: int, private_text: str) -> None`
- Produces: `GroupingEvidence.text_for(evidence_id: str, unit_kind: str, unit_index: int) -> str`
- Produces: `GroupingEvidence.complete_for(evidence_id: str, unit_kind: str, unit_index: int) -> bool`
- Produces: `GroupingEvidence.capture_source_duplicate(evidence_id: str, duplicate_group_id: str) -> None`
- Produces: `GroupingEvidence.duplicate_group_for(evidence_id: str) -> str | None`
- Produces: `GroupingEvidence.clear() -> None`
- Changes: `inspect_observation(..., _private_text_sink: Callable[[str, str, int, str], None] | None = None) -> InspectionResult`
- Preserves: `InspectionResult.to_dict()` and all public inspection CLI bytes.

- [ ] **Step 1: Write the collector RED tests**

Create generated tests that prove exact type validation, stable normalization, per-unit truncation, aggregate truncation, duplicate-key rejection, private-safe `repr`, and clearing:

```python
def test_grouping_evidence_is_bounded_private_and_clearable():
    facts = GroupingEvidence(max_units=2, max_chars_per_unit=64, max_total_chars=96)
    facts.capture("evidence-0001", "pdf-page", 1, "Nguyễn Văn A 079123456789")

    assert facts.text_for("evidence-0001", "pdf-page", 1) == "NGUYEN VAN A 079123456789"
    assert facts.complete_for("evidence-0001", "pdf-page", 1) is True
    assert "Nguyễn" not in repr(facts)
    assert "079123456789" not in repr(facts)

    facts.clear()
    assert facts.text_for("evidence-0001", "pdf-page", 1) == ""
    assert facts.complete_for("evidence-0001", "pdf-page", 1) is False
```

Add separate tests for a unit whose normalized text exceeds `max_chars_per_unit`, a third unit after `max_units=2`, aggregate exhaustion, `bool` indexes, non-`str` text, a second capture for the same key, and opaque duplicate-group capture. The defined outcome for any text cap crossing is no partial text: `text_for(...) == ""` and `complete_for(...) is False`. A unit-count crossing creates no entry and is also incomplete. Duplicate-group facts accept only existing `duplicate-NNNN` IDs and remain absent from `repr`.

- [ ] **Step 2: Run the collector tests to verify RED**

Run:

```bash
python3 -m pytest server/ctv_grouping_evidence_test.py -q
```

Expected: collection fails with `ModuleNotFoundError: No module named 'ctv_grouping_evidence'`.

- [ ] **Step 3: Implement the bounded collector**

Use exact built-in types, an immutable key, private non-repr storage, and NFKD/case/whitespace normalization:

```python
@dataclass(frozen=True)
class UnitTextKey:
    evidence_id: str
    unit_kind: str
    unit_index: int


class GroupingEvidence:
    def __init__(
        self,
        *,
        max_units: int = 10_000,
        max_chars_per_unit: int = 32 * 1024,
        max_total_chars: int = 16 * 1024 * 1024,
    ) -> None:
        self._limits = (max_units, max_chars_per_unit, max_total_chars)
        self._texts = {}
        self._complete_keys = set()
        self._duplicate_groups = {}
        self._used = 0
        self.complete = True

    def capture(self, evidence_id, unit_kind, unit_index, private_text) -> None:
        key = UnitTextKey(evidence_id, unit_kind, unit_index)
        normalized = _normalized_private_text(private_text)
        # Reject duplicate keys. Retain the complete normalized value or no
        # value; a truncated value must never qualify an automatic match.

    def text_for(self, evidence_id, unit_kind, unit_index) -> str:
        return self._texts.get(UnitTextKey(evidence_id, unit_kind, unit_index), "")

    def complete_for(self, evidence_id, unit_kind, unit_index) -> bool:
        return UnitTextKey(evidence_id, unit_kind, unit_index) in self._complete_keys

    def capture_source_duplicate(self, evidence_id, duplicate_group_id) -> None:
        # Retain only the existing opaque inventory duplicate ID.

    def duplicate_group_for(self, evidence_id) -> str | None:
        return self._duplicate_groups.get(evidence_id)

    def clear(self) -> None:
        self._texts.clear()
        self._complete_keys.clear()
        self._duplicate_groups.clear()
        self._used = 0
        self.complete = False
```

`_normalized_private_text` must remove combining marks, uppercase, and replace non-alphanumeric runs with one space. Bound checks happen before retention; do not return a partial prefix. Do not implement serialization or `to_dict`.

- [ ] **Step 4: Add one-pass capture RED tests to the media and inspection suites**

Generate a text PDF and OCR image with a private marker. Inject a recording sink and assert:

```python
inspection = inspect_observation(
    observation,
    _private_text_sink=facts.capture,
)
assert private_marker not in repr(inspection)
assert private_marker not in repr(inspection.to_dict())
assert "PRIVATE MARKER" in facts.text_for(evidence_id, "pdf-page", 1)
assert ocr_calls == 1
```

Also inject a sink that raises and assert the call fails without including the private marker or raw exception text. Existing inspection without a sink must remain byte-identical for a fixed generated fixture.

- [ ] **Step 5: Run the one-pass tests to verify RED**

Run:

```bash
python3 -m pytest server/ctv_inspection_media_test.py server/ctv_inspection_test.py -q -k 'private_text_sink or grouping_evidence or public_result_unchanged'
```

Expected: the sink keyword or expected capture call is absent.

- [ ] **Step 6: Wire the optional private sink before text is cleared**

Add a no-op default through `_ocr_evidence`, `_inspect_pdf_page`, `inspect_pdf`, `inspect_image`, `_inspect_observed_source`, and `_inspection_result`. Bind the source evidence ID only in `ctv_inspection.py`:

```python
def capture_unit_text(unit_kind: str, unit_index: int, private_text: str) -> None:
    if private_text_sink is not None:
        private_text_sink(source.evidence_id, unit_kind, unit_index, private_text)
```

Call it after text has passed existing byte bounds and before assigning `private_text = ""`. Do not capture workbook cell values; roster acquisition remains in the roster component. Translate sink failures to the existing internal inspection failure boundary without raw exception chaining.

- [ ] **Step 7: Run Task 1 GREEN and regression gates**

Run:

```bash
python3 -m pytest server/ctv_grouping_evidence_test.py server/ctv_inspection_media_test.py server/ctv_inspection_test.py -q
python3 -m py_compile server/ctv_grouping_evidence.py server/ctv_inspection_media.py server/ctv_inspection.py
git diff --check
```

Expected: all tests pass, compile exits `0`, and diff check is empty.

- [ ] **Step 8: Commit Task 1**

```bash
git add server/ctv_grouping_evidence.py server/ctv_grouping_evidence_test.py server/ctv_inspection_media.py server/ctv_inspection_media_test.py server/ctv_inspection.py server/ctv_inspection_test.py
git commit -m "feat(ctv): retain bounded local grouping facts"
```

---

### Task 2: Extract Roster Candidates and Select a Unique Strong Candidate Automatically

**Files:**
- Create: `server/ctv_proposal_roster.py`
- Create: `server/ctv_proposal_roster_test.py`
- Modify: `server/ctv_proposal.py:62-99,199-346`
- Modify: `server/ctv_proposal_test.py`

**Interfaces:**
- Consumes: `InspectionResult`, caller-owned `snapshot_source(evidence_id: str, *, max_bytes: int) -> bytes`
- Produces: `RosterCandidate`
- Produces: `load_roster_candidates(inspection: InspectionResult, snapshot_source: Callable) -> tuple[RosterCandidate, ...]`
- Produces: `choose_automatic_roster(candidates: tuple[RosterCandidate, ...]) -> RosterSelection`
- Preserves: existing `RosterRowSnapshot` values used by `ApprovedProposalSnapshot`.

- [ ] **Step 1: Write generated roster selection RED tests**

Cover these exact cases:

```python
def test_one_valid_roster_is_selected_without_user_action(tmp_path):
    inspection, snapshots = generated_inspection_with_rosters(tmp_path, valid=1)
    candidates = load_roster_candidates(inspection, snapshots)
    selection = choose_automatic_roster(candidates)

    assert selection.status == "selected"
    assert selection.roster_unit_id == candidates[0].unit_id
    assert selection.issue_codes == ()


def test_equal_valid_rosters_create_one_roster_exception(tmp_path):
    inspection, snapshots = generated_inspection_with_rosters(tmp_path, valid=2)
    selection = choose_automatic_roster(
        load_roster_candidates(inspection, snapshots)
    )

    assert selection.status == "ambiguous"
    assert selection.roster_unit_id is None
    assert selection.issue_codes == ("roster-ambiguous",)
```

Also test no candidate, malformed header, zero rows, duplicate identity, formula-only physical rows, FA-code completeness, stable numeric unit ordering, hard row/cell/workbook caps, snapshot failure, and absence of names/identities from `repr(selection)`.

- [ ] **Step 2: Run roster tests to verify RED**

Run:

```bash
python3 -m pytest server/ctv_proposal_roster_test.py -q
```

Expected: `ModuleNotFoundError: No module named 'ctv_proposal_roster'`.

- [ ] **Step 3: Move roster parsing behind the new immutable interface**

Define private-value fields with `repr=False`:

```python
@dataclass(frozen=True)
class RosterCandidateRow:
    row_index: int
    name: str = field(repr=False)
    identity: str = field(repr=False)
    values: tuple[tuple[str, str], ...] = field(repr=False)


@dataclass(frozen=True)
class RosterCandidate:
    unit_id: str
    evidence_id: str
    worksheet_index: int
    rows: tuple[RosterCandidateRow, ...] = field(repr=False)
    blocking_issue_codes: tuple[str, ...]
    package_issue_codes: tuple[str, ...]
    canonical_to_source_columns: tuple[tuple[str, str], ...] = field(repr=False)
    score: tuple[int, int, int]


@dataclass(frozen=True)
class RosterSelection:
    status: Literal["selected", "missing", "ambiguous", "invalid"]
    roster_unit_id: str | None
    candidate_unit_ids: tuple[str, ...]
    issue_codes: tuple[str, ...]
```

The score is exactly `(has_no_blocking_issues, has_complete_package_fields, usable_row_count)`. Select automatically only when the highest score is unique, has no blocking issues, has complete required package fields, and has at least one usable row. A tie at the highest eligible score is `roster-ambiguous`; no payment-roster worksheet is `roster-missing`; candidates with blocking issues or incomplete required package fields are ineligible, and an all-ineligible set is `roster-invalid`.

- [ ] **Step 4: Convert `ProposalState.select_roster` to use `RosterCandidate`**

Keep the existing explicit method for ambiguous-roster resolution, but make it select only from preloaded candidates. Remove workbook parsing from `ctv_proposal.py`; convert the chosen candidate rows into the existing `RosterRowSnapshot` and private local participant display.

- [ ] **Step 5: Run Task 2 GREEN and compatibility gates**

Run:

```bash
python3 -m pytest server/ctv_proposal_roster_test.py server/ctv_proposal_test.py server/ctv_package_assignment_test.py -q
python3 -m py_compile server/ctv_proposal_roster.py server/ctv_proposal.py
git diff --check
```

Expected: all tests pass; explicit roster selection still works; private values stay out of public results.

- [ ] **Step 6: Commit Task 2**

```bash
git add server/ctv_proposal_roster.py server/ctv_proposal_roster_test.py server/ctv_proposal.py server/ctv_proposal_test.py
git commit -m "feat(ctv): select authoritative roster automatically"
```

---

### Task 3: Build Deterministic Review Groups and Exception Clusters

**Files:**
- Create: `server/ctv_proposal_grouping.py`
- Create: `server/ctv_proposal_grouping_test.py`

**Interfaces:**
- Consumes: `InspectionResult`, selected `RosterCandidate`, and `GroupingEvidence`
- Produces: `build_grouping_plan(inspection, roster, evidence) -> GroupingPlan`
- Produces: immutable `ReviewGroup`, `ExceptionCluster`, `GroupTarget`, and `ExpandedDecision` records
- Guarantees: `GroupingPlan.covered_unit_ids` equals the inspection unit ID set exactly.

- [ ] **Step 1: Write the immutable model and coverage RED tests**

Write tests for exact dataclass field validation, stable ordering, unique IDs, duplicate unit rejection, missing unit rejection, unsupported roles/scopes, private-safe `repr`, and bounded group/exception counts:

```python
def test_plan_requires_exactly_once_unit_coverage():
    with pytest.raises(ValueError, match="group coverage must equal inspection units"):
        GroupingPlan(
            roster_unit_id="unit-0001",
            groups=(group(member_unit_ids=("unit-0001", "unit-0001")),),
            exceptions=(),
            source_exceptions=(),
            expected_unit_ids=("unit-0001",),
        )
```

- [ ] **Step 2: Run model tests to verify RED**

Run:

```bash
python3 -m pytest server/ctv_proposal_grouping_test.py -q -k 'model or coverage or bounds'
```

Expected: module collection failure.

- [ ] **Step 3: Implement the closed grouping records**

Use these exact state and target values:

```python
GroupState = Literal["automatically-organized", "exception", "user-resolved"]
Scope = Literal["individual", "shared", "case"]

@dataclass(frozen=True)
class GroupTarget:
    scope: Scope
    participant_handles: tuple[str, ...]

@dataclass(frozen=True)
class ReviewGroup:
    group_id: str
    evidence_id: str
    unit_kind: str
    member_unit_ids: tuple[str, ...]
    first_unit_index: int
    last_unit_index: int
    role: str
    target: GroupTarget
    state: GroupState
    check_codes: tuple[str, ...]
    issue_codes: tuple[str, ...]

@dataclass(frozen=True)
class ExceptionCluster:
    exception_id: str
    group_ids: tuple[str, ...]
    member_unit_ids: tuple[str, ...]
    issue_code: str
    recommended_action: str
    allowed_actions: tuple[str, ...]
    similarity_key: str
```

Group IDs and exception IDs are assigned from canonical numeric source/unit order as `group-0001` and `exception-0001`. Do not derive display labels or IDs from private values. `similarity_key` is derived only from fixed issue code, recommended action shape, allowed actions, role, and scope; it never contains normalized source text, participant display values, or source labels.

- [ ] **Step 4: Write participant matching and segmentation RED tests**

Generate private text facts and roster rows for:

- exact normalized full-name plus bounded identity-token match to one participant;
- name-only, identity-only, zero-match, and multiple-match exceptions;
- a participant anchor starting a segment that ends immediately before the next participant anchor;
- leading case-level contract pages;
- contiguous concrete role runs;
- unknown continuation pages bounded by compatible anchors;
- gaps between incompatible anchors becoming the smallest exception range;
- worksheet roster as one case-level payment-roster group;
- shared contracts/policies represented once at case scope;
- existing opaque inventory duplicate-group facts producing deterministic duplicate exclusion candidates without a second hash/read;
- unreadable/unsupported source-only exceptions;
- semantic similarity never creating an automatic exclusion.

Use exact expected group membership, not only counts:

```python
assert plan.groups[1].member_unit_ids == (
    "unit-0007", "unit-0008", "unit-0009"
)
assert plan.groups[1].target == GroupTarget(
    "individual", ("participant-0001",)
)
assert plan.exceptions[0].member_unit_ids == ("unit-0010",)
```

- [ ] **Step 5: Run grouping behavior tests to verify RED**

Run:

```bash
python3 -m pytest server/ctv_proposal_grouping_test.py -q -k 'matching or segment or shared or duplicate or source_exception'
```

Expected: `build_grouping_plan` is absent or returns no groups.

- [ ] **Step 6: Implement matching, segmentation, and eligibility**

Participant automatic assignment requires both an exact normalized full-name word sequence and an exact normalized identity token to resolve to the same roster row. One-sided or conflicting matches are exceptions.

For each source in numeric evidence order:

1. Mark any unit whose private fact is absent or incomplete as an exception; never match or propagate through partial text.
2. Mark roster, participant, concrete-role, and whole-case anchors.
3. Start participant segments at participant anchors and end before the next participant anchor.
4. Propagate a role through an unknown gap only when both bounding role anchors agree; for a single-anchor whole-source case document, allow trailing continuation to the source end when no participant anchor exists.
5. Split whenever target, role, unit kind, or source changes.
6. Apply deterministic eligibility checks to every resulting group.
7. Convert each failed group or source-only record into the smallest exception cluster.
8. For an opaque duplicate group, retain the first source in canonical evidence order and propose later exact duplicates as exclusions; never infer duplicates from text similarity.
9. Verify exactly-once unit coverage before returning.

Automatic group check codes are canonical and fixed:

```python
_AUTO_CHECK_ORDER = (
    "roster-selected",
    "participant-name-match",
    "participant-identity-match",
    "role-concrete",
    "role-scope-supported",
    "source-range-contiguous",
    "packet-structure-coherent",
    "target-unambiguous",
    "source-issues-clear",
    "unit-issues-clear",
    "coverage-exact",
)
```

Do not use `confidence_band` as a sufficient check. A concrete high-confidence role may contribute `role-concrete`, but participant, role/scope, packet structure, source issue, unit issue, target, and coverage checks remain mandatory. A single-anchor whole-source case group is eligible only when no unit contains a participant-identity conflict and all propagated units remain structurally compatible.

- [ ] **Step 7: Run Task 3 GREEN and determinism gates**

Run:

```bash
python3 -m pytest server/ctv_proposal_grouping_test.py -q
python3 -m py_compile server/ctv_proposal_grouping.py
git diff --check
```

Run the full grouping fixture twice and assert canonical `GroupingPlan.to_digest_input()` JSON bytes are equal.

- [ ] **Step 8: Commit Task 3**

```bash
git add server/ctv_proposal_grouping.py server/ctv_proposal_grouping_test.py
git commit -m "feat(ctv): group evidence into review exceptions"
```

---

### Task 4: Make Proposal State Exception-First and Expand Groups Exactly

**Files:**
- Modify: `server/ctv_proposal.py:146-592`
- Modify: `server/ctv_proposal_test.py`
- Modify: `server/ctv_package_assignment_test.py`

**Interfaces:**
- Consumes: `GroupingEvidence`, roster candidate interfaces, and `build_grouping_plan`
- Changes: `ProposalState.from_inspection(..., _grouping_evidence: GroupingEvidence | None = None)`
- Produces: `ProposalState.local_review_snapshot() -> dict`
- Produces: `ProposalState.resolve_exception(mapping: dict) -> None`
- Produces: `ProposalState.undo_exception(mapping: dict) -> None`
- Produces: `ProposalState.reopen_group(mapping: dict) -> None`
- Preserves: `ApprovedProposalSnapshot` and current public terminal result shapes.

- [ ] **Step 1: Write automatic initialization RED tests**

Construct a generated inspection, snapshots, and grouping evidence, then assert:

```python
state = ProposalState.from_inspection(
    observation,
    inspection,
    _grouping_evidence=facts,
)
local = state.local_review_snapshot()

assert set(local) == {"roster", "review", "summary"}
assert local["roster"]["status"] == "selected"
assert local["review"]["coverage"] == {
    "groups": 4,
    "automaticallyOrganizedUnits": 11,
    "exceptionClusters": 2,
    "exceptionUnits": 3,
    "unaccountedUnits": 0,
}
assert len(local["exceptions"]) == 2
assert state.approval_summary()["readyToPrepare"] is False
```

Add a no-exception case whose proposal is immediately ready for one final approval, while `local["summary"]["counts"]` and the existing public terminal `counts` still have exactly `sources`, `units`, `participants`, `accepted`, `reassigned`, `excluded`, and `unresolved`.

- [ ] **Step 2: Run initialization tests to verify RED**

Run:

```bash
python3 -m pytest server/ctv_proposal_test.py -q -k 'automatic_group or exception_cluster or local_review_snapshot'
```

Expected: `_grouping_evidence` or `local_review_snapshot` is unsupported.

- [ ] **Step 3: Integrate automatic roster and grouping initialization**

On construction with grouping evidence:

1. Load roster candidates once from retained snapshots.
2. Apply an eligible unique automatic selection.
3. Build the grouping plan.
4. Populate `_unit_decisions` for automatically organized groups.
5. Populate deterministic duplicate exclusions only.
6. Leave only exception member units/source records unresolved.

When no grouping evidence is supplied, retain the current explicit legacy flow for existing injected test drivers until Task 7 converts all production callers.

- [ ] **Step 4: Write exception action, batch, undo, and coverage RED tests**

Validate exact request shapes:

```python
state.resolve_exception({
    "exceptionId": "exception-0001",
    "action": "assign",
    "role": "acceptance-record",
    "target": {
        "scope": "individual",
        "participantHandles": ["participant-0001"],
    },
    "applyToSimilar": False,
})
```

Required action shapes:

- `accept-recommendation`: `exceptionId`, `action`, `applyToSimilar`;
- `assign`: plus `role`, exact `target`;
- `exclude`: plus fixed `reason`;
- `split`: plus `splitBeforeUnitId`;
- `merge-next`: exact base shape only;
- `choose-roster`: plus `rosterUnitId`;
- undo: only `exceptionId`;
- reopen: only `groupId`.

Prove batch application selects only unresolved clusters with the same `similarity_key` and identical allowed action. Prove an invalid member, cross-source merge, noncontiguous split, or stale exception ID leaves the prior digest and state unchanged.

- [ ] **Step 5: Run action tests to verify RED**

Run:

```bash
python3 -m pytest server/ctv_proposal_test.py -q -k 'resolve_exception or apply_to_similar or undo_exception or reopen_group or exact_coverage'
```

Expected: action methods are missing.

- [ ] **Step 6: Implement atomic exception transitions and exact expansion**

Build each transition on a candidate copy, validate it, then replace state only after coverage succeeds:

```python
candidate_resolutions = dict(self._exception_resolutions)
candidate_resolutions[exception_id] = resolution
expanded = self._grouping_plan.expand(candidate_resolutions)
_require_exact_unit_coverage(expanded, self._units_by_id)
self._exception_resolutions = candidate_resolutions
self._unit_decisions = _proposal_decisions(expanded)
self._invalidate_approved_package()
```

Include `groupReview` in `_digest_input()` with canonical group order, membership, checks, states, and user resolutions. Keep `_public_assignments()` limited to the existing `unitAssignments` and `sourceDispositions` projections.

`consume_approved_package_snapshot()` continues returning the existing immutable snapshot type after expanding every group. Automatically organized units use `accepted` when their role equals the inspection suggestion and `reassigned` only when a deterministic inherited role differs. User-resolved actions preserve their explicit decision semantics.

- [ ] **Step 7: Run Task 4 GREEN and package contract gates**

Run:

```bash
python3 -m pytest server/ctv_proposal_test.py server/ctv_package_assignment_test.py -q
python3 -m py_compile server/ctv_proposal.py
git diff --check
```

Assert the resulting `AssignmentsDocumentV2` still validates and its schema version, decision actor, locators, exclusions, and participant ordering remain unchanged.

- [ ] **Step 8: Commit Task 4**

```bash
git add server/ctv_proposal.py server/ctv_proposal_test.py server/ctv_package_assignment_test.py
git commit -m "feat(ctv): resolve proposal exceptions by group"
```

---

### Task 5: Expose a Strict Group and Exception Review API

**Files:**
- Modify: `server/ctv_proposal_review.py:145-197,273-687`
- Modify: `server/ctv_proposal_review_test.py`

**Interfaces:**
- Consumes: `ProposalState.local_review_snapshot`, `resolve_exception`, `undo_exception`, `reopen_group`
- Produces: authenticated `GET /api/state`
- Produces: authenticated POST routes `/api/exception`, `/api/exception/undo`, `/api/group/reopen`, plus existing summary/draft/cancel/approve/heartbeat routes
- Preserves: authenticated `GET /api/preview?unitId=<opaque-id>` for bounded page, image, and worksheet previews.

- [ ] **Step 1: Write real-loopback API RED tests**

After bootstrap, assert the state has this exact top-level shape:

```python
assert set(client_state) == {
    "csrfToken", "participants", "roster", "review", "summary"
}
assert set(client_state["review"]) == {
    "exceptions", "organizedGroups", "coverage", "issueCodes"
}
assert len(client_state["review"]["exceptions"]) == 2
assert len(client_state["review"]["organizedGroups"]) == 4
assert "unitDecisions" not in client_state["review"]
```

Post a valid exception resolution and assert only its cluster leaves the queue. Post undo and assert it returns. Reopen an automatic group and assert one exception appears without losing unit coverage. Keep preview queries unit-scoped and sourced only from group/exception member IDs.

- [ ] **Step 2: Write hostile request RED tests**

For every new route test duplicate JSON keys, extra/missing fields, wrong built-in types, spoofed equality values, unknown IDs, cross-cluster unit IDs, invalid roles/scopes/reasons, oversized bodies, wrong Host/Origin/cookie/CSRF/content type, query strings, and methods. Assert bounded fixed 4xx bodies and that the session remains usable after each rejection.

- [ ] **Step 3: Run API tests to verify RED**

Run with localhost permission:

```bash
python3 -m pytest server/ctv_proposal_review_test.py -q -k 'group_state or exception_route or exception_undo or group_reopen'
```

Expected: current state exposes `units` and `unitDecisions`; new routes return `404`.

- [ ] **Step 4: Replace the local unit projection and route dispatch**

Use the state-owned closed projection:

```python
def _client_state(self) -> dict:
    local = self.session.state.local_review_snapshot()
    return {
        "csrfToken": self.session.csrf_token,
        "participants": self.session.state.participants_for_local_review(),
        "roster": local["roster"],
        "review": local["review"],
        "summary": local["summary"],
    }
```

Map new POST routes directly to the exact state methods. Remove `/api/unit` and `/api/source` from `_POST_ROUTES`; they must return fixed `route-not-found`. Preserve draft/cancel/approve terminal behavior and source-change failure handling.

- [ ] **Step 5: Add group-aware preview authorization**

Before rendering a unit preview, require that the requested unit ID is present in the current organized-group or exception projection. Do not accept a source path, page number, or worksheet number from the browser. Continue resolving those values from trusted inspection state.

- [ ] **Step 6: Run Task 5 GREEN and complete HTTP boundary gates**

Run with localhost permission:

```bash
python3 -m pytest server/ctv_proposal_review_test.py -q
python3 -m pytest server/ctv_proposal_test.py server/ctv_proposal_review_test.py -q
python3 -m py_compile server/ctv_proposal_review.py
git diff --check
```

Expected: all tests pass and no raw private value appears in any HTTP error or terminal result.

- [ ] **Step 7: Commit Task 5**

```bash
git add server/ctv_proposal_review.py server/ctv_proposal_review_test.py
git commit -m "feat(ctv): expose exception-first review API"
```

---

### Task 6: Replace the Flat Unit UI with the Exception-First Screen

**Files:**
- Modify: `server/ctv_proposal_review_ui.py:1-573`
- Modify: `server/ctv_proposal_review_ui_test.py`

**Interfaces:**
- Consumes: Task 5 client state and POST routes
- Produces: static `UI_HTML`, `UI_CSS`, and `UI_JS` served by the existing loopback server
- Preserves: no inline scripts, no remote resources, existing CSP compatibility, and one preview fetch per user selection.

- [ ] **Step 1: Write static layout and copy RED tests**

Assert that the HTML contains the new landmarks and omits the old flat controls:

```python
assert 'id="exception-list"' in UI_HTML
assert 'id="organized-groups"' in UI_HTML
assert 'id="coverage-summary"' in UI_HTML
assert 'id="approve-button"' in UI_HTML
assert 'id="unit-list"' not in UI_HTML
assert "Current decisions" not in UI_HTML
```

In the executable render tests, assert the first heading becomes “Review exceptions” when exceptions exist and “Ready for approval” when none exist. Assert no opaque unit list is rendered on initial load.

- [ ] **Step 2: Write executable interaction RED tests**

Use the existing Node `vm` harness with a state containing 536 units represented by 25 groups and 3 exception clusters. Assert:

- only 3 exception cards and 25 collapsed group summaries are created;
- no 536-item DOM list is created;
- selecting an exception fetches one member preview;
- the recommended action posts the exact `/api/exception` payload;
- “Apply to all similar” is checked only when permitted;
- undo posts only the exception ID;
- reopening a group posts only the group ID;
- after zero exceptions, focus moves to the coverage summary and approval becomes enabled;
- batch-action scope is announced through `aria-live`;
- keyboard activation works for every action;
- object URLs are revoked after preview load/error and on terminal actions.

- [ ] **Step 3: Run UI tests to verify RED**

Run:

```bash
python3 -m pytest server/ctv_proposal_review_ui_test.py -q
```

Expected: new landmarks and interaction functions are absent.

- [ ] **Step 4: Implement the exception-first HTML and CSS**

Use this fixed reading order:

```html
<header class="topbar">case totals and terminal status</header>
<main>
  <section id="exception-workspace" aria-labelledby="exception-heading">
    <div id="exception-list"></div>
    <section id="exception-detail"></section>
  </section>
  <section id="organized-evidence" aria-labelledby="organized-heading">
    <div id="organized-groups"></div>
  </section>
  <aside id="coverage-and-approval">
    <dl id="coverage-summary"></dl>
    <button id="approve-button">Approve complete proposal</button>
  </aside>
</main>
```

Exception cards show the fixed issue explanation, source ordinal/range, recommended action, alternatives, and batch checkbox. Organized groups use native `<details>` so they are collapsed and keyboard accessible without custom state.

- [ ] **Step 5: Implement state rendering and actions**

Replace `units`, `unitDecisions`, and source navigation with:

```javascript
const localReview = {
  csrfToken: "",
  participants: [],
  roster: null,
  review: { exceptions: [], organizedGroups: [], coverage: {}, issueCodes: [] },
  summary: null,
  activeExceptionId: null,
  previewObjectUrl: null,
};
```

Render exception cards from `review.exceptions`, group summaries from `review.organizedGroups`, and totals from `review.coverage`. Use text nodes only for local values. Never set `innerHTML`. After a successful action, replace state from the server response and move focus to the next exception; when none remain, focus the coverage heading.

- [ ] **Step 6: Run Task 6 GREEN, CSP, and accessibility gates**

Run:

```bash
python3 -m pytest server/ctv_proposal_review_ui_test.py server/ctv_proposal_review_test.py -q
python3 -m py_compile server/ctv_proposal_review_ui.py
git diff --check
```

Inspect generated static text for remote URLs, inline event attributes, unsafe HTML sinks, missing labels, duplicate IDs, and color-only state. The existing review security-header test must still pass with the final CSP.

- [ ] **Step 7: Commit Task 6**

```bash
git add server/ctv_proposal_review_ui.py server/ctv_proposal_review_ui_test.py server/ctv_proposal_review_test.py
git commit -m "feat(ctv): render exception-first proposal review"
```

---

### Task 7: Wire Production CLI and Package Preparation to Grouping Evidence

**Files:**
- Modify: `server/ctv_intake_cli.py:560-590,930-990`
- Modify: `server/ctv_intake_cli_test.py`
- Modify: `server/ctv_package_acceptance_test.py`
- Modify: `server/README.md`

**Interfaces:**
- Consumes: `GroupingEvidence`, Task 1 inspection sink, and Task 4 `ProposalState`
- Preserves: current CLI argv, exit codes, canonical stdout envelopes, lazy imports, and prepared result projection.
- Preserves: current `prepare_package(observation, inspection, approved, output)` boundary.

- [ ] **Step 1: Write CLI production-wiring RED tests**

Inject a generated review driver and assert it receives a state whose automatic roster and grouping plan are already built:

```python
def review_driver(state):
    local = state.local_review_snapshot()
    assert local["roster"]["status"] == "selected"
    assert local["review"]["coverage"]["unaccountedUnits"] == 0
    assert local["review"]["coverage"]["automaticallyOrganizedUnits"] > 0
    return state.draft_result()
```

Poison a second OCR invocation and assert `package prepare` still reaches the driver, proving grouping facts came from the original inspection pass. Poison public inspection serialization with private markers and assert canonical stdout is unchanged.

- [ ] **Step 2: Write terminal and failure RED tests**

Cover:

- no-exception final approval and package publication;
- draft/cancel with grouping evidence cleared by normal scope exit;
- grouping collector cap exhaustion creating exceptions, not internal success;
- grouping construction failure returning a fixed controlled package/proposal failure;
- source mutation before close invalidating approval;
- malformed injected terminal results still rejected by existing strict normalization;
- package collision preserving the already-published package;
- lazy imports for unrelated CLI commands.

- [ ] **Step 3: Run CLI tests to verify RED**

Run:

```bash
python3 -m pytest server/ctv_intake_cli_test.py server/ctv_package_acceptance_test.py -q -k 'exception_first or grouping_evidence or automatic_roster or one_pass'
```

Expected: production callers create `ProposalState` without grouping evidence.

- [ ] **Step 4: Wire one collector through proposal and package flows**

Use one collector per retained observation:

```python
grouping_evidence = GroupingEvidence()
try:
    for item in observation.result.items:
        if item.duplicate_group_id is not None:
            grouping_evidence.capture_source_duplicate(
                item.evidence_id,
                item.duplicate_group_id,
            )
    inspection = inspect_observation(
        observation,
        _private_text_sink=grouping_evidence.capture,
    )
    state = ProposalState.from_inspection(
        observation,
        inspection,
        _grouping_evidence=grouping_evidence,
    )
    terminal = review_driver(state)
finally:
    grouping_evidence.clear()
```

Do this in both `proposal_review_source` and `_package_result`, with the real review/package continuation occurring inside the `try` so roster recomputation can still use the private facts. Clear the collector on every approved, draft, cancelled, and failed exit. Reuse only the inventory result's already-computed opaque `duplicate_group_id`; do not re-open or re-hash a source. Do not import grouping modules in `version`, `doctor`, contract, inventory, or inspect-only paths. Do not add grouping facts to stdout or the prepared package.

- [ ] **Step 5: Preserve package assignment and validation behavior**

Run the real generated package path and assert the approved expanded snapshot reaches `prepare_package` with exact unit coverage. No changes to the contract tree, writer interface, validation report, receipt, or publication transaction are allowed in this task.

- [ ] **Step 6: Update the local/WP documentation**

Document:

- automatic roster selection in normal cases;
- deterministic automatic organization;
- exception-only user actions;
- final whole-proposal approval;
- local-only private matching facts;
- unchanged bounded WP output;
- draft/cancel writes nothing;
- source changes invalidate the proposal.

Remove any wording that says the user reviews each unit.

- [ ] **Step 7: Run Task 7 GREEN and compatibility gates**

Run:

```bash
python3 -m pytest server/ctv_intake_cli_test.py server/ctv_package_acceptance_test.py server/ctv_package_assignment_test.py -q
python3 -m py_compile server/ctv_intake_cli.py
git diff --check
```

Verify both public contracts:

```bash
python3 server/ctv_intake_cli.py contract verify --json
python3 server/ctv_intake_cli.py contract verify --target ctv-intake-v2 --json
```

Expected: both return `verified: true` with their existing hashes.

- [ ] **Step 8: Commit Task 7**

```bash
git add server/ctv_intake_cli.py server/ctv_intake_cli_test.py server/ctv_package_acceptance_test.py server/README.md
git commit -m "feat(ctv): prepare packages from grouped review"
```

---

### Task 8: Prove the Complete Exception-First Workflow and Pilot Readiness

**Files:**
- Create: `server/ctv_exception_review_acceptance_test.py`
- Modify: `server/ctv_proposal_acceptance_test.py`
- Modify: `server/ctv_package_acceptance_test.py`
- Modify: `server/README.md`

**Interfaces:**
- Exercises: real CLI → retained observation → one-pass inspection facts → automatic roster/grouping → authenticated review HTTP → exception resolution → approval → writer → standalone validator.
- Produces: release evidence only; no new production interface.

- [ ] **Step 1: Write the full generated acceptance RED test**

Generate a source folder containing:

- one uniquely valid two-participant roster;
- one multi-page participant PDF with two deterministic participant anchors;
- one shared contract PDF;
- one exact duplicate;
- one ambiguous page cluster;
- one unsupported source.

The authenticated HTTP driver must assert:

```python
assert state["review"]["coverage"]["units"] == generated_unit_count
assert state["review"]["coverage"]["unaccountedUnits"] == 0
assert len(state["review"]["exceptions"]) == 2
assert len(state["review"]["organizedGroups"]) < generated_unit_count
assert "unitDecisions" not in state["review"]
```

Resolve the two exception clusters, approve the digest, validate the published package independently, recompute its tree digest, and retry to prove deterministic collision. Assert the source tree is byte- and metadata-unchanged.

- [ ] **Step 2: Run acceptance to verify RED**

Run with localhost permission:

```bash
python3 -m pytest server/ctv_exception_review_acceptance_test.py -q
```

Expected: collection failure before the file exists or the existing UI/API exposes units instead of exception clusters.

- [ ] **Step 3: Complete only integration fixes revealed by the acceptance test**

Keep fixes in the owning module and add a focused regression before each production edit. Do not change contract files, pins, source mutation boundaries, output layout, or publication semantics. The acceptance test must use real generated PDFs/workbooks/images and the real local HTTP server; do not replace grouping, writer, or validator with mocks.

- [ ] **Step 4: Run the complete affected suite**

Run with localhost permission where required:

```bash
python3 -m pytest \
  server/ctv_grouping_evidence_test.py \
  server/ctv_inspection_media_test.py \
  server/ctv_inspection_test.py \
  server/ctv_proposal_roster_test.py \
  server/ctv_proposal_grouping_test.py \
  server/ctv_proposal_test.py \
  server/ctv_proposal_review_test.py \
  server/ctv_proposal_review_ui_test.py \
  server/ctv_package_assignment_test.py \
  server/ctv_package_acceptance_test.py \
  server/ctv_exception_review_acceptance_test.py \
  server/ctv_intake_cli_test.py -q
```

Expected: all affected tests pass with only the repository's existing deprecation warnings.

- [ ] **Step 5: Run full repository verification**

Run:

```bash
python3 -m pytest -q
npm test
npm run build
python3 -m py_compile server/*.py
git diff --check
python3 server/ctv_intake_cli.py contract verify --json
python3 server/ctv_intake_cli.py contract verify --target ctv-intake-v2 --json
```

If the sandbox denies the six known loopback tests, rerun only those tests with localhost permission and report the split counts explicitly. Any non-loopback failure is a product failure and must be corrected before completion.

- [ ] **Step 6: Run privacy and frozen-contract checks**

Scan added lines and terminal artifacts for absolute paths, source filenames, tokens, raw OCR/cell values, participant names, identities, and real-looking account numbers. Export and byte-compare both frozen contract trees and pin files using the existing exporter tests. Expected: zero privacy hits and zero frozen-tree diff.

- [ ] **Step 7: Run the real-folder pilot without approving for the user**

Use the selected real source and a new empty output directory. Record only privacy-safe counts:

- source count;
- atomic unit count;
- organized group count;
- automatically organized unit count;
- exception cluster count;
- exception unit count;
- unaccounted unit count;
- time to first review screen.

Acceptance requirements:

- the screen does not render a flat 536-unit list;
- user actions equal exception clusters plus final approval, with at most one extra roster action;
- `unaccountedUnits` is `0`;
- no package exists before user approval;
- the user, not the agent, performs final approval;
- standalone validator returns `valid` after approval;
- published tree digest equals the CLI result.

- [ ] **Step 8: Commit Task 8**

```bash
git add server/ctv_exception_review_acceptance_test.py server/ctv_proposal_acceptance_test.py server/ctv_package_acceptance_test.py server/README.md
git commit -m "test(ctv): accept exception-first package review"
```

---

## Final Review Gate

After Task 8, request an independent exact-HEAD review covering:

- deterministic automatic eligibility and participant matching;
- exactly-once unit coverage and smallest-range exceptions;
- roster ambiguity and recomputation;
- batch-action isolation and undo;
- proposal digest coverage and source mutation invalidation;
- privacy of captured grouping text and local participant display;
- HTTP authorization and bounded hostile requests;
- UI action count, keyboard behavior, and absence of the flat unit list;
- exact assignment expansion, package validation, atomic publication, and unchanged v1/v2 pins.

Any Critical or Important finding requires a focused RED/GREEN correction and exact-head re-review before WP pilot handoff.
