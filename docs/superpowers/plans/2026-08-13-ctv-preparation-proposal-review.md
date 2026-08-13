# CTV Preparation Proposal Review Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an ephemeral local hybrid review screen that turns one unchanged CTV inspection observation into a deterministic, privacy-safe, locally approved preparation proposal without writing files.

**Architecture:** Keep one secure `InventoryObservation` open across inspection, private roster/preview access, proposal editing, and approval. Pure immutable proposal models and validation sit below a memory-only session state machine; a standard-library loopback server exposes only authenticated fixed endpoints to a dependency-free local UI. The CLI blocks until approved, draft, cancelled, or failed, closes/revalidates the observation, then emits one bounded canonical envelope.

**Tech Stack:** Python 3.14, dataclasses, Pydantic-free closed model validation, hashlib/json, existing PyMuPDF/Pillow/OpenPyXL safety adapters, standard-library `http.server`/`socket`/`secrets`/`webbrowser`, pytest, existing React/Vitest frontend regression suite.

**Spec:** `docs/superpowers/specs/2026-08-13-ctv-preparation-proposal-review-design.md`

## Global Constraints

- Exact public invocation: `proposal review --source-root SOURCE --json`; all other ordering/abbreviation/extra-token forms are invalid.
- CLI envelope schema stays `1.0`; the new operation is exactly `proposal.review`.
- No prepared package, draft, report, cache, thumbnail, extracted-text file, state file, source modification, WP bundle, database, new dependency, contract snapshot change, or non-loopback network access.
- One live descriptor-bound observation owns inspection, roster extraction, preview, approval, and final tree revalidation; stdout is emitted only after that context closes successfully.
- Browser binding is IPv4 `127.0.0.1` on an OS-assigned port; bootstrap, session, and CSRF values each carry at least 256 bits of entropy.
- Browser private values never enter stdout, stderr, logs, public result models, digest input except opaque IDs, commits, or WP context.
- Approved output accounts exactly once for every inspection unit and every zero/unknown-unit source; drafts return totals/issues only; cancelled returns no assignments.
- `readyToPrepare: true` requires a valid explicit roster, every record resolved, no `unknown` role, exact digest recheck, unchanged observation, and local user approval.
- Maximum session duration is 2 hours; idle duration 5 minutes; JSON request 1 MiB; JSON response 16 MiB; preview response 25 MiB.
- Existing inventory, PDF, workbook, image, OCR, unit, and canonical-output ceilings remain hard upper bounds.
- Tests use generated synthetic data only; no real customer PII is committed or printed.
- TDD is mandatory: capture exact RED before each production edit, then minimal GREEN.
- Every task commits only its declared files locally; no push, merge, release, packaging, or worktree cleanup.

---

### Task 1: Immutable Proposal Contract and Pure Validator

**Files:**
- Create: `server/ctv_proposal_model.py`
- Create: `server/ctv_proposal_model_test.py`
- Create: `server/ctv_proposal_validator.py`
- Create: `server/ctv_proposal_validator_test.py`

**Interfaces:**
- Consumes: `InspectionResult`, `InspectionSource`, `InspectionUnit`, and the existing fixed `SuggestedRole`/unit-kind role rules from `ctv_inspection_model.py`.
- Produces: immutable `Participant`, `AssignmentTarget`, `UnitDecision`, `SourceDisposition`, `ProposalTotals`, `ProposalDraftState`, `ApprovedProposal`, `DraftProposal`, `CancelledProposal`; `validate_proposal(inspection, participants, roster_unit_id, source_dispositions, unit_decisions) -> ProposalValidation`; `proposal_digest(validation) -> str`; `approve_proposal(validation, expected_digest) -> ApprovedProposal`.

- [ ] **Step 1: Write closed-model RED tests**

Create constructors/helpers using only synthetic opaque IDs, then require exact primitives, deep immutability, deterministic `to_dict()`, extra-field rejection at mapping parsers, and closed enum/cardinality rules. Include at least these direct tests:

```python
def test_shared_target_requires_two_distinct_handles_in_roster_order():
    with pytest.raises(ValueError):
        AssignmentTarget("shared", ("participant-0001",))
    with pytest.raises(ValueError):
        AssignmentTarget("shared", ("participant-0002", "participant-0001"))
    assert AssignmentTarget(
        "shared", ("participant-0001", "participant-0002")
    ).to_dict() == {
        "scope": "shared",
        "participantHandles": ["participant-0001", "participant-0002"],
    }

def test_unknown_role_cannot_be_resolved_or_approved():
    with pytest.raises(ValueError):
        UnitDecision(
            unit_id="unit-0001", decision="accepted", role="unknown",
            target=AssignmentTarget("case", ()), exclusion_reason=None,
        )
```

Also test `accepted` must equal the inspection suggestion during validation,
`reassigned` must differ, excluded/unresolved have neither role nor target, and
all five fixed exclusion reasons are the only accepted values.

- [ ] **Step 2: Run model RED**

Run:

```bash
python3 -m pytest server/ctv_proposal_model_test.py -q
```

Expected: collection/import failure because `ctv_proposal_model.py` does not exist.

- [ ] **Step 3: Implement immutable public values**

Use frozen dataclasses and exact-type checks. Define these closed literals and regexes:

```python
ProposalOutcome = Literal["approved", "draft", "cancelled"]
Decision = Literal["accepted", "reassigned", "excluded", "unresolved"]
TargetScope = Literal["individual", "shared", "case"]
ExclusionReason = Literal[
    "duplicate", "irrelevant", "unreadable-replacement-available",
    "intentionally-omitted", "other",
]
PARTICIPANT_HANDLE = re.compile(r"^participant-[0-9]{4,}$")
PROPOSAL_DIGEST = re.compile(r"^proposal-[a-f0-9]{64}$")
```

Each `to_dict()` returns a deep copy. Mapping parsers accept `type(value) is dict`
only and require exact key sets. Public `ApprovedProposal`, `DraftProposal`, and
`CancelledProposal` enforce their exact shape and readiness/outcome relationship.

- [ ] **Step 4: Run model GREEN**

Run the Task 1 model file and require all tests pass.

- [ ] **Step 5: Write pure-validator RED tests**

Build a synthetic inspection with two participants, two units, and one opaque
source-only record. Require:

```python
def test_validation_accounts_for_every_unit_and_source_only_record_once():
    result = validate_proposal(
        inspection=_inspection(),
        participants=_participants(),
        roster_unit_id="unit-0001",
        source_dispositions=(),
        unit_decisions=(),
    )
    assert result.ready_to_prepare is False
    assert result.totals.unresolved == 3
    assert result.issue_codes == ("proposal-unresolved",)
```

Add RED cases for missing/duplicate/foreign IDs, wrong roster kind/signal,
participant target cardinality/order, role not allowed for unit kind, accepted vs
reassigned mismatch, unresolved blocking, source-only resolution, at least one
participant, and canonical inspection order regardless of caller order.

Add digest tests changing each mutable approval field independently and asserting
the digest changes, while private labels/notes cannot enter the validator API.

- [ ] **Step 6: Run validator RED**

Run:

```bash
python3 -m pytest server/ctv_proposal_validator_test.py -q
```

Expected: import failure for the missing validator.

- [ ] **Step 7: Implement pure validation and digest**

Define:

```python
@dataclass(frozen=True)
class ProposalValidation:
    observation_id: str
    roster_unit_id: str | None
    participants: tuple[Participant, ...]
    source_dispositions: tuple[SourceDisposition, ...]
    unit_decisions: tuple[UnitDecision, ...]
    totals: ProposalTotals
    issue_codes: tuple[str, ...]
    ready_to_prepare: bool

def validate_proposal(...) -> ProposalValidation: ...
def canonical_approval_payload(validation: ProposalValidation) -> dict[str, object]: ...
def proposal_digest(validation: ProposalValidation) -> str: ...
def approve_proposal(validation: ProposalValidation, expected_digest: str) -> ApprovedProposal: ...
```

Build authoritative maps once for O(n) validation. Canonical JSON uses
`ensure_ascii=False`, `sort_keys=True`, separators `(',', ':')`, and UTF-8. Digest
is `proposal-` plus lowercase SHA-256 hex. `approve_proposal` requires readiness,
recomputes the digest, compares with `hmac.compare_digest`, and never accepts a
caller-supplied approval object.

- [ ] **Step 8: Run Task 1 and legacy contract tests**

Run:

```bash
python3 -m pytest \
  server/ctv_proposal_model_test.py \
  server/ctv_proposal_validator_test.py \
  server/ctv_inspection_model_test.py \
  server/ctv_cli_protocol_test.py -q
python3 -m py_compile server/ctv_proposal_model.py server/ctv_proposal_validator.py
git diff --check
```

- [ ] **Step 9: Commit Task 1**

Stage only the four Task 1 files and commit:

```bash
git commit -m "feat(ctv): define preparation proposal contract"
```

---

### Task 2: Private Roster Extraction on the Retained Observation

**Files:**
- Create: `server/ctv_proposal_roster.py`
- Create: `server/ctv_proposal_roster_test.py`
- Modify: `server/ctv_inspection_workbook.py`
- Modify: `server/ctv_inspection_workbook_test.py`
- Modify: `server/ctv_inspection.py`
- Modify: `server/ctv_inspection_test.py`

**Interfaces:**
- Consumes: one caller-owned live `InventoryObservation`; its bounded `snapshot(evidence_id, max_bytes=...)`; current inspection models; existing safe workbook member parsing/normalization boundaries.
- Produces: `inspect_observation(observation, *, limits=...) -> InspectionResult` that never closes the caller-owned observation; private frozen `RosterParticipant(handle, display_name, row_index)`; `extract_roster_participants(observation, inspection, roster_unit_id) -> tuple[RosterParticipant, ...]`.

- [ ] **Step 1: Write caller-owned observation RED tests**

Require that `inspect_observation()` produces the same deterministic result as
`inspect_source()` while leaving close/revalidation to the caller. Test one
observation used for inspection and a second snapshot before context exit; verify
source mutation before exit maps to the existing tree-changed boundary.

- [ ] **Step 2: Run RED and implement the narrow inspection interface**

Run the named new tests first. Refactor only the existing internal
`_inspection_result()` ownership boundary; do not expose descriptors, state
registries, source components, or general filesystem access. `inspect_source()`
must continue to open/close its own observation and preserve exact behavior.

- [ ] **Step 3: Write roster extraction RED tests**

Generate bounded `.xlsx` snapshots for transitional and strict OOXML. Cover:

- exact explicit worksheet unit selection;
- header requiring recognized `name` and `identity` categories;
- handles in usable row order;
- local NFC display labels capped at 256 characters;
- normalized identity keys used only for duplicate detection and cleared after use;
- duplicate identity, malformed/blank rows, formula/error/date/bool identity cells,
  hidden selected sheet, >10,000 rows, >100,000 examined cells, decompression/parser
  boundaries, encrypted/corrupt content, and wrong/current-observation unit IDs;
- no names/identities in `repr`, exception text, public model, captured stdout/stderr,
  or report fixtures.

Representative assertion:

```python
participants = extract_roster_participants(
    observation, inspection, "unit-0001"
)
assert [(p.handle, p.row_index) for p in participants] == [
    ("participant-0001", 2), ("participant-0002", 3),
]
assert participants[0].display_name == "Synthetic Person A"
assert "900000000001" not in repr(participants)
```

- [ ] **Step 4: Run roster RED**

Run:

```bash
python3 -m pytest server/ctv_proposal_roster_test.py -q
```

Expected: import failure for missing roster module.

- [ ] **Step 5: Add a bounded workbook-sheet reader**

Inside `ctv_inspection_workbook.py`, expose one private-safe function that accepts
snapshot bytes and one-based sheet index and calls a supplied visitor over bounded
cell primitives without returning a workbook object:

```python
def visit_bounded_worksheet(
    snapshot: bytes,
    worksheet_index: int,
    *,
    max_rows: int,
    max_columns: int,
    max_cell_characters: int,
    visitor: Callable[[int, int, str], None],
) -> None: ...
```

It must reuse the existing archive/member/XML/parser/decompression checks, inspect
only the selected current sheet after authoritative enumeration, never evaluate
formulas, and clear private text after each visitor call. Bounds may only narrow
existing limits.

- [ ] **Step 6: Implement roster extraction**

Resolve the selected unit through the inspection result to its evidence ID and
worksheet index; snapshot exactly that current evidence under the workbook source
cap; visit at most 10,000 rows and existing cell budget. Detect header categories
using `roster_header_categories_from_private_text`. Accept plain string/number
identity cells only after bounded normalization; never retain or return the
identity. Fail with fixed private `RosterError(code)` where allowed codes are
`proposal-roster-unavailable`, `proposal-roster-invalid`, and
`proposal-roster-duplicate`.

- [ ] **Step 7: Run Task 2 gates**

Run:

```bash
python3 -m pytest \
  server/ctv_proposal_roster_test.py \
  server/ctv_inspection_workbook_test.py \
  server/ctv_inspection_test.py -q
python3 -m pytest server/ctv_proposal_model_test.py server/ctv_proposal_validator_test.py -q
python3 -m py_compile server/ctv_proposal_roster.py server/ctv_inspection_workbook.py server/ctv_inspection.py
git diff --check
```

- [ ] **Step 8: Commit Task 2**

Commit only the six declared files:

```bash
git commit -m "feat(ctv): derive private roster participants safely"
```

---

### Task 3: Authenticated Unit Preview Adapters

**Files:**
- Create: `server/ctv_proposal_preview.py`
- Create: `server/ctv_proposal_preview_test.py`
- Modify: `server/ctv_inspection_media.py`
- Modify: `server/ctv_inspection_media_test.py`
- Modify: `server/ctv_inspection_workbook.py`
- Modify: `server/ctv_inspection_workbook_test.py`

**Interfaces:**
- Consumes: live `InventoryObservation`, current `InspectionResult`, a current `unit_id`, and existing bounded PDF/image/workbook parsers.
- Produces: frozen private `PreviewPayload(content_type, body)`; `preview_unit(observation, inspection, unit_id) -> PreviewPayload` where body is either bounded normalized PNG bytes or bounded UTF-8 JSON table bytes.

- [ ] **Step 1: Write preview RED tests**

Test generated PDF page, image, and worksheet units. Require current unit binding,
correct one-based page/sheet selection, PNG signature for media, closed worksheet
table schema, 200-row/50-column/256-character narrowing, 25 MiB maximum response,
and fixed private `PreviewError` on unsupported/wrong/changed/unsafe content.

Poison filesystem paths, temp APIs, external sockets, logging, and parser methods
before boundary proof. Verify preview errors have no raw context/cause/traceback
locals containing markers.

- [ ] **Step 2: Run preview RED**

Run the new preview file and expect missing-module import failure.

- [ ] **Step 3: Extract bounded media rendering helpers**

Add narrow helpers that operate only on caller-supplied snapshot bytes and indexes:

```python
def render_pdf_page_preview(snapshot: bytes, page_index: int, *, limits: InspectionLimits) -> bytes: ...
def normalize_image_preview(snapshot: bytes, *, limits: InspectionLimits) -> bytes: ...
```

PDF preview must call the existing page/resource proof before `get_pixmap`; image
preview must call existing header/frame/pixel proof before decode. Both render at
or below existing 150 DPI/50M pixels/25 MiB bounds and return PNG only.

- [ ] **Step 4: Add bounded worksheet table output**

Use `visit_bounded_worksheet` and create canonical UTF-8 JSON:

```json
{"columns":3,"rows":[["A","B","C"],["1","2","3"]]}
```

No sheet name, formula text, type diagnostic, merged-cell metadata, or workbook
path is included. Enforce 16 MiB JSON and clear temporary private strings.

- [ ] **Step 5: Implement preview dispatch**

Build one O(1) unit map from inspection; resolve the evidence ID and unit index;
snapshot only the corresponding source under its type cap; dispatch by exact unit
kind. Reject unknown IDs before snapshot/parser acquisition.

- [ ] **Step 6: Run Task 3 gates**

Run:

```bash
python3 -m pytest \
  server/ctv_proposal_preview_test.py \
  server/ctv_inspection_media_test.py \
  server/ctv_inspection_workbook_test.py -q
python3 -m pytest server/ctv_proposal_roster_test.py server/ctv_inspection_test.py -q
python3 -m py_compile server/ctv_proposal_preview.py server/ctv_inspection_media.py server/ctv_inspection_workbook.py
git diff --check
```

- [ ] **Step 7: Commit Task 3**

Commit only the six declared files:

```bash
git commit -m "feat(ctv): render bounded local proposal previews"
```

---

### Task 4: Memory-Only Proposal Session State Machine

**Files:**
- Create: `server/ctv_proposal_session.py`
- Create: `server/ctv_proposal_session_test.py`

**Interfaces:**
- Consumes: one live caller-owned observation; `inspect_observation`; roster extraction; previews; Task 1 validation/digest/approval.
- Produces: factory-owned `ProposalSession` capability with fixed methods `review_state()`, `select_roster()`, `set_unit_decision()`, `set_source_disposition()`, `preview()`, `draft()`, `approval_summary()`, `approve()`, `cancel()`, `heartbeat()`, `wait_for_outcome()`, and `close()`; `run_proposal_session(source_root, serve) -> ApprovedProposal | DraftProposal | CancelledProposal`.

- [ ] **Step 1: Write state-machine RED tests**

Cover exact transitions:

```text
created -> reviewing -> summary-ready -> approved -> closed
created/reviewing/summary-ready -> draft -> closed
created/reviewing/summary-ready -> cancelled -> closed
any live state -> failed -> closed
```

Require illegal/replayed/out-of-order actions fail with fixed codes and do not
mutate state. Test approval summary digest becomes stale after every decision,
roster, participant, or observation change. Test approve always rebuilds and
revalidates rather than trusting a cached validation object.

Test exact-once close, close during preview, concurrent action serialization,
capability fabrication/reuse rejection, private state cleanup, idle and total
deadline boundaries with an injected monotonic clock, and no final outcome until
the inventory context exits successfully.

- [ ] **Step 2: Run session RED**

Run the missing session module test and capture exact failure.

- [ ] **Step 3: Implement private factory authority and state**

Use a closure-owned identity registry or a simpler closure-generated capability
whose construction path cannot accept a public token. Avoid equality-based trust.
All state changes occur under one lock. Store only current opaque IDs, local
participant labels, bounded private note, decisions, deadlines, and terminal
outcome. Never store source paths after the observation is opened.

Define exact public-safe exceptions:

```python
class ProposalSessionError(RuntimeError):
    code: Literal[
        "proposal-source-changed", "proposal-roster-unavailable",
        "proposal-session-timeout", "proposal-session-failed",
        "proposal-output-too-large",
    ]
```

Translate outside active exception handlers so private causes/contexts are absent.

- [ ] **Step 4: Implement retained-observation runner**

`run_proposal_session` must:

1. open the one inventory observation context;
2. inspect that observation;
3. create the session;
4. call injected `serve(session)`;
5. stop serving and close session;
6. exit/revalidate the observation context;
7. only then return the terminal public result.

If step 6 fails, discard any approved/draft result and raise
`proposal-source-changed`. A serve/browser/internal failure never returns partial
state.

- [ ] **Step 5: Run Task 4 gates**

Run:

```bash
python3 -m pytest \
  server/ctv_proposal_session_test.py \
  server/ctv_proposal_model_test.py \
  server/ctv_proposal_validator_test.py \
  server/ctv_proposal_roster_test.py \
  server/ctv_proposal_preview_test.py \
  server/ctv_inspection_test.py \
  server/ctv_inventory_test.py -q
python3 -m py_compile server/ctv_proposal_session.py
git diff --check
```

- [ ] **Step 6: Commit Task 4**

Commit only the two Task 4 files:

```bash
git commit -m "feat(ctv): manage ephemeral proposal review sessions"
```

---

### Task 5: Loopback HTTP Boundary and Hybrid Local UI

**Files:**
- Create: `server/ctv_proposal_server.py`
- Create: `server/ctv_proposal_server_test.py`
- Create: `server/ctv_proposal_review_ui.py`
- Create: `server/ctv_proposal_review_ui_test.py`

**Interfaces:**
- Consumes: one live `ProposalSession` capability and injected `webbrowser.open`/clock/token factory for tests.
- Produces: `serve_proposal_review(session, *, browser_open=webbrowser.open, clock=time.monotonic) -> None`; immutable `UI_HTML`, `UI_CSS`, `UI_JS` bytes.

- [ ] **Step 1: Write UI static/privacy RED tests**

Require one dependency-free hybrid screen with left participant/source navigation,
center preview, right decision panel, progress/unresolved counts, draft/cancel,
approval summary/digest, and disabled approval until ready. Static assets contain
no CDN, remote URL, eval, inline event handler, template interpolation, source
path, or PII fixture. JS uses text nodes/`textContent`, never `innerHTML` for data.

- [ ] **Step 2: Run UI RED and implement static bytes**

Create deterministic UTF-8 constants. The CSP will permit only `'self'`; use
separate `/app.css` and `/app.js`, not inline script/style. All API calls use
`credentials: 'same-origin'`, exact JSON, CSRF header on mutations, and fixed
client-side error copy.

- [ ] **Step 3: Write real-loopback server RED tests**

Use real `127.0.0.1` ephemeral sockets and an injected fake session. Cover:

- address family/host/port 0 binding;
- bootstrap one-time token in exact query, token replay failure, redirect to clean
  URL, exact `HttpOnly; SameSite=Strict; Path=/` session cookie;
- exact Host and Origin (`http://127.0.0.1:<actual-port>`) validation;
- cookie required on all private endpoints; CSRF plus same-origin required on
  mutations;
- duplicate JSON key rejection using `object_pairs_hook`, exact object key sets,
  exact primitive types, content type, content length, 1 MiB body cap;
- method/path/query rejection and no arbitrary static/file fallback;
- all security/no-store headers on success and error;
- preview content type/body cap and unit ID validation before session call;
- draft/approval/cancel/heartbeat endpoint-to-session mapping;
- disconnect/broken pipe containment, shutdown on terminal outcome, token cleanup,
  idle/total timeout, and browser-launch false/exception mapping;
- no private token/port/path/body/error values in stdout/stderr/logging.

- [ ] **Step 4: Run server RED**

Run the new server tests and capture missing-module failure.

- [ ] **Step 5: Implement the fixed route table**

Use `ThreadingHTTPServer` only if request serialization is enforced at the session;
otherwise use single-threaded `HTTPServer`. Override default logging to no-op.
Accept only:

```text
GET  /bootstrap?token=<one-time>
GET  /
GET  /app.css
GET  /app.js
GET  /api/state
GET  /api/preview?unitId=<opaque>
POST /api/roster
POST /api/unit-decision
POST /api/source-disposition
POST /api/draft
POST /api/approval-summary
POST /api/approve
POST /api/cancel
POST /api/heartbeat
```

Generate tokens with `secrets.token_urlsafe(32)` and compare with
`hmac.compare_digest`. Set request/socket timeouts. Never reflect request data.
Construct the bootstrap URL only in a short-lived local variable passed to
`browser_open`; never log or return it.

- [ ] **Step 6: Run Task 5 security gates**

Run:

```bash
python3 -m pytest \
  server/ctv_proposal_review_ui_test.py \
  server/ctv_proposal_server_test.py \
  server/ctv_proposal_session_test.py -q
python3 -m py_compile server/ctv_proposal_server.py server/ctv_proposal_review_ui.py
git diff --check
```

- [ ] **Step 7: Commit Task 5**

Commit only the four Task 5 files:

```bash
git commit -m "feat(ctv): serve private local proposal review"
```

---

### Task 6: CLI Integration, Handoff Documentation, and Acceptance

**Files:**
- Modify: `server/ctv_cli_protocol.py`
- Modify: `server/ctv_cli_protocol_test.py`
- Modify: `server/ctv_intake_cli.py`
- Modify: `server/ctv_intake_cli_test.py`
- Modify: `server/README.md`
- Create: `server/ctv_proposal_acceptance_test.py`

**Interfaces:**
- Consumes: `run_proposal_session`, `serve_proposal_review`, all public proposal outcomes/errors, and existing canonical CLI envelope/emitter patterns.
- Produces: exact `proposal review --source-root SOURCE --json` operation `proposal.review`; canonical bounded result/error envelopes; WP-local-tool handoff documentation.

- [ ] **Step 1: Write protocol and argv RED tests**

Add `proposal.review` to the exact operation set, then test the full invalid argv
matrix: missing/reordered/duplicated/abbreviated/empty/option-like source/extra
tokens. Require no stdout and fixed stderr for invalid invocation. Test lazy imports
so proposal/server/browser modules do not load for version/doctor/contract/
inventory/inspect or invalid argv.

- [ ] **Step 2: Run CLI RED**

Run the new exact CLI selection and confirm failures occur because the operation is
not integrated.

- [ ] **Step 3: Implement CLI dispatch and bounded emitter**

Add a dedicated `_is_proposal_review_argv`, parser branch, lazy result wrapper,
fixed error allowlist, and emitter capped at 16 MiB. Map:

```text
approved/draft/cancelled -> succeeded, exit 0
controlled proposal/inspection/inventory failure -> failed, exit 2
invalid invocation -> empty stdout/fixed stderr, exit 1
unexpected BaseException/GeneratorExit/SystemExit from delegated boundary -> fixed internal failed envelope, exit 1
```

Buffer exactly once and emit only after `run_proposal_session` has returned from
final observation revalidation. Never serialize private session state or raw
exceptions.

- [ ] **Step 4: Write acceptance RED tests**

Build generated synthetic roster/PDF/image sources. Inject a deterministic server
driver that performs the same session calls as the HTTP layer, then assert:

- approved canonical JSON uses opaque handles/fixed codes only;
- draft and cancelled shapes leak no assignments;
- mutation during review and immediately before/after approval fails without
  stdout partial proposal;
- source tree content/metadata hash is unchanged;
- no application/temp/cache/output files appear;
- deterministic repeated unchanged runs produce identical result apart from
  observation-scoped values that the existing observation contract defines;
- no external socket, arbitrary subprocess, or file write occurs;
- all legacy commands remain byte-for-byte compatible where specified.

- [ ] **Step 5: Run focused integration GREEN**

Run:

```bash
python3 -m pytest \
  server/ctv_cli_protocol_test.py \
  server/ctv_intake_cli_test.py \
  server/ctv_proposal_acceptance_test.py \
  server/ctv_proposal_model_test.py \
  server/ctv_proposal_validator_test.py \
  server/ctv_proposal_roster_test.py \
  server/ctv_proposal_preview_test.py \
  server/ctv_proposal_session_test.py \
  server/ctv_proposal_server_test.py \
  server/ctv_proposal_review_ui_test.py -q
```

- [ ] **Step 6: Document the WP handoff and boundaries**

Add the exact preflight/command sequence, local-browser behavior, outcomes/exits,
privacy-safe result meaning, two-hour/five-minute limits, retry-from-fresh behavior,
and explicit statement that no package is prepared and no payment is approved.
State that WP invokes the local script; no CTV logic is bundled into WP.

- [ ] **Step 7: Run full acceptance**

Run fresh on the exact head:

```bash
python3 -m pytest -q
npm test -- --run
npm run build
python3 -m py_compile server/ctv_*.py
git diff --check
git status --short --untracked-files=all
```

Also run scoped static/privacy scans confirming no new dependency/lockfile,
contract snapshot, frontend product code, WP code, output writer, network client,
PII marker, placeholder, or non-declared file change.

- [ ] **Step 8: Generated browser smoke**

Run the real loopback server against generated synthetic inputs, open the local
screen, exercise roster selection, one individual assignment, one shared/case or
exclusion, summary, and approval. Verify security headers, clean bootstrap URL,
server shutdown, canonical stdout, zero console errors, and byte-for-byte unchanged
source tree. Record sanitized counts/statuses only.

- [ ] **Step 9: Commit Task 6**

Stage only the six declared files and commit:

```bash
git commit -m "feat(ctv): expose local proposal review workflow"
```

---

## Final review and integration boundary

After all six tasks have task-scoped independent approval:

1. run one independent whole-branch security/correctness review against this plan
   and the approved spec;
2. allow one final fix wave and one scoped re-review under the
   subagent-driven-development protocol;
3. record any residual ruling with reason and cost if wrong;
4. rerun full Python/frontend/build/privacy/no-write/generated-browser gates on the
   exact final head;
5. present local merge / push-and-PR / keep-as-is options to the user.

Do not merge, push, release, prepare a package, or clean the worktree without the
user's explicit choice.

