"""Immutable, privacy-safe public values for CTV preparation proposals."""

import copy
import re
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal


ProposalOutcome = Literal["approved", "draft", "cancelled"]
Decision = Literal["accepted", "reassigned", "excluded", "unresolved"]
TargetScope = Literal["individual", "shared", "case"]
ExclusionReason = Literal[
    "duplicate", "irrelevant", "unreadable-replacement-available",
    "intentionally-omitted", "other",
]

PARTICIPANT_HANDLE = re.compile(r"^participant-[0-9]{4,}$")
PROPOSAL_DIGEST = re.compile(r"^proposal-[a-f0-9]{64}$")
_OBSERVATION_ID = re.compile(r"^observation-[a-f0-9]{64}$")
_UNIT_ID = re.compile(r"^unit-[0-9]{4,}$")
_EVIDENCE_ID = re.compile(r"^evidence-[0-9]{4,}$")

_TARGET_SCOPES = frozenset({"individual", "shared", "case"})
_DECISIONS = frozenset({"accepted", "reassigned", "excluded", "unresolved"})
_EXCLUSION_REASONS = frozenset({
    "duplicate", "irrelevant", "unreadable-replacement-available",
    "intentionally-omitted", "other",
})
_ROLES = frozenset({
    "payment-roster", "service-contract", "acceptance-record", "payment-tax-form",
    "identity-front", "identity-back", "shared-supporting-evidence",
    "other-supporting-evidence",
})
_PROPOSAL_ISSUES = frozenset({"proposal-unresolved"})


def _require_plain_mapping(value: object, keys: frozenset[str]) -> dict[str, object]:
    if type(value) is not dict or frozenset(value) != keys:
        raise ValueError("mapping must have an exact public shape")
    return value


def _immutable_sequence(values: object, expected: type, field_name: str) -> tuple:
    if isinstance(values, (str, bytes)):
        raise ValueError(f"{field_name} must be a sequence")
    try:
        copied = tuple(copy.deepcopy(tuple(values)))
    except TypeError:
        raise ValueError(f"{field_name} must be a sequence") from None
    if not all(type(value) is expected for value in copied):
        raise ValueError(f"{field_name} must contain {expected.__name__} values")
    return copied


def _validate_opaque(value: object, pattern: re.Pattern[str], field_name: str) -> str:
    if type(value) is not str or not pattern.fullmatch(value):
        raise ValueError(f"{field_name} must be an opaque ID")
    return value


def _validate_totals_value(value: object, field_name: str) -> int:
    if type(value) is not int or value < 0:
        raise ValueError(f"{field_name} must be a non-negative integer")
    return value


@dataclass(frozen=True)
class Participant:
    participant_handle: str

    def __post_init__(self) -> None:
        _validate_opaque(self.participant_handle, PARTICIPANT_HANDLE, "participant_handle")

    @classmethod
    def from_dict(cls, value: object) -> "Participant":
        mapping = _require_plain_mapping(value, frozenset({"participantHandle"}))
        return cls(mapping["participantHandle"])

    def to_dict(self) -> dict[str, object]:
        return {"participantHandle": self.participant_handle}


@dataclass(frozen=True)
class AssignmentTarget:
    scope: TargetScope
    participant_handles: Sequence[str]

    def __post_init__(self) -> None:
        if type(self.scope) is not str or self.scope not in _TARGET_SCOPES:
            raise ValueError("scope must be a supported target scope")
        handles = _immutable_sequence(self.participant_handles, str, "participant_handles")
        if any(not PARTICIPANT_HANDLE.fullmatch(handle) for handle in handles):
            raise ValueError("participant_handles must be opaque participant handles")
        if self.scope == "individual" and len(handles) != 1:
            raise ValueError("individual scope requires exactly one participant handle")
        if self.scope == "shared":
            if len(handles) < 2 or len(set(handles)) != len(handles):
                raise ValueError("shared scope requires distinct participant handles")
            if tuple(sorted(handles, key=lambda handle: int(handle.removeprefix("participant-")))) != handles:
                raise ValueError("shared participant handles must be in roster order")
        if self.scope == "case" and handles:
            raise ValueError("case scope must not include participant handles")
        object.__setattr__(self, "participant_handles", handles)

    @classmethod
    def from_dict(cls, value: object) -> "AssignmentTarget":
        mapping = _require_plain_mapping(value, frozenset({"scope", "participantHandles"}))
        return cls(mapping["scope"], mapping["participantHandles"])

    def to_dict(self) -> dict[str, object]:
        return copy.deepcopy({
            "scope": self.scope,
            "participantHandles": list(self.participant_handles),
        })


@dataclass(frozen=True)
class UnitDecision:
    unit_id: str
    decision: Decision
    role: str | None
    target: AssignmentTarget | None
    exclusion_reason: ExclusionReason | None

    def __post_init__(self) -> None:
        _validate_opaque(self.unit_id, _UNIT_ID, "unit_id")
        if type(self.decision) is not str or self.decision not in _DECISIONS:
            raise ValueError("decision must be supported")
        if self.decision in {"accepted", "reassigned"}:
            if type(self.role) is not str or self.role not in _ROLES:
                raise ValueError("resolved decision requires a supported role")
            if type(self.target) is not AssignmentTarget or self.exclusion_reason is not None:
                raise ValueError("resolved decision requires target and no exclusion reason")
        elif self.decision == "excluded":
            if self.role is not None or self.target is not None:
                raise ValueError("excluded decision must not have role or target")
            if type(self.exclusion_reason) is not str or self.exclusion_reason not in _EXCLUSION_REASONS:
                raise ValueError("excluded decision requires a fixed exclusion reason")
        elif self.role is not None or self.target is not None or self.exclusion_reason is not None:
            raise ValueError("unresolved decision must not have role, target, or exclusion reason")

    @classmethod
    def from_dict(cls, value: object) -> "UnitDecision":
        if type(value) is not dict or type(value.get("decision")) is not str:
            raise ValueError("mapping must have an exact public shape")
        if value["decision"] in {"accepted", "reassigned"}:
            mapping = _require_plain_mapping(value, frozenset({"unitId", "decision", "role", "target"}))
            return cls(mapping["unitId"], mapping["decision"], mapping["role"], AssignmentTarget.from_dict(mapping["target"]), None)
        if value["decision"] == "excluded":
            mapping = _require_plain_mapping(value, frozenset({"unitId", "decision", "exclusionReason"}))
            return cls(mapping["unitId"], mapping["decision"], None, None, mapping["exclusionReason"])
        mapping = _require_plain_mapping(value, frozenset({"unitId", "decision"}))
        return cls(mapping["unitId"], mapping["decision"], None, None, None)

    def to_dict(self) -> dict[str, object]:
        if self.decision in {"accepted", "reassigned"}:
            return copy.deepcopy({
                "unitId": self.unit_id, "decision": self.decision, "role": self.role,
                "target": self.target.to_dict(),
            })
        if self.decision == "excluded":
            return {"unitId": self.unit_id, "decision": "excluded", "exclusionReason": self.exclusion_reason}
        return {"unitId": self.unit_id, "decision": "unresolved"}


@dataclass(frozen=True)
class SourceDisposition:
    evidence_id: str
    decision: Literal["excluded", "unresolved"]
    exclusion_reason: ExclusionReason | None

    def __post_init__(self) -> None:
        _validate_opaque(self.evidence_id, _EVIDENCE_ID, "evidence_id")
        if type(self.decision) is not str or self.decision not in {"excluded", "unresolved"}:
            raise ValueError("source disposition decision must be supported")
        if self.decision == "excluded":
            if type(self.exclusion_reason) is not str or self.exclusion_reason not in _EXCLUSION_REASONS:
                raise ValueError("excluded source requires a fixed exclusion reason")
        elif self.exclusion_reason is not None:
            raise ValueError("unresolved source must not have an exclusion reason")

    @classmethod
    def from_dict(cls, value: object) -> "SourceDisposition":
        if type(value) is not dict or type(value.get("decision")) is not str:
            raise ValueError("mapping must have an exact public shape")
        if value["decision"] == "excluded":
            mapping = _require_plain_mapping(value, frozenset({"evidenceId", "decision", "exclusionReason"}))
            return cls(mapping["evidenceId"], mapping["decision"], mapping["exclusionReason"])
        mapping = _require_plain_mapping(value, frozenset({"evidenceId", "decision"}))
        return cls(mapping["evidenceId"], mapping["decision"], None)

    def to_dict(self) -> dict[str, object]:
        if self.decision == "excluded":
            return {"evidenceId": self.evidence_id, "decision": "excluded", "exclusionReason": self.exclusion_reason}
        return {"evidenceId": self.evidence_id, "decision": "unresolved"}


@dataclass(frozen=True)
class ProposalTotals:
    sources: int
    source_only: int
    participants: int
    units: int
    accepted: int
    reassigned: int
    excluded: int
    unresolved: int
    issues: int

    def __post_init__(self) -> None:
        for field_name in self.__dataclass_fields__:
            _validate_totals_value(getattr(self, field_name), field_name)

    @classmethod
    def from_dict(cls, value: object) -> "ProposalTotals":
        mapping = _require_plain_mapping(value, frozenset({
            "sources", "sourceOnly", "participants", "units", "accepted",
            "reassigned", "excluded", "unresolved", "issues",
        }))
        return cls(
            mapping["sources"], mapping["sourceOnly"], mapping["participants"],
            mapping["units"], mapping["accepted"], mapping["reassigned"],
            mapping["excluded"], mapping["unresolved"], mapping["issues"],
        )

    def to_dict(self) -> dict[str, int]:
        return {
            "sources": self.sources,
            "sourceOnly": self.source_only,
            "participants": self.participants,
            "units": self.units,
            "accepted": self.accepted,
            "reassigned": self.reassigned,
            "excluded": self.excluded,
            "unresolved": self.unresolved,
            "issues": self.issues,
        }


def _immutable_records(values: object, expected: type, field_name: str) -> tuple:
    return _immutable_sequence(values, expected, field_name)


@dataclass(frozen=True)
class ProposalDraftState:
    observation_id: str
    roster_unit_id: str | None
    participants: Sequence[Participant]
    source_dispositions: Sequence[SourceDisposition]
    unit_decisions: Sequence[UnitDecision]

    def __post_init__(self) -> None:
        _validate_opaque(self.observation_id, _OBSERVATION_ID, "observation_id")
        if self.roster_unit_id is not None:
            _validate_opaque(self.roster_unit_id, _UNIT_ID, "roster_unit_id")
        object.__setattr__(self, "participants", _immutable_records(self.participants, Participant, "participants"))
        object.__setattr__(self, "source_dispositions", _immutable_records(self.source_dispositions, SourceDisposition, "source_dispositions"))
        object.__setattr__(self, "unit_decisions", _immutable_records(self.unit_decisions, UnitDecision, "unit_decisions"))


@dataclass(frozen=True)
class ApprovedProposal:
    observation_id: str
    proposal_digest: str
    roster_unit_id: str
    participants: Sequence[Participant]
    source_dispositions: Sequence[SourceDisposition]
    assignments: Sequence[UnitDecision]
    totals: ProposalTotals
    issue_codes: Sequence[str]
    approval_status: Literal["user-approved"]

    def __post_init__(self) -> None:
        _validate_opaque(self.observation_id, _OBSERVATION_ID, "observation_id")
        _validate_opaque(self.proposal_digest, PROPOSAL_DIGEST, "proposal_digest")
        _validate_opaque(self.roster_unit_id, _UNIT_ID, "roster_unit_id")
        participants = _immutable_records(self.participants, Participant, "participants")
        source_dispositions = _immutable_records(self.source_dispositions, SourceDisposition, "source_dispositions")
        assignments = _immutable_records(self.assignments, UnitDecision, "assignments")
        if not participants or len({item.participant_handle for item in participants}) != len(participants):
            raise ValueError("approved proposal requires unique participants")
        if any(item.decision != "excluded" for item in source_dispositions):
            raise ValueError("approved proposal cannot retain unresolved source dispositions")
        if any(item.decision not in {"accepted", "reassigned", "excluded"} for item in assignments):
            raise ValueError("approved proposal cannot retain unresolved assignments")
        if type(self.totals) is not ProposalTotals or self.totals.unresolved or self.totals.issues:
            raise ValueError("approved proposal requires zero unresolved work and issues")
        if tuple(self.issue_codes) or self.approval_status != "user-approved":
            raise ValueError("approved proposal requires empty issues and user approval")
        object.__setattr__(self, "participants", participants)
        object.__setattr__(self, "source_dispositions", source_dispositions)
        object.__setattr__(self, "assignments", assignments)
        object.__setattr__(self, "issue_codes", ())

    def to_dict(self) -> dict[str, object]:
        return copy.deepcopy({
            "proposalVersion": "1.0", "outcome": "approved", "observationId": self.observation_id,
            "proposalDigest": self.proposal_digest, "readyToPrepare": True,
            "rosterUnitId": self.roster_unit_id,
            "participants": [item.to_dict() for item in self.participants],
            "sourceDispositions": [item.to_dict() for item in self.source_dispositions],
            "assignments": [item.to_dict() for item in self.assignments],
            "totals": self.totals.to_dict(), "issueCodes": list(self.issue_codes),
            "approval": {"status": "user-approved", "approvedProposalDigest": self.proposal_digest},
        })


@dataclass(frozen=True)
class DraftProposal:
    observation_id: str
    totals: ProposalTotals
    issue_codes: Sequence[str]

    def __post_init__(self) -> None:
        _validate_opaque(self.observation_id, _OBSERVATION_ID, "observation_id")
        if type(self.totals) is not ProposalTotals:
            raise ValueError("totals must be ProposalTotals")
        issue_codes = _immutable_sequence(self.issue_codes, str, "issue_codes")
        if any(code not in _PROPOSAL_ISSUES for code in issue_codes) or len(set(issue_codes)) != len(issue_codes):
            raise ValueError("issue_codes must use fixed proposal codes")
        if self.totals.issues != len(issue_codes):
            raise ValueError("totals issues must match issue_codes")
        object.__setattr__(self, "issue_codes", issue_codes)

    def to_dict(self) -> dict[str, object]:
        return copy.deepcopy({
            "proposalVersion": "1.0", "outcome": "draft", "observationId": self.observation_id,
            "readyToPrepare": False, "totals": self.totals.to_dict(), "issueCodes": list(self.issue_codes),
        })


@dataclass(frozen=True)
class CancelledProposal:
    def to_dict(self) -> dict[str, object]:
        return {"proposalVersion": "1.0", "outcome": "cancelled", "readyToPrepare": False}
