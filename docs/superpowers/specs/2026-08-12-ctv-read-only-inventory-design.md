# CTV Read-Only Folder Inventory — Design

**Date:** 2026-08-12

**Status:** Approved design; implementation not started

**Product owner:** CTV/AP Review

**Consumers:** WePrompt agents and local operators

## 1. Decision

Extend the standalone CTV local CLI with one read-only folder-inventory command.
The command safely enumerates an explicitly selected batch folder and returns a
bounded, privacy-preserving map of opaque evidence records.

This is the second local-toolkit milestone after the preflight CLI foundation. It
does not inspect document semantics, open archives, create working state, organize
files, or modify any source.

The command is directly usable from Terminal. WePrompt (WP) remains the
conversational orchestrator and receives no CTV runtime, contract, extension, MCP
server, or generated bundle.

## 2. Product purpose

Real CTV/AP batches contain inconsistent nested folders, multiple unrelated files,
opaque archives, large documents, unsupported formats, and unreadable or unsafe
entries. Before an agent can ask useful questions, the toolkit must establish what
was received without trusting filenames, silently skipping evidence, or exposing
personal data to the model.

The inventory milestone answers only:

- how many directories and files were encountered;
- which broad file types are present;
- which regular files were fully hashed;
- which files are exact-byte duplicates; and
- which entries could not be handled safely.

It does not answer which FA case owns a file, whether a workbook is a roster, which
people appear in evidence, whether a packet is complete, or whether payment evidence
is correct.

## 3. Command and preflight

Add one exact CLI form:

```bash
python3 server/ctv_intake_cli.py inventory \
  --source-root "/path/to/batch" \
  --json
```

`--source-root` is an explicit caller-selected local directory. The CLI does not
search the computer, use the shell search path, choose among repository copies, or
infer a batch folder from the current directory.

Before a WP agent calls inventory, it must successfully run the existing preflight
sequence against the same toolkit:

1. `version --json`;
2. `doctor --json`; and
3. `contract verify --json`.

The CLI accepts the inventory arguments only in the exact order shown. Abbreviated,
duplicated, reordered, missing, or extra options are invalid invocations: exit `1`,
empty stdout, and bounded fixed guidance on stderr.

Inventory uses operation identifier `inventory` in the existing `1.0` CLI envelope.
Adding the operation extends the documented operation allowlist but does not change
the envelope schema.

## 4. Filesystem trust boundary

Inventory is read-only and stateless:

- open the selected source root once and bind traversal to that descriptor;
- traverse only descriptor-relative children beneath that root;
- never follow a symlink;
- open regular-file candidates with nonblocking, no-follow flags before type checks;
- use `fstat` to prove regular-file identity and type;
- reject special files such as sockets, devices, and FIFOs without blocking;
- never create an inventory cache, report, state, temporary, lock, or output file;
- never modify permissions, names, contents, modification times, or application
  metadata; ordinary read access may affect access time if the host filesystem
  applies that policy;
- never invoke a package manager or start a service; and
- never access the network.

The command uses the same fail-closed secure-open capability boundary as the
contract verifier. Unsupported platforms return a controlled failure instead of
falling back to pathname-based reads.

Traversal maintains directory and entry identities across the operation. A replaced
root, escaped path, changed entry, or structurally inconsistent tree cannot yield a
successful complete inventory.

Consistency is defined at the command's final observation point. Mutations observed
before that point fail or become explicit item issues as defined below. Changes after
the final observation are reflected by the next inventory call. The command does not
claim post-return filesystem immutability.

## 5. Archive and document boundary

This milestone treats archives and documents as opaque regular files.

It may:

- read a bounded leading byte sample for conservative broad-type detection; and
- stream regular-file bytes for SHA-256 within the hashing limits.

It may not:

- list or extract ZIP or RAR members;
- parse PDF objects or count PDF pages;
- load workbook metadata, sheets, cells, drawings, or embedded images;
- decode or OCR images;
- extract text, titles, names, identity numbers, or other document content; or
- infer file purpose, case ownership, roster status, or payment meaning.

No PyMuPDF document open, OpenPyXL workbook load, archive reader, image decoder, OCR
engine, or AI model participates in inventory.

## 6. Stable result model

The command uses the existing CLI envelope:

```json
{
  "schemaVersion": "1.0",
  "operation": "inventory",
  "status": "succeeded",
  "summary": "Inventory completed: 8 files, 2 items need attention",
  "result": {
    "inventoryVersion": "1.0",
    "inventoryStatus": "complete-with-issues",
    "totals": {
      "regularFiles": 8,
      "directories": 3,
      "issues": 2,
      "totalBytes": 1452000
    },
    "items": [
      {
        "evidenceId": "evidence-0001",
        "depth": 1,
        "extension": ".pdf",
        "detectedType": "pdf",
        "size": 840000,
        "sha256": "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef",
        "hashStatus": "computed",
        "duplicateGroupId": null,
        "issueCodes": []
      }
    ]
  },
  "errors": [],
  "retryable": false
}
```

### Inventory result

`inventoryVersion` is exactly `1.0`.

`inventoryStatus` is:

- `complete` when traversal completes with no item issues; or
- `complete-with-issues` when traversal completes and every encountered problem is
  represented safely.

`totals` contains:

- `regularFiles`: number of regular-file records;
- `directories`: number of directories beneath the selected root; the root itself
  is not counted;
- `issues`: number of item issue occurrences, not merely affected items; and
- `totalBytes`: sum of `size` for accepted regular-file records, independent of
  whether a full hash was computed.

`items` contains one record for every accepted regular file. Unsafe non-regular
entries also receive a minimal issue record so their existence is accounted for.
Ordinary directories contribute only to totals and do not receive records.

### Item shape

Every item contains:

- `evidenceId`: deterministic run-local identifier `evidence-NNNN`;
- `depth`: one-based depth beneath the source root;
- `extension`: normalized safe extension or `unknown`;
- `detectedType`: `pdf`, `xlsx`, `zip`, `rar`, `image`, or `unknown`;
- `size`: non-negative bytes for a proven regular file, otherwise `null`;
- `sha256`: lowercase digest only when `hashStatus` is `computed`, otherwise `null`;
- `hashStatus`: `computed`, `skipped-too-large`, `budget-exhausted`, or
  `not-applicable`;
- `duplicateGroupId`: deterministic `duplicate-NNNN` or `null`; and
- `issueCodes`: ordered stable lower-case kebab-case codes.

Minimal records for symlinks and special files use `extension: "unknown"`,
`detectedType: "unknown"`, `size: null`, `sha256: null`,
`hashStatus: "not-applicable"`, and no duplicate group.

## 7. Privacy and opaque identity

Model-facing stdout and controlled stderr never include:

- absolute paths;
- relative paths;
- original filenames or directory names;
- private sort keys;
- archive member names;
- document text, metadata, titles, sheet names, or PDF page counts;
- guessed personal names, case names, or file roles;
- raw exception text; or
- local usernames or repository paths.

Extensions are normalized to lowercase and returned only when the complete suffix
matches `^\.[a-z0-9]{1,10}$`. All other suffixes become `unknown`. A returned
extension is only a syntax hint and does not override byte-based type detection.

The command privately sorts entries by the UTF-8 bytes of normalized POSIX relative
paths and assigns sequential evidence IDs. Private paths are never serialized.

Evidence IDs are deterministic only for an unchanged sorted inventory. Adding,
removing, or renaming an entry may renumber IDs. They are not durable external IDs
and must not be stored or referenced across changed inventory runs. Durable source
identity belongs to a later working-state milestone.

## 8. Broad type detection

Type detection reads at most the first 16 KiB of an eligible regular file from the
same opened descriptor used for identity checks. It uses conservative byte
signatures, not filename extension trust.

The v1 categories are:

- `pdf`: a valid PDF header signature within the allowed leading signature window;
- `xlsx`: an OOXML ZIP container identified conservatively from the bounded sample
  without opening members; because the sample cannot prove workbook semantics, the
  classification may remain `zip` unless the bounded signature is conclusive;
- `zip`: ZIP signature;
- `rar`: supported RAR 4 or RAR 5 signature;
- `image`: common PNG, JPEG, GIF, TIFF, or WebP signature; and
- `unknown`: no supported signature.

The detector does not claim semantic validity. A matching signature means only that
the bytes resemble the broad container or format.

If the normalized extension implies one supported category but the byte signature
is different or unknown, the detected bytes govern and the item receives
`type-extension-mismatch`. The file remains inventoried.

A safe failure while reading the detection sample results in `type-detection-failed`
and an explicit item record when the file can still be accounted for safely.

## 9. Hashing and duplicate signals

Eligible regular files at or below 256 MiB are streamed through SHA-256 from the
already opened descriptor. No single read buffers the full file.

The total full-hash budget is 2 GiB per inventory run. Private sorted order governs
budget allocation so unchanged folders produce identical decisions.

- A file larger than 256 MiB uses `hashStatus: "skipped-too-large"`, no digest, and
  issue `hash-skipped-too-large`.
- An otherwise eligible file that would exceed the remaining 2 GiB budget uses
  `hashStatus: "budget-exhausted"`, no digest, and issue
  `hash-budget-exhausted`.
- Special or unsafe entries use `hashStatus: "not-applicable"`.

Sampling and hashing verify the descriptor's identity, size, modification time, and
change time before and after reads. A detected mutation produces
`changed-during-read`; the item has no digest and cannot join a duplicate group.

Files with the same computed SHA-256 and size form an exact-byte duplicate group.
Groups are ordered by the first member's private inventory order and receive
`duplicate-NNNN`. A group is assigned only when at least two records match.

A duplicate group is a signal only. Inventory never deletes, hides, excludes,
merges, or designates a preferred copy.

## 10. Ordering and determinism

Traversal and output do not depend on filesystem enumeration order. The toolkit
collects bounded private entry facts, normalizes relative paths to POSIX separators,
sorts by their UTF-8 bytes, and then performs ordered sampling and hashing.

For an unchanged source tree and runtime, repeated calls return byte-identical
canonical JSON except for no timestamp because inventory returns no time-dependent
field.

Issue codes use a stable deterministic order defined by the implementation contract,
not discovery or exception order. Duplicate groups and evidence IDs are also
deterministic from private sorted order.

## 11. Limits

Inventory v1 enforces these hard limits:

- maximum traversal depth beneath the root: 32;
- maximum directories beneath the root: 2,000;
- maximum regular-file records: 10,000;
- maximum total item records, including unsafe entries: 10,000;
- type-detection sample per eligible file: 16 KiB;
- full-hash size per file: 256 MiB;
- aggregate bytes fully hashed per run: 2 GiB; and
- maximum serialized item records: 10,000.

Directory enumeration is streamed and bounded before an entire attacker-controlled
directory can be materialized. The implementation also caps the combined entries
encountered during traversal at 12,000 so directories and unsafe entries cannot
bypass the individual record limits.

The JSON payload is structurally bounded by the fixed item shape, safe strings, and
10,000-record limit. The implementation must additionally verify canonical output
does not exceed 16 MiB before writing stdout. An oversized result fails safely with
no partial JSON.

The command does not silently truncate. A depth, directory, entry, record, or output
limit prevents an honest complete inventory and therefore returns an operation-level
failure.

## 12. Item issues and operation failures

### Item issues

These issues allow inventory to complete while retaining safe siblings:

- `symlink`;
- `special-file`;
- `unreadable`;
- `changed-during-read`;
- `type-detection-failed`;
- `type-extension-mismatch`;
- `hash-skipped-too-large`; and
- `hash-budget-exhausted`.

If traversal accounts for every encountered entry within all limits, item issues
produce `status: "succeeded"`, exit `0`, and
`inventoryStatus: "complete-with-issues"`. `retryable` remains `false` because the
operation completed honestly; the agent may decide whether a user action justifies
a later rerun.

### Controlled operation failures

These conditions prevent an honest complete inventory and return `status: "failed"`
with exit `2`:

- source root missing, unsafe, replaced, or not a directory;
- secure descriptor-relative traversal unavailable;
- depth, directory, entry, record, or output limit exceeded;
- directory enumeration unreadable or inconsistent;
- a tree mutation invalidates the final inventory snapshot; or
- a bounded structural condition prevents complete accounting.

The failure envelope contains stable safe codes and an empty or explicitly
non-authoritative result. It never returns a truncated list that appears complete.

Invalid invocation and unexpected toolkit failure return exit `1`. Unexpected
failures expose only `internal-error` and a fixed safe message.

## 13. Testing and acceptance

### Read-only enumeration

- Nested regular files produce complete deterministic opaque records.
- The same unchanged folder produces byte-identical canonical JSON twice.
- Adding, removing, or renaming an entry produces a new deterministic inventory.
- The source tree's bytes, modes, modification times, names, and directory structure
  remain unchanged after success and controlled failure. Access time is excluded
  because it is controlled by the host filesystem's read policy.
- No inventory, state, temporary, report, lock, or output file is created. Tests
  assert this within the selected source tree and the CLI's application-owned
  locations; interpreter-managed bytecode caches outside the source tree are not an
  inventory artifact.

### Privacy

- Absolute paths, relative paths, filenames, folder names, file contents, and raw
  exception strings do not appear in stdout or controlled stderr.
- Vietnamese names, spaces, identity-like filenames, unusual suffixes, and hostile
  control characters remain private.
- Opaque evidence IDs and duplicate-group IDs are deterministic.

### Filesystem safety

- Missing, file, symlink, replaced, and unreadable roots fail safely.
- Symlinks, FIFOs, sockets, devices, and concurrent regular-to-special replacements
  do not block, escape, or become normal file records.
- Files changed during sample or hash reads receive no trusted digest.
- Directory substitution and descendant mutation are detected through the defined
  final observation point.
- Unsupported secure-open primitives fail closed.

### Limits

- Depth 33, directory 2,001, regular file 10,001, combined entry 12,001, and item
  record 10,001 cases fail before unbounded work.
- A 256 MiB file remains hash-eligible; a file one byte larger is listed with
  `skipped-too-large` without a full read.
- The 2 GiB aggregate hash boundary is deterministic and enforced before the next
  file read would exceed it.
- Directory enumeration and JSON serialization remain within the stated caps.

### Detection and hashing

- PDF, ZIP, RAR 4, RAR 5, PNG, JPEG, GIF, TIFF, WebP, OOXML-like, mislabeled, and
  unknown binary samples receive conservative expected classifications.
- Archives are never opened or extracted.
- Document parsers, OCR, AI, and network clients are never invoked.
- Hashes match an independent SHA-256 calculation for eligible stable files.
- Exact-byte duplicates receive deterministic groups; size/digest mismatch,
  uncomputed hashes, and changed files never group.

### CLI integration

- The exact inventory argv succeeds from unrelated working directories.
- Unicode/spaced toolkit and source-root paths work.
- Missing, abbreviated, duplicated, reordered, and extra options are rejected.
- Parsed operations return canonical JSON and consistent exit/status behavior.
- Existing `version`, `doctor`, and `contract verify` behavior remains unchanged.

### Regression gates

- The complete backend suite passes; the current merged baseline is 425 tests with
  six pre-existing deprecation warnings.
- The frontend suite passes 130 tests.
- The production frontend build passes.
- A synthetic messy folder passes before any copied real batch is used.
- No real client file, path, PII, secret, dependency output, WP code, or unrelated
  change is committed.

## 14. Milestone boundaries

### Included

- exact inventory CLI surface;
- secure bounded source-root traversal;
- broad byte-signature classification;
- bounded SHA-256 and exact-byte duplicate signals;
- opaque item identity and privacy-safe JSON;
- item-level issue continuation;
- honest operation-level completeness failures; and
- direct Terminal documentation and tests.

### Excluded

- durable inventory or working-state files;
- original filenames or paths in model-facing output;
- archive-member listing or extraction;
- PDF page counts or parsing;
- workbook, image, or text inspection;
- OCR or AI classification;
- case grouping, roster identification, or evidence ownership;
- file transformation, renaming, copying, deletion, or organization;
- prepared-package creation or validation through inventory;
- WP repository changes or WP assistant instructions;
- direct submission to CTV Review; and
- payment approval or rejection.

## 15. Next milestone

After inventory is implemented, independently reviewed, and accepted against a
synthetic messy folder, the next design milestone is safe document inspection and
classification. It may consume opaque evidence IDs during one unchanged inventory
snapshot but must introduce its own authorization, parser limits, privacy model, and
error-recovery contract.

Inventory completion does not authorize that next milestone automatically.
