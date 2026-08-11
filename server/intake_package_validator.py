"""Read-only semantic validation for prepared CTV intake packages."""
from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat

import fitz
import openpyxl
from pydantic import ValidationError

from intake_contract import ExceptionsDocument, PackageManifest, ValidationCheck, ValidationReport
from roster_workbook import MAX_WORKBOOK_BYTES as MAX_ROSTER_WORKBOOK_BYTES
from roster_workbook import preflight_roster_workbook


VALIDATOR_VERSION = "1.0.0"
_MIB = 1024 * 1024
MAX_MANIFEST_BYTES = 16 * _MIB
# V1 package ceilings bound in-memory snapshots. Workbook limits mirror the
# existing app gates; the PDF ceiling is deliberately higher because the
# current upload path has no lower PDF limit, and JSON artifacts stay compact.
MAX_ARTIFACT_BYTES_BY_KIND = {
    "input-pdf": 256 * _MIB,
    "roster": MAX_ROSTER_WORKBOOK_BYTES,
    "cccd": 100 * _MIB,
    "exceptions": 16 * _MIB,
    "validation-report": 16 * _MIB,
}
_MANIFEST_NAME = "case-manifest.json"
_REQUIRED_ARTIFACT_KINDS = frozenset({"input-pdf", "roster", "exceptions"})
_WINDOWS_ABSOLUTE_PATH_RE = re.compile(r"^[A-Za-z]:[\\/]")
_CLOSE_ON_EXEC = getattr(os, "O_CLOEXEC", 0)
_DIRECTORY = getattr(os, "O_DIRECTORY", 0)
_NO_FOLLOW = getattr(os, "O_NOFOLLOW", 0)
_NON_BLOCKING = getattr(os, "O_NONBLOCK", 0)
_SUPPORTS_SECURE_RELATIVE_OPEN = os.open in os.supports_dir_fd and bool(_NO_FOLLOW)


@dataclass
class _PackageReader:
    root_path: Path
    root_fd: int | None

    @classmethod
    def open(cls, package_dir: Path) -> tuple["_PackageReader | None", str | None]:
        root_path = Path(package_dir)
        if not _SUPPORTS_SECURE_RELATIVE_OPEN:
            return None, "secure-open-unavailable"
        try:
            root_fd = os.open(
                root_path,
                os.O_RDONLY | _CLOSE_ON_EXEC | _DIRECTORY | _NO_FOLLOW,
            )
        except OSError:
            return None, "symlink" if root_path.is_symlink() else "missing"
        try:
            if not stat.S_ISDIR(os.fstat(root_fd).st_mode):
                os.close(root_fd)
                return None, "missing"
        except OSError:
            os.close(root_fd)
            return None, "missing"
        return cls(root_path=root_path, root_fd=root_fd), None

    def close(self) -> None:
        if self.root_fd is not None:
            os.close(self.root_fd)
            self.root_fd = None

    def read(
        self,
        declared_path: str,
        *,
        expected_size: int | None = None,
        max_bytes: int,
    ) -> tuple[bytes | None, str | None]:
        parts = _relative_path_parts(declared_path)
        if parts is None:
            return None, "unsafe"
        if self.root_fd is None:
            return None, "secure-open-unavailable"
        return _read_relative_to_fd(
            self.root_fd,
            parts,
            expected_size=expected_size,
            max_bytes=max_bytes,
        )


def _relative_path_parts(declared_path: str) -> tuple[str, ...] | None:
    parts = declared_path.split("/")
    pure_path = PurePosixPath(declared_path)
    if (
        not declared_path
        or "\x00" in declared_path
        or pure_path.is_absolute()
        or _WINDOWS_ABSOLUTE_PATH_RE.match(declared_path)
        or "\\" in declared_path
        or any(part in {"", ".", ".."} for part in parts)
    ):
        return None
    return tuple(parts)


def _read_relative_to_fd(
    root_fd: int,
    parts: tuple[str, ...],
    *,
    expected_size: int | None,
    max_bytes: int,
) -> tuple[bytes | None, str | None]:
    parent_fd = os.dup(root_fd)
    try:
        for part in parts[:-1]:
            try:
                child_fd = os.open(
                    part,
                    os.O_RDONLY | _CLOSE_ON_EXEC | _DIRECTORY | _NO_FOLLOW,
                    dir_fd=parent_fd,
                )
            except OSError:
                return None, "symlink" if _is_symlink_at(parent_fd, part) else "missing"
            os.close(parent_fd)
            parent_fd = child_fd

        try:
            file_fd = os.open(
                parts[-1],
                os.O_RDONLY | _CLOSE_ON_EXEC | _NO_FOLLOW | _NON_BLOCKING,
                dir_fd=parent_fd,
            )
        except OSError:
            return None, "symlink" if _is_symlink_at(parent_fd, parts[-1]) else "missing"
        try:
            metadata = os.fstat(file_fd)
            if not stat.S_ISREG(metadata.st_mode):
                return None, "not-regular"
            if metadata.st_size > max_bytes:
                return None, "too-large"
            if expected_size is not None and metadata.st_size != expected_size:
                return None, "size-mismatch"
            with os.fdopen(file_fd, "rb", closefd=False) as stream:
                content = stream.read(max_bytes + 1)
            if len(content) > max_bytes:
                return None, "too-large"
            if expected_size is not None and len(content) != expected_size:
                return None, "size-mismatch"
            return content, None
        except OSError:
            return None, "missing"
        finally:
            os.close(file_fd)
    finally:
        os.close(parent_fd)


def _is_symlink_at(parent_fd: int, name: str) -> bool:
    try:
        metadata = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
    except OSError:
        return False
    return stat.S_ISLNK(metadata.st_mode)


@dataclass
class _Issues:
    errors: dict[str, set[str]] = field(default_factory=lambda: defaultdict(set))
    warnings: dict[str, set[str]] = field(default_factory=lambda: defaultdict(set))

    def error(self, code: str, *evidence_refs: str) -> None:
        self.errors[code].update(evidence_refs)

    def warning(self, code: str, *evidence_refs: str) -> None:
        self.warnings[code].update(evidence_refs)

    def report(self, manifest: PackageManifest | None) -> ValidationReport:
        error_codes = sorted(self.errors)
        warning_codes = sorted(self.warnings)
        check_codes = sorted(set(error_codes) | set(warning_codes))
        checks = [
            ValidationCheck(
                code=code,
                passed=False,
                evidenceRefs=sorted(self.errors[code] | self.warnings[code]),
            )
            for code in check_codes
        ]
        invalid = bool(error_codes)
        return ValidationReport(
            schemaVersion="1.0",
            outcome="invalid" if invalid else "valid",
            packageStatus=(
                "partially_prepared"
                if invalid or manifest is None
                else manifest.status
            ),
            checks=checks,
            errors=error_codes,
            warnings=warning_codes,
            validatedAt=datetime.now(timezone.utc),
            validatorVersion=VALIDATOR_VERSION,
        )


def validate_package(package_dir: Path) -> ValidationReport:
    """Validate one package without modifying the package or its artifacts."""
    issues = _Issues()
    reader, root_failure = _PackageReader.open(Path(package_dir))
    if root_failure == "symlink":
        issues.error("symlink-not-allowed", "package-root")
        return issues.report(None)
    if root_failure == "secure-open-unavailable":
        issues.error("secure-open-unavailable", "package-root")
        return issues.report(None)
    if reader is None:
        issues.error("manifest-invalid", _MANIFEST_NAME)
        return issues.report(None)
    try:
        return _validate_open_package(reader, issues)
    finally:
        reader.close()


def _validate_open_package(reader: _PackageReader, issues: _Issues) -> ValidationReport:
    manifest_content, manifest_failure = reader.read(
        _MANIFEST_NAME, max_bytes=MAX_MANIFEST_BYTES
    )
    if manifest_failure == "symlink":
        issues.error("symlink-not-allowed", _MANIFEST_NAME)
        return issues.report(None)
    if manifest_content is None:
        issues.error("manifest-invalid", _MANIFEST_NAME)
        return issues.report(None)
    try:
        raw_manifest = _read_json_bytes(manifest_content)
    except (UnicodeError, json.JSONDecodeError):
        issues.error("manifest-invalid", _MANIFEST_NAME)
        return issues.report(None)

    _inspect_raw_artifact_paths(raw_manifest, issues)
    _inspect_raw_unresolved_coverage(raw_manifest, issues)
    try:
        manifest = PackageManifest.model_validate(raw_manifest)
    except ValidationError:
        issues.error("manifest-invalid", _MANIFEST_NAME)
        return issues.report(None)

    artifacts_by_kind: dict[str, list] = defaultdict(list)
    for artifact in manifest.artifacts:
        artifacts_by_kind[artifact.kind].append(artifact)
    for kind in sorted(_REQUIRED_ARTIFACT_KINDS - set(artifacts_by_kind)):
        issues.error("missing-required-artifact", kind)
    for kind, artifacts in sorted(artifacts_by_kind.items()):
        if len(artifacts) > 1:
            issues.error(
                "duplicate-artifact-kind",
                *(artifact.artifact_id for artifact in sorted(
                    artifacts, key=lambda item: item.artifact_id
                )),
            )

    usable_artifacts: dict[str, bytes] = {}
    for artifact in sorted(manifest.artifacts, key=lambda item: item.artifact_id):
        content, failure = reader.read(
            artifact.path,
            expected_size=artifact.size,
            max_bytes=MAX_ARTIFACT_BYTES_BY_KIND[artifact.kind],
        )
        if failure == "unsafe":
            issues.error("unsafe-artifact-path", artifact.artifact_id)
            continue
        if failure == "symlink":
            issues.error("symlink-not-allowed", artifact.artifact_id)
            continue
        if failure == "too-large":
            issues.error("artifact-too-large", artifact.artifact_id)
            continue
        if failure == "size-mismatch":
            issues.error("artifact-size-mismatch", artifact.artifact_id)
            continue
        if content is None:
            issues.error("artifact-missing", artifact.artifact_id)
            continue
        digest_matches = hashlib.sha256(content).hexdigest() == artifact.sha256
        if not digest_matches:
            issues.error("artifact-digest-mismatch", artifact.artifact_id)
        if digest_matches:
            usable_artifacts[artifact.artifact_id] = content

    exceptions = _load_exceptions(
        manifest, artifacts_by_kind, usable_artifacts, issues
    )
    derived_pdf_page_counts = _inspect_pdfs(
        artifacts_by_kind, usable_artifacts, issues
    )
    _inspect_rosters(
        manifest, artifacts_by_kind, usable_artifacts, issues
    )
    _inspect_validation_reports(artifacts_by_kind, usable_artifacts, issues)
    _check_references(manifest, exceptions, issues)
    _check_input_pdf_provenance(manifest, artifacts_by_kind, issues)
    _check_pdf_coverage(
        manifest, artifacts_by_kind, derived_pdf_page_counts, issues
    )
    _check_exceptions(manifest, exceptions, issues)
    _check_unresolved_coverage(manifest, issues)
    return issues.report(manifest)


def _read_json_bytes(content: bytes) -> object:
    return json.loads(content.decode("utf-8"))


def _inspect_raw_artifact_paths(raw_manifest: object, issues: _Issues) -> None:
    if not isinstance(raw_manifest, dict):
        return
    artifacts = raw_manifest.get("artifacts")
    if not isinstance(artifacts, list):
        return
    for index, artifact in enumerate(artifacts):
        if not isinstance(artifact, dict):
            continue
        evidence = artifact.get("artifactId")
        if not isinstance(evidence, str) or not evidence:
            evidence = f"artifact-index-{index}"
        path = artifact.get("path")
        if not isinstance(path, str):
            issues.error("unsafe-artifact-path", evidence)
            continue
        if _relative_path_parts(path) is None:
            issues.error("unsafe-artifact-path", evidence)


def _inspect_raw_unresolved_coverage(raw_manifest: object, issues: _Issues) -> None:
    if not isinstance(raw_manifest, dict):
        return
    sources = raw_manifest.get("sources")
    if isinstance(sources, list):
        for index, source in enumerate(sources):
            if not isinstance(source, dict) or source.get("coverageState") != "unresolved":
                continue
            source_id = source.get("sourceId")
            evidence = source_id if isinstance(source_id, str) else f"source-index-{index}"
            issues.error("unresolved-coverage", evidence)
    pages = raw_manifest.get("pdfPages")
    if isinstance(pages, list):
        for index, page in enumerate(pages):
            if not isinstance(page, dict) or page.get("coverageState") != "unresolved":
                continue
            source_id = page.get("sourceId")
            page_number = page.get("sourcePage")
            evidence = (
                f"{source_id}#page={page_number}"
                if isinstance(source_id, str) and isinstance(page_number, int)
                else f"page-index-{index}"
            )
            issues.error("unresolved-coverage", evidence)


def _load_exceptions(
    manifest: PackageManifest,
    artifacts_by_kind: dict[str, list],
    usable_artifacts: dict[str, bytes],
    issues: _Issues,
) -> ExceptionsDocument | None:
    documents: list[ExceptionsDocument] = []
    for artifact in sorted(
        artifacts_by_kind.get("exceptions", []), key=lambda item: item.artifact_id
    ):
        content = usable_artifacts.get(artifact.artifact_id)
        if content is None:
            continue
        try:
            documents.append(
                ExceptionsDocument.model_validate(_read_json_bytes(content))
            )
        except (UnicodeError, json.JSONDecodeError, ValidationError):
            issues.error("exceptions-invalid", artifact.artifact_id)
    if not documents:
        return None
    if len(documents) == 1:
        return documents[0]
    all_items = [item for document in documents for item in document.items]
    try:
        return ExceptionsDocument(schemaVersion="1.0", items=all_items)
    except ValidationError:
        issues.error(
            "exceptions-invalid",
            *(artifact.artifact_id for artifact in artifacts_by_kind["exceptions"]),
        )
        return None


def _inspect_pdfs(
    artifacts_by_kind: dict[str, list],
    usable_artifacts: dict[str, bytes],
    issues: _Issues,
) -> dict[str, int]:
    page_counts: dict[str, int] = {}
    for artifact in sorted(
        artifacts_by_kind.get("input-pdf", []), key=lambda item: item.artifact_id
    ):
        content = usable_artifacts.get(artifact.artifact_id)
        if content is None:
            continue
        try:
            with fitz.open(stream=content, filetype="pdf") as document:
                if not document.is_pdf or document.needs_pass:
                    raise ValueError("PDF is encrypted or has the wrong format")
                page_count = document.page_count
                for page_index in range(page_count):
                    document.load_page(page_index)
        except (OSError, RuntimeError, ValueError, fitz.FileDataError):
            issues.error("pdf-unreadable", artifact.artifact_id)
            continue
        page_counts[artifact.artifact_id] = page_count
    return page_counts


def _inspect_rosters(
    manifest: PackageManifest,
    artifacts_by_kind: dict[str, list],
    usable_artifacts: dict[str, bytes],
    issues: _Issues,
) -> None:
    mapping = manifest.roster_mapping
    mapping_valid = _mapping_is_unambiguous(mapping)
    if not mapping_valid:
        issues.error("roster-mapping-missing", "rosterMapping")

    roster_artifacts = sorted(
        artifacts_by_kind.get("roster", []), key=lambda item: item.artifact_id
    )
    if mapping is not None and not any(
        mapping.source_id in artifact.source_ids for artifact in roster_artifacts
    ):
        issues.error("roster-mapping-missing", mapping.source_id)

    for artifact in roster_artifacts:
        content = usable_artifacts.get(artifact.artifact_id)
        if content is None:
            continue
        try:
            preflight_roster_workbook(io.BytesIO(content))
            workbook = openpyxl.load_workbook(
                io.BytesIO(content), read_only=True, data_only=True
            )
        except Exception:
            issues.error("roster-unreadable", artifact.artifact_id)
            continue
        try:
            if not mapping_valid or mapping is None:
                continue
            if mapping.sheet_name not in workbook.sheetnames:
                issues.error("roster-sheet-missing", mapping.sheet_name)
                continue
            worksheet = workbook[mapping.sheet_name]
            header_row = next(
                worksheet.iter_rows(min_row=1, max_row=1, values_only=True), ()
            )
            header_positions: dict[object, list[int]] = defaultdict(list)
            for index, value in enumerate(header_row):
                header_positions[value].append(index)
            column_names = mapping.canonical_to_source_columns
            missing_columns = sorted(
                name
                for name in (column_names["name"], column_names["identity"])
                if len(header_positions[name]) != 1
            )
            if missing_columns:
                issues.error("roster-column-missing", *missing_columns)
                continue
            identity_index = header_positions[column_names["identity"]][0]
            identity_rows: dict[object, list[int]] = defaultdict(list)
            for row_number, row in enumerate(
                worksheet.iter_rows(min_row=2, values_only=True), start=2
            ):
                value = row[identity_index] if identity_index < len(row) else None
                if value is not None and value != "":
                    identity_rows[value].append(row_number)
            duplicate_rows = sorted(
                row_number
                for rows in identity_rows.values()
                if len(rows) > 1
                for row_number in rows
            )
            if duplicate_rows:
                issues.error(
                    "roster-identity-duplicate",
                    *(
                        f"{artifact.artifact_id}#row={row_number}"
                        for row_number in duplicate_rows
                    ),
                )
        except (OSError, RuntimeError, ValueError):
            issues.error("roster-unreadable", artifact.artifact_id)
        finally:
            workbook.close()


def _inspect_validation_reports(
    artifacts_by_kind: dict[str, list],
    usable_artifacts: dict[str, bytes],
    issues: _Issues,
) -> None:
    for artifact in sorted(
        artifacts_by_kind.get("validation-report", []),
        key=lambda item: item.artifact_id,
    ):
        content = usable_artifacts.get(artifact.artifact_id)
        if content is None:
            continue
        try:
            ValidationReport.model_validate(_read_json_bytes(content))
        except (UnicodeError, json.JSONDecodeError, ValidationError):
            issues.error("validation-report-invalid", artifact.artifact_id)


def _mapping_is_unambiguous(mapping) -> bool:
    if mapping is None:
        return False
    columns = mapping.canonical_to_source_columns
    name = columns.get("name")
    identity = columns.get("identity")
    return (
        isinstance(name, str)
        and bool(name)
        and isinstance(identity, str)
        and bool(identity)
        and name != identity
    )


def _check_references(
    manifest: PackageManifest,
    exceptions: ExceptionsDocument | None,
    issues: _Issues,
) -> None:
    source_ids = {source.source_id for source in manifest.sources}
    artifact_ids = {artifact.artifact_id for artifact in manifest.artifacts}
    decision_ids = {decision.decision_id for decision in manifest.decisions}
    exception_ids = (
        {item.exception_id for item in exceptions.items} if exceptions is not None else set()
    )
    known_evidence_refs = source_ids | artifact_ids | decision_ids | exception_ids
    for source in manifest.sources:
        if source.media_type != "application/pdf":
            continue
        if source.page_count is not None:
            known_evidence_refs.update(
                f"{source.source_id}#page={page_number}"
                for page_number in range(1, source.page_count + 1)
            )
        else:
            known_evidence_refs.update(
                f"{page.source_id}#page={page.source_page}"
                for page in manifest.pdf_pages
                if page.source_id == source.source_id
            )

    unknown_sources: set[str] = set()
    unknown_decisions: set[str] = set()
    for source in manifest.sources:
        if source.duplicate_source_id and source.duplicate_source_id not in source_ids:
            unknown_sources.add(source.duplicate_source_id)
        if source.decision_id and source.decision_id not in decision_ids:
            unknown_decisions.add(source.decision_id)
    for page in manifest.pdf_pages:
        if page.source_id not in source_ids:
            unknown_sources.add(page.source_id)
        if page.decision_id and page.decision_id not in decision_ids:
            unknown_decisions.add(page.decision_id)
    for artifact in manifest.artifacts:
        unknown_sources.update(
            source_id for source_id in artifact.source_ids if source_id not in source_ids
        )
    if manifest.roster_mapping and manifest.roster_mapping.source_id not in source_ids:
        unknown_sources.add(manifest.roster_mapping.source_id)

    unknown_evidence_refs: set[str] = set()
    for decision in manifest.decisions:
        for index, evidence_ref in enumerate(decision.evidence_refs):
            if evidence_ref not in known_evidence_refs:
                unknown_evidence_refs.add(
                    f"{decision.decision_id}#evidence-ref={index}"
                )
    if exceptions is not None:
        for item in exceptions.items:
            for index, evidence_ref in enumerate(item.evidence_refs):
                if evidence_ref not in known_evidence_refs:
                    unknown_evidence_refs.add(
                        f"{item.exception_id}#evidence-ref={index}"
                    )

    if unknown_sources:
        issues.error("source-reference-unknown", *sorted(unknown_sources))
    if unknown_decisions:
        issues.error("decision-reference-unknown", *sorted(unknown_decisions))
    if unknown_evidence_refs:
        issues.error(
            "evidence-reference-unknown", *sorted(unknown_evidence_refs)
        )


def _check_input_pdf_provenance(
    manifest: PackageManifest,
    artifacts_by_kind: dict[str, list],
    issues: _Issues,
) -> None:
    sources_by_id = {source.source_id: source for source in manifest.sources}
    represented_source_ids = {
        page.source_id for page in manifest.pdf_pages if page.target_page is not None
    }
    for artifact in sorted(
        artifacts_by_kind.get("input-pdf", []), key=lambda item: item.artifact_id
    ):
        declared_source_ids = set(artifact.source_ids)
        omitted_source_ids = sorted(represented_source_ids - declared_source_ids)
        extra_source_ids = sorted(declared_source_ids - represented_source_ids)
        non_pdf_source_ids = sorted(
            source_id
            for source_id in declared_source_ids
            if source_id in sources_by_id
            and sources_by_id[source_id].media_type != "application/pdf"
        )
        evidence_refs = [
            f"{artifact.artifact_id}#omitted-source={index}"
            for index, _source_id in enumerate(omitted_source_ids, start=1)
        ]
        evidence_refs.extend(
            f"{artifact.artifact_id}#extra-source={index}"
            for index, _source_id in enumerate(extra_source_ids, start=1)
        )
        evidence_refs.extend(
            f"{artifact.artifact_id}#non-pdf-source={index}"
            for index, _source_id in enumerate(non_pdf_source_ids, start=1)
        )
        if evidence_refs:
            issues.error("input-pdf-provenance-mismatch", *evidence_refs)


def _check_pdf_coverage(
    manifest: PackageManifest,
    artifacts_by_kind: dict[str, list],
    derived_page_counts: dict[str, int],
    issues: _Issues,
) -> None:
    source_coverage = Counter(
        (page.source_id, page.source_page) for page in manifest.pdf_pages
    )
    source_ids = {source.source_id for source in manifest.sources}
    pdf_sources = sorted(
        (
            source
            for source in manifest.sources
            if source.media_type == "application/pdf"
        ),
        key=lambda source: source.source_id,
    )
    pdf_source_ids = {source.source_id for source in pdf_sources}
    for source in pdf_sources:
        source_id = source.source_id
        page_count = source.page_count
        if page_count is None:
            issues.error("page-coverage-missing", f"{source_id}#page-count")
            continue
        for page_number in range(1, page_count + 1):
            count = source_coverage[(source_id, page_number)]
            evidence = f"{source_id}#page={page_number}"
            if count == 0:
                issues.error("page-coverage-missing", evidence)
            elif count > 1:
                issues.error("page-coverage-extra", evidence)
        for covered_source, page_number in sorted(source_coverage):
            if covered_source == source_id and page_number > page_count:
                issues.error(
                    "page-coverage-extra", f"{source_id}#page={page_number}"
                )
    for source_id, page_number in sorted(source_coverage):
        if source_id not in pdf_source_ids and source_id in source_ids:
            issues.error(
                "page-coverage-extra", f"{source_id}#page={page_number}"
            )

    target_coverage = Counter(
        page.target_page
        for page in manifest.pdf_pages
        if page.target_page is not None
    )
    for artifact in sorted(
        artifacts_by_kind.get("input-pdf", []), key=lambda item: item.artifact_id
    ):
        page_count = derived_page_counts.get(artifact.artifact_id)
        if page_count is None:
            continue
        for page_number in range(1, page_count + 1):
            count = target_coverage[page_number]
            evidence = f"{artifact.artifact_id}#target-page={page_number}"
            if count == 0:
                issues.error("page-coverage-missing", evidence)
            elif count > 1:
                issues.error("page-coverage-extra", evidence)
        for page_number in sorted(target_coverage):
            if page_number > page_count:
                issues.error(
                    "page-coverage-extra",
                    f"{artifact.artifact_id}#target-page={page_number}",
                )


def _check_exceptions(
    manifest: PackageManifest,
    exceptions: ExceptionsDocument | None,
    issues: _Issues,
) -> None:
    declared_ids = set(manifest.exception_ids)
    document_ids = (
        {item.exception_id for item in exceptions.items}
        if exceptions is not None
        else set()
    )
    unresolved_references = declared_ids ^ document_ids
    if unresolved_references:
        issues.error("exception-reference-unknown", *sorted(unresolved_references))
    if exceptions is None:
        return
    for item in sorted(exceptions.items, key=lambda value: value.exception_id):
        if item.resolution != "open":
            continue
        if item.severity == "blocking":
            issues.error("blocking-exception", item.exception_id)
        else:
            issues.warning(item.code, item.exception_id)


def _check_unresolved_coverage(manifest: PackageManifest, issues: _Issues) -> None:
    for source in manifest.sources:
        if source.coverage_state == "unresolved":
            issues.error("unresolved-coverage", source.source_id)
    for page in manifest.pdf_pages:
        if page.coverage_state == "unresolved":
            issues.error(
                "unresolved-coverage",
                f"{page.source_id}#page={page.source_page}",
            )
