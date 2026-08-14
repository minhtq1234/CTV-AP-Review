import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
SOURCE_COMMIT = "b48eee33bed17e8810f5bf57c598ed02b6a70e52"
TARGET = "ctv-intake-v2"


def _export(repository_root: Path, source_commit: str = SOURCE_COMMIT):
    return subprocess.run(
        [
            sys.executable,
            str(REPOSITORY_ROOT / "server/export_contract_pin.py"),
            "--repository-root",
            str(repository_root),
            "--source-commit",
            source_commit,
            "--target",
            TARGET,
        ],
        capture_output=True,
        check=False,
    )


def _portable_tree_sha256(repository_root: Path) -> str:
    root = "contracts/ctv-intake/v2"
    entries = subprocess.check_output(
        ["git", "-C", str(repository_root), "ls-tree", "-r", "-z", SOURCE_COMMIT, "--", root]
    )
    lines = []
    for entry in entries.split(b"\0"):
        if not entry:
            continue
        metadata, raw_path = entry.split(b"\t", 1)
        mode, kind, _object_id = metadata.decode("ascii").split(" ")
        assert kind == "blob"
        assert mode != "120000"
        path = raw_path.decode("utf-8")
        content = subprocess.check_output(
            ["git", "-C", str(repository_root), "show", f"{SOURCE_COMMIT}:{path}"]
        )
        relative = path.removeprefix(root + "/")
        lines.append(
            (relative, f"{hashlib.sha256(content).hexdigest()}  {relative}\n".encode())
        )
    return hashlib.sha256(b"".join(line for _, line in sorted(lines))).hexdigest()


def test_exporter_derives_canonical_three_field_v2_pin_from_exact_commit():
    result = _export(REPOSITORY_ROOT)

    assert result.returncode == 0, result.stderr.decode("utf-8", errors="replace")
    payload = json.loads(result.stdout)
    assert set(payload) == {
        "sourceCommit",
        "contractTreeSha256",
        "compatibilityTarget",
    }
    assert payload == {
        "sourceCommit": SOURCE_COMMIT,
        "contractTreeSha256": _portable_tree_sha256(REPOSITORY_ROOT),
        "compatibilityTarget": TARGET,
    }
    assert result.stdout == (
        json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2).encode("utf-8")
        + b"\n"
    )


def test_exporter_ignores_v2_working_tree_mutations(tmp_path):
    clone = tmp_path / "repository"
    subprocess.run(
        ["git", "clone", "--no-hardlinks", str(REPOSITORY_ROOT), str(clone)],
        capture_output=True,
        check=True,
    )
    changed = clone / "contracts/ctv-intake/v2/compatibility.md"
    changed.write_text("working tree mutation\n", encoding="utf-8")

    result = _export(clone)

    assert result.returncode == 0, result.stderr.decode("utf-8", errors="replace")
    assert json.loads(result.stdout)["contractTreeSha256"] == _portable_tree_sha256(
        clone
    )


def test_exporter_rejects_non_exact_commit_and_unknown_target():
    short_commit = _export(REPOSITORY_ROOT, SOURCE_COMMIT[:12])
    unknown_target = subprocess.run(
        [
            sys.executable,
            str(REPOSITORY_ROOT / "server/export_contract_pin.py"),
            "--repository-root",
            str(REPOSITORY_ROOT),
            "--source-commit",
            SOURCE_COMMIT,
            "--target",
            "ctv-intake-v3",
        ],
        capture_output=True,
        check=False,
    )

    assert short_commit.returncode != 0
    assert unknown_target.returncode != 0
    assert short_commit.stdout == unknown_target.stdout == b""
