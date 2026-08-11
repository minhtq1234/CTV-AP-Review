# WePrompt CTV Intake Assistant — Design and Team Handoff

**Date:** 2026-08-11

**Status:** Approved design; implementation not started

**Requesting product:** CTV/AP Review

**Delivery owner:** WePrompt team

**Downstream owner:** CTV/AP Review team

## 1. Summary

Build a dedicated **CTV Intake Assistant** in WePrompt (WP). The assistant lets a
user select a folder containing inconsistent CTV/AP evidence, discusses ambiguity
with the user, and creates reviewer-confirmed derived packages for the existing CTV
Review application.

WP owns messy-folder intake, conversation, file organization, and preparation. CTV
Review continues to own packet OCR, field comparison, evidence review, and final
human decisions.

The assistant is not a free-form prompt with unrestricted file access. It
orchestrates bounded inspection, transformation, validation, and export skills. AI
may propose structure and explain uncertainty; deterministic tools prove file/page
coverage; the user approves every package.

## 2. Problem Evidence

The current CTV application accepts one required PDF, one optional roster XLSX, and
one optional CCCD-image XLSX. Real submissions are materially less consistent:

- users provide folders containing multiple FA cases;
- supporting documents arrive as PDFs, XLSX files, ZIP/RAR archives, and images;
- the relevant Excel sheet is not necessarily the active sheet;
- equivalent headers vary (`Số CCCD`, `CMND`, `CCCD/PP`, `Họ và tên`, `Họ tên`,
  `Chủ tài khoản`);
- identity evidence can be embedded in workbooks, collated into PDFs, or stored as
  loose archive images;
- shared documents and front matter may not belong to any individual packet;
- packet creation can omit pages while still producing a superficially complete
  count.

In the observed `FA-PM260706029` case, a loose name reader counted 25 roster names
while the strict reconciliation reader produced zero usable roster rows. The UI
therefore showed `25/25` packets but marked all 25 unmatched. The proposed packets
covered PDF pages 33–178; pages 1–32 were not represented in the dashboard. This is
an intake-interpretation failure, not evidence that all 25 submissions must be sent
back.

## 3. Product Promise

The assistant will:

1. account for every received file and PDF page;
2. explain what it understood, inferred, changed, and could not resolve;
3. create normalized **derived** artifacts without changing originals;
4. pause for user decisions when evidence or ownership is ambiguous; and
5. hand only a user-confirmed package to CTV Review.

The assistant will not claim that successful preprocessing, successful OCR, or “no
issue found” constitutes payment approval.

## 4. Goals

- Accept a selected folder with nested files and subfolders as one intake batch.
- Propose one or more FA cases within the batch.
- Safely inspect supported documents and archives.
- Detect likely roster sheets and map varied source headers to canonical fields.
- Identify shared, duplicate, unknown, unreadable, and unassigned evidence.
- Let the user correct case ownership and document roles conversationally.
- Preview transformations before writing derived artifacts.
- Create a reproducible prepared package with provenance and exceptions.
- Preserve partial progress and permit item-level retry.
- Keep final packet and payment decisions with human reviewers.

## 5. Non-goals for v1

- Autonomous payment approval or rejection.
- Silent modification, deletion, or renaming of original files.
- Guessing missing identity, bank, tax, amount, or date values.
- Replacing the existing CTV packet viewer or review workflow.
- Treating a general-purpose shell agent as the product interface.
- Direct submission into CTV Review before the package contract is accepted by the
  CTV team. V1 produces and validates the prepared package; direct submission is a
  follow-on integration using the same package.

## 6. Ownership Boundary

### WePrompt team owns

- CTV Intake Assistant definition and conversational workflow;
- folder/workspace selection and file permission UX;
- bounded CTV preprocessing skills and their tool adapters;
- inspection summaries, evidence pointers, questions, and transformation previews;
- creation and validation of the prepared package;
- retry, progress, and audit history within the WP project workspace.

### CTV team owns

- canonical prepared-package schema acceptance;
- downstream import/submission contract;
- packet splitting, OCR, field extraction, reconciliation, and evidence rendering;
- packet review states and final human approval/rejection;
- interpretation of ACC/GAS business checks.

### Shared contract

Both teams own versioning and compatibility tests for the prepared-package schema.
WP must not mark a package compatible with a CTV version it has not validated.

## 7. Architecture

```text
User selects folder in a WP project
                |
                v
      Immutable source inventory
                |
                v
  CTV Intake Assistant + bounded skills
  - deterministic inspection
  - AI classification and explanation
  - deterministic coverage validation
                |
                v
  Mandatory conversational review gate
  - proposed FA cases
  - chosen roster sheets and mappings
  - shared/unassigned/unknown evidence
  - planned derived-file changes
                |
         user confirms package
                |
                v
      Prepared package in workspace
                |
       future explicit submission
                |
                v
          CTV Review application
```

AI is an orchestrator and reasoning layer, not the evidence store or validation
authority. Large or sensitive documents remain in the local workspace. Skills return
bounded summaries and evidence references rather than placing entire batches into
model context.

## 8. Assistant Workflow

### 8.1 Receive

The user selects or drops a folder into a WP project and asks the CTV Intake
Assistant to prepare it. WP records the selected root and requests the minimum file
read/write permissions required for the workspace.

### 8.2 Inventory

The assistant calls deterministic inventory tooling to create immutable records for
every source item:

- relative path;
- byte size and detected media type;
- SHA-256 digest;
- container/archive relationship;
- readability and encryption status;
- initial state: `received`, `duplicate`, `unsupported`, `unreadable`, or
  `inspectable`.

Archive extraction is performed only into a derived working directory with path
containment, type, count, expanded-size, nesting, and timeout limits. The archive
itself remains part of the source inventory.

### 8.3 Inspect

Specialized inspectors produce structured facts:

- **PDF:** page count, orientation, text/image characteristics, likely boundaries,
  duplicate pages, and page-level source references;
- **Workbook:** all sheet names, visibility/active state, used ranges, candidate
  header rows, canonical-field candidates, embedded-image counts, and formula/error
  warnings;
- **Image:** type, dimensions, orientation, duplicate digest, and a sensitive-content
  classification sufficient to route identity evidence;
- **Archive:** contained-file inventory and extraction issues.

Inspectors must not log raw identity numbers, account numbers, addresses, or full
document text in ordinary application logs.

### 8.4 Propose cases and roles

The assistant proposes:

- batch-level files;
- FA case boundaries;
- primary case PDF(s);
- roster workbook and sheet;
- source-to-canonical roster column mappings;
- identity evidence collections;
- shared evidence;
- duplicates;
- unassigned or unknown files and pages.

Every proposal includes confidence, evidence references, and an explanation. A
filename may be a signal but cannot be the only evidence for a high-confidence role.

### 8.5 Resolve ambiguity conversationally

The assistant asks one targeted question at a time. Examples:

- “Pages 1–32 appear to be shared evidence. Keep them at case level?”
- “Should `CMND` be treated as the identity-number column in this workbook?”
- “These 14 PDFs appear to belong to one FA case. Combine them in this order?”

User answers become explicit decisions in the audit trail. A later answer may revise
an earlier proposal without re-running successful unrelated inspections.

### 8.6 Preview transformations

Before any derived write, WP presents:

- target paths;
- source items used;
- operation type and ordering;
- roster header mapping;
- excluded/duplicate items;
- remaining exceptions;
- package compatibility result.

The user can approve, edit, or cancel. Approval applies only to the displayed
transformation version; changes after approval require a new preview.

### 8.7 Prepare and validate

The assistant calls deterministic transformation tools, then independently validates
their outputs. Failure of one case does not discard successfully prepared sibling
cases.

## 9. Skill and Tool Boundaries

The WP team should package the workflow as a dedicated CTV skill that orchestrates
the following bounded capabilities. Names are conceptual, not prescribed APIs.

### `inventory_batch`

Recursively inventories source items, hashes files, identifies duplicates, and
returns a stable batch manifest. Read-only against the source folder.

### `inspect_documents`

Dispatches to PDF, workbook, image, and archive inspectors. Returns structured facts
and evidence references with bounded output.

### `propose_case_plan`

Uses inspected facts to propose cases, document roles, roster mappings, and
exceptions. AI may generate the proposal, but it cannot alter inventory facts.

### `preview_transformations`

Produces a deterministic plan/diff describing all derived writes and source links.
It performs no writes.

### `prepare_case`

Creates approved derived artifacts in a new versioned package directory. It may
extract archives, copy/merge/rotate/reorder PDFs, and create a canonical roster. It
cannot write under the source root.

### `validate_package`

Checks schema, digests, source/page coverage, roster keys, derived-file readability,
exception completeness, and CTV compatibility. Deterministic validation can veto an
AI proposal.

### `submit_to_ctv` — follow-on integration

Submits an already validated package only after a separate explicit user action.
Submission is idempotent and records the returned CTV case identifier. It is outside
the WP v1 delivery until the CTV package API is available.

## 10. Prepared Package

Each confirmed case is written under a versioned derived directory, for example:

```text
Prepared/
  <batch-id>/
    <fa-code>/
      v001/
        case-manifest.json
        input.pdf
        roster.xlsx
        cccd.xlsx              # optional
        exceptions.json
        validation-report.json
```

`case-manifest.json` contains:

- schema version, batch identifier, case identifier, and proposed FA code;
- source inventory references and SHA-256 digests;
- derived artifact paths and digests;
- selected workbook sheet and canonical column mapping;
- PDF page/source mapping;
- user decisions with timestamps and proposal versions;
- excluded, duplicate, shared, unknown, and unresolved evidence references;
- compatibility target and validation outcome.

`exceptions.json` records every unresolved item with a stable code, severity,
evidence reference, explanation, and required action. An empty list means “no known
preprocessing exceptions”; it does not mean the payment evidence is correct.

## 11. Coverage and Approval Rules

Package confirmation is blocked unless:

- every original file is `assigned`, `shared`, `duplicate`, `unsupported`,
  `unreadable`, `excluded-by-user`, or `unresolved`;
- every page of every PDF is assigned to a derived document, retained as shared
  evidence, explicitly excluded, or unresolved;
- the proposed roster has a unique identity column and a name column, or is clearly
  marked unresolved;
- derived artifacts are readable and their digests match the manifest;
- all AI assertions used for transformation point to inspectable evidence;
- the user has reviewed the current transformation version.

Unresolved items may remain in a prepared package only when they are visible in the
exception list and the user explicitly confirms that the package is intentionally
partial. A partial package must never be labeled complete.

## 12. State Model and Recovery

Batch states:

```text
received -> inventory_ready -> analyzing
         -> needs_user_input -> ready_for_confirmation
         -> preparing -> prepared
         -> partially_prepared
         -> blocked
```

Case and file states are independent of the batch state. A corrupt workbook may
block one case while archive extraction and PDF inspection continue for other cases.

Retries operate on the smallest failed unit. Previous successful facts and derived
artifacts are reused only when their source digests, tool versions, and decisions
still match. The user can resume the conversation without re-uploading or rebuilding
the whole batch.

## 13. Error Handling

- **Unsupported file:** retain in inventory and request classification or exclusion.
- **Corrupt/password-protected file:** mark unreadable; do not fail sibling files.
- **Archive traversal/bomb/nesting limit:** stop that extraction, record a security
  exception, and retain the archive.
- **Multiple candidate roster sheets:** show a comparison and ask the user.
- **Ambiguous header mapping:** propose candidates with evidence; never write a
  canonical value until confirmed.
- **Unassigned PDF pages:** show page ranges/thumbnails and block complete status.
- **AI unavailable:** preserve deterministic inspection results and allow retry or
  manual role assignment.
- **Derived write failure:** keep the approved plan, remove or quarantine incomplete
  derived output, and retry only the failed operation.
- **Validation failure:** keep the package in `partially_prepared`; never submit it.

## 14. Privacy, Security, and Audit

- Originals are immutable and remain outside derived write targets.
- Path resolution must prevent writes or extraction outside the WP project workspace.
- Raw PII and identity images remain local by default.
- External model use for raw identity evidence requires explicit organizational and
  user authorization; otherwise use local/private inference or deterministic tools.
- Model-facing summaries should minimize PII and use evidence IDs instead of raw
  identity/account values whenever possible.
- Every AI proposal records model/provider identity, prompt/skill version, referenced
  facts, confidence, and timestamp.
- Every user decision and derived write is auditable.
- No original document, extracted identity image, or real customer fixture may be
  committed to source control.

## 15. UX Requirements

The primary interface is conversation supplemented by structured artifacts:

- batch inventory and progress;
- proposed case cards;
- roster-sheet/header mapping preview;
- file/page coverage ledger;
- transformation preview/diff;
- exception list;
- prepared-package validation report.

The assistant must use plain operational language. It must distinguish:

- **understood** from **inferred**;
- **unresolved** from **incorrect**;
- **prepared** from **approved**;
- **preprocessing complete** from **CTV review complete**.

## 16. Testing Strategy

### Unit tests

- file inventory, hashing, duplicate detection, and stable IDs;
- safe archive extraction limits and path containment;
- PDF page accounting and derived page maps;
- workbook sheet discovery and header-candidate normalization;
- transformation-plan versioning and approval invalidation;
- package schema and digest validation;
- state transitions and item-level retry;
- PII-safe logging and bounded model context.

### Contract tests

- WP prepared-package fixtures validate against the CTV-owned schema;
- compatible and incompatible schema versions produce explicit outcomes;
- submission, when added, is idempotent and preserves provenance identifiers.

### Scenario tests

- multiple FA folders in one batch;
- ZIP/RAR archives containing PDFs or identity images;
- relevant roster sheet is not active;
- varied headers including `CMND`, `CCCD/PP`, and `Họ tên`;
- shared/unassigned leading PDF pages;
- duplicate and conflicting files;
- one corrupt item with successful sibling cases;
- AI unavailable after deterministic inspection;
- user changes a decision after preview;
- intentionally partial package with visible exceptions.

### Acceptance test: `CTV AP GAS`

Using the real batch locally and without committing its contents, the assistant must:

1. identify four proposed FA cases;
2. inventory all top-level files and safely expose archive contents;
3. inspect all relevant workbook sheets instead of trusting the active sheet;
4. propose the correct roster candidates and header mappings with evidence;
5. expose unsupported CCCD PDFs, loose/archive images, and multi-PDF cases;
6. surface the 32 unassigned pages in `FA-PM260706029`;
7. prepare independent case packages or explicit blocked/partial results;
8. leave every original file unchanged; and
9. prevent “complete” status while any file/page lacks an explicit state.

## 17. Success Measures

- 100% of received files and PDF pages have explicit coverage states.
- 0 original-file mutations.
- 0 silent AI transformations.
- 0 packages labeled complete with hidden unresolved evidence.
- 100% of derived artifacts have source provenance and digests.
- A single-file/case failure never destroys successful sibling progress.
- Users can understand and correct the proposed organization without manually
  reconstructing the source folder.

## 18. Delivery Sequence

1. Agree and version the prepared-package schema with the CTV team.
2. Build deterministic inventory, inspection, and validation tools with synthetic
   fixtures.
3. Build the CTV Intake Assistant skill and conversational proposal workflow.
4. Add transformation preview and versioned derived-package creation.
5. Run the local `CTV AP GAS` acceptance test with PII-safe evidence reporting.
6. Add direct CTV submission only after the package API is available and separately
   accepted.

This sequence keeps the assistant useful as an interactive file organizer before
coupling it to CTV Review, while preserving a stable integration boundary.
