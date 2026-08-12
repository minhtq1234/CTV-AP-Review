# CTV Read-Only Folder Inventory Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a standalone, deterministic, read-only `inventory` CLI command that safely enumerates an explicit local batch folder and returns bounded opaque evidence records without exposing filenames or opening document semantics.

**Architecture:** Extend the existing CLI protocol with the `inventory` operation, define immutable inventory result types, isolate broad byte-signature detection in a pure module, and implement descriptor-bound traversal/hashing in a dedicated inventory engine. The existing CLI remains a thin dispatcher that converts engine results and safe engine errors into the established JSON envelope and exit conventions.

**Tech Stack:** Python 3.10+ standard library only for new inventory code; frozen dataclasses; descriptor-relative `os.open`/`os.stat`/`os.scandir`; SHA-256; pytest; existing npm/Vitest/Vite regression gates.

## Global Constraints

- Execute implementation in a new isolated worktree created from the reviewed `ver1` commit containing this plan. Require approved design commit `afab704` to be an ancestor, require this plan to be committed unchanged, and record the exact full base SHA before edits.
- Use branch `codex/ctv-read-only-inventory`. Do not implement in the active `ver1` checkout. Do not push, merge, release, deploy, or clean existing unrelated worktrees without separate authorization.
- Preserve the active checkout's untracked `.DS_Store` and `.superpowers/` paths. Each execution plan uses only its own ignored SDD workspace.
- Add no Python or JavaScript dependency. Do not modify `package.json`, `package-lock.json`, or the approved contract tree under `contracts/ctv-intake/v1/`.
- Make no WP repository change. Add no WP extension, MCP server, daemon, bundled runtime, automatic toolkit discovery, or global installation.
- The exact new CLI surface is `inventory --source-root <path> --json` in that order. Existing exact forms `version --json`, `doctor --json`, and `contract verify --json` remain unchanged.
- Inventory reads only an explicit source root. It performs no network access and creates no inventory, state, cache, temporary, report, lock, or output file.
- Inventory does not list/extract archive members; parse/count PDF pages; load workbook/image metadata; OCR; extract text; infer names, file purpose, ownership, roster status, or payment meaning; or invoke AI.
- Never serialize or print an absolute path, relative path, filename, directory name, private sort key, archive member, document content/metadata, raw exception, secret, PII, local username, or repository path.
- Secure traversal is descriptor-relative and fail-closed. Require `O_NOFOLLOW`, `O_DIRECTORY`, `O_NONBLOCK`, descriptor-relative open/stat, no-follow stat, and descriptor scandir. Never fall back to pathname reads.
- Consistency is defined at the command's final observation point. Mutations observed before that point are explicit item issues or controlled operation failures; changes after it are reflected by the next call. Do not claim post-return immutability.
- Hard defaults: depth 32; directories 2,000; regular files 10,000; total item records 10,000; combined encountered entries 12,000; sample 16 KiB; per-file full hash 256 MiB; aggregate hash 2 GiB; canonical JSON 16 MiB.
- Large and budget-exhausted regular files remain inventoried without a digest. Item problems continue with safe siblings only when every entry can still be honestly accounted for.
- A complete inventory, including `complete-with-issues`, uses succeeded envelope and exit `0`. A controlled condition preventing complete accounting uses failed envelope and exit `2`. Invalid invocation or unexpected toolkit failure uses exit `1`.
- No real client folder or copied real batch is used in implementation or committed tests. Acceptance uses synthetic fixtures only.

---

## File map

| File | Responsibility |
|---|---|
| `server/ctv_cli_protocol.py` | Permit the new stable `inventory` operation in the existing immutable envelope. |
| `server/ctv_cli_protocol_test.py` | Prove inventory envelopes remain canonical and old invariants unchanged. |
| `server/ctv_inventory_model.py` | Frozen limits, provisional/final item types, totals/result validation, safe serialization, deterministic IDs/groups. |
| `server/ctv_inventory_model_test.py` | Exact shapes, invariants, issue ordering, privacy-safe values, duplicate grouping, and defensive copies. |
| `server/ctv_inventory_detection.py` | Pure safe-extension normalization and bounded byte-signature classification. |
| `server/ctv_inventory_detection_test.py` | PDF/ZIP/XLSX-like/RAR/image/unknown/mismatch signature matrix. |
| `server/ctv_inventory.py` | Secure root opening, bounded traversal, stable snapshots, sample/hash reads, mutation handling, and inventory assembly. |
| `server/ctv_inventory_test.py` | Descriptor, race, privacy, limit, determinism, hash-budget, no-write, and archive-opacity tests. |
| `server/ctv_intake_cli.py` | Exact inventory argv recognition, engine dispatch, safe envelope/exit mapping, and output-size guard. |
| `server/ctv_intake_cli_test.py` | Subprocess, invalid surface, safe failures, alternate CWD, Unicode relocation, output limit, and static scope tests. |
| `server/README.md` | Terminal command, ordered preflight, opaque result semantics, limits, exit behavior, and non-approval warning. |

---

### Task 1: Inventory protocol and immutable result model

**Files:**

- Modify: `server/ctv_cli_protocol.py`
- Modify: `server/ctv_cli_protocol_test.py`
- Create: `server/ctv_inventory_model.py`
- Create: `server/ctv_inventory_model_test.py`

**Interfaces:**

- Consumes: existing `CliEnvelope`, `succeeded`, `failed`, and `canonical_json_bytes` behavior.
- Produces:
  - `InventoryLimits(max_depth=32, max_directories=2_000, max_regular_files=10_000, max_items=10_000, max_entries=12_000, sample_bytes=16*1024, max_hash_file_bytes=256*1024*1024, max_hash_total_bytes=2*1024*1024*1024, max_json_bytes=16*1024*1024)`
  - `DEFAULT_LIMITS: InventoryLimits`
  - `InventoryItemDraft(depth, extension, detected_type, size, sha256, hash_status, issue_codes)`
  - `InventoryItem(evidence_id, depth, extension, detected_type, size, sha256, hash_status, duplicate_group_id, issue_codes)`
  - `InventoryTotals(regular_files, directories, issues, total_bytes)`
  - `InventoryResult(inventory_version, inventory_status, totals, items)`
  - `InventoryResult.to_dict() -> dict[str, object]`
  - `assign_evidence_and_duplicate_ids(items: Sequence[InventoryItemDraft]) -> tuple[InventoryItem, ...]`
  - `ISSUE_ORDER: tuple[str, ...]` equal to `("symlink", "special-file", "unreadable", "changed-during-read", "type-detection-failed", "type-extension-mismatch", "hash-skipped-too-large", "hash-budget-exhausted")`

- [ ] **Step 1: Create the isolated worktree and verify the base**

From `/Users/lap16603/Documents/New project/work/CTV_APReview-v1`, invoke
`superpowers:using-git-worktrees`. Resolve `git rev-parse ver1^{commit}`, then run:

```bash
git merge-base --is-ancestor afab704 ver1
git diff --exit-code ver1 -- docs/superpowers/plans/2026-08-12-ctv-read-only-inventory.md
git ls-tree -r --name-only ver1 | rg '^docs/superpowers/plans/2026-08-12-ctv-read-only-inventory.md$'
```

Expected: all exit `0`. Record the resolved full `ver1` SHA as
`ctv_inventory_base`. Create an isolated sibling worktree at
`/Users/lap16603/Documents/New project/work/CTV_APReview-inventory` on branch
`codex/ctv-read-only-inventory` from exactly that commit.

- [ ] **Step 2: Run clean baselines before production edits**

In the isolated worktree:

```bash
git status --short --branch
cd server && python3 -m pytest -q
cd .. && npm ci
npm test
npm run build
git status --short --branch
```

Expected:

- clean tracked tree before and after setup;
- backend `425 passed`, with only the six existing deprecation warnings;
- frontend `130 passed`;
- production build exits `0`; and
- `npm ci` changes no tracked manifest or lockfile.

If any baseline fails, stop and report it as unverified; do not edit production
files.

- [ ] **Step 3: Write failing protocol and model tests**

First extend `server/ctv_cli_protocol_test.py` with:

```python
def test_inventory_is_a_supported_canonical_operation():
    envelope = succeeded(
        "inventory",
        "Inventory completed",
        {"inventoryVersion": "1.0", "items": []},
    )
    payload = json.loads(canonical_json_bytes(envelope))
    assert payload["operation"] == "inventory"
    assert payload["status"] == "succeeded"
```

Create `server/ctv_inventory_model_test.py` with exact model cases:

```python
import json

import pytest

from ctv_inventory_model import (
    DEFAULT_LIMITS,
    InventoryItem,
    InventoryItemDraft,
    InventoryResult,
    InventoryTotals,
    assign_evidence_and_duplicate_ids,
)


def _item(*, digest=None, size=12, issues=()):
    return InventoryItemDraft(
        depth=1,
        extension=".pdf",
        detected_type="pdf",
        size=size,
        sha256=digest,
        hash_status="computed" if digest else "not-applicable",
        duplicate_group_id=None,
        issue_codes=issues,
    )


def test_default_limits_are_the_approved_v1_values():
    assert DEFAULT_LIMITS.max_depth == 32
    assert DEFAULT_LIMITS.max_directories == 2_000
    assert DEFAULT_LIMITS.max_regular_files == 10_000
    assert DEFAULT_LIMITS.max_items == 10_000
    assert DEFAULT_LIMITS.max_entries == 12_000
    assert DEFAULT_LIMITS.sample_bytes == 16 * 1024
    assert DEFAULT_LIMITS.max_hash_file_bytes == 256 * 1024 * 1024
    assert DEFAULT_LIMITS.max_hash_total_bytes == 2 * 1024 * 1024 * 1024
    assert DEFAULT_LIMITS.max_json_bytes == 16 * 1024 * 1024


def test_exact_byte_duplicates_receive_deterministic_groups():
    digest = "a" * 64
    assigned = assign_evidence_and_duplicate_ids(
        (_item(digest=digest), _item(digest=digest), _item(digest="b" * 64))
    )
    assert [item.evidence_id for item in assigned] == [
        "evidence-0001", "evidence-0002", "evidence-0003"
    ]
    assert [item.duplicate_group_id for item in assigned] == [
        "duplicate-0001", "duplicate-0001", None
    ]


def test_inventory_result_serializes_the_exact_private_safe_shape():
    items = assign_evidence_and_duplicate_ids(
        (_item(issues=("type-extension-mismatch",)),)
    )
    result = InventoryResult(
        inventory_version="1.0",
        inventory_status="complete-with-issues",
        totals=InventoryTotals(
            regular_files=1, directories=2, issues=1, total_bytes=12
        ),
        items=items,
    )
    payload = result.to_dict()
    assert payload["inventoryVersion"] == "1.0"
    assert payload["inventoryStatus"] == "complete-with-issues"
    assert payload["totals"] == {
        "regularFiles": 1,
        "directories": 2,
        "issues": 1,
        "totalBytes": 12,
    }
    assert set(payload["items"][0]) == {
        "evidenceId", "depth", "extension", "detectedType", "size",
        "sha256", "hashStatus", "duplicateGroupId", "issueCodes",
    }
    assert "/" not in json.dumps(payload)
```

Add parameterized validation tests for:

- invalid inventory version/status;
- `complete` with item issues or `complete-with-issues` without any item issue;
- totals whose regular-file, issue, or byte counts disagree with the final items;
- depth outside `1..32`;
- unsafe extension values;
- invalid detected/hash status;
- malformed digest;
- digest present when status is not `computed` or absent when it is;
- duplicate group on an uncomputed digest;
- negative counts/sizes;
- more than 10,000 items;
- issue codes outside lower-case kebab case;
- duplicate issue codes or issue codes not ordered according to `ISSUE_ORDER`;
- mutable caller lists/dicts changed after model construction; and
- duplicate grouping exclusion for size mismatch, missing digest, and changed items.

- [ ] **Step 4: Run the tests to establish RED**

```bash
cd server
python3 -m pytest ctv_cli_protocol_test.py ctv_inventory_model_test.py -q
```

Expected: the protocol test fails because `inventory` is unsupported, and model
collection fails with `ModuleNotFoundError: No module named 'ctv_inventory_model'`.

- [ ] **Step 5: Implement the immutable model and protocol extension**

In `server/ctv_cli_protocol.py`, change only the operation allowlist:

```python
_OPERATIONS = frozenset({"version", "doctor", "contract.verify", "inventory"})
```

Create `server/ctv_inventory_model.py` with frozen dataclasses and these literal
domains:

```python
InventoryStatus = Literal["complete", "complete-with-issues"]
DetectedType = Literal["pdf", "xlsx", "zip", "rar", "image", "unknown"]
HashStatus = Literal[
    "computed", "skipped-too-large", "budget-exhausted", "not-applicable"
]
```

Use `copy.deepcopy` in construction and `to_dict()` as the existing CLI protocol
does. `InventoryItemDraft` is an immutable internal assembly value and has no
evidence or duplicate ID. `InventoryItem` is the public final record and always has
a valid evidence ID. Validate extensions against `unknown|\.[a-z0-9]{1,10}`, evidence IDs against
`evidence-[0-9]{4,}`, duplicate IDs against `duplicate-[0-9]{4,}`, digests against
lowercase 64-character SHA-256, and issue codes against lower-case kebab case.

`assign_evidence_and_duplicate_ids()` consumes drafts already in private sorted order,
assigns evidence IDs sequentially, groups only `hash_status == "computed"` items
with equal `(size, sha256)` and at least two members, then assigns group IDs by the
first member's order. It never reorders records.

`InventoryResult` validates that `regularFiles` equals the number of items with a
non-null regular-file size, `issues` equals the sum of item issue-code counts, and
`totalBytes` equals the sum of non-null item sizes. `complete` requires zero issues;
`complete-with-issues` requires at least one. Directory totals remain engine-supplied
because ordinary directories intentionally have no public records.

Every draft/final item validates issue codes against `ISSUE_ORDER`, rejects
duplicates, and requires their tuple to follow that exact order. This makes output
independent from the order in which sampling, type checks, and hash decisions were
performed.

- [ ] **Step 6: Run Task 1 GREEN and focused regressions**

```bash
cd server
python3 -m pytest ctv_cli_protocol_test.py ctv_inventory_model_test.py -q
python3 -m pytest \
  ctv_cli_protocol_test.py \
  ctv_contract_pin_test.py \
  ctv_cli_doctor_test.py \
  ctv_intake_cli_test.py \
  -q
```

Expected: all pass; output is pristine because these modules do not import document
libraries.

- [ ] **Step 7: Commit Task 1**

```bash
git add \
  server/ctv_cli_protocol.py \
  server/ctv_cli_protocol_test.py \
  server/ctv_inventory_model.py \
  server/ctv_inventory_model_test.py
git diff --cached --check
git diff --cached --name-status
git commit -m "feat(ctv): define inventory result protocol"
```

Expected: commit contains exactly these four files.

---

### Task 2: Conservative byte-signature detection

**Files:**

- Create: `server/ctv_inventory_detection.py`
- Create: `server/ctv_inventory_detection_test.py`

**Interfaces:**

- Consumes: a caller-supplied filename used privately and a byte sample already
  bounded to at most 16 KiB.
- Produces:
  - `safe_extension(private_name: str) -> str`
  - `detect_type(sample: bytes) -> DetectedType`
  - `extension_expected_type(extension: str) -> DetectedType | None`
  - `type_issue_codes(extension: str, detected_type: DetectedType, *, sample_failed: bool = False) -> tuple[str, ...]`

- [ ] **Step 1: Write the complete failing signature matrix**

Create `server/ctv_inventory_detection_test.py`:

```python
import pytest

from ctv_inventory_detection import (
    detect_type,
    extension_expected_type,
    safe_extension,
    type_issue_codes,
)


@pytest.mark.parametrize(
    ("sample", "expected"),
    [
        (b"%PDF-1.7\n", "pdf"),
        (b"prefix" + b"%PDF-2.0" + b"x" * 16, "pdf"),
        (b"PK\x03\x04rest", "zip"),
        (b"PK\x05\x06rest", "zip"),
        (b"PK\x07\x08rest", "zip"),
        (b"PK\x03\x04[Content_Types].xml xx xl/workbook.xml", "xlsx"),
        (b"Rar!\x1a\x07\x00rest", "rar"),
        (b"Rar!\x1a\x07\x01\x00rest", "rar"),
        (b"\x89PNG\r\n\x1a\nrest", "image"),
        (b"\xff\xd8\xffrest", "image"),
        (b"GIF87arest", "image"),
        (b"GIF89arest", "image"),
        (b"II*\x00rest", "image"),
        (b"MM\x00*rest", "image"),
        (b"RIFF\x04\x00\x00\x00WEBPrest", "image"),
        (b"not a known format", "unknown"),
    ],
)
def test_detect_type_uses_only_conservative_bounded_signatures(sample, expected):
    assert detect_type(sample) == expected


@pytest.mark.parametrize(
    ("private_name", "expected"),
    [
        ("PERSON.PDF", ".pdf"),
        ("archive.tar.gz", ".gz"),
        ("no-extension", "unknown"),
        ("bad.verylongextension", "unknown"),
        ("bad.địnhdạng", "unknown"),
        ("bad.<script>", "unknown"),
    ],
)
def test_safe_extension_never_returns_private_or_unsafe_text(private_name, expected):
    assert safe_extension(private_name) == expected


def test_mislabeled_supported_extension_reports_mismatch():
    assert extension_expected_type(".pdf") == "pdf"
    assert type_issue_codes(".pdf", "unknown") == ("type-extension-mismatch",)
    assert type_issue_codes(".pdf", "pdf") == ()
```

Add tests proving:

- PDF signature is accepted only within the first 1,024 sample bytes;
- malformed/truncated signatures remain `unknown`;
- XLSX requires both literal `[Content_Types].xml` and `xl/workbook.xml` in the
  bounded ZIP sample, otherwise remains `zip`;
- supported extension maps cover `.pdf`, `.xlsx`, `.xlsm`, `.xltx`, `.xltm`,
  `.zip`, `.rar`, `.png`, `.jpg`, `.jpeg`, `.gif`, `.tif`, `.tiff`, `.webp`;
- unknown extensions do not create mismatch issues;
- sample failure returns exactly `("type-detection-failed",)` and does not also
  claim a mismatch; and
- no returned extension or issue includes the input filename.

- [ ] **Step 2: Run detection tests to verify RED**

```bash
cd server
python3 -m pytest ctv_inventory_detection_test.py -q
```

Expected: collection fails with
`ModuleNotFoundError: No module named 'ctv_inventory_detection'`.

- [ ] **Step 3: Implement the pure detector**

Create `server/ctv_inventory_detection.py` with no filesystem, archive, PDF,
workbook, image-decoder, OCR, network, or AI imports.

Detection priority is:

1. PDF header anywhere in `sample[:1024]` matching `%PDF-[0-9].[0-9]`;
2. RAR 5 then RAR 4 exact leading signatures;
3. supported image leading signatures;
4. ZIP signatures, upgraded to `xlsx` only when the same bounded sample contains
   both `[Content_Types].xml` and `xl/workbook.xml` as literal ASCII bytes; and
5. `unknown`.

This `xlsx` result is a conservative container hint, not workbook validation. Do not
decompress or open any member.

`safe_extension()` uses only the last suffix after the final dot, lowercases it, and
returns it only when the complete value matches `\.[a-z0-9]{1,10}`.

- [ ] **Step 4: Run Task 2 GREEN and AST opacity checks**

```bash
cd server
python3 -m pytest ctv_inventory_detection_test.py -q
python3 - <<'PY'
import ast
from pathlib import Path

path = Path("ctv_inventory_detection.py")
tree = ast.parse(path.read_text(encoding="utf-8"))
roots = set()
for node in ast.walk(tree):
    if isinstance(node, ast.Import):
        roots.update(alias.name.split(".", 1)[0] for alias in node.names)
    elif isinstance(node, ast.ImportFrom) and node.module:
        roots.add(node.module.split(".", 1)[0])
forbidden = {
    "fitz", "openpyxl", "zipfile", "rarfile", "tarfile", "PIL",
    "pytesseract", "socket", "urllib", "http", "requests", "httpx",
}
assert roots.isdisjoint(forbidden), roots & forbidden
print("detector-import-boundary: PASS")
PY
```

Expected: all tests pass and the script prints
`detector-import-boundary: PASS`.

- [ ] **Step 5: Commit Task 2**

```bash
git add server/ctv_inventory_detection.py server/ctv_inventory_detection_test.py
git diff --cached --check
git commit -m "feat(ctv): detect broad inventory file types"
```

Expected: commit contains exactly the detector and its tests.

---

### Task 3: Secure bounded inventory engine

**Files:**

- Create: `server/ctv_inventory.py`
- Create: `server/ctv_inventory_test.py`

**Interfaces:**

- Consumes:
  - `InventoryLimits`, `DEFAULT_LIMITS`, `InventoryItemDraft`, `InventoryItem`, `InventoryTotals`,
    `InventoryResult`, and `assign_evidence_and_duplicate_ids` from
    `ctv_inventory_model`;
  - `safe_extension`, `detect_type`, and `type_issue_codes` from
    `ctv_inventory_detection`.
- Produces:
  - `InventoryError(code: str)` with public string equal only to its stable code;
  - `inventory_source(source_root: Path, *, limits: InventoryLimits = DEFAULT_LIMITS) -> InventoryResult`.

- [ ] **Step 1: Write basic deterministic inventory RED tests**

Create `server/ctv_inventory_test.py` with helpers that construct only synthetic
folders. Start with:

```python
import hashlib
import json
import os
from pathlib import Path
import socket
import stat

import pytest

from ctv_inventory import InventoryError, inventory_source
from ctv_inventory_model import InventoryLimits


def _small_limits(**overrides):
    values = dict(
        max_depth=4,
        max_directories=8,
        max_regular_files=16,
        max_items=16,
        max_entries=24,
        sample_bytes=16 * 1024,
        max_hash_file_bytes=1024,
        max_hash_total_bytes=4096,
        max_json_bytes=64 * 1024,
    )
    values.update(overrides)
    return InventoryLimits(**values)


def test_nested_files_are_deterministic_private_and_fully_hashed(tmp_path):
    source = tmp_path / "Khách hàng tuyệt mật"
    nested = source / "Tên người A"
    nested.mkdir(parents=True)
    first = source / "CCCD-012345678901.pdf"
    second = nested / "Bảng kê.xlsx"
    first.write_bytes(b"%PDF-1.7\nprivate")
    second.write_bytes(b"PK\x03\x04[Content_Types].xml xl/workbook.xml")

    one = inventory_source(source, limits=_small_limits())
    two = inventory_source(source, limits=_small_limits())

    assert one.to_dict() == two.to_dict()
    assert one.inventory_status == "complete"
    assert one.totals.regular_files == 2
    assert one.totals.directories == 1
    assert [item.evidence_id for item in one.items] == [
        "evidence-0001", "evidence-0002"
    ]
    serialized = json.dumps(one.to_dict(), ensure_ascii=False)
    for private in (str(tmp_path), source.name, nested.name, first.name, second.name):
        assert private not in serialized
    assert {item.detected_type for item in one.items} == {"pdf", "xlsx"}
    assert all(item.hash_status == "computed" for item in one.items)


def test_exact_duplicate_bytes_receive_one_group(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    content = b"%PDF-1.7\nsame"
    (source / "one.pdf").write_bytes(content)
    (source / "two.pdf").write_bytes(content)

    result = inventory_source(source, limits=_small_limits())

    assert [item.sha256 for item in result.items] == [
        hashlib.sha256(content).hexdigest(),
        hashlib.sha256(content).hexdigest(),
    ]
    assert {item.duplicate_group_id for item in result.items} == {
        "duplicate-0001"
    }
```

- [ ] **Step 2: Add RED tests for item continuation and hash limits**

Add cases proving:

- symlink item produces minimal record with `symlink`, safe siblings remain, and
  target bytes are never read;
- FIFO and Unix socket produce `special-file` without blocking;
- unreadable regular-file open (injected `PermissionError`) produces `unreadable`;
- sample read failure produces `type-detection-failed`;
- file larger than injected per-file limit is sampled, not fully hashed, and returns
  `skipped-too-large` plus `hash-skipped-too-large`;
- sorted eligible files consume an injected aggregate budget deterministically and
  later file returns `budget-exhausted` plus `hash-budget-exhausted`;
- size/digest mismatch, changed-during-read, skipped, and failed files never receive
  a duplicate group; and
- `complete-with-issues`, issue count, byte totals, and status remain honest.

Use injected small limits and monkeypatched descriptor reads/stat boundaries; do not
create 256 MiB or 2 GiB test files.

An unreadable or sample-failed regular file retains its known size and safe extension,
uses detected type `unknown`, `sha256: null`, `hashStatus: "not-applicable"`, and
cannot join a duplicate group. A changed-during-read record follows the same digest
and hash-status rules. Symlink and special-file records always use safe extension
`unknown`, regardless of the private entry suffix.

- [ ] **Step 3: Add RED tests for operation failures and race boundaries**

Add focused cases for:

- missing root, file root, symlink root, FIFO root, and replaced root;
- unsupported secure-open primitive;
- depth 5 with injected max 4;
- directory 9 with injected max 8;
- regular file 17 with injected max 16;
- total item 17 with injected max 16;
- combined entry 25 with injected max 24;
- unreadable directory enumeration;
- a regular candidate raced to FIFO before open is opened with `O_NONBLOCK` and
  rejected without hanging;
- file identity/size/time mutation during sample and hash;
- directory substitution and descendant mutation through the defined final
  observation point;
- serialized result exceeding injected `max_json_bytes`; and
- every controlled `InventoryError` string contains only a stable code and never
  the temporary absolute path.

For mutation during a file read, require one bounded refresh of the final regular
entry metadata: the record receives `changed-during-read`, no trusted digest, and
the final snapshot must stabilize to that refreshed metadata. A second mutation,
disappearance, or type change prevents complete accounting and raises
`InventoryError("inventory-tree-changed")`.

- [ ] **Step 4: Add RED no-write, opacity, and privacy tests**

Add tests that:

- snapshot source bytes, modes, modification times, names, and directory structure
  before/after success and controlled failure; access time is deliberately excluded;
- monkeypatch write-capable primitives (`open` with write flags, `os.write`,
  `os.mkdir`, `os.makedirs`, `os.rename`, `os.replace`, `os.unlink`) to fail if the
  engine calls them;
- poison `zipfile`, `tarfile`, PyMuPDF, OpenPyXL, Pillow, pytesseract, socket clients,
  and subprocess entry points and prove inventory never invokes them;
- include filenames with Vietnamese text, spaces, identity-like digits, control
  characters where the filesystem permits, and unusual suffixes, then scan the
  complete result and error strings for leaks; and
- prove ZIP/RAR contents and fake PDF/workbook inner strings do not appear in output.

- [ ] **Step 5: Run the engine tests to establish RED**

```bash
cd server
python3 -m pytest ctv_inventory_test.py -q
```

Expected: collection fails with
`ModuleNotFoundError: No module named 'ctv_inventory'`.

- [ ] **Step 6: Implement secure enumeration and private candidate facts**

Create `server/ctv_inventory.py` with no document/parser/network imports.

Use private frozen facts:

```python
@dataclass(frozen=True)
class _EntryFact:
    components: tuple[str, ...]
    private_sort_key: bytes
    depth: int
    kind: Literal["regular", "directory", "symlink", "special"]
    device: int
    inode: int
    mode: int
    size: int | None
    modified_ns: int
    changed_ns: int
```

Lexically normalize the caller path with `os.path.abspath` without resolving
symlinks. Starting from a trusted filesystem-root descriptor, open every normalized
path component with `O_RDONLY | O_DIRECTORY | O_NOFOLLOW | O_CLOEXEC`. Reject empty,
`.`/`..`, symlink, missing, and non-directory components. Prove each component is a
directory with `fstat` and retain the final source-root identity. Never call
`Path.resolve()` or follow an intermediate symlink. Enumerate iteratively with
descriptor `os.scandir(fd)`; never recurse through Python call depth and never
materialize more than the injected combined-entry cap.

For each child, use no-follow descriptor-relative stat. Classify only from mode.
Store private path components and POSIX UTF-8 sort bytes internally. Enforce depth,
directory, regular-file, item, and combined-entry limits before appending a fact.
Close every owned descriptor exactly once on success or error.

After enumeration, sort facts by `private_sort_key`. Directories contribute to the
directory total but not item records. Symlinks and special entries produce minimal
item facts in private order and are never opened.

- [ ] **Step 7: Implement descriptor-bound sample and hash processing**

To open a regular fact, start from the retained root descriptor and reopen each
private directory component with no-follow directory flags, checking `(st_dev,
st_ino)` against enumeration facts. Open the final file with
`O_RDONLY | O_NOFOLLOW | O_NONBLOCK | O_CLOEXEC`; then require regular type and exact
captured identity before reading.

Read at most `limits.sample_bytes`, classify the sample, then seek to byte zero for
eligible hashing. Stream SHA-256 in 64 KiB chunks with explicit per-file and
aggregate bounds. Require exact byte count and stable device, inode, mode, size,
mtime-ns, and ctime-ns before/after the read.

Processing rules:

- over per-file limit: sample only, skip full hash;
- insufficient aggregate budget: sample only, skip full hash;
- stable eligible file: sample and full hash;
- first detected mutation: discard sample/digest, refresh one stable no-follow
  regular-file fact, emit `changed-during-read`, and update the authoritative final
  snapshot for this path;
- second mutation, missing entry, or non-regular replacement: operation-level
  `inventory-tree-changed`.

Do not retain any sample bytes in a public model or error.

- [ ] **Step 8: Implement final revalidation and result assembly**

Perform one complete iterative descriptor-bound revalidation from the retained root
after all item processing. Compare private names, kinds, identities, modes, sizes,
mtime-ns, and ctime-ns against the authoritative snapshot, including the one bounded
refresh allowed above. At the final observation point, reopen the original selected
root component-by-component with the same no-follow routine and require its final
device/inode to match the retained descriptor. This detects rename/replacement of
the selected path without using the reopened path for traversal or file reads.

As approved, this proves consistency at that observation point only. Do not add an
impossible post-return mutation guarantee.

Build `InventoryItemDraft` values in private sorted order, assign final
evidence/duplicate IDs,
derive totals and `complete` versus `complete-with-issues`, and return
`InventoryResult`. Before returning, serialize the result dict using the same
canonical JSON settings and reject more than `limits.max_json_bytes` as
`inventory-output-too-large`; do not return truncation.

Map all expected OS failures to stable `InventoryError` codes. The exception stores
only `code` and uses that code as its public string. Never wrap or interpolate an OS
error or path.

- [ ] **Step 9: Run engine GREEN and focused regressions**

```bash
cd server
python3 -m pytest ctv_inventory_test.py -q
python3 -m pytest \
  ctv_cli_protocol_test.py \
  ctv_inventory_model_test.py \
  ctv_inventory_detection_test.py \
  ctv_inventory_test.py \
  ctv_contract_pin_test.py \
  -q
python3 -m py_compile \
  ctv_inventory_model.py \
  ctv_inventory_detection.py \
  ctv_inventory.py
```

Expected: all pass; only existing warnings may occur if unchanged contract tests
import PyMuPDF indirectly.

- [ ] **Step 10: Commit Task 3**

```bash
git add server/ctv_inventory.py server/ctv_inventory_test.py
git diff --cached --check
git commit -m "feat(ctv): inventory local source folders safely"
```

Expected: commit contains exactly the engine and its tests.

---

### Task 4: Exact CLI integration, synthetic smoke, and operator handoff

**Files:**

- Modify: `server/ctv_intake_cli.py`
- Modify: `server/ctv_intake_cli_test.py`
- Modify: `server/README.md`

**Interfaces:**

- Consumes:
  - existing canonical CLI protocol;
  - `inventory_source(source_root: Path) -> InventoryResult`;
  - `InventoryError(code: str)`.
- Produces:
  - exact command `inventory --source-root <path> --json`;
  - operation `inventory` envelopes;
  - `main(argv: list[str] | None = None) -> int` with existing exit conventions.

- [ ] **Step 1: Write failing inventory subprocess acceptance**

Extend `server/ctv_intake_cli_test.py`:

```python
def test_inventory_returns_private_canonical_json_from_unrelated_cwd(tmp_path):
    source = tmp_path / "Tên khách hàng tuyệt mật"
    source.mkdir()
    private_file = source / "CCCD-012345678901.PDF"
    private_file.write_bytes(b"%PDF-1.7\nprivate")
    unrelated = tmp_path / "unrelated"
    unrelated.mkdir()

    result = _run(
        "inventory", "--source-root", str(source), "--json", cwd=unrelated
    )

    payload = _envelope(result, "inventory", "succeeded")
    assert result.returncode == 0
    assert result.stderr == b""
    assert payload["result"]["inventoryStatus"] == "complete"
    assert payload["result"]["totals"]["regularFiles"] == 1
    serialized = json.dumps(payload, ensure_ascii=False)
    assert str(source) not in serialized
    assert source.name not in serialized
    assert private_file.name not in serialized
```

Add a second subprocess test that runs the exact command twice on an unchanged
synthetic folder and requires byte-identical stdout.

- [ ] **Step 2: Write failing safe failure and exact-surface tests**

Add in-process tests using monkeypatch/capsysbinary:

- `InventoryError("source-root-missing")` maps to failed `inventory` envelope,
  exit `2`, `retryable: false`, and safe fixed message;
- `InventoryError("inventory-tree-changed")` maps the same way without paths;
- unexpected error containing a private path maps only to `internal-error` and exit
  `1`;
- result canonical bytes over `DEFAULT_LIMITS.max_json_bytes` map to failed
  `inventory-output-too-large`, exit `2`, and no partial stdout; and
- `complete-with-issues` remains succeeded exit `0`.

Add subprocess parameterization rejecting empty/missing paths, abbreviated flags,
duplicate `--source-root` or `--json`, reordered tokens, extra tokens, and option-like
source strings. Every invalid form must exit `1`, write no stdout, emit bounded fixed
guidance, and never echo a supplied private path.

- [ ] **Step 3: Extend relocation and static-boundary tests**

Extend the existing Unicode/spaced toolkit copy test with a Unicode/spaced synthetic
source root and the inventory command.

Update static checks so:

- `ctv_inventory.py` and `ctv_inventory_detection.py` have no network, subprocess,
  document-parser, archive-parser, OCR, or AI import;
- CLI still has no subprocess/shell use;
- parser exposes `source-root` only on inventory, not on preflight commands; and
- exact argv validation accepts only the three preflight forms plus the five-token
  inventory form.

- [ ] **Step 4: Run CLI tests to establish RED**

```bash
cd server
python3 -m pytest ctv_intake_cli_test.py -q
```

Expected: inventory acceptance fails because the dispatcher rejects the new command.

- [ ] **Step 5: Integrate inventory without weakening exact argv**

In `server/ctv_intake_cli.py`:

- keep the existing three `_APPROVED_ARGV` forms unchanged;
- add `_is_inventory_argv(invocation: list[str]) -> bool` requiring exactly five
  tokens: `inventory`, `--source-root`, a non-empty path value that does not begin
  with `-`, and `--json`;
- reject every other sequence before argparse and never echo caller tokens;
- extend the parser with inventory `--source-root` as `Path` and required `--json`;
- import and call `inventory_source(args.source_root)` only for operation
  `inventory`;
- wrap `result.to_dict()` in `succeeded("inventory", safe_summary, result_dict)`;
- use summary `Inventory completed: <regularFiles> files, <issues> items need attention`
  where both values come from bounded numeric totals;
- map every `InventoryError` to a fixed safe message and exit `2`;
- keep unexpected exceptions at `internal-error`, exit `1`; and
- serialize once, enforce the 16 MiB canonical envelope limit before `_emit_stdout`,
  and never write partial JSON.

Because the engine already enforces its result limit, the CLI envelope guard is a
second boundary that includes summary/envelope overhead.

- [ ] **Step 6: Run CLI GREEN and direct synthetic smoke**

```bash
cd server
python3 -m pytest ctv_intake_cli_test.py -q
synthetic_root=$(mktemp -d /private/tmp/ctv-inventory-smoke.XXXXXX)
mkdir "$synthetic_root/Nested"
python3 - "$synthetic_root" <<'PY'
from pathlib import Path
import sys

root = Path(sys.argv[1])
(root / "a.pdf").write_bytes(b"%PDF-1.7\nsynthetic")
(root / "Nested/archive.zip").write_bytes(b"PK\x03\x04synthetic")
PY
python3 ctv_intake_cli.py inventory --source-root "$synthetic_root" --json
```

Expected: tests pass; smoke command exits `0`, returns two opaque item records, and
does not print the temporary source path or filenames. The shell fixture is under
`/private/tmp` and is not committed. Do not delete it with a broad recursive command;
leave cleanup to the temporary-directory policy or remove only the resolved explicit
`synthetic_root` after validating it.

- [ ] **Step 7: Document the inventory handoff**

Add `### Inventorying a source folder` beneath the existing standalone-toolkit
section in `server/README.md`. Include:

- ordered preflight followed by the exact inventory command;
- explicit source-root selection and no automatic discovery;
- opaque IDs and absence of filenames/paths;
- broad type/signature and exact-byte duplicate semantics;
- archives remain unopened;
- large/hash-budget files remain listed without a digest;
- item issues versus operation-level completeness failures;
- limits 32 / 2,000 / 10,000 / 12,000 / 16 KiB / 256 MiB / 2 GiB / 16 MiB;
- read-only/no-state/no-network boundary;
- evidence IDs are not stable after folder changes; and
- inventory success does not establish document completeness, case assignment, or
  payment approval.

Do not document inspection, extraction, OCR, organization, package creation, or WP
assistant behavior as implemented.

- [ ] **Step 8: Run full candidate acceptance before staging**

Run:

```bash
cd server
python3 -m pytest -q
cd ..
npm test
npm run build
python3 server/ctv_intake_cli.py version --json
python3 server/ctv_intake_cli.py doctor --json
python3 server/ctv_intake_cli.py contract verify --json
git diff --check
ctv_inventory_base=$(git merge-base ver1 HEAD)
git rev-parse --verify "$ctv_inventory_base^{commit}"
git diff --exit-code "$ctv_inventory_base" -- contracts/ctv-intake/v1
git status --short
```

Expected:

- all prior 425 backend tests plus all new inventory tests pass;
- frontend 130 passes;
- build exits `0`;
- all three original preflight commands still succeed;
- contract tree is unchanged; and
- tracked tree contains only planned changes.

Run exact scope and leak scans:

```bash
changed=$(git diff --name-only "$ctv_inventory_base")
printf '%s\n' "$changed"
if rg -n '/Users/|CTV AP GAS|FA-PM[0-9]|@vng|BEGIN (RSA |EC |OPENSSH )?PRIVATE KEY' \
  server/ctv_cli_protocol.py \
  server/ctv_inventory_model.py \
  server/ctv_inventory_detection.py \
  server/ctv_inventory.py \
  server/ctv_intake_cli.py \
  server/README.md; then exit 1; fi
```

Expected changed paths are exactly the eleven files in this plan's file map. The
leak scan returns no matches. Inspect added test strings separately and require only
obviously synthetic identities.

- [ ] **Step 9: Commit Task 4**

```bash
git add server/ctv_intake_cli.py server/ctv_intake_cli_test.py server/README.md
git diff --cached --check
git diff --cached --name-status
git commit -m "feat(ctv): expose read-only inventory CLI"
```

Expected: commit contains exactly the dispatcher, integration tests, and README.
Leave the branch unpushed and unmerged for independent task and whole-branch review.

- [ ] **Step 10: Re-run final acceptance on the committed head**

Run fresh on the exact committed tree:

```bash
cd server
python3 -m pytest -q
cd ..
npm test
npm run build
python3 server/ctv_intake_cli.py version --json
python3 server/ctv_intake_cli.py doctor --json
python3 server/ctv_intake_cli.py contract verify --json
git diff --check
git diff --exit-code "$ctv_inventory_base"...HEAD -- contracts/ctv-intake/v1
git status --short --branch
```

Expected: the same green counts and checks as Step 8 on the committed head, with no
tracked or staged changes. Only the plan-specific ignored SDD workspace may be
present. Record exact outputs in the Task 4 report before whole-branch review.

---

## Completion boundary

Completing this plan proves only that the standalone CTV toolkit can safely and
privately inventory one explicit local source folder through deterministic opaque
JSON. It does not persist inventory state, expose filenames, open archives, inspect
documents, perform OCR, infer roles or ownership, organize files, create or validate
prepared packages, modify WP, submit to CTV Review, or approve/reject payment.

The next admissible design activity is safe document inspection and classification.
Do not begin it under this plan.
