import json

import pytest

from ctv_inspection_model import (
    DEFAULT_INSPECTION_LIMITS,
    INSPECTION_ISSUE_ORDER,
    SIGNAL_ORDER,
    InspectionAdapterResult,
    InspectionLimits,
    InspectionResult,
    InspectionSource,
    InspectionTotals,
    InspectionUnit,
    InspectionUnitEvidence,
)


def _unit(**overrides):
    values = dict(
        unit_id="unit-0001",
        evidence_id="evidence-0001",
        unit_kind="pdf-page",
        unit_index=1,
        suggested_role="service-contract",
        confidence_band="high",
        needs_user_review=False,
        inspection_method="embedded-text",
        signal_codes=(
            "service-contract-heading",
            "party-section-present",
            "signature-section-present",
        ),
        issue_codes=(),
    )
    values.update(overrides)
    return InspectionUnit(**values)


def _source(**overrides):
    values = dict(
        evidence_id="evidence-0001",
        detected_type="pdf",
        inspection_status="inspected",
        unit_count=1,
        issue_codes=(),
    )
    values.update(overrides)
    return InspectionSource(**values)


def _result(*, source=None, unit=None, status="complete", totals=None):
    source = _source() if source is None else source
    unit = _unit() if unit is None else unit
    totals = (
        InspectionTotals(1, 1, 1, 0, 0, 0) if totals is None else totals
    )
    return InspectionResult(
        inspection_version="1.0",
        inspection_status=status,
        observation_id="observation-" + "a" * 64,
        totals=totals,
        sources=(source,),
        units=(unit,),
    )


def test_result_serializes_exact_private_shape():
    payload = _result().to_dict()

    assert set(payload) == {
        "inspectionVersion", "inspectionStatus", "observationId",
        "totals", "sources", "units",
    }
    assert payload["totals"] == {
        "sources": 1,
        "units": 1,
        "classified": 1,
        "unknown": 0,
        "needsUserReview": 0,
        "issues": 0,
    }
    assert set(payload["sources"][0]) == {
        "evidenceId", "detectedType", "inspectionStatus", "unitCount", "issueCodes",
    }
    assert set(payload["units"][0]) == {
        "unitId", "evidenceId", "unitKind", "unitIndex", "suggestedRole",
        "confidenceBand", "needsUserReview", "inspectionMethod", "signalCodes",
        "issueCodes",
    }
    assert "/" not in json.dumps(payload)


@pytest.mark.parametrize(
    ("factory", "field", "value"),
    [
        (_source, "detected_type", "docx"),
        (_source, "inspection_status", "partial"),
        (_unit, "unit_kind", "pdf"),
        (_unit, "suggested_role", "contract"),
        (_unit, "confidence_band", "certain"),
        (_unit, "inspection_method", "parser"),
    ],
)
def test_records_reject_invalid_literal_domains(factory, field, value):
    with pytest.raises(ValueError, match=field):
        factory(**{field: value})


@pytest.mark.parametrize(
    ("factory", "field", "value"),
    [
        (_source, "evidence_id", "evidence-private/path"),
        (_source, "evidence_id", "evidence-1"),
        (_unit, "unit_id", "unit-private/path"),
        (_unit, "unit_id", "unit-1"),
        (_unit, "evidence_id", "evidence-0001-name"),
    ],
)
def test_records_reject_unsafe_or_malformed_opaque_ids(factory, field, value):
    with pytest.raises(ValueError, match=field):
        factory(**{field: value})


@pytest.mark.parametrize(
    ("unit_kind", "unit_index"),
    [
        ("pdf-page", 0),
        ("pdf-page", 10_001),
        ("worksheet", 0),
        ("worksheet", 101),
        ("image", 2),
    ],
)
def test_unit_rejects_zero_or_out_of_range_index(unit_kind, unit_index):
    with pytest.raises(ValueError, match="unit_index"):
        _unit(unit_kind=unit_kind, unit_index=unit_index)


@pytest.mark.parametrize(
    ("unit_kind", "suggested_role"),
    [
        ("worksheet", "service-contract"),
        ("image", "payment-roster"),
        ("image", "acceptance-record"),
    ],
)
def test_unit_rejects_roles_not_allowed_for_its_kind(unit_kind, suggested_role):
    with pytest.raises(ValueError, match="suggested_role"):
        _unit(unit_kind=unit_kind, suggested_role=suggested_role)


@pytest.mark.parametrize(
    "overrides",
    [
        {"suggested_role": "unknown", "confidence_band": "high", "needs_user_review": True},
        {"suggested_role": "service-contract", "confidence_band": "none", "needs_user_review": True},
        {"needs_user_review": True},
        {"confidence_band": "medium", "needs_user_review": False},
        {"issue_codes": ("ocr-failed",), "needs_user_review": False},
    ],
)
def test_unit_enforces_confidence_and_review_contract(overrides):
    with pytest.raises(ValueError):
        _unit(**overrides)


@pytest.mark.parametrize(
    ("field", "values"),
    [
        ("signal_codes", ("unknown-signal",)),
        ("signal_codes", ("signature-section-present", "party-section-present")),
        ("signal_codes", ("party-section-present", "party-section-present")),
        ("issue_codes", ("unknown-issue",)),
        ("issue_codes", ("ocr-failed", "ocr-failed")),
        ("issue_codes", ("ocr-failed", "document-unreadable")),
    ],
)
def test_unit_rejects_unknown_duplicate_or_unordered_codes(field, values):
    with pytest.raises(ValueError, match=field):
        _unit(**{field: values})


@pytest.mark.parametrize(
    "overrides",
    [
        {"inspection_status": "inspected", "unit_count": None},
        {"inspection_status": "opaque", "detected_type": "pdf", "unit_count": 0},
        {"inspection_status": "opaque", "detected_type": "zip", "unit_count": 1},
        {"inspection_status": "unsupported", "unit_count": None},
        {"inspection_status": "unreadable", "unit_count": 0},
        {"inspection_status": "encrypted", "unit_count": 0},
        {"inspection_status": "over-limit", "unit_count": 0},
        {"inspection_status": "not-applicable", "unit_count": None},
    ],
)
def test_source_rejects_invalid_status_unit_count_combinations(overrides):
    with pytest.raises(ValueError, match="unit_count|inspection_status"):
        _source(**overrides)


@pytest.mark.parametrize(
    ("inspection_status", "detected_type", "unit_count", "issue_code"),
    [
        ("opaque", "zip", 0, "opaque-archive"),
        ("unsupported", "unknown", 0, "unsupported-document-type"),
        ("unreadable", "pdf", None, "document-unreadable"),
        ("encrypted", "pdf", None, "document-encrypted"),
        ("over-limit", "pdf", None, "document-over-limit"),
    ],
)
def test_problem_source_status_requires_its_safe_issue(
    inspection_status, detected_type, unit_count, issue_code
):
    with pytest.raises(ValueError, match="issue_codes"):
        _source(
            inspection_status=inspection_status,
            detected_type=detected_type,
            unit_count=unit_count,
            issue_codes=(),
        )
    assert _source(
        inspection_status=inspection_status,
        detected_type=detected_type,
        unit_count=unit_count,
        issue_codes=(issue_code,),
    ).issue_codes == (issue_code,)


def test_adapter_result_is_immutable_and_requires_inspected_count_to_match_units():
    evidence = InspectionUnitEvidence(
        unit_kind="pdf-page",
        unit_index=1,
        inspection_method="embedded-text",
        signal_codes=["service-contract-heading"],
        issue_codes=[],
    )
    signals = evidence.signal_codes
    assert signals == ("service-contract-heading",)
    with pytest.raises(ValueError, match="unit_count"):
        InspectionAdapterResult("inspected", 2, (), (evidence,))
    with pytest.raises(ValueError, match="unit_count"):
        InspectionAdapterResult("opaque", None, (), ())


@pytest.mark.parametrize(
    "totals",
    [
        InspectionTotals(0, 1, 1, 0, 0, 0),
        InspectionTotals(1, 0, 1, 0, 0, 0),
        InspectionTotals(1, 1, 0, 0, 0, 0),
        InspectionTotals(1, 1, 1, 1, 0, 0),
        InspectionTotals(1, 1, 1, 0, 1, 0),
        InspectionTotals(1, 1, 1, 0, 0, 1),
    ],
)
def test_result_rejects_totals_that_do_not_match_records(totals):
    with pytest.raises(ValueError, match="totals"):
        _result(totals=totals)


def test_result_requires_inspected_source_count_to_match_bound_units():
    with pytest.raises(ValueError, match="unit_count"):
        _result(source=_source(unit_count=2))


def test_result_requires_status_to_match_source_or_unit_issues():
    issue_source = _source(issue_codes=("document-unreadable",))
    with pytest.raises(ValueError, match="inspection_status"):
        _result(source=issue_source, status="complete", totals=InspectionTotals(1, 1, 1, 0, 0, 1))
    with pytest.raises(ValueError, match="inspection_status"):
        _result(status="complete-with-issues")


def test_models_defensively_copy_caller_containers_and_serialized_values():
    signals = ["service-contract-heading", "party-section-present"]
    issues = []
    unit = _unit(signal_codes=signals, issue_codes=issues)
    signals.append("signature-section-present")
    issues.append("ocr-failed")
    result = _result(unit=unit)
    payload = result.to_dict()
    payload["units"][0]["signalCodes"].append("signature-section-present")
    assert result.units[0].signal_codes == (
        "service-contract-heading", "party-section-present"
    )


def test_result_rejects_more_than_ten_thousand_public_units():
    unit = _unit()
    sources = (_source(unit_count=10_001),)
    units = (unit,) * 10_001
    totals = InspectionTotals(1, 10_001, 10_001, 0, 0, 0)
    with pytest.raises(ValueError, match="max_units"):
        InspectionResult("1.0", "complete", "observation-" + "a" * 64, totals, sources, units)


def test_default_limits_are_the_exact_hard_ceilings():
    assert DEFAULT_INSPECTION_LIMITS.max_pdf_source_bytes == 256 * 1024 * 1024
    assert DEFAULT_INSPECTION_LIMITS.max_pdf_pages == 10_000
    assert DEFAULT_INSPECTION_LIMITS.max_embedded_text_bytes_per_page == 64 * 1024
    assert DEFAULT_INSPECTION_LIMITS.max_workbook_source_bytes == 25 * 1024 * 1024
    assert DEFAULT_INSPECTION_LIMITS.max_worksheets_per_workbook == 100
    assert DEFAULT_INSPECTION_LIMITS.max_cells_per_workbook == 100_000
    assert DEFAULT_INSPECTION_LIMITS.max_cell_text_characters == 256
    assert DEFAULT_INSPECTION_LIMITS.max_image_source_bytes == 25 * 1024 * 1024
    assert DEFAULT_INSPECTION_LIMITS.max_decoded_image_pixels == 50_000_000
    assert DEFAULT_INSPECTION_LIMITS.max_ocr_units == 500
    assert DEFAULT_INSPECTION_LIMITS.max_ocr_seconds_per_unit == 30
    assert DEFAULT_INSPECTION_LIMITS.max_ocr_total_seconds == 30 * 60
    assert DEFAULT_INSPECTION_LIMITS.max_units == 10_000
    assert DEFAULT_INSPECTION_LIMITS.max_json_bytes == 16 * 1024 * 1024


@pytest.mark.parametrize(
    "field",
    tuple(DEFAULT_INSPECTION_LIMITS.__dataclass_fields__),
)
def test_limits_reject_values_above_hard_ceilings(field):
    values = {
        name: getattr(DEFAULT_INSPECTION_LIMITS, name)
        for name in DEFAULT_INSPECTION_LIMITS.__dataclass_fields__
    }
    values[field] += 1
    with pytest.raises(ValueError, match=field):
        InspectionLimits(**values)


def test_code_orders_are_exact_and_stable():
    assert SIGNAL_ORDER == (
        "service-contract-heading", "party-section-present", "service-scope-section-present",
        "signature-section-present", "acceptance-heading", "acceptance-period-present",
        "payment-request-heading", "tax-form-heading", "roster-column-pattern",
        "roster-row-pattern", "identity-front-heading", "identity-front-layout",
        "identity-back-layout", "identity-number-pattern-present",
        "identity-issue-section-present", "case-level-heading",
        "multi-party-reference-present", "supporting-document-heading",
        "embedded-media-present", "worksheet-hidden", "mostly-image-page",
        "mostly-text-page", "multiple-role-signals",
    )
    assert INSPECTION_ISSUE_ORDER[-15:] == (
        "opaque-archive", "unsupported-document-type", "document-unreadable",
        "document-encrypted", "document-over-limit", "unit-over-limit",
        "embedded-media-present", "worksheet-hidden", "multi-frame-image",
        "ocr-unavailable", "ocr-timeout", "ocr-failed", "ocr-low-confidence",
        "classification-ambiguous", "classification-conflict",
    )
