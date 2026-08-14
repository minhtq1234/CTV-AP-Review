"""Export a CTV contract pin from an immutable Git commit."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys

from ctv_contract_pin import _CONTRACT_TARGETS


_COMMIT = re.compile(r"[0-9a-f]{40}")


class ContractPinExportError(RuntimeError):
    pass


def _run_git(repository_root: Path, argv: list[str]) -> bytes:
    result = subprocess.run(
        ["git", "-C", str(repository_root), *argv],
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        raise ContractPinExportError("git-command-failed")
    return result.stdout


def _target_path(target: str) -> tuple[str, str]:
    if target not in _CONTRACT_TARGETS:
        raise ContractPinExportError("contract-target-invalid")
    version, pin_name = _CONTRACT_TARGETS[target]
    return f"contracts/ctv-intake/{version}", pin_name


def export_pin_from_commit(
    repository_root: Path, source_commit: str, target: str
) -> bytes:
    """Return the canonical three-field pin for a regular-blob Git tree."""
    if not isinstance(source_commit, str) or _COMMIT.fullmatch(source_commit) is None:
        raise ContractPinExportError("source-commit-invalid")
    version_root, _pin_name = _target_path(target)
    resolved = _run_git(
        Path(repository_root), ["rev-parse", "--verify", f"{source_commit}^{{commit}}"]
    ).decode("ascii").strip()
    if resolved != source_commit:
        raise ContractPinExportError("source-commit-invalid")

    raw_entries = _run_git(
        Path(repository_root),
        ["ls-tree", "-r", "-z", source_commit, "--", version_root],
    )
    prefix = version_root + "/"
    lines: list[tuple[str, bytes]] = []
    for raw_entry in raw_entries.split(b"\0"):
        if not raw_entry:
            continue
        try:
            metadata, raw_path = raw_entry.split(b"\t", 1)
            mode, object_type, _object_id = metadata.decode("ascii").split(" ")
            path = raw_path.decode("utf-8")
        except (UnicodeDecodeError, ValueError):
            raise ContractPinExportError("contract-entry-invalid") from None
        if object_type != "blob" or mode not in {"100644", "100755"}:
            raise ContractPinExportError("contract-entry-invalid")
        if not path.startswith(prefix) or not path[len(prefix) :]:
            raise ContractPinExportError("contract-entry-invalid")
        content = _run_git(Path(repository_root), ["show", f"{source_commit}:{path}"])
        relative = path[len(prefix) :]
        file_sha256 = hashlib.sha256(content).hexdigest()
        lines.append((relative, f"{file_sha256}  {relative}\n".encode("utf-8")))
    if not lines:
        raise ContractPinExportError("contract-tree-missing")

    tree_bytes = b"".join(line for _, line in sorted(lines))
    payload = {
        "compatibilityTarget": target,
        "contractTreeSha256": hashlib.sha256(tree_bytes).hexdigest(),
        "sourceCommit": source_commit,
    }
    return (
        json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2).encode("utf-8")
        + b"\n"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--repository-root", type=Path, required=True)
    parser.add_argument("--source-commit", required=True)
    parser.add_argument("--target", required=True)
    try:
        args = parser.parse_args(argv)
        sys.stdout.buffer.write(
            export_pin_from_commit(args.repository_root, args.source_commit, args.target)
        )
        return 0
    except (ContractPinExportError, OSError, subprocess.SubprocessError):
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
