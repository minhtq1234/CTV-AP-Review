"""Pure validation, canonicalization, digesting, and approval for CTV proposals."""

import copy
import hashlib
import hmac
import json
from collections.abc import Sequence
from dataclasses import dataclass

from ctv_inspection_model import InspectionResult, InspectionUnit
from ctv_proposal_model import (
    PROPOSAL_DIGEST,
    ApprovedProposal,
    Participant,
    ProposalTotals,
    SourceDisposition,
    UnitDecision,
)


_ALLOWED_ROLES = {
    "pdf-page": frozenset({
        "payment-roster", "service-contract", "acceptance-record", "payment-tax-form",
        "identity-front", "identity-back", "shared-supporting-evidence",
        "other-supporting-evidence",
    }),
    "worksheet": frozenset({"payment-roster", "other-supporting-evidence"}),
    "image": frozenset({
        "identity-front", "identity-back", "shared-supporting-evidence",
        "other-supporting-evidence",
    }),
}


def _records(values: object, expected: type, field_name: str) -> tuple:
    if isinstance(values, (str, bytes)):
        raise ValueError(f"{field_name} must be a sequence")
    try:
        copied = tuple(copy.deepcopy(tuple(values)))
    except TypeError:
        raise ValueError(f"{field_name} must be a sequence") from None
    if not all(type(value) is expected for value in copied):
        raise ValueError(f"{field_name} must contain {expected.__name__} values")
    return copied


@dataclass(frozen=True)
class ProposalValidation:
    observation_id: str
    roster_unit_id: str | None
    participants: tuple[Participant, ...]
    source_dispositions: tuple[SourceDisposition, ...]
    unit_decisions: tuple[UnitDecision, ...]
    totals: ProposalTotals
    issue_codes: tuple[str, ...]
    ready_to_prepare: bool

    def __post_init__(self) -> None:
        if type(self.observation_id) is not str:
            raise ValueError("observation_id must be an opaque observation ID")
        if self.roster_unit_id is not None and type(self.roster_unit_id) is not str:
            raise ValueError("roster_unit_id must be an opaque unit ID or null")
        object.__setattr__(self, "participants", _records(self.participants, Participant, "participants"))
        object.__setattr__(self, "source_dispositions", _records(self.source_dispositions, SourceDisposition, "source_dispositions"))
        object.__setattr__(self, "unit_decisions", _records(self.unit_decisions, UnitDecision, "unit_decisions"))
        if type(self.totals) is not ProposalTotals:
            raise ValueError("totals must be ProposalTotals")
        if type(self.ready_to_prepare) is not bool:
            raise ValueError("ready_to_prepare must be a Boolean")
        issues = _records(self.issue_codes, str, "issue_codes")
        if issues not in {(), ("proposal-unresolved",)}:
            raise ValueError("issue_codes must use fixed proposal codes")
        if self.totals.issues != len(issues):
            raise ValueError("totals issues must match issue_codes")
        if self.ready_to_prepare != (not issues and self.totals.unresolved == 0):
            raise ValueError("ready_to_prepare must agree with proposal readiness")
        object.__setattr__(self, "issue_codes", issues)


def _unique_map(records: tuple, identifier: str) -> tuple[dict[str, object], bool]:
    mapped: dict[str, object] = {}
    invalid = False
    for record in records:
        record_id = getattr(record, identifier)
        if record_id in mapped:
            invalid = True
            continue
        mapped[record_id] = record
    return mapped, invalid


def _valid_target(decision: UnitDecision, participant_positions: dict[str, int]) -> bool:
    target = decision.target
    if target is None:
        return False
    handles = target.participant_handles
    if any(handle not in participant_positions for handle in handles):
        return False
    return all(
        participant_positions[left] < participant_positions[right]
        for left, right in zip(handles, handles[1:])
    )


def _valid_unit_decision(
    decision: UnitDecision, unit: InspectionUnit, participant_positions: dict[str, int]
) -> bool:
    if decision.decision == "unresolved":
        return False
    if decision.decision == "excluded":
        return True
    if decision.role not in _ALLOWED_ROLES[unit.unit_kind] or not _valid_target(decision, participant_positions):
        return False
    if decision.decision == "accepted":
        return decision.role == unit.suggested_role and unit.suggested_role != "unknown"
    return decision.role != unit.suggested_role


def validate_proposal(
    inspection: InspectionResult,
    participants: Sequence[Participant],
    roster_unit_id: str | None,
    source_dispositions: Sequence[SourceDisposition],
    unit_decisions: Sequence[UnitDecision],
) -> ProposalValidation:
    """Validate a full proposal and return only canonical inspection-ordered values."""
    if type(inspection) is not InspectionResult:
        raise ValueError("inspection must be InspectionResult")
    participants = _records(participants, Participant, "participants")
    source_dispositions = _records(source_dispositions, SourceDisposition, "source_dispositions")
    unit_decisions = _records(unit_decisions, UnitDecision, "unit_decisions")

    participant_handles = [participant.participant_handle for participant in participants]
    participants_valid = bool(participants) and len(set(participant_handles)) == len(participant_handles)
    participant_positions = {handle: index for index, handle in enumerate(participant_handles)}

    units_by_id = {unit.unit_id: unit for unit in inspection.units}
    units_by_evidence = {source.evidence_id: 0 for source in inspection.sources}
    for unit in inspection.units:
        units_by_evidence[unit.evidence_id] += 1
    source_only_ids = tuple(
        source.evidence_id for source in inspection.sources if units_by_evidence[source.evidence_id] == 0
    )

    roster_valid = False
    if type(roster_unit_id) is str:
        roster = units_by_id.get(roster_unit_id)
        roster_valid = (
            roster is not None
            and roster.unit_kind == "worksheet"
            and "roster-column-pattern" in roster.signal_codes
        )

    source_map, invalid_source_records = _unique_map(source_dispositions, "evidence_id")
    unit_map, invalid_unit_records = _unique_map(unit_decisions, "unit_id")
    invalid_source_records = invalid_source_records or any(
        evidence_id not in source_only_ids for evidence_id in source_map
    )
    invalid_unit_records = invalid_unit_records or any(unit_id not in units_by_id for unit_id in unit_map)

    canonical_sources: list[SourceDisposition] = []
    canonical_units: list[UnitDecision] = []
    accepted = reassigned = excluded = unresolved = 0
    invalid_semantics = False

    for evidence_id in source_only_ids:
        disposition = source_map.get(evidence_id)
        if disposition is None or disposition.decision != "excluded":
            unresolved += 1
            if disposition is not None:
                canonical_sources.append(disposition)
            continue
        canonical_sources.append(disposition)
        excluded += 1

    for unit in inspection.units:
        decision = unit_map.get(unit.unit_id)
        if decision is None:
            unresolved += 1
            continue
        canonical_units.append(decision)
        if not _valid_unit_decision(decision, unit, participant_positions):
            unresolved += 1
            invalid_semantics = True
            continue
        if decision.decision == "accepted":
            accepted += 1
        elif decision.decision == "reassigned":
            reassigned += 1
        else:
            excluded += 1

    invalid = (
        invalid_source_records or invalid_unit_records or invalid_semantics
        or not participants_valid or not roster_valid
    )
    issue_codes = ("proposal-unresolved",) if unresolved or invalid else ()
    totals = ProposalTotals(
        sources=len(inspection.sources), source_only=len(source_only_ids),
        participants=len(participants), units=len(inspection.units), accepted=accepted,
        reassigned=reassigned, excluded=excluded, unresolved=unresolved,
        issues=len(issue_codes),
    )
    return ProposalValidation(
        inspection.observation_id, roster_unit_id, participants,
        tuple(canonical_sources), tuple(canonical_units), totals, issue_codes,
        not issue_codes,
    )


def canonical_approval_payload(validation: ProposalValidation) -> dict[str, object]:
    if type(validation) is not ProposalValidation:
        raise ValueError("validation must be ProposalValidation")
    return copy.deepcopy({
        "proposalVersion": "1.0",
        "observationId": validation.observation_id,
        "rosterUnitId": validation.roster_unit_id,
        "participants": [participant.to_dict() for participant in validation.participants],
        "sourceDispositions": [item.to_dict() for item in validation.source_dispositions],
        "assignments": [item.to_dict() for item in validation.unit_decisions],
        "totals": validation.totals.to_dict(),
        "issueCodes": list(validation.issue_codes),
    })


def proposal_digest(validation: ProposalValidation) -> str:
    payload = canonical_approval_payload(validation)
    encoded = json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return "proposal-" + hashlib.sha256(encoded).hexdigest()


def approve_proposal(validation: ProposalValidation, expected_digest: str) -> ApprovedProposal:
    if type(validation) is not ProposalValidation or not validation.ready_to_prepare:
        raise ValueError("proposal validation is not ready for approval")
    if type(expected_digest) is not str or not PROPOSAL_DIGEST.fullmatch(expected_digest):
        raise ValueError("expected_digest must be a proposal digest")
    digest = proposal_digest(validation)
    if not hmac.compare_digest(digest, expected_digest):
        raise ValueError("proposal digest changed before approval")
    if validation.roster_unit_id is None:
        raise ValueError("ready proposal requires a roster unit")
    return ApprovedProposal(
        validation.observation_id, digest, validation.roster_unit_id,
        validation.participants, validation.source_dispositions, validation.unit_decisions,
        validation.totals, validation.issue_codes, "user-approved",
    )
