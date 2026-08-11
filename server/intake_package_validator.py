"""Read-only semantic validation for prepared CTV intake packages."""
from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
from typing import Iterable

import fitz
import openpyxl
from pydantic import ValidationError

from intake_contract import ExceptionsDocument, PackageManifest, ValidationCheck, ValidationReport
from roster_workbook import RosterWorkbookError, preflight_roster_workbook


VALIDATOR_VERSION = "1.0.0"
_MANIFEST_NAME = "case-manifest.json"
_REQUIRED_ARTIFACT_KINDS = frozenset({"input-pdf", "roster", "exceptions"})
_WINDOWS_ABSOLUTE_PATH_RE = re.compile(r"^[A-Za-z]:[\\/]")


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
    package_root = Path(package_dir)
    issues = _Issues()
    if package_root.is_symlink():
        issues.error("symlink-not-allowed", str(package_root))
        return issues.report(None)
    if not package_root.is_dir():
        issues.error("manifest-invalid", _MANIFEST_NAME)
        return issues.report(None)

    package_root = package_root.resolve()
    manifest_path = package_root / _MANIFEST_NAME
    if manifest_path.is_symlink():
        issues.error("symlink-not-allowed", _MANIFEST_NAME)
        return issues.report(None)

    try:
        raw_manifest = _read_json(manifest_path)
    except (OSError, UnicodeError, json.JSONDecodeError):
        issues.error("manifest-invalid", _MANIFEST_NAME)
        return issues.report(None)

    _inspect_raw_artifact_paths(package_root, raw_manifest, issues)
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

    usable_artifacts: dict[str, Path] = {}
    for artifact in sorted(manifest.artifacts, key=lambda item: item.artifact_id):
        path = _safe_artifact_path(
            package_root, artifact.path, artifact.artifact_id, issues
        )
        if path is None:
            continue
        if not path.is_file():
            issues.error("artifact-missing", artifact.artifact_id)
            continue
        try:
            actual_size = path.stat().st_size
        except OSError:
            issues.error("artifact-missing", artifact.artifact_id)
            continue
        size_matches = actual_size == artifact.size
        if not size_matches:
            issues.error("artifact-size-mismatch", artifact.artifact_id)
        try:
            digest_matches = _sha256(path) == artifact.sha256
        except OSError:
            issues.error("artifact-missing", artifact.artifact_id)
            continue
        if not digest_matches:
            issues.error("artifact-digest-mismatch", artifact.artifact_id)
        if size_matches and digest_matches:
            usable_artifacts[artifact.artifact_id] = path

    exceptions = _load_exceptions(
        manifest, artifacts_by_kind, usable_artifacts, issues
    )
    pdf_page_counts = _inspect_pdfs(
        manifest, artifacts_by_kind, usable_artifacts, issues
    )
    _inspect_rosters(
        manifest, artifacts_by_kind, usable_artifacts, issues
    )
    _check_references(manifest, exceptions, issues)
    _check_pdf_coverage(manifest, pdf_page_counts, issues)
    _check_exceptions(manifest, exceptions, issues)
    _check_unresolved_coverage(manifest, issues)
    return issues.report(manifest)


def _read_json(path: Path) -> object:
    return json.loads(path.read_text(encoding="utf-8"))


def _inspect_raw_artifact_paths(
    package_root: Path, raw_manifest: object, issues: _Issues
) -> None:
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
        _safe_artifact_path(package_root, path, evidence, issues)


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


def _safe_artifact_path(
    package_root: Path,
    declared_path: str,
    evidence_ref: str,
    issues: _Issues,
) -> Path | None:
    parts = declared_path.split("/")
    pure_path = PurePosixPath(declared_path)
    if (
        not declared_path
        or pure_path.is_absolute()
        or _WINDOWS_ABSOLUTE_PATH_RE.match(declared_path)
        or "\\" in declared_path
        or any(part in {"", ".", ".."} for part in parts)
    ):
        issues.error("unsafe-artifact-path", evidence_ref)
        return None

    candidate = package_root.joinpath(*parts)
    current = package_root
    for part in parts:
        current = current / part
        if current.is_symlink():
            issues.error("symlink-not-allowed", evidence_ref)
            return None
    try:
        candidate.resolve(strict=False).relative_to(package_root)
    except (OSError, ValueError):
        issues.error("unsafe-artifact-path", evidence_ref)
        return None
    return candidate


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _load_exceptions(
    manifest: PackageManifest,
    artifacts_by_kind: dict[str, list],
    usable_artifacts: dict[str, Path],
    issues: _Issues,
) -> ExceptionsDocument | None:
    documents: list[ExceptionsDocument] = []
    for artifact in sorted(
        artifacts_by_kind.get("exceptions", []), key=lambda item: item.artifact_id
    ):
        path = usable_artifacts.get(artifact.artifact_id)
        if path is None:
            continue
        try:
            documents.append(ExceptionsDocument.model_validate(_read_json(path)))
        except (OSError, UnicodeError, json.JSONDecodeError, ValidationError):
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
    manifest: PackageManifest,
    artifacts_by_kind: dict[str, list],
    usable_artifacts: dict[str, Path],
    issues: _Issues,
) -> dict[str, int]:
    source_ids = {
        source.source_id
        for source in manifest.sources
        if source.media_type == "application/pdf"
    }
    page_counts: dict[str, int] = {}
    for artifact in sorted(
        artifacts_by_kind.get("input-pdf", []), key=lambda item: item.artifact_id
    ):
        path = usable_artifacts.get(artifact.artifact_id)
        if path is None:
            continue
        try:
            with fitz.open(path) as document:
                if not document.is_pdf or document.needs_pass:
                    raise ValueError("PDF is encrypted or has the wrong format")
                page_count = document.page_count
                for page_index in range(page_count):
                    document.load_page(page_index)
        except (OSError, RuntimeError, ValueError, fitz.FileDataError):
            issues.error("pdf-unreadable", artifact.artifact_id)
            continue
        for source_id in artifact.source_ids:
            if source_id in source_ids and source_id not in page_counts:
                page_counts[source_id] = page_count
    return page_counts


def _inspect_rosters(
    manifest: PackageManifest,
    artifacts_by_kind: dict[str, list],
    usable_artifacts: dict[str, Path],
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
        path = usable_artifacts.get(artifact.artifact_id)
        if path is None:
            continue
        try:
            preflight_roster_workbook(path)
            workbook = openpyxl.load_workbook(path, read_only=True, data_only=True)
        except (OSError, ValueError, RosterWorkbookError):
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
    known_evidence_refs.update(
        f"{page.source_id}#page={page.source_page}" for page in manifest.pdf_pages
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

    evidence_refs: Iterable[str] = (
        ref for decision in manifest.decisions for ref in decision.evidence_refs
    )
    exception_evidence_refs = (
        (ref for item in exceptions.items for ref in item.evidence_refs)
        if exceptions is not None
        else ()
    )
    for evidence_ref in (*evidence_refs, *exception_evidence_refs):
        if evidence_ref not in known_evidence_refs:
            unknown_sources.add(evidence_ref)

    if unknown_sources:
        issues.error("source-reference-unknown", *sorted(unknown_sources))
    if unknown_decisions:
        issues.error("decision-reference-unknown", *sorted(unknown_decisions))


def _check_pdf_coverage(
    manifest: PackageManifest,
    page_counts: dict[str, int],
    issues: _Issues,
) -> None:
    coverage = Counter((page.source_id, page.source_page) for page in manifest.pdf_pages)
    pdf_source_ids = {
        source.source_id
        for source in manifest.sources
        if source.media_type == "application/pdf"
    }
    for source_id, page_count in sorted(page_counts.items()):
        for page_number in range(1, page_count + 1):
            count = coverage[(source_id, page_number)]
            evidence = f"{source_id}#page={page_number}"
            if count == 0:
                issues.error("page-coverage-missing", evidence)
            elif count > 1:
                issues.error("page-coverage-extra", evidence)
        for covered_source, page_number in sorted(coverage):
            if covered_source == source_id and page_number > page_count:
                issues.error(
                    "page-coverage-extra", f"{source_id}#page={page_number}"
                )
    for source_id, page_number in sorted(coverage):
        if source_id in pdf_source_ids and source_id not in page_counts:
            continue
        if source_id not in pdf_source_ids and source_id in {
            source.source_id for source in manifest.sources
        }:
            issues.error(
                "page-coverage-extra", f"{source_id}#page={page_number}"
            )


def _check_exceptions(
    manifest: PackageManifest,
    exceptions: ExceptionsDocument | None,
    issues: _Issues,
) -> None:
    if exceptions is None:
        return
    declared_ids = set(manifest.exception_ids)
    document_ids = {item.exception_id for item in exceptions.items}
    unresolved_references = declared_ids ^ document_ids
    if unresolved_references:
        issues.error("exception-reference-unknown", *sorted(unresolved_references))
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
