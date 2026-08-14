# CTV Transactional Prepared-Package Writer Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn one fully resolved, locally approved CTV proposal into one deterministic, validated `ctv-intake-v2` package published atomically beneath an explicit local output parent.

**Architecture:** Preserve v1 and add a separate v2 contract/model/validator path. The existing proposal state exposes one private approved snapshot; a pure builder turns that snapshot plus retained source bytes into deterministic artifact recipes; a capability-owned transaction writes, validates, revalidates, and atomically publishes the package. The existing CLI composes inspection, local review, preparation, and one bounded WP-facing result.

**Tech Stack:** Python 3.14 standard library, Pydantic, PyMuPDF, Pillow, OpenPyXL, pytest, existing HTML/CSS/vanilla-JS local review, React/Vitest regression suite, Darwin `renameatx_np` with `RENAME_EXCL` reached through `ctypes` with no new dependency.

**Spec:** `docs/superpowers/specs/2026-08-14-ctv-prepared-package-writer-design.md`

## Global Constraints

- Exact command: `package prepare --source-root SOURCE --output-root OUTPUT_PARENT --json`; CLI operation `package.prepare`; CLI envelope version remains `1.0`.
- Exact v2 preflight: `contract verify --target ctv-intake-v2 --json`; existing `contract verify --json` remains byte-compatible v1 behavior.
- Preserve every checked-in byte below `contracts/ctv-intake/v1/`; v1 model, fixture, exporter, validator, report writer, CLI, and pin tests remain green.
- V2 lives below `contracts/ctv-intake/v2/`; pin metadata is `contracts/ctv-intake/PIN.v2.json`; compatibility target is exactly `ctv-intake-v2`.
- Writer output is fully resolved `prepared` only. Draft, cancel, unresolved, missing/conflicting FA code, build failure, or validation failure publishes nothing.
- Source is read-only. Build only from one retained content-bound `InventoryObservation`; never independently reopen a source pathname.
- Output parent must already exist, be separate/non-overlapping with the source, and support descriptor-relative no-follow operations plus atomic no-replace publication.
- Final directory suffix is the first 24 lowercase hex characters of the full domain-separated package digest. Never overwrite, merge, reuse, or recursively clean an existing final directory.
- Required published files: `case-manifest.json`, `input.pdf`, `roster.xlsx`, `assignments.json`, `exceptions.json`, and undeclared `validation-report.json`; only opaque `evidence/evidence-NNNN.(png|xlsx)` members may be additional files.
- At least one included PDF page. Every included page appears exactly once; shared pages are referenced, not duplicated.
- Selected roster must have recognized name, identity, and one unambiguous non-empty FA-code column/value. Ignore only wholly blank rows; any nonblank invalid row blocks approval.
- Package JSON/manifest/declared artifacts are deterministic for one writer/dependency version and approved input. Only the undeclared validation receipt may contain validation time.
- Hard ceilings: 10,000 units, 25,000 package PDF pages, 256 MiB input PDF, 25 MiB roster/evidence artifact, 16 MiB each JSON document, 1,000 evidence artifacts, and 1 GiB complete package.
- WP receives no source/output absolute paths, original filenames, FA code, participant values, roster cells, preview/OCR text, raw parser errors, tokens, ports, timestamps, or staging names.
- Same-interpreter reflection and a malicious same-OS-user write after the final staging/source linearization points are outside the approved lean threat boundary. No tests may expand the milestone to an impossible OS-immutable snapshot guarantee.
- Generated synthetic data only. Each task uses RED/GREEN TDD, one narrow implementation commit, one independent review, and at most one focused correction wave before the task returns to the plan owner.
- No new dependency, WP bundle, database, persistence, archive extraction, direct CTV/ACC submission, push, release, merge, or worktree cleanup without a later explicit user choice.

## File and Responsibility Map

- `server/intake_contract_v2.py`: closed Pydantic v2 document models and local invariants; no v1 imports are mutated.
- `server/export_intake_contract.py`: default-v1, explicit-target deterministic contract exporter.
- `server/intake_fixture_factory_v2.py`: generated synthetic v2 package materialization built through production serializers.
- `server/ctv_package_assignment.py`: trusted approved-proposal snapshot conversion and canonical assignment mapping.
- `server/ctv_package_builder.py`: pure identity, ordering, transformation, artifact-recipe, and manifest generation.
- `server/intake_package_validator_v2.py`: v2 content/publication validation against caller-owned readers and observations.
- `server/ctv_package_transaction.py`: output-parent/staging capabilities, atomic file writes, tree digest, cleanup, and Darwin no-replace publish.
- `server/ctv_package_writer.py`: orchestration from approved snapshot through builder, validator, receipt, source finalization, and publication.
- Existing proposal/inventory modules: expose only the private approved snapshot and final-publication source boundary required by the writer.
- Existing pin/validator/CLI modules: version dispatch and public compatibility; v1 default behavior is unchanged.

---

### Task 1: Freeze the CTV Intake V2 Contract

**Files:**
- Create: `server/intake_contract_v2.py`
- Create: `server/intake_contract_v2_test.py`
- Modify: `server/export_intake_contract.py`
- Modify: `server/export_intake_contract_test.py`
- Create: `contracts/ctv-intake/v2/package.schema.json`
- Create: `contracts/ctv-intake/v2/assignments.schema.json`
- Create: `contracts/ctv-intake/v2/canonical-roster.schema.json`
- Create: `contracts/ctv-intake/v2/exceptions.schema.json`
- Create: `contracts/ctv-intake/v2/validation-report.schema.json`
- Create: `contracts/ctv-intake/v2/exception-codes.json`
- Create: `contracts/ctv-intake/v2/compatibility.md`
- Create: `contracts/ctv-intake/v2/fixtures/README.md`
- Create: `contracts/ctv-intake/v2/fixtures/schema-example/case-manifest.json`
- Create: `contracts/ctv-intake/v2/fixtures/schema-example/assignments.json`
- Create: `contracts/ctv-intake/v2/fixtures/schema-example/exceptions.json`
- Create: `contracts/ctv-intake/v2/fixtures/schema-example/validation-report.json`
- Create: `contracts/ctv-intake/v2/fixtures/invalid-assignment/case-manifest.json`
- Create: `contracts/ctv-intake/v2/fixtures/invalid-assignment/assignments.json`
- Create: `contracts/ctv-intake/v2/fixtures/invalid-assignment/exceptions.json`

**Interfaces:**
- Consumes: Pydantic patterns from `server/intake_contract.py`; v1 exception meanings; the approved v2 design.
- Produces: `PackageManifestV2`, `AssignmentsDocumentV2`, `ExceptionsDocumentV2`, `ValidationReportV2`, `CanonicalRosterDocumentV2`, `ArtifactV2`, `VerifiedSourceV2`, `UnacquiredSourceV2`, typed output locators, and `export_contract_artifacts(output_root, compatibility_target="ctv-intake-v1")` with unchanged default v1 output.

- [ ] **Step 1: Write strict model RED tests**

Create tests that instantiate one complete model and independently reject extra
keys, bool-as-int, malformed IDs/digests, wrong versions, duplicate IDs, duplicate
single-instance artifacts, more than 1,000 evidence artifacts, unsafe paths,
unacquired sources with bytes/artifact provenance, included units without locators,
excluded records without manifest decisions, participant/roster mismatch, and a
valid report with no completed content checks.

Representative test:

```python
def test_v2_manifest_requires_assignments_and_allows_repeatable_evidence():
    manifest = complete_manifest_v2()
    assert [artifact.kind for artifact in manifest.artifacts].count("assignments") == 1
    assert [artifact.kind for artifact in manifest.artifacts].count("evidence") == 2

    duplicate = manifest.model_copy(
        update={"artifacts": manifest.artifacts + [manifest.artifacts[2]]}
    )
    with pytest.raises(ValueError, match="single-instance artifact"):
        PackageManifestV2.model_validate(duplicate.model_dump(by_alias=True))
```

- [ ] **Step 2: Capture the exact model RED**

Run:

```bash
python3 -m pytest server/intake_contract_v2_test.py -q
```

Expected: collection fails with `ModuleNotFoundError: No module named 'intake_contract_v2'`.

- [ ] **Step 3: Implement closed v2 models**

Use discriminated source binding and typed locators rather than optional-field
combinations:

```python
class VerifiedSourceV2(_ContractModel):
    binding_status: Literal["verified-content"] = Field(alias="bindingStatus")
    source_id: OpaqueSourceId = Field(alias="sourceId")
    path: SafeRelativePath
    media_type: str = Field(alias="mediaType", min_length=1, max_length=128)
    size: int = Field(ge=0)
    sha256: Sha256
    page_count: int | None = Field(alias="pageCount", default=None, ge=1)
    coverage_state: ResolvedCoverage = Field(alias="coverageState")
    decision_id: OpaqueDecisionId | None = Field(alias="decisionId", default=None)

class UnacquiredSourceV2(_ContractModel):
    binding_status: Literal["unacquired-exclusion"] = Field(alias="bindingStatus")
    source_id: OpaqueSourceId = Field(alias="sourceId")
    path: SafeRelativePath | None = None
    acquisition_status: AcquisitionStatus = Field(alias="acquisitionStatus")
    issue_codes: list[FixedInspectionIssue] = Field(alias="issueCodes")
    coverage_state: Literal["duplicate", "excluded-by-user"] = Field(alias="coverageState")
    decision_id: OpaqueDecisionId = Field(alias="decisionId")
```

Define `PdfPageLocatorV2`, `RosterLocatorV2`, `ImageLocatorV2`, and
`WorksheetLocatorV2` as a `kind`-discriminated union. Manifest decisions are
exactly `accept-unit`, `reassign-unit`, `exclude-unit`, `exclude-source`,
`select-roster`, and `approve-proposal`; they contain no timestamp. Every document
uses `schemaVersion: "2.0"`; every artifact uses `formatVersion: "2.0"`.

- [ ] **Step 4: Write explicit-target exporter RED tests**

Require exact generated filenames, byte-for-byte repeatability across two fresh
directories, no writes outside the selected target, JSON canonical ordering, v1
tree byte preservation, checked-in schema-example document validity, and
invalid-assignment fixture failure for only its named cross-reference reason.
Calling `export_contract_artifacts(output)` must still produce only the exact v1
files; v2 requires the explicit compatibility target.

- [ ] **Step 5: Capture exporter RED**

Run:

```bash
python3 -m pytest \
  server/intake_contract_v2_test.py \
  server/export_intake_contract_test.py -q
```

Expected: v2 model import fails and the exporter rejects the new target argument.

- [ ] **Step 6: Implement deterministic target dispatch and fixture documents**

Keep the existing v1 registries/default path intact and add separate v2 registries.
`export_contract_artifacts(output_root, compatibility_target="ctv-intake-v2")`
serializes the v2 schemas, compatibility text, codes, and synthetic fixture JSON
with sorted keys, two-space indentation, UTF-8, and one LF. Contract fixtures use
only clearly synthetic values such as `Synthetic Person 0001` and
`FA-SYNTHETIC-001`. `fixtures/README.md` states that `schema-example` demonstrates
closed document shapes only and is not a materialized package; semantic complete
packages come from the production-backed Task 5 fixture factory. The exporter
must regenerate all checked-in v2 files exactly and must never touch v1.

- [ ] **Step 7: Run Task 1 gates**

```bash
python3 -m pytest \
  server/intake_contract_v2_test.py \
  server/intake_contract_test.py \
  server/export_intake_contract_test.py \
  server/intake_fixture_factory_test.py -q
python3 -m py_compile \
  server/intake_contract_v2.py \
  server/export_intake_contract.py
git diff --check
```

Export to two fresh temporary directories and compare all v2 files byte-for-byte.
Also compute and record the pre/post SHA-256 tree digest of
`contracts/ctv-intake/v1/`; the two values must be identical.

- [ ] **Step 8: Commit and independently review the frozen tree**

Stage only Task 1 files and commit:

```bash
git commit -m "feat(ctv): define intake contract v2"
```

The reviewer checks closed schemas, cross-document invariants, safe bounds,
synthetic fixtures, deterministic export, and exact v1 preservation. Any later
contract correction must return to this task and force Task 2 to regenerate the
v2 pin; downstream code must not reinterpret a frozen schema locally.

---

### Task 2: Add the Versioned V2 Contract Pin

**Files:**
- Create: `server/export_contract_pin.py`
- Create: `server/export_contract_pin_test.py`
- Create: `contracts/ctv-intake/PIN.v2.json`
- Modify: `server/ctv_contract_pin.py`
- Modify: `server/ctv_contract_pin_test.py`
- Modify: `contracts/ctv-intake/README.md`

**Interfaces:**
- Consumes: the exact reviewed Task 1 commit and its `contracts/ctv-intake/v2/` Git tree.
- Produces: `load_contract_pin(repository_root, target="ctv-intake-v1")`, unchanged positional `compute_contract_tree_sha256(version_root)` accepting correctly located `v1` or `v2`, `verify_contract(repository_root, target="ctv-intake-v1")`, and `export_pin_from_commit(repository_root, source_commit, target) -> bytes`.

- [ ] **Step 1: Write RED version-selection tests**

Test unchanged no-argument v1 calls, explicit v1 calls, explicit v2 calls,
`PIN.v2.json` selection, exact target/version-root mapping, invalid target, mismatched
pin target, symlink/FIFO/extra-key/oversized pin, working-tree mutation exclusion
from exact-commit export, and a v2 tree change causing verification mismatch.

```python
def test_default_pin_stays_v1_and_explicit_v2_uses_pin_v2(repository_copy):
    assert load_contract_pin(repository_copy).compatibility_target == "ctv-intake-v1"
    assert load_contract_pin(
        repository_copy, target="ctv-intake-v2"
    ).compatibility_target == "ctv-intake-v2"
```

- [ ] **Step 2: Capture exact RED**

```bash
python3 -m pytest \
  server/ctv_contract_pin_test.py \
  server/export_contract_pin_test.py -q
```

Expected: new target argument and exporter are absent.

- [ ] **Step 3: Implement fixed target routing**

Use one closed mapping:

```python
_CONTRACT_TARGETS = {
    "ctv-intake-v1": ("v1", "PIN.json"),
    "ctv-intake-v2": ("v2", "PIN.v2.json"),
}
```

All opens remain descriptor-relative/no-follow. The exact-commit exporter uses
`git rev-parse`, `git ls-tree`, and `git show` with argv arrays, rejects anything
except a full lowercase 40-character commit, hashes regular blob entries only,
and emits exactly the three pin fields as canonical JSON.

- [ ] **Step 4: Generate the literal v2 pin from the reviewed commit**

Before editing the pin, capture the exact Task 1 commit:

```bash
source_commit=$(git rev-parse HEAD)
python3 server/export_contract_pin.py \
  --source-commit "$source_commit" \
  --target ctv-intake-v2 \
  --repository-root . \
  > /tmp/ctv-intake-PIN.v2.json
```

Read the generated three-field file, add those literal values to
`contracts/ctv-intake/PIN.v2.json` with `apply_patch`, then require
`verify_contract(REPOSITORY_ROOT, target="ctv-intake-v2").verified is True`.

- [ ] **Step 5: Update handoff documentation**

Document both immutable snapshots, exact command selection, distinct pin files,
v1 default preservation, v2 copy path, and the rule that WP must pin the exact v2
commit/tree rather than editing its v1 snapshot.

- [ ] **Step 6: Run Task 2 gates**

```bash
python3 -m pytest \
  server/ctv_contract_pin_test.py \
  server/export_contract_pin_test.py \
  server/ctv_intake_cli_test.py -q
python3 -m py_compile server/ctv_contract_pin.py server/export_contract_pin.py
git diff --check
```

Run both v1 and v2 verification from the repository root. Both must be verified;
the v1 result bytes for the legacy invocation must match the pre-task golden test.

- [ ] **Step 7: Commit and review**

```bash
git commit -m "docs(ctv): pin intake contract v2"
```

The reviewer compares `PIN.v2.json` to the exact Task 1 commit blobs, reruns the
portable tree hash, and confirms the no-argument v1 API/CLI behavior is unchanged.

---

### Task 3: Freeze One Approved Preparation Snapshot

**Files:**
- Create: `server/ctv_package_assignment.py`
- Create: `server/ctv_package_assignment_test.py`
- Modify: `server/ctv_proposal.py`
- Modify: `server/ctv_proposal_test.py`
- Modify: `server/ctv_inspection_classifier.py`
- Modify: `server/ctv_inspection_classifier_test.py`

**Interfaces:**
- Consumes: live `ProposalState`, selected roster snapshot, terminal local approval, `InspectionResult`, and v2 assignment models.
- Produces: immutable private `ApprovedProposalSnapshot`, `RosterRowSnapshot`, `UnitDecisionSnapshot`, `SourceDispositionSnapshot`; one-time `ProposalState.consume_approved_package_snapshot(expected_digest) -> ApprovedProposalSnapshot`; `build_assignments(snapshot, *, package_id, locators) -> AssignmentBuildResult`.

- [ ] **Step 1: Write roster/approval RED tests**

Use generated workbooks to cover exact recognized canonical columns (`name`,
`identity`, `faCode`, `taxId`, `birthDate`, `bankAccount`, `serviceFee`, `product`),
duplicate recognized headers, missing/conflicting/blank FA codes, wholly blank rows,
partially populated nonblank rows, duplicate identities, formulas without cached
values, roster switching, digest mutation, package snapshot before approval, stale
expected digest, and a second snapshot request after state mutation.

```python
approved_public = state.approve(state.approval_summary()["proposalDigest"])
snapshot = state.consume_approved_package_snapshot(approved_public["proposalDigest"])
assert snapshot.fa_code == "FA-SYNTHETIC-001"
assert snapshot.roster_rows[0].participant_handle == "participant-0001"
assert "Synthetic Person" not in repr(snapshot)
```

Require every public result, default `repr`, digest input, stderr-safe exception,
and local-review HTTP projection to exclude the actual FA code and roster values.
Also require package-specific consumption to reject an excluded selected roster,
a roster not assigned as case-scope `payment-roster`, no included PDF page, a
second consumption, and any state mutation after approval. Legacy proposal-review
readiness/outcomes remain unchanged.

- [ ] **Step 2: Capture exact RED**

```bash
python3 -m pytest \
  server/ctv_package_assignment_test.py \
  server/ctv_proposal_test.py \
  server/ctv_inspection_classifier_test.py -q
```

Expected: missing assignment module and approved snapshot method.

- [ ] **Step 3: Extend private roster parsing without widening public output**

Add fixed header categories for FA code and optional canonical fields. Parse one
bounded selected worksheet snapshot once, retain private values in ordinary
frozen dataclasses with `repr=False`, and keep only name plus masked identity in
`participants_for_local_review()`.

`approve(expected_digest)` records a one-time internal approval token. Every
later roster/decision mutation invalidates it. The new consume method recomputes
package-specific readiness/digest, requires that exact digest was approved in the
local session, consumes the token once, and returns deep immutable tuples. It does
not close or own the source observation and never authorizes writing from the
public approval dictionary alone.

- [ ] **Step 4: Implement assignment mapping**

Define locators as a complete mapping from included unit ID to one typed v2
locator. Derive deterministic decision IDs from proposal digest plus opaque record
ID. Emit one participant record per roster row, one included unit per assignment,
one excluded unit/source-only record per exclusion, and the fixed select-roster
and approve-proposal decisions used by the manifest.

```python
def build_assignments(
    snapshot: ApprovedProposalSnapshot,
    *,
    package_id: str,
    locators: Mapping[str, OutputLocatorV2],
) -> AssignmentBuildResult:
    """Return the closed assignment document plus its manifest decisions."""
```

Reject missing/extra locators, included unsupported units, selected roster not
case-scope `payment-roster`, participant order drift, and any private value in the
serialized assignment document.

- [ ] **Step 5: Run Task 3 gates**

```bash
python3 -m pytest \
  server/ctv_package_assignment_test.py \
  server/ctv_proposal_test.py \
  server/ctv_proposal_review_test.py \
  server/ctv_proposal_review_ui_test.py \
  server/ctv_inspection_classifier_test.py -q
python3 -m py_compile server/ctv_package_assignment.py server/ctv_proposal.py
git diff --check
```

- [ ] **Step 6: Commit and review**

```bash
git commit -m "feat(ctv): freeze approved package assignments"
```

Review focuses on normal roster correctness, explicit approval binding, exact
assignment accounting, private-value isolation, deterministic IDs, and no source
ownership/write change. Same-interpreter forged-object tests are excluded.

---

### Task 4: Build Deterministic Package Artifacts

**Files:**
- Create: `server/ctv_package_builder.py`
- Create: `server/ctv_package_builder_test.py`
- Modify: `server/ctv_inspection_media.py`
- Modify: `server/ctv_inspection_media_test.py`
- Modify: `server/ctv_inspection_workbook.py`
- Modify: `server/ctv_inspection_workbook_test.py`

**Interfaces:**
- Consumes: retained `InventoryObservation`, `InspectionResult`, `ApprovedProposalSnapshot`, v2 contract models, existing bounded parser proofs.
- Produces: `PackageIdentity.derive(observation_id, proposal_digest, writer_version, schema_version, compatibility_target)`, `PackageBuildPlan`, `ArtifactRecipe`, `RenderedArtifact`, `ArtifactReceipt`, `create_build_plan(observation, inspection, approved)`, `iter_rendered_artifacts(plan, observation)`, and `build_manifest_bytes(plan, receipts)`.

- [ ] **Step 1: Write identity/order RED tests**

Test domain-separated full package/batch/case IDs; 24-hex final suffix; writer
version affecting identity; no filename/path/value/timestamp inputs; exact PDF
ordering (case, shared, individual roster order, then source/unit order); shared
nonduplication; evidence numbering by source inspection order; worksheet grouping;
and locators fixed before rendering.

Call the exact boundaries with approved runtime values:

```python
identity = PackageIdentity.derive(
    observation_id=observation.observation_id,
    proposal_digest=approved.proposal_digest,
    writer_version=writer_version_string(),
    schema_version="2.0",
    compatibility_target="ctv-intake-v2",
)
plan = create_build_plan(observation, inspection, approved)
```

```python
plan = create_build_plan(observation, inspection, approved_snapshot)
assert plan.identity.final_directory == "ctv-package-" + plan.identity.digest[:24]
assert [page.unit_id for page in plan.pdf_pages] == [
    "unit-0004", "unit-0002", "unit-0001", "unit-0003"
]
assert len({page.source_page_key for page in plan.pdf_pages}) == len(plan.pdf_pages)
```

- [ ] **Step 2: Write transformation RED tests**

Generated adversarial/synthetic tests cover:

- exact source PDF page selection and contiguous target pages;
- zero-PDF rejection and 25,000-page ceiling before page acquisition;
- deterministic PyMuPDF save settings, cleared metadata, and derived trailer ID;
- selected roster single sheet, fixed `Roster Row ID`, canonical headers/order,
  values only, no formulas/macros/links/hidden content/comments/names/drawings;
- PNG RGBA normalization, first-frame rule, stripped metadata, fixed compression,
  pixel/25-MiB caps;
- one values-only evidence workbook per included source workbook, opaque sheet
  names, output index mapping, canonical ZIP entry order/time/permissions;
- unsupported/excluded source bytes never acquired or present in rendered output;
- per-file and aggregate byte charging before a render crosses its ceiling; and
- two complete builds producing byte-identical declared artifacts and manifest.

- [ ] **Step 3: Capture exact RED**

```bash
python3 -m pytest server/ctv_package_builder_test.py -q
```

Expected: `ModuleNotFoundError: No module named 'ctv_package_builder'`.

- [ ] **Step 4: Expose only the bounded transformation helpers needed**

Add package-specific public helpers that accept immutable bytes, never paths:

```python
def normalize_package_image(snapshot: bytes, *, limits: InspectionLimits) -> bytes:
    """Return fixed RGBA PNG bytes or raise a fixed bounded media error."""

def selected_worksheet_values(
    snapshot: bytes,
    worksheet_indexes: tuple[int, ...],
    *,
    limits: InspectionLimits,
) -> tuple[WorksheetValues, ...]:
    """Return bounded values-only rows after existing OOXML preflight."""
```

Keep existing inspection/OCR/preview output byte-compatible. Package helpers
reuse the same parser proofs and fixed errors; they do not add a second path-based
loader.

- [ ] **Step 5: Implement pure build planning and one-artifact-at-a-time rendering**

`create_build_plan` computes identities, assignment locators, artifact IDs/paths,
and recipes without writing. `iter_rendered_artifacts` snapshots only recipe
sources and yields at most one bounded artifact in memory. Sequence is input PDF,
roster, evidence in source order, assignments, exceptions. After the transaction
returns exact receipts, `build_manifest_bytes` creates canonical manifest bytes
whose artifact provenance equals the assignments.

Canonical XLSX output is OpenPyXL values-only content repacked with sorted ZIP
members, fixed `1980-01-01` timestamps, fixed Unix permissions, and compression
level 9. Canonical JSON uses sorted keys, compact separators, UTF-8, and one LF.
Canonical PDF uses `garbage=4`, `clean=1`, `deflate=1`, `no_new_id=1`, cleared
metadata, and the derived trailer ID.

- [ ] **Step 6: Run Task 4 gates**

```bash
python3 -m pytest \
  server/ctv_package_builder_test.py \
  server/ctv_package_assignment_test.py \
  server/ctv_inspection_media_test.py \
  server/ctv_inspection_workbook_test.py -q
python3 -m py_compile \
  server/ctv_package_builder.py \
  server/ctv_inspection_media.py \
  server/ctv_inspection_workbook.py
git diff --check
```

Run the deterministic generated build three times in fresh directories and compare
manifest plus every declared artifact byte-for-byte.

- [ ] **Step 7: Commit and review**

```bash
git commit -m "feat(ctv): build deterministic intake artifacts"
```

The reviewer traces every approved unit to one locator/artifact, checks page/order
rules and byte/resource bounds, and verifies excluded data is never acquired.

---

### Task 5: Validate V2 Content and Publication Receipts

**Files:**
- Create: `server/intake_fixture_factory_v2.py`
- Create: `server/intake_fixture_factory_v2_test.py`
- Create: `server/intake_package_validator_v2.py`
- Create: `server/intake_package_validator_v2_test.py`
- Modify: `server/intake_package_validator.py`
- Modify: `server/intake_package_validator_test.py`
- Modify: `server/validate_intake_package.py`
- Modify: `server/validate_intake_package_test.py`
- Create: `server/validate_intake_package_v2_test.py`

**Interfaces:**
- Consumes: production v2 builder, caller-owned `_PackageReader`, live `InventoryObservation`, v2 models, v1 validator behavior.
- Produces: `MaterializedV2Fixture`, `materialize_v2_fixture(name, output, include_receipt=False)`, `_PackageReader.open_at(parent_fd, child_name, expected_identity=None)`, descriptor-owned tree snapshot/digest, `V2ValidationExpectation`, `ContentValidationV2`, `validate_v2_content_reader(reader, observation, expectation)`, `canonical_v2_receipt_bytes(content)`, `validate_v2_publication_reader(reader, observation, expectation)`, and standalone v1/v2 version dispatch.

- [ ] **Step 1: Write generated fixture and package-reader RED tests**

The factory builds its synthetic source through inspection, proposal decisions,
and the production Task 4 serializers. It returns package/source directories,
manifest/assignment models, and observation ID; it does not contain a second PDF,
XLSX, image, assignment, or manifest writer. Require deterministic materialization,
no writes outside the target, complete and invalid-assignment variants, and
clearly synthetic values only.

Cover `open_at` exact single-component child names, no-follow, expected inode,
closed/arbitrary descriptor rejection under the existing lean internal boundary,
tree allowlist, deterministic sorted digest, symlink/FIFO/nested/extra/changed
entry rejection, byte charging on failed reads, and v1 reader/public API regression.

- [ ] **Step 2: Write content-validation RED tests**

Materialize the production-backed `complete` v2 fixture and independently corrupt every contract
relationship: manifest/artifact/assignment digest, source binding, actual PDF page
count, hidden/duplicate/missing target page, participant/row mapping, decision
type, accepted/reassigned role, scope cardinality/order, artifact source IDs,
output locator, evidence workbook index, FA code, package identity, empty
exceptions rule, extra file, and a report present during content phase.

```python
content = validate_v2_content_reader(
    package_reader,
    observation,
    expectation=V2ValidationExpectation(
        observation_id=observation.observation_id,
        proposal_digest=approved_digest,
    ),
)
assert content.report.outcome == "valid"
assert content.manifest_sha256 == sha256(manifest_bytes).hexdigest()
assert content.report.checks
```

- [ ] **Step 3: Write publication-validation RED tests**

Require the receipt to match content `sourceObservationId`, `proposalDigest`,
`packageId`, `manifestSha256`, declared-artifact-set digest, outcome, and ordered
checks. Reject missing, malformed, stale, self-declared, empty-check, mismatched,
or privately verbose reports. Require exactly one additional
`validation-report-consistent` publication check.

- [ ] **Step 4: Capture exact RED**

```bash
python3 -m pytest \
  server/intake_fixture_factory_v2_test.py \
  server/intake_package_validator_v2_test.py \
  server/intake_package_validator_test.py \
  server/validate_intake_package_test.py -q
```

Expected: v2 factory/validator are missing and reader lacks `open_at`/tree snapshot.

- [ ] **Step 5: Implement the reader-owned v2 core**

First implement `materialize_v2_fixture` as a generated test utility over the
production builder. With `include_receipt=False` it materializes content phase;
after a valid content result it may write that canonical receipt when
`include_receipt=True`. It never generates a receipt without validator output.

Do not pass source paths to the in-process validator. Verified sources use
`observation.snapshot(source_id, max_bytes=source_ceiling)`; unacquired exclusions are matched
to the observation's fixed source facts without opening them. Parse each artifact
from its one cached bounded byte snapshot. Use fixed issue codes and synthetic
evidence IDs; never include paths, values, parser diagnostics, or raw exceptions.

Content validation requires the receipt absent. Publication validation recomputes
content with the receipt excluded from the declared tree digest, validates the
receipt, and adds the fixed receipt-consistency check. The receipt does not hash
itself.

- [ ] **Step 6: Add standalone version dispatch without weakening v1**

The standalone CLI securely reads the manifest once through its opened reader.
Schema `1.0` calls the unchanged v1 core. Schema `2.0` opens one content-bound
inventory observation for `--source-root` and performs publication validation of
the existing writer receipt. V2 `--write-report` fails with fixed
`v2-report-writer-only`; only `ctv_package_writer.py` may create the receipt inside
its retained transaction. Existing v1 historical-report refusal, report writing,
and output remain unchanged.

- [ ] **Step 7: Run Task 5 gates**

```bash
python3 -m pytest \
  server/intake_fixture_factory_v2_test.py \
  server/intake_package_validator_v2_test.py \
  server/intake_package_validator_test.py \
  server/validate_intake_package_test.py \
  server/validate_intake_package_v2_test.py \
  server/intake_contract_v2_test.py \
  server/intake_contract_test.py -q
python3 -m py_compile \
  server/intake_fixture_factory_v2.py \
  server/intake_package_validator_v2.py \
  server/intake_package_validator.py \
  server/validate_intake_package.py
git diff --check
```

Run the complete v1 synthetic fixture through the public validator and compare its
canonical report to the pre-task golden bytes. Run the complete v2 fixture through
content, report write, and publication validation.

- [ ] **Step 8: Commit and review**

```bash
git commit -m "feat(ctv): validate intake contract v2"
```

Review focuses on false-valid packages, bounded acquisition before parser calls,
reader/source capability ownership, two-phase receipt semantics, privacy-safe
issues, and exact v1 compatibility.

---

### Task 6: Publish Through a Capability-Owned Transaction

**Files:**
- Create: `server/ctv_package_transaction.py`
- Create: `server/ctv_package_transaction_test.py`
- Create: `server/ctv_package_writer.py`
- Create: `server/ctv_package_writer_test.py`
- Modify: `server/ctv_inventory.py`
- Modify: `server/ctv_inventory_test.py`

**Interfaces:**
- Consumes: retained observation, retained `OutputParent`, approved snapshot, build plan/artifacts, v2 validator.
- Produces: `InventoryObservation.directory_identity_chain()`, `InventoryObservation.finalize_for_publication() -> ObservationPublicationToken`, `OutputParent.open(path)`, `OutputParent.require_disjoint(source_identity_chain)`, `StagingTransaction`, `prepare_package(observation, inspection, approved, output) -> PackagePreparationResult`.

- [ ] **Step 1: Write source-finalization RED tests**

Require an observation publication token only after successful exact-tree
revalidation; no snapshots after finalization; context exit releases without a
second revalidation; ordinary proposal/inventory contexts still revalidate on
exit; mutation before finalization fails; directory identity chain contains only
device/inode pairs; and repr/errors contain no path.

```python
with open_inventory_observation(source_root) as observation:
    _ = observation.snapshot("evidence-0001", max_bytes=1024)
    token = observation.finalize_for_publication()
    assert token.observation_id == observation.observation_id
    with pytest.raises(RuntimeError, match="finalized"):
        observation.snapshot("evidence-0001", max_bytes=1024)
```

- [ ] **Step 2: Write output/staging RED tests**

Cover missing/non-directory/symlink/FIFO output; source equals output; either tree
inside the other using inode ancestry; component swap; mode `0700`/`0600`;
descriptor-relative no-follow writes; temp collision; partial/zero-progress write;
fsync error; exact allowlist/tree digest; final-name preexistence; competing
creation between precheck and publish; unavailable `renameatx_np`; cleanup only of
the retained run-owned staging inode; crash-like hidden staging ignored; and no
source modification.

- [ ] **Step 3: Capture transaction RED**

```bash
python3 -m pytest \
  server/ctv_package_transaction_test.py \
  server/ctv_inventory_test.py -q
```

Expected: transaction module and observation publication boundary are missing.

- [ ] **Step 4: Implement the source publication boundary**

`finalize_for_publication()` waits for in-flight snapshot leases, performs the
existing exact tree revalidation, marks the observation finalized, returns a
trusted ordinary token, and prevents further source reads. The context manager
releases a finalized observation without rerunning the tree scan. If finalization
is never called, existing close-time revalidation remains unchanged.

`directory_identity_chain()` walks `..` from the retained root descriptor with a
fixed depth cap and returns only `(device, inode)` values. It never exposes or
reopens the source path.

- [ ] **Step 5: Implement output and staging capabilities**

Open the output parent once with `O_DIRECTORY|O_NOFOLLOW|O_CLOEXEC`. Compare its
descriptor ancestry with the source chain in both directions. Create one random
hidden child with `mkdirat` semantics and retain its device/inode. All writes use
fresh `O_CREAT|O_EXCL|O_NOFOLLOW` temporaries, complete-write loops, fsync, and
same-directory rename. Attempted bytes are charged against the 1-GiB run budget
before writing.

Implement Darwin no-replace publication exactly:

```python
RENAME_EXCL = 0x00000004
renameatx_np = ctypes.CDLL(None, use_errno=True).renameatx_np
renameatx_np.argtypes = [
    ctypes.c_int, ctypes.c_char_p,
    ctypes.c_int, ctypes.c_char_p,
    ctypes.c_uint,
]
renameatx_np.restype = ctypes.c_int
```

Call it with retained parent FD for both source and destination names. A nonzero
result maps only known collision/unavailable cases to fixed errors; never fall
back to `os.rename`, `os.replace`, pathname copy, or delete-then-rename.

- [ ] **Step 6: Write writer-orchestration RED tests**

Inject fake builder/validator/transaction stages and fail each boundary. Require:
no staging before all approval/FA/collision checks; declared artifacts written in
plan order; content validation before receipt; receipt atomic write/fsync;
publication validation; source finalization; final staging inode/tree digest;
no-replace publication; handled cleanup; deterministic collision; successful
output survives stdout-independent later error; and public result exact fields.

- [ ] **Step 7: Capture writer RED**

```bash
python3 -m pytest server/ctv_package_writer_test.py -q
```

Expected: writer module is missing.

- [ ] **Step 8: Implement `prepare_package`**

```python
def prepare_package(
    observation: InventoryObservation,
    inspection: InspectionResult,
    approved: ApprovedProposalSnapshot,
    output: OutputParent,
) -> PackagePreparationResult:
    """Build, validate, finalize, and atomically publish one v2 package."""
```

The CLI has already opened the output parent and proved it disjoint without
writing. The writer creates a plan, checks deterministic collision, creates
staging, streams rendered artifacts one at a time, writes manifest, opens
a reader with `open_at`, runs content validation, writes the canonical receipt,
runs publication validation with a fresh reader, calls source finalization, checks
the final staging identity/tree digest, and publishes no-replace. The result stores
only package ID, opaque directory name, manifest/artifact/tree digests, contract
version, safe counts, fixed validation codes, and `readyForCtvReview=True`.

- [ ] **Step 9: Run Task 6 gates**

```bash
python3 -m pytest \
  server/ctv_package_transaction_test.py \
  server/ctv_package_writer_test.py \
  server/ctv_inventory_test.py \
  server/ctv_package_builder_test.py \
  server/intake_package_validator_v2_test.py -q
python3 -m py_compile \
  server/ctv_package_transaction.py \
  server/ctv_package_writer.py \
  server/ctv_inventory.py
git diff --check
```

On Darwin/APFS, run the real no-replace race and atomic-visibility integration
tests rather than relying only on monkeypatches.

- [ ] **Step 10: Commit and review**

```bash
git commit -m "feat(ctv): publish prepared packages atomically"
```

Review follows the exact transaction sequence and approved threat boundary. It
must prove no existing output can be replaced and no failure before publication
exposes a final package.

---

### Task 7: Expose the Combined Package-Prepare CLI

**Files:**
- Modify: `server/ctv_cli_protocol.py`
- Modify: `server/ctv_cli_protocol_test.py`
- Modify: `server/ctv_intake_cli.py`
- Modify: `server/ctv_intake_cli_test.py`
- Modify: `server/README.md`

**Interfaces:**
- Consumes: versioned pin verification, retained inspection/proposal review, approved snapshot, `prepare_package`.
- Produces: exact `contract verify --target ctv-intake-v2 --json`, exact `package prepare --source-root SOURCE --output-root OUTPUT_PARENT --json`, operation `package.prepare`, exit mapping, lazy imports, and bounded canonical WP result.

- [ ] **Step 1: Write exact argv/protocol RED tests**

Require only these new exact forms:

```text
contract verify --target ctv-intake-v2 --json
package prepare --source-root SOURCE --output-root OUTPUT_PARENT --json
```

Reject reordered, repeated, abbreviated, empty, option-like, slash-empty-component,
missing, and extra arguments with empty stdout and fixed usage stderr. Existing
exact commands retain their golden bytes. Require lazy imports so invalid/v1/
inventory/inspect/proposal commands do not import builder/writer/v2 validator.

- [ ] **Step 2: Write lifecycle/outcome RED tests**

Use injected review and writer drivers. Cover approved→prepared, draft, cancelled,
review/source/output/build/validation/collision/cleanup controlled failures,
unexpected failure, result over 16 MiB, final stdout failure, no writes for
draft/cancel, and v2 pin failure before source observation opens.

```python
exit_code = main(
    [
        "package", "prepare",
        "--source-root", str(source_root),
        "--output-root", str(output_root),
        "--json",
    ],
    package_review_driver=approve_driver,
    package_prepare_driver=fake_prepare,
)
assert exit_code == 0
assert json.loads(stdout)["operation"] == "package.prepare"
```

- [ ] **Step 3: Capture exact RED**

```bash
python3 -m pytest \
  server/ctv_cli_protocol_test.py \
  server/ctv_intake_cli_test.py -q
```

Expected: protocol rejects `package.prepare` and parser rejects both new forms.

- [ ] **Step 4: Implement lazy combined lifecycle**

Add `package.prepare` to the closed protocol operation set. Before opening the
source, call `verify_contract(REPOSITORY_ROOT, target="ctv-intake-v2")`. Then:

```python
with OutputParent.open(output_root) as output:
    with open_inventory_observation(source_root) as observation:
        output.require_disjoint(observation.directory_identity_chain())
        inspection = inspect_observation(observation)
        state = ProposalState.from_inspection(observation, inspection)
        terminal = review_driver(state)
        if terminal["outcome"] in {"draft", "cancelled"}:
            return terminal
        approved = state.consume_approved_package_snapshot(terminal["proposalDigest"])
        return prepare_driver(observation, inspection, approved, output)
```

Opening/proving the output boundary performs no write, so unsafe/overlapping roots
fail before the local review and draft/cancel still creates no staging. The writer
finalizes the observation before publication; context exit then only releases it.
Buffer the envelope and emit once. Map fixed controlled failures to
exit 2, invalid invocation/unexpected internal failure to exit 1, and prepared/
draft/cancelled to exit 0. Never delete a published package after emission failure.

- [ ] **Step 5: Define exact prepared public result**

Return only:

```json
{
  "version": "1.0",
  "outcome": "prepared",
  "packageId": "package-0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef",
  "packageDirectoryName": "ctv-package-0123456789abcdef01234567",
  "manifestSha256": "1123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef",
  "declaredArtifactSetSha256": "2123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef",
  "publishedTreeSha256": "3123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef",
  "contractVersion": "2.0",
  "counts": {
    "sources": 5,
    "participants": 2,
    "pdfPages": 3,
    "evidenceArtifacts": 2,
    "assignments": 5,
    "exclusions": 1
  },
  "validation": {
    "outcome": "valid",
    "checkCodes": [
      "manifest-valid",
      "assignments-valid",
      "source-verification-complete",
      "validation-report-consistent"
    ],
    "warningCodes": []
  },
  "readyForCtvReview": true
}
```

The values are synthetic but the key/type shape and fixed check-code spellings are
exact. Draft and cancel reuse the lean proposal safe shape and contain no output
field.

- [ ] **Step 6: Document local WP usage**

Document v2 preflight, exact command, local screen, output-parent meaning, opaque
directory result, exit/outcome table, collision/retry behavior, hidden-staging
recovery boundary, privacy exclusions, human CTV review requirement, and that WP
calls local scripts without bundling them.

- [ ] **Step 7: Run Task 7 gates**

```bash
python3 -m pytest \
  server/ctv_cli_protocol_test.py \
  server/ctv_intake_cli_test.py \
  server/ctv_proposal_review_test.py \
  server/ctv_package_writer_test.py \
  server/ctv_contract_pin_test.py -q
python3 -m py_compile server/ctv_cli_protocol.py server/ctv_intake_cli.py
git diff --check
```

- [ ] **Step 8: Commit and review**

```bash
git commit -m "feat(ctv): expose prepared package command"
```

Review traces exact argv through v2 pin, one retained observation, local approval,
writer publication, canonical output, exit code, lazy imports, and private-value
scans. It also reruns every legacy CLI golden test.

---

### Task 8: Generated End-to-End Acceptance and Handoff

**Files:**
- Create: `server/ctv_package_acceptance_test.py`
- Modify: `server/README.md`
- Modify: `contracts/ctv-intake/README.md`

**Interfaces:**
- Consumes: exact Task 7 head, generated v2 fixture/source, public CLI, local review HTTP/UI, standalone validator.
- Produces: one executable generated acceptance test, sanitized smoke evidence, exact-head review, and WP handoff documentation.

- [ ] **Step 1: Write the full generated acceptance gate**

Materialize a source folder with a two-page PDF, selected roster, included image,
included non-roster worksheet, excluded unit, and excluded unsupported source-only
record. Drive the real local review HTTP endpoints with bootstrap cookie/CSRF,
select roster, set individual/shared/case assignments, exclude records, approve,
and let the real writer publish.

Assert:

- one opaque final directory and no hidden staging;
- exact allowlisted layout/modes;
- input PDF page order/count;
- roster values/row IDs and no active content;
- assignments cross-references and no participant values;
- evidence normalized and excluded bytes absent;
- empty exceptions;
- standalone publication validation returns valid;
- CLI JSON exact safe keys/counts/digests;
- source protected content/entry set/mode/size/mtime unchanged, excluding atime;
- second identical run returns controlled collision and changes no output byte.

- [ ] **Step 2: Run the acceptance test and fix only real integration gaps**

```bash
python3 -m pytest server/ctv_package_acceptance_test.py -q
```

Expected: FAIL at the first real integration or cross-reference gap, or PASS if
the earlier task gates already cover the complete flow. Never manufacture a
production change merely to force a RED. For a real failure, fix the owning
earlier task's module and add the focused regression there; do not add
acceptance-only production branches. A spec contradiction stops execution and
returns to design approval; a contract change returns to Task 1 and regenerates
the Task 2 pin.

- [ ] **Step 3: Run a real local browser smoke**

Materialize the same generated source in a fresh temporary directory, start the
exact `package prepare` command in a PTY, use the opened local screen to select the
roster and make one individual, one shared, one case, and one exclusion decision,
approve, then verify:

- zero browser console errors;
- no non-loopback request;
- terminal exit 0 and one canonical prepared envelope;
- standalone v2 validator exit 0 with `--source-root`;
- published tree digest equals the CLI value; and
- no private source/roster value in terminal output or recorded smoke notes.

Record only opaque IDs, safe counts, fixed codes, exit statuses, and test totals.

- [ ] **Step 4: Run complete regression and deterministic gates**

```bash
python3 -m pytest -q
npm test -- --run
npm run build
python3 -m py_compile server/*.py
git diff --check
```

Additionally:

1. Export v1 and v2 contracts into fresh directories; compare each to its
   checked-in version byte-for-byte.
2. Verify both pin targets.
3. Compute v1 tree digest and require its original pinned value.
4. Compute v2 tree digest from the exact reviewed contract commit and require
   `PIN.v2.json` equality.
5. Search product diffs, fixtures, test output, and docs for real-looking names,
   identities, FA codes, bank values, absolute source paths, raw parser errors,
   temporary tokens, and staging names.
6. Confirm `git status --short` contains only intentional task files plus the
   preserved pre-existing `.DS_Store` and `.superpowers/` entries.

- [ ] **Step 5: Commit the acceptance/handoff slice**

```bash
git commit -m "test(ctv): accept prepared package workflow"
```

- [ ] **Step 6: Final independent exact-head review**

Reviewer reads the approved spec and every task commit, then checks the real
CLI→review→assignment→builder→validator→transaction→JSON flow. Findings are rated
Critical/Important/Minor against the explicit lean threat boundary. Allow one
final surgical correction wave for Critical/Important findings, rerun the focused
and complete gates, commit that correction separately, and require a clean
exact-head re-review.

Do not push, merge, update WP's pinned copy, delete worktrees, or claim CTV/payment
approval. Return exact local commits, tests, safe smoke evidence, v2 tree hash, and
remaining product limitations to the plan owner.

---

## Completion Boundary

The implementation is complete only when all eight tasks are independently
accepted, the exact-head browser/package smoke passes, full Python/frontend/build
gates are green, v1 is byte-compatible, v2 pin/tree hashes match, and the public
result is privacy-safe. Completion means “locally prepared for CTV human review,”
not evidence authenticity, accounting approval, payment authorization, direct
submission, WP pin integration, push, merge, or release.
