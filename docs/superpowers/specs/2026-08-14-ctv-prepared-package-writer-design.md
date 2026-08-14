# CTV Transactional Prepared-Package Writer Design

**Date:** 2026-08-14

**Status:** Design decisions approved; written specification awaiting confirmation

**Base:** local `ver1` after the lean proposal-review workflow

**Compatibility target:** `ctv-intake-v2`

## Decision

Add one transactional local command that turns a fully resolved, locally approved
proposal into a validated CTV intake package:

```text
WP agent
  -> runs local `ctv-intake package prepare`
  -> toolkit observes and inspects the selected source folder read-only
  -> user reviews and approves the proposal in the existing local screen
  -> toolkit builds inside a private staging directory
  -> toolkit validates the package and revalidates the source observation
  -> toolkit atomically publishes one new package directory
  -> toolkit returns bounded privacy-safe JSON to WP
  -> WP explains the result; it does not submit the package to CTV
```

The exact public command is:

```bash
python3 /local/path/to/CTV_APReview-v1/server/ctv_intake_cli.py \
  package prepare \
  --source-root /explicit/local/source \
  --output-root /explicit/local/output-parent \
  --json
```

The existing `proposal review` command remains a read-only preview/dry-run. It
does not persist a plan and does not create a package.

## Why this is contract v2

The v1 package contract records source coverage and artifacts, but it cannot
durably express:

- which normalized unit belongs to which participant;
- the approved evidence role;
- individual, shared, or case scope;
- the output location of non-PDF evidence; or
- the complete set of explicit exclusions.

The writer therefore requires a new `assignments.json` artifact and adds repeatable
`evidence` artifacts. Those are breaking changes for a strict v1 consumer, so the
writer targets `ctv-intake-v2` rather than widening v1 in place.

Implementation must preserve every checked-in byte below
`contracts/ctv-intake/v1/`. V2 lives below `contracts/ctv-intake/v2/`, has its own
schemas, synthetic fixtures, compatibility document, and exact tree hash. The
legacy root `PIN.json` keeps its v1 meaning; v2 uses separate version-addressed pin
metadata at `contracts/ctv-intake/PIN.v2.json`. That file has exactly
`compatibilityTarget`, `sourceCommit`, and `contractTreeSha256`, with the same
exact-commit hashing rules applied to `contracts/ctv-intake/v2/`. WP copies and
reviews the exact v2 tree as a new immutable snapshot. A
v1 consumer is not allowed to claim compatibility with a v2 package.

## Scope

This milestone includes:

- the v2 package, assignment, roster, exception, and validation-report contract;
- deterministic transformation of approved PDF pages, the selected roster,
  images, and non-roster worksheets;
- one transactional package builder and safe publisher;
- v2 semantic validation and canonical validation reporting;
- the combined local review-and-prepare CLI lifecycle;
- bounded, privacy-safe terminal results for WP; and
- generated end-to-end acceptance tests.

This milestone does not include:

- a WP plugin bundle, skill bundle, or copied runtime;
- direct submission to CTV or ACC;
- AI-generated FA codes, participant identities, or missing evidence;
- partial or unresolved prepared packages;
- persisted drafts, resume, background jobs, or a database;
- automatic multi-case splitting;
- archive extraction or arbitrary input conversion;
- user-selected artifact filenames or directory names;
- overwrite, merge, in-place update, or cleanup of older output packages;
- mutation of the selected source folder;
- new network services, non-loopback traffic, or new runtime dependencies.

WP agents call the installed local script. All source content, previews, roster
values, and prepared artifacts remain on the local machine.

## Threat and guarantee boundary

This writer inherits the lean review boundary and additionally defends against
malformed source/package content, path and symlink substitution, output-name
races, partial writes, bounded resource exhaustion, and source/staging mutations
observed at their final revalidation points. The atomic no-replace publication
primitive closes the final-name collision race.

This milestone does not claim an OS-level immutable filesystem snapshot. A
malicious process already running as the same OS user could alter an owned `0700`
staging directory in the syscall interval after the final tree rewalk, just as it could inspect this
process's memory. Same-interpreter reflection, memory tampering, kernel/filesystem
compromise, and that post-linearization same-user attack are outside this
milestone. Package bytes are nevertheless built only from retained immutable
source snapshots, and ordinary/concurrent mutation before the declared final
points fails closed.

## User flow

1. WP runs `version --json`, `doctor --json`, and
   `contract verify --target ctv-intake-v2 --json`. The existing exact
   `contract verify --json` form remains the v1 verification path.
2. The command resolves and securely retains one source observation.
3. It validates that the source root and output parent are existing, separate,
   non-overlapping directory trees.
4. It performs the existing bounded inspection without modifying the source.
5. It opens the existing authenticated loopback review screen.
6. The user selects one authoritative roster and resolves every unit and
   source-only record.
7. The screen allows approval only when the proposal is complete and internally
   consistent.
8. Draft or cancel closes the observation and returns without creating staging or
   output content.
9. Approval freezes the proposal digest in memory. The writer derives opaque
   deterministic package identities from that approved state.
10. The writer creates a fresh private staging directory beneath the output
    parent and builds the complete v2 package from retained snapshots.
11. The capability-aware validator validates the staged package against the
    retained source observation.
12. The writer writes the canonical validation report and validates the complete
    staged tree again.
13. The source observation performs its final close-time revalidation.
14. The writer atomically renames staging to the deterministic final package
    directory.
15. The CLI emits one bounded JSON result. No artifact contents or local absolute
    paths are returned to WP.

`package prepare` repeats the v2 contract verification internally before opening
the source observation, so a caller cannot bypass the pin check by skipping the
recommended WP preflight.

## Approval gate

Writing is authorized only by an `approved` proposal produced during the same
command and retained observation. The proposal must satisfy all lean-review rules
and these writer-specific rules:

- every inspected unit is `accepted`, `reassigned`, or `excluded`;
- every source-only record is explicitly excluded;
- no unit or source remains `unknown` or `unresolved`;
- exactly one usable roster worksheet is selected;
- the selected roster is a case-scope `payment-roster` unit;
- every participant target resolves to a row in that selected roster;
- at least one PDF page is included in `input.pdf`;
- the roster contains one unambiguous non-empty case-wide FA code; and
- the approved proposal digest still matches the displayed summary.

The writer never turns a draft, cancel, partially resolved proposal, or validator
warning into implicit approval. High-confidence inspection remains a suggestion;
the human decision is still required.

## Package identity

V2 uses opaque deterministic identifiers. The canonical identity input is:

```text
schema version
compatibility target
writer version
source observation ID
approved proposal digest
```

Canonical JSON encoding of those fixed fields is SHA-256 hashed. Domain-separated
prefixes derive `packageId`, `batchId`, and `caseId`. Public identifiers contain no
source name, filename, participant value, FA code, path, timestamp, or random
token.

The final directory name is `ctv-package-<short-package-id>`, where the short form
is the first 24 lowercase hexadecimal characters (96 bits) of the domain-separated
package digest. The manifest retains the full 64-character digest. Repeating the
same approved preparation therefore selects the same final name. If that name
already exists, the command returns a controlled collision and never opens,
modifies, merges, or replaces the existing directory.

`faCode` is copied only from the selected normalized roster. All usable roster
rows must yield the same exact non-empty case-wide FA code. Missing, conflicting,
or ambiguous values block preparation before the first staging write. The toolkit
does not infer, repair, or invent an FA code.

## Published layout

Each successful run publishes exactly one directory:

```text
ctv-package-a83f19c2d4e6b7019fa2012c/
  case-manifest.json
  input.pdf
  roster.xlsx
  assignments.json
  exceptions.json
  validation-report.json
  evidence/
    evidence-0001.png
    evidence-0002.xlsx
```

The `evidence/` directory may be empty, but `input.pdf`, `roster.xlsx`,
`assignments.json`, and `exceptions.json` are always present. Filenames are fixed
or opaque and deterministic. Original filenames are never used as artifact
filenames.

The only allowed published paths are the fixed files above and bounded opaque
members under `evidence/`. Symlinks, aliases, sockets, devices, FIFOs, nested
directories, undeclared evidence files, and extra top-level files are invalid.

`validation-report.json` is a generated receipt, not a manifest artifact. It is
not declared or digest-pinned inside the manifest, avoiding a circular self-hash.
The validator recognizes only that exact fixed receipt path and rejects other
undeclared content.

## V2 manifest

The v2 manifest retains the v1 source, PDF-page, provenance, decision, roster,
exception, and validator concepts, with these normative changes:

- `schemaVersion` is `2.0`;
- `compatibilityTarget` is `ctv-intake-v2`;
- `packageId` is required;
- `sourceObservationId` and `proposalDigest` are required;
- `status` is exactly `prepared` for writer output;
- identity-bearing manifest and decision records contain no timestamp;
- v1 `validatedAt` moves from the manifest to the undeclared validation receipt;
- manifest `packageVersion` is the exact writer version and `validatorVersion`
  remains the exact deterministic validator version;
- artifact kinds add `assignments` and repeatable `evidence`;
- exactly one `input-pdf`, `roster`, `assignments`, and `exceptions` artifact is
  required;
- zero or more `evidence` artifacts are allowed;
- `cccd` remains reserved for compatible external producers but is not emitted
  by this writer; and
- `validation-report` is no longer a declared artifact in writer output.

Every v2 artifact record carries `formatVersion: "2.0"`. Manifest,
`assignments.json`, `exceptions.json`, and `validation-report.json` each use
`schemaVersion: "2.0"`. The canonical roster workbook is identified by its
artifact `formatVersion` and the v2 canonical-roster schema; it does not add a
hidden metadata sheet.

V2 replaces the v1 decision enum with the fixed writer decisions
`accept-unit`, `reassign-unit`, `exclude-unit`, `exclude-source`,
`select-roster`, and `approve-proposal`. A decision contains a deterministic
decision ID, proposal version/digest, actor `user`, and bounded opaque subject
references. It contains no timestamp or display value. `accepted`, `reassigned`,
and exclusion records in `assignments.json` map one-to-one to those manifest
decision types; the selected roster and final approval each have one additional
manifest decision.

Every single-instance kind is unique. `evidence` is the only repeatable artifact
kind. Artifact IDs, source IDs, decision IDs, participant handles, roster row IDs,
and unit IDs are independently unique and follow fixed bounded formats.

Artifact provenance is exact: the input-PDF `sourceIds` are the distinct included
PDF sources in inspection order; the roster has only the selected workbook source;
each evidence artifact has only its originating image/workbook source; generated
assignments and exceptions artifacts have an empty `sourceIds` array. No artifact
may name an unmaterialized or merely excluded source.

The manifest lists every inspection source. A `verified-content` source has its
safe source-relative path, bounded size, digest, verified media type, actual PDF
page count when applicable, coverage state, and decision reference. An
`unacquired-exclusion` source represents a symlink, special, unreadable,
unsupported, encrypted, or over-limit source-only record that the observation
could not bind to bytes. It has the opaque source ID, safe relative path when one
was observed, fixed acquisition status and issue codes, null size/digest/page
count, excluded coverage, and one exclusion decision. It cannot appear in any
artifact `sourceIds`. These private provenance fields remain in the local package;
they are not returned in CLI JSON.

In v2, source coverage is a derived summary rather than the assignment authority.
An entirely excluded source is `excluded-by-user` (or `duplicate` when every unit
has that reason); a source whose included units are all shared is `shared`; any
other resolved source with included units is `assigned`. Exact per-unit and
per-page disposition comes from `assignments.json` and `pdfPages`. A source-level
`decisionId` is used only for a source-only disposition; it is null for a unitized
source whose decisions are recorded per unit.

`sourceObservationId` is the deterministic identity of the verified source tree.
`proposalDigest` is the exact digest approved in the same local review session.
The manifest, assignment artifact, writer expectation, and package-identity
derivation must agree on both values.

## `assignments.json`

`assignments.json` is the durable human-approved preparation map. Its canonical
shape is:

```json
{
  "schemaVersion": "2.0",
  "packageId": "package-opaque-full-id",
  "sourceObservationId": "observation-opaque-full-id",
  "proposalDigest": "lowercase-sha256",
  "rosterArtifactId": "artifact-roster",
  "participants": [
    {
      "participantHandle": "participant-0001",
      "rosterRowId": "roster-row-0001"
    }
  ],
  "units": [
    {
      "unitId": "unit-0001",
      "sourceId": "source-0001",
      "sourceUnitIndex": 1,
      "unitKind": "pdf-page",
      "decisionId": "decision-0001",
      "decision": "accepted",
      "role": "payment-evidence",
      "target": {
        "scope": "individual",
        "participantHandles": ["participant-0001"]
      },
      "outputLocator": {
        "kind": "pdf-page",
        "artifactId": "artifact-input-pdf",
        "targetPage": 1
      }
    }
  ],
  "exclusions": [
    {
      "recordType": "unit",
      "recordId": "unit-0009",
      "decisionId": "decision-0009",
      "reason": "duplicate"
    }
  ]
}
```

All key sets are closed and all arrays are bounded. The exact v2 schema defines
the existing role and exclusion enums rather than accepting arbitrary strings.

### Participants

- One participant record exists for each usable row of the selected normalized
  roster, in roster order.
- `participantHandle` is the opaque handle used during review.
- `rosterRowId` is the stable opaque ID written into `roster.xlsx`.
- Names, identities, bank details, and other roster values do not appear in
  `assignments.json`.
- A row is ignored only when every bounded cell in the roster region is blank.
  Any nonblank row with a missing, duplicate, malformed, truncated, or otherwise
  unusable required participant value blocks approval; the writer never silently
  filters that person out.

### Units

- Every included inspected unit appears exactly once in `units`.
- The selected roster unit appears with role `payment-roster`, case scope, and a
  locator to the roster artifact.
- An accepted unit retains the inspected suggested role; a reassigned unit uses
  the explicit replacement role.
- Individual scope has exactly one handle; shared scope has at least two distinct
  handles in roster order; case scope has no handles.
- Output locators are typed:
  - PDF page: input-PDF artifact ID and one `targetPage`;
  - roster: roster artifact ID and normalized worksheet index `1`;
  - image: one evidence artifact ID;
  - worksheet: one evidence workbook artifact ID and one output worksheet index.
- No included unit may lack an output locator.
- Every unit `decisionId` resolves to one manifest user decision whose type,
  evidence references, and proposal version agree with the assignment.

### Exclusions

- Every excluded unit or source-only record appears exactly once.
- The record uses only its opaque ID and fixed exclusion reason.
- Excluded bytes are never copied into a published artifact.
- Exclusions are user decisions, not exceptions and not validator waivers.
- Every exclusion `decisionId` resolves to the corresponding manifest user
  exclusion decision.

## Deterministic transformations

All transformation inputs come from the retained, bounded, digest-verified
observation. The writer never reopens an untrusted source pathname independently.
It does not modify, rename, quarantine, annotate, or repair source files.

Output serialization uses fixed metadata, canonical JSON key ordering and UTF-8
encoding, fixed archive member ordering/timestamps, and fixed PDF/image save
settings. JSON uses compact separators, LF, and one terminal newline. PNG uses
8-bit RGBA, stripped ancillary chunks, fixed filter selection, compression level
9, and no optimization pass. OOXML uses lexicographically ordered members, fixed
1980-01-01 ZIP timestamps, fixed permissions, fixed Deflate level, and canonical
values-only XML. PDF serialization clears volatile metadata, uses fixed save
options/object ordering, and derives the trailer ID from canonical page inputs.
The supported dependency versions are part of `writerVersion`. Volatile
application metadata and source timestamps are removed. For
the same contract/writer version, observation, and approved proposal, the
manifest, every declared artifact, and their digests must be byte-identical. Only
the undeclared validation receipt may contain its contract-required validation
time, and that time is not an input to deterministic package identity.

### PDF

`input.pdf` contains every included source PDF page exactly once. Physical page
order is:

1. case-scope pages;
2. shared-scope pages;
3. individual-scope pages grouped by selected roster order.

Within each group, pages retain deterministic inspection source order and source
unit index. A shared page is referenced by multiple participants in one assignment
but appears physically only once. An included source page maps to one contiguous
`targetPage` value, and every physical target page is mapped exactly once.

The writer does not OCR, rasterize, redact, enhance, or synthesize PDF content.
Existing bounded PDF inspection and parser rules still apply. A package with no
included PDF page is rejected before staging.

### Roster

`roster.xlsx` is a new single-sheet, values-only workbook built from the selected
worksheet snapshot. It contains:

- one fixed opaque `Roster Row ID` column;
- the recognized canonical roster columns required by the v2 roster schema; and
- only usable participant rows, in original selected-sheet order.

The workbook contains no formulas, macros, external links, hidden sheets, hidden
rows/columns, drawings, comments, named ranges, or copied workbook metadata. The
sheet name is fixed. Cell values and types are bounded and canonicalized by the
contract. Formula cells contribute their already inspected cached values only
when that bounded value is available; otherwise preparation is blocked rather
than recalculating or inventing data.

The manifest roster mapping records the selected source and recognized columns.
Assignments bind participant handles to the new opaque roster row IDs.

### Images

Each included image becomes one deterministic evidence artifact. It is decoded
through the existing bounded image path, orientation-normalized, metadata-stripped,
and encoded as PNG with fixed settings. The output name is the corresponding
opaque evidence artifact sequence.

### Non-roster worksheets

Included worksheets from the same source workbook are written to one values-only
evidence workbook. Only included worksheets appear. Output sheet order follows
source unit index; output sheet names are fixed opaque names. Assignments point to
the artifact and one-based output worksheet index.

The same removal rules as the roster apply: no formulas, macros, links, hidden
content, drawings, comments, names, or copied metadata. A source workbook with no
included worksheet produces no evidence artifact.

Across images and workbooks, evidence artifact sequence numbers follow original
source inspection order. An image source produces at most one PNG artifact, and a
workbook source produces at most one evidence workbook. This ordering is
independent of UI click order.

### Unsupported input

An inspected unit kind without a normative output transformation cannot be
included. It must be explicitly excluded or the proposal remains unresolved.
The writer does not fall back to raw copying.

## Cross-validation

V2 validation is mechanical and fail-closed. In addition to all applicable v1
checks, it proves:

- the manifest, assignment, roster, exception, and validation-report schemas;
- exact compatibility target and package identity coherence;
- exact required artifact cardinality and evidence-only repeatability;
- safe relative paths, regular files, bounded sizes, digests, and no extra files;
- actual verified-content source size, digest, media type, and PDF page count
  against the retained source; unacquired exclusions are checked structurally
  without opening or following their unsafe entries;
- exact source and PDF-page coverage with no hidden or duplicate page;
- contiguous input-PDF target pages equal to the actual derived page count;
- every assignments participant resolves to exactly one normalized roster row;
- every assignment source, unit, decision, artifact, and output locator resolves;
- every included unit has exactly one assignment and every excluded record has
  exactly one exclusion;
- every evidence artifact has at least one assignment and every evidence locator
  points to the artifact's actual content position;
- assignment role is compatible with unit kind and accept/reassign semantics;
- scope cardinality and roster-order canonicalization;
- the selected roster, FA code, and manifest roster mapping agree;
- `proposalDigest` and package identity agree with the approved writer inputs;
- `exceptions.json` is empty for this fully resolved writer path; and
- report outcome, checks, errors, warnings, version, and package status agree.

Validation may produce warnings, but this writer publishes only when the outcome
is `valid`, status is `prepared`, there are no errors, and no warning represents
unresolved evidence or a required human decision. The contract describes this
mechanical result; it does not claim the evidence is authentic or payment-ready.

During preparation, the validator receives the expected observation ID and
approved proposal digest through a capability-aware in-process entrypoint. That
entrypoint consumes the writer's already retained package reader and source
observation; it does not reopen either pathname. It requires exact agreement with
the manifest and assignment artifact. The separate standalone CLI validator opens
its own secure package/source readers once, then calls the same reader-owned core.
It recomputes the source observation ID from the verified source root, checks
internal proposal-digest equality and package-identity derivation, and validates
every materialized assignment. A standalone package cannot by itself
cryptographically prove that a particular human approved the original browser
session; the contract does not make that claim.

Validation has two explicit phases:

1. **Content validation** requires `validation-report.json` to be absent. It
   validates the manifest and every declared artifact and returns canonical
   content checks plus `manifestSha256` and a digest of the ordered declared
   artifact IDs, paths, sizes, and hashes.
2. **Publication validation** requires the receipt. It recomputes content
   validation, validates the receipt schema, and requires the receipt's
   observation ID, proposal digest, package ID, `manifestSha256`, artifact-set
   digest, content outcome, and ordered content checks to match. It then adds one
   fixed `validation-report-consistent` check.

The receipt records the content-validation result, not its own hash and not the
publication-only receipt check. This avoids self-reference while allowing a later
standalone validator to prove that the receipt still describes the package bytes.

## Resource ceilings

V2 never raises the existing inspection ceilings. Writer and validator enforce,
before and during acquisition:

- at most 10,000 inspected units and 25,000 package PDF pages;
- at most 256 MiB for `input.pdf`;
- at most 25 MiB for the roster or any one evidence artifact;
- at most 16 MiB each for manifest, assignments, exceptions, and validation
  report JSON;
- at most 1,000 evidence artifacts; and
- at most 1 GiB for every regular file in the staged/published package combined.

The exact v2 contract publishes these constants. Attempted bytes count against
aggregate work even when a file later fails stability or validation, so retrying
failed reads inside one run cannot bypass the ceiling. The builder stops before a
write or parser call that would cross a limit and returns a fixed safe code.

## Transaction and filesystem boundary

The output parent must already exist. It is opened securely and retained for the
entire write transaction. Source and output are rejected when either path is the
same directory, an ancestor of the other, resolves through a symlink, is not a
regular directory tree, or cannot support the required descriptor-relative and
atomic operations.

The transaction is:

1. Complete all pre-write proposal, roster, FA-code, identity, collision, and
   capacity checks.
2. Create one randomly named hidden staging directory directly under the retained
   output parent, mode `0700`.
3. Create only descriptor-relative regular files with no-follow semantics, mode
   `0600`; create the evidence directory mode `0700`.
4. Write bounded content to fresh temporary files, flush, validate size/digest,
   and rename them to their fixed staging names.
5. Fsync every declared file and staging directory where supported by the
   declared platform.
6. Run v2 content validation through the retained package/source capabilities.
7. Write canonical `validation-report.json` through the same fresh-temporary,
   flush, fsync, and rename path, then fsync the staging directory.
8. Run publication validation with the receipt present; require a valid outcome
   and the fixed receipt-consistency check.
9. Perform the retained source observation's final revalidation. Any mutation
    observed at that linearization point invalidates the transaction.
10. Immediately before publication, rewalk the exact retained staging directory,
    verify its inode/capability and complete allowlisted tree digest, and require
    it to equal the tree just publication-validated. `publishedTreeSha256` uses
    the contract's portable sorted relative-path plus file-digest tree algorithm
    and includes the undeclared receipt.
11. Atomically rename the retained staging directory to the deterministic final
    directory within the same retained output parent using a descriptor-relative
    no-replace primitive, then fsync the parent. If atomic no-replace is
    unavailable, fail closed.

The final name is never used as a build directory. The command never overwrites,
deletes, empties, or recursively cleans an existing final directory.

The source guarantee is linearized at the final revalidation point: the package
was built from the retained immutable snapshots and the selected tree still
matched them at that point. A later external edit to the user's source folder
cannot alter the published package, but the toolkit does not claim to freeze or
control the user's folder after the command completes.

On a handled failure, cleanup targets only the exact staging directory created by
that run, after verifying its retained identity. A crash may leave a hidden staging
directory. Later runs ignore and never reuse it; automatic broad stale-staging
cleanup is outside this milestone. A hidden staging directory is not a prepared
package and is not returned to WP.

Publication is the atomic rename. Before it, no final package exists. After it,
the entire validated package exists. Once publication succeeds, the internal
outcome is `prepared` and later cleanup must not delete the package. The CLI
attempts to emit the prepared result; if stdout itself fails, it cannot guarantee
delivery of JSON, but the published package remains intact and a retry reaches the
deterministic collision boundary rather than overwriting it.

## CLI outcomes

### Exit 0

- `prepared`: one new package was atomically published.
- `draft`: review ended without approval; no staging or output package exists.
- `cancelled`: user cancelled; no staging or output package exists.

### Exit 2

Controlled operational or validation failure, including source mutation, unsafe
or unavailable output boundary, collision, bounded resource rejection, build
failure, validation failure, or cleanup failure. It returns one fixed safe error
code and no partial proposal or package path.

### Exit 1

Invalid invocation or unexpected internal failure. It returns the existing
bounded internal-error shape without private exception text.

### Prepared JSON

The success result contains only:

- protocol version and outcome `prepared`;
- full opaque `packageId` and opaque final directory name;
- exact `manifestSha256`, `declaredArtifactSetSha256`,
  `publishedTreeSha256`, and contract version;
- bounded source, participant, PDF-page, evidence-artifact, assignment, and
  exclusion counts;
- validation outcome and fixed check/warning codes;
- `readyForCtvReview: true`.

It excludes absolute and relative source paths, output-parent path, original
filenames, FA code, participant names/identities, roster values, assignment display
labels, evidence contents, preview data, OCR text, tokens, ports, timestamps, raw
parser errors, and staging names.

Draft and cancelled results retain their existing lean-review privacy boundary and
do not reveal or imply an output location.

## Components

Implementation should remain in focused local modules:

1. `ctv_package_assignment.py`: v2 assignment model, canonical serialization,
   proposal-to-assignment conversion, and cross-reference helpers.
2. `ctv_package_builder.py`: deterministic PDF, roster, image, worksheet, manifest,
   exception, and assignment generation from retained snapshots.
3. `ctv_package_writer.py`: safe output-parent capability, staging transaction,
   validation/report sequence, cleanup, and atomic publication.
4. Existing intake contract/export/validator modules: version dispatch, v2 schemas,
   semantic validation, deterministic fixture export, and v1 regression support.
5. Existing proposal-review and CLI modules: same-session approval handoff, combined
   command lifecycle, bounded result, and documentation.

The public boundary is the CLI. WP invokes the local command; it does not import
these modules, copy scripts into WP, or receive local content.

## Testing and acceptance

All fixtures use generated synthetic data. No real participant, ACC, CTV, payment,
identity, bank, or customer data is checked in or logged.

### Contract tests

- v1 exported bytes and validator behavior remain unchanged;
- v2 schema/export determinism and exact commit-tree hashing;
- required assignments artifact and evidence multiplicity;
- strict closed shapes, enums, bounds, uniqueness, and path rules;
- old v1 consumer rejects v2 and v2 dispatch does not reinterpret v1;
- WP pin documentation uses the exact reviewed v2 commit and tree digest.

### Transformation tests

- exact PDF page order, one-to-one source/target coverage, shared-page nonduplicate,
  minimum one-page rule, and parser/resource caps;
- values-only roster, fixed row IDs, exact column mapping, FA-code agreement, and
  removal of formulas/macros/links/hidden content/metadata;
- deterministic normalized image PNG bytes;
- values-only evidence workbooks, grouping, ordering, and locator indices;
- excluded and unsupported bytes never appear in output;
- repeated generated runs yield byte-identical declared artifacts and digests.

### Transaction tests

- no staging before approval; draft/cancel/unresolved create nothing;
- source/output overlap, symlink, replacement, non-directory, FIFO, and unsafe
  capability rejection;
- collision never opens or changes existing output;
- build, flush, validation, report, source-revalidation, and rename failures leave
  no final package and clean only the run-owned staging directory;
- controlled source/output mutation before the respective final revalidation
  point fails closed;
- atomic visibility: readers see no final path or the complete final tree;
- source entry set, regular-file bytes, symlink text, mode, size, and modification
  time are unchanged; filesystem-managed access time is explicitly excluded;
- published output survives terminal-emission failure.

### Semantic validator tests

- participant, roster row, source, unit, decision, artifact, and locator integrity;
- exact PDF and evidence coverage;
- role/unit and decision semantics;
- individual/shared/case cardinality;
- empty writer exceptions and completed positive validation checks;
- malformed, oversized, duplicate, missing, extra, swapped, and privacy-sensitive
  data fail with fixed codes and bounded I/O.

### CLI and end-to-end tests

- exact command, lazy imports, canonical JSON, exit codes, and privacy scanning;
- real generated browser review through approval to a published package;
- a second run proves deterministic collision without overwrite;
- generated package validates through the public validator with `--source-root`;
- WP-facing result contains only approved safe fields;
- full Python suite, frontend suite, production build, `py_compile`, diff/scope,
  placeholder/PII, deterministic export, and exact-commit tree-hash gates.

Each implementation slice receives an independent review. The exact final head
receives a whole-flow review and generated smoke test before local integration.
No push, release, or WP pin update is implied by passing local acceptance.

## Acceptance boundary

This milestone is complete when a user can select a local folder through WP,
review the inspected evidence in the local screen, approve a fully resolved
proposal, and receive a newly published, locally validated v2 package in the
chosen output parent—without source mutation, partial output, private-data leakage
to WP, overwrite, or direct submission.

The prepared package is ready for the existing CTV human review workflow. It is
not evidence authenticity proof, accounting approval, payment authorization, or
automatic submission.
