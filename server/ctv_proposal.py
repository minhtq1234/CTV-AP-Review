"""Memory-only, privacy-safe proposal state for the local CTV review."""

import hashlib
import hmac
import json
import re
from dataclasses import dataclass, field

from ctv_inspection_model import InspectionResult
from ctv_inventory import InventoryObservation
from ctv_proposal_roster import (
    RosterCandidate,
    choose_automatic_roster,
    load_roster_candidates,
)


_VERSION = "1.0"
_UNIT_ID = re.compile(r"^unit-[0-9]{4,}$")
_EVIDENCE_ID = re.compile(r"^evidence-[0-9]{4,}$")
_PARTICIPANT_HANDLE = re.compile(r"^participant-[0-9]{4,}$")
_ROLES_BY_KIND = {
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
_UNIT_DECISIONS = frozenset({"accepted", "reassigned", "excluded", "unresolved"})
_SOURCE_DECISIONS = frozenset({"excluded", "unresolved"})
_SCOPES = frozenset({"individual", "shared", "case"})
_EXCLUSION_REASONS = frozenset({
    "duplicate", "irrelevant", "unreadable-replacement-available",
    "intentionally-omitted", "other",
})
_ACQUISITION_STATUS_BY_INSPECTION_STATUS = {
    "opaque": "opaque",
    "unsupported": "unsupported",
    "unreadable": "unreadable",
    "encrypted": "encrypted",
    "over-limit": "over-limit",
}


@dataclass(frozen=True)
class RosterRowSnapshot:
    participant_handle: str
    row_index: int
    name: str = field(repr=False)
    identity: str = field(repr=False)
    fa_code: str = field(repr=False)
    tax_id: str = field(repr=False)
    birth_date: str = field(repr=False)
    bank_account: str = field(repr=False)
    service_fee: str = field(repr=False)
    product: str = field(repr=False)


@dataclass(frozen=True)
class UnitDecisionSnapshot:
    unit_id: str
    evidence_id: str
    unit_kind: str
    unit_index: int
    decision: str
    role: str = ""
    scope: str = ""
    participant_handles: tuple[str, ...] = ()
    reason: str = ""


@dataclass(frozen=True)
class SourceDispositionSnapshot:
    evidence_id: str
    decision: str
    reason: str = ""
    acquisition_status: str = ""
    coverage_state: str = ""
    issue_codes: tuple[str, ...] = ()


@dataclass(frozen=True)
class ApprovedProposalSnapshot:
    observation_id: str
    proposal_digest: str
    roster_unit_id: str
    roster_evidence_id: str
    roster_worksheet_index: int
    roster_rows: tuple[RosterRowSnapshot, ...]
    unit_decisions: tuple[UnitDecisionSnapshot, ...]
    source_dispositions: tuple[SourceDispositionSnapshot, ...]
    fa_code: str = field(repr=False)
    canonical_to_source_columns: tuple[tuple[str, str], ...] = field(repr=False)


def _mapping(value, keys):
    if type(value) is not dict or set(value) != set(keys):
        raise ValueError("proposal request must use its exact object shape")
    return value


def _string(value, pattern, name):
    if type(value) is not str or not pattern.fullmatch(value):
        raise ValueError(f"{name} must be a valid opaque ID")
    return value


def _enum(value, allowed, name):
    if type(value) is not str or value not in allowed:
        raise ValueError(f"{name} must be an approved value")
    return value


def _canonical_digest(value):
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


class ProposalState:
    """Trusted proposal records constructed after strict local API conversion."""

    def __init__(self, observation, inspection, snapshot_source=None):
        self._observation = observation
        self._inspection = inspection
        self._snapshot_source = (
            observation.snapshot if snapshot_source is None else snapshot_source
        )
        self._units_by_id = {unit.unit_id: unit for unit in inspection.units}
        self._sources_by_id = {source.evidence_id: source for source in inspection.sources}
        self._unit_decisions = {}
        self._source_dispositions = {}
        self._roster_unit_id = None
        self._participant_handles = ()
        self._participant_display = ()
        self._roster_issues = ()
        self._roster_package_issues = ()
        self._roster_rows_private = ()
        self._roster_columns_private = ()
        self._approved_package_digest = None
        self.units = tuple(
            {
                "unitId": unit.unit_id, "evidenceId": unit.evidence_id,
                "unitKind": unit.unit_kind, "suggestedRole": unit.suggested_role,
                "issueCodes": list(unit.issue_codes),
            }
            for unit in inspection.units
        )
        self.sources = tuple(
            {
                "evidenceId": source.evidence_id, "detectedType": source.detected_type,
                "inspectionStatus": source.inspection_status, "unitCount": source.unit_count,
                "issueCodes": list(source.issue_codes),
            }
            for source in inspection.sources
        )
        candidates = load_roster_candidates(inspection, self._snapshot_source)
        self._roster_candidates_by_id = {
            candidate.unit_id: candidate for candidate in candidates
        }
        selection = choose_automatic_roster(candidates)
        if selection.status == "selected":
            self._apply_roster_candidate(
                self._roster_candidates_by_id[selection.roster_unit_id]
            )
        else:
            self._roster_issues = selection.issue_codes

    @classmethod
    def from_inspection(cls, observation, inspection, *, _snapshot_source=None):
        if type(observation) is not InventoryObservation:
            raise TypeError("observation must be a live inventory observation")
        if type(inspection) is not InspectionResult:
            raise TypeError("inspection must be an inspection result")
        if inspection.observation_id != observation.observation_id:
            raise ValueError("inspection must belong to its observation")
        if _snapshot_source is not None and not callable(_snapshot_source):
            raise TypeError("snapshot source must be callable")
        return cls(observation, inspection, _snapshot_source)

    def _invalidate_approved_package(self):
        self._approved_package_digest = None

    def _roster_rows(self, unit):
        """Return the retained compatibility projection from a preloaded candidate."""
        candidate = self._roster_candidates_by_id.get(unit.unit_id)
        if candidate is None:
            return (), ("roster-unreadable",), (), ()
        return (
            tuple(
                (dict(row.values), row.row_index) for row in candidate.rows
            ),
            candidate.blocking_issue_codes,
            candidate.package_issue_codes,
            candidate.canonical_to_source_columns,
        )

    def _apply_roster_candidate(self, candidate: RosterCandidate):
        unit_id = candidate.unit_id
        self._invalidate_approved_package()
        if self._roster_unit_id is not None and self._roster_unit_id != unit_id:
            self._unit_decisions = {
                decision_unit_id: record
                for decision_unit_id, record in self._unit_decisions.items()
                if not (
                    record["decision"] in {"accepted", "reassigned"}
                    and record["target"]["participantHandles"]
                )
            }
        self._roster_unit_id = unit_id
        self._participant_handles = tuple(
            f"participant-{index:04d}"
            for index, _row in enumerate(candidate.rows, start=1)
        )
        self._participant_display = tuple(
            {
                "participantHandle": handle,
                "name": row["name"],
                "identityHint": f"***-{row['identity'][-3:]}",
            }
            for handle, candidate_row in zip(
                self._participant_handles, candidate.rows
            )
            for row in (dict(candidate_row.values),)
        )
        self._roster_issues = candidate.blocking_issue_codes
        self._roster_package_issues = candidate.package_issue_codes
        self._roster_rows_private = tuple(
            RosterRowSnapshot(
                participant_handle=handle,
                row_index=candidate_row.row_index,
                name=row["name"],
                identity=row["identity"],
                fa_code=row.get("faCode", ""),
                tax_id=row.get("taxId", ""),
                birth_date=row.get("birthDate", ""),
                bank_account=row.get("bankAccount", ""),
                service_fee=row.get("serviceFee", ""),
                product=row.get("product", ""),
            )
            for handle, candidate_row in zip(
                self._participant_handles, candidate.rows
            )
            for row in (dict(candidate_row.values),)
        )
        self._roster_columns_private = candidate.canonical_to_source_columns

    def select_roster(self, mapping):
        mapping = _mapping(mapping, {"rosterUnitId"})
        unit_id = _string(mapping["rosterUnitId"], _UNIT_ID, "rosterUnitId")
        candidate = self._roster_candidates_by_id.get(unit_id)
        if candidate is None:
            raise ValueError(
                "rosterUnitId must identify an inspected roster worksheet"
            )
        self._apply_roster_candidate(candidate)

    def participants_for_local_review(self):
        """Return private roster display fields only to the local review session."""
        return [dict(participant) for participant in self._participant_display]

    def _target(self, value):
        value = _mapping(value, {"scope", "participantHandles"})
        scope = _enum(value["scope"], _SCOPES, "scope")
        handles = value["participantHandles"]
        if type(handles) is not list:
            raise ValueError("participantHandles must be a list")
        if any(type(handle) is not str or not _PARTICIPANT_HANDLE.fullmatch(handle) for handle in handles):
            raise ValueError("participantHandles must be opaque participant handles")
        if len(handles) != len(set(handles)) or any(handle not in self._participant_handles for handle in handles):
            raise ValueError("participantHandles must be selected roster handles")
        if (scope == "individual" and len(handles) != 1) or (scope == "shared" and len(handles) < 2) or (scope == "case" and handles):
            raise ValueError("participantHandles must match the assignment scope")
        return {"scope": scope, "participantHandles": tuple(handles)}

    def set_unit_decision(self, mapping):
        if type(mapping) is not dict:
            raise ValueError("proposal request must use its exact object shape")
        decision = _enum(mapping.get("decision"), _UNIT_DECISIONS, "decision")
        required = {
            "accepted": {"unitId", "decision", "role", "target"},
            "reassigned": {"unitId", "decision", "role", "target"},
            "excluded": {"unitId", "decision", "reason"},
            "unresolved": {"unitId", "decision"},
        }[decision]
        _mapping(mapping, required)
        unit_id = _string(mapping["unitId"], _UNIT_ID, "unitId")
        unit = self._units_by_id.get(unit_id)
        if unit is None:
            raise ValueError("unitId must identify an inspected unit")
        record = {"decision": decision}
        if decision in {"accepted", "reassigned"}:
            role = _enum(mapping["role"], _ROLES_BY_KIND[unit.unit_kind], "role")
            if decision == "accepted" and (
                unit.suggested_role == "unknown" or role != unit.suggested_role
            ):
                raise ValueError("accepted role must equal a concrete suggested role")
            if decision == "reassigned" and (
                unit.suggested_role != "unknown" and role == unit.suggested_role
            ):
                raise ValueError("reassigned role must differ from a concrete suggested role")
            record.update({"role": role, "target": self._target(mapping["target"])})
        elif decision == "excluded":
            record["reason"] = _enum(mapping["reason"], _EXCLUSION_REASONS, "reason")
        self._unit_decisions[unit_id] = record
        self._invalidate_approved_package()

    def set_source_disposition(self, mapping):
        if type(mapping) is not dict:
            raise ValueError("proposal request must use its exact object shape")
        decision = _enum(mapping.get("decision"), _SOURCE_DECISIONS, "decision")
        required = {"excluded": {"evidenceId", "decision", "reason"}, "unresolved": {"evidenceId", "decision"}}[decision]
        _mapping(mapping, required)
        evidence_id = _string(mapping["evidenceId"], _EVIDENCE_ID, "evidenceId")
        source = self._sources_by_id.get(evidence_id)
        if source is None or any(unit.evidence_id == evidence_id for unit in self._inspection.units):
            raise ValueError("evidenceId must identify a source-only record")
        record = {"decision": decision}
        if decision == "excluded":
            record["reason"] = _enum(mapping["reason"], _EXCLUSION_REASONS, "reason")
        self._source_dispositions[evidence_id] = record
        self._invalidate_approved_package()

    def _issue_codes(self):
        issues = set(self._roster_issues)
        for source in self._inspection.sources:
            issues.update(source.issue_codes)
        for unit in self._inspection.units:
            issues.update(unit.issue_codes)
        return sorted(issues)

    def _ready(self):
        source_only_ids = {
            source.evidence_id for source in self._inspection.sources
            if not any(unit.evidence_id == source.evidence_id for unit in self._inspection.units)
        }
        return (
            self._roster_unit_id is not None
            and not self._roster_issues
            and set(self._unit_decisions) == set(self._units_by_id)
            and all(value["decision"] != "unresolved" for value in self._unit_decisions.values())
            and set(self._source_dispositions) == source_only_ids
            and all(value["decision"] != "unresolved" for value in self._source_dispositions.values())
        )

    def _counts(self):
        source_only_ids = {
            source.evidence_id for source in self._inspection.sources
            if not any(unit.evidence_id == source.evidence_id for unit in self._inspection.units)
        }
        return {
            "sources": len(self._inspection.sources), "units": len(self._inspection.units),
            "participants": len(self._participant_handles),
            "accepted": sum(value["decision"] == "accepted" for value in self._unit_decisions.values()),
            "reassigned": sum(value["decision"] == "reassigned" for value in self._unit_decisions.values()),
            "excluded": sum(value["decision"] == "excluded" for value in self._unit_decisions.values()) + sum(value["decision"] == "excluded" for value in self._source_dispositions.values()),
            "unresolved": sum(
                self._unit_decisions.get(unit_id, {"decision": "unresolved"})["decision"] == "unresolved"
                for unit_id in self._units_by_id
            ) + sum(
                self._source_dispositions.get(evidence_id, {"decision": "unresolved"})["decision"] == "unresolved"
                for evidence_id in source_only_ids
            ),
        }

    def _digest_input(self):
        assignments = []
        for unit_id in sorted(self._units_by_id):
            record = self._unit_decisions.get(unit_id, {"decision": "unresolved"})
            value = {"unitId": unit_id, "decision": record["decision"]}
            if "role" in record:
                value["role"] = record["role"]
                value["target"] = {"scope": record["target"]["scope"], "participantHandles": list(record["target"]["participantHandles"])}
            if "reason" in record:
                value["reason"] = record["reason"]
            assignments.append(value)
        unit_evidence_ids = {unit.evidence_id for unit in self._inspection.units}
        dispositions = [
            {
                "evidenceId": evidence_id,
                **self._source_dispositions.get(evidence_id, {"decision": "unresolved"}),
            }
            for evidence_id in sorted(
                source.evidence_id for source in self._inspection.sources
                if source.evidence_id not in unit_evidence_ids
            )
        ]
        return {
            "observationId": self._inspection.observation_id, "rosterUnitId": self._roster_unit_id,
            "participantHandles": list(self._participant_handles), "unitAssignments": assignments,
            "sourceDispositions": dispositions, "issueCodes": self._issue_codes(), "counts": self._counts(),
        }

    def approval_summary(self):
        digest = _canonical_digest(self._digest_input())
        return {
            "observationId": self._inspection.observation_id, "rosterUnitId": self._roster_unit_id,
            "participantHandles": list(self._participant_handles), "counts": self._counts(),
            "issueCodes": self._issue_codes(), "readyToPrepare": self._ready(), "proposalDigest": digest,
        }

    def _public_assignments(self):
        return self._digest_input()["unitAssignments"], self._digest_input()["sourceDispositions"]

    def draft_result(self):
        return {
            "version": _VERSION, "outcome": "draft", "observationId": self._inspection.observation_id,
            "readyToPrepare": False, "counts": self._counts(), "issueCodes": self._issue_codes(),
        }

    def cancelled_result(self):
        return {"version": _VERSION, "outcome": "cancelled", "readyToPrepare": False}

    def approve(self, expected_digest):
        if type(expected_digest) is not str or not re.fullmatch(r"[a-f0-9]{64}", expected_digest):
            raise ValueError("expected proposal digest must be a SHA-256 digest")
        summary = self.approval_summary()
        if not self._ready() or not hmac.compare_digest(expected_digest, summary["proposalDigest"]):
            raise ValueError("proposal is not ready for approval")
        self._approved_package_digest = summary["proposalDigest"]
        assignments, dispositions = self._public_assignments()
        return {
            "version": _VERSION, "outcome": "approved", "observationId": self._inspection.observation_id,
            "proposalDigest": summary["proposalDigest"], "readyToPrepare": True,
            "rosterUnitId": self._roster_unit_id, "participantHandles": list(self._participant_handles),
            "unitAssignments": assignments, "sourceDispositions": dispositions, "counts": self._counts(),
            "issueCodes": self._issue_codes(),
            "approval": {"status": "user-approved", "approvedProposalDigest": summary["proposalDigest"]},
        }

    def _package_ready(self):
        if not self._ready() or self._roster_unit_id is None or self._roster_package_issues:
            return False
        roster_decision = self._unit_decisions.get(self._roster_unit_id)
        if roster_decision is None or not (
            roster_decision.get("decision") in {"accepted", "reassigned"}
            and roster_decision.get("role") == "payment-roster"
            and roster_decision.get("target", {}).get("scope") == "case"
        ):
            return False
        source_only_ids = {
            source.evidence_id for source in self._inspection.sources
            if not any(unit.evidence_id == source.evidence_id for unit in self._inspection.units)
        }
        if any(
            self._sources_by_id[evidence_id].inspection_status
            not in _ACQUISITION_STATUS_BY_INSPECTION_STATUS
            for evidence_id in source_only_ids
        ):
            return False
        return any(
            unit.unit_kind == "pdf-page"
            and self._unit_decisions.get(unit.unit_id, {}).get("decision") in {"accepted", "reassigned"}
            for unit in self._inspection.units
        )

    def consume_approved_package_snapshot(self, expected_digest):
        """Consume the private local approval token into immutable preparation data."""
        if (
            type(expected_digest) is not str
            or not re.fullmatch(r"[a-f0-9]{64}", expected_digest)
            or self._approved_package_digest is None
            or not hmac.compare_digest(expected_digest, self._approved_package_digest)
            or not self._package_ready()
            or not hmac.compare_digest(expected_digest, self.approval_summary()["proposalDigest"])
        ):
            raise ValueError("approved package snapshot is unavailable")
        roster_unit = self._units_by_id[self._roster_unit_id]
        unit_snapshots = []
        for unit in sorted(self._inspection.units, key=lambda value: int(value.unit_id.rsplit("-", 1)[1])):
            record = self._unit_decisions[unit.unit_id]
            target = record.get("target", {})
            unit_snapshots.append(UnitDecisionSnapshot(
                unit_id=unit.unit_id, evidence_id=unit.evidence_id, unit_kind=unit.unit_kind,
                unit_index=unit.unit_index, decision=record["decision"], role=record.get("role", ""),
                scope=target.get("scope", ""), participant_handles=tuple(target.get("participantHandles", ())),
                reason=record.get("reason", ""),
            ))
        source_snapshots = tuple(
            SourceDispositionSnapshot(
                evidence_id=evidence_id,
                decision=record["decision"],
                reason=record.get("reason", ""),
                acquisition_status=_ACQUISITION_STATUS_BY_INSPECTION_STATUS[
                    self._sources_by_id[evidence_id].inspection_status
                ],
                coverage_state=(
                    "duplicate" if record.get("reason") == "duplicate"
                    else "excluded-by-user"
                ),
                issue_codes=tuple(self._sources_by_id[evidence_id].issue_codes),
            )
            for evidence_id, record in sorted(self._source_dispositions.items())
        )
        self._approved_package_digest = None
        return ApprovedProposalSnapshot(
            observation_id=self._inspection.observation_id, proposal_digest=expected_digest,
            roster_unit_id=roster_unit.unit_id, roster_evidence_id=roster_unit.evidence_id,
            roster_worksheet_index=roster_unit.unit_index, roster_rows=tuple(self._roster_rows_private),
            unit_decisions=tuple(unit_snapshots), source_dispositions=source_snapshots,
            fa_code=self._roster_rows_private[0].fa_code,
            canonical_to_source_columns=tuple(self._roster_columns_private),
        )
