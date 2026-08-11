# CTV Intake Contract v1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Publish a CTV-owned, machine-verifiable v1 contract for prepared FA case packages, including semantic validation, synthetic fixtures, and compatibility rules that WP can pin without copying real customer data.

**Architecture:** Pydantic models in the CTV backend are the executable source of truth. A deterministic exporter writes versioned JSON Schemas and exception codes under `contracts/ctv-intake/v1/`; a validator checks both schema shape and cross-file invariants such as digests, page coverage, exception completeness, and package status. Contract fixtures are generated from synthetic files only.

**Tech Stack:** Python 3, Pydantic v2, pytest, PyMuPDF, openpyxl, JSON Schema artifacts, SHA-256.

## Global Constraints

- Execute in a new isolated CTV worktree created from the currently approved `ver1` head after rechecking `git status`, ancestry, and the exact SHA.
- Do not modify or delete `.DS_Store`, `.superpowers/`, `server/data/`, or any unrelated user files.
- Never add `CTV AP GAS`, real names, identity numbers, bank data, extracted images, or other PII to git.
- Originals are immutable. The validator reads package artifacts but does not repair them.
- `prepared` means mechanically complete for CTV intake; it does not mean the payment evidence is correct or approved.
- A package with visible unresolved evidence may be `partially_prepared`; it may never be labeled `prepared`.
- Use lower-case kebab-case stable codes. Once published in v1, codes are append-only.
- Run `git diff --check` and the full CTV Python and frontend suites before requesting review.

---

## Contract Types to Implement

Use these exact public values:

```python
CoverageState = Literal[
    "assigned", "shared", "duplicate", "unsupported", "unreadable",
    "excluded-by-user", "unresolved",
]
PackageStatus = Literal["prepared", "partially_prepared"]
ValidationOutcome = Literal["valid", "invalid"]
ExceptionSeverity = Literal["warning", "blocking"]
ArtifactKind = Literal["input-pdf", "roster", "cccd", "exceptions", "validation-report"]
ExceptionResolution = Literal["open", "accepted-partial", "resolved"]
DecisionType = Literal[
    "assign-source", "share-source", "mark-duplicate", "exclude-source",
    "assign-page", "select-roster-sheet", "map-roster-column",
    "approve-preview", "accept-partial",
]
```

`case-manifest.json` must contain:

- `schemaVersion`, fixed to `"1.0"`;
- `batchId`, `caseId`, nullable `faCode`, `packageVersion`, `status`, and `compatibilityTarget`;
- `sources[]`: stable `sourceId`, workspace-relative path, media type, size, SHA-256, coverage state, and optional duplicate/decision references;
- `pdfPages[]`: source ID, one-based source page, coverage state, optional target page, and optional decision reference;
- `artifacts[]`: kind, package-relative path, size, SHA-256, and source references;
- nullable `rosterMapping`: source/sheet identity plus canonical-to-source column mapping;
- `decisions[]`: stable ID, proposal version, decision type, actor `"user"`, timestamp, and evidence references;
- `exceptionIds[]`; and
- `validatedAt` plus `validatorVersion`.

`exceptions.json` is an object with `schemaVersion: "1.0"` and `items: ExceptionItem[]`, where each item has stable ID, code, severity, evidence references, explanation, required action, and resolution state.

`validation-report.json` is `{schemaVersion, outcome, packageStatus, checks, errors, warnings, validatedAt, validatorVersion}`. Each check has a stable code, pass/fail result, and evidence references.

## Task 1: Establish the isolated contract workspace

**Files:**

- No product files changed in this task.

- [ ] From `/Users/lap16603/Documents/New project/work/CTV_APReview-v1`, refresh status and record the exact base:

```bash
git status --short
git rev-parse HEAD
git log -5 --oneline
git worktree list --porcelain
```

Expected: current branch is `ver1`; only known unrelated local files are present; the approved design spec is reachable from `HEAD`.

- [ ] Invoke `superpowers:using-git-worktrees` and create an isolated branch/worktree such as `codex/ctv-intake-contract-v1` under a verified worktree parent. Do not reuse a dirty checkout.
- [ ] In the new worktree, run the baseline suites:

```bash
cd server && python3 -m pytest -q
cd .. && npm test
```

Expected: both commands exit 0. Record existing warnings separately; do not treat a stalled or interrupted suite as passing.

## Task 2: Define executable contract models

**Files:**

- Create: `server/intake_contract.py`
- Create: `server/intake_contract_test.py`

- [ ] Write failing model tests for the exact public types above and for rejection of:
  - absolute paths and `..` traversal;
  - malformed SHA-256 values;
  - zero-based page numbers;
  - duplicate source, artifact, decision, or exception IDs;
  - `prepared` with any unresolved coverage or blocking exception;
  - an artifact path outside the package directory.

```bash
cd server && python3 -m pytest intake_contract_test.py -q
```

Expected: FAIL because `intake_contract` does not exist.

- [ ] Implement focused Pydantic models with `extra="forbid"`. Keep path syntax validation and local shape validation in field/model validators; reserve filesystem and cross-file checks for Task 5.
- [ ] Add a `PackageManifest`, `ExceptionsDocument`, `ValidationReport`, and `CanonicalRosterRow` model. Export a stable `EXCEPTION_CODES` mapping from the same module.
- [ ] Re-run the targeted test.

Expected: PASS.

- [ ] Commit only the model and test:

```bash
git add server/intake_contract.py server/intake_contract_test.py
git commit -m "feat(ctv): define intake package contract"
```

## Task 3: Export versioned contract artifacts

**Files:**

- Create: `server/export_intake_contract.py`
- Create: `server/export_intake_contract_test.py`
- Create: `contracts/ctv-intake/v1/package.schema.json`
- Create: `contracts/ctv-intake/v1/exceptions.schema.json`
- Create: `contracts/ctv-intake/v1/validation-report.schema.json`
- Create: `contracts/ctv-intake/v1/canonical-roster.schema.json`
- Create: `contracts/ctv-intake/v1/exception-codes.json`
- Create: `contracts/ctv-intake/v1/compatibility.md`

- [ ] Write a failing determinism test that exports to `tmp_path` twice and compares bytes. Also assert that checked-in generated files equal a fresh export and contain no absolute build paths or timestamps.
- [ ] Implement `python3 server/export_intake_contract.py --output contracts/ctv-intake/v1` using `model_json_schema()` and canonical JSON (`ensure_ascii=False`, sorted keys, two-space indent, final newline).
- [ ] Document compatibility precisely:
  - producer and consumer must match major version `1`;
  - consumers may accept added optional fields only after contract tests pass;
  - removing/renaming fields, changing enum meaning, or weakening coverage is a major change;
  - exception codes are append-only within v1;
  - WP records the exact CTV commit and tree digest in `SOURCE.json`.
- [ ] Run:

```bash
python3 server/export_intake_contract.py --output contracts/ctv-intake/v1
cd server && python3 -m pytest export_intake_contract_test.py intake_contract_test.py -q
```

Expected: PASS and a clean second export (`git diff` unchanged).

- [ ] Commit:

```bash
git add server/export_intake_contract.py server/export_intake_contract_test.py contracts/ctv-intake/v1
git commit -m "feat(ctv): publish intake contract v1"
```

## Task 4: Add synthetic complete and partial fixtures

**Files:**

- Create: `server/intake_fixture_factory.py`
- Create: `server/intake_fixture_factory_test.py`
- Create: `contracts/ctv-intake/v1/fixtures/complete/case-manifest.json`
- Create: `contracts/ctv-intake/v1/fixtures/complete/exceptions.json`
- Create: `contracts/ctv-intake/v1/fixtures/partial/case-manifest.json`
- Create: `contracts/ctv-intake/v1/fixtures/partial/exceptions.json`
- Create: `contracts/ctv-intake/v1/fixtures/invalid-hidden-page/case-manifest.json`
- Create: `contracts/ctv-intake/v1/fixtures/README.md`

- [ ] Write failing tests that generate a tiny synthetic PDF and workbook in `tmp_path`, then create:
  - one complete package with every file/page assigned;
  - one intentionally partial package with an `unassigned-page` blocking exception;
  - one invalid package that claims `prepared` while hiding an uncovered page.
- [ ] Implement deterministic fixture helpers. Use fake identifiers such as `FA-SYNTH-001`; do not use realistic 12-digit identity or bank-account values.
- [ ] Check in only the small JSON fixture documents. Generate binary PDF/XLSX artifacts during tests so git never becomes a precedent for customer-like document fixtures.
- [ ] Run:

```bash
cd server && python3 -m pytest intake_fixture_factory_test.py -q
```

Expected: PASS; complete and partial fixture models parse; invalid fixture is rejected for the expected stable code.

- [ ] Commit:

```bash
git add server/intake_fixture_factory.py server/intake_fixture_factory_test.py contracts/ctv-intake/v1/fixtures
git commit -m "test(ctv): add synthetic intake contract fixtures"
```

## Task 5: Implement semantic package validation

**Files:**

- Create: `server/intake_package_validator.py`
- Create: `server/intake_package_validator_test.py`

- [ ] Write failing tests for `validate_package(package_dir: Path) -> ValidationReport` covering:
  - missing required artifact;
  - digest or byte-size mismatch;
  - missing or extra PDF page coverage;
  - source/artifact/decision/exception references to unknown IDs;
  - unreadable PDF or roster;
  - ambiguous/missing canonical name or identity mapping and duplicate non-empty canonical identity values;
  - `prepared` with warning-only exceptions (allowed) versus blocking/unresolved exceptions (rejected);
  - a symlink or package-relative path escaping `package_dir`;
  - deterministic error ordering.
- [ ] Implement the validator as a pure read/check/report pipeline. Reuse `preflight_roster_workbook`; open PDFs with PyMuPDF only after size/path checks; never normalize or mutate files.
- [ ] Ensure the validator reports all independent failures in one run rather than stopping at the first malformed sibling artifact.
- [ ] Run:

```bash
cd server && python3 -m pytest intake_package_validator_test.py intake_contract_test.py -q
```

Expected: PASS.

- [ ] Commit:

```bash
git add server/intake_package_validator.py server/intake_package_validator_test.py
git commit -m "feat(ctv): validate prepared intake packages"
```

## Task 6: Add the validator CLI and handoff documentation

**Files:**

- Create: `server/validate_intake_package.py`
- Create: `server/validate_intake_package_test.py`
- Modify: `server/README.md`
- Create: `contracts/ctv-intake/README.md`

- [ ] Write CLI tests for exit 0 on valid, exit 2 on invalid, JSON to stdout, diagnostics only to stderr, and `--write-report` writing inside the package directory only.
- [ ] Implement:

```bash
python3 server/validate_intake_package.py /path/to/package
python3 server/validate_intake_package.py /path/to/package --write-report
```

- [ ] Document the WP pinning procedure, required `SOURCE.json` fields (`sourceRepository`, `sourceCommit`, `contractPath`, `contractTreeSha256`, `copiedAt`), and the rule that WP never edits the snapshot in place.
- [ ] Run the complete CTV verification:

```bash
cd server && python3 -m pytest -q
cd .. && npm test
npm run build
git diff --check
git status --short
```

Expected: all commands exit 0; status contains only intended contract work plus any preserved pre-existing user files.

- [ ] Commit:

```bash
git add server/validate_intake_package.py server/validate_intake_package_test.py server/README.md contracts/ctv-intake/README.md
git commit -m "docs(ctv): document intake contract handoff"
```

## Task 7: CTV contract review gate

- [ ] Ask an independent reviewer to compare the implementation against Sections 8, 12–16, and 18–20 of the approved design spec.
- [ ] Require evidence for: zero hidden pages, zero source mutation, deterministic schemas, path containment, partial-status semantics, and absence of PII.
- [ ] Re-run `python3 server/export_intake_contract.py` and require no diff.
- [ ] Record the final CTV commit SHA and contract directory tree hash for the WP `SOURCE.json` pin. Do not push or merge unless explicitly authorized.

## Plan Self-Review Checklist

- [ ] Every prepared-package field and every coverage state in the design spec maps to an executable model or semantic check.
- [ ] Complete, partial, and invalid-hidden-evidence fixtures are covered.
- [ ] No step adds real input files or extracted evidence to git.
- [ ] A placeholder scan finds no unfinished markers in the implementation.
- [ ] The checked-in schemas are reproducible from the typed source.
- [ ] The final handoff includes exact commit and tree digests, not branch names alone.
