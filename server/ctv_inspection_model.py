"""Private-safe immutable values for read-only CTV document inspection."""

import copy
import re
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal

from ctv_inventory_model import ISSUE_ORDER


UnitKind = Literal["pdf-page", "worksheet", "image"]
SuggestedRole = Literal[
    "payment-roster",
    "service-contract",
    "acceptance-record",
    "payment-tax-form",
    "identity-front",
    "identity-back",
    "shared-supporting-evidence",
    "other-supporting-evidence",
    "unknown",
]
ConfidenceBand = Literal["high", "medium", "low", "none"]
InspectionMethod = Literal[
    "embedded-text", "local-ocr", "worksheet-structure", "image-structure", "none"
]
SourceInspectionStatus = Literal[
    "inspected", "opaque", "unsupported", "unreadable", "encrypted", "over-limit",
    "not-applicable",
]
InspectionStatus = Literal["complete", "complete-with-issues"]


SIGNAL_ORDER: tuple[str, ...] = (
    "service-contract-heading",
    "party-section-present",
    "service-scope-section-present",
    "signature-section-present",
    "acceptance-heading",
    "acceptance-period-present",
    "payment-request-heading",
    "tax-form-heading",
    "roster-column-pattern",
    "roster-row-pattern",
    "identity-front-heading",
    "identity-front-layout",
    "identity-back-layout",
    "identity-number-pattern-present",
    "identity-issue-section-present",
    "case-level-heading",
    "multi-party-reference-present",
    "supporting-document-heading",
    "embedded-media-present",
    "worksheet-hidden",
    "mostly-image-page",
    "mostly-text-page",
    "multiple-role-signals",
)
INSPECTION_ISSUE_ORDER: tuple[str, ...] = ISSUE_ORDER + (
    "opaque-archive",
    "unsupported-document-type",
    "document-unreadable",
    "document-encrypted",
    "document-over-limit",
    "unit-over-limit",
    "embedded-media-present",
    "worksheet-hidden",
    "multi-frame-image",
    "ocr-unavailable",
    "ocr-timeout",
    "ocr-failed",
    "ocr-low-confidence",
    "classification-ambiguous",
    "classification-conflict",
)

_EVIDENCE_ID = re.compile(r"^evidence-[0-9]{4,}$")
_UNIT_ID = re.compile(r"^unit-[0-9]{4,}$")
_OBSERVATION_ID = re.compile(r"^observation-[a-f0-9]{64}$")
_DETECTED_TYPES = frozenset({"pdf", "xlsx", "zip", "rar", "image", "unknown"})
_UNIT_KINDS = frozenset({"pdf-page", "worksheet", "image"})
_SUGGESTED_ROLES = frozenset({
    "payment-roster", "service-contract", "acceptance-record", "payment-tax-form",
    "identity-front", "identity-back", "shared-supporting-evidence",
    "other-supporting-evidence", "unknown",
})
_CONFIDENCE_BANDS = frozenset({"high", "medium", "low", "none"})
_INSPECTION_METHODS = frozenset({
    "embedded-text", "local-ocr", "worksheet-structure", "image-structure", "none",
})
_SOURCE_STATUSES = frozenset({
    "inspected", "opaque", "unsupported", "unreadable", "encrypted", "over-limit",
    "not-applicable",
})
_INSPECTION_STATUSES = frozenset({"complete", "complete-with-issues"})
_SIGNAL_POSITIONS = {code: index for index, code in enumerate(SIGNAL_ORDER)}
_ISSUE_POSITIONS = {code: index for index, code in enumerate(INSPECTION_ISSUE_ORDER)}
_ALLOWED_ROLES = {
    "pdf-page": _SUGGESTED_ROLES,
    "worksheet": frozenset({"payment-roster", "other-supporting-evidence", "unknown"}),
    "image": frozenset({
        "identity-front", "identity-back", "shared-supporting-evidence",
        "other-supporting-evidence", "unknown",
    }),
}
_ALLOWED_METHODS = {
    "pdf-page": frozenset({"embedded-text", "local-ocr", "none"}),
    "worksheet": frozenset({"worksheet-structure", "none"}),
    "image": frozenset({"local-ocr", "image-structure", "none"}),
}
_SOURCE_COUNT_RULES = {
    "inspected": "count",
    "opaque": "zero",
    "unsupported": "zero",
    "unreadable": "none",
    "encrypted": "none",
    "over-limit": "none",
    "not-applicable": "zero",
}
_SOURCE_REQUIRED_ISSUES = {
    "opaque": "opaque-archive",
    "unsupported": "unsupported-document-type",
    "unreadable": "document-unreadable",
    "encrypted": "document-encrypted",
    "over-limit": "document-over-limit",
}


@dataclass(frozen=True)
class InspectionLimits:
    max_pdf_source_bytes: int = 256 * 1024 * 1024
    max_pdf_pages: int = 10_000
    max_embedded_text_bytes_per_page: int = 64 * 1024
    max_workbook_source_bytes: int = 25 * 1024 * 1024
    max_worksheets_per_workbook: int = 100
    max_cells_per_workbook: int = 100_000
    max_cell_text_characters: int = 256
    max_image_source_bytes: int = 25 * 1024 * 1024
    max_decoded_image_pixels: int = 50_000_000
    max_ocr_units: int = 500
    max_ocr_seconds_per_unit: int = 30
    max_ocr_total_seconds: int = 30 * 60
    max_units: int = 10_000
    max_json_bytes: int = 16 * 1024 * 1024

    def __post_init__(self) -> None:
        for field_name, field in self.__dataclass_fields__.items():
            value = getattr(self, field_name)
            ceiling = field.default
            if (
                not isinstance(value, int)
                or isinstance(value, bool)
                or value <= 0
                or value > ceiling
            ):
                raise ValueError(f"{field_name} must be a positive hard-bounded integer")


DEFAULT_INSPECTION_LIMITS = InspectionLimits()


def _immutable_codes(
    values: Sequence[str], *, positions: dict[str, int], field_name: str
) -> tuple[str, ...]:
    if isinstance(values, (str, bytes)):
        raise ValueError(f"{field_name} must be a sequence")
    try:
        copied = tuple(copy.deepcopy(tuple(values)))
    except TypeError as error:
        raise ValueError(f"{field_name} must be a sequence") from None
    if any(not isinstance(value, str) or value not in positions for value in copied):
        raise ValueError(f"{field_name} must use approved codes")
    if len(set(copied)) != len(copied):
        raise ValueError(f"{field_name} must not contain duplicates")
    if tuple(sorted(copied, key=positions.__getitem__)) != copied:
        raise ValueError(f"{field_name} must follow its approved order")
    return copied


def _validate_evidence_id(evidence_id: str) -> None:
    if not isinstance(evidence_id, str) or not _EVIDENCE_ID.fullmatch(evidence_id):
        raise ValueError("evidence_id must be an opaque evidence ID")


def _validate_unit_kind_and_index(unit_kind: str, unit_index: int) -> None:
    if unit_kind not in _UNIT_KINDS:
        raise ValueError("unit_kind must be supported")
    maximum = {"pdf-page": 10_000, "worksheet": 100, "image": 1}[unit_kind]
    if (
        not isinstance(unit_index, int)
        or isinstance(unit_index, bool)
        or not 1 <= unit_index <= maximum
    ):
        raise ValueError("unit_index must be within the unit kind hard limit")


def _validate_method(unit_kind: str, inspection_method: str) -> None:
    if inspection_method not in _INSPECTION_METHODS:
        raise ValueError("inspection_method must be supported")
    if inspection_method not in _ALLOWED_METHODS[unit_kind]:
        raise ValueError("inspection_method is not allowed for unit_kind")


@dataclass(frozen=True)
class InspectionSource:
    evidence_id: str
    detected_type: str
    inspection_status: SourceInspectionStatus
    unit_count: int | None
    issue_codes: Sequence[str]

    def __post_init__(self) -> None:
        _validate_evidence_id(self.evidence_id)
        if self.detected_type not in _DETECTED_TYPES:
            raise ValueError("detected_type must be supported")
        if self.inspection_status not in _SOURCE_STATUSES:
            raise ValueError("inspection_status must be supported")
        count_rule = _SOURCE_COUNT_RULES[self.inspection_status]
        if count_rule == "none":
            if self.unit_count is not None:
                raise ValueError("unit_count must be null when it cannot be established")
        elif (
            not isinstance(self.unit_count, int)
            or isinstance(self.unit_count, bool)
            or self.unit_count < 0
            or (count_rule == "zero" and self.unit_count != 0)
        ):
            raise ValueError("unit_count must agree with inspection_status")
        if self.inspection_status == "opaque" and self.detected_type not in {"zip", "rar"}:
            raise ValueError("inspection_status opaque requires an archive detected_type")
        issue_codes = _immutable_codes(
            self.issue_codes, positions=_ISSUE_POSITIONS, field_name="issue_codes"
        )
        required_issue = _SOURCE_REQUIRED_ISSUES.get(self.inspection_status)
        if required_issue is not None and required_issue not in issue_codes:
            raise ValueError("issue_codes must account for inspection_status")
        object.__setattr__(self, "issue_codes", issue_codes)

    def to_dict(self) -> dict[str, object]:
        return {
            "evidenceId": self.evidence_id,
            "detectedType": self.detected_type,
            "inspectionStatus": self.inspection_status,
            "unitCount": self.unit_count,
            "issueCodes": list(self.issue_codes),
        }


@dataclass(frozen=True)
class InspectionUnitEvidence:
    """Acquisition-only structural evidence with no raw source content."""

    unit_kind: UnitKind
    unit_index: int
    inspection_method: InspectionMethod
    signal_codes: Sequence[str]
    issue_codes: Sequence[str]

    def __post_init__(self) -> None:
        _validate_unit_kind_and_index(self.unit_kind, self.unit_index)
        _validate_method(self.unit_kind, self.inspection_method)
        object.__setattr__(
            self,
            "signal_codes",
            _immutable_codes(self.signal_codes, positions=_SIGNAL_POSITIONS, field_name="signal_codes"),
        )
        object.__setattr__(
            self,
            "issue_codes",
            _immutable_codes(self.issue_codes, positions=_ISSUE_POSITIONS, field_name="issue_codes"),
        )


@dataclass(frozen=True)
class InspectionAdapterResult:
    """Private adapter output before public IDs, roles, and totals are assigned."""

    inspection_status: SourceInspectionStatus
    unit_count: int | None
    source_issue_codes: Sequence[str]
    units: Sequence[InspectionUnitEvidence]

    def __post_init__(self) -> None:
        if self.inspection_status not in _SOURCE_STATUSES:
            raise ValueError("inspection_status must be supported")
        if isinstance(self.units, (str, bytes)):
            raise ValueError("units must be a sequence")
        try:
            units = tuple(copy.deepcopy(tuple(self.units)))
        except TypeError:
            raise ValueError("units must be a sequence") from None
        if not all(isinstance(unit, InspectionUnitEvidence) for unit in units):
            raise ValueError("units must contain InspectionUnitEvidence values")
        count_rule = _SOURCE_COUNT_RULES[self.inspection_status]
        if self.inspection_status == "inspected":
            if (
                not isinstance(self.unit_count, int)
                or isinstance(self.unit_count, bool)
                or self.unit_count < 0
                or self.unit_count != len(units)
            ):
                raise ValueError("unit_count must match inspected units")
        elif count_rule == "none":
            if self.unit_count is not None or units:
                raise ValueError("unit_count and units must be absent when not established")
        elif self.unit_count != 0 or units:
            raise ValueError("unit_count and units must be zero for source-only statuses")
        object.__setattr__(
            self,
            "source_issue_codes",
            _immutable_codes(
                self.source_issue_codes,
                positions=_ISSUE_POSITIONS,
                field_name="source_issue_codes",
            ),
        )
        object.__setattr__(self, "units", units)


@dataclass(frozen=True)
class InspectionUnit:
    unit_id: str
    evidence_id: str
    unit_kind: UnitKind
    unit_index: int
    suggested_role: SuggestedRole
    confidence_band: ConfidenceBand
    needs_user_review: bool
    inspection_method: InspectionMethod
    signal_codes: Sequence[str]
    issue_codes: Sequence[str]

    def __post_init__(self) -> None:
        if not isinstance(self.unit_id, str) or not _UNIT_ID.fullmatch(self.unit_id):
            raise ValueError("unit_id must be an opaque unit ID")
        _validate_evidence_id(self.evidence_id)
        _validate_unit_kind_and_index(self.unit_kind, self.unit_index)
        if self.suggested_role not in _SUGGESTED_ROLES:
            raise ValueError("suggested_role must be supported")
        if self.suggested_role not in _ALLOWED_ROLES[self.unit_kind]:
            raise ValueError("suggested_role is not allowed for unit_kind")
        if self.confidence_band not in _CONFIDENCE_BANDS:
            raise ValueError("confidence_band must be supported")
        if self.suggested_role == "unknown" and self.confidence_band != "none":
            raise ValueError("unknown suggested_role requires confidence_band none")
        if self.suggested_role != "unknown" and self.confidence_band == "none":
            raise ValueError("confidence_band none requires suggested_role unknown")
        if not isinstance(self.needs_user_review, bool):
            raise ValueError("needs_user_review must be a Boolean")
        _validate_method(self.unit_kind, self.inspection_method)
        signal_codes = _immutable_codes(
            self.signal_codes, positions=_SIGNAL_POSITIONS, field_name="signal_codes"
        )
        issue_codes = _immutable_codes(
            self.issue_codes, positions=_ISSUE_POSITIONS, field_name="issue_codes"
        )
        expected_review = (
            self.confidence_band != "high"
            or self.suggested_role == "unknown"
            or bool(issue_codes)
            or "multiple-role-signals" in signal_codes
        )
        if self.needs_user_review != expected_review:
            raise ValueError("needs_user_review must agree with the review contract")
        object.__setattr__(self, "signal_codes", signal_codes)
        object.__setattr__(self, "issue_codes", issue_codes)

    def to_dict(self) -> dict[str, object]:
        return {
            "unitId": self.unit_id,
            "evidenceId": self.evidence_id,
            "unitKind": self.unit_kind,
            "unitIndex": self.unit_index,
            "suggestedRole": self.suggested_role,
            "confidenceBand": self.confidence_band,
            "needsUserReview": self.needs_user_review,
            "inspectionMethod": self.inspection_method,
            "signalCodes": list(self.signal_codes),
            "issueCodes": list(self.issue_codes),
        }


@dataclass(frozen=True)
class InspectionTotals:
    sources: int
    units: int
    classified: int
    unknown: int
    needs_user_review: int
    issues: int

    def __post_init__(self) -> None:
        for value in (
            self.sources,
            self.units,
            self.classified,
            self.unknown,
            self.needs_user_review,
            self.issues,
        ):
            if not isinstance(value, int) or isinstance(value, bool) or value < 0:
                raise ValueError("inspection totals must be non-negative integers")

    def to_dict(self) -> dict[str, int]:
        return {
            "sources": self.sources,
            "units": self.units,
            "classified": self.classified,
            "unknown": self.unknown,
            "needsUserReview": self.needs_user_review,
            "issues": self.issues,
        }


@dataclass(frozen=True)
class InspectionResult:
    inspection_version: str
    inspection_status: InspectionStatus
    observation_id: str
    totals: InspectionTotals
    sources: Sequence[InspectionSource]
    units: Sequence[InspectionUnit]

    def __post_init__(self) -> None:
        if self.inspection_version != "1.0":
            raise ValueError("inspection_version must be 1.0")
        if self.inspection_status not in _INSPECTION_STATUSES:
            raise ValueError("inspection_status must be complete or complete-with-issues")
        if not isinstance(self.observation_id, str) or not _OBSERVATION_ID.fullmatch(
            self.observation_id
        ):
            raise ValueError("observation_id must be an opaque observation ID")
        if not isinstance(self.totals, InspectionTotals):
            raise ValueError("totals must be InspectionTotals")
        sources = self._immutable_records(self.sources, InspectionSource, "sources")
        units = self._immutable_records(self.units, InspectionUnit, "units")
        if len(units) > DEFAULT_INSPECTION_LIMITS.max_units:
            raise ValueError("units must not exceed max_units")
        source_ids = {source.evidence_id for source in sources}
        if len(source_ids) != len(sources):
            raise ValueError("sources must have unique evidence_id values")
        if any(unit.evidence_id not in source_ids for unit in units):
            raise ValueError("units must reference a source evidence_id")
        units_by_source = {
            source.evidence_id: sum(
                unit.evidence_id == source.evidence_id for unit in units
            )
            for source in sources
        }
        for source in sources:
            if source.inspection_status != "inspected" and units_by_source[source.evidence_id]:
                raise ValueError("source-only inspection_status cannot own units")
            if (
                source.inspection_status == "inspected"
                and source.unit_count != units_by_source[source.evidence_id]
            ):
                raise ValueError("source unit_count must match bound units")
        expected_totals = InspectionTotals(
            sources=len(sources),
            units=len(units),
            classified=sum(unit.suggested_role != "unknown" for unit in units),
            unknown=sum(unit.suggested_role == "unknown" for unit in units),
            needs_user_review=sum(unit.needs_user_review for unit in units),
            issues=sum(len(source.issue_codes) for source in sources)
            + sum(len(unit.issue_codes) for unit in units),
        )
        if self.totals != expected_totals:
            raise ValueError("totals must agree with sources and units")
        if self.inspection_status == "complete" and expected_totals.issues:
            raise ValueError("inspection_status complete requires zero issues")
        if self.inspection_status == "complete-with-issues" and not expected_totals.issues:
            raise ValueError("inspection_status complete-with-issues requires issues")
        object.__setattr__(self, "sources", sources)
        object.__setattr__(self, "units", units)

    @staticmethod
    def _immutable_records(values: Sequence[object], expected_type: type, field_name: str) -> tuple:
        if isinstance(values, (str, bytes)):
            raise ValueError(f"{field_name} must be a sequence")
        try:
            copied = tuple(copy.deepcopy(tuple(values)))
        except TypeError:
            raise ValueError(f"{field_name} must be a sequence") from None
        if not all(isinstance(value, expected_type) for value in copied):
            raise ValueError(f"{field_name} must contain {expected_type.__name__} values")
        return copied

    def to_dict(self) -> dict[str, object]:
        return copy.deepcopy(
            {
                "inspectionVersion": self.inspection_version,
                "inspectionStatus": self.inspection_status,
                "observationId": self.observation_id,
                "totals": self.totals.to_dict(),
                "sources": [source.to_dict() for source in self.sources],
                "units": [unit.to_dict() for unit in self.units],
            }
        )
