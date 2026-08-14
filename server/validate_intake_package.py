"""Validate one prepared CTV intake package."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import secrets
import stat
import sys

from intake_package_validator import (
    MAX_MANIFEST_BYTES,
    _PackageReader,
    _SourceReader,
    _report_package_root_failure,
    _validate_package_reader,
)


_MANIFEST_NAME = "case-manifest.json"
_REPORT_NAME = "validation-report.json"
_TEMP_PREFIX = f".{_REPORT_NAME}.tmp-"


class ReportWriteError(RuntimeError):
    """The requested report cannot be written without violating safety rules."""


def _canonical_report_bytes(report: object) -> bytes:
    payload = report.model_dump(by_alias=True, mode="json")
    return (
        json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2).encode("utf-8")
        + b"\n"
    )


def _guard_report_target(root_descriptor: int) -> None:
    try:
        target_status = os.stat(
            _REPORT_NAME,
            dir_fd=root_descriptor,
            follow_symlinks=False,
        )
    except FileNotFoundError:
        return
    except OSError as error:
        raise ReportWriteError(f"report target cannot be inspected safely: {error}") from error
    if stat.S_ISLNK(target_status.st_mode):
        raise ReportWriteError("validation-report.json target is a symlink")
    if not stat.S_ISREG(target_status.st_mode):
        raise ReportWriteError("validation-report.json target is not a regular file")


def _manifest_declares_historical_report(content: bytes | None) -> bool:
    if content is None:
        return False
    try:
        manifest = json.loads(content.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError):
        return False
    if not isinstance(manifest, dict) or not isinstance(manifest.get("artifacts"), list):
        return False
    return any(
        isinstance(artifact, dict)
        and artifact.get("kind") == "validation-report"
        and artifact.get("path") == _REPORT_NAME
        for artifact in manifest["artifacts"]
    )


def _write_all(descriptor: int, content: bytes) -> None:
    written = 0
    while written < len(content):
        count = os.write(descriptor, content[written:])
        if count <= 0:
            raise OSError("report temporary file write made no progress")
        written += count


def _atomic_write_report(root_descriptor: int, content: bytes) -> None:
    temporary_name: str | None = None
    temporary_descriptor = -1
    try:
        for _ in range(32):
            candidate = f"{_TEMP_PREFIX}{secrets.token_hex(8)}"
            try:
                temporary_descriptor = os.open(
                    candidate,
                    os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                    0o600,
                    dir_fd=root_descriptor,
                )
            except FileExistsError:
                continue
            temporary_name = candidate
            break
        if temporary_name is None:
            raise ReportWriteError("could not allocate a report temporary file")
        _write_all(temporary_descriptor, content)
        os.fsync(temporary_descriptor)
        os.close(temporary_descriptor)
        temporary_descriptor = -1
        os.replace(
            temporary_name,
            _REPORT_NAME,
            src_dir_fd=root_descriptor,
            dst_dir_fd=root_descriptor,
        )
        temporary_name = None
        os.fsync(root_descriptor)
    finally:
        if temporary_descriptor >= 0:
            os.close(temporary_descriptor)
        if temporary_name is not None:
            try:
                os.unlink(temporary_name, dir_fd=root_descriptor)
            except FileNotFoundError:
                pass


def _emit_stdout(content: bytes) -> None:
    stream = getattr(sys.stdout, "buffer", sys.stdout)
    stream.write(content)
    stream.flush()


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("package_dir", type=Path)
    parser.add_argument(
        "--source-root",
        type=Path,
        help="read-only source workspace required for a valid/prepared result",
    )
    parser.add_argument(
        "--write-report",
        action="store_true",
        help=f"atomically write the same JSON to {_REPORT_NAME} inside the package",
    )
    return parser


def _package_root_write_error(root_failure: str | None) -> ReportWriteError:
    if root_failure == "symlink":
        return ReportWriteError("package root is a symlink")
    if root_failure == "secure-open-unavailable":
        return ReportWriteError("secure package-root opening is unavailable")
    return ReportWriteError("package root is not a safe directory")


def _manifest_schema_version(content: bytes | None) -> str | None:
    if content is None:
        return None
    try:
        document = json.loads(content.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError):
        return None
    if not isinstance(document, dict):
        return None
    value = document.get("schemaVersion")
    return value if isinstance(value, str) else None


def _v2_manifest_proposal_digest(content: bytes) -> str:
    document = json.loads(content.decode("utf-8"))
    value = document.get("proposalDigest") if isinstance(document, dict) else None
    if (
        isinstance(value, str)
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    ):
        return value
    return "0" * 64


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    reader = None
    source_reader = None
    try:
        reader, root_failure = _PackageReader.open(args.package_dir)
        if reader is None:
            if args.write_report:
                raise _package_root_write_error(root_failure)
            report = _report_package_root_failure(root_failure)
            content = _canonical_report_bytes(report)
            _emit_stdout(content)
            return 2

        root_descriptor = reader.root_fd
        if root_descriptor is None:
            raise ReportWriteError("secure package-root descriptor is unavailable")
        manifest_content, _manifest_failure = reader.read_manifest()
        if _manifest_schema_version(manifest_content) == "2.0":
            if args.write_report:
                raise ReportWriteError("v2-report-writer-only")
            if args.source_root is None:
                raise ReportWriteError("v2-source-root-required")
            from ctv_inventory import open_inventory_observation
            from intake_package_validator_v2 import (
                V2ValidationExpectation,
                validate_v2_publication_reader,
            )

            assert manifest_content is not None
            with open_inventory_observation(args.source_root) as observation:
                expectation = V2ValidationExpectation(
                    observation_id=observation.observation_id,
                    proposal_digest=_v2_manifest_proposal_digest(manifest_content),
                )
                result = validate_v2_publication_reader(
                    reader, observation, expectation
                )
            content = _canonical_report_bytes(result.report)
            _emit_stdout(content)
            return 0 if result.report.outcome == "valid" else 2

        if args.write_report:
            _guard_report_target(root_descriptor)
            if _manifest_declares_historical_report(manifest_content):
                raise ReportWriteError(
                    "refusing to overwrite declared validation-report.json artifact"
                )

        source_root_failure = None
        if args.source_root is not None:
            source_reader, source_root_failure = _SourceReader.open(args.source_root)
        report = _validate_package_reader(
            reader,
            source_reader=source_reader,
            source_root_failure=source_root_failure,
        )
        content = _canonical_report_bytes(report)
        if args.write_report:
            _atomic_write_report(root_descriptor, content)
        _emit_stdout(content)
        return 0 if report.outcome == "valid" else 2
    except Exception as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    finally:
        if source_reader is not None:
            source_reader.close()
        if reader is not None:
            reader.close()


if __name__ == "__main__":
    raise SystemExit(main())
