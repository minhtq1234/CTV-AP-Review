# CTV Local CLI Foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deliver a standalone, read-only CTV command-line foundation that identifies its approved contract, checks its local runtime, verifies the canonical contract tree, and returns deterministic JSON for WP agents or Terminal users.

**Architecture:** Keep `server/ctv_intake_cli.py` as a thin command dispatcher over three focused modules: a JSON response protocol, an immutable contract-pin verifier, and a dependency/capability doctor. Resolve repository resources relative to the CLI file, never the caller's working directory. The CTV repository remains the only runtime and contract owner; WP receives no code, extension, bundle, or copied contract.

**Tech Stack:** Python 3.10+ standard library, existing PyMuPDF (`fitz`), OpenPyXL, Pydantic 2, pytest, existing npm/Vitest/Vite frontend gates.

## Global Constraints

- Execute implementation in an isolated worktree created from the reviewed `ver1` commit that contains this plan. Before creating it, require `e0a947d` to be an ancestor, require this plan to be a committed unchanged blob, and record the resolved full base SHA in the implementer report. Do not implement in the active `ver1` checkout.
- Create branch `codex/ctv-local-cli-foundation` at execution time. Do not push, release, deploy, merge, or change WP without separate authorization.
- Preserve the existing untracked `.DS_Store` and `.superpowers/` paths in the active checkout.
- Add no CTV runtime, dependency, validator, extension, MCP server, generated bundle, or contract snapshot to the WP repository.
- Add no new Python or JavaScript dependency. `doctor` inspects the dependencies already required by the canonical validator.
- Perform no network request, package installation, background-service launch, user-document discovery, OCR, transformation, or package write from the foundation CLI.
- Standard output for a successfully parsed `--json` command is exactly one UTF-8 JSON object plus one newline. Do not print banners, logs, warnings, stack traces, or paths to stdout.
- Never expose a repository absolute path, document name, document content, raw exception, secret, or PII in an envelope or controlled diagnostic.
- Use exit `0` only for a succeeded check, exit `2` for a completed user-correctable check failure, and exit `1` for invalid invocation or an unexpected toolkit failure.
- Keep `contracts/ctv-intake/v1/` byte-for-byte unchanged. Store pin metadata at `contracts/ctv-intake/PIN.json`, outside the hashed tree.
- Pin exactly:
  - `sourceCommit`: `75b3b3bc7e3d4edef1b24a0cfc9bb6c039320f3a`
  - `contractTreeSha256`: `83d0523ffdf871d79597310d2a24424c8bb17b6fcdb208d9bf28afc70da6900d`
  - `compatibilityTarget`: `ctv-intake-v1`
- Do not run `npm audit fix` or make unrelated dependency changes. If baseline installation or tests fail, record the failure as unverified and stop before production edits.

---

## File map

| File | Responsibility |
|---|---|
| `server/ctv_cli_protocol.py` | Immutable envelope/error types and canonical JSON serialization. |
| `server/ctv_cli_protocol_test.py` | Exact schema, ordering, UTF-8, newline, and mutation-isolation tests. |
| `contracts/ctv-intake/PIN.json` | Reviewed source commit, aggregate tree hash, and compatibility target. |
| `server/ctv_contract_pin.py` | Strict pin parsing plus bounded, deterministic hashing of every regular `v1/` file. |
| `server/ctv_contract_pin_test.py` | Complete/modified/missing/added/unsafe tree and malformed-pin tests. |
| `server/ctv_cli_doctor.py` | Dependency API and secure-open capability probes without document or network access. |
| `server/ctv_cli_doctor_test.py` | Healthy, missing, incompatible, and secure-open-unavailable probes. |
| `server/ctv_intake_cli.py` | Argument parsing, command dispatch, exit mapping, and stdout emission only. |
| `server/ctv_intake_cli_test.py` | Subprocess and in-process acceptance tests, including alternate CWD and Unicode paths. |
| `server/README.md` | Human and WP-agent invocation, semantics, and explicit non-approval warning. |

---

### Task 1: Canonical JSON response protocol

**Files:**

- Create: `server/ctv_cli_protocol.py`
- Create: `server/ctv_cli_protocol_test.py`

**Interfaces:**

- Consumes: Python standard library only.
- Produces:
  - `CliError(code: str, message: str)`
  - `CliEnvelope(schema_version, operation, status, summary, result, errors, retryable)`
  - `succeeded(operation: str, summary: str, result: Mapping[str, object]) -> CliEnvelope`
  - `failed(operation: str, summary: str, errors: Sequence[CliError], *, retryable: bool, result: Mapping[str, object] | None = None) -> CliEnvelope`
  - `canonical_json_bytes(envelope: CliEnvelope) -> bytes`

- [ ] **Step 1: Create the isolated execution worktree and capture the baseline**

From `/Users/lap16603/Documents/New project/work/CTV_APReview-v1`, invoke `superpowers:using-git-worktrees`. Resolve `git rev-parse ver1^{commit}`, verify `git merge-base --is-ancestor e0a947d ver1`, verify `git diff --exit-code ver1 -- docs/superpowers/plans/2026-08-12-ctv-local-cli-foundation.md`, and confirm the plan exists in `git ls-tree -r --name-only ver1`. Record that resolved full SHA as the implementation base, then create a sibling isolated worktree on `codex/ctv-local-cli-foundation` from exactly that SHA without modifying or cleaning the current checkout.

In the new worktree run:

```bash
git status --short --branch
cd server && python3 -m pytest -q
cd .. && npm ci
npm test
npm run build
```

Expected before production edits:

- worktree has no tracked or untracked changes;
- backend baseline passes (`341 passed`, with the six existing deprecation warnings acceptable);
- frontend baseline passes (`130 passed`);
- production build exits `0`;
- `npm ci` does not modify `package.json` or `package-lock.json`.

- [ ] **Step 2: Write failing protocol tests**

Create `server/ctv_cli_protocol_test.py` with these concrete cases:

```python
import json

from ctv_cli_protocol import CliError, canonical_json_bytes, failed, succeeded


def test_success_envelope_is_exact_canonical_utf8_json():
    envelope = succeeded(
        "doctor",
        "Bộ công cụ CTV đã sẵn sàng",
        {"pythonVersion": "3.14.3"},
    )

    content = canonical_json_bytes(envelope)

    assert content.endswith(b"\n")
    assert content.count(b"\n") > 1  # canonical, indented single JSON object
    assert json.loads(content) == {
        "schemaVersion": "1.0",
        "operation": "doctor",
        "status": "succeeded",
        "summary": "Bộ công cụ CTV đã sẵn sàng",
        "result": {"pythonVersion": "3.14.3"},
        "errors": [],
        "retryable": False,
    }
    assert b"\\u1ed9" not in content  # ensure_ascii=False
    assert content == canonical_json_bytes(envelope)


def test_failure_envelope_copies_inputs_and_preserves_error_order():
    result = {"checked": ["fitz"]}
    errors = [
        CliError("dependency-missing", "A required dependency is missing."),
        CliError("secure-open-unavailable", "Secure local file opening is unavailable."),
    ]
    envelope = failed(
        "doctor",
        "Local CTV toolkit is not ready",
        errors,
        retryable=True,
        result=result,
    )
    result["checked"].append("untrusted-later-mutation")
    errors.reverse()

    payload = json.loads(canonical_json_bytes(envelope))

    assert payload["status"] == "failed"
    assert payload["retryable"] is True
    assert payload["result"] == {"checked": ["fitz"]}
    assert [error["code"] for error in payload["errors"]] == [
        "dependency-missing",
        "secure-open-unavailable",
    ]
```

Also add parameterized tests rejecting an empty/unknown `operation`, an empty `summary`, an invalid error code (anything outside lower-case kebab case), and a success envelope with errors.

- [ ] **Step 3: Run the tests to verify RED**

Run:

```bash
cd server
python3 -m pytest ctv_cli_protocol_test.py -q
```

Expected: collection fails with `ModuleNotFoundError: No module named 'ctv_cli_protocol'`.

- [ ] **Step 4: Implement the minimal immutable protocol**

Create `server/ctv_cli_protocol.py` using frozen dataclasses and defensive deep copies. Implement these exact shapes:

```python
@dataclass(frozen=True)
class CliError:
    code: str
    message: str


@dataclass(frozen=True)
class CliEnvelope:
    schema_version: str
    operation: str
    status: Literal["succeeded", "failed"]
    summary: str
    result: Mapping[str, object]
    errors: tuple[CliError, ...]
    retryable: bool

    def to_dict(self) -> dict[str, object]: ...


def succeeded(
    operation: str,
    summary: str,
    result: Mapping[str, object],
) -> CliEnvelope: ...


def failed(
    operation: str,
    summary: str,
    errors: Sequence[CliError],
    *,
    retryable: bool,
    result: Mapping[str, object] | None = None,
) -> CliEnvelope: ...


def canonical_json_bytes(envelope: CliEnvelope) -> bytes:
    return (
        json.dumps(
            envelope.to_dict(),
            ensure_ascii=False,
            sort_keys=True,
            indent=2,
        ).encode("utf-8")
        + b"\n"
    )
```

Validate operation names against `{"version", "doctor", "contract.verify"}` and error codes against `^[a-z0-9]+(?:-[a-z0-9]+)*$`. Use `copy.deepcopy` when constructing and serializing `result`; never retain a caller-owned mutable dictionary or list.

- [ ] **Step 5: Run protocol tests and the focused regression gate**

Run:

```bash
cd server
python3 -m pytest ctv_cli_protocol_test.py -q
python3 -m pytest intake_contract_test.py intake_package_validator_test.py -q
```

Expected: all tests pass; only the existing PyMuPDF deprecation warnings may remain.

- [ ] **Step 6: Commit Task 1**

```bash
git add server/ctv_cli_protocol.py server/ctv_cli_protocol_test.py
git diff --cached --check
git commit -m "feat(ctv): define local CLI response protocol"
```

Expected: commit contains exactly the two protocol files.

---

### Task 2: Immutable contract pin and tree verification

**Files:**

- Create: `contracts/ctv-intake/PIN.json`
- Create: `server/ctv_contract_pin.py`
- Create: `server/ctv_contract_pin_test.py`

**Interfaces:**

- Consumes: the canonical hash definition in `contracts/ctv-intake/README.md` and the protocol's safe error-code vocabulary.
- Produces:
  - `ContractPin(source_commit: str, contract_tree_sha256: str, compatibility_target: str)`
  - `ContractVerification(pin: ContractPin, actual_tree_sha256: str, verified: bool)`
  - `ContractPinError(code: str)` with no local path or wrapped raw exception in its public string
  - `load_contract_pin(repository_root: Path) -> ContractPin`
  - `compute_contract_tree_sha256(version_root: Path) -> str`
  - `verify_contract(repository_root: Path) -> ContractVerification`

- [ ] **Step 1: Add the reviewed pin metadata and failing tests**

Create `contracts/ctv-intake/PIN.json` with exactly:

```json
{
  "compatibilityTarget": "ctv-intake-v1",
  "contractTreeSha256": "83d0523ffdf871d79597310d2a24424c8bb17b6fcdb208d9bf28afc70da6900d",
  "sourceCommit": "75b3b3bc7e3d4edef1b24a0cfc9bb6c039320f3a"
}
```

Create `server/ctv_contract_pin_test.py`. Copy the real pin and `v1/` tree into a temporary repository and test the real API:

```python
from pathlib import Path
import json
import shutil

import pytest

from ctv_contract_pin import ContractPinError, verify_contract


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]


def _copy_contract(tmp_path: Path) -> Path:
    root = tmp_path / "repository"
    target = root / "contracts" / "ctv-intake"
    target.mkdir(parents=True)
    shutil.copy2(REPOSITORY_ROOT / "contracts/ctv-intake/PIN.json", target / "PIN.json")
    shutil.copytree(REPOSITORY_ROOT / "contracts/ctv-intake/v1", target / "v1")
    return root


def test_approved_contract_tree_matches_reviewed_pin(tmp_path):
    verification = verify_contract(_copy_contract(tmp_path))
    assert verification.verified is True
    assert verification.pin.source_commit == "75b3b3bc7e3d4edef1b24a0cfc9bb6c039320f3a"
    assert verification.actual_tree_sha256 == "83d0523ffdf871d79597310d2a24424c8bb17b6fcdb208d9bf28afc70da6900d"


@pytest.mark.parametrize("mutation", ["modified", "missing", "added"])
def test_any_contract_tree_mutation_is_detected(tmp_path, mutation):
    root = _copy_contract(tmp_path)
    version_root = root / "contracts/ctv-intake/v1"
    if mutation == "modified":
        (version_root / "compatibility.md").write_text("modified\n", encoding="utf-8")
    elif mutation == "missing":
        (version_root / "compatibility.md").unlink()
    else:
        (version_root / "unexpected.json").write_text("{}\n", encoding="utf-8")

    verification = verify_contract(root)

    assert verification.verified is False
    assert verification.actual_tree_sha256 != verification.pin.contract_tree_sha256
```

Add separate tests for missing/malformed `PIN.json`, extra pin keys, uppercase/short digests, wrong compatibility target, a symlink anywhere under `v1/`, a non-regular FIFO when supported, deterministic Unicode/POSIX relative paths, and a failure message that does not contain the temporary absolute path.

- [ ] **Step 2: Run the contract verifier tests to verify RED**

Run:

```bash
cd server
python3 -m pytest ctv_contract_pin_test.py -q
```

Expected: collection fails with `ModuleNotFoundError: No module named 'ctv_contract_pin'`.

- [ ] **Step 3: Implement strict pin parsing and bounded streaming hashes**

Create `server/ctv_contract_pin.py` with:

```python
@dataclass(frozen=True)
class ContractPin:
    source_commit: str
    contract_tree_sha256: str
    compatibility_target: str


@dataclass(frozen=True)
class ContractVerification:
    pin: ContractPin
    actual_tree_sha256: str
    verified: bool


class ContractPinError(RuntimeError):
    def __init__(self, code: str):
        self.code = code
        super().__init__(code)
```

Requirements for `load_contract_pin`:

- open `repository_root` as a directory descriptor, then open `contracts`,
  `ctv-intake`, and `PIN.json` component by component with descriptor-relative
  `O_NOFOLLOW`; reject unsafe or unsupported traversal before reading pin bytes;
- cap the pin at 16 KiB before parsing;
- require exactly `sourceCommit`, `contractTreeSha256`, and `compatibilityTarget`;
- require lower-case 40-character SHA-1 syntax for `sourceCommit`;
- require lower-case 64-character SHA-256 syntax for `contractTreeSha256`;
- require `compatibilityTarget == "ctv-intake-v1"`; and
- convert all I/O/JSON failures to stable codes such as `contract-pin-missing`, `contract-pin-too-large`, or `contract-pin-invalid`, without including a path.

Requirements for `compute_contract_tree_sha256`:

- enumerate every entry below `contracts/ctv-intake/v1/` without following links;
- reject symlinks and non-regular entries as `contract-entry-unsafe`;
- cap the file count at 1,000 and each file at 16 MiB;
- cap the aggregate bytes read at 64 MiB;
- from the already opened repository descriptor, open `contracts`, `ctv-intake`,
  and `v1` component by component with descriptor-relative `O_NOFOLLOW`, then
  perform recursive descriptor-relative enumeration and reads; fail closed as
  `secure-open-unavailable` when the platform cannot provide those primitives;
- reject an entry unless descriptor `fstat` proves it is a regular file and its
  identity and size remain unchanged through the bounded streaming hash;
- stream each file in chunks rather than calling `read_bytes()`;
- compare descriptor-relative directory entry snapshots before and after hashing,
  and fail as `contract-tree-changed` if any name, type, or identity changed during
  the operation;
- convert each relative path to POSIX separators;
- calculate `<file-sha256><two spaces><relative-path>\n`;
- sort by the UTF-8 contract-relative path and hash the concatenated lines exactly as the canonical README specifies; and
- expose no absolute path in any error.

`verify_contract` loads the pin, computes the actual hash, and returns `verified=False` for a cleanly computed mismatch. Structural or I/O failures raise `ContractPinError`.

- [ ] **Step 4: Run the verifier and independently compare the approved hash**

Run:

```bash
cd server
python3 -m pytest ctv_contract_pin_test.py -q
cd ..
python3 - 75b3b3bc7e3d4edef1b24a0cfc9bb6c039320f3a <<'PY'
import hashlib
import subprocess
import sys

source_commit = sys.argv[1]
root = "contracts/ctv-intake/v1"
tree_raw = subprocess.check_output(
    ["git", "ls-tree", "-r", "-z", source_commit, "--", root]
)
entries = []
for raw_entry in tree_raw.split(b"\0"):
    if not raw_entry:
        continue
    metadata, raw_path = raw_entry.split(b"\t", 1)
    mode, object_type, _object_id = metadata.decode("ascii").split(" ")
    path = raw_path.decode("utf-8")
    if object_type != "blob" or mode == "120000":
        raise SystemExit(f"unsafe contract entry: {path}")
    relative = path[len(root) + 1:]
    content = subprocess.check_output(["git", "show", f"{source_commit}:{path}"])
    file_sha256 = hashlib.sha256(content).hexdigest()
    entries.append((relative, f"{file_sha256}  {relative}\n".encode("utf-8")))
tree_bytes = b"".join(line for _, line in sorted(entries))
print(hashlib.sha256(tree_bytes).hexdigest())
PY
```

The second command is independent of the new implementation and reads immutable
commit blobs. Expected output:

```text
83d0523ffdf871d79597310d2a24424c8bb17b6fcdb208d9bf28afc70da6900d
```

Then run:

```bash
git diff -- contracts/ctv-intake/v1
```

Expected: no output; the hashed contract tree is unchanged.

- [ ] **Step 5: Run focused contract/fixture/exporter regressions**

```bash
cd server
python3 -m pytest \
  ctv_cli_protocol_test.py \
  ctv_contract_pin_test.py \
  intake_contract_test.py \
  intake_fixture_factory_test.py \
  export_intake_contract_test.py \
  -q
```

Expected: all pass; only existing PyMuPDF deprecation warnings may remain.

- [ ] **Step 6: Commit Task 2**

```bash
git add contracts/ctv-intake/PIN.json server/ctv_contract_pin.py server/ctv_contract_pin_test.py
git diff --cached --check
git commit -m "feat(ctv): verify the local intake contract pin"
```

Expected: commit contains exactly the pin, verifier, and verifier tests; no `v1/` file changes.

---

### Task 3: Runtime and secure-open doctor

**Files:**

- Create: `server/ctv_cli_doctor.py`
- Create: `server/ctv_cli_doctor_test.py`

**Interfaces:**

- Consumes: installed modules `fitz`, `openpyxl`, `pydantic`, and local `intake_package_validator`; does not call any parser or open a user path.
- Produces:
  - `DoctorIssue(code: str, dependency: str)`
  - `DoctorResult(python_version: str, validator_version: str | None, checked: tuple[str, ...], issues: tuple[DoctorIssue, ...])`
  - `DoctorResult.ready -> bool`
  - `run_doctor(import_module: Callable[[str], ModuleType] = importlib.import_module) -> DoctorResult`

- [ ] **Step 1: Write failing dependency and capability tests**

Create `server/ctv_cli_doctor_test.py` with a fake importer so tests do not uninstall or mutate the real environment:

```python
from types import SimpleNamespace

from ctv_cli_doctor import run_doctor


def _healthy_modules():
    base_model = type("BaseModel", (), {"model_validate": classmethod(lambda cls, value: value)})
    return {
        "fitz": SimpleNamespace(open=lambda *args, **kwargs: None),
        "openpyxl": SimpleNamespace(load_workbook=lambda *args, **kwargs: None),
        "pydantic": SimpleNamespace(BaseModel=base_model),
        "intake_package_validator": SimpleNamespace(
            VALIDATOR_VERSION="1.0.0",
            _SUPPORTS_SECURE_RELATIVE_OPEN=True,
        ),
    }


def test_doctor_reports_ready_only_when_every_probe_passes():
    modules = _healthy_modules()
    result = run_doctor(import_module=modules.__getitem__)
    assert result.ready is True
    assert result.validator_version == "1.0.0"
    assert result.issues == ()
    assert result.checked == ("fitz", "openpyxl", "pydantic", "intake-package-validator")


def _importer(modules):
    def import_module(name):
        try:
            return modules[name]
        except KeyError as error:
            raise ModuleNotFoundError(name) from error
    return import_module


def test_missing_dependency_is_bounded_and_retryable_by_the_cli():
    modules = _healthy_modules()
    del modules["fitz"]

    result = run_doctor(import_module=_importer(modules))

    assert result.ready is False
    assert [(issue.code, issue.dependency) for issue in result.issues] == [
        ("dependency-missing", "fitz")
    ]
```

Use `_importer(_healthy_modules())` in the success test as well. Add tests for
missing required attributes, validator import failure, absent/false
secure-relative-open capability, issue ordering independent of exception text, and
proof that raw importer exception text is absent from `DoctorIssue`. Give the fake
callable dependency attributes counters and assert every counter remains zero,
proving the doctor inspects capabilities but does not open a PDF, workbook, contract
document, or package.

- [ ] **Step 2: Run doctor tests to verify RED**

Run:

```bash
cd server
python3 -m pytest ctv_cli_doctor_test.py -q
```

Expected: collection fails with `ModuleNotFoundError: No module named 'ctv_cli_doctor'`.

- [ ] **Step 3: Implement pure, non-mutating probes**

Create `server/ctv_cli_doctor.py`. Probe in this fixed order:

```python
DEPENDENCY_PROBES = (
    ("fitz", "fitz", ("open",)),
    ("openpyxl", "openpyxl", ("load_workbook",)),
    ("pydantic", "pydantic", ("BaseModel.model_validate",)),
    ("intake-package-validator", "intake_package_validator", ("VALIDATOR_VERSION",)),
)
```

For each probe:

- import by the injected `import_module` callable;
- map `ModuleNotFoundError` to `dependency-missing`; map other `ImportError` and
  missing required attributes to `dependency-incompatible`; never copy exception
  text into the issue;
- never invoke `fitz.open`, `openpyxl.load_workbook`, Pydantic validation, or the
  intake validator; and
- after importing the validator, require
  `_SUPPORTS_SECURE_RELATIVE_OPEN is True`, otherwise add
  `DoctorIssue("secure-open-unavailable", "intake-package-validator")`.

Return `platform.python_version()` and the validator's string `VALIDATOR_VERSION`
when safe. `ready` is true only when `issues` is empty.

- [ ] **Step 4: Run doctor tests and prove the real environment**

Run:

```bash
cd server
python3 -m pytest ctv_cli_doctor_test.py -q
python3 - <<'PY'
from ctv_cli_doctor import run_doctor
result = run_doctor()
assert result.ready, result.issues
assert result.validator_version == "1.0.0"
print(result.python_version)
PY
```

Expected: tests pass and the real environment prints only its Python version.

- [ ] **Step 5: Commit Task 3**

```bash
git add server/ctv_cli_doctor.py server/ctv_cli_doctor_test.py
git diff --cached --check
git commit -m "feat(ctv): add local toolkit health probes"
```

Expected: commit contains exactly the doctor and its tests.

---

### Task 4: Thin CLI dispatcher, launch acceptance, and operator handoff

**Files:**

- Create: `server/ctv_intake_cli.py`
- Create: `server/ctv_intake_cli_test.py`
- Modify: `server/README.md`

**Interfaces:**

- Consumes:
  - `succeeded`, `failed`, `CliError`, and `canonical_json_bytes` from `ctv_cli_protocol`
  - `load_contract_pin` and `verify_contract` from `ctv_contract_pin`
  - `run_doctor` from `ctv_cli_doctor`
- Produces:
  - commands `version --json`, `doctor --json`, and `contract verify --json`
  - `main(argv: list[str] | None = None) -> int`
  - exit/status behavior defined by the approved design

- [ ] **Step 1: Write failing subprocess tests for the three commands**

Create `server/ctv_intake_cli_test.py` with:

```python
import json
from pathlib import Path
import subprocess
import sys


SCRIPT = Path(__file__).with_name("ctv_intake_cli.py")
EXPECTED_COMMIT = "75b3b3bc7e3d4edef1b24a0cfc9bb6c039320f3a"
EXPECTED_TREE = "83d0523ffdf871d79597310d2a24424c8bb17b6fcdb208d9bf28afc70da6900d"


def _run(*args: str, cwd: Path | None = None):
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        cwd=cwd,
        capture_output=True,
        check=False,
    )


def _envelope(result, operation: str, status: str):
    assert result.stdout.endswith(b"\n")
    payload = json.loads(result.stdout)
    assert payload["schemaVersion"] == "1.0"
    assert payload["operation"] == operation
    assert payload["status"] == status
    assert result.stdout == (
        json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2).encode("utf-8")
        + b"\n"
    )
    return payload


def test_version_reports_the_reviewed_identity_from_an_unrelated_cwd(tmp_path):
    result = _run("version", "--json", cwd=tmp_path)
    payload = _envelope(result, "version", "succeeded")
    assert result.returncode == 0
    assert result.stderr == b""
    assert payload["result"]["sourceCommit"] == EXPECTED_COMMIT
    assert payload["result"]["contractTreeSha256"] == EXPECTED_TREE
    assert payload["result"]["compatibilityTarget"] == "ctv-intake-v1"


def test_doctor_reports_the_real_runtime_without_reading_documents(tmp_path):
    result = _run("doctor", "--json", cwd=tmp_path)
    payload = _envelope(result, "doctor", "succeeded")
    assert result.returncode == 0
    assert result.stderr == b""
    assert payload["result"]["ready"] is True


def test_contract_verify_reports_the_approved_tree(tmp_path):
    result = _run("contract", "verify", "--json", cwd=tmp_path)
    payload = _envelope(result, "contract.verify", "succeeded")
    assert result.returncode == 0
    assert result.stderr == b""
    assert payload["result"]["verified"] is True
    assert payload["result"]["actualTreeSha256"] == EXPECTED_TREE
```

- [ ] **Step 2: Add failing in-process error-mapping tests**

Add tests using `monkeypatch` and `capsysbinary`:

- `doctor` with one missing dependency returns a failed `doctor` envelope, safe
  `dependency-missing`, `retryable: true`, and exit `2`;
- contract mismatch returns a failed `contract.verify` envelope,
  `contract-tree-mismatch`, `retryable: false`, and exit `2`;
- a `ContractPinError("contract-pin-invalid")` returns a safe failed envelope and
  exit `1`;
- an unexpected exception whose message contains a temporary absolute path returns
  only `internal-error`, never that message, and exits `1`;
- an unknown command or missing `--json` exits `1`, emits no JSON object, and writes
  only bounded invocation guidance to stderr; and
- extra positional path arguments are rejected, proving foundation commands cannot
  accept a source or document path.

- [ ] **Step 3: Add failing launch and static safety tests**

Add a helper that copies `server/*.py`, `contracts/ctv-intake/PIN.json`, and
`contracts/ctv-intake/v1/` into a temporary repository named
`Bộ công cụ CTV thử nghiệm`, excluding `*_test.py`, `__pycache__`, and data files.
Launch all three commands from a different current directory and require the same
status, hashes, and exit codes as the original checkout.

Parse the AST of `ctv_intake_cli.py`, `ctv_cli_doctor.py`, and
`ctv_contract_pin.py` and fail if they import network/client roots
`socket`, `urllib`, `http`, `requests`, `httpx`, `ftplib`, or `webbrowser`.
Also assert the argument parser exposes no source-root, workspace-root, input-file,
output-file, install, repair, or update option.

- [ ] **Step 4: Run the CLI tests to verify RED**

Run:

```bash
cd server
python3 -m pytest ctv_intake_cli_test.py -q
```

Expected: subprocess tests fail because `ctv_intake_cli.py` does not exist.

- [ ] **Step 5: Implement the thin dispatcher**

Create `server/ctv_intake_cli.py` with a custom `argparse.ArgumentParser` whose
`error()` raises a private `CliInvocationError` instead of exiting with argparse's
default code `2`. Define exactly these parser branches:

```text
version --json
doctor --json
contract verify --json
```

Resolve the repository root only with:

```python
REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
```

Command behavior:

- `version`: call `load_contract_pin(REPOSITORY_ROOT)` and return toolkit version
  `1.0.0`, CLI `schemaVersion` `1.0`, and the three pin fields.
- `doctor`: call `run_doctor()`. A ready result succeeds with exit `0`; issues map
  in their existing order to safe `CliError` objects, fail with exit `2`, and are
  retryable only when every issue code is `dependency-missing` or
  `dependency-incompatible`.
- `contract verify`: call `verify_contract(REPOSITORY_ROOT)`. A matching tree
  succeeds with exit `0`; a computed mismatch returns `contract-tree-mismatch` and
  exit `2`; a structural `ContractPinError` returns its safe code and exit `1`.
- Any unexpected handler exception after an operation is known returns a failed
  envelope containing only `internal-error` and exit `1`.
- Invalid invocation occurs before a stable operation exists, writes bounded usage
  to stderr, emits no stdout, and exits `1`.

Emit the envelope with one `_emit_stdout(content: bytes)` helper equivalent to the
existing validator CLI's binary-safe implementation. Do not invoke `shell=True`,
subprocesses, a network library, a package manager, or the existing package
validation function.

- [ ] **Step 6: Run targeted CLI and module gates**

Run:

```bash
cd server
python3 -m pytest \
  ctv_cli_protocol_test.py \
  ctv_contract_pin_test.py \
  ctv_cli_doctor_test.py \
  ctv_intake_cli_test.py \
  -q
python3 ../server/ctv_intake_cli.py version --json
python3 ../server/ctv_intake_cli.py doctor --json
python3 ../server/ctv_intake_cli.py contract verify --json
```

Expected: all tests pass; each manual command prints one JSON object and exits `0`.

- [ ] **Step 7: Document the operator and WP-agent handoff**

Add `## Checking the standalone CTV toolkit` to `server/README.md` with the three
exact commands. Document:

- the caller supplies the explicit local script path;
- commands work from outside the checkout;
- WP must run `version`, `doctor`, then `contract verify` before future processing;
- exit codes `0`, `2`, and `1`;
- stdout is JSON-only for parsed `--json` operations;
- foundation commands do not accept document folders or write files;
- WP contains no CTV code and performs no automatic toolkit discovery; and
- a successful preflight does not validate or approve a payment package.

Do not document inventory, OCR, transformations, package creation, or an MCP server
as available functionality.

- [ ] **Step 8: Run full acceptance and privacy/scope gates**

Run:

```bash
cd server
python3 -m pytest -q
cd ..
npm test
npm run build
git diff --check
git diff --name-only "$ctv_cli_base"...HEAD
git status --short
```

Expected:

- backend passes all prior 341 tests plus all new CLI foundation tests;
- frontend passes 130 tests;
- production build exits `0`;
- relative to the recorded implementation base, only the ten product/test files
  listed in this plan are changed; the already-committed plan is not an
  implementation change;
- `contracts/ctv-intake/v1/` has no diff;
- no WP path, generated bundle, dependency lockfile, real client data, secret,
  absolute developer path, or unrelated file is staged.

Here `ctv_cli_base` is the exact full base SHA recorded in Task 1 Step 1; set it as
an ordinary task-specific shell variable before running the diff command. Do not
substitute `e0a947d`, because that would include this already-reviewed plan in the
implementation diff.

Run a narrow leak/scope scan over the new tracked content:

```bash
rg -n "/Users/|CTV AP GAS|FA-PM[0-9]|@vng|BEGIN (RSA |EC |OPENSSH )?PRIVATE KEY|requests|httpx|MCP server" \
  contracts/ctv-intake/PIN.json \
  server/ctv_cli_protocol.py \
  server/ctv_contract_pin.py \
  server/ctv_cli_doctor.py \
  server/ctv_intake_cli.py \
  server/README.md
```

Expected: no sensitive/local-path hits. The intentional README sentence stating
that no MCP server is used may be reviewed manually; no executable MCP code or
dependency may exist.

- [ ] **Step 9: Commit Task 4**

```bash
git add server/ctv_intake_cli.py server/ctv_intake_cli_test.py server/README.md
git diff --cached --check
git diff --cached --name-status
git commit -m "feat(ctv): expose local toolkit preflight CLI"
```

Expected: final task commit contains exactly the dispatcher, integration tests, and
README update. Leave the implementation branch unpushed and unmerged for independent
review and explicit user direction.

---

## Completion boundary

Completion of this plan proves only that a local CTV toolkit can identify itself,
check its runtime, and verify its approved contract through a stable JSON CLI. It
does not implement folder inventory, document inspection, OCR, AI classification,
organization proposals, approvals, package creation, package validation through the
new CLI, WP instructions, direct CTV submission, or payment approval.

The next admissible design activity is the separate read-only folder-inventory
milestone. Do not begin it as part of this plan.
