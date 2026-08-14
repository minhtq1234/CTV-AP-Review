import ast
from pathlib import Path

import pytest

from ctv_inspection_classifier import (
    Classification,
    TextSignalContext,
    classify,
    roster_header_categories_from_private_text,
    signals_from_private_text,
)
from ctv_inspection_model import SIGNAL_ORDER


@pytest.mark.parametrize(
    ("kind", "signals", "role", "band"),
    [
        ("worksheet", ("roster-column-pattern", "roster-row-pattern"), "payment-roster", "high"),
        ("worksheet", ("roster-column-pattern",), "payment-roster", "medium"),
        ("pdf-page", ("service-contract-heading", "party-section-present", "signature-section-present"), "service-contract", "high"),
        ("pdf-page", ("service-contract-heading", "party-section-present"), "service-contract", "medium"),
        ("pdf-page", ("service-contract-heading",), "service-contract", "low"),
        ("pdf-page", ("acceptance-heading", "party-section-present", "signature-section-present"), "acceptance-record", "high"),
        ("pdf-page", ("acceptance-heading", "signature-section-present"), "acceptance-record", "medium"),
        ("pdf-page", ("acceptance-heading",), "acceptance-record", "low"),
        ("pdf-page", ("payment-request-heading", "party-section-present", "signature-section-present"), "payment-tax-form", "high"),
        ("pdf-page", ("tax-form-heading", "party-section-present"), "payment-tax-form", "medium"),
        ("pdf-page", ("tax-form-heading",), "payment-tax-form", "low"),
        ("image", ("identity-front-heading", "identity-front-layout", "identity-number-pattern-present"), "identity-front", "high"),
        ("image", ("identity-front-heading", "identity-front-layout"), "identity-front", "medium"),
        ("image", ("identity-front-layout",), "identity-front", "low"),
        ("image", ("identity-back-layout", "identity-issue-section-present"), "identity-back", "high"),
        ("image", ("identity-back-layout",), "identity-back", "medium"),
        ("image", ("case-level-heading", "multi-party-reference-present"), "shared-supporting-evidence", "medium"),
        ("pdf-page", ("supporting-document-heading", "mostly-text-page"), "other-supporting-evidence", "medium"),
        ("pdf-page", ("supporting-document-heading",), "other-supporting-evidence", "low"),
    ],
)
def test_exact_role_table(kind, signals, role, band):
    result = classify(kind, "embedded-text", signals, ())
    assert (result.suggested_role, result.confidence_band) == (role, band)


@pytest.mark.parametrize(
    ("kind", "signals", "expected_issue", "expected_marker"),
    [
        ("pdf-page", ("service-contract-heading", "party-section-present", "signature-section-present", "acceptance-heading", "acceptance-period-present", "identity-front-heading", "identity-front-layout", "identity-number-pattern-present"), "classification-conflict", True),
        ("pdf-page", ("service-contract-heading", "party-section-present", "signature-section-present", "acceptance-heading", "signature-section-present"), "classification-conflict", True),
        ("pdf-page", ("acceptance-heading", "signature-section-present", "case-level-heading", "multi-party-reference-present"), "classification-conflict", True),
        ("pdf-page", ("service-contract-heading", "acceptance-heading"), "classification-ambiguous", True),
        ("pdf-page", (), "classification-ambiguous", False),
    ],
)
def test_conflicts_and_unknowns_have_fixed_issue_codes(kind, signals, expected_issue, expected_marker):
    result = classify(kind, "embedded-text", signals, ())
    assert (result.suggested_role, result.confidence_band, result.needs_user_review) == (
        "unknown", "none", True,
    )
    assert result.issue_codes == (expected_issue,)
    assert ("multiple-role-signals" in result.signal_codes) is expected_marker


@pytest.mark.parametrize(
    ("kind", "signals", "allowed_roles"),
    [
        ("pdf-page", SIGNAL_ORDER, {
            "payment-roster", "service-contract", "acceptance-record", "payment-tax-form",
            "identity-front", "identity-back", "shared-supporting-evidence",
            "other-supporting-evidence", "unknown",
        }),
        ("worksheet", SIGNAL_ORDER, {
            "payment-roster", "other-supporting-evidence", "unknown",
        }),
        ("image", SIGNAL_ORDER, {
            "identity-front", "identity-back", "shared-supporting-evidence",
            "other-supporting-evidence", "unknown",
        }),
    ],
)
def test_unit_kind_never_emits_a_disallowed_role(kind, signals, allowed_roles):
    result = classify(kind, "embedded-text", signals, ())
    assert result.suggested_role in allowed_roles


@pytest.mark.parametrize(
    ("kind", "signals"),
    [
        ("pdf-page", ("roster-column-pattern", "roster-row-pattern")),
        ("worksheet", ("service-contract-heading", "party-section-present", "signature-section-present")),
        ("image", ("acceptance-heading", "party-section-present", "signature-section-present")),
    ],
)
def test_unit_kind_rejects_other_kind_role_evidence(kind, signals):
    result = classify(kind, "embedded-text", signals, ())
    assert (result.suggested_role, result.confidence_band) == ("unknown", "none")


@pytest.mark.parametrize(
    ("signals", "expected"),
    [
        (("roster-row-pattern",), ("unknown", "none")),
        (("identity-issue-section-present", "identity-front-heading"), ("unknown", "none")),
        (("case-level-heading",), ("unknown", "none")),
    ],
)
def test_rule_table_non_emitted_states_remain_unknown(signals, expected):
    result = classify("image", "embedded-text", signals, ())
    assert (result.suggested_role, result.confidence_band) == expected


@pytest.mark.parametrize(
    ("signals", "expected_review"),
    [
        (("identity-front-heading", "identity-front-layout", "identity-number-pattern-present"), False),
        (("identity-front-heading", "identity-front-layout"), True),
        (("identity-front-layout",), True),
        ((), True),
    ],
)
def test_only_unissued_high_confidence_proposals_skip_review(signals, expected_review):
    result = classify("image", "embedded-text", signals, ())
    assert result.needs_user_review is expected_review


def test_classifier_canonicalizes_signal_and_issue_order_without_duplicates():
    forward = classify(
        "image", "local-ocr",
        ("identity-front-layout", "identity-front-heading", "identity-number-pattern-present"),
        ("ocr-low-confidence", "embedded-media-present"),
    )
    backward = classify(
        "image", "local-ocr",
        ("identity-number-pattern-present", "identity-front-heading", "identity-front-layout"),
        ("embedded-media-present", "ocr-low-confidence", "ocr-low-confidence"),
    )
    assert forward == backward
    assert forward.issue_codes == ("embedded-media-present", "ocr-low-confidence")
    assert forward.needs_user_review is True


@pytest.mark.parametrize("issue", ("ocr-unavailable", "ocr-failed", "ocr-timeout", "ocr-low-confidence"))
def test_ocr_issues_always_require_review(issue):
    result = classify(
        "image", "local-ocr",
        ("identity-front-heading", "identity-front-layout", "identity-number-pattern-present"),
        (issue,),
    )
    assert result.needs_user_review is True


@pytest.mark.parametrize("issue", ("ocr-failed", "ocr-timeout"))
def test_failed_or_timed_out_ocr_discards_ocr_signals(issue):
    result = classify(
        "image", "local-ocr",
        ("identity-front-heading", "identity-front-layout", "identity-number-pattern-present"),
        (issue,),
    )
    assert (result.suggested_role, result.confidence_band) == ("identity-front", "low")
    assert result.needs_user_review is True


@pytest.mark.parametrize("issue", ("ocr-failed", "ocr-timeout"))
def test_failed_or_timed_out_ocr_retains_structural_identity_layout(issue):
    result = classify(
        "image", "local-ocr",
        ("identity-back-layout", "identity-issue-section-present"),
        (issue,),
    )
    assert (result.suggested_role, result.confidence_band, result.needs_user_review) == (
        "identity-back", "medium", True,
    )


def test_hidden_worksheet_retains_role_and_requires_review():
    result = classify(
        "worksheet", "worksheet-structure",
        ("roster-column-pattern", "roster-row-pattern", "worksheet-hidden"),
        ("worksheet-hidden",),
    )
    assert (result.suggested_role, result.confidence_band, result.needs_user_review) == (
        "payment-roster", "high", True,
    )


def test_hidden_worksheet_signal_alone_forces_review_for_a_high_roster():
    result = classify(
        "worksheet", "worksheet-structure",
        ("roster-column-pattern", "roster-row-pattern", "worksheet-hidden"),
        (),
    )
    assert (result.suggested_role, result.confidence_band, result.needs_user_review) == (
        "payment-roster", "high", True,
    )


def test_private_text_reducer_normalizes_vietnamese_and_emits_only_safe_codes():
    private_text = (
        "  HỢP   ĐỒNG   DỊCH   VỤ\nBÊN   A  - BÊN B\n"
        "NỘI DUNG CÔNG VIỆC\nĐẠI DIỆN KÝ\n"
        "CCCD: 012345678901; 12/08/2026; 1.250.000; Nguyễn Văn An"
    )
    signals = signals_from_private_text(
        private_text,
        TextSignalContext("pdf-page", mostly_image=False, embedded_media=False,
                          worksheet_hidden=False, row_pattern=False),
    )
    assert signals == (
        "service-contract-heading", "party-section-present",
        "service-scope-section-present", "signature-section-present",
        "identity-number-pattern-present", "mostly-text-page",
    )
    assert tuple(sorted(signals, key=SIGNAL_ORDER.index)) == signals
    forbidden = ("012345678901", "12/08/2026", "1.250.000", "Nguyễn", private_text)
    assert all(fragment not in " ".join(signals) for fragment in forbidden)


def test_roster_header_reducer_recognizes_only_fixed_canonical_categories():
    assert roster_header_categories_from_private_text("faCode") == ("faCode",)
    assert roster_header_categories_from_private_text("bankAccount") == ("bankAccount",)
    assert roster_header_categories_from_private_text("serviceFee") == ("serviceFee",)
    assert roster_header_categories_from_private_text("PRIVATE PERSON 079123456781") == ()


def test_private_text_reducer_does_not_leak_invalid_input_into_errors():
    private_text = "Nguyễn Văn An 012345678901 12/08/2026"
    with pytest.raises(ValueError) as error:
        signals_from_private_text(private_text, object())
    rendered = str(error.value)
    assert all(fragment not in rendered for fragment in (private_text, "Nguyễn", "012345678901", "12/08/2026"))


def test_classifier_converts_untrusted_iterable_errors_to_fixed_safe_errors():
    private_text = "Nguyễn Văn An 012345678901"

    def unsafe_codes():
        raise RuntimeError(private_text)
        yield "service-contract-heading"

    with pytest.raises(ValueError) as error:
        classify("pdf-page", "embedded-text", unsafe_codes(), ())
    assert private_text not in str(error.value)


@pytest.mark.parametrize("unit_kind, inspection_method", (
    (object(), "embedded-text"),
    ("pdf-page", object()),
))
def test_classifier_rejects_hostile_primitive_inputs_without_leaking_them(unit_kind, inspection_method):
    private_text = "Nguyễn Văn An 012345678901"

    class HostileValue:
        def __hash__(self):
            raise RuntimeError(private_text)

        def __eq__(self, other):
            raise RuntimeError(private_text)

    if not isinstance(unit_kind, str):
        unit_kind = HostileValue()
    else:
        inspection_method = HostileValue()
    with pytest.raises(ValueError) as error:
        classify(unit_kind, inspection_method, (), ())
    assert private_text not in str(error.value)


def test_structural_context_signals_are_safe_and_canonically_ordered():
    signals = signals_from_private_text(
        "DANH SÁCH CHI TRẢ",
        TextSignalContext("worksheet", mostly_image=True, embedded_media=True,
                          worksheet_hidden=True, row_pattern=True,
                          roster_column_pattern=True),
    )
    assert signals == (
        "roster-column-pattern", "roster-row-pattern", "embedded-media-present",
        "worksheet-hidden", "mostly-image-page",
    )


def test_single_roster_like_cell_cannot_emit_a_row_level_column_pattern():
    signals = signals_from_private_text(
        "MA SO NHAN VIEN",
        TextSignalContext(
            "worksheet",
            mostly_image=False,
            embedded_media=False,
            worksheet_hidden=False,
            row_pattern=False,
        ),
    )

    assert "roster-column-pattern" not in signals


def test_text_signal_context_rejects_string_subclasses_before_membership():
    class StringSubclass(str):
        pass

    with pytest.raises(ValueError, match="unit_kind"):
        TextSignalContext(
            StringSubclass("worksheet"),
            mostly_image=False,
            embedded_media=False,
            worksheet_hidden=False,
            row_pattern=False,
        )


@pytest.mark.parametrize(
    "overrides",
    [
        {"confidence_band": "medium", "needs_user_review": False},
        {"issue_codes": ("ocr-low-confidence",), "needs_user_review": False},
        {"signal_codes": ("worksheet-hidden",), "needs_user_review": False},
    ],
)
def test_classification_constructor_enforces_the_complete_review_invariant(overrides):
    values = {
        "suggested_role": "service-contract",
        "confidence_band": "high",
        "needs_user_review": False,
        "issue_codes": (),
        "signal_codes": (),
    }
    values.update(overrides)

    with pytest.raises(ValueError, match="review"):
        Classification(**values)


def test_classification_rejects_string_subclasses_as_non_exact_primitives():
    class StringSubclass(str):
        pass

    with pytest.raises(ValueError, match="suggested_role"):
        Classification(
            StringSubclass("service-contract"),
            "high",
            False,
            (),
        )


def test_classifier_is_frozen_and_returns_only_fixed_issue_codes():
    result = classify("pdf-page", "embedded-text", (), ())
    assert isinstance(result, Classification)
    with pytest.raises((AttributeError, TypeError)):
        result.suggested_role = "service-contract"
    assert result.issue_codes == ("classification-ambiguous",)


def test_classifier_has_only_approved_standard_library_and_model_imports():
    module_path = Path(__file__).with_name("ctv_inspection_classifier.py")
    module = ast.parse(module_path.read_text())
    imports = {
        node.module.split(".")[0]
        for node in ast.walk(module)
        if isinstance(node, ast.ImportFrom) and node.module
    }
    imports |= {
        alias.name.split(".")[0]
        for node in ast.walk(module)
        if isinstance(node, ast.Import)
        for alias in node.names
    }
    assert imports <= {"dataclasses", "re", "unicodedata", "ctv_inspection_model"}
