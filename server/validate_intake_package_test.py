import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from intake_package_validator_test import (
    _artifact,
    _save_manifest,
    _write_package,
)


SCRIPT = Path(__file__).with_name("validate_intake_package.py")


def _run_cli(*args: object) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(
        [sys.executable, str(SCRIPT), *(str(arg) for arg in args)],
        capture_output=True,
        check=False,
    )


def _assert_canonical_report(stdout: bytes, expected_outcome: str) -> dict:
    assert stdout.endswith(b"\n")
    report = json.loads(stdout)
    assert report["outcome"] == expected_outcome
    expected = (
        json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2).encode("utf-8")
        + b"\n"
    )
    assert stdout == expected
    return report


def test_valid_package_emits_one_canonical_report_and_exits_zero(tmp_path):
    package_dir = tmp_path / "package"
    _write_package(package_dir)

    result = _run_cli(package_dir)

    assert result.returncode == 0
    _assert_canonical_report(result.stdout, "valid")
    assert result.stderr == b""


def test_invalid_package_emits_report_without_diagnostics_and_exits_two(tmp_path):
    package_dir = tmp_path / "package"
    manifest = _write_package(package_dir)
    manifest["artifacts"] = [
        artifact for artifact in manifest["artifacts"] if artifact["kind"] != "roster"
    ]
    _save_manifest(package_dir, manifest)

    result = _run_cli(package_dir)

    assert result.returncode == 2
    report = _assert_canonical_report(result.stdout, "invalid")
    assert "missing-required-artifact" in report["errors"]
    assert result.stderr == b""


def test_write_report_persists_identical_bytes_for_an_invalid_package(tmp_path):
    package_dir = tmp_path / "package"
    manifest = _write_package(package_dir)
    manifest["artifacts"] = [
        artifact for artifact in manifest["artifacts"] if artifact["kind"] != "roster"
    ]
    _save_manifest(package_dir, manifest)

    result = _run_cli(package_dir, "--write-report")

    assert result.returncode == 2
    _assert_canonical_report(result.stdout, "invalid")
    assert (package_dir / "validation-report.json").read_bytes() == result.stdout
    assert result.stderr == b""


def test_write_report_atomically_replaces_an_undeclared_generated_report(tmp_path):
    package_dir = tmp_path / "package"
    _write_package(package_dir)
    report_path = package_dir / "validation-report.json"
    report_path.write_bytes(b"old generated report\n")

    result = _run_cli(package_dir, "--write-report")

    assert result.returncode == 0
    assert report_path.read_bytes() == result.stdout
    assert report_path.read_bytes() != b"old generated report\n"
    assert not list(package_dir.glob(".validation-report.json.tmp-*"))


def test_directory_substitution_cannot_split_validation_from_report_write(
    tmp_path, monkeypatch, capsysbinary
):
    import validate_intake_package as cli

    package_dir = tmp_path / "package"
    original_manifest = _write_package(package_dir)
    original_manifest["artifacts"] = [
        artifact
        for artifact in original_manifest["artifacts"]
        if artifact["kind"] != "roster"
    ]
    _save_manifest(package_dir, original_manifest)
    valid_replacement = tmp_path / "valid-replacement"
    _write_package(valid_replacement)
    opened_original = tmp_path / "opened-original"
    real_guard = cli._guard_report_target

    def substitute_path_after_open(root_descriptor):
        real_guard(root_descriptor)
        package_dir.rename(opened_original)
        valid_replacement.rename(package_dir)

    monkeypatch.setattr(cli, "_guard_report_target", substitute_path_after_open)

    exit_code = cli.main([str(package_dir), "--write-report"])
    captured = capsysbinary.readouterr()

    report = _assert_canonical_report(captured.out, "invalid")
    assert exit_code == 2
    assert "missing-required-artifact" in report["errors"]
    assert captured.err == b""
    assert (opened_original / "validation-report.json").read_bytes() == captured.out
    assert not (package_dir / "validation-report.json").exists()


def test_write_report_refuses_a_digest_pinned_historical_report(tmp_path):
    package_dir = tmp_path / "package"
    manifest = _write_package(package_dir)
    report_path = package_dir / "validation-report.json"
    historical = b'{"historical":true}\n'
    report_path.write_bytes(historical)
    manifest["artifacts"].append(
        _artifact(
            "artifact-validation-report",
            "validation-report",
            report_path,
            [],
        )
    )
    _save_manifest(package_dir, manifest)

    result = _run_cli(package_dir, "--write-report")

    assert result.returncode == 1
    assert result.stdout == b""
    assert b"declared validation-report.json" in result.stderr
    assert report_path.read_bytes() == historical
    assert not list(package_dir.glob(".validation-report.json.tmp-*"))


def test_write_report_refuses_a_symlink_target_without_following_it(tmp_path):
    package_dir = tmp_path / "package"
    _write_package(package_dir)
    outside = tmp_path / "outside.json"
    outside.write_bytes(b"outside\n")
    report_path = package_dir / "validation-report.json"
    report_path.symlink_to(outside)

    result = _run_cli(package_dir, "--write-report")

    assert result.returncode == 1
    assert result.stdout == b""
    assert b"symlink" in result.stderr
    assert report_path.is_symlink()
    assert outside.read_bytes() == b"outside\n"
    assert not list(package_dir.glob(".validation-report.json.tmp-*"))


def test_write_report_refuses_a_non_regular_target(tmp_path):
    package_dir = tmp_path / "package"
    _write_package(package_dir)
    report_path = package_dir / "validation-report.json"
    report_path.mkdir()

    result = _run_cli(package_dir, "--write-report")

    assert result.returncode == 1
    assert result.stdout == b""
    assert b"not a regular file" in result.stderr
    assert report_path.is_dir()
    assert not list(package_dir.glob(".validation-report.json.tmp-*"))


@pytest.mark.parametrize("root_kind", ["symlink", "file"])
def test_write_report_refuses_a_symlink_or_non_directory_package_root(
    tmp_path, root_kind
):
    package_dir = tmp_path / "package"
    _write_package(package_dir)
    supplied_root = tmp_path / "supplied"
    if root_kind == "symlink":
        supplied_root.symlink_to(package_dir, target_is_directory=True)
    else:
        supplied_root.write_bytes(b"not a directory")

    result = _run_cli(supplied_root, "--write-report")

    assert result.returncode == 1
    assert result.stdout == b""
    assert result.stderr
    assert not (package_dir / "validation-report.json").exists()


def test_write_report_has_no_caller_selected_path_or_traversal_form(tmp_path):
    package_dir = tmp_path / "package"
    _write_package(package_dir)
    escape = tmp_path / "escape.json"

    result = _run_cli(package_dir, f"--write-report={escape}")

    assert result.returncode == 2
    assert result.stdout == b""
    assert b"usage:" in result.stderr
    assert not escape.exists()
    assert not (package_dir / "validation-report.json").exists()


def test_forced_atomic_replace_failure_leaves_no_temp_or_partial_report(
    tmp_path, monkeypatch, capsysbinary
):
    import validate_intake_package as cli

    package_dir = tmp_path / "package"
    _write_package(package_dir)

    def fail_replace(*_args, **_kwargs):
        raise OSError("synthetic replace failure")

    monkeypatch.setattr(cli.os, "replace", fail_replace)

    exit_code = cli.main([str(package_dir), "--write-report"])
    captured = capsysbinary.readouterr()

    assert exit_code == 1
    assert captured.out == b""
    assert b"synthetic replace failure" in captured.err
    assert not (package_dir / "validation-report.json").exists()
    assert not list(package_dir.glob(".validation-report.json.tmp-*"))


def test_manifest_swap_cannot_hide_a_historical_report_declaration(
    tmp_path, monkeypatch, capsysbinary
):
    import validate_intake_package as cli

    package_dir = tmp_path / "package"
    clean_manifest = _write_package(package_dir)
    clean_manifest_bytes = (package_dir / "case-manifest.json").read_bytes()
    report_path = package_dir / "validation-report.json"
    historical = b'{"historical":true}\n'
    report_path.write_bytes(historical)
    clean_manifest["artifacts"].append(
        _artifact(
            "artifact-validation-report",
            "validation-report",
            report_path,
            [],
        )
    )
    _save_manifest(package_dir, clean_manifest)
    real_guard = cli._guard_report_target

    def swap_manifest_after_the_required_snapshot(root_descriptor):
        real_guard(root_descriptor)
        temporary = package_dir / "case-manifest.clean"
        temporary.write_bytes(clean_manifest_bytes)
        os.replace(temporary, package_dir / "case-manifest.json")

    monkeypatch.setattr(cli, "_guard_report_target", swap_manifest_after_the_required_snapshot)

    exit_code = cli.main([str(package_dir), "--write-report"])
    captured = capsysbinary.readouterr()

    assert exit_code == 1
    assert captured.out == b""
    assert b"declared validation-report.json" in captured.err
    assert report_path.read_bytes() == historical


def test_fifo_manifest_returns_promptly_instead_of_blocking(tmp_path):
    package_dir = tmp_path / "package"
    package_dir.mkdir()
    os.mkfifo(package_dir / "case-manifest.json")

    result = subprocess.run(
        [sys.executable, str(SCRIPT), str(package_dir), "--write-report"],
        capture_output=True,
        check=False,
        timeout=2,
    )

    assert result.returncode == 2
    report = _assert_canonical_report(result.stdout, "invalid")
    assert report["errors"] == ["manifest-invalid"]
    assert result.stderr == b""


def test_handoff_hash_recipe_reads_only_blobs_from_the_exact_commit():
    handoff = (
        Path(__file__).parents[1] / "contracts" / "ctv-intake" / "README.md"
    ).read_text(encoding="utf-8")

    assert 'git rev-parse --verify "$source_commit^{commit}"' in handoff
    assert 'git ls-tree -r -z "$source_commit" -- contracts/ctv-intake/v1' in handoff
    assert 'git show "$source_commit:$path"' in handoff
    assert 'mode == "120000"' in handoff
    assert "object_type != \"blob\"" in handoff
    assert 'len(source_commit) != 40' in handoff
    assert "git ls-files" not in handoff
    assert "path.read_bytes()" not in handoff
