"""Typed, filesystem-independent contract for CTV prepared packages.

These models validate the JSON document shapes and their local invariants.
They deliberately do not inspect package files or resolve references across
documents; those checks belong to the package validation layer.
"""
from __future__ import annotations

import re
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


CoverageState = Literal[
    "assigned", "shared", "duplicate", "unsupported", "unreadable",
    "excluded-by-user", "unresolved",
]
PackageStatus = Literal["prepared", "partially_prepared"]
ValidationOutcome = Literal["valid", "invalid"]
ExceptionSeverity = Literal["warning", "blocking"]
ArtifactKind = Literal["input-pdf", "roster", "cccd", "exceptions", "validation-report"]
ExceptionResolution = Literal["open", "accepted-partial", "resolved"]
DecisionType = Literal[
    "assign-source", "share-source", "mark-duplicate", "exclude-source",
    "assign-page", "select-roster-sheet", "map-roster-column",
    "approve-preview", "accept-partial",
]


EXCEPTION_CODES = {
    "artifact-outside-package": "Artifact path is outside the package artifact directory.",
    "blocking-exception": "A blocking exception prevents a prepared package.",
    "duplicate-id": "A document contains duplicate stable identifiers.",
    "malformed-sha256": "A SHA-256 value is malformed.",
    "path-not-workspace-relative": "A path is not workspace-relative.",
    "unassigned-page": "A PDF page is not assigned to package coverage.",
    "unresolved-coverage": "Coverage remains unresolved.",
    "zero-based-page": "A PDF page number must be one-based.",
}

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_WINDOWS_ABSOLUTE_PATH_RE = re.compile(r"^[A-Za-z]:[\\/]")
_KEBAB_CASE_CODE_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")


class _ContractModel(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)


def _validate_relative_path(value: str) -> str:
    if not value or value.startswith("/") or _WINDOWS_ABSOLUTE_PATH_RE.match(value):
        raise ValueError("path must be workspace-relative")
    if "\\" in value or any(part in {"", ".", ".."} for part in value.split("/")):
        raise ValueError("path must not contain traversal or empty segments")
    return value


def _validate_kebab_case_code(value: str) -> str:
    if not _KEBAB_CASE_CODE_RE.fullmatch(value):
        raise ValueError("code must be lower-case kebab-case")
    return value


class Source(_ContractModel):
    source_id: str = Field(alias="sourceId", min_length=1)
    path: str = Field(min_length=1)
    media_type: str = Field(alias="mediaType", min_length=1)
    page_count: int | None = Field(default=None, alias="pageCount", ge=1)
    size: int = Field(ge=0)
    sha256: str
    coverage_state: CoverageState = Field(alias="coverageState")
    duplicate_source_id: str | None = Field(default=None, alias="duplicateSourceId", min_length=1)
    decision_id: str | None = Field(default=None, alias="decisionId", min_length=1)

    @field_validator("path")
    @classmethod
    def path_is_workspace_relative(cls, value: str) -> str:
        return _validate_relative_path(value)

    @field_validator("sha256")
    @classmethod
    def sha256_is_valid(cls, value: str) -> str:
        if not _SHA256_RE.fullmatch(value):
            raise ValueError("sha256 must be a lowercase 64-character hexadecimal value")
        return value


class PdfPage(_ContractModel):
    source_id: str = Field(alias="sourceId", min_length=1)
    source_page: int = Field(alias="sourcePage", ge=1)
    coverage_state: CoverageState = Field(alias="coverageState")
    target_page: int | None = Field(default=None, alias="targetPage", ge=1)
    decision_id: str | None = Field(default=None, alias="decisionId", min_length=1)


class Artifact(_ContractModel):
    artifact_id: str = Field(alias="artifactId", min_length=1)
    kind: ArtifactKind
    path: str = Field(min_length=1)
    size: int = Field(ge=0)
    sha256: str
    source_ids: list[str] = Field(alias="sourceIds")

    @field_validator("path")
    @classmethod
    def path_is_package_relative(cls, value: str) -> str:
        return _validate_relative_path(value)

    @field_validator("sha256")
    @classmethod
    def sha256_is_valid(cls, value: str) -> str:
        if not _SHA256_RE.fullmatch(value):
            raise ValueError("sha256 must be a lowercase 64-character hexadecimal value")
        return value


class RosterMapping(_ContractModel):
    source_id: str = Field(alias="sourceId", min_length=1)
    sheet_name: str = Field(alias="sheetName", min_length=1)
    canonical_to_source_columns: dict[str, str] = Field(alias="canonicalToSourceColumns", min_length=1)


class Decision(_ContractModel):
    decision_id: str = Field(alias="decisionId", min_length=1)
    proposal_version: str = Field(alias="proposalVersion", min_length=1)
    type: DecisionType
    actor: Literal["user"]
    timestamp: datetime
    evidence_refs: list[str] = Field(alias="evidenceRefs")


class ExceptionItem(_ContractModel):
    exception_id: str = Field(alias="exceptionId", min_length=1)
    code: str = Field(min_length=1)
    severity: ExceptionSeverity
    evidence_refs: list[str] = Field(alias="evidenceRefs")
    explanation: str = Field(min_length=1)
    required_action: str = Field(alias="requiredAction", min_length=1)
    resolution: ExceptionResolution

    @field_validator("code")
    @classmethod
    def code_is_known(cls, value: str) -> str:
        value = _validate_kebab_case_code(value)
        if value not in EXCEPTION_CODES:
            raise ValueError("exception code is not in EXCEPTION_CODES")
        return value


class ExceptionsDocument(_ContractModel):
    schema_version: Literal["1.0"] = Field(alias="schemaVersion")
    items: list[ExceptionItem]

    @model_validator(mode="after")
    def exception_ids_are_unique(self) -> "ExceptionsDocument":
        _require_unique(self.items, "exception_id", "exception IDs")
        return self


class ValidationCheck(_ContractModel):
    code: str = Field(min_length=1)
    passed: bool
    evidence_refs: list[str] = Field(alias="evidenceRefs")

    @field_validator("code")
    @classmethod
    def code_is_kebab_case(cls, value: str) -> str:
        return _validate_kebab_case_code(value)


class ValidationReport(_ContractModel):
    schema_version: Literal["1.0"] = Field(alias="schemaVersion")
    outcome: ValidationOutcome
    package_status: PackageStatus = Field(alias="packageStatus")
    checks: list[ValidationCheck]
    errors: list[str]
    warnings: list[str]
    validated_at: datetime = Field(alias="validatedAt")
    validator_version: str = Field(alias="validatorVersion", min_length=1)

    @model_validator(mode="after")
    def report_is_internally_consistent(self) -> "ValidationReport":
        if (self.outcome == "valid") != (not self.errors):
            raise ValueError("validation outcome must agree with errors")
        if self.package_status == "prepared" and self.errors:
            raise ValueError("prepared packages cannot contain blocking exceptions")
        check_codes = [check.code for check in self.checks]
        if len(check_codes) != len(set(check_codes)):
            raise ValueError("validation check codes must be unique")
        if len(self.errors) != len(set(self.errors)) or len(self.warnings) != len(set(self.warnings)):
            raise ValueError("validation issue codes must be unique")
        if set(self.errors) & set(self.warnings):
            raise ValueError("a validation code cannot be both an error and warning")
        failed_codes = {check.code for check in self.checks if not check.passed}
        issue_codes = set(self.errors) | set(self.warnings)
        if failed_codes != issue_codes:
            raise ValueError("failed checks must correspond exactly to errors and warnings")
        return self


class PackageManifest(_ContractModel):
    schema_version: Literal["1.0"] = Field(alias="schemaVersion")
    batch_id: str = Field(alias="batchId", min_length=1)
    case_id: str = Field(alias="caseId", min_length=1)
    fa_code: str | None = Field(alias="faCode", default=None, min_length=1)
    package_version: str = Field(alias="packageVersion", min_length=1)
    status: PackageStatus
    compatibility_target: Literal["ctv-intake-v1"] = Field(alias="compatibilityTarget")
    sources: list[Source]
    pdf_pages: list[PdfPage] = Field(alias="pdfPages")
    artifacts: list[Artifact]
    roster_mapping: RosterMapping | None = Field(alias="rosterMapping", default=None)
    decisions: list[Decision]
    exception_ids: list[str] = Field(alias="exceptionIds")
    validated_at: datetime = Field(alias="validatedAt")
    validator_version: str = Field(alias="validatorVersion", min_length=1)

    @model_validator(mode="after")
    def local_manifest_invariants_hold(self) -> "PackageManifest":
        _require_unique(self.sources, "source_id", "source IDs")
        _require_unique(self.artifacts, "artifact_id", "artifact IDs")
        _require_unique(self.decisions, "decision_id", "decision IDs")
        if len(self.exception_ids) != len(set(self.exception_ids)):
            raise ValueError("exception IDs must be unique")
        if self.status == "prepared":
            coverage = [source.coverage_state for source in self.sources]
            coverage.extend(page.coverage_state for page in self.pdf_pages)
            if "unresolved" in coverage:
                raise ValueError("prepared packages cannot contain unresolved coverage")
        return self


class CanonicalRosterValues(_ContractModel):
    name: str = Field(min_length=1)
    identity: str = Field(min_length=1)
    fa_code: str | None = Field(default=None, alias="faCode", min_length=1)
    tax_id: str | None = Field(default=None, alias="taxId", min_length=1)
    birth_date: str | None = Field(default=None, alias="birthDate", min_length=1)
    bank_account: str | None = Field(default=None, alias="bankAccount", min_length=1)
    service_fee: str | None = Field(default=None, alias="serviceFee", min_length=1)
    product: str | None = Field(default=None, min_length=1)


class CanonicalRosterRow(_ContractModel):
    row_id: str = Field(alias="rowId", min_length=1)
    values: CanonicalRosterValues


def _require_unique(items: list[object], field_name: str, label: str) -> None:
    values = [getattr(item, field_name) for item in items]
    if len(values) != len(set(values)):
        raise ValueError(f"{label} must be unique")
