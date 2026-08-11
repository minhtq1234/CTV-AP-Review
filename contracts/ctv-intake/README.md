# CTV intake contract handoff

This directory is the CTV-to-WePrompt (WP) handoff entrypoint for prepared intake
packages. CTV owns the executable contract under `v1/`. WP copies a byte-for-byte,
immutable snapshot into its implementation workspace and validates its generated
packages against that snapshot.

Both the CTV and WP contract reviewers must review an update before WP changes its
pin. WP must never edit, widen, or reinterpret a copied snapshot in place. A needed
contract change starts in CTV, passes the CTV contract gate, and is then copied as a
new reviewed snapshot by WP.

## Pinning a snapshot in WP

After the final CTV contract review, WP performs the copy from the exact reviewed
CTV commit. The WP snapshot contains every versioned file below
`contracts/ctv-intake/v1/`, unchanged. Alongside the snapshot, WP creates
`SOURCE.json` with exactly these fields:

| Field | Required value |
|---|---|
| `sourceRepository` | Stable identifier for the CTV source repository. |
| `sourceCommit` | Full 40-character SHA of the reviewed CTV commit. |
| `contractPath` | Source path `contracts/ctv-intake/v1`. |
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

The tree hash covers every regular versioned file below
`contracts/ctv-intake/v1/`, including the checked-in synthetic fixture JSON and
README files. For each file:

1. Compute its lowercase SHA-256.
2. Express its path relative to `v1/` with POSIX `/` separators.
3. Form the UTF-8 line `<lowercase-file-sha256><two spaces><relative-path>\n`.
4. Sort those contract-relative paths lexicographically, concatenate their lines,
   and SHA-256 the resulting bytes.

Symlinks and untracked files are forbidden inputs. From the CTV repository root,
this Python 3 command implements the definition without depending on platform
specific `sha256sum` variants:

```bash
python3 - <<'PY'
from pathlib import Path
import hashlib
import subprocess

root = Path("contracts/ctv-intake/v1")
tracked_raw = subprocess.check_output(
    ["git", "ls-files", "-z", "--", root.as_posix()]
)
untracked_raw = subprocess.check_output(
    ["git", "ls-files", "--others", "--exclude-standard", "-z", "--", root.as_posix()]
)
if untracked_raw:
    raise SystemExit("untracked contract files are forbidden")

files = [Path(raw.decode("utf-8")) for raw in tracked_raw.split(b"\0") if raw]
entries = []
for path in files:
    if path.is_symlink() or not path.is_file():
        raise SystemExit(f"contract entry is not a regular file: {path}")
    relative = path.relative_to(root).as_posix()
    file_sha256 = hashlib.sha256(path.read_bytes()).hexdigest()
    entries.append((relative, f"{file_sha256}  {relative}\n".encode("utf-8")))

tree_bytes = b"".join(line for _, line in sorted(entries))
print(hashlib.sha256(tree_bytes).hexdigest())
PY
```

The hash is meaningful only together with the exact 40-character `sourceCommit`;
WP records both after Task 7 rather than pinning a branch name.

## Handoff boundary

A valid report proves mechanical schema, digest, source/page coverage, roster,
exception, and compatibility checks. `prepared` does not mean the payment evidence
is correct or approved. Visible unresolved evidence may only produce an explicitly
partial package.

The v1 handoff stops at a validated prepared package. It does not authorize direct
submission to CTV, placing real pilot data in Git, changing originals, or bypassing
the ACC reviewer who makes the final payment decision.
