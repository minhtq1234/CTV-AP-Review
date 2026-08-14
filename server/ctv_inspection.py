"""Secure read-only composition of inventory and bounded document inspection."""

import json
from pathlib import Path

from ctv_inspection_classifier import classify
from ctv_inspection_media import (
    PdfPageCountExceededError,
    PdfParserBoundaryExceededError,
    inspect_image,
    inspect_pdf,
)
from ctv_inspection_model import (
    DEFAULT_INSPECTION_LIMITS,
    INSPECTION_ISSUE_ORDER,
    InspectionAdapterResult,
    InspectionLimits,
    InspectionResult,
    InspectionSource,
    InspectionTotals,
    InspectionUnit,
    InspectionUnitCountExceededError,
    InspectionUnitEvidence,
)
from ctv_inspection_workbook import (
    WorkbookParserBoundaryExceededError,
    WorkbookWorksheetCountExceededError,
    inspect_workbook,
)
from ctv_inventory import (
    InventoryError,
    InventoryObservation,
    ObservedInventorySource,
    open_inventory_observation,
)
from ctv_local_ocr import OcrBudget, open_local_ocr, run_local_ocr


INSPECTION_ERROR_CODES = (
    "inspection-output-too-large",
    "inspection-parser-boundary-exceeded",
    "inspection-pdf-page-count-exceeded",
    "inspection-tree-changed",
    "inspection-unit-count-exceeded",
    "inspection-worksheet-count-exceeded",
    "inventory-depth-exceeded",
    "inventory-directory-count-exceeded",
    "inventory-directory-unreadable",
    "inventory-entry-count-exceeded",
    "inventory-entry-unsafe",
    "inventory-item-count-exceeded",
    "inventory-output-too-large",
    "inventory-regular-file-count-exceeded",
    "secure-open-unavailable",
    "source-root-missing",
    "source-root-unsafe",
)

_INSPECTION_ERROR_CODE_SET = frozenset(INSPECTION_ERROR_CODES)
_RETAINED_INVENTORY_ERROR_CODES = frozenset(
    {
        "inventory-depth-exceeded",
        "inventory-directory-count-exceeded",
        "inventory-directory-unreadable",
        "inventory-entry-count-exceeded",
        "inventory-entry-unsafe",
        "inventory-item-count-exceeded",
        "inventory-output-too-large",
        "inventory-regular-file-count-exceeded",
        "secure-open-unavailable",
        "source-root-missing",
        "source-root-unsafe",
    }
)
_ZIP_SIGNATURES = (b"PK\x03\x04", b"PK\x05\x06", b"PK\x07\x08")
_RAR_SIGNATURES = (b"Rar!\x1a\x07\x00", b"Rar!\x1a\x07\x01\x00")
_UNSAFE_SOURCE_ISSUES = frozenset({"type-detection-failed"})
_WORKBOOK_EXTENSIONS = frozenset({".xlsx", ".xlsm", ".xltx", ".xltm"})
_UNKNOWN_INVENTORY_FAILURE = object()


class InspectionError(RuntimeError):
    """A controlled operation failure containing only one allowlisted code."""

    def __init__(self, code: str) -> None:
        if type(code) is not str or code not in _INSPECTION_ERROR_CODE_SET:
            raise ValueError("inspection error code must be allowlisted")
        self.code = code
        super().__init__(code)


def _bounded_limits(limits: InspectionLimits) -> InspectionLimits:
    if type(limits) is not InspectionLimits:
        raise TypeError("inspection limits must be valid")
    values = {}
    for field_name, field in InspectionLimits.__dataclass_fields__.items():
        value = getattr(limits, field_name, None)
        if type(value) is not int or value <= 0:
            raise ValueError("inspection limits must be positive hard-bounded integers")
        values[field_name] = min(value, field.default)
    return InspectionLimits(**values)


def _ordered_issues(*groups) -> tuple[str, ...]:
    retained = {code for group in groups for code in group}
    return tuple(code for code in INSPECTION_ISSUE_ORDER if code in retained)


def _source_only(
    source: ObservedInventorySource,
    status: str,
    unit_count: int | None,
    *added_issues: str,
    detected_type: str | None = None,
) -> tuple[InspectionSource, tuple[InspectionUnitEvidence, ...]]:
    return (
        InspectionSource(
            source.evidence_id,
            source.detected_type if detected_type is None else detected_type,
            status,
            unit_count,
            _ordered_issues(source.issue_codes, added_issues),
        ),
        (),
    )


def _leading_archive_type(snapshot: bytes) -> str | None:
    if snapshot.startswith(_ZIP_SIGNATURES):
        return "zip"
    if snapshot.startswith(_RAR_SIGNATURES):
        return "rar"
    return None


def _inspect_observed_source(
    observation,
    source: ObservedInventorySource,
    *,
    snapshot_source,
    limits: InspectionLimits,
    ocr_budget: OcrBudget,
    ocr_runner,
    remaining_units: int,
) -> tuple[InspectionSource, tuple[InspectionUnitEvidence, ...]]:
    inventory_issues = source.issue_codes
    if "symlink" in inventory_issues or "special-file" in inventory_issues:
        return _source_only(source, "not-applicable", 0)
    if "unreadable" in inventory_issues:
        return _source_only(source, "unreadable", None, "document-unreadable")
    if _UNSAFE_SOURCE_ISSUES.intersection(inventory_issues):
        return _source_only(source, "unreadable", None, "document-unreadable")
    if source.detected_type in {"zip", "rar"}:
        return _source_only(source, "opaque", 0, "opaque-archive")
    if (
        source.detected_type == "xlsx"
        and source.extension not in _WORKBOOK_EXTENSIONS
    ):
        return _source_only(
            source,
            "opaque",
            0,
            "opaque-archive",
            detected_type="zip",
        )
    if source.detected_type == "unknown":
        return _source_only(source, "unsupported", 0, "unsupported-document-type")
    if type(source.size) is not int or source.size < 0:
        return _source_only(source, "unreadable", None, "document-unreadable")

    source_cap = {
        "pdf": limits.max_pdf_source_bytes,
        "xlsx": limits.max_workbook_source_bytes,
        "image": limits.max_image_source_bytes,
    }[source.detected_type]
    if source.size > source_cap:
        if source.detected_type == "image":
            if remaining_units < 1:
                raise InspectionUnitCountExceededError()
            adapter_result = InspectionAdapterResult(
                "inspected",
                1,
                (),
                (
                    InspectionUnitEvidence(
                        "image", 1, "none", (), ("unit-over-limit",)
                    ),
                ),
            )
        else:
            return _source_only(source, "over-limit", None, "document-over-limit")
    else:
        snapshot = snapshot_source(source.evidence_id, max_bytes=source_cap)
        archive_type = _leading_archive_type(snapshot)
        workbook_candidate = (
            archive_type == "zip"
            and source.detected_type == "xlsx"
            and source.extension in _WORKBOOK_EXTENSIONS
        )
        if archive_type is not None and not workbook_candidate:
            snapshot = b""
            return _source_only(
                source,
                "opaque",
                0,
                "opaque-archive",
                detected_type=archive_type,
            )
        if source.detected_type == "pdf":
            adapter_result = inspect_pdf(
                snapshot,
                limits=limits,
                ocr_budget=ocr_budget,
                ocr_runner=ocr_runner,
                remaining_units=remaining_units,
            )
        elif source.detected_type == "xlsx":
            adapter_result = inspect_workbook(
                snapshot,
                limits=limits,
                remaining_units=remaining_units,
            )
        else:
            if remaining_units < 1:
                raise InspectionUnitCountExceededError()
            adapter_result = inspect_image(
                snapshot,
                limits=limits,
                ocr_budget=ocr_budget,
                ocr_runner=ocr_runner,
            )
        snapshot = b""

    if (
        adapter_result.inspection_status == "inspected"
        and adapter_result.unit_count is not None
        and adapter_result.unit_count > remaining_units
    ):
        raise InspectionUnitCountExceededError()

    source_record = InspectionSource(
        source.evidence_id,
        source.detected_type,
        adapter_result.inspection_status,
        adapter_result.unit_count,
        _ordered_issues(source.issue_codes, adapter_result.source_issue_codes),
    )
    return source_record, adapter_result.units


def _canonical_result_bytes(result: InspectionResult) -> bytes:
    return (
        json.dumps(
            result.to_dict(),
            ensure_ascii=False,
            sort_keys=True,
            indent=2,
        ).encode("utf-8")
        + b"\n"
    )


def _inspection_result(
    observation,
    *,
    limits: InspectionLimits,
    ocr_session,
    snapshot_source=None,
) -> InspectionResult | str:
    if snapshot_source is None:
        snapshot_source = observation.snapshot
    if any(
        "changed-during-read" in observed_source.issue_codes
        for observed_source in observation.sources
    ):
        failure_code = "inspection-tree-changed"
        return failure_code

    ocr_budget = OcrBudget(
        max_units=limits.max_ocr_units,
        max_total_seconds=limits.max_ocr_total_seconds,
    )

    def bound_ocr(image_bytes, *, budget, timeout_seconds):
        return run_local_ocr(
            image_bytes,
            session=ocr_session,
            budget=budget,
            timeout_seconds=timeout_seconds,
        )

    sources = []
    units = []
    for observed_source in observation.sources:
        source_record, unit_evidence = _inspect_observed_source(
            observation,
            observed_source,
            snapshot_source=snapshot_source,
            limits=limits,
            ocr_budget=ocr_budget,
            ocr_runner=bound_ocr,
            remaining_units=limits.max_units - len(units),
        )
        for evidence in unit_evidence:
            if len(units) >= limits.max_units:
                raise InspectionUnitCountExceededError()
            classification = classify(
                evidence.unit_kind,
                evidence.inspection_method,
                evidence.signal_codes,
                evidence.issue_codes,
            )
            units.append(
                InspectionUnit(
                    unit_id=f"unit-{len(units) + 1:04d}",
                    evidence_id=observed_source.evidence_id,
                    unit_kind=evidence.unit_kind,
                    unit_index=evidence.unit_index,
                    suggested_role=classification.suggested_role,
                    confidence_band=classification.confidence_band,
                    needs_user_review=classification.needs_user_review,
                    inspection_method=evidence.inspection_method,
                    signal_codes=classification.signal_codes,
                    issue_codes=classification.issue_codes,
                )
            )
        sources.append(source_record)

    totals = InspectionTotals(
        sources=len(sources),
        units=len(units),
        classified=sum(unit.suggested_role != "unknown" for unit in units),
        unknown=sum(unit.suggested_role == "unknown" for unit in units),
        needs_user_review=sum(unit.needs_user_review for unit in units),
        issues=sum(len(source.issue_codes) for source in sources)
        + sum(len(unit.issue_codes) for unit in units),
    )
    result = InspectionResult(
        inspection_version="1.0",
        inspection_status="complete-with-issues" if totals.issues else "complete",
        observation_id=observation.observation_id,
        totals=totals,
        sources=tuple(sources),
        units=tuple(units),
    )
    if len(_canonical_result_bytes(result)) > limits.max_json_bytes:
        raise InspectionError("inspection-output-too-large")
    return result


def _mapped_inventory_error_code(error: InventoryError) -> str | None:
    code = getattr(error, "code", None)
    if type(code) is not str:
        return None
    if code == "inventory-tree-changed":
        return "inspection-tree-changed"
    if code in _RETAINED_INVENTORY_ERROR_CODES:
        return code
    return None


def _inspect_fresh_observation(
    source_root: Path,
    *,
    limits: InspectionLimits,
    ocr_session,
):
    outcome = _UNKNOWN_INVENTORY_FAILURE
    failure_code = None
    try:
        with open_inventory_observation(source_root) as observation:
            outcome = _inspection_result(
                observation,
                limits=limits,
                ocr_session=ocr_session,
            )
    except InventoryError as error:
        failure_code = _mapped_inventory_error_code(error)
    except PdfPageCountExceededError:
        failure_code = "inspection-pdf-page-count-exceeded"
    except PdfParserBoundaryExceededError:
        failure_code = "inspection-parser-boundary-exceeded"
    except WorkbookParserBoundaryExceededError:
        failure_code = "inspection-parser-boundary-exceeded"
    except WorkbookWorksheetCountExceededError:
        failure_code = "inspection-worksheet-count-exceeded"
    except InspectionUnitCountExceededError:
        failure_code = "inspection-unit-count-exceeded"
    if failure_code is not None:
        return failure_code
    return outcome


def _raise_controlled_failure(code: str) -> None:
    raise InspectionError(code)


def _raise_internal_failure() -> None:
    raise RuntimeError("inspection-internal-error")


def inspect_observation(
    observation: InventoryObservation,
    *,
    limits: InspectionLimits = DEFAULT_INSPECTION_LIMITS,
    _snapshot_source=None,
) -> InspectionResult:
    """Inspect one caller-owned live observation without closing it."""
    if type(observation) is not InventoryObservation:
        raise TypeError("observation must be a live inventory observation")
    if _snapshot_source is not None and not callable(_snapshot_source):
        raise TypeError("snapshot source must be callable")
    limits = _bounded_limits(limits)
    ocr_session = open_local_ocr()
    result = _UNKNOWN_INVENTORY_FAILURE
    failure_code = None
    try:
        result = _inspection_result(
            observation,
            limits=limits,
            ocr_session=ocr_session,
            snapshot_source=_snapshot_source,
        )
    except InventoryError as error:
        failure_code = _mapped_inventory_error_code(error)
    except PdfPageCountExceededError:
        failure_code = "inspection-pdf-page-count-exceeded"
    except PdfParserBoundaryExceededError:
        failure_code = "inspection-parser-boundary-exceeded"
    except WorkbookParserBoundaryExceededError:
        failure_code = "inspection-parser-boundary-exceeded"
    except WorkbookWorksheetCountExceededError:
        failure_code = "inspection-worksheet-count-exceeded"
    except InspectionUnitCountExceededError:
        failure_code = "inspection-unit-count-exceeded"
    finally:
        ocr_session = None
    if failure_code is not None:
        _raise_controlled_failure(failure_code)
    if type(result) is str:
        _raise_controlled_failure(result)
    if result is _UNKNOWN_INVENTORY_FAILURE:
        _raise_internal_failure()
    return result


def inspect_source(
    source_root: Path,
    *,
    limits: InspectionLimits = DEFAULT_INSPECTION_LIMITS,
) -> InspectionResult:
    """Inspect one fresh descriptor-bound source observation without writing."""
    limits = _bounded_limits(limits)
    ocr_session = open_local_ocr()
    result = _inspect_fresh_observation(
        source_root,
        limits=limits,
        ocr_session=ocr_session,
    )
    source_root = None
    ocr_session = None
    if type(result) is str:
        failure_code = result
        result = None
        _raise_controlled_failure(failure_code)
    if result is _UNKNOWN_INVENTORY_FAILURE:
        _raise_internal_failure()
    return result
