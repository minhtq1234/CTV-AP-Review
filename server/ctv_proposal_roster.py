"""Immutable, privacy-safe roster candidates from retained workbook snapshots."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from io import BytesIO
from typing import Literal

from openpyxl import load_workbook

from ctv_inspection_classifier import roster_header_categories_from_private_text
from ctv_inspection_model import DEFAULT_INSPECTION_LIMITS, InspectionResult
from ctv_inspection_workbook import (
    PackageWorkbookError,
    worksheet_nonblank_row_indexes,
)


_MAX_ROWS = 10_000
_MAX_CELLS = 100_000
_MAX_CELL_TEXT = 256
_MAX_WORKBOOK_BYTES = 25 * 1024 * 1024
_ROSTER_ISSUE_ORDER = (
    "roster-header-missing",
    "roster-row-invalid",
    "roster-identity-duplicate",
    "roster-over-limit",
    "roster-unreadable",
)
_CANONICAL_ROSTER_FIELDS = (
    "name",
    "identity",
    "faCode",
    "taxId",
    "birthDate",
    "bankAccount",
    "serviceFee",
    "product",
)


@dataclass(frozen=True)
class RosterCandidateRow:
    row_index: int
    name: str = field(repr=False)
    identity: str = field(repr=False)
    values: tuple[tuple[str, str], ...] = field(repr=False)


@dataclass(frozen=True)
class RosterCandidate:
    unit_id: str
    evidence_id: str
    worksheet_index: int
    rows: tuple[RosterCandidateRow, ...] = field(repr=False)
    blocking_issue_codes: tuple[str, ...]
    package_issue_codes: tuple[str, ...]
    canonical_to_source_columns: tuple[tuple[str, str], ...] = field(repr=False)
    score: tuple[int, int, int]


@dataclass(frozen=True)
class RosterSelection:
    status: Literal["selected", "missing", "ambiguous", "invalid"]
    roster_unit_id: str | None
    candidate_unit_ids: tuple[str, ...]
    issue_codes: tuple[str, ...]


def _private_cell_text(value: object) -> str:
    if value is None or type(value) not in {str, int, float}:
        return ""
    text = str(value).strip()
    if len(text) > _MAX_CELL_TEXT:
        return ""
    return text


def _numeric_unit_key(value) -> int:
    return int(value.unit_id.rsplit("-", 1)[1])


def _candidate(
    unit,
    *,
    rows: tuple[RosterCandidateRow, ...] = (),
    blocking_issue_codes: tuple[str, ...] = (),
    package_issue_codes: tuple[str, ...] = (),
    canonical_to_source_columns: tuple[tuple[str, str], ...] = (),
) -> RosterCandidate:
    return RosterCandidate(
        unit_id=unit.unit_id,
        evidence_id=unit.evidence_id,
        worksheet_index=unit.unit_index,
        rows=rows,
        blocking_issue_codes=blocking_issue_codes,
        package_issue_codes=package_issue_codes,
        canonical_to_source_columns=canonical_to_source_columns,
        score=(
            int(not blocking_issue_codes),
            int(not package_issue_codes),
            len(rows),
        ),
    )


def _fixed_snapshot_failure(unit, code: str = "roster-unreadable") -> RosterCandidate:
    return _candidate(unit, blocking_issue_codes=(code,))


def _parse_candidate(unit, snapshot: bytes) -> RosterCandidate:
    try:
        physically_nonblank_rows = frozenset(
            worksheet_nonblank_row_indexes(
                snapshot,
                unit.unit_index,
                limits=DEFAULT_INSPECTION_LIMITS,
            )
        )
    except PackageWorkbookError as error:
        if str(error) == "package-workbook-over-limit":
            return _fixed_snapshot_failure(unit, "roster-over-limit")
        return _fixed_snapshot_failure(unit)
    except Exception:
        return _fixed_snapshot_failure(unit)

    workbook = None
    try:
        workbook = load_workbook(
            BytesIO(snapshot), read_only=True, data_only=True, keep_links=False
        )
        worksheets = workbook.worksheets
        if unit.unit_index > len(worksheets):
            return _fixed_snapshot_failure(unit)
        worksheet = worksheets[unit.unit_index - 1]
        header = None
        package_issues = set()
        candidate_rows = []
        cells = 0
        issues = set()
        for row_index, workbook_row in enumerate(worksheet.iter_rows(), start=1):
            if row_index > _MAX_ROWS:
                issues.add("roster-over-limit")
                break
            values = []
            for cell in workbook_row:
                cells += 1
                if cells > _MAX_CELLS:
                    issues.add("roster-over-limit")
                    break
                values.append(_private_cell_text(cell.value))
            if "roster-over-limit" in issues:
                break
            categories = [
                roster_header_categories_from_private_text(value) if value else ()
                for value in values
            ]
            columns = {
                field_name: [
                    index
                    for index, value in enumerate(categories)
                    if field_name in value
                ]
                for field_name in _CANONICAL_ROSTER_FIELDS
            }
            name_columns = columns["name"]
            identity_columns = columns["identity"]
            if header is None and name_columns and identity_columns:
                header = {
                    field_name: (positions[0], values[positions[0]])
                    for field_name, positions in columns.items()
                    if positions
                }
                if any(len(positions) > 1 for positions in columns.values()):
                    package_issues.add("roster-header-duplicate")
                if "faCode" not in header:
                    package_issues.add("roster-fa-code-missing")
                continue
            if header is None or row_index not in physically_nonblank_rows:
                continue
            row_values = {
                field_name: values[index] if index < len(values) else ""
                for field_name, (index, _column_name) in header.items()
            }
            name = row_values.get("name", "")
            identity = row_values.get("identity", "")
            if not name or not identity:
                issues.add("roster-row-invalid")
                continue
            candidate_rows.append(
                RosterCandidateRow(
                    row_index=row_index,
                    name=name,
                    identity=identity,
                    values=tuple(sorted(row_values.items())),
                )
            )
        if header is None:
            issues.add("roster-header-missing")
        if not candidate_rows:
            issues.add("roster-row-invalid")
        if len(candidate_rows) != len({row.identity for row in candidate_rows}):
            issues.add("roster-identity-duplicate")
        fa_codes = {
            dict(row.values).get("faCode", "") for row in candidate_rows
        }
        if not fa_codes or "" in fa_codes:
            package_issues.add("roster-fa-code-blank")
        if len(fa_codes - {""}) > 1:
            package_issues.add("roster-fa-code-conflict")
        source_columns = (
            tuple(
                (field_name, column_name)
                for field_name, (_index, column_name) in sorted(header.items())
            )
            if header is not None
            else ()
        )
        blocking_issue_codes = tuple(
            code for code in _ROSTER_ISSUE_ORDER if code in issues
        )
        return _candidate(
            unit,
            rows=tuple(candidate_rows),
            blocking_issue_codes=blocking_issue_codes,
            package_issue_codes=tuple(sorted(package_issues)),
            canonical_to_source_columns=source_columns,
        )
    except Exception:
        return _fixed_snapshot_failure(unit)
    finally:
        if workbook is not None:
            try:
                workbook.close()
            except Exception:
                pass


def load_roster_candidates(
    inspection: InspectionResult,
    snapshot_source: Callable[..., bytes],
) -> tuple[RosterCandidate, ...]:
    if type(inspection) is not InspectionResult:
        raise TypeError("inspection must be an inspection result")
    if not callable(snapshot_source):
        raise TypeError("snapshot source must be callable")
    sources_by_id = {source.evidence_id: source for source in inspection.sources}
    units = sorted(
        (
            unit
            for unit in inspection.units
            if unit.unit_kind == "worksheet"
            and unit.suggested_role == "payment-roster"
        ),
        key=_numeric_unit_key,
    )
    snapshot_cache: dict[str, bytes | None] = {}
    candidates = []
    for unit in units:
        source = sources_by_id[unit.evidence_id]
        if source.detected_type != "xlsx" or source.inspection_status != "inspected":
            candidates.append(_fixed_snapshot_failure(unit))
            continue
        if unit.evidence_id not in snapshot_cache:
            try:
                snapshot = snapshot_source(
                    unit.evidence_id, max_bytes=_MAX_WORKBOOK_BYTES
                )
            except Exception:
                snapshot = None
            snapshot_cache[unit.evidence_id] = snapshot
        snapshot = snapshot_cache[unit.evidence_id]
        if type(snapshot) is not bytes:
            candidates.append(_fixed_snapshot_failure(unit))
            continue
        candidates.append(_parse_candidate(unit, snapshot))
    return tuple(candidates)


def choose_automatic_roster(
    candidates: tuple[RosterCandidate, ...],
) -> RosterSelection:
    if type(candidates) is not tuple or any(
        type(candidate) is not RosterCandidate for candidate in candidates
    ):
        raise TypeError("candidates must be immutable roster candidates")
    ordered = tuple(sorted(candidates, key=_numeric_unit_key))
    candidate_unit_ids = tuple(candidate.unit_id for candidate in ordered)
    if not ordered:
        return RosterSelection(
            status="missing",
            roster_unit_id=None,
            candidate_unit_ids=(),
            issue_codes=("roster-missing",),
        )
    highest_score = max(candidate.score for candidate in ordered)
    highest = tuple(
        candidate for candidate in ordered if candidate.score == highest_score
    )
    eligible = (
        highest_score[0] == 1
        and highest_score[1] == 1
        and highest_score[2] >= 1
    )
    if not eligible:
        return RosterSelection(
            status="invalid",
            roster_unit_id=None,
            candidate_unit_ids=candidate_unit_ids,
            issue_codes=("roster-invalid",),
        )
    if len(highest) != 1:
        return RosterSelection(
            status="ambiguous",
            roster_unit_id=None,
            candidate_unit_ids=candidate_unit_ids,
            issue_codes=("roster-ambiguous",),
        )
    return RosterSelection(
        status="selected",
        roster_unit_id=highest[0].unit_id,
        candidate_unit_ids=candidate_unit_ids,
        issue_codes=(),
    )
