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

Only regular blob entries from the exact reviewed commit are inputs. Working-tree
changes and untracked files cannot affect the result. From the CTV repository root,
set `source_commit` to the supplied full commit ID. The preflight operations are
equivalent to `git rev-parse --verify "$source_commit^{commit}"`,
`git ls-tree -r -z "$source_commit" -- contracts/ctv-intake/v1`, and
`git show "$source_commit:$path"`. This Python 3 command implements the complete
definition without depending on platform-specific `sha256sum` variants:

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
