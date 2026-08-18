"""TDD coverage for deterministic, private-safe proposal grouping."""

from __future__ import annotations

from dataclasses import FrozenInstanceError
import json

import pytest

from ctv_grouping_evidence import GroupingEvidence
from ctv_inspection_model import (
    InspectionResult,
    InspectionSource,
    InspectionTotals,
    InspectionUnit,
)
from ctv_proposal_grouping import (
    ExceptionCluster,
    ExpandedDecision,
    GroupingPlan,
    GroupTarget,
    ReviewGroup,
    SourceException,
    build_grouping_plan,
)
from ctv_proposal_roster import RosterCandidate, RosterCandidateRow


_PRIVATE_NAME = "Nguyễn Văn An"
_PRIVATE_IDENTITY = "079123456781"
_OTHER_PRIVATE_NAME = "Trần Thị Bích"
_OTHER_PRIVATE_IDENTITY = "079123456782"


class _HostileValue:
    def __eq__(self, _other):
        raise AssertionError("hostile equality must not run")

    def __str__(self):
        raise AssertionError("hostile coercion must not run")


def _target(scope="case", participant_handles=()):
    return GroupTarget(scope, participant_handles)


def _group(**overrides):
    values = {
        "group_id": "group-0001",
        "evidence_id": "evidence-0001",
        "unit_kind": "pdf-page",
        "member_unit_ids": ("unit-0001",),
        "first_unit_index": 1,
        "last_unit_index": 1,
        "role": "service-contract",
        "target": _target(),
        "state": "automatically-organized",
        "check_codes": (
            "roster-selected",
            "role-concrete",
            "role-scope-supported",
            "source-range-contiguous",
            "packet-structure-coherent",
            "target-unambiguous",
            "source-issues-clear",
            "unit-issues-clear",
            "coverage-exact",
        ),
        "issue_codes": (),
    }
    values.update(overrides)
    return ReviewGroup(**values)


def _exception(**overrides):
    values = {
        "exception_id": "exception-0001",
        "group_ids": ("group-0001",),
        "member_unit_ids": ("unit-0001",),
        "issue_code": "participant-no-match",
        "recommended_action": "assign",
        "allowed_actions": ("assign", "exclude"),
        "similarity_key": "similarity-0123456789abcdef",
    }
    values.update(overrides)
    return ExceptionCluster(**values)


def _source_exception(**overrides):
    values = {
        "exception_id": "exception-0001",
        "evidence_id": "evidence-0001",
        "issue_code": "source-unreadable",
        "recommended_action": "exclude",
        "allowed_actions": ("exclude",),
        "similarity_key": "similarity-0123456789abcdef",
    }
    values.update(overrides)
    return SourceException(**values)


def _expanded(**overrides):
    values = {
        "unit_id": "unit-0001",
        "decision": "assign",
        "group_id": "group-0001",
        "state": "automatically-organized",
        "role": "service-contract",
        "target": _target(),
        "reason": "",
    }
    values.update(overrides)
    return ExpandedDecision(**values)


def _row(index, name, identity):
    return RosterCandidateRow(
        row_index=index,
        name=name,
        identity=identity,
        values=(
            ("faCode", "FA-SYNTHETIC-001"),
            ("identity", identity),
            ("name", name),
        ),
    )


def _roster(*rows, unit_id="unit-0001", evidence_id="evidence-0001"):
    rows = rows or (_row(2, _PRIVATE_NAME, _PRIVATE_IDENTITY),)
    return RosterCandidate(
        unit_id=unit_id,
        evidence_id=evidence_id,
        worksheet_index=1,
        rows=tuple(rows),
        blocking_issue_codes=(),
        package_issue_codes=(),
        canonical_to_source_columns=(
            ("faCode", "faCode"),
            ("identity", "identity"),
            ("name", "name"),
        ),
        score=(1, 1, len(rows)),
    )


def _unit(
    number,
    evidence_number,
    index,
    role,
    *,
    unit_kind="pdf-page",
    confidence="high",
    signal_codes=(),
    issue_codes=(),
):
    if role == "unknown":
        confidence = "none"
    return InspectionUnit(
        unit_id=f"unit-{number:04d}",
        evidence_id=f"evidence-{evidence_number:04d}",
        unit_kind=unit_kind,
        unit_index=index,
        suggested_role=role,
        confidence_band=confidence,
        needs_user_review=(
            confidence != "high"
            or role == "unknown"
            or bool(issue_codes)
            or "multiple-role-signals" in signal_codes
        ),
        inspection_method={
            "pdf-page": "embedded-text",
            "worksheet": "worksheet-structure",
            "image": "image-structure",
        }[unit_kind],
        signal_codes=signal_codes,
        issue_codes=issue_codes,
    )


def _inspection(units, *, source_overrides=None):
    units = tuple(units)
    source_overrides = source_overrides or {}
    evidence_numbers = sorted(
        {
            *(int(unit.evidence_id.rsplit("-", 1)[1]) for unit in units),
            *source_overrides,
        }
    )
    sources = []
    for evidence_number in evidence_numbers:
        owned = tuple(
            unit
            for unit in units
            if unit.evidence_id == f"evidence-{evidence_number:04d}"
        )
        values = {
            "evidence_id": f"evidence-{evidence_number:04d}",
            "detected_type": (
                "xlsx" if owned and owned[0].unit_kind == "worksheet" else "pdf"
            ),
            "inspection_status": "inspected",
            "unit_count": len(owned),
            "issue_codes": (),
        }
        values.update(source_overrides.get(evidence_number, {}))
        sources.append(InspectionSource(**values))
    issues = sum(len(source.issue_codes) for source in sources) + sum(
        len(unit.issue_codes) for unit in units
    )
    return InspectionResult(
        inspection_version="1.0",
        inspection_status="complete-with-issues" if issues else "complete",
        observation_id="observation-" + "0" * 64,
        totals=InspectionTotals(
            sources=len(sources),
            units=len(units),
            classified=sum(unit.suggested_role != "unknown" for unit in units),
            unknown=sum(unit.suggested_role == "unknown" for unit in units),
            needs_user_review=sum(unit.needs_user_review for unit in units),
            issues=issues,
        ),
        sources=tuple(sources),
        units=units,
    )


def _facts(inspection, private_text_by_unit, *, duplicate_groups=None):
    facts = GroupingEvidence()
    by_id = {unit.unit_id: unit for unit in inspection.units}
    for unit_id, private_text in private_text_by_unit.items():
        unit = by_id[unit_id]
        facts.capture(
            unit.evidence_id,
            unit.unit_kind,
            unit.unit_index,
            private_text,
        )
    for evidence_id, duplicate_group_id in (duplicate_groups or {}).items():
        facts.capture_source_duplicate(evidence_id, duplicate_group_id)
    return facts


def test_grouping_model_records_are_frozen_and_private_safe():
    target = _target("individual", ("participant-0001",))
    group = _group(
        target=target,
        check_codes=(
            "roster-selected",
            "participant-name-match",
            "participant-identity-match",
            "role-concrete",
            "role-scope-supported",
            "source-range-contiguous",
            "packet-structure-coherent",
            "target-unambiguous",
            "source-issues-clear",
            "unit-issues-clear",
            "coverage-exact",
        ),
    )
    decision = _expanded(target=target)

    for record in (target, group, _exception(), _source_exception(), decision):
        with pytest.raises(FrozenInstanceError):
            record.extra = "forbidden"
        rendered = repr(record)
        assert _PRIVATE_NAME not in rendered
        assert _PRIVATE_IDENTITY not in rendered


@pytest.mark.parametrize(
    "factory,overrides",
    [
        (_target, {"scope": _HostileValue()}),
        (_target, {"participant_handles": ["participant-0001"]}),
        (_group, {"group_id": _HostileValue()}),
        (_group, {"member_unit_ids": ["unit-0001"]}),
        (_group, {"first_unit_index": True}),
        (_group, {"target": _HostileValue()}),
        (_group, {"check_codes": ["coverage-exact"]}),
        (_exception, {"group_ids": ["group-0001"]}),
        (_exception, {"allowed_actions": ["assign"]}),
        (_source_exception, {"evidence_id": _HostileValue()}),
        (_expanded, {"unit_id": _HostileValue()}),
        (_expanded, {"target": _HostileValue()}),
    ],
    ids=(
        "target-hostile-scope",
        "target-list-handles",
        "group-hostile-id",
        "group-list-members",
        "group-bool-index",
        "group-hostile-target",
        "group-list-checks",
        "exception-list-groups",
        "exception-list-actions",
        "source-hostile-evidence",
        "decision-hostile-unit",
        "decision-hostile-target",
    ),
)
def test_grouping_model_requires_exact_builtin_types(factory, overrides):
    with pytest.raises((TypeError, ValueError)):
        factory(**overrides)


@pytest.mark.parametrize(
    "factory,overrides",
    [
        (_target, {"scope": "private-scope"}),
        (_target, {"scope": "case", "participant_handles": ("participant-0001",)}),
        (_target, {"scope": "individual", "participant_handles": ()}),
        (_group, {"unit_kind": "private-kind"}),
        (_group, {"role": "unknown"}),
        (_group, {"role": "identity-front", "target": _target()}),
        (_group, {"state": "private-state"}),
        (_group, {"check_codes": ("coverage-exact", "role-concrete")}),
        (_exception, {"issue_code": "private-issue"}),
        (_exception, {"recommended_action": "private-action"}),
        (_exception, {"similarity_key": _PRIVATE_NAME}),
        (_source_exception, {"issue_code": "participant-no-match"}),
    ],
    ids=(
        "unknown-scope",
        "case-with-participant",
        "individual-without-participant",
        "unknown-kind",
        "unknown-role",
        "unsupported-role-scope",
        "unknown-state",
        "unordered-checks",
        "unknown-issue",
        "unknown-action",
        "private-similarity",
        "unit-issue-on-source",
    ),
)
def test_grouping_model_rejects_unsupported_or_private_values(factory, overrides):
    with pytest.raises(ValueError):
        factory(**overrides)


def test_grouping_model_expanded_decisions_enforce_closed_shapes():
    assert _expanded(
        decision="exclude",
        group_id=None,
        role="",
        target=None,
        reason="duplicate",
    ).reason == "duplicate"
    assert _expanded(
        decision="unresolved",
        state="exception",
        role="",
        target=None,
        reason="",
    ).decision == "unresolved"

    invalid = (
        {"decision": "private-decision"},
        {"decision": "assign", "group_id": None},
        {"decision": "assign", "reason": "duplicate"},
        {
            "decision": "exclude",
            "group_id": None,
            "role": "service-contract",
            "target": None,
            "reason": "duplicate",
        },
        {
            "decision": "exclude",
            "group_id": None,
            "state": "exception",
            "role": "",
            "target": None,
            "reason": "duplicate",
        },
        {
            "decision": "exclude",
            "group_id": None,
            "role": "",
            "target": None,
            "reason": "other",
        },
        {
            "decision": "unresolved",
            "state": "automatically-organized",
            "role": "",
            "target": None,
            "reason": "",
        },
    )
    for overrides in invalid:
        with pytest.raises(ValueError):
            _expanded(**overrides)


def test_grouping_model_requires_stable_unique_ids_and_numeric_order():
    with pytest.raises(ValueError, match="groups must use canonical ordered IDs"):
        GroupingPlan(
            roster_unit_id="unit-0001",
            groups=(_group(group_id="group-0002"),),
            exceptions=(),
            source_exceptions=(),
            expected_unit_ids=("unit-0001",),
        )
    with pytest.raises(ValueError, match="expected unit IDs must be unique and ordered"):
        GroupingPlan(
            roster_unit_id="unit-0001",
            groups=(_group(),),
            exceptions=(),
            source_exceptions=(),
            expected_unit_ids=("unit-0002", "unit-0001"),
        )


def test_grouping_model_rejects_canonical_ids_attached_to_out_of_order_records():
    with pytest.raises(ValueError, match="groups must follow canonical source/unit order"):
        GroupingPlan(
            roster_unit_id="unit-0001",
            groups=(
                _group(
                    group_id="group-0001",
                    evidence_id="evidence-0002",
                    member_unit_ids=("unit-0002",),
                ),
                _group(
                    group_id="group-0002",
                    evidence_id="evidence-0001",
                    member_unit_ids=("unit-0001",),
                ),
            ),
            exceptions=(),
            source_exceptions=(),
            expected_unit_ids=("unit-0001", "unit-0002"),
        )

    with pytest.raises(ValueError, match="source exceptions must be ordered"):
        GroupingPlan(
            roster_unit_id="unit-0001",
            groups=(_group(),),
            exceptions=(),
            source_exceptions=(
                _source_exception(
                    exception_id="exception-0001",
                    evidence_id="evidence-0003",
                ),
                _source_exception(
                    exception_id="exception-0002",
                    evidence_id="evidence-0002",
                ),
            ),
            expected_unit_ids=("unit-0001",),
        )

    with pytest.raises(ValueError, match="automatic exclusions must be ordered"):
        GroupingPlan(
            roster_unit_id="unit-0001",
            groups=(_group(),),
            exceptions=(),
            source_exceptions=(),
            expected_unit_ids=("unit-0001", "unit-0002", "unit-0003"),
            automatic_exclusions=(
                _expanded(
                    unit_id="unit-0003",
                    decision="exclude",
                    group_id=None,
                    role="",
                    target=None,
                    reason="duplicate",
                ),
                _expanded(
                    unit_id="unit-0002",
                    decision="exclude",
                    group_id=None,
                    role="",
                    target=None,
                    reason="duplicate",
                ),
            ),
        )


def test_plan_requires_exactly_once_unit_coverage():
    with pytest.raises(ValueError, match="group coverage must equal inspection units"):
        GroupingPlan(
            roster_unit_id="unit-0001",
            groups=(
                _group(member_unit_ids=("unit-0001", "unit-0001"), last_unit_index=2),
            ),
            exceptions=(),
            source_exceptions=(),
            expected_unit_ids=("unit-0001",),
        )


def test_grouping_model_rejects_duplicate_members_at_the_record_boundary():
    with pytest.raises(ValueError, match="group coverage must equal inspection units"):
        _group(
            member_unit_ids=("unit-0001", "unit-0001"),
            last_unit_index=2,
        )


def test_grouping_model_bounds_each_exception_cluster_projection():
    with pytest.raises(ValueError, match="exception cluster exceeds hard limit"):
        _exception(
            group_ids=tuple(f"group-{index:04d}" for index in range(1, 10_002)),
        )


def test_plan_rejects_missing_unit_coverage():
    with pytest.raises(ValueError, match="group coverage must equal inspection units"):
        GroupingPlan(
            roster_unit_id="unit-0001",
            groups=(_group(),),
            exceptions=(),
            source_exceptions=(),
            expected_unit_ids=("unit-0001", "unit-0002"),
        )


def test_plan_coverage_may_use_one_automatic_exclusion():
    plan = GroupingPlan(
        roster_unit_id="unit-0001",
        groups=(_group(),),
        exceptions=(),
        source_exceptions=(),
        expected_unit_ids=("unit-0001", "unit-0002"),
        automatic_exclusions=(
            _expanded(
                unit_id="unit-0002",
                decision="exclude",
                group_id=None,
                role="",
                target=None,
                reason="duplicate",
            ),
        ),
    )

    assert plan.covered_unit_ids == ("unit-0001", "unit-0002")
    assert tuple(item.decision for item in plan.expand()) == ("assign", "exclude")


def test_plan_coverage_requires_exception_groups_to_match_clusters():
    failed_group = _group(
        state="exception",
        check_codes=("roster-selected", "coverage-exact"),
        issue_codes=("participant-no-match",),
    )
    with pytest.raises(ValueError, match="exception groups must match clusters"):
        GroupingPlan(
            roster_unit_id="unit-0001",
            groups=(failed_group,),
            exceptions=(),
            source_exceptions=(),
            expected_unit_ids=("unit-0001",),
        )


def test_grouping_model_enforces_group_and_exception_bounds():
    group = _group()
    with pytest.raises(ValueError, match="group count exceeds hard limit"):
        GroupingPlan(
            roster_unit_id="unit-0001",
            groups=(group,) * 10_001,
            exceptions=(),
            source_exceptions=(),
            expected_unit_ids=("unit-0001",),
        )
    with pytest.raises(ValueError, match="exception count exceeds hard limit"):
        GroupingPlan(
            roster_unit_id="unit-0001",
            groups=(group,),
            exceptions=(_exception(),) * 10_001,
            source_exceptions=(),
            expected_unit_ids=("unit-0001",),
        )


def test_grouping_model_digest_input_is_canonical_private_safe_json_bytes():
    plan = GroupingPlan(
        roster_unit_id="unit-0001",
        groups=(_group(),),
        exceptions=(),
        source_exceptions=(),
        expected_unit_ids=("unit-0001",),
    )

    payload = plan.to_digest_input()

    assert type(payload) is bytes
    assert json.loads(payload) == {
        "automaticExclusions": [],
        "coveredUnitIds": ["unit-0001"],
        "exceptions": [],
        "groups": [
            {
                "checkCodes": [
                    "roster-selected",
                    "role-concrete",
                    "role-scope-supported",
                    "source-range-contiguous",
                    "packet-structure-coherent",
                    "target-unambiguous",
                    "source-issues-clear",
                    "unit-issues-clear",
                    "coverage-exact",
                ],
                "evidenceId": "evidence-0001",
                "firstUnitIndex": 1,
                "groupId": "group-0001",
                "issueCodes": [],
                "lastUnitIndex": 1,
                "memberUnitIds": ["unit-0001"],
                "role": "service-contract",
                "state": "automatically-organized",
                "target": {"participantHandles": [], "scope": "case"},
                "unitKind": "pdf-page",
            }
        ],
        "rosterUnitId": "unit-0001",
        "sourceExceptions": [],
    }
    assert _PRIVATE_NAME.encode() not in payload
    assert _PRIVATE_IDENTITY.encode() not in payload


def test_matching_requires_exact_full_name_and_identity_for_one_roster_row():
    inspection = _inspection(
        (
            _unit(1, 1, 1, "payment-roster", unit_kind="worksheet"),
            _unit(2, 2, 1, "service-contract"),
        )
    )
    roster = _roster()
    facts = _facts(
        inspection,
        {
            "unit-0001": "payment roster",
            "unit-0002": f"Contract for {_PRIVATE_NAME}; ID {_PRIVATE_IDENTITY}",
        },
    )

    plan = build_grouping_plan(inspection, roster, facts)

    assert tuple(group.member_unit_ids for group in plan.groups) == (
        ("unit-0001",),
        ("unit-0002",),
    )
    assert plan.groups[0].target == GroupTarget("case", ())
    assert plan.groups[1].target == GroupTarget(
        "individual", ("participant-0001",)
    )
    assert plan.groups[1].check_codes == (
        "roster-selected",
        "participant-name-match",
        "participant-identity-match",
        "role-concrete",
        "role-scope-supported",
        "source-range-contiguous",
        "packet-structure-coherent",
        "target-unambiguous",
        "source-issues-clear",
        "unit-issues-clear",
        "coverage-exact",
    )
    assert plan.exceptions == ()


def test_matching_one_sided_zero_conflicting_and_multiple_facts_are_exceptions():
    inspection = _inspection(
        (
            _unit(1, 1, 1, "payment-roster", unit_kind="worksheet"),
            _unit(2, 2, 1, "identity-front"),
            _unit(3, 2, 2, "identity-front"),
            _unit(4, 2, 3, "identity-front"),
            _unit(5, 2, 4, "identity-front"),
            _unit(6, 2, 5, "identity-front"),
        )
    )
    roster = _roster(
        _row(2, _PRIVATE_NAME, _PRIVATE_IDENTITY),
        _row(3, _OTHER_PRIVATE_NAME, _OTHER_PRIVATE_IDENTITY),
    )
    facts = _facts(
        inspection,
        {
            "unit-0001": "payment roster",
            "unit-0002": _PRIVATE_NAME,
            "unit-0003": _PRIVATE_IDENTITY,
            "unit-0004": "identity document without roster facts",
            "unit-0005": (
                f"{_PRIVATE_NAME} {_PRIVATE_IDENTITY} "
                f"{_OTHER_PRIVATE_NAME} {_OTHER_PRIVATE_IDENTITY}"
            ),
            "unit-0006": f"{_PRIVATE_NAME} {_OTHER_PRIVATE_IDENTITY}",
        },
    )

    plan = build_grouping_plan(inspection, roster, facts)

    assert tuple(item.member_unit_ids for item in plan.exceptions) == (
        ("unit-0002",),
        ("unit-0003",),
        ("unit-0004",),
        ("unit-0005",),
        ("unit-0006",),
    )
    assert tuple(item.issue_code for item in plan.exceptions) == (
        "participant-name-only",
        "participant-identity-only",
        "participant-no-match",
        "participant-multiple-match",
        "participant-identity-conflict",
    )
    assert tuple(item.decision for item in plan.expand()) == (
        "assign",
        "unresolved",
        "unresolved",
        "unresolved",
        "unresolved",
        "unresolved",
    )


def test_segment_starts_at_participant_anchor_and_stops_before_the_next_anchor():
    inspection = _inspection(
        (
            _unit(1, 1, 1, "payment-roster", unit_kind="worksheet"),
            _unit(2, 2, 1, "service-contract"),
            _unit(3, 2, 2, "service-contract"),
            _unit(4, 2, 3, "acceptance-record"),
            _unit(5, 2, 4, "unknown"),
            _unit(6, 2, 5, "acceptance-record"),
            _unit(7, 2, 6, "service-contract"),
            _unit(8, 2, 7, "service-contract"),
            _unit(9, 2, 8, "unknown"),
        )
    )
    roster = _roster(
        _row(2, _PRIVATE_NAME, _PRIVATE_IDENTITY),
        _row(3, _OTHER_PRIVATE_NAME, _OTHER_PRIVATE_IDENTITY),
    )
    facts = _facts(
        inspection,
        {
            "unit-0001": "payment roster",
            "unit-0002": "case service contract opening",
            "unit-0003": "case service contract terms",
            "unit-0004": f"{_PRIVATE_NAME} {_PRIVATE_IDENTITY} acceptance",
            "unit-0005": "acceptance continuation",
            "unit-0006": "acceptance signature",
            "unit-0007": (
                f"{_OTHER_PRIVATE_NAME} {_OTHER_PRIVATE_IDENTITY} contract"
            ),
            "unit-0008": "contract continuation",
            "unit-0009": "unclassified trailing page",
        },
    )

    plan = build_grouping_plan(inspection, roster, facts)

    assert tuple(group.member_unit_ids for group in plan.groups) == (
        ("unit-0001",),
        ("unit-0002", "unit-0003"),
        ("unit-0004", "unit-0005", "unit-0006"),
        ("unit-0007", "unit-0008"),
        ("unit-0009",),
    )
    assert plan.groups[1].target == GroupTarget("case", ())
    assert plan.groups[2].target == GroupTarget(
        "individual", ("participant-0001",)
    )
    assert plan.groups[3].target == GroupTarget(
        "individual", ("participant-0002",)
    )
    assert plan.exceptions[0].member_unit_ids == ("unit-0009",)
    assert plan.exceptions[0].issue_code == "role-uncertain"


def test_segment_unknown_gap_propagates_only_between_compatible_role_anchors():
    inspection = _inspection(
        (
            _unit(1, 1, 1, "payment-roster", unit_kind="worksheet"),
            _unit(2, 2, 1, "service-contract"),
            _unit(3, 2, 2, "unknown"),
            _unit(4, 2, 3, "unknown"),
            _unit(5, 2, 4, "acceptance-record"),
        )
    )
    roster = _roster()
    facts = _facts(
        inspection,
        {
            "unit-0001": "payment roster",
            "unit-0002": f"{_PRIVATE_NAME} {_PRIVATE_IDENTITY} contract",
            "unit-0003": "unknown middle one",
            "unit-0004": "unknown middle two",
            "unit-0005": "acceptance signature",
        },
    )

    plan = build_grouping_plan(inspection, roster, facts)

    assert tuple(group.member_unit_ids for group in plan.groups) == (
        ("unit-0001",),
        ("unit-0002",),
        ("unit-0003", "unit-0004"),
        ("unit-0005",),
    )
    assert plan.exceptions[0].member_unit_ids == ("unit-0003", "unit-0004")
    assert plan.exceptions[0].issue_code == "role-gap-conflict"


def test_segment_single_case_anchor_propagates_to_trailing_source_end():
    inspection = _inspection(
        (
            _unit(1, 1, 1, "payment-roster", unit_kind="worksheet"),
            _unit(2, 2, 1, "service-contract"),
            _unit(3, 2, 2, "unknown"),
            _unit(4, 2, 3, "unknown"),
        )
    )
    roster = _roster()
    facts = _facts(
        inspection,
        {
            "unit-0001": "payment roster",
            "unit-0002": "whole case contract",
            "unit-0003": "continuation terms",
            "unit-0004": "continuation signatures",
        },
    )

    plan = build_grouping_plan(inspection, roster, facts)

    assert plan.groups[1].member_unit_ids == (
        "unit-0002",
        "unit-0003",
        "unit-0004",
    )
    assert plan.groups[1].role == "service-contract"
    assert plan.groups[1].target == GroupTarget("case", ())
    assert plan.exceptions == ()


def test_segment_incomplete_fact_is_the_smallest_safe_exception():
    inspection = _inspection(
        (
            _unit(1, 1, 1, "payment-roster", unit_kind="worksheet"),
            _unit(2, 2, 1, "service-contract"),
            _unit(3, 2, 2, "service-contract"),
            _unit(4, 2, 3, "service-contract"),
        )
    )
    roster = _roster()
    facts = _facts(
        inspection,
        {
            "unit-0001": "payment roster",
            "unit-0002": "case contract opening",
            "unit-0004": "case contract signature",
        },
    )

    plan = build_grouping_plan(inspection, roster, facts)

    assert tuple(group.member_unit_ids for group in plan.groups) == (
        ("unit-0001",),
        ("unit-0002",),
        ("unit-0003",),
        ("unit-0004",),
    )
    assert plan.exceptions[0].member_unit_ids == ("unit-0003",)
    assert plan.exceptions[0].issue_code == "private-fact-incomplete"


def test_shared_contracts_and_policies_are_represented_once_at_case_scope():
    inspection = _inspection(
        (
            _unit(1, 1, 1, "payment-roster", unit_kind="worksheet"),
            _unit(2, 2, 1, "shared-supporting-evidence"),
            _unit(3, 2, 2, "shared-supporting-evidence"),
        )
    )
    roster = _roster(
        _row(2, _PRIVATE_NAME, _PRIVATE_IDENTITY),
        _row(3, _OTHER_PRIVATE_NAME, _OTHER_PRIVATE_IDENTITY),
    )
    facts = _facts(
        inspection,
        {
            "unit-0001": "payment roster",
            "unit-0002": "whole case policy",
            "unit-0003": "whole case policy continuation",
        },
    )

    plan = build_grouping_plan(inspection, roster, facts)

    assert plan.groups[1].member_unit_ids == ("unit-0002", "unit-0003")
    assert plan.groups[1].target == GroupTarget("case", ())
    assert plan.groups[1].role == "shared-supporting-evidence"
    assert plan.exceptions == ()


def test_duplicate_facts_keep_first_source_and_exclude_later_exact_units():
    inspection = _inspection(
        (
            _unit(1, 1, 1, "payment-roster", unit_kind="worksheet"),
            _unit(2, 2, 1, "service-contract"),
            _unit(3, 3, 1, "service-contract"),
        )
    )
    roster = _roster()
    facts = _facts(
        inspection,
        {
            "unit-0001": "payment roster",
            "unit-0002": "canonical contract",
        },
        duplicate_groups={
            "evidence-0002": "duplicate-0007",
            "evidence-0003": "duplicate-0007",
        },
    )

    plan = build_grouping_plan(inspection, roster, facts)

    assert tuple(group.member_unit_ids for group in plan.groups) == (
        ("unit-0001",),
        ("unit-0002",),
    )
    assert tuple(item.unit_id for item in plan.automatic_exclusions) == (
        "unit-0003",
    )
    assert plan.automatic_exclusions[0].reason == "duplicate"
    assert tuple(item.decision for item in plan.expand()) == (
        "assign",
        "assign",
        "exclude",
    )


def test_duplicate_semantic_similarity_never_creates_automatic_exclusion():
    inspection = _inspection(
        (
            _unit(1, 1, 1, "payment-roster", unit_kind="worksheet"),
            _unit(2, 2, 1, "service-contract"),
            _unit(3, 3, 1, "service-contract"),
        )
    )
    roster = _roster()
    same_text = "visually and semantically similar contract"
    facts = _facts(
        inspection,
        {
            "unit-0001": "payment roster",
            "unit-0002": same_text,
            "unit-0003": same_text,
        },
    )

    plan = build_grouping_plan(inspection, roster, facts)

    assert tuple(group.member_unit_ids for group in plan.groups) == (
        ("unit-0001",),
        ("unit-0002",),
        ("unit-0003",),
    )
    assert plan.automatic_exclusions == ()


def test_source_exception_records_unreadable_and_unsupported_sources_once():
    inspection = _inspection(
        (_unit(1, 1, 1, "payment-roster", unit_kind="worksheet"),),
        source_overrides={
            2: {
                "detected_type": "pdf",
                "inspection_status": "unreadable",
                "unit_count": None,
                "issue_codes": ("document-unreadable",),
            },
            3: {
                "detected_type": "unknown",
                "inspection_status": "unsupported",
                "unit_count": 0,
                "issue_codes": ("unsupported-document-type",),
            },
        },
    )
    roster = _roster()
    facts = _facts(inspection, {"unit-0001": "payment roster"})

    plan = build_grouping_plan(inspection, roster, facts)

    assert tuple(item.evidence_id for item in plan.source_exceptions) == (
        "evidence-0002",
        "evidence-0003",
    )
    assert tuple(item.issue_code for item in plan.source_exceptions) == (
        "source-unreadable",
        "source-unsupported",
    )
    assert tuple(item.exception_id for item in plan.source_exceptions) == (
        "exception-0001",
        "exception-0002",
    )


def test_grouping_fixture_is_deterministic_bytes_across_repeated_builds():
    inspection = _inspection(
        (
            _unit(3, 2, 2, "acceptance-record"),
            _unit(1, 1, 1, "payment-roster", unit_kind="worksheet"),
            _unit(2, 2, 1, "acceptance-record"),
        )
    )
    roster = _roster()
    facts = _facts(
        inspection,
        {
            "unit-0001": "payment roster",
            "unit-0002": f"{_PRIVATE_NAME} {_PRIVATE_IDENTITY} acceptance",
            "unit-0003": "acceptance continuation",
        },
    )

    first = build_grouping_plan(inspection, roster, facts)
    second = build_grouping_plan(inspection, roster, facts)

    assert first.to_digest_input() == second.to_digest_input()
    assert first.to_digest_input() == bytes(first.to_digest_input())


def test_confidence_alone_never_overrides_conflicting_role_signals():
    inspection = _inspection(
        (
            _unit(1, 1, 1, "payment-roster", unit_kind="worksheet"),
            _unit(
                2,
                2,
                1,
                "service-contract",
                signal_codes=("multiple-role-signals",),
            ),
        )
    )
    roster = _roster()
    facts = _facts(
        inspection,
        {
            "unit-0001": "payment roster",
            "unit-0002": f"{_PRIVATE_NAME} {_PRIVATE_IDENTITY} ambiguous role",
        },
    )

    plan = build_grouping_plan(inspection, roster, facts)

    assert plan.exceptions[0].member_unit_ids == ("unit-0002",)
    assert plan.exceptions[0].issue_code == "role-uncertain"
    assert plan.expand()[1].decision == "unresolved"


def test_fixed_eligibility_checks_block_source_unit_and_role_uncertainty():
    inspection = _inspection(
        (
            _unit(1, 1, 1, "payment-roster", unit_kind="worksheet"),
            _unit(2, 2, 1, "service-contract"),
            _unit(
                3,
                3,
                1,
                "service-contract",
                issue_codes=("classification-conflict",),
            ),
            _unit(4, 4, 1, "service-contract", confidence="medium"),
        ),
        source_overrides={
            2: {"issue_codes": ("classification-conflict",)},
        },
    )
    roster = _roster()
    facts = _facts(
        inspection,
        {
            "unit-0001": "payment roster",
            "unit-0002": f"{_PRIVATE_NAME} {_PRIVATE_IDENTITY} source issue",
            "unit-0003": f"{_PRIVATE_NAME} {_PRIVATE_IDENTITY} unit issue",
            "unit-0004": f"{_PRIVATE_NAME} {_PRIVATE_IDENTITY} uncertain role",
        },
    )

    plan = build_grouping_plan(inspection, roster, facts)

    assert tuple(item.issue_code for item in plan.exceptions) == (
        "source-issue-present",
        "unit-issue-present",
        "role-uncertain",
    )
    assert tuple(item.member_unit_ids for item in plan.exceptions) == (
        ("unit-0002",),
        ("unit-0003",),
        ("unit-0004",),
    )
