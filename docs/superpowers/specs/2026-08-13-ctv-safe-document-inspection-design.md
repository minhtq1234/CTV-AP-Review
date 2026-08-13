# CTV Safe Document Inspection and Classification — Design

**Date:** 2026-08-13

**Status:** Approved design; implementation not started

**Product owner:** CTV/AP Review

**Consumer:** WePrompt CTV Intake Assistant and local operators

## 1. Decision

Extend the standalone CTV local CLI with a separate read-only `inspect` command.
The command performs a fresh folder inventory, securely inspects supported
documents, and returns bounded deterministic JSON containing fixed document-role
proposals, confidence bands, privacy-safe signal codes, and issue codes.

The command supports:

- PDF pages;
- Excel worksheets; and
- standalone images.

ZIP and RAR archives remain opaque. Inspection never lists or extracts archive
members.

The first version uses deterministic local classification. It does not use a
remote model, a local generative model, or WP model inference to assign roles.
Local OCR is permitted under strict limits for scanned PDF pages and standalone
images. Raw document text and raw OCR output never enter the JSON result or WP
model context.

Inspection creates no report, cache, thumbnail, working state, or derived
artifact. Writing begins only in a later preparation milestone after the user has
reviewed and approved a proposal.

## 2. Product boundary

This milestone sits between the completed folder inventory and future package
preparation:

```text
User selects source folder
        |
        v
WP calls local inventory/inspection command
        |
        v
Toolkit re-inventories and inspects read-only
        |
        v
Bounded opaque JSON: roles, confidence, signals, issues
        |
        v
WP explains uncertainty and asks the user
        |
        v
Future milestone: approved preparation proposal and derived package
```

The inspection milestone answers:

- how many safely enumerable PDF pages, workbook sheets, and standalone images
  were received;
- which fixed document role is suggested for each unit;
- which fixed structural or text-presence signals support that proposal;
- how strong the deterministic evidence is; and
- which units or sources need human attention.

It does not establish:

- document authenticity, validity, ownership, or completeness;
- whether two units belong to the same person or FA case;
- whether a workbook sheet is the authoritative roster;
- whether a payment, tax, identity, or bank value is correct;
- packet completeness or payment approval; or
- permission to copy, transform, exclude, group, or submit evidence.

## 3. Command and preflight

Add one exact CLI form:

```bash
python3 server/ctv_intake_cli.py inspect \
  --source-root "/path/to/batch" \
  --json
```

The CLI accepts these tokens only in the order shown. Missing, abbreviated,
duplicated, reordered, empty, option-like, or extra arguments are invalid. An
invalid invocation exits `1`, writes no stdout, and emits only fixed bounded
guidance on stderr without echoing caller input.

Before WP calls `inspect`, it runs the existing local-toolkit preflights against
the same checkout:

1. `version --json`;
2. `doctor --json`; and
3. `contract verify --json`.

`doctor` must report whether the local OCR runtime and required language data are
available. An unavailable OCR runtime does not prevent structural enumeration,
embedded-text inspection, or worksheet inspection. Units that require OCR are
returned with safe issues and require user review.

The new CLI operation identifier is `inspect`. Existing exact forms and response
semantics for `version`, `doctor`, `contract.verify`, and `inventory` remain
unchanged.

## 4. One fresh bound observation

Every `inspect` invocation begins with a fresh inventory inside the same command.
It does not accept an earlier inventory result, persisted evidence map, filename,
relative path, or caller-supplied evidence ID.

The operation privately binds:

- the inventory's deterministic evidence order;
- the secure source-root descriptor and final root identity;
- every source identity and stable byte snapshot used for parsing or OCR;
- the authoritative PDF page, workbook sheet, and image unit counts; and
- the final descriptor-bound tree revalidation.

The result receives an opaque `observationId`. It is deterministically derived
from the complete private authoritative observation, without serializing private
paths or content. It is a correlation value for this unchanged observation, not a
durable source identifier. A detected mutation invalidates the result. A later
call against a changed folder creates a new observation and may assign new
evidence and unit IDs.

The command never silently reuses an evidence ID from another observation.

## 5. Filesystem and process trust boundary

Inspection inherits the inventory milestone's fail-closed filesystem rules:

- explicit caller-selected source root only;
- component-by-component no-follow root opening;
- descriptor-relative enumeration, stat, reopen, and reads;
- nonblocking opens before regular-file proof;
- no symlink following or pathname-read fallback;
- stable device, inode, mode, size, modification-time, and change-time checks;
- exact descriptor ownership on success and error; and
- final root and descendant revalidation at the defined observation point.

Inspection never modifies the selected source folder. It also creates no
application report, state, cache, temporary document, thumbnail, extracted text,
lock, or derived output anywhere. PDF rendering and workbook parsing use bounded
in-memory snapshots. Local OCR receives bounded image bytes through stdin and
returns text through stdout; the toolkit does not create OCR input or output files.
Python bytecode writing remains disabled before source-backed imports.

Inspection performs no network access. It never sends document bytes, rendered
images, OCR text, workbook cells, filenames, or paths to WP or an external model.

Consistency ends at the command's final observation point. The command makes no
post-return immutability claim.

## 6. Supported source and unit model

Inspection returns one source record for every inventory item, including opaque,
unsupported, unreadable, and unsafe items. Supported regular documents additionally
produce unit records.

### 6.1 PDF

A safely parsed PDF produces one unit for every actual page, in one-based source
page order. Mixed-document PDFs are expected; each page is classified
independently.

For each page:

1. acquire bounded embedded text when sufficient;
2. otherwise render a bounded in-memory image and invoke local OCR;
3. reduce private text and structure immediately to fixed signal codes;
4. discard raw text and rendered bytes; and
5. assign one role, confidence band, and review status.

Encrypted, corrupt, over-limit, or structurally unsafe PDFs remain accounted for
at source level. When the page count cannot be established honestly, the command
does not invent page units.

### 6.2 Excel workbook

A safely parsed `.xlsx`-family workbook produces one unit for every worksheet in
workbook order. The public result uses a one-based worksheet index and never a
sheet name.

Visible, hidden, and very-hidden sheets are counted. Hidden state becomes a safe
signal or issue and always requires user review. The classifier examines bounded
cell types, header-like text, populated regions, and formula/value presence. It
does not return cell values or formulas.

Workbook embedded drawings and images are not separate classification units in
this milestone. Their presence may produce `embedded-media-present`; inspecting
and assigning those images belongs to a later preparation capability. The toolkit
does not extract them during inspection.

### 6.3 Standalone image

Each supported standalone PNG, JPEG, GIF, TIFF, or WebP file produces one image
unit. Classification may use bounded dimensions, aspect/orientation, and local OCR.
The result never contains image bytes, thumbnails, raw dimensions beyond approved
coarse signals, or OCR text.

### 6.4 Archives and other sources

ZIP and RAR records remain source-only and receive `opaque-archive`. The command
does not list, parse, decompress, or extract members.

Other unsupported regular files remain source-only and receive
`unsupported-document-type`. Symlinks and special entries retain inventory's safe
accounting and are never inspected.

## 7. Fixed classification taxonomy

Every unit has exactly one `suggestedRole` from this closed v1 set:

- `payment-roster`;
- `service-contract`;
- `acceptance-record`;
- `payment-tax-form`;
- `identity-front`;
- `identity-back`;
- `shared-supporting-evidence`;
- `other-supporting-evidence`; or
- `unknown`.

Allowed roles are constrained by unit type:

| Unit kind | Allowed suggested roles |
|---|---|
| PDF page | Entire taxonomy |
| Worksheet | `payment-roster`, `other-supporting-evidence`, `unknown` |
| Standalone image | `identity-front`, `identity-back`, `shared-supporting-evidence`, `other-supporting-evidence`, `unknown` |

`unknown` is always a valid result. The classifier never forces the closest role.

## 8. Signals and deterministic classification

Private text and structure are converted immediately into fixed lower-case
kebab-case signals. Signals describe only the presence of a pattern; they never
contain the matched value, text fragment, filename, sheet name, or page content.

Initial signal families include:

- `service-contract-heading`;
- `party-section-present`;
- `service-scope-section-present`;
- `signature-section-present`;
- `acceptance-heading`;
- `acceptance-period-present`;
- `payment-request-heading`;
- `tax-form-heading`;
- `roster-column-pattern`;
- `roster-row-pattern`;
- `identity-front-heading`;
- `identity-front-layout`;
- `identity-back-layout`;
- `identity-number-pattern-present`;
- `identity-issue-section-present`;
- `case-level-heading`;
- `multi-party-reference-present`;
- `supporting-document-heading`;
- `embedded-media-present`;
- `worksheet-hidden`;
- `mostly-image-page`;
- `mostly-text-page`; and
- `multiple-role-signals`.

### 8.1 Exact v1 rule table

The classifier evaluates only roles allowed for the unit kind. For each candidate,
the following table defines its strong, supported, and weak states:

| Role | Strong (`high`) | Supported (`medium`) | Weak (`low`) |
|---|---|---|---|
| `payment-roster` | worksheet has both `roster-column-pattern` and `roster-row-pattern` | worksheet has `roster-column-pattern` without sufficient row pattern | not emitted; otherwise `unknown` |
| `service-contract` | `service-contract-heading` + `party-section-present` + at least one of `service-scope-section-present` or `signature-section-present` | heading + exactly one of the remaining required/supporting signals | heading alone |
| `acceptance-record` | `acceptance-heading` + at least two of `acceptance-period-present`, `party-section-present`, `signature-section-present` | heading + exactly one supporting signal | heading alone |
| `payment-tax-form` | one of `payment-request-heading` or `tax-form-heading` + at least two of `party-section-present`, `signature-section-present`, `roster-column-pattern` | one heading + exactly one supporting signal | one heading alone |
| `identity-front` | all of `identity-front-heading`, `identity-front-layout`, `identity-number-pattern-present` | any two of those signals | `identity-front-layout` alone |
| `identity-back` | `identity-back-layout` + `identity-issue-section-present` | either signal alone when no front-side signal exists | not emitted; otherwise `unknown` |
| `shared-supporting-evidence` | not emitted at high confidence in v1 | both `case-level-heading` and `multi-party-reference-present` | not emitted; otherwise `unknown` |
| `other-supporting-evidence` | not emitted at high confidence in v1 | `supporting-document-heading` + one of `mostly-text-page`, `mostly-image-page`, or `embedded-media-present` | `supporting-document-heading` alone |

A signal used in a rule means presence only. It never exposes the matching text or
value.

### 8.2 Conflict and precedence rules

1. Evaluate every allowed non-`unknown` role independently.
2. If two or more roles reach `high`, return `unknown`/`none` with
   `classification-conflict` and `multiple-role-signals`.
3. If exactly one role reaches `high`, select it unless another role reaches
   `medium`; a high/medium conflict becomes `unknown`/`none` with the same conflict
   markers.
4. With no high candidate, exactly one medium candidate is selected as `medium`.
   Two or more medium candidates become `unknown`/`none` with conflict markers.
5. With no high or medium candidate, exactly one low candidate is selected as
   `low`. Multiple low candidates become `unknown`/`none` with
   `classification-ambiguous` and `multiple-role-signals`.
6. With no candidate, return `unknown`/`none` and
   `classification-ambiguous`.
7. A hidden worksheet retains the role produced by these rules but always requires
   review. An OCR failure or timeout discards OCR-derived signals before rules are
   evaluated; structural signals may still support a proposal.

These rules deliberately have no tie-breaking role precedence. Conflicting evidence
is surfaced rather than silently resolved.

Classification is a pure deterministic function of unit kind, inspection method,
fixed signals, and safe issue codes. It performs no generative inference. Repeated
calls on the same authoritative observation and runtime version produce
byte-identical canonical JSON.

## 9. Confidence and review contract

Every unit has one confidence band:

- `high`: one role has its strong required signal combination and no material
  conflict;
- `medium`: one role is supported, but at least one expected supporting signal is
  absent;
- `low`: weak evidence favors one allowed role;
- `none`: no role is supportable; `suggestedRole` must be `unknown`.

Confidence is deliberately categorical. The toolkit does not expose a misleading
probability or reuse OCR confidence as classification confidence.

`needsUserReview` is always `true` when any of these conditions holds:

- confidence is `medium`, `low`, or `none`;
- suggested role is `unknown`;
- signals conflict or indicate multiple roles;
- OCR is unavailable, fails, times out, or is low confidence;
- a worksheet is hidden or very hidden;
- a source or unit is unsupported, unreadable, encrypted, or over a limit; or
- any inspection issue is present.

A high-confidence proposal is still not an approval. WP may summarize consecutive
high-confidence units instead of asking about each one, but the later preparation
proposal remains subject to explicit user confirmation.

Inspection records no user decision and writes no state. Future preparation may
group consecutive confirmed pages, but this command always emits page-level units.

## 10. Stable JSON result

Inspection uses the existing CLI envelope. A representative succeeded result is:

```json
{
  "schemaVersion": "1.0",
  "operation": "inspect",
  "status": "succeeded",
  "summary": "Inspection completed: 42 units, 11 need attention",
  "result": {
    "inspectionVersion": "1.0",
    "inspectionStatus": "complete-with-issues",
    "observationId": "observation-0123456789abcdef",
    "totals": {
      "sources": 8,
      "units": 42,
      "classified": 35,
      "unknown": 7,
      "needsUserReview": 11,
      "issues": 13
    },
    "sources": [
      {
        "evidenceId": "evidence-0001",
        "detectedType": "pdf",
        "inspectionStatus": "inspected",
        "unitCount": 6,
        "issueCodes": []
      }
    ],
    "units": [
      {
        "unitId": "unit-0001",
        "evidenceId": "evidence-0001",
        "unitKind": "pdf-page",
        "unitIndex": 1,
        "suggestedRole": "service-contract",
        "confidenceBand": "high",
        "needsUserReview": false,
        "inspectionMethod": "embedded-text",
        "signalCodes": [
          "service-contract-heading",
          "party-section-present",
          "signature-section-present"
        ],
        "issueCodes": []
      }
    ]
  },
  "errors": [],
  "retryable": false
}
```

### 10.1 Result status

`inspectionVersion` is exactly `1.0`.

`inspectionStatus` is:

- `complete` when every source and unit was accounted for and no inspection issue
  occurred; or
- `complete-with-issues` when complete accounting succeeded and every problem is
  represented in a source or unit issue record.

Confidence below `high` and a role of `unknown` affect review totals but are not by
themselves operational failures.

### 10.2 Source record

Every inventory item receives exactly one source record containing:

- `evidenceId`: the inventory evidence ID bound to this observation;
- `detectedType`: the conservative inventory type;
- `inspectionStatus`: `inspected`, `opaque`, `unsupported`, `unreadable`,
  `encrypted`, `over-limit`, or `not-applicable`;
- `unitCount`: non-negative authoritative count, or `null` when it cannot be
  established safely; and
- ordered `issueCodes`.

### 10.3 Unit record

Every safely enumerable unit contains:

- `unitId`: deterministic `unit-NNNN` in evidence order then unit index order;
- `evidenceId`: owning source record;
- `unitKind`: `pdf-page`, `worksheet`, or `image`;
- `unitIndex`: one-based page/sheet/image index; standalone images use `1`;
- `suggestedRole`: one fixed taxonomy role;
- `confidenceBand`: `high`, `medium`, `low`, or `none`;
- `needsUserReview`: deterministic Boolean derived from the review contract;
- `inspectionMethod`: `embedded-text`, `local-ocr`, `worksheet-structure`,
  `image-structure`, or `none`;
- ordered fixed `signalCodes`; and
- ordered fixed `issueCodes`.

No public record contains a filename, path, sheet name, extracted value, text
snippet, OCR confidence number, bounding box, cell coordinate, document title, or
personal datum.

## 11. Privacy boundary

Stdout and controlled stderr never include:

- absolute or relative paths;
- filenames or directory names;
- worksheet names;
- raw embedded text, cell values, formulas, or OCR output;
- names, identity numbers, tax identifiers, bank accounts, amounts, or dates;
- archive member names;
- rendered images, thumbnails, dimensions precise enough to reproduce content, or
  document metadata;
- private sort keys or parser diagnostics;
- raw exceptions, commands, environment values, usernames, or repository paths.

Only opaque evidence/unit/observation IDs, unit indexes, closed role/confidence
values, fixed signals, fixed issues, and bounded counts are model-facing.

Routine logs must follow the same boundary. Tests and documentation use generated
synthetic documents and identities only. Real client folders are never copied into
Git or test artifacts.

## 12. Resource limits

V1 uses these hard ceilings:

| Resource | Limit |
|---|---:|
| PDF source size | 256 MiB per file |
| Actual PDF pages | 10,000 per file |
| Embedded text examined | 64 KiB per PDF page |
| Workbook source size | 25 MiB per file |
| Worksheets | 100 per workbook |
| Cells examined | 100,000 per workbook |
| Cell text examined | 256 characters per cell |
| Standalone image size | 25 MiB per file |
| Decoded image area | 50 megapixels per image |
| OCR units | 500 per command |
| OCR wall time | 30 seconds per unit |
| Total OCR wall time | 30 minutes per command |
| Public unit records | 10,000 per command |
| Canonical JSON | 16 MiB including CLI envelope |

OCR is sequential in v1. This keeps CPU, memory, timeout, and ordering behavior
predictable.

An individual unit that exceeds an OCR or text-acquisition limit remains visible as
`unknown` with a safe issue when its existence and unit identity are already known.
A limit that prevents complete source/unit enumeration causes a controlled
operation failure. The command never returns an apparently complete truncated
list.

Parser input comes from one bounded immutable byte snapshot per source. Parsers do
not reopen source paths. Decompressed workbook and document structures receive
separate bounded counters so small compressed inputs cannot cause unbounded work.

## 13. Issue and failure semantics

Initial fixed issue families include:

- `opaque-archive`;
- `unsupported-document-type`;
- `document-unreadable`;
- `document-encrypted`;
- `document-over-limit`;
- `unit-over-limit`;
- `embedded-media-present`;
- `worksheet-hidden`;
- `ocr-unavailable`;
- `ocr-timeout`;
- `ocr-failed`;
- `ocr-low-confidence`;
- `classification-ambiguous`;
- `classification-conflict`; and
- inherited safe inventory issues.

### 13.1 Succeeded operation, exit `0`

The command succeeds with `complete` or `complete-with-issues` when it can honestly
account for every encountered source and every safely enumerable unit. Corrupt,
encrypted, unsupported, or opaque sources may therefore be represented as explicit
source issues without failing the whole batch.

### 13.2 Controlled operation failure, exit `2`

The command returns a fixed failed `inspect` envelope when complete accounting
cannot be proven, including:

- source tree or inspected snapshot changed;
- secure descriptor capability unavailable;
- root, traversal, source, combined-entry, or unit-count cap exceeded;
- PDF/workbook structure cannot be bounded before enumeration;
- parser or decompression behavior crosses a hard safety boundary; or
- canonical result would exceed 16 MiB.

Allowed public error codes are explicitly allowlisted at the CLI boundary.
Malformed or unknown internal codes fail closed as `internal-error`.

### 13.3 Invalid or unexpected failure, exit `1`

Invalid invocation and unexpected toolkit faults use exit `1`. They never expose a
raw exception, private path, filename, OCR text, parser message, or partial stdout.

The canonical response is buffered and size-checked before one stdout write.

## 14. WP interaction contract

WP:

- runs and verifies the three preflights;
- invokes the exact local `inspect` command;
- parses stdout JSON rather than inferring success from the exit code alone;
- keeps `observationId`, `evidenceId`, `unitId`, and unit indexes as the only
  references in model context;
- explains `complete`, `complete-with-issues`, and failed accounting distinctly;
- groups consecutive units with the same likely role when asking questions;
- always asks about medium/low/none confidence, unknown roles, conflicting signals,
  hidden worksheets, opaque archives, and source/unit issues;
- never silently excludes or assigns an unresolved unit; and
- requests explicit approval before any future preparation command writes derived
  files.

Example WP questions include:

> Pages 1–4 of evidence-0002 look like one service contract. Confirm this role?

> Worksheets 2 and 3 of evidence-0007 both resemble payment rosters. Which one
> should be authoritative?

> Eight units remain unknown. Review them now or keep them as unresolved evidence?

WP must not claim that a high-confidence role is correct, that an inspection issue
is harmless, or that successful inspection authorizes package preparation or
payment approval.

## 15. Components and ownership

The implementation remains in the standalone CTV toolkit:

- immutable inspection result model and canonical serialization;
- deterministic signal/classification core;
- bounded PDF, workbook, image, and OCR adapters;
- secure inspection orchestrator that composes fresh inventory with source/unit
  inspection and final revalidation;
- exact CLI dispatch and safe error mapping; and
- synthetic security, privacy, determinism, resource, and regression tests.

WP receives no bundled CTV runtime, extension, daemon, MCP server, or generated
toolkit. A WP agent later calls these local scripts on the user's machine.

## 16. Testing and acceptance

Tests use generated synthetic inputs only:

- embedded-text, scanned, mixed-role, encrypted, corrupt, oversized, and changing
  PDFs;
- visible, hidden, roster-like, supporting, corrupt, encrypted, oversized, and
  decompression-adversarial workbooks;
- identity-front-like, identity-back-like, supporting, ambiguous, corrupt,
  oversized, and decompression-adversarial images;
- archives whose member names and bytes would leak if opened;
- OCR unavailable, timeout, failure, low-confidence, and command-budget cases;
- conflicting/insufficient signals and every role/confidence transition;
- fresh observation rebinding after folder changes;
- descriptor races, symlink/special-file inputs, FD ownership, and final
  revalidation;
- exact no-write assertions, including no Python/Tesseract cache or temporary file
  in the source or working tree;
- complete result/error/log scans for paths, filenames, sheet names, raw text,
  identity patterns, amounts, dates, usernames, and parser diagnostics;
- byte-identical canonical JSON across unchanged calls;
- exact CLI surface, relocation, Unicode/spaced paths, and unrelated current
  directory;
- original preflight and inventory regression gates; and
- the complete existing backend, frontend, and production-build suites.

Acceptance requires:

1. every encountered inventory source has exactly one safe source record;
2. every safely enumerable PDF page, worksheet, and standalone image has exactly
   one unit record;
3. no truncation or skipped evidence can produce `complete`;
4. raw source or OCR content never reaches JSON, stderr, logs, tests, or Git;
5. classification is deterministic, fixed-taxonomy, and permits `unknown`;
6. all non-high-confidence and problematic units require user review;
7. archives remain opaque;
8. the operation creates no application file and never changes the source;
9. unchanged calls produce byte-identical output; and
10. existing CLI, package validator, application, and build behavior remain green.

## 17. Completion boundary

Completing this milestone proves only that the local CTV toolkit can securely
account for and classify supported document units with bounded privacy-safe
signals. It does not persist inspection state, accept user decisions, extract
archives, organize evidence, create a preparation proposal, write derived files,
build a package, validate a generated package, submit to CTV Review, or make any
payment decision.

The next admissible design milestone is the user-approved preparation proposal and
separate output-root write boundary.
