"""Closed, filesystem-independent CTV intake v2 contract models.

The models deliberately validate document shapes and local/cross-document
references only. Reading package files and proving generated content belongs to
the later package-validator boundary.
"""
from __future__ import annotations

import re
from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from ctv_inspection_model import INSPECTION_ISSUE_ORDER


MAX_EVIDENCE_ARTIFACTS = 1_000
MAX_INSPECTED_UNITS = 10_000
MAX_PACKAGE_PDF_PAGES = 25_000
MAX_INPUT_PDF_BYTES = 256 * 1024 * 1024
MAX_ROSTER_OR_EVIDENCE_BYTES = 25 * 1024 * 1024
MAX_JSON_BYTES = 16 * 1024 * 1024
MAX_PACKAGE_BYTES = 1024 * 1024 * 1024

Sha256 = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
OpaqueId = Annotated[str, Field(pattern=r"^[a-z][a-z0-9]*(?:-[a-z0-9]+)*$", min_length=3, max_length=128)]
OpaqueSourceId = Annotated[str, Field(pattern=r"^source-[0-9a-z]+(?:-[0-9a-z]+)*$", min_length=8, max_length=128)]
OpaqueArtifactId = Annotated[str, Field(pattern=r"^artifact-[0-9a-z]+(?:-[0-9a-z]+)*$", min_length=10, max_length=128)]
OpaqueDecisionId = Annotated[str, Field(pattern=r"^decision-[0-9a-z]+(?:-[0-9a-z]+)*$", min_length=10, max_length=128)]
OpaqueUnitId = Annotated[str, Field(pattern=r"^unit-[0-9a-z]+(?:-[0-9a-z]+)*$", min_length=7, max_length=128)]
OpaqueParticipantHandle = Annotated[str, Field(pattern=r"^participant-[0-9a-z]+(?:-[0-9a-z]+)*$", min_length=14, max_length=128)]
OpaqueRosterRowId = Annotated[str, Field(pattern=r"^roster-row-[0-9a-z]+(?:-[0-9a-z]+)*$", min_length=12, max_length=128)]
OpaquePackageId = Annotated[str, Field(pattern=r"^package-[0-9a-f]{64}$")]
OpaqueObservationId = Annotated[str, Field(pattern=r"^observation-[0-9a-f]{64}$")]

CoverageStateV2 = Literal["assigned", "shared", "duplicate", "excluded-by-user"]
ArtifactKindV2 = Literal["input-pdf", "roster", "assignments", "exceptions", "cccd", "evidence"]
DecisionTypeV2 = Literal["accept-unit", "reassign-unit", "exclude-unit", "exclude-source", "select-roster", "approve-proposal"]
UnitKindV2 = Literal["pdf-page", "worksheet", "image"]
AssignmentDecisionV2 = Literal["accepted", "reassigned"]
AssignmentRoleV2 = Literal[
    "payment-roster", "service-contract", "acceptance-record", "payment-tax-form",
    "identity-front", "identity-back", "shared-supporting-evidence",
    "other-supporting-evidence",
]
ExclusionReasonV2 = Literal[
    "duplicate", "unsupported", "unreadable", "encrypted", "over-limit",
    "excluded-by-user", "unresolved",
]
AcquisitionStatus = Literal["opaque", "unsupported", "unreadable", "encrypted", "over-limit"]
FixedInspectionIssue = Literal[tuple(INSPECTION_ISSUE_ORDER)]

_WINDOWS_ABSOLUTE_PATH_RE = re.compile(r"^[A-Za-z]:[\\/]")


class _ContractModel(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)


def _safe_relative_path(value: str) -> str:
    if not value or value.startswith("/") or _WINDOWS_ABSOLUTE_PATH_RE.match(value):
        raise ValueError("path must be safely relative")
    if "\\" in value or any(part in {"", ".", ".."} for part in value.split("/")):
        raise ValueError("path must not contain traversal or empty segments")
    return value


def _unique(values: list[object], label: str) -> None:
    if len(values) != len(set(values)):
        raise ValueError(f"{label} must be unique")


class VerifiedSourceV2(_ContractModel):
    binding_status: Literal["verified-content"] = Field(alias="bindingStatus")
    source_id: OpaqueSourceId = Field(alias="sourceId")
    path: str = Field(min_length=1, max_length=1024)
    media_type: str = Field(alias="mediaType", min_length=1, max_length=128)
    size: int = Field(ge=0, le=MAX_INPUT_PDF_BYTES, strict=True)
    sha256: Sha256
    page_count: int | None = Field(alias="pageCount", default=None, ge=1, le=MAX_PACKAGE_PDF_PAGES, strict=True)
    coverage_state: CoverageStateV2 = Field(alias="coverageState")
    decision_id: OpaqueDecisionId | None = Field(alias="decisionId", default=None)

    @field_validator("path")
    @classmethod
    def path_is_safe(cls, value: str) -> str:
        return _safe_relative_path(value)


class UnacquiredSourceV2(_ContractModel):
    binding_status: Literal["unacquired-exclusion"] = Field(alias="bindingStatus")
    source_id: OpaqueSourceId = Field(alias="sourceId")
    path: str | None = Field(default=None, max_length=1024)
    acquisition_status: AcquisitionStatus = Field(alias="acquisitionStatus")
    issue_codes: list[FixedInspectionIssue] = Field(alias="issueCodes", min_length=1, max_length=32)
    coverage_state: Literal["duplicate", "excluded-by-user"] = Field(alias="coverageState")
    decision_id: OpaqueDecisionId = Field(alias="decisionId")

    @field_validator("path")
    @classmethod
    def path_is_safe(cls, value: str | None) -> str | None:
        return None if value is None else _safe_relative_path(value)

    @model_validator(mode="after")
    def issue_codes_are_unique(self) -> "UnacquiredSourceV2":
        _unique(self.issue_codes, "issue codes")
        return self


SourceV2 = Annotated[VerifiedSourceV2 | UnacquiredSourceV2, Field(discriminator="binding_status")]


class PdfPageV2(_ContractModel):
    source_id: OpaqueSourceId = Field(alias="sourceId")
    source_page: int = Field(alias="sourcePage", ge=1, le=MAX_PACKAGE_PDF_PAGES, strict=True)
    target_page: int | None = Field(alias="targetPage", default=None, ge=1, le=MAX_PACKAGE_PDF_PAGES, strict=True)
    coverage_state: CoverageStateV2 = Field(alias="coverageState")
    decision_id: OpaqueDecisionId | None = Field(alias="decisionId", default=None)


class ArtifactV2(_ContractModel):
    artifact_id: OpaqueArtifactId = Field(alias="artifactId")
    kind: ArtifactKindV2
    format_version: Literal["2.0"] = Field(alias="formatVersion")
    path: str = Field(min_length=1, max_length=1024)
    size: int = Field(ge=0, le=MAX_INPUT_PDF_BYTES, strict=True)
    sha256: Sha256
    source_ids: list[OpaqueSourceId] = Field(alias="sourceIds", max_length=MAX_INSPECTED_UNITS)

    @field_validator("path")
    @classmethod
    def path_is_safe(cls, value: str) -> str:
        return _safe_relative_path(value)

    @model_validator(mode="after")
    def artifact_limits_hold(self) -> "ArtifactV2":
        _unique(self.source_ids, "artifact source IDs")
        if self.kind in {"roster", "evidence"} and self.size > MAX_ROSTER_OR_EVIDENCE_BYTES:
            raise ValueError("roster and evidence artifacts are limited to 25 MiB")
        if self.kind in {"assignments", "exceptions"} and self.size > MAX_JSON_BYTES:
            raise ValueError("JSON artifacts are limited to 16 MiB")
        return self


class RosterMappingV2(_ContractModel):
    source_id: OpaqueSourceId = Field(alias="sourceId")
    sheet_name: str = Field(alias="sheetName", min_length=1, max_length=128)
    canonical_to_source_columns: dict[str, str] = Field(alias="canonicalToSourceColumns", min_length=1, max_length=32)


class DecisionV2(_ContractModel):
    decision_id: OpaqueDecisionId = Field(alias="decisionId")
    proposal_version: str = Field(alias="proposalVersion", min_length=1, max_length=128)
    proposal_digest: Sha256 = Field(alias="proposalDigest")
    type: DecisionTypeV2
    actor: Literal["user"]
    subject_refs: list[OpaqueId] = Field(alias="subjectRefs", max_length=MAX_INSPECTED_UNITS)
    evidence_refs: list[OpaqueId] = Field(alias="evidenceRefs", max_length=MAX_INSPECTED_UNITS)

    @model_validator(mode="after")
    def references_are_unique(self) -> "DecisionV2":
        _unique(self.subject_refs, "decision subject references")
        _unique(self.evidence_refs, "decision evidence references")
        return self


class PackageManifestV2(_ContractModel):
    schema_version: Literal["2.0"] = Field(alias="schemaVersion")
    compatibility_target: Literal["ctv-intake-v2"] = Field(alias="compatibilityTarget")
    package_id: OpaquePackageId = Field(alias="packageId")
    source_observation_id: OpaqueObservationId = Field(alias="sourceObservationId")
    proposal_digest: Sha256 = Field(alias="proposalDigest")
    batch_id: OpaqueId = Field(alias="batchId")
    case_id: OpaqueId = Field(alias="caseId")
    fa_code: str | None = Field(alias="faCode", default=None, min_length=1, max_length=128)
    package_version: str = Field(alias="packageVersion", min_length=1, max_length=128)
    status: Literal["prepared"]
    validator_version: str = Field(alias="validatorVersion", min_length=1, max_length=128)
    sources: list[SourceV2] = Field(min_length=1, max_length=MAX_INSPECTED_UNITS)
    pdf_pages: list[PdfPageV2] = Field(alias="pdfPages", max_length=MAX_PACKAGE_PDF_PAGES)
    artifacts: list[ArtifactV2] = Field(min_length=4)
    roster_mapping: RosterMappingV2 | None = Field(alias="rosterMapping", default=None)
    decisions: list[DecisionV2] = Field(min_length=1, max_length=MAX_INSPECTED_UNITS + 2)
    exception_ids: list[OpaqueId] = Field(alias="exceptionIds", max_length=MAX_INSPECTED_UNITS)

    @model_validator(mode="after")
    def local_invariants_hold(self) -> "PackageManifestV2":
        _unique([source.source_id for source in self.sources], "source IDs")
        _unique([decision.decision_id for decision in self.decisions], "decision IDs")
        _unique(self.exception_ids, "exception IDs")
        evidence = [artifact for artifact in self.artifacts if artifact.kind == "evidence"]
        if len(evidence) > MAX_EVIDENCE_ARTIFACTS:
            raise ValueError("at most 1,000 evidence artifacts are allowed")
        for kind in ("input-pdf", "roster", "assignments", "exceptions"):
            if sum(artifact.kind == kind for artifact in self.artifacts) != 1:
                raise ValueError(f"single-instance artifact {kind} must appear exactly once")
        singles = [artifact.kind for artifact in self.artifacts if artifact.kind != "evidence"]
        if len(singles) != len(set(singles)):
            raise ValueError("single-instance artifact kinds must be unique")
        _unique([artifact.artifact_id for artifact in self.artifacts], "artifact IDs")
        if sum(artifact.size for artifact in self.artifacts) > MAX_PACKAGE_BYTES:
            raise ValueError("package artifacts exceed 1 GiB")
        unacquired_ids = {source.source_id for source in self.sources if isinstance(source, UnacquiredSourceV2)}
        if any(unacquired_ids & set(artifact.source_ids) for artifact in self.artifacts):
            raise ValueError("unacquired sources cannot have artifact provenance")
        if any(decision.proposal_digest != self.proposal_digest for decision in self.decisions):
            raise ValueError("decision proposal digests must match the manifest")
        return self


class IndividualTargetV2(_ContractModel):
    scope: Literal["individual"]
    participant_handles: list[OpaqueParticipantHandle] = Field(alias="participantHandles", min_length=1, max_length=1)


class SharedTargetV2(_ContractModel):
    scope: Literal["shared"]
    participant_handles: list[OpaqueParticipantHandle] = Field(alias="participantHandles", min_length=2, max_length=MAX_INSPECTED_UNITS)

    @model_validator(mode="after")
    def handles_are_unique(self) -> "SharedTargetV2":
        _unique(self.participant_handles, "shared participant handles")
        return self


class CaseTargetV2(_ContractModel):
    scope: Literal["case"]
    participant_handles: list[OpaqueParticipantHandle] = Field(alias="participantHandles", max_length=0)


AssignmentTargetV2 = Annotated[IndividualTargetV2 | SharedTargetV2 | CaseTargetV2, Field(discriminator="scope")]


class PdfPageLocatorV2(_ContractModel):
    kind: Literal["pdf-page"]
    artifact_id: OpaqueArtifactId = Field(alias="artifactId")
    target_page: int = Field(alias="targetPage", ge=1, le=MAX_PACKAGE_PDF_PAGES, strict=True)


class RosterLocatorV2(_ContractModel):
    kind: Literal["roster"]
    artifact_id: OpaqueArtifactId = Field(alias="artifactId")
    worksheet_index: Literal[1] = Field(alias="worksheetIndex")


class ImageLocatorV2(_ContractModel):
    kind: Literal["image"]
    artifact_id: OpaqueArtifactId = Field(alias="artifactId")


class WorksheetLocatorV2(_ContractModel):
    kind: Literal["worksheet"]
    artifact_id: OpaqueArtifactId = Field(alias="artifactId")
    worksheet_index: int = Field(alias="worksheetIndex", ge=1, le=100, strict=True)


OutputLocatorV2 = Annotated[PdfPageLocatorV2 | RosterLocatorV2 | ImageLocatorV2 | WorksheetLocatorV2, Field(discriminator="kind")]


class AssignmentParticipantV2(_ContractModel):
    participant_handle: OpaqueParticipantHandle = Field(alias="participantHandle")
    roster_row_id: OpaqueRosterRowId = Field(alias="rosterRowId")


class AssignmentUnitV2(_ContractModel):
    unit_id: OpaqueUnitId = Field(alias="unitId")
    source_id: OpaqueSourceId = Field(alias="sourceId")
    source_unit_index: int = Field(alias="sourceUnitIndex", ge=1, le=MAX_INSPECTED_UNITS, strict=True)
    unit_kind: UnitKindV2 = Field(alias="unitKind")
    decision_id: OpaqueDecisionId = Field(alias="decisionId")
    decision: AssignmentDecisionV2
    role: AssignmentRoleV2
    target: AssignmentTargetV2
    output_locator: OutputLocatorV2 = Field(alias="outputLocator")


class ExclusionRecordV2(_ContractModel):
    record_type: Literal["unit", "source"] = Field(alias="recordType")
    record_id: OpaqueId = Field(alias="recordId")
    decision_id: OpaqueDecisionId = Field(alias="decisionId")
    reason: ExclusionReasonV2


class AssignmentsDocumentV2(_ContractModel):
    schema_version: Literal["2.0"] = Field(alias="schemaVersion")
    package_id: OpaquePackageId = Field(alias="packageId")
    source_observation_id: OpaqueObservationId = Field(alias="sourceObservationId")
    proposal_digest: Sha256 = Field(alias="proposalDigest")
    roster_artifact_id: OpaqueArtifactId = Field(alias="rosterArtifactId")
    participants: list[AssignmentParticipantV2] = Field(max_length=MAX_INSPECTED_UNITS)
    units: list[AssignmentUnitV2] = Field(max_length=MAX_INSPECTED_UNITS)
    exclusions: list[ExclusionRecordV2] = Field(max_length=MAX_INSPECTED_UNITS)

    @model_validator(mode="after")
    def local_invariants_hold(self) -> "AssignmentsDocumentV2":
        _unique([participant.participant_handle for participant in self.participants], "participant handles")
        _unique([participant.roster_row_id for participant in self.participants], "roster row IDs")
        _unique([unit.unit_id for unit in self.units], "unit IDs")
        _unique([(record.record_type, record.record_id) for record in self.exclusions], "exclusion records")
        return self

    def validate_against_manifest(self, manifest: PackageManifestV2) -> None:
        if (self.package_id, self.source_observation_id, self.proposal_digest) != (manifest.package_id, manifest.source_observation_id, manifest.proposal_digest):
            raise ValueError("assignments identity must match manifest")
        artifacts = {artifact.artifact_id: artifact for artifact in manifest.artifacts}
        if self.roster_artifact_id not in artifacts or artifacts[self.roster_artifact_id].kind != "roster":
            raise ValueError("assignments roster artifact must resolve to the roster")
        sources = {source.source_id for source in manifest.sources}
        decisions = {decision.decision_id: decision for decision in manifest.decisions}
        for unit in self.units:
            decision = decisions.get(unit.decision_id)
            if unit.source_id not in sources:
                raise ValueError("assignment source must resolve")
            expected_types = {"accept-unit"} if unit.decision == "accepted" else {"reassign-unit"}
            if unit.role == "payment-roster" and unit.output_locator.kind == "roster":
                expected_types.add("select-roster")
            if decision is None or decision.type not in expected_types:
                raise ValueError("assignment decision must resolve")
            if unit.output_locator.artifact_id not in artifacts:
                raise ValueError("assignment output locator must resolve")
        for exclusion in self.exclusions:
            decision = decisions.get(exclusion.decision_id)
            expected_type = "exclude-unit" if exclusion.record_type == "unit" else "exclude-source"
            if decision is None or decision.type != expected_type:
                raise ValueError("exclusion decision must resolve")

    def validate_against_roster(self, roster: "CanonicalRosterDocumentV2") -> None:
        if self.roster_artifact_id != roster.artifact_id:
            raise ValueError("assignments roster artifact must match roster document")
        participant_rows = [participant.roster_row_id for participant in self.participants]
        roster_rows = [row.roster_row_id for row in roster.rows]
        if participant_rows != roster_rows:
            raise ValueError("participant/roster mismatch")


class CanonicalRosterValuesV2(_ContractModel):
    name: str = Field(min_length=1, max_length=256)
    identity: str = Field(min_length=1, max_length=256)
    fa_code: str | None = Field(alias="faCode", default=None, min_length=1, max_length=128)
    tax_id: str | None = Field(alias="taxId", default=None, min_length=1, max_length=128)
    birth_date: str | None = Field(alias="birthDate", default=None, min_length=1, max_length=128)
    bank_account: str | None = Field(alias="bankAccount", default=None, min_length=1, max_length=128)
    service_fee: str | None = Field(alias="serviceFee", default=None, min_length=1, max_length=128)
    product: str | None = Field(default=None, min_length=1, max_length=256)


class CanonicalRosterRowV2(_ContractModel):
    roster_row_id: OpaqueRosterRowId = Field(alias="rosterRowId")
    values: CanonicalRosterValuesV2


class CanonicalRosterDocumentV2(_ContractModel):
    schema_version: Literal["2.0"] = Field(alias="schemaVersion")
    artifact_id: OpaqueArtifactId = Field(alias="artifactId")
    rows: list[CanonicalRosterRowV2] = Field(max_length=MAX_INSPECTED_UNITS)

    @model_validator(mode="after")
    def row_ids_are_unique(self) -> "CanonicalRosterDocumentV2":
        _unique([row.roster_row_id for row in self.rows], "roster row IDs")
        return self


class ExceptionItemV2(_ContractModel):
    exception_id: OpaqueId = Field(alias="exceptionId")
    code: str = Field(pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$", min_length=1, max_length=128)
    severity: Literal["warning", "blocking"]
    evidence_refs: list[OpaqueId] = Field(alias="evidenceRefs", max_length=MAX_INSPECTED_UNITS)
    explanation: str = Field(min_length=1, max_length=1024)
    required_action: str = Field(alias="requiredAction", min_length=1, max_length=1024)
    resolution: Literal["open", "accepted-partial", "resolved"]


class ExceptionsDocumentV2(_ContractModel):
    schema_version: Literal["2.0"] = Field(alias="schemaVersion")
    items: list[ExceptionItemV2] = Field(max_length=MAX_INSPECTED_UNITS)

    @model_validator(mode="after")
    def item_ids_are_unique(self) -> "ExceptionsDocumentV2":
        _unique([item.exception_id for item in self.items], "exception IDs")
        return self


class ValidationCheckV2(_ContractModel):
    code: str = Field(pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$", min_length=1, max_length=128)
    passed: bool
    evidence_refs: list[OpaqueId] = Field(alias="evidenceRefs", max_length=MAX_INSPECTED_UNITS)


class ValidationReportV2(_ContractModel):
    schema_version: Literal["2.0"] = Field(alias="schemaVersion")
    outcome: Literal["valid", "invalid"]
    package_status: Literal["prepared"] = Field(alias="packageStatus")
    checks: list[ValidationCheckV2] = Field(max_length=MAX_INSPECTED_UNITS)
    errors: list[str] = Field(max_length=MAX_INSPECTED_UNITS)
    warnings: list[str] = Field(max_length=MAX_INSPECTED_UNITS)
    validated_at: datetime = Field(alias="validatedAt")
    validator_version: str = Field(alias="validatorVersion", min_length=1, max_length=128)
    package_id: OpaquePackageId = Field(alias="packageId")
    source_observation_id: OpaqueObservationId = Field(alias="sourceObservationId")
    proposal_digest: Sha256 = Field(alias="proposalDigest")
    manifest_sha256: Sha256 = Field(alias="manifestSha256")
    declared_artifact_set_sha256: Sha256 = Field(alias="declaredArtifactSetSha256")

    @model_validator(mode="after")
    def report_is_consistent(self) -> "ValidationReportV2":
        _unique([check.code for check in self.checks], "validation check codes")
        _unique(self.errors, "validation errors")
        _unique(self.warnings, "validation warnings")
        if set(self.errors) & set(self.warnings):
            raise ValueError("a validation issue cannot be both an error and warning")
        failed = {check.code for check in self.checks if not check.passed}
        if failed != set(self.errors) | set(self.warnings):
            raise ValueError("failed checks must correspond exactly to errors and warnings")
        if (self.outcome == "valid") != (not self.errors):
            raise ValueError("validation outcome must agree with errors")
        if self.outcome == "valid" and not self.checks:
            raise ValueError("valid reports require completed content checks")
        return self
