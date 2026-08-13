import dataclasses

import pytest

from ctv_proposal_model import (
    ApprovedProposal,
    AssignmentTarget,
    CancelledProposal,
    DraftProposal,
    Participant,
    ProposalDraftState,
    ProposalTotals,
    SourceDisposition,
    UnitDecision,
)


def _totals(**overrides):
    values = dict(
        sources=3, source_only=1, participants=2, units=2, accepted=1,
        reassigned=0, excluded=1, unresolved=0, issues=0,
    )
    values.update(overrides)
    return ProposalTotals(**values)


def _digest():
    return "proposal-" + "a" * 64


def _observation_id():
    return "observation-" + "a" * 64


def test_shared_target_requires_two_distinct_handles_in_roster_order():
    with pytest.raises(ValueError):
        AssignmentTarget("shared", ("participant-0001",))
    with pytest.raises(ValueError):
        AssignmentTarget("shared", ("participant-0002", "participant-0001"))
    assert AssignmentTarget(
        "shared", ("participant-0001", "participant-0002")
    ).to_dict() == {
        "scope": "shared",
        "participantHandles": ["participant-0001", "participant-0002"],
    }


def test_unknown_role_cannot_be_resolved_or_approved():
    with pytest.raises(ValueError):
        UnitDecision(
            unit_id="unit-0001", decision="accepted", role="unknown",
            target=AssignmentTarget("case", ()), exclusion_reason=None,
        )


def test_decision_serialization_uses_exact_conditional_public_shapes():
    accepted = UnitDecision(
        "unit-0001", "accepted", "service-contract", AssignmentTarget("case", ()), None
    )
    excluded = UnitDecision("unit-0002", "excluded", None, None, "irrelevant")
    unresolved = UnitDecision("unit-0003", "unresolved", None, None, None)
    assert accepted.to_dict() == {
        "unitId": "unit-0001", "decision": "accepted", "role": "service-contract",
        "target": {"scope": "case", "participantHandles": []},
    }
    assert excluded.to_dict() == {
        "unitId": "unit-0002", "decision": "excluded", "exclusionReason": "irrelevant",
    }
    assert unresolved.to_dict() == {"unitId": "unit-0003", "decision": "unresolved"}
    with pytest.raises(ValueError):
        UnitDecision.from_dict({
            "unitId": "unit-0003", "decision": "unresolved", "role": None,
            "target": None, "exclusionReason": None,
        })


def test_source_disposition_serialization_uses_exact_conditional_public_shapes():
    assert SourceDisposition("evidence-0001", "excluded", "irrelevant").to_dict() == {
        "evidenceId": "evidence-0001", "decision": "excluded", "exclusionReason": "irrelevant",
    }
    assert SourceDisposition("evidence-0002", "unresolved", None).to_dict() == {
        "evidenceId": "evidence-0002", "decision": "unresolved",
    }


@pytest.mark.parametrize(
    "decision, role, target, exclusion_reason",
    [
        ("accepted", None, None, None),
        ("reassigned", None, None, None),
        ("excluded", "service-contract", None, "irrelevant"),
        ("excluded", None, AssignmentTarget("case", ()), "irrelevant"),
        ("excluded", None, None, None),
        ("unresolved", "service-contract", None, None),
        ("unresolved", None, AssignmentTarget("case", ()), None),
        ("unresolved", None, None, "irrelevant"),
    ],
)
def test_unit_decision_enforces_closed_decision_shape(
    decision, role, target, exclusion_reason
):
    with pytest.raises(ValueError):
        UnitDecision("unit-0001", decision, role, target, exclusion_reason)


@pytest.mark.parametrize(
    "reason",
    [
        "duplicate", "irrelevant", "unreadable-replacement-available",
        "intentionally-omitted", "other",
    ],
)
def test_excluded_values_accept_only_fixed_reasons(reason):
    assert UnitDecision("unit-0001", "excluded", None, None, reason).exclusion_reason == reason
    assert SourceDisposition("evidence-0001", "excluded", reason).exclusion_reason == reason


@pytest.mark.parametrize("reason", ["", "not-needed", "Duplicate", None])
def test_excluded_values_reject_unknown_reasons(reason):
    with pytest.raises(ValueError):
        UnitDecision("unit-0001", "excluded", None, None, reason)
    with pytest.raises(ValueError):
        SourceDisposition("evidence-0001", "excluded", reason)


def test_values_are_frozen_deeply_immutable_and_serialization_is_a_copy():
    handles = ["participant-0001", "participant-0002"]
    target = AssignmentTarget("shared", handles)
    handles.append("participant-0003")
    payload = target.to_dict()
    payload["participantHandles"].append("participant-0003")

    assert target.participant_handles == ("participant-0001", "participant-0002")
    assert payload != target.to_dict()
    with pytest.raises(dataclasses.FrozenInstanceError):
        target.scope = "case"


@pytest.mark.parametrize(
    "parser, payload",
    [
        (Participant.from_dict, {"participantHandle": "participant-0001", "extra": True}),
        (AssignmentTarget.from_dict, {"scope": "case"}),
        (UnitDecision.from_dict, {"unitId": "unit-0001", "decision": "unresolved", "role": None, "target": None, "exclusionReason": None, "extra": True}),
        (SourceDisposition.from_dict, {"evidenceId": "evidence-0001", "decision": "unresolved", "exclusionReason": None, "extra": True}),
        (ProposalTotals.from_dict, {"sources": 0}),
    ],
)
def test_mapping_parsers_require_plain_dicts_with_exact_keys(parser, payload):
    with pytest.raises(ValueError):
        parser(payload)
    with pytest.raises(ValueError):
        parser(dict(payload))


def test_mapping_parsers_reject_dict_subclasses():
    class MappingSubclass(dict):
        pass

    with pytest.raises(ValueError):
        Participant.from_dict(MappingSubclass(participantHandle="participant-0001"))


def test_public_outcomes_enforce_exact_readiness_relationships_and_shapes():
    participant = Participant("participant-0001")
    assignment = UnitDecision(
        "unit-0001", "accepted", "service-contract", AssignmentTarget("case", ()), None
    )
    source = SourceDisposition("evidence-0002", "excluded", "irrelevant")
    approved = ApprovedProposal(
        _observation_id(), _digest(), "unit-0001", (participant,), (source,),
        (assignment,), _totals(), (), "user-approved",
    )
    assert approved.to_dict()["readyToPrepare"] is True
    assert approved.to_dict()["approval"] == {
        "status": "user-approved", "approvedProposalDigest": _digest()
    }
    draft = DraftProposal(_observation_id(), _totals(unresolved=1, issues=1), ("proposal-unresolved",))
    assert draft.to_dict()["outcome"] == "draft"
    assert draft.to_dict()["readyToPrepare"] is False
    assert set(draft.to_dict()) == {
        "proposalVersion", "outcome", "observationId", "readyToPrepare", "totals", "issueCodes"
    }
    assert CancelledProposal().to_dict() == {
        "proposalVersion": "1.0", "outcome": "cancelled", "readyToPrepare": False
    }
    with pytest.raises(ValueError):
        ApprovedProposal(_observation_id(), _digest(), "unit-0001", (), (), (), _totals(), (), "user-approved")


def test_approved_proposal_rejects_unresolved_public_records_even_with_zero_totals():
    with pytest.raises(ValueError):
        ApprovedProposal(
            _observation_id(), _digest(), "unit-0001", (Participant("participant-0001"),),
            (SourceDisposition("evidence-0001", "unresolved", None),), (), _totals(), (), "user-approved",
        )


def test_draft_state_rejects_private_or_untyped_values():
    with pytest.raises(ValueError):
        ProposalDraftState(_observation_id(), "unit-0001", ("participant-0001",), (), ())
