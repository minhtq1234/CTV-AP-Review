import copy

import pytest

from ctv_inspection_model import InspectionResult, InspectionSource, InspectionTotals, InspectionUnit
from ctv_proposal_model import AssignmentTarget, Participant, SourceDisposition, UnitDecision
from ctv_proposal_validator import (
    approve_proposal,
    canonical_approval_payload,
    proposal_digest,
    validate_proposal,
)


def _unit(**overrides):
    values = dict(
        unit_id="unit-0001", evidence_id="evidence-0001", unit_kind="worksheet",
        unit_index=1, suggested_role="payment-roster", confidence_band="high",
        needs_user_review=False, inspection_method="worksheet-structure",
        signal_codes=("roster-column-pattern",), issue_codes=(),
    )
    values.update(overrides)
    return InspectionUnit(**values)


def _inspection():
    units = (
        _unit(),
        _unit(
            unit_id="unit-0002", evidence_id="evidence-0002", unit_kind="image",
            suggested_role="identity-front", inspection_method="image-structure",
            signal_codes=("identity-front-layout",),
        ),
    )
    sources = (
        InspectionSource("evidence-0001", "xlsx", "inspected", 1, ()),
        InspectionSource("evidence-0002", "image", "inspected", 1, ()),
        InspectionSource("evidence-0003", "zip", "opaque", 0, ("opaque-archive",)),
    )
    return InspectionResult(
        "1.0", "complete-with-issues", "observation-" + "a" * 64,
        InspectionTotals(3, 2, 2, 0, 0, 1), sources, units,
    )


def _participants():
    return (Participant("participant-0001"), Participant("participant-0002"))


def _resolved(*, accepted_role="payment-roster", target=None):
    target = AssignmentTarget("individual", ("participant-0001",)) if target is None else target
    return (
        (SourceDisposition("evidence-0003", "excluded", "irrelevant"),),
        (
            UnitDecision("unit-0001", "accepted", accepted_role, target, None),
            UnitDecision(
                "unit-0002", "accepted", "identity-front",
                AssignmentTarget("individual", ("participant-0001",)), None,
            ),
        ),
    )


def test_validation_accounts_for_every_unit_and_source_only_record_once():
    result = validate_proposal(
        inspection=_inspection(), participants=_participants(), roster_unit_id="unit-0001",
        source_dispositions=(), unit_decisions=(),
    )
    assert result.ready_to_prepare is False
    assert result.totals.unresolved == 3
    assert result.issue_codes == ("proposal-unresolved",)


@pytest.mark.parametrize(
    "roster_unit_id",
    [None, "unit-0002", "unit-9999"],
)
def test_validation_requires_a_current_roster_worksheet_with_roster_signal(roster_unit_id):
    source_dispositions, decisions = _resolved()
    result = validate_proposal(_inspection(), _participants(), roster_unit_id, source_dispositions, decisions)
    assert result.ready_to_prepare is False
    assert result.issue_codes == ("proposal-unresolved",)


def test_validation_rejects_missing_duplicate_and_foreign_identifiers_as_unresolved():
    source_dispositions, decisions = _resolved()
    result = validate_proposal(
        _inspection(), _participants(), "unit-0001",
        source_dispositions + (SourceDisposition("evidence-0003", "excluded", "duplicate"),),
        decisions[:-1] + (UnitDecision("unit-9999", "excluded", None, None, "irrelevant"),),
    )
    assert result.ready_to_prepare is False
    assert result.totals.unresolved == 1
    assert result.issue_codes == ("proposal-unresolved",)


def test_validation_rejects_target_handles_that_are_not_distinct_roster_ordered_members():
    source_dispositions, decisions = _resolved(
        target=AssignmentTarget("individual", ("participant-0002",))
    )
    result = validate_proposal(
        _inspection(), (Participant("participant-0002"), Participant("participant-0001")), "unit-0001", source_dispositions,
        decisions[:-1] + (
            UnitDecision(
                "unit-0002", "accepted", "identity-front",
                AssignmentTarget("shared", ("participant-0001", "participant-0002")), None,
            ),
        ),
    )
    assert result.ready_to_prepare is False
    assert result.totals.unresolved == 1


def test_validation_rejects_role_not_allowed_for_the_unit_kind():
    source_dispositions, decisions = _resolved()
    result = validate_proposal(
        _inspection(), _participants(), "unit-0001", source_dispositions,
        decisions[:-1] + (
            UnitDecision(
                "unit-0002", "reassigned", "service-contract",
                AssignmentTarget("case", ()), None,
            ),
        ),
    )
    assert result.ready_to_prepare is False
    assert result.totals.unresolved == 1


@pytest.mark.parametrize(
    "decision, role",
    [("accepted", "identity-front"), ("reassigned", "payment-roster")],
)
def test_validation_requires_accepted_to_match_and_reassigned_to_differ(decision, role):
    source_dispositions, decisions = _resolved()
    result = validate_proposal(
        _inspection(), _participants(), "unit-0001", source_dispositions,
        (UnitDecision("unit-0001", decision, role, AssignmentTarget("case", ()), None),) + decisions[1:],
    )
    assert result.ready_to_prepare is False
    assert result.totals.unresolved == 1


def test_unresolved_source_or_unit_blocks_readiness():
    source_dispositions, decisions = _resolved()
    result = validate_proposal(
        _inspection(), _participants(), "unit-0001",
        (SourceDisposition("evidence-0003", "unresolved", None),), decisions,
    )
    assert result.ready_to_prepare is False
    assert result.totals.unresolved == 1


def test_validation_requires_at_least_one_participant_and_a_resolved_source_only_record():
    source_dispositions, decisions = _resolved()
    no_people = validate_proposal(_inspection(), (), "unit-0001", source_dispositions, decisions)
    missing_source = validate_proposal(_inspection(), _participants(), "unit-0001", (), decisions)
    assert no_people.ready_to_prepare is False
    assert missing_source.totals.unresolved == 1


def test_validation_canonicalizes_to_inspection_order_regardless_of_caller_order():
    source_dispositions, decisions = _resolved()
    result = validate_proposal(
        _inspection(), _participants(), "unit-0001", tuple(reversed(source_dispositions)), tuple(reversed(decisions))
    )
    assert [decision.unit_id for decision in result.unit_decisions] == ["unit-0001", "unit-0002"]
    assert [disposition.evidence_id for disposition in result.source_dispositions] == ["evidence-0003"]
    assert result.ready_to_prepare is True


def test_digest_changes_for_each_mutable_approval_field_and_excludes_private_labels_or_notes():
    source_dispositions, decisions = _resolved()
    validation = validate_proposal(_inspection(), _participants(), "unit-0001", source_dispositions, decisions)
    baseline = proposal_digest(validation)
    assert baseline.startswith("proposal-")
    payload = canonical_approval_payload(validation)
    assert "label" not in repr(payload).lower()
    assert "note" not in repr(payload).lower()

    changed_participants = validate_proposal(
        _inspection(), (Participant("participant-0002"), Participant("participant-0001")), "unit-0001", source_dispositions, decisions
    )
    changed_target = validate_proposal(
        _inspection(), _participants(), "unit-0001", source_dispositions,
        decisions[:-1] + (UnitDecision("unit-0002", "accepted", "identity-front", AssignmentTarget("individual", ("participant-0002",)), None),),
    )
    changed_decision = validate_proposal(
        _inspection(), _participants(), "unit-0001", (SourceDisposition("evidence-0003", "excluded", "duplicate"),), decisions
    )
    assert {proposal_digest(changed_participants), proposal_digest(changed_target), proposal_digest(changed_decision)}.isdisjoint({baseline})


def test_approval_requires_ready_validation_and_exact_digest():
    source_dispositions, decisions = _resolved()
    validation = validate_proposal(_inspection(), _participants(), "unit-0001", source_dispositions, decisions)
    approved = approve_proposal(validation, proposal_digest(validation))
    assert approved.to_dict()["outcome"] == "approved"
    with pytest.raises(ValueError):
        approve_proposal(validation, "proposal-" + "b" * 64)
    unresolved = validate_proposal(_inspection(), _participants(), "unit-0001", (), ())
    with pytest.raises(ValueError):
        approve_proposal(unresolved, proposal_digest(unresolved))
