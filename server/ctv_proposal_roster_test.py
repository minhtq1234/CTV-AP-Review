"""TDD coverage for immutable private roster candidates and selection."""

from __future__ import annotations

from io import BytesIO

from openpyxl import Workbook
import pytest

from ctv_inspection_model import (
    InspectionResult,
    InspectionSource,
    InspectionTotals,
    InspectionUnit,
)
from ctv_proposal_roster import (
    choose_automatic_roster,
    load_roster_candidates,
)


_PRIVATE = ("Synthetic Person", "079123456781", "FA-SYNTHETIC-001")


def _workbook_bytes(*, headers=None, rows=(), formula_only_row=False):
    workbook = Workbook()
    worksheet = workbook.active
    worksheet.title = "Payment roster"
    worksheet.append(headers or ("name", "identity", "faCode"))
    for row in rows:
        worksheet.append(row)
    if formula_only_row:
        worksheet.cell(row=worksheet.max_row + 1, column=3, value="=1+1")
    output = BytesIO()
    workbook.save(output)
    workbook.close()
    return output.getvalue()


def _inspection_for_snapshots(snapshots, *, unit_numbers=None):
    if unit_numbers is None:
        unit_numbers = tuple(range(1, len(snapshots) + 1))
    sources = tuple(
        InspectionSource(
            evidence_id=f"evidence-{index:04d}",
            detected_type="xlsx",
            inspection_status="inspected",
            unit_count=1,
            issue_codes=(),
        )
        for index in range(1, len(snapshots) + 1)
    )
    units = tuple(
        InspectionUnit(
            unit_id=f"unit-{unit_number:04d}",
            evidence_id=source.evidence_id,
            unit_kind="worksheet",
            unit_index=1,
            suggested_role="payment-roster",
            confidence_band="high",
            needs_user_review=False,
            inspection_method="worksheet-structure",
            signal_codes=("roster-column-pattern", "roster-row-pattern"),
            issue_codes=(),
        )
        for source, unit_number in zip(sources, unit_numbers)
    )
    inspection = InspectionResult(
        inspection_version="1.0",
        inspection_status="complete",
        observation_id="observation-" + "0" * 64,
        totals=InspectionTotals(
            sources=len(sources),
            units=len(units),
            classified=len(units),
            unknown=0,
            needs_user_review=0,
            issues=0,
        ),
        sources=sources,
        units=units,
    )
    by_evidence_id = {
        source.evidence_id: snapshot
        for source, snapshot in zip(sources, snapshots)
    }

    def snapshot_source(evidence_id, *, max_bytes):
        assert max_bytes == 25 * 1024 * 1024
        return by_evidence_id[evidence_id]

    return inspection, snapshot_source


def generated_inspection_with_rosters(tmp_path, *, valid):
    del tmp_path
    snapshots = tuple(
        _workbook_bytes(
            rows=((f"Synthetic Person {index}", f"07912345678{index}", "FA-SYNTHETIC-001"),)
        )
        for index in range(1, valid + 1)
    )
    return _inspection_for_snapshots(snapshots)


def test_one_valid_roster_is_selected_without_user_action(tmp_path):
    inspection, snapshots = generated_inspection_with_rosters(tmp_path, valid=1)
    candidates = load_roster_candidates(inspection, snapshots)
    selection = choose_automatic_roster(candidates)

    assert selection.status == "selected"
    assert selection.roster_unit_id == candidates[0].unit_id
    assert selection.issue_codes == ()


def test_equal_valid_rosters_create_one_roster_exception(tmp_path):
    inspection, snapshots = generated_inspection_with_rosters(tmp_path, valid=2)
    selection = choose_automatic_roster(
        load_roster_candidates(inspection, snapshots)
    )

    assert selection.status == "ambiguous"
    assert selection.roster_unit_id is None
    assert selection.issue_codes == ("roster-ambiguous",)


def test_no_payment_roster_candidate_is_missing():
    inspection, snapshots = _inspection_for_snapshots(())

    selection = choose_automatic_roster(
        load_roster_candidates(inspection, snapshots)
    )

    assert selection.status == "missing"
    assert selection.roster_unit_id is None
    assert selection.candidate_unit_ids == ()
    assert selection.issue_codes == ("roster-missing",)


@pytest.mark.parametrize(
    ("snapshot", "expected_codes"),
    [
        (
            _workbook_bytes(headers=("name", "other"), rows=((_PRIVATE[0], "x"),)),
            ("roster-header-missing", "roster-row-invalid"),
        ),
        (_workbook_bytes(rows=()), ("roster-row-invalid",)),
        (
            _workbook_bytes(
                rows=(
                    (_PRIVATE[0], _PRIVATE[1], _PRIVATE[2]),
                    ("Other Person", _PRIVATE[1], _PRIVATE[2]),
                )
            ),
            ("roster-identity-duplicate",),
        ),
        (
            _workbook_bytes(
                rows=((_PRIVATE[0], _PRIVATE[1], _PRIVATE[2]),),
                formula_only_row=True,
            ),
            ("roster-row-invalid",),
        ),
    ],
    ids=("malformed-header", "zero-rows", "duplicate-identity", "formula-only-row"),
)
def test_blocking_roster_defects_are_ineligible(snapshot, expected_codes):
    inspection, snapshots = _inspection_for_snapshots((snapshot,))

    candidates = load_roster_candidates(inspection, snapshots)
    selection = choose_automatic_roster(candidates)

    assert candidates[0].blocking_issue_codes == expected_codes
    assert selection.status == "invalid"
    assert selection.issue_codes == ("roster-invalid",)


@pytest.mark.parametrize(
    ("headers", "rows", "expected_issue"),
    [
        (
            ("name", "identity"),
            ((_PRIVATE[0], _PRIVATE[1]),),
            "roster-fa-code-missing",
        ),
        (
            ("name", "identity", "faCode"),
            ((_PRIVATE[0], _PRIVATE[1], ""),),
            "roster-fa-code-blank",
        ),
        (
            ("name", "identity", "faCode"),
            (
                (_PRIVATE[0], _PRIVATE[1], _PRIVATE[2]),
                ("Other Person", "079123456782", "FA-SYNTHETIC-002"),
            ),
            "roster-fa-code-conflict",
        ),
    ],
    ids=("missing-column", "blank-value", "conflicting-values"),
)
def test_fa_code_incompleteness_prevents_automatic_selection(
    headers, rows, expected_issue
):
    inspection, snapshots = _inspection_for_snapshots(
        (_workbook_bytes(headers=headers, rows=rows),)
    )

    candidates = load_roster_candidates(inspection, snapshots)
    selection = choose_automatic_roster(candidates)

    assert expected_issue in candidates[0].package_issue_codes
    assert candidates[0].score[1] == 0
    assert selection.status == "invalid"
    assert selection.issue_codes == ("roster-invalid",)


def test_unique_eligible_roster_with_most_rows_wins_in_stable_numeric_order():
    inspection, snapshots = _inspection_for_snapshots(
        (
            _workbook_bytes(rows=(("Person 10", "ID-10", "FA-1"),)),
            _workbook_bytes(
                rows=(("Person 2A", "ID-2A", "FA-1"), ("Person 2B", "ID-2B", "FA-1"))
            ),
        ),
        unit_numbers=(10, 2),
    )

    candidates = load_roster_candidates(inspection, snapshots)
    selection = choose_automatic_roster(candidates)

    assert tuple(candidate.unit_id for candidate in candidates) == (
        "unit-0002",
        "unit-0010",
    )
    assert selection.status == "selected"
    assert selection.roster_unit_id == "unit-0002"
    assert selection.candidate_unit_ids == ("unit-0002", "unit-0010")


def test_row_cap_is_blocking():
    rows = tuple(
        (f"Person {index}", f"ID-{index}", "FA-1")
        for index in range(1, 10_001)
    )
    inspection, snapshots = _inspection_for_snapshots(
        (_workbook_bytes(rows=rows),)
    )

    candidate = load_roster_candidates(inspection, snapshots)[0]

    assert candidate.blocking_issue_codes == ("roster-over-limit",)


def test_cell_cap_is_blocking():
    workbook = Workbook()
    worksheet = workbook.active
    worksheet.cell(row=1, column=1, value="x")
    worksheet.cell(row=7, column=15_000, value="x")
    output = BytesIO()
    workbook.save(output)
    workbook.close()
    inspection, snapshots = _inspection_for_snapshots((output.getvalue(),))

    candidate = load_roster_candidates(inspection, snapshots)[0]

    assert candidate.blocking_issue_codes == ("roster-over-limit",)


def test_workbook_cap_and_snapshot_failure_use_one_fixed_private_safe_result():
    inspection, _snapshots = _inspection_for_snapshots((_workbook_bytes(),))
    calls = []

    def failing_snapshot_source(evidence_id, *, max_bytes):
        calls.append((evidence_id, max_bytes))
        raise RuntimeError("private-path-and-cell-value")

    candidate = load_roster_candidates(inspection, failing_snapshot_source)[0]

    assert calls == [("evidence-0001", 25 * 1024 * 1024)]
    assert candidate.blocking_issue_codes == ("roster-unreadable",)
    assert "private-path-and-cell-value" not in repr(candidate)


def test_private_roster_values_are_absent_from_candidate_row_and_selection_repr():
    inspection, snapshots = _inspection_for_snapshots(
        (_workbook_bytes(rows=((_PRIVATE[0], _PRIVATE[1], _PRIVATE[2]),)),)
    )

    candidates = load_roster_candidates(inspection, snapshots)
    selection = choose_automatic_roster(candidates)

    assert all(value not in repr(candidates[0]) for value in _PRIVATE)
    assert all(value not in repr(candidates[0].rows[0]) for value in _PRIVATE)
    assert all(value not in repr(selection) for value in _PRIVATE)
