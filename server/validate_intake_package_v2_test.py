"""Standalone v2 publication-validation dispatch without report authorship."""

from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys

from intake_fixture_factory_v2 import materialize_v2_fixture


SCRIPT = Path(__file__).with_name("validate_intake_package.py")


def _run(*args: object) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(
        [sys.executable, str(SCRIPT), *(str(item) for item in args)],
        capture_output=True,
        check=False,
    )


def _canonical(stdout: bytes) -> dict:
    report = json.loads(stdout)
    assert stdout == (
        json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2).encode()
        + b"\n"
    )
    return report


def test_v2_standalone_dispatch_validates_existing_publication_receipt(tmp_path):
    fixture = materialize_v2_fixture(
        "complete", tmp_path / "fixture", include_receipt=True
    )

    result = _run(
        fixture.package_dir, "--source-root", fixture.source_dir
    )

    assert result.returncode == 0
    report = _canonical(result.stdout)
    assert report["schemaVersion"] == "2.0"
    assert report["outcome"] == "valid"
    assert report["checks"][-1] == {
        "code": "validation-report-consistent",
        "evidenceRefs": ["receipt"],
        "passed": True,
    }
    assert result.stderr == b""


def test_v2_standalone_rejects_missing_receipt_as_an_invalid_publication(tmp_path):
    fixture = materialize_v2_fixture("complete", tmp_path / "fixture")

    result = _run(
        fixture.package_dir, "--source-root", fixture.source_dir
    )

    assert result.returncode == 2
    report = _canonical(result.stdout)
    assert report["outcome"] == "invalid"
    assert report["errors"] == ["validation-report-consistent"]
    assert result.stderr == b""


def test_v2_standalone_requires_one_content_bound_source_observation(tmp_path):
    fixture = materialize_v2_fixture(
        "complete", tmp_path / "fixture", include_receipt=True
    )

    result = _run(fixture.package_dir)

    assert result.returncode == 1
    assert result.stdout == b""
    assert result.stderr == b"error: v2-source-root-required\n"


def test_v2_write_report_is_reserved_for_the_transaction_writer(tmp_path):
    fixture = materialize_v2_fixture(
        "complete", tmp_path / "fixture", include_receipt=True
    )
    report_path = fixture.package_dir / "validation-report.json"
    before = report_path.read_bytes()

    result = _run(
        fixture.package_dir,
        "--source-root",
        fixture.source_dir,
        "--write-report",
    )

    assert result.returncode == 1
    assert result.stdout == b""
    assert result.stderr == b"error: v2-report-writer-only\n"
    assert report_path.read_bytes() == before
    assert not list(fixture.package_dir.glob(".validation-report.json.tmp-*"))


def test_v2_dispatch_reads_the_manifest_once_through_the_open_reader(
    tmp_path, monkeypatch, capsysbinary
):
    import validate_intake_package as cli

    fixture = materialize_v2_fixture(
        "complete", tmp_path / "fixture", include_receipt=True
    )
    import intake_package_validator as validator

    original = validator._read_relative_to_fd
    calls = 0

    def counted(root_fd, parts, **kwargs):
        nonlocal calls
        if parts == ("case-manifest.json",):
            calls += 1
        return original(root_fd, parts, **kwargs)

    monkeypatch.setattr(validator, "_read_relative_to_fd", counted)

    exit_code = cli.main([
        str(fixture.package_dir), "--source-root", str(fixture.source_dir)
    ])
    captured = capsysbinary.readouterr()

    assert exit_code == 0
    assert _canonical(captured.out)["outcome"] == "valid"
    assert captured.err == b""
    assert calls == 1
