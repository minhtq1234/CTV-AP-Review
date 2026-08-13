# CTV Safe Document Inspection Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an exact, read-only `inspect` CLI command that securely re-inventories a selected folder and returns deterministic page-, worksheet-, and image-level role proposals using bounded local parsing and OCR without exposing source content.

**Architecture:** Extend the immutable CLI/result protocol first, implement a pure signal/classification core, then add a direct-stdin local OCR adapter and optional doctor capability. Refactor inventory behind a retained descriptor-bound observation context, build bounded PDF/image and workbook adapters over immutable byte snapshots, compose them in one inspection orchestrator, and finally expose the exact CLI plus operator documentation.

**Tech Stack:** Python 3.10+; standard library; existing PyMuPDF (`fitz`), OpenPyXL, Pillow, and local Tesseract executable; frozen dataclasses; descriptor-relative POSIX file APIs; pytest; existing Vitest/Vite gates.

**Spec:** `docs/superpowers/specs/2026-08-13-ctv-safe-document-inspection-design.md`

## Global Constraints

- Execute in a new isolated worktree from the committed `ver1` head that contains the approved spec and this plan. Use branch `codex/ctv-safe-document-inspection`; do not implement in the active `ver1` checkout.
- Do not push, merge, release, deploy, modify WP, or clean unrelated worktrees without separate authorization. Preserve active-checkout `.DS_Store` and `.superpowers/` paths.
- Add no dependency and do not modify `package.json`, `package-lock.json`, or `contracts/ctv-intake/v1/`.
- The exact new CLI form is `inspect --source-root <path> --json`. Existing `version`, `doctor`, `contract verify`, and `inventory` forms and semantics remain compatible.
- Each call performs a fresh inventory and one descriptor-bound observation. It accepts no earlier inventory JSON, evidence ID, filename, relative path, or persisted state.
- PDF pages, worksheets, and standalone images are separate one-based units. ZIP/RAR archives remain opaque and their members are never listed, parsed, decompressed, or extracted.
- Use only the fixed roles, confidence bands, signal rules, precedence, issue semantics, and review rules in the approved spec. `unknown` is always valid; no model or probabilistic classifier participates.
- Raw paths, filenames, sheet names, runtime-derived document/OCR/cell content, extracted values, PII, parser messages, raw exceptions, commands, usernames, and repository paths never enter public JSON, controlled stderr, routine logs, committed artifacts, or model context. Tests may contain only deliberately generated synthetic literals needed to exercise classification rules.
- Inspection is read-only and stateless. It creates no report, cache, temporary document, thumbnail, extracted-text file, lock, working state, or derived output. Python bytecode remains disabled before local imports.
- Source access is component-by-component, no-follow, descriptor-relative, nonblocking before regular-file proof, snapshot-based, mutation-aware, and fail-closed. Parsers receive bounded in-memory bytes and never reopen a source pathname.
- Local Tesseract is invoked directly without a shell using image bytes on stdin and TSV on stdout. Do not use `pytesseract`, Python temporary files, input/output filenames, or network access.
- Hard limits are exact: PDF 256 MiB and 10,000 pages; embedded text 64 KiB/page; workbook 25 MiB, 100 sheets, 100,000 examined cells, 256 characters/cell; image 25 MiB and 50 megapixels; OCR 500 units, 30 seconds/unit, 30 minutes/command; 10,000 public units; 16 MiB canonical CLI envelope. Caller-injected test limits cannot relax these ceilings.
- An individual known unit may become `unknown` with an issue when acquisition fails. A boundary preventing complete source/unit enumeration fails the operation; never return a truncated result as complete.
- Tests and acceptance use generated synthetic documents only. No real CTV/AP folder, name, identity, bank, tax, amount, date, document image, or extracted text is committed.

---

## File map

| File | Responsibility |
|---|---|
| `server/ctv_cli_protocol.py` | Permit the stable `inspect` operation. |
| `server/ctv_cli_protocol_test.py` | Preserve canonical envelope behavior with inspect. |
| `server/ctv_inspection_model.py` | Frozen limits, source/unit/result types, validation, defensive serialization. |
| `server/ctv_inspection_model_test.py` | Exact shapes, domains, invariants, privacy, ordering, limits. |
| `server/ctv_inspection_classifier.py` | Private text-to-signal reduction and pure deterministic role/confidence rules. |
| `server/ctv_inspection_classifier_test.py` | Exact role table, conflicts, confidence, accent handling, privacy. |
| `server/ctv_local_ocr.py` | Fixed Tesseract capability probe, sequential budget, stdin/stdout OCR, safe outcomes. |
| `server/ctv_local_ocr_test.py` | Command, timeout, budget, TSV, no-temp, and privacy tests. |
| `server/ctv_cli_doctor.py` | Report optional local OCR capability without making structural inspection unavailable. |
| `server/ctv_cli_doctor_test.py` | OCR capability and legacy readiness tests. |
| `server/ctv_inventory.py` | Retained descriptor-bound inventory observation and immutable source snapshots. |
| `server/ctv_inventory_test.py` | Observation binding, snapshot, final revalidation, mutation, FD, and legacy tests. |
| `server/ctv_inspection_media.py` | Bounded in-memory PDF page and standalone-image inspection. |
| `server/ctv_inspection_media_test.py` | PDF/image structure, OCR fallback, corrupt/encrypted/limit/privacy tests. |
| `server/ctv_inspection_workbook.py` | OOXML preflight and bounded worksheet structure/text inspection. |
| `server/ctv_inspection_workbook_test.py` | Sheet visibility, roster/supporting signals, ZIP bomb, corrupt/encrypted tests. |
| `server/ctv_inspection.py` | Fresh inventory composition, adapter dispatch, observation ID, totals, final result. |
| `server/ctv_inspection_test.py` | End-to-end engine determinism, accounting, races, no-write, opacity, privacy. |
| `server/ctv_intake_cli.py` | Exact inspect argv, dispatch, stable error allowlist, output guard. |
| `server/ctv_intake_cli_test.py` | Subprocess behavior, relocation, invalid surface, errors, output, leak/static gates. |
| `server/README.md` | Inspect preflight, command, result, limits, uncertainty, completion boundary. |

---

### Task 1: Immutable inspection protocol and result model

**Files:**

- Modify: `server/ctv_cli_protocol.py`
- Modify: `server/ctv_cli_protocol_test.py`
- Create: `server/ctv_inspection_model.py`
- Create: `server/ctv_inspection_model_test.py`

**Interfaces:**

- Consumes: existing `CliEnvelope`, `canonical_json_bytes`, inventory opaque IDs, and the approved inspection spec.
- Produces:
  - `InspectionLimits` and `DEFAULT_INSPECTION_LIMITS` with every exact hard ceiling;
  - literals `UnitKind`, `SuggestedRole`, `ConfidenceBand`, `InspectionMethod`, `SourceInspectionStatus`;
  - `InspectionSource(evidence_id, detected_type, inspection_status, unit_count, issue_codes)`;
  - `InspectionUnit(unit_id, evidence_id, unit_kind, unit_index, suggested_role, confidence_band, needs_user_review, inspection_method, signal_codes, issue_codes)`;
  - `InspectionTotals(sources, units, classified, unknown, needs_user_review, issues)`;
  - `InspectionResult(inspection_version, inspection_status, observation_id, totals, sources, units)` and `to_dict()`;
  - internal immutable `InspectionUnitEvidence(unit_kind, unit_index, inspection_method, signal_codes, issue_codes)` and `InspectionAdapterResult(inspection_status, unit_count, source_issue_codes, units)` values used by later adapters/orchestrator;
  - exact ordered tuples `SIGNAL_ORDER` and `INSPECTION_ISSUE_ORDER`.

- [ ] **Step 1: Create isolated execution workspace and record baseline**

From the active checkout, resolve and record:

```bash
git status --short --branch
git rev-parse ver1^{commit}
git merge-base --is-ancestor 857f85a ver1
git diff --exit-code ver1 -- \
  docs/superpowers/specs/2026-08-13-ctv-safe-document-inspection-design.md \
  docs/superpowers/plans/2026-08-13-ctv-safe-document-inspection.md
```

Create `/Users/lap16603/Documents/New project/work/CTV_APReview-inspection` on
`codex/ctv-safe-document-inspection` from that exact SHA. Initialize this plan's
SDD workspace and ledger. In the new worktree run:

```bash
python3 -m pytest -q
npm ci
npm test
npm run build
git status --short --branch
```

Expected baseline: Python `640 passed` with only six existing dependency warnings,
frontend `130 passed`, build exit `0`, and no tracked setup change. Stop without
production edits if the baseline is not green.

- [ ] **Step 2: Write protocol/model RED tests**

Add the inspect operation test:

```python
def test_inspect_is_a_supported_canonical_operation():
    envelope = succeeded(
        "inspect",
        "Inspection completed",
        {"inspectionVersion": "1.0", "sources": [], "units": []},
    )
    payload = json.loads(canonical_json_bytes(envelope))
    assert payload["operation"] == "inspect"
    assert payload["status"] == "succeeded"
```

Create model tests with a canonical source/unit fixture:

```python
def _unit(**overrides):
    values = dict(
        unit_id="unit-0001",
        evidence_id="evidence-0001",
        unit_kind="pdf-page",
        unit_index=1,
        suggested_role="service-contract",
        confidence_band="high",
        needs_user_review=False,
        inspection_method="embedded-text",
        signal_codes=(
            "service-contract-heading",
            "party-section-present",
            "signature-section-present",
        ),
        issue_codes=(),
    )
    values.update(overrides)
    return InspectionUnit(**values)


def test_result_serializes_exact_private_shape():
    source = InspectionSource(
        evidence_id="evidence-0001",
        detected_type="pdf",
        inspection_status="inspected",
        unit_count=1,
        issue_codes=(),
    )
    unit = _unit()
    result = InspectionResult(
        inspection_version="1.0",
        inspection_status="complete",
        observation_id="observation-" + "a" * 64,
        totals=InspectionTotals(
            sources=1, units=1, classified=1, unknown=0,
            needs_user_review=0, issues=0,
        ),
        sources=(source,),
        units=(unit,),
    )
    payload = result.to_dict()
    assert set(payload) == {
        "inspectionVersion", "inspectionStatus", "observationId",
        "totals", "sources", "units",
    }
    assert "/" not in json.dumps(payload)
```

Add parameterized failures for every invalid literal, unsafe/malformed opaque ID,
zero/out-of-range unit index, role forbidden for its unit kind, `unknown` without
`none`, non-unknown with `none`, inconsistent review Boolean, unordered/duplicate/
unknown signals and issues, invalid source unit count/status combinations, totals
mismatch, status/issue mismatch, mutable caller containers, more than 10,000 units,
and any limit above its hard ceiling.

- [ ] **Step 3: Capture RED**

```bash
cd server
python3 -m pytest ctv_cli_protocol_test.py ctv_inspection_model_test.py -q
```

Expected: model collection fails with `ModuleNotFoundError`, and the protocol case
would reject `inspect` before the allowlist edit.

- [ ] **Step 4: Implement the model and protocol extension**

Change only the protocol operation set to include `inspect`. Implement frozen
dataclasses with deep defensive serialization. Use the spec's exact role/unit/
method/source-status domains and exact limits.

Define `SIGNAL_ORDER` in the order listed in spec sections 8 and 8.1. Define
`INSPECTION_ISSUE_ORDER` as inventory `ISSUE_ORDER` followed by:

```python
(
    "opaque-archive", "unsupported-document-type", "document-unreadable",
    "document-encrypted", "document-over-limit", "unit-over-limit",
    "embedded-media-present", "worksheet-hidden", "multi-frame-image",
    "ocr-unavailable", "ocr-timeout", "ocr-failed", "ocr-low-confidence",
    "classification-ambiguous", "classification-conflict",
)
```

`needs_user_review` must be true for every non-high band, `unknown`, or nonempty
issue tuple. Totals are derived/validated against final records. Source issue counts
and unit issue counts both contribute to `totals.issues`.

`InspectionUnitEvidence` is acquisition-only: it contains fixed signals/issues and
never private text. `InspectionAdapterResult.units` is an immutable tuple of those
values. Validate `unitCount` against the tuple for `inspected`; permit `None` only
for statuses whose authoritative unit count cannot be established.

Implement explicit `to_dict()` builders for public records; do not use
`dataclasses.asdict`. Mark every private-byte/text/session helper field with
`repr=False`, make its `__str__` fixed and safe, and test exception chaining is
suppressed at every public boundary.

- [ ] **Step 5: Run GREEN and compatibility gates**

```bash
cd server
python3 -m pytest ctv_cli_protocol_test.py ctv_inspection_model_test.py -q
python3 -m pytest \
  ctv_cli_protocol_test.py ctv_inventory_model_test.py \
  ctv_contract_pin_test.py ctv_intake_cli_test.py -q
python3 -m py_compile ctv_inspection_model.py
```

- [ ] **Step 6: Commit Task 1**

Stage exactly the four Task 1 files, run `git diff --cached --check`, inspect the
cached name list, and commit:

```bash
git commit -m "feat(ctv): define inspection result protocol"
```

---

### Task 2: Deterministic signal and classification core

**Files:**

- Create: `server/ctv_inspection_classifier.py`
- Create: `server/ctv_inspection_classifier_test.py`

**Interfaces:**

- Consumes: `UnitKind`, `SuggestedRole`, `ConfidenceBand`, `SIGNAL_ORDER`.
- Produces:
  - `TextSignalContext(unit_kind, mostly_image, embedded_media, worksheet_hidden, row_pattern)`;
  - `signals_from_private_text(text: str, context: TextSignalContext) -> tuple[str, ...]`;
  - `Classification(suggested_role, confidence_band, needs_user_review, issue_codes)`;
  - `classify(unit_kind, inspection_method, signal_codes, acquisition_issue_codes) -> Classification`.

- [ ] **Step 1: Write the exact rule-table RED matrix**

Create parameterized tests covering every row from spec 8.1. Representative cases:

```python
@pytest.mark.parametrize(
    ("kind", "signals", "role", "band"),
    [
        ("worksheet", ("roster-column-pattern", "roster-row-pattern"),
         "payment-roster", "high"),
        ("pdf-page", ("service-contract-heading", "party-section-present",
                      "signature-section-present"),
         "service-contract", "high"),
        ("pdf-page", ("acceptance-heading", "signature-section-present"),
         "acceptance-record", "medium"),
        ("image", ("identity-front-heading", "identity-front-layout"),
         "identity-front", "medium"),
        ("image", ("identity-back-layout", "identity-issue-section-present"),
         "identity-back", "high"),
    ],
)
def test_exact_role_table(kind, signals, role, band):
    result = classify(kind, "embedded-text", signals, ())
    assert (result.suggested_role, result.confidence_band) == (role, band)
```

Add exact conflict tests: high/high, high/medium, medium/medium become
`unknown`/`none` with `classification-conflict`; low/low becomes ambiguous;
no candidate becomes ambiguous. Verify unit-kind role restrictions, hidden sheet,
OCR unavailable/failure/timeout/low confidence review behavior, and deterministic
signal ordering independent of input order.

For text reduction use synthetic Vietnamese headings and decoy values. Assert
accent/case/spacing normalization recognizes fixed phrases but no returned signal or
exception contains any input substring, identity-like digits, date, amount, name,
or raw text.

Add an exhaustive table test that derives the allowed-role set from unit kind:
PDF pages permit the full taxonomy; worksheets permit only `payment-roster`,
`other-supporting-evidence`, and `unknown`; standalone images permit only identity,
shared/other supporting, and `unknown` roles.

- [ ] **Step 2: Capture RED**

```bash
cd server
python3 -m pytest ctv_inspection_classifier_test.py -q
```

Expected: missing-module collection failure.

- [ ] **Step 3: Implement private text reduction and pure rules**

Use Unicode NFD normalization, Vietnamese `đ` normalization, whitespace collapse,
and fixed phrase/token groups only. Keep the normalized string inside this function
and overwrite local references after emitting signals. The fixed lexicon includes synthetic-safe
Vietnamese concepts for service contract, parties, scope, signatures, acceptance,
period, payment request, tax form, roster columns/rows, identity front/back, issue
authority, case-level/shared evidence, and supporting-document headings.

Never retain a match object or matched value in a returned value. Pattern signals
such as identity-number presence return only the signal code. Apply spec 8.2 without
tie-breaking precedence.

- [ ] **Step 4: Run GREEN and privacy/static gates**

```bash
cd server
python3 -m pytest ctv_inspection_classifier_test.py ctv_inspection_model_test.py -q
python3 -m py_compile ctv_inspection_classifier.py
```

Parse the module AST and require imports to be a subset of
`{"dataclasses", "re", "unicodedata", "ctv_inspection_model"}`.

- [ ] **Step 5: Commit Task 2**

Commit exactly classifier and test:

```bash
git commit -m "feat(ctv): classify private document signals"
```

---

### Task 3: Direct local OCR and optional doctor capability

**Files:**

- Create: `server/ctv_local_ocr.py`
- Create: `server/ctv_local_ocr_test.py`
- Modify: `server/ctv_cli_doctor.py`
- Modify: `server/ctv_cli_doctor_test.py`

**Interfaces:**

- Produces:
  - `OcrCapability(available: bool, language: Literal["vie"] | None)`;
  - private-path-safe `LocalOcrSession` created once per inspect call, with a
    sanitized `repr`, public `capability`, and no executable-path accessor;
  - `open_local_ocr(...) -> LocalOcrSession` with injected executable lookup/process factory;
  - `probe_local_ocr(...) -> OcrCapability` with injected executable lookup/runner;
  - `OcrBudget(max_units=500, max_total_seconds=1800, used_units=0, started_at=...)`;
  - `OcrOutcome(status: Literal["succeeded", "unavailable", "timeout", "failed", "low-confidence", "over-limit"], private_text: str)`;
  - `run_local_ocr(image_bytes: bytes, *, session, budget, timeout_seconds=30, ...) -> OcrOutcome`;
  - `DoctorResult.local_ocr: OcrCapability`; Task 8 exposes it as public
    `localOcr: {available: bool, language: "vie" | null}`.

- [ ] **Step 1: Write OCR RED tests**

Tests must prove the exact command (executable path is private and never returned):

```python
assert argv == [
    executable, "stdin", "stdout", "-l", "vie", "--psm", "6", "tsv"
]
assert input_bytes == synthetic_png
assert timeout == 30
assert shell is False
```

Inject a bounded-process runner/clock rather than invoking a real executable. The
runner contract must demonstrate `stdin=PIPE`, `stdout=PIPE`, `stderr=DEVNULL`,
`shell=False`, `close_fds=True`, `cwd=os.path.abspath(os.sep)`, one bounded writer,
selector-driven nonblocking stdout reads, and kill/wait cleanup when timeout or the
output cap is crossed.

Use an injected runner result with synthetic TSV. Require text assembly from only
nonempty tokens with confidence `>= 0`, low-confidence status when the mean of
usable nonnegative confidences is below `70`, `succeeded` otherwise, and an empty
private string for unavailable/timeout/failed/over-limit. Test malformed TSV,
stderr containing private values, timeout exception, missing executable, unit 501,
total deadline,
non-PNG/empty input, and input/output caps.

Monkeypatch `tempfile`, `open`, `Path.write_*`, and shell-capable calls to fail.
Assert the runner receives bytes only on stdin and no path argument derived from a
source.

Doctor tests require missing OCR to leave existing `ready` unchanged while
`localOcr.available` is false; a fixed `vie` capability becomes true; no executable
path/version/list output is serialized.

- [ ] **Step 2: Capture RED**

```bash
cd server
python3 -m pytest ctv_local_ocr_test.py ctv_cli_doctor_test.py -q
```

- [ ] **Step 3: Implement capability probe and OCR runner**

Use `shutil.which("tesseract")` privately once when opening a session. Probe with fixed no-shell commands
`[exe, "--version"]` and `[exe, "--list-langs"]`, each bounded to five seconds and
64 KiB stdout while stderr is discarded. Capability is true only when both exit `0` and the language
list contains exact `vie`.

Implement one private `_run_bounded_process` using `subprocess.Popen` directly,
never a shell. Feed the already-bounded input through a dedicated writer while the
calling thread incrementally reads stdout up to `output_limit + 1`; route stderr to
`DEVNULL`. Use `selectors.DefaultSelector` plus monotonic deadlines so a silent
child cannot defeat the timeout; kill then wait on timeout/cap/error, join the
writer, unregister descriptors, and close every pipe on all paths. The helper
returns a frozen safe outcome whose output bytes are private and never represented
in `repr`/`str`; test process details through an injected private recorder rather
than returning argv or executable path. Resolve the executable before constructing the process, then
pass an exact environment of
`{"PATH": os.defpath, "LANG": "C", "LC_ALL": "C"}` so caller-controlled
Tesseract debug/output/configuration variables are not inherited. The capability
probe and OCR invocation use the same environment. Cap PNG input at 25 MiB and TSV
stdout at 4 MiB; probe stdout is capped at 64 KiB. Never include stdout in an
exception, and never collect stderr.

The orchestrator opens one session and passes that same bound session to every OCR
call. The budget reserves one unit before invoking the process and charges elapsed
monotonic time on every invoked outcome. A missing runtime does not reserve an OCR
unit. An exhausted unit or total-clock budget returns `over-limit` without spawning
a process; the owning adapter maps that to `unit-over-limit`.

Extend `DoctorResult` with the capability object while preserving existing
readiness and issue semantics. `checked` gains stable `local-ocr`; missing OCR is
not a doctor error because structure-only inspection remains available. Do not
change CLI serialization in this task; Task 8 adds the final `localOcr` JSON field
when the complete inspect surface is integrated.

- [ ] **Step 4: Run GREEN and compatibility gates**

```bash
cd server
python3 -m pytest ctv_local_ocr_test.py ctv_cli_doctor_test.py ctv_intake_cli_test.py -q
python3 -m py_compile ctv_local_ocr.py ctv_cli_doctor.py
```

AST gate: `ctv_local_ocr.py` may import `subprocess`, `selectors`, and `threading`;
no other new inspection module and no CLI module may import them. `pytesseract` and
`tempfile` are forbidden.

- [ ] **Step 5: Commit Task 3**

```bash
git commit -m "feat(ctv): probe and run bounded local OCR"
```

---

### Task 4: Retained secure inventory observation and snapshots

**Files:**

- Modify: `server/ctv_inventory.py`
- Modify: `server/ctv_inventory_test.py`

**Interfaces:**

- Produces:
  - frozen safe `ObservedInventorySource(evidence_id, extension, detected_type, size, hash_status, issue_codes)`;
  - `open_inventory_observation(source_root: Path, *, limits=DEFAULT_LIMITS)` context manager;
  - yielded `InventoryObservation` with read-only properties `result`, `observation_id`, `sources` and method `snapshot(evidence_id: str, *, max_bytes: int) -> bytes`;
  - normal context exit performs the final descriptor-bound root/tree revalidation; controlled mutation raises existing `InventoryError("inventory-tree-changed")`.

- [ ] **Step 1: Write observation RED tests**

Cover:

```python
with open_inventory_observation(source, limits=_small_limits()) as observation:
    assert observation.result.to_dict() == inventory_source(source, limits=_small_limits()).to_dict()
    assert [s.evidence_id for s in observation.sources] == ["evidence-0001"]
    assert observation.snapshot("evidence-0001", max_bytes=1024) == content
    first_id = observation.observation_id

with open_inventory_observation(source, limits=_small_limits()) as again:
    assert again.observation_id == first_id
```

Add tests for unknown/forged evidence ID, non-regular item, max-byte breach before
read, read failure, short read, identity/size/time mutation, source replacement,
mutation during final context exit, double close, use after close, exception inside
the context, no path/name/bytes in public errors, and FD leak counts.

Prove observation ID changes for rename, metadata/content mutation (including same
size), entry addition/removal, and directory substitution. It is a full
`observation-` plus 64 lowercase hex characters. Compute its digest from a
domain-separated encoding of the complete private authoritative observation,
including private relative-path bytes and device/inode/mode/size/mtime/ctime. Only
the digest is public; raw path bytes and private sort keys are never serialized.

- [ ] **Step 2: Capture RED without editing inventory production code**

```bash
cd server
python3 -m pytest ctv_inventory_test.py -q -k 'observation or snapshot'
```

Expected: import/name failures for the new interface.

- [ ] **Step 3: Refactor inventory behind the observation context**

Retain the root descriptor and authoritative `_EntryFact` sequence after existing
inventory processing. Build the public inventory result and safe observed-source
tuple once. Keep evidence-to-fact mapping private.

`snapshot()` reopens the source descriptor-relatively from the retained root,
requires the exact enumerated directory chain and final regular identity, checks
the caller max before reading, reads exactly the declared size into a bounded byte
array, and requires stable metadata after read. It never returns partial bytes.

Refactor existing `inventory_source()` to use the same context internally and
return the same result. Do not duplicate traversal or revalidation logic.

- [ ] **Step 4: Run security GREEN and complete legacy inventory suite**

```bash
cd server
python3 -m pytest ctv_inventory_test.py -q
python3 -m pytest \
  ctv_inventory_model_test.py ctv_inventory_detection_test.py \
  ctv_inventory_test.py ctv_intake_cli_test.py -q
python3 -m py_compile ctv_inventory.py
```

Run FD-count, no-write, parser-opacity, pathname-fallback, race, privacy, and exact
byte-identical legacy inventory tests fresh.

- [ ] **Step 5: Commit Task 4**

```bash
git commit -m "refactor(ctv): retain secure inventory observations"
```

---

### Task 5: Bounded PDF and standalone-image adapters

**Files:**

- Create: `server/ctv_inspection_media.py`
- Create: `server/ctv_inspection_media_test.py`

**Interfaces:**

- Consumes: immutable source bytes, `InspectionLimits`, `OcrBudget`,
  `run_local_ocr`, `signals_from_private_text`, `InspectionUnitEvidence`, and
  `InspectionAdapterResult`.
- Produces:
  - `inspect_pdf(snapshot: bytes, *, limits, ocr_budget, ocr_runner) -> InspectionAdapterResult`;
  - `inspect_image(snapshot: bytes, *, limits, ocr_budget, ocr_runner) -> InspectionAdapterResult`.

- [ ] **Step 1: Generate media RED fixtures in memory**

Use PyMuPDF to generate synthetic PDFs and Pillow/BytesIO to generate images. Do
not check binaries into Git. Tests cover:

- embedded-text service-contract and acceptance pages;
- scanned pages that invoke OCR exactly once;
- embedded text at/over 64 KiB;
- mixed-role multipage order and 10,001-page declared boundary via monkeypatch;
- encrypted/corrupt/empty PDFs;
- page render failure, OCR unavailable/timeout/failure/low confidence;
- 25 MiB image size and 50-megapixel area boundaries;
- identity-front/back, ambiguous, corrupt, and multi-frame images;
- no raw text, identity-like digits, amounts, dates, image bytes, dimensions, parser
  messages, or exception text in `InspectionAdapterResult`/errors; and
- no filesystem/temp/network calls.

- [ ] **Step 2: Capture RED**

```bash
cd server
python3 -m pytest ctv_inspection_media_test.py -q
```

- [ ] **Step 3: Implement PDF inspection**

Open only with `fitz.open(stream=snapshot, filetype="pdf")`. Encrypted PDFs return
source status `encrypted`, `unit_count=None`, and `document-encrypted`. Corrupt PDFs
return `unreadable`. More than 10,000 pages raises a stable adapter boundary error
that the orchestrator maps to controlled operation failure because complete unit
enumeration is prohibited.

For each page, acquire embedded text and examine at most 64 KiB. Treat text as
sufficient when it has at least 40 non-whitespace characters and at least four
alphabetic tokens. Otherwise render at 150 DPI to in-memory PNG, verify rendered
area `<= 50_000_000`, and call OCR. Discard private text immediately after signal
reduction. Unit indexes exactly follow source page numbers.

- [ ] **Step 4: Implement image inspection**

Use `PIL.Image.open(BytesIO(snapshot))`, catch Pillow decompression-bomb warnings
and errors, verify width × height before pixel loading, and normalize the first
frame to an in-memory RGB PNG. Do not mutate process-global
`Image.MAX_IMAGE_PIXELS`. Multiple frames add `multi-frame-image` and force review
but do not create hidden units. Invoke OCR subject to the shared budget. Never call
`Image.open` with a path.

- [ ] **Step 5: Run GREEN and opacity gates**

```bash
cd server
python3 -m pytest \
  ctv_inspection_media_test.py ctv_local_ocr_test.py \
  ctv_inspection_classifier_test.py -q
python3 -m py_compile ctv_inspection_media.py
```

AST gate permits `fitz`, `PIL`, `io`, and project modules; forbids `openpyxl`,
archive modules, `pytesseract`, `tempfile`, network, and direct subprocess use.

- [ ] **Step 6: Commit Task 5**

```bash
git commit -m "feat(ctv): inspect PDF pages and images safely"
```

---

### Task 6: Bounded workbook adapter

**Files:**

- Create: `server/ctv_inspection_workbook.py`
- Create: `server/ctv_inspection_workbook_test.py`

**Interfaces:**

- Consumes: immutable workbook bytes, `InspectionLimits`, classifier signal helper,
  `InspectionUnitEvidence`, and `InspectionAdapterResult`.
- Produces:
  - `inspect_workbook(snapshot: bytes, *, limits) -> InspectionAdapterResult`.

- [ ] **Step 1: Write generated workbook RED tests**

Use OpenPyXL/BytesIO to generate:

- high/medium roster-like sheets and supporting sheets;
- visible, hidden, and very-hidden sheet ordering;
- formulas, dates, amounts, identity-like values, Unicode/space sheet names, and
  embedded synthetic image presence without output leaks;
- 100/101 sheets, 100,000-cell budget exhaustion, 256/257-character cells;
- workbook size boundary through injected limits;
- corrupt, encrypted-like, macro extension, external-link-like, and malformed OOXML;
- ZIP entry count, uncompressed total, and compression ratio adversaries; and
- no member name, sheet name, cell value, formula, parser error, or raw bytes in
  public drafts/errors.

- [ ] **Step 2: Capture RED**

```bash
cd server
python3 -m pytest ctv_inspection_workbook_test.py -q
```

- [ ] **Step 3: Implement OOXML preflight and worksheet inspection**

Before OpenPyXL, inspect the in-memory ZIP central directory only to prove an OOXML
workbook container. Require `[Content_Types].xml` and `xl/workbook.xml`; cap at
10,000 ZIP entries, 100 MiB aggregate declared uncompressed bytes, 25 MiB per
member, and 100:1 declared compression ratio. Never return member names and never
extract a member to disk.

Read only the bounded workbook, workbook-relationship, worksheet, and
worksheet-relationship XML members needed to map each worksheet to the presence of
a drawing relationship. Reject DTD/entity declarations before standard-library
pull parsing, count decompressed member bytes against the same aggregate
budget, and emit only `embedded-media-present`; never retain a member name,
relationship target, or drawing metadata. Do not read image members.

Load with `openpyxl.load_workbook(BytesIO(snapshot), read_only=True,
data_only=False, keep_links=False)`. Reject more than 100 worksheets as an
operation boundary. Iterate in workbook order and stop private cell examination at
100,000 total. A sheet that cannot be fully sampled inside the acquisition budget
remains a known unit with `unit-over-limit`, `unknown`, and review required; unit
enumeration remains complete.

Examine at most 256 characters per scalar cell, reduce immediately to fixed signals,
and discard values. Worksheet index is one-based; sheet name is never returned.

- [ ] **Step 4: Run GREEN and archive-opacity gates**

```bash
cd server
python3 -m pytest \
  ctv_inspection_workbook_test.py ctv_inspection_classifier_test.py -q
python3 -m py_compile ctv_inspection_workbook.py
```

AST permits `zipfile` only in this workbook adapter. Tests poison extraction APIs,
`ZipFile.extract*`, filesystem writes, network, OCR, and arbitrary archive handling.

- [ ] **Step 5: Commit Task 6**

```bash
git commit -m "feat(ctv): inspect workbook sheets safely"
```

---

### Task 7: Secure inspection orchestrator

**Files:**

- Create: `server/ctv_inspection.py`
- Create: `server/ctv_inspection_test.py`

**Interfaces:**

- Consumes: `open_inventory_observation`, inventory safe source metadata,
  inspection limits/model, classifier, OCR budget, PDF/image/workbook adapters.
- Produces:
  - `InspectionError(code: str)` whose public string is exactly its stable code;
  - `inspect_source(source_root: Path, *, limits=DEFAULT_INSPECTION_LIMITS) -> InspectionResult`.

- [ ] **Step 1: Write synthetic end-to-end RED tests**

Build one source folder containing generated mixed PDF, roster-like workbook,
standalone identity-like image, opaque ZIP/RAR bytes, unsupported file, duplicate,
and special/symlink entries. Assert:

- one source record per inventory item in evidence order;
- one unit per PDF page, worksheet, and standalone image;
- unit IDs in evidence order then unit index;
- archives have no units and `opaque-archive`;
- exact totals/status/review counts;
- byte-identical `to_dict()` and canonical JSON on unchanged calls;
- observation/evidence IDs change after a safe folder mutation;
- no source path/name/sheet name/raw content/identity/date/amount/member appears;
- source status for corrupt/encrypted/over-limit/unsupported evidence;
- OCR budget allocation is deterministic and sequential;
- tree/file mutation during adapter work and final observation exit becomes
  `inspection-tree-changed` with no partial result;
- more than 10,000 units and adapter enumeration boundaries fail closed;
- injected limits cannot relax any hard ceiling; and
- all stable errors contain only allowlisted kebab-case codes.

Add no-write tests snapshotting names, bytes, modes, and mtimes before/after success
and controlled failure. Poison write flags, mkdir/rename/replace/unlink, tempfile,
network, shell, and archive extraction. Access time remains excluded.

- [ ] **Step 2: Capture RED**

```bash
cd server
python3 -m pytest ctv_inspection_test.py -q
```

- [ ] **Step 3: Implement source dispatch and bounded composition**

Before entering `open_inventory_observation`, open one `LocalOcrSession`; then,
inside the observation:

1. create one `OcrBudget` and reuse the one bound OCR session;
2. emit source-only records for inventory special/symlink/unsafe items;
3. keep ZIP/RAR opaque even when an extension suggests a document;
4. snapshot and dispatch proven PDF, XLSX, and image sources only when source size is
   within its exact cap; an oversized PDF/workbook has `unitCount=null`, while an
   oversized proven standalone image still emits its one known image unit as
   `unknown`/`none` with `unit-over-limit`;
5. use detected bytes as authority; permit an `.xlsx`-family extension only after
   the workbook adapter's OOXML preflight proves the workbook container;
6. convert each adapter `InspectionUnitEvidence` through the pure classifier and
   create the final `InspectionUnit` without retaining its private acquisition text;
7. enforce 10,000 units before appending;
8. derive totals/status and build `InspectionResult`; and
9. let normal observation-context exit perform final revalidation before return.

Map inventory tree-change to `InspectionError("inspection-tree-changed")`. Define
the exact public operation-error tuple, ordered lexically, as:

```python
INSPECTION_ERROR_CODES = (
    "inspection-output-too-large",
    "inspection-parser-boundary-exceeded",
    "inspection-pdf-page-count-exceeded",
    "inspection-tree-changed",
    "inspection-unit-count-exceeded",
    "inspection-worksheet-count-exceeded",
    "inventory-depth-exceeded",
    "inventory-directory-count-exceeded",
    "inventory-directory-unreadable",
    "inventory-entry-count-exceeded",
    "inventory-entry-unsafe",
    "inventory-item-count-exceeded",
    "inventory-output-too-large",
    "inventory-regular-file-count-exceeded",
    "secure-open-unavailable",
    "source-root-missing",
    "source-root-unsafe",
)
```

Map retained inventory errors to the same code except
`inventory-tree-changed -> inspection-tree-changed`. A parser/decompression bound
that prevents authoritative unit enumeration uses
`inspection-parser-boundary-exceeded`; corrupt bounded content that can be safely
accounted remains a source issue. OCR unit/clock exhaustion occurs only after unit
enumeration and therefore produces the known unit with `unit-over-limit`, not an
operation error. Never interpolate underlying errors.

Use the observation ID from the secure observation; do not hash public JSON again.

- [ ] **Step 4: Run engine GREEN and focused security regressions**

```bash
cd server
python3 -m pytest \
  ctv_inspection_model_test.py ctv_inspection_classifier_test.py \
  ctv_local_ocr_test.py ctv_inventory_test.py \
  ctv_inspection_media_test.py ctv_inspection_workbook_test.py \
  ctv_inspection_test.py -q
python3 -m py_compile \
  ctv_inspection_model.py ctv_inspection_classifier.py ctv_local_ocr.py \
  ctv_inventory.py ctv_inspection_media.py ctv_inspection_workbook.py \
  ctv_inspection.py
```

- [ ] **Step 5: Commit Task 7**

```bash
git commit -m "feat(ctv): inspect local document units read-only"
```

---

### Task 8: Exact inspect CLI, documentation, and full acceptance

**Files:**

- Modify: `server/ctv_intake_cli.py`
- Modify: `server/ctv_intake_cli_test.py`
- Modify: `server/README.md`

**Interfaces:**

- Consumes: `inspect_source`, `InspectionError`, inspection result and limits.
- Produces exact `inspect --source-root <path> --json` CLI and stable envelope/exit behavior.

- [ ] **Step 1: Write subprocess RED acceptance**

Add a synthetic folder acceptance test:

```python
def test_inspect_returns_private_canonical_units_from_unrelated_cwd(tmp_path):
    source = _synthetic_inspection_folder(tmp_path)
    unrelated = tmp_path / "unrelated"
    unrelated.mkdir()
    result = _run("inspect", "--source-root", str(source), "--json", cwd=unrelated)
    payload = _envelope(result, "inspect", "succeeded")
    assert result.returncode == 0
    assert result.stderr == b""
    assert payload["result"]["totals"]["units"] >= 3
    raw = result.stdout.decode("utf-8")
    for private in _private_fixture_strings(source):
        assert private not in raw
```

Run unchanged folder twice and require byte-identical stdout. Add
`complete-with-issues` exit `0`, every controlled inspection error exit `2`, unknown
or malformed error code to fixed `internal-error` exit `1`, and oversized canonical
envelope replacement without partial output.

- [ ] **Step 2: Write exact-surface, relocation, and static RED tests**

Reject missing/empty/option-like/reordered/duplicated/abbreviated/extra args,
repeated/trailing separators, and `////`; accept canonical `/` with a mocked engine.
Every invalid call has empty stdout, fixed bounded stderr, and no caller token.

Extend Unicode/spaced relocated-toolkit tests. Create the toolkit beneath the
selected source root with bytecode environment overrides removed; compare external
tree names/bytes/modes/mtimes before/after success and controlled failure.

Static tests require:

- only `ctv_local_ocr.py` imports subprocess;
- only workbook adapter imports ZIP parsing;
- no inspection module imports archive extraction, `pytesseract`, tempfile,
  network, AI/model libraries, or shell helpers;
- CLI exact forms are the four existing forms plus inspect; and
- CLI inspection error allowlist exactly equals every literal code raised by the
  inspection engine, failing on keyword/dynamic unsupported AST shapes.

- [ ] **Step 3: Capture CLI RED**

```bash
cd server
python3 -m pytest ctv_intake_cli_test.py -q -k inspect
```

- [ ] **Step 4: Implement exact CLI integration**

Add inspect parser and `_is_inspect_argv` using the same raw path validation as
inventory. Dispatch only to `inspect_source(args.source_root)`. Extend doctor
serialization with the already-probed `localOcr` capability object without changing
doctor readiness/error semantics. Use summary:

```text
Inspection completed: <units> units, <needsUserReview> need attention
```

Buffer `canonical_json_bytes` once and enforce the 16 MiB full-envelope limit before
one stdout write. A known `InspectionError` uses fixed safe message, nonretryable
failed inspect envelope, exit `2`. Unknown code/unexpected exception uses fixed
`internal-error`, exit `1`. Never serialize the raw code unless exact allowlist
membership is proven.

- [ ] **Step 5: Document operator/WP handoff**

Add `### Inspecting document units` after inventory. Include exact preflights and
command; fresh observation/rebinding; PDF-page/worksheet/image units; fixed roles
and confidence bands; local OCR optional capability; no raw text/paths/sheet names;
archive opacity; exact limits; complete vs issue vs operation failure; no writes;
WP review questions; and the statement that inspection does not establish
authenticity, ownership, completeness, package readiness, or payment approval.

- [ ] **Step 6: Run focused and direct synthetic smoke**

```bash
cd server
python3 -m pytest ctv_intake_cli_test.py ctv_cli_doctor_test.py -q
synthetic_root=$(mktemp -d /private/tmp/ctv-inspect-smoke.XXXXXX)
python3 - "$synthetic_root" <<'PY'
from io import BytesIO
from pathlib import Path
import sys
import fitz
from openpyxl import Workbook
from PIL import Image

root = Path(sys.argv[1])
doc = fitz.open()
page = doc.new_page()
page.insert_text((72, 72), "HOP DONG DICH VU\nBEN A\nBEN B\nCHU KY")
doc.save(root / "synthetic.pdf")
doc.close()
wb = Workbook()
ws = wb.active
ws.append(["HO TEN", "CCCD", "SO TIEN"])
ws.append(["SYNTHETIC PERSON", "000000000000", 1000])
wb.save(root / "synthetic.xlsx")
Image.new("RGB", (64, 64), "white").save(root / "synthetic.png")
PY
python3 ctv_intake_cli.py inspect --source-root "$synthetic_root" --json
```

Require exit `0`, PDF/worksheet/image units, no temporary path or synthetic source
names/text/values in stdout, and no created application file in the source.

- [ ] **Step 7: Run complete candidate acceptance before staging**

```bash
python3 -m pytest -q
npm test
npm run build
python3 server/ctv_intake_cli.py version --json
python3 server/ctv_intake_cli.py doctor --json
python3 server/ctv_intake_cli.py contract verify --json
acceptance_root=$(mktemp -d /private/tmp/ctv-inventory-acceptance.XXXXXX)
python3 server/ctv_intake_cli.py inventory --source-root "$acceptance_root" --json
git diff --check
inspection_base=$(git merge-base ver1 HEAD)
git diff --exit-code "$inspection_base" -- \
  contracts/ctv-intake/v1 package.json package-lock.json
git status --short
```

Never inventory unrelated user temporary data. The exact changed-file set must
equal this plan's file map. Run source scans for real FA identifiers, VNG addresses,
key material, and local absolute paths. Separately scan captured runtime JSON,
stderr, and logs for synthetic filenames, identity/date/amount values, OCR text,
and parser diagnostics.

- [ ] **Step 8: Commit and verify exact committed head**

Stage exactly CLI, CLI test, and README; commit:

```bash
git commit -m "feat(ctv): expose safe document inspection CLI"
```

Then rerun the complete Python suite, frontend suite, build, all four preflight/
inventory commands, direct inspect smoke, contract/dependency/scope/privacy gates,
`git diff --check`, and clean tracked status on the exact committed head. Record
exact counts, exit codes, warnings, and smoke totals in the Task 8 report. Leave the
branch unpushed and unmerged for independent whole-branch review.

---

## Completion boundary

Completing this plan proves only that the local CTV toolkit can re-inventory and
classify supported PDF pages, worksheets, and standalone images with deterministic
privacy-safe signals and explicit uncertainty. It does not persist inspection,
accept user decisions, inspect/extract archives, organize evidence, create a
preparation proposal, write to an output root, build/validate a package, submit to
CTV Review, or decide payment.

The next admissible milestone is a user-approved preparation proposal and separate
output-root write boundary. Do not implement that milestone under this plan.
