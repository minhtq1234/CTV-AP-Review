# CTV intake contract handoff

This directory is the CTV-to-WePrompt (WP) handoff entrypoint for prepared intake
packages. CTV owns two executable, immutable contract snapshots: `v1/` and `v2/`.
`PIN.json` selects `v1/`; `PIN.v2.json` selects `v2/`. WP copies a byte-for-byte
snapshot into its implementation workspace and validates generated packages against
that selected snapshot.

Both the CTV and WP contract reviewers must review an update before WP changes its
pin. WP must never edit, widen, or reinterpret a copied snapshot in place. A needed
contract change starts in CTV, passes the CTV contract gate, and is then copied as a
new reviewed snapshot by WP.

## Selecting and pinning a snapshot in WP

The local CTV CLI defaults to v1. These commands are intentionally unchanged:

```bash
python3 server/ctv_intake_cli.py version --json
python3 server/ctv_intake_cli.py contract verify --json
```

Select v2 explicitly when its reviewed pin is required:

```bash
python3 server/ctv_intake_cli.py version --target ctv-intake-v2 --json
python3 server/ctv_intake_cli.py contract verify --target ctv-intake-v2 --json
```

An explicit `--target ctv-intake-v1` emits the same result bytes as the legacy
no-target command. Each target reads only its paired version directory and pin:
`ctv-intake-v1` -> `v1/` and `PIN.json`; `ctv-intake-v2` -> `v2/` and
`PIN.v2.json`.

WP must pin the exact reviewed v2 commit and its `v2/` Git tree; it must not edit,
reuse, or reinterpret its v1 snapshot as v2. Export a reviewable pin directly from
the immutable CTV commit, never from working-tree bytes:

```bash
python3 server/export_contract_pin.py \
  --repository-root . \
  --source-commit <reviewed-40-character-commit> \
  --target ctv-intake-v2 > PIN.v2.json
```

## Pinning a snapshot in WP

After the final CTV contract review, WP performs the copy from the exact reviewed
CTV commit. The WP snapshot contains every versioned file below the selected
version directory, unchanged. Alongside the snapshot, WP creates
`SOURCE.json` with exactly these fields:

| Field | Required value |
|---|---|
| `sourceRepository` | Stable identifier for the CTV source repository. |
| `sourceCommit` | Full 40-character SHA of the reviewed CTV commit. |
| `contractPath` | Source path `contracts/ctv-intake/v1` or `contracts/ctv-intake/v2`, matching the selected pin. |
| `contractTreeSha256` | Lowercase SHA-256 produced by the portable algorithm below. |
| `copiedAt` | ISO-8601 timestamp supplied at the time of the WP copy. |

`copiedAt` is copy-operation metadata. It is not generated into the deterministic
CTV artifacts. Task 7 supplies the final commit and tree hash; this document does
not publish provisional values or create a sample `SOURCE.json`.

WP must then run its contract tests against the copied bytes. If copying, the tree
hash, or contract tests fail, WP does not mark the snapshot compatible. Later
updates repeat the reviewed copy and pinning process instead of modifying the
existing snapshot.

## Portable `contractTreeSha256`

The tree hash covers every regular versioned file below the selected version root,
such as `contracts/ctv-intake/v1/` or `contracts/ctv-intake/v2/`, including the checked-in synthetic fixture JSON and
README files. For each file:

1. Compute its lowercase SHA-256.
2. Express its path relative to the selected version root with POSIX `/` separators.
3. Form the UTF-8 line `<lowercase-file-sha256><two spaces><relative-path>\n`.
4. Sort those contract-relative paths lexicographically, concatenate their lines,
   and SHA-256 the resulting bytes.

`contracts/ctv-intake/v1/` has paths relative to `v1/`;
`contracts/ctv-intake/v2/` has paths relative to `v2/`. The v1 code example below
uses the former selected root; the v2 recipe changes only `root` to
`contracts/ctv-intake/v2` before deriving `prefix` and `relative`.

Only regular blob entries from the exact reviewed commit are inputs. Working-tree
changes and untracked files cannot affect the result. From the CTV repository root,
set `source_commit` to the supplied full commit ID and choose the matching version
root. The preflight operations are equivalent to `git rev-parse --verify "$source_commit^{commit}"`,
`git ls-tree -r -z "$source_commit" -- <selected-contract-root>`, and
`git show "$source_commit:$path"`. This Python 3 command implements the complete
definition without depending on platform-specific `sha256sum` variants:

For the preserved v1 recipe, the selected root remains
`git ls-tree -r -z "$source_commit" -- contracts/ctv-intake/v1`. V2 uses the
same recipe with `contracts/ctv-intake/v2`.

```bash
source_commit=<reviewed-40-character-commit>
python3 - "$source_commit" <<'PY'
import hashlib
import subprocess
import sys

source_commit = sys.argv[1]
if len(source_commit) != 40 or any(character not in "0123456789abcdef" for character in source_commit):
    raise SystemExit("source commit must be a full lowercase 40-character SHA")
resolved = subprocess.check_output(
    ["git", "rev-parse", "--verify", f"{source_commit}^{{commit}}"], text=True
).strip()
if resolved != source_commit:
    raise SystemExit("source commit did not resolve exactly")

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
        raise SystemExit(f"contract entry is not a regular blob: {path}")
    prefix = root + "/"
    if not path.startswith(prefix):
        raise SystemExit(f"contract entry escaped the version root: {path}")
    relative = path[len(prefix):]
    content = subprocess.check_output(["git", "show", f"{source_commit}:{path}"])
    file_sha256 = hashlib.sha256(content).hexdigest()
    entries.append((relative, f"{file_sha256}  {relative}\n".encode("utf-8")))

tree_bytes = b"".join(line for _, line in sorted(entries))
print(hashlib.sha256(tree_bytes).hexdigest())
PY
```

The hash is meaningful only together with the exact 40-character `sourceCommit`;
WP records both after Task 7 rather than pinning a branch name.

## Handoff boundary

A valid report requires `--source-root` access to the immutable original workspace
and proves mechanical schema, package/source digests, actual source PDF page counts,
page coverage, roster, exception, and compatibility checks. Package-only validation
still returns diagnostics but is invalid with `source-verification-unavailable`.
Source-root failures use synthetic evidence and do not expose the caller's absolute
workspace path. `prepared` does not mean the payment evidence is correct or approved.
Visible unresolved evidence may only produce an explicitly partial package.

The v1 handoff stops at a validated prepared package. It does not authorize direct
submission to CTV, placing real pilot data in Git, changing originals, or bypassing
the ACC reviewer who makes the final payment decision.
