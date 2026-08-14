"""Private conversion of an approved proposal snapshot to v2 assignments."""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from dataclasses import dataclass

from ctv_proposal import ApprovedProposalSnapshot
from intake_contract_v2 import (
    AssignmentParticipantV2, AssignmentsDocumentV2, AssignmentUnitV2, DecisionV2,
    ExclusionRecordV2, ImageLocatorV2, OutputLocatorV2, PdfPageLocatorV2,
    RosterLocatorV2, WorksheetLocatorV2,
)


def _id(prefix: str, digest: str, record_id: str) -> str:
    return f"{prefix}-{hashlib.sha256((digest + ":" + record_id).encode()).hexdigest()[:32]}"


def _source_id(digest: str, evidence_id: str) -> str:
    return _id("source", digest, evidence_id)


def _decision_type(decision: str) -> str:
    return "accept-unit" if decision == "accepted" else "reassign-unit"


def _source_exclusion_reason(item) -> str:
    if item.coverage_state == "duplicate":
        return "duplicate"
    try:
        return {
            "opaque": "excluded-by-user",
            "unsupported": "unsupported",
            "unreadable": "unreadable",
            "encrypted": "encrypted",
            "over-limit": "over-limit",
        }[item.acquisition_status]
    except KeyError:
        raise ValueError("source exclusion facts are unsupported") from None


@dataclass(frozen=True)
class AssignmentBuildResult:
    document: AssignmentsDocumentV2
    decisions: tuple[DecisionV2, ...]


def _locator_matches(unit, locator) -> bool:
    expected = {
        "pdf-page": PdfPageLocatorV2,
        "image": ImageLocatorV2,
        "worksheet": RosterLocatorV2 if unit.role == "payment-roster" else WorksheetLocatorV2,
    }[unit.unit_kind]
    return type(locator) is expected


def build_assignments(
    snapshot: ApprovedProposalSnapshot,
    *,
    package_id: str,
    locators: Mapping[str, OutputLocatorV2],
) -> AssignmentBuildResult:
    """Return the closed assignment document plus its manifest decisions."""
    if type(snapshot) is not ApprovedProposalSnapshot or not isinstance(locators, Mapping):
        raise ValueError("approved package snapshot and locators are required")
    included = tuple(item for item in snapshot.unit_decisions if item.decision in {"accepted", "reassigned"})
    if any(item.unit_kind not in {"pdf-page", "worksheet", "image"} for item in included):
        raise ValueError("included units must be supported")
    if set(locators) != {item.unit_id for item in included}:
        raise ValueError("locators must completely cover included units")
    roster = next((item for item in included if item.unit_id == snapshot.roster_unit_id), None)
    if roster is None or (roster.role, roster.scope, roster.unit_kind) != ("payment-roster", "case", "worksheet"):
        raise ValueError("selected roster must be case-scope payment-roster")
    expected_handles = tuple(f"participant-{index:04d}" for index in range(1, len(snapshot.roster_rows) + 1))
    if tuple(row.participant_handle for row in snapshot.roster_rows) != expected_handles:
        raise ValueError("roster participant order is invalid")
    if any(not _locator_matches(item, locators[item.unit_id]) for item in included):
        raise ValueError("output locator does not match included unit")
    roster_locator = locators[snapshot.roster_unit_id]
    assert type(roster_locator) is RosterLocatorV2
    participants = [
        AssignmentParticipantV2(
            participantHandle=row.participant_handle,
            rosterRowId=_id("roster-row", snapshot.proposal_digest, row.participant_handle),
        )
        for row in snapshot.roster_rows
    ]
    units = []
    decisions = []
    for item in included:
        decision_id = _id("decision", snapshot.proposal_digest, item.unit_id)
        source_id = _source_id(snapshot.proposal_digest, item.evidence_id)
        units.append(AssignmentUnitV2(
            unitId=item.unit_id, sourceId=source_id, sourceUnitIndex=item.unit_index,
            unitKind=item.unit_kind, decisionId=decision_id, decision=item.decision,
            role=item.role, target={"scope": item.scope, "participantHandles": list(item.participant_handles)},
            outputLocator=locators[item.unit_id],
        ))
        decisions.append(DecisionV2(
            decisionId=decision_id, proposalVersion="1.0", proposalDigest=snapshot.proposal_digest,
            type=_decision_type(item.decision), actor="user", subjectRefs=[item.unit_id], evidenceRefs=[source_id],
        ))
    exclusions = []
    for item in snapshot.unit_decisions:
        if item.decision != "excluded":
            continue
        decision_id = _id("decision", snapshot.proposal_digest, item.unit_id)
        exclusions.append(ExclusionRecordV2(recordType="unit", recordId=item.unit_id, decisionId=decision_id, reason="excluded-by-user"))
        decisions.append(DecisionV2(decisionId=decision_id, proposalVersion="1.0", proposalDigest=snapshot.proposal_digest, type="exclude-unit", actor="user", subjectRefs=[item.unit_id], evidenceRefs=[_source_id(snapshot.proposal_digest, item.evidence_id)]))
    for item in snapshot.source_dispositions:
        if item.decision != "excluded":
            continue
        source_id = _source_id(snapshot.proposal_digest, item.evidence_id)
        decision_id = _id("decision", snapshot.proposal_digest, source_id)
        exclusions.append(ExclusionRecordV2(
            recordType="source", recordId=source_id, decisionId=decision_id,
            reason=_source_exclusion_reason(item),
        ))
        decisions.append(DecisionV2(decisionId=decision_id, proposalVersion="1.0", proposalDigest=snapshot.proposal_digest, type="exclude-source", actor="user", subjectRefs=[source_id], evidenceRefs=[source_id]))
    roster_source_id = _source_id(snapshot.proposal_digest, snapshot.roster_evidence_id)
    decisions.extend((
        DecisionV2(decisionId=_id("decision", snapshot.proposal_digest, "select-roster"), proposalVersion="1.0", proposalDigest=snapshot.proposal_digest, type="select-roster", actor="user", subjectRefs=[snapshot.roster_unit_id], evidenceRefs=[roster_source_id]),
        DecisionV2(decisionId=_id("decision", snapshot.proposal_digest, "approve-proposal"), proposalVersion="1.0", proposalDigest=snapshot.proposal_digest, type="approve-proposal", actor="user", subjectRefs=[snapshot.roster_unit_id], evidenceRefs=[roster_source_id]),
    ))
    document = AssignmentsDocumentV2(
        schemaVersion="2.0", packageId=package_id, sourceObservationId=snapshot.observation_id,
        proposalDigest=snapshot.proposal_digest, rosterArtifactId=roster_locator.artifact_id,
        participants=participants, units=units, exclusions=exclusions,
    )
    return AssignmentBuildResult(document=document, decisions=tuple(decisions))
