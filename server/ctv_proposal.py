"""Memory-only, privacy-safe proposal state for the local CTV review."""

import copy
import hashlib
import hmac
import json
import re
from dataclasses import dataclass, field

from ctv_grouping_evidence import GroupingEvidence
from ctv_inspection_model import InspectionResult
from ctv_inventory import InventoryObservation
from ctv_proposal_grouping import (
    ExpandedDecision,
    GroupTarget,
    GroupingPlan,
    build_grouping_plan,
)
from ctv_proposal_roster import (
    RosterCandidate,
    RosterSelection,
    choose_automatic_roster,
    load_roster_candidates,
    validate_roster_candidates,
)


_VERSION = "1.0"
_UNIT_ID = re.compile(r"^unit-[0-9]{4,}$")
_EVIDENCE_ID = re.compile(r"^evidence-[0-9]{4,}$")
_PARTICIPANT_HANDLE = re.compile(r"^participant-[0-9]{4,}$")
_GROUP_ID = re.compile(r"^group-[0-9]{4,}$")
_EXCEPTION_ID = re.compile(r"^exception-[0-9]{4,}$")
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
_EXCEPTION_ACTIONS = frozenset({
    "accept-recommendation", "assign", "exclude", "split", "merge-next",
    "choose-roster",
})
_FIXED_GROUP_ISSUES = (
    "private-fact-incomplete", "participant-name-only",
    "participant-identity-only", "participant-no-match",
    "participant-multiple-match", "participant-identity-conflict",
    "target-unresolved", "role-uncertain", "role-gap-conflict",
    "role-scope-unsupported", "packet-structure-incoherent",
    "source-issue-present", "unit-issue-present",
)
_ACQUISITION_STATUS_BY_INSPECTION_STATUS = {
    # The frozen reason retains intentional omission; v2 encodes that user
    # exclusion through its existing opaque acquisition representation.
    "inspected": "opaque",
    "not-applicable": "opaque",
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


def _exact_mapping_keys(value):
    if (
        type(value) is not dict
        or any(type(key) is not str for key in value)
    ):
        raise ValueError("proposal request must use its exact object shape")
    return value


def _mapping(value, keys):
    value = _exact_mapping_keys(value)
    if set(value) != set(keys):
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


def _numeric_opaque_id(value):
    return int(value.rsplit("-", 1)[1])


def _review_similarity_key(issue_code, recommended_action, actions, role, scope):
    fixed = "|".join(
        (issue_code, recommended_action, ",".join(actions), role, scope)
    )
    return "similarity-" + hashlib.sha256(fixed.encode("ascii")).hexdigest()[:16]


def _require_exact_unit_coverage(expanded, units_by_id):
    unit_ids = tuple(item.unit_id for item in expanded)
    if len(unit_ids) != len(set(unit_ids)) or set(unit_ids) != set(units_by_id):
        raise ValueError("expanded coverage must equal inspection units")


def _proposal_decisions(expanded, units_by_id):
    decisions = {}
    for item in expanded:
        if item.decision == "assign":
            unit = units_by_id[item.unit_id]
            decision = (
                "accepted"
                if unit.suggested_role != "unknown" and item.role == unit.suggested_role
                else "reassigned"
            )
            decisions[item.unit_id] = {
                "decision": decision,
                "role": item.role,
                "target": {
                    "scope": item.target.scope,
                    "participantHandles": item.target.participant_handles,
                },
            }
        elif item.decision == "exclude":
            decisions[item.unit_id] = {
                "decision": "excluded",
                "reason": item.reason,
            }
        else:
            decisions[item.unit_id] = {"decision": "unresolved"}
    return decisions


class ProposalState:
    """Trusted proposal records constructed after strict local API conversion."""

    def __init__(
        self,
        observation,
        inspection,
        snapshot_source=None,
        grouping_evidence=None,
        roster_candidates=None,
    ):
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
        self._grouping_evidence = grouping_evidence
        self._grouping_plan = None
        self._review_groups = []
        self._review_exceptions = []
        self._exception_resolutions = {}
        self._review_operations = []
        self._undo_states = {}
        self._next_group_number = 1
        self._next_exception_number = 1
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
        candidates = (
            load_roster_candidates(inspection, self._snapshot_source)
            if roster_candidates is None
            else validate_roster_candidates(inspection, roster_candidates)
        )
        self._roster_candidates_by_id = {
            candidate.unit_id: candidate for candidate in candidates
        }
        selection = choose_automatic_roster(candidates)
        self._roster_selection = selection
        if selection.status == "selected":
            candidate = self._roster_candidates_by_id[selection.roster_unit_id]
            if grouping_evidence is not None:
                transition = self._prepare_grouped_roster_transition(
                    candidate, selection, retire_existing_ids=False
                )
                self._commit_grouped_roster_transition(transition)
            else:
                self._apply_roster_candidate(candidate)
        else:
            self._roster_issues = selection.issue_codes
            if grouping_evidence is not None:
                self._review_exceptions = [self._roster_exception(selection)]
                self._next_exception_number = 2

    @classmethod
    def from_inspection(
        cls,
        observation,
        inspection,
        *,
        _snapshot_source=None,
        _grouping_evidence=None,
        _roster_candidates=None,
    ):
        if type(observation) is not InventoryObservation:
            raise TypeError("observation must be a live inventory observation")
        if type(inspection) is not InspectionResult:
            raise TypeError("inspection must be an inspection result")
        if inspection.observation_id != observation.observation_id:
            raise ValueError("inspection must belong to its observation")
        if _snapshot_source is not None and not callable(_snapshot_source):
            raise TypeError("snapshot source must be callable")
        if (
            _grouping_evidence is not None
            and type(_grouping_evidence) is not GroupingEvidence
        ):
            raise TypeError("grouping evidence must be exact GroupingEvidence")
        if _roster_candidates is not None and type(_roster_candidates) is not tuple:
            raise TypeError("preloaded roster candidates must be an exact tuple")
        return cls(
            observation,
            inspection,
            _snapshot_source,
            _grouping_evidence,
            _roster_candidates,
        )

    def _prepare_grouped_roster_transition(
        self, candidate, selection, *, retire_existing_ids
    ):
        plan = build_grouping_plan(
            self._inspection,
            candidate,
            self._grouping_evidence,
        )
        expanded = plan.expand()
        _require_exact_unit_coverage(expanded, self._units_by_id)

        groups = [
            self._review_group_from_plan(group) for group in plan.groups
        ]
        exceptions = [
            self._review_exception_from_plan(item, source=False)
            for item in plan.exceptions
        ] + [
            self._review_exception_from_plan(item, source=True)
            for item in plan.source_exceptions
        ]
        exceptions.sort(key=lambda item: _numeric_opaque_id(item["exceptionId"]))

        next_group_number = self._next_group_number
        next_exception_number = self._next_exception_number
        if retire_existing_ids:
            group_id_map = {}
            for group in groups:
                old_id = group["groupId"]
                group["groupId"] = f"group-{next_group_number:04d}"
                next_group_number += 1
                group_id_map[old_id] = group["groupId"]
            for item in exceptions:
                item["exceptionId"] = f"exception-{next_exception_number:04d}"
                next_exception_number += 1
                if item["kind"] == "unit-cluster":
                    item["groupIds"] = tuple(
                        group_id_map[group_id] for group_id in item["groupIds"]
                    )
        else:
            if groups:
                next_group_number = max(
                    next_group_number,
                    max(_numeric_opaque_id(group["groupId"]) for group in groups) + 1,
                )
            if exceptions:
                next_exception_number = max(
                    next_exception_number,
                    max(
                        _numeric_opaque_id(item["exceptionId"])
                        for item in exceptions
                    )
                    + 1,
                )

        for exclusion in plan.automatic_exclusions:
            unit = self._units_by_id[exclusion.unit_id]
            groups.append(
                {
                    "groupId": f"group-{next_group_number:04d}",
                    "evidenceId": unit.evidence_id,
                    "unitKind": unit.unit_kind,
                    "memberUnitIds": (unit.unit_id,),
                    "firstUnitIndex": unit.unit_index,
                    "lastUnitIndex": unit.unit_index,
                    "role": "",
                    "target": {"scope": "case", "participantHandles": ()},
                    "state": "automatically-organized",
                    "checkCodes": ("coverage-exact",),
                    "issueCodes": (),
                    "automaticExclusion": True,
                }
            )
            next_group_number += 1

        groups, exceptions, resolutions = self._canonicalize_review(
            groups, exceptions, {}
        )
        expanded, source_dispositions = self._expanded_review(
            groups, exceptions, resolutions, plan=plan
        )
        return {
            "roster": self._roster_candidate_state(candidate),
            "selection": selection,
            "plan": plan,
            "groups": groups,
            "exceptions": exceptions,
            "resolutions": resolutions,
            "expanded": expanded,
            "sourceDispositions": source_dispositions,
            "nextGroupNumber": next_group_number,
            "nextExceptionNumber": next_exception_number,
        }

    def _commit_grouped_roster_transition(self, transition):
        self._commit_roster_state(transition["roster"])
        self._roster_selection = transition["selection"]
        self._grouping_plan = transition["plan"]
        self._review_groups = transition["groups"]
        self._review_exceptions = transition["exceptions"]
        self._exception_resolutions = transition["resolutions"]
        self._review_operations = []
        self._undo_states = {}
        self._unit_decisions = _proposal_decisions(
            transition["expanded"], self._units_by_id
        )
        self._source_dispositions = transition["sourceDispositions"]
        self._next_group_number = transition["nextGroupNumber"]
        self._next_exception_number = transition["nextExceptionNumber"]
        self._invalidate_approved_package()

    @staticmethod
    def _roster_exception(selection):
        issue_code = selection.issue_codes[0]
        return {
            "exceptionId": "exception-0001",
            "kind": "roster",
            "issueCode": issue_code,
            "recommendedAction": "choose-roster",
            "allowedActions": ("choose-roster",),
            "similarityKey": _review_similarity_key(
                issue_code,
                "choose-roster",
                ("choose-roster",),
                "unknown",
                "case",
            ),
        }

    @staticmethod
    def _review_group_from_plan(group):
        return {
            "groupId": group.group_id,
            "evidenceId": group.evidence_id,
            "unitKind": group.unit_kind,
            "memberUnitIds": tuple(group.member_unit_ids),
            "firstUnitIndex": group.first_unit_index,
            "lastUnitIndex": group.last_unit_index,
            "role": group.role,
            "target": {
                "scope": group.target.scope,
                "participantHandles": tuple(group.target.participant_handles),
            },
            "state": group.state,
            "checkCodes": tuple(group.check_codes),
            "issueCodes": tuple(group.issue_codes),
        }

    @staticmethod
    def _review_exception_from_plan(item, *, source):
        value = {
            "exceptionId": item.exception_id,
            "kind": "source" if source else "unit-cluster",
            "issueCode": item.issue_code,
            "recommendedAction": item.recommended_action,
            "allowedActions": tuple(item.allowed_actions),
            "similarityKey": item.similarity_key,
        }
        if source:
            value["evidenceId"] = item.evidence_id
        else:
            value["groupIds"] = tuple(item.group_ids)
            value["memberUnitIds"] = tuple(item.member_unit_ids)
        return value

    @staticmethod
    def _target_projection(target):
        return {
            "scope": target["scope"],
            "participantHandles": list(target["participantHandles"]),
        }

    def _group_projection(self, group, *, include_effective_resolution=False):
        resolved_item = next(
            (
                item
                for item in self._review_exceptions
                if item["kind"] == "unit-cluster"
                and group["groupId"] in item["groupIds"]
                and item["exceptionId"] in self._exception_resolutions
            ),
            None,
        )
        value = {
            "groupId": group["groupId"],
            "evidenceId": group["evidenceId"],
            "unitKind": group["unitKind"],
            "memberUnitIds": list(group["memberUnitIds"]),
            "firstUnitIndex": group["firstUnitIndex"],
            "lastUnitIndex": group["lastUnitIndex"],
            "role": group["role"],
            "target": self._target_projection(group["target"]),
            "state": "user-resolved" if resolved_item else group["state"],
            "checkCodes": list(group["checkCodes"]),
            "issueCodes": list(group["issueCodes"]),
        }
        if resolved_item is not None and include_effective_resolution:
            resolution = self._exception_resolutions[
                resolved_item["exceptionId"]
            ]
            effective = {"action": resolution["action"]}
            if resolution["action"] == "assign":
                effective["role"] = resolution["role"]
                effective["target"] = self._target_projection(
                    resolution["target"]
                )
            else:
                effective["reason"] = resolution["reason"]
            value["effectiveResolution"] = effective
        return value

    def _roster_candidate_summaries(self):
        values = []
        for unit_id in self._roster_selection.candidate_unit_ids:
            candidate = self._roster_candidates_by_id[unit_id]
            issue_codes = list(
                dict.fromkeys(
                    (
                        *candidate.blocking_issue_codes,
                        *candidate.package_issue_codes,
                    )
                )
            )
            values.append(
                {
                    "rosterUnitId": unit_id,
                    "participantCount": len(candidate.rows),
                    "eligible": bool(candidate.rows) and not issue_codes,
                    "issueCodes": issue_codes,
                }
            )
        return values

    @staticmethod
    def _exception_projection(item):
        value = {
            "exceptionId": item["exceptionId"],
            "kind": item["kind"],
            "issueCode": item["issueCode"],
            "allowedActions": list(item["allowedActions"]),
            "similarityKey": item["similarityKey"],
        }
        if item.get("recommendationExecutable", True):
            value["recommendedAction"] = item["recommendedAction"]
        if item["kind"] == "source":
            value["evidenceId"] = item["evidenceId"]
        elif item["kind"] == "unit-cluster":
            value["groupIds"] = list(item["groupIds"])
            value["memberUnitIds"] = list(item["memberUnitIds"])
        return value

    def _review_coverage(self):
        unresolved = [
            item
            for item in self._review_exceptions
            if item["exceptionId"] not in self._exception_resolutions
        ]
        covered_ids = {
            unit_id
            for group in self._review_groups
            for unit_id in group["memberUnitIds"]
        }
        return {
            "groups": len(self._review_groups),
            "automaticallyOrganizedUnits": sum(
                len(group["memberUnitIds"])
                for group in self._review_groups
                if group["state"] == "automatically-organized"
            ),
            "exceptionClusters": len(unresolved),
            "exceptionUnits": sum(
                len(item["memberUnitIds"])
                for item in unresolved
                if item["kind"] == "unit-cluster"
            ),
            "unaccountedUnits": len(self._units_by_id) - len(covered_ids),
        }

    def local_review_snapshot(self):
        groups = [
            self._group_projection(
                group, include_effective_resolution=True
            )
            for group in self._review_groups
        ]
        exceptions = [
            self._exception_projection(item)
            for item in self._review_exceptions
            if item["exceptionId"] not in self._exception_resolutions
        ]
        resolved_exclusions = []
        for item in self._review_exceptions:
            resolution = self._exception_resolutions.get(item["exceptionId"])
            if (
                item["kind"] == "source"
                and resolution is not None
                and resolution["action"] == "exclude"
            ):
                resolved_exclusions.append(
                    {
                        "exceptionId": item["exceptionId"],
                        "kind": "source",
                        "evidenceId": item["evidenceId"],
                        "issueCode": item["issueCode"],
                        "reason": resolution["reason"],
                    }
                )
        summary = self.approval_summary()
        return {
            "roster": {
                "status": self._roster_selection.status,
                "rosterUnitId": self._roster_unit_id,
                "candidateUnitIds": list(
                    self._roster_selection.candidate_unit_ids
                ),
                "candidateSummaries": self._roster_candidate_summaries(),
                "participantHandles": list(self._participant_handles),
                "issueCodes": list(self._roster_issues),
            },
            "review": {
                "groups": groups,
                "exceptions": exceptions,
                "resolvedExclusions": resolved_exclusions,
                "coverage": self._review_coverage(),
                "issueCodes": sorted(
                    {item["issueCode"] for item in exceptions}
                ),
            },
            "summary": {
                "counts": summary["counts"],
                "readyToPrepare": summary["readyToPrepare"],
                "proposalDigest": summary["proposalDigest"],
            },
        }

    def _transition_state(self):
        return (
            copy.deepcopy(self._review_groups),
            copy.deepcopy(self._review_exceptions),
            copy.deepcopy(self._exception_resolutions),
            copy.deepcopy(self._review_operations),
        )

    def _validated_assignment_target(
        self, member_unit_ids, group_id, role, target
    ):
        target_value = GroupTarget(
            target["scope"], target["participantHandles"]
        )
        if any(
            role not in _ROLES_BY_KIND[self._units_by_id[unit_id].unit_kind]
            for unit_id in member_unit_ids
        ):
            raise ValueError("assigned role must support every exception unit")
        ExpandedDecision(
            unit_id=member_unit_ids[0],
            decision="assign",
            group_id=group_id,
            state="user-resolved",
            role=role,
            target=target_value,
            reason="",
        )
        return target_value

    @staticmethod
    def _group_order_key(group):
        return (
            _numeric_opaque_id(group["evidenceId"]),
            _numeric_opaque_id(group["memberUnitIds"][0]),
        )

    @staticmethod
    def _exception_order_key(item, groups_by_id):
        if item["kind"] == "source":
            return (_numeric_opaque_id(item["evidenceId"]), 0)
        group = groups_by_id[item["groupIds"][0]]
        return (
            _numeric_opaque_id(group["evidenceId"]),
            _numeric_opaque_id(item["memberUnitIds"][0]),
        )

    def _expanded_review(self, groups, exceptions, resolutions, *, plan=None):
        plan = self._grouping_plan if plan is None else plan
        if plan is None:
            raise ValueError("group review is unavailable until roster selection")
        if (
            any(
                type(group.get("groupId")) is not str
                or _GROUP_ID.fullmatch(group["groupId"]) is None
                for group in groups
            )
            or len({group["groupId"] for group in groups}) != len(groups)
        ):
            raise ValueError("group review IDs must be unique")
        if groups != sorted(groups, key=self._group_order_key):
            raise ValueError("group review must use canonical group order")
        covered = []
        groups_by_id = {}
        for group in groups:
            groups_by_id[group["groupId"]] = group
            members = group["memberUnitIds"]
            member_units = [self._units_by_id.get(unit_id) for unit_id in members]
            if (
                not members
                or any(unit is None for unit in member_units)
                or any(
                    unit.evidence_id != group["evidenceId"]
                    or unit.unit_kind != group["unitKind"]
                    for unit in member_units
                )
                or tuple(unit.unit_index for unit in member_units)
                != tuple(
                    range(group["firstUnitIndex"], group["lastUnitIndex"] + 1)
                )
            ):
                raise ValueError("group review must remain same-source and contiguous")
            covered.extend(members)
        covered.extend(
            item.unit_id
            for item in plan.automatic_exclusions
            if item.unit_id not in covered
        )
        if len(covered) != len(set(covered)) or set(covered) != set(self._units_by_id):
            raise ValueError("group review coverage must equal inspection units")

        exception_ids = [item["exceptionId"] for item in exceptions]
        if (
            any(
                type(exception_id) is not str
                or _EXCEPTION_ID.fullmatch(exception_id) is None
                for exception_id in exception_ids
            )
            or len(exception_ids) != len(set(exception_ids))
            or exceptions
            != sorted(
                exceptions,
                key=lambda item: self._exception_order_key(item, groups_by_id),
            )
        ):
            raise ValueError("exceptions must use canonical review order")
        if any(exception_id not in exception_ids for exception_id in resolutions):
            raise ValueError("resolutions must reference current exceptions")
        clustered_group_ids = []
        clustered_unit_ids = []
        source_evidence_ids = []
        for item in exceptions:
            if item["kind"] == "unit-cluster":
                if any(group_id not in groups_by_id for group_id in item["groupIds"]):
                    raise ValueError("exception must reference current groups")
                members = tuple(
                    member
                    for group_id in item["groupIds"]
                    for member in groups_by_id[group_id]["memberUnitIds"]
                )
                if members != item["memberUnitIds"]:
                    raise ValueError("exception membership must equal group membership")
                clustered_group_ids.extend(item["groupIds"])
                clustered_unit_ids.extend(item["memberUnitIds"])
            elif item["kind"] == "source":
                source_evidence_ids.append(item["evidenceId"])
            else:
                raise ValueError("roster exception must be resolved before grouping")
        exception_group_ids = [
            group["groupId"] for group in groups if group["state"] == "exception"
        ]
        if (
            len(clustered_group_ids) != len(set(clustered_group_ids))
            or set(clustered_group_ids) != set(exception_group_ids)
            or len(clustered_unit_ids) != len(set(clustered_unit_ids))
        ):
            raise ValueError("exception coverage must match exception groups")
        expected_source_ids = {
            item.evidence_id for item in plan.source_exceptions
        }
        if len(source_evidence_ids) != len(set(source_evidence_ids)) or set(
            source_evidence_ids
        ) != expected_source_ids:
            raise ValueError("source exception coverage must remain exact")

        expanded_by_id = {
            item.unit_id: item for item in plan.expand()
        }
        source_dispositions = {
            evidence_id: {"decision": "unresolved"}
            for evidence_id in expected_source_ids
        }
        for item in exceptions:
            exception_id = item["exceptionId"]
            if item["kind"] == "unit-cluster":
                group_id = item["groupIds"][0]
                for unit_id in item["memberUnitIds"]:
                    expanded_by_id[unit_id] = ExpandedDecision(
                        unit_id=unit_id,
                        decision="unresolved",
                        group_id=group_id,
                        state="exception",
                        role="",
                        target=None,
                        reason="",
                    )
            resolution = resolutions.get(exception_id)
            if resolution is None:
                continue
            if resolution["action"] == "assign":
                target = self._validated_assignment_target(
                    item["memberUnitIds"],
                    item["groupIds"][0],
                    resolution["role"],
                    resolution["target"],
                )
                for unit_id in item["memberUnitIds"]:
                    expanded_by_id[unit_id] = ExpandedDecision(
                        unit_id=unit_id,
                        decision="assign",
                        group_id=item["groupIds"][0],
                        state="user-resolved",
                        role=resolution["role"],
                        target=target,
                        reason="",
                    )
            elif resolution["action"] == "exclude":
                if item["kind"] == "source":
                    source_dispositions[item["evidenceId"]] = {
                        "decision": "excluded",
                        "reason": resolution["reason"],
                    }
                else:
                    for unit_id in item["memberUnitIds"]:
                        expanded_by_id[unit_id] = ExpandedDecision(
                            unit_id=unit_id,
                            decision="exclude",
                            group_id=None,
                            state="user-resolved",
                            role="",
                            target=None,
                            reason=resolution["reason"],
                        )
            else:
                raise ValueError("resolution must use an effective terminal action")
        expanded = tuple(
            expanded_by_id[unit_id]
            for unit_id in sorted(expanded_by_id, key=_numeric_opaque_id)
        )
        _require_exact_unit_coverage(expanded, self._units_by_id)
        return expanded, source_dispositions

    def _commit_review(
        self,
        groups,
        exceptions,
        resolutions,
        operations,
        *,
        next_group_number=None,
        next_exception_number=None,
    ):
        groups, exceptions, resolutions = self._canonicalize_review(
            groups, exceptions, resolutions
        )
        expanded, source_dispositions = self._expanded_review(
            groups, exceptions, resolutions
        )
        self._review_groups = groups
        self._review_exceptions = exceptions
        self._exception_resolutions = resolutions
        self._review_operations = operations
        self._unit_decisions = _proposal_decisions(expanded, self._units_by_id)
        self._source_dispositions = source_dispositions
        if next_group_number is not None:
            self._next_group_number = next_group_number
        if next_exception_number is not None:
            self._next_exception_number = next_exception_number
        self._invalidate_approved_package()

    @staticmethod
    def _recommended_exclusion_reason(item):
        if item["kind"] == "unit-cluster":
            reason = item.get("recommendedReason")
            if reason is None:
                raise ValueError("unit recommendation does not exclude")
            return reason
        return {
            "source-exact-duplicate": "duplicate",
            "source-unreadable": "unreadable-replacement-available",
            "source-opaque": "intentionally-omitted",
            "source-unsupported": "intentionally-omitted",
            "source-encrypted": "intentionally-omitted",
            "source-over-limit": "intentionally-omitted",
            "source-not-applicable": "intentionally-omitted",
        }[item["issueCode"]]

    def _canonicalize_review(self, groups, exceptions, resolutions):
        groups.sort(key=self._group_order_key)
        groups_by_id = {group["groupId"]: group for group in groups}
        exceptions.sort(
            key=lambda item: self._exception_order_key(item, groups_by_id)
        )
        unresolved_by_group = {
            item["groupIds"][0]: item
            for item in exceptions
            if item["kind"] == "unit-cluster"
            and len(item["groupIds"]) == 1
            and item["exceptionId"] not in resolutions
        }
        group_indexes = {
            group["groupId"]: index for index, group in enumerate(groups)
        }
        for item in exceptions:
            if item["kind"] != "unit-cluster" or len(item["groupIds"]) != 1:
                continue
            actions = tuple(
                action for action in item["allowedActions"] if action != "merge-next"
            )
            group = groups_by_id[item["groupIds"][0]]
            group_index = group_indexes[group["groupId"]]
            can_merge = False
            if (
                item["exceptionId"] not in resolutions
                and group_index + 1 < len(groups)
            ):
                next_group = groups[group_index + 1]
                can_merge = (
                    next_group["groupId"] in unresolved_by_group
                    and group["evidenceId"] == next_group["evidenceId"]
                    and group["unitKind"] == next_group["unitKind"]
                    and group["lastUnitIndex"] + 1
                    == next_group["firstUnitIndex"]
                )
            if can_merge:
                actions += ("merge-next",)
            item["allowedActions"] = actions
            if item["recommendedAction"] == "assign":
                try:
                    self._validated_assignment_target(
                        item["memberUnitIds"],
                        item["groupIds"][0],
                        group["role"],
                        group["target"],
                    )
                except (TypeError, ValueError):
                    item["recommendationExecutable"] = False
                else:
                    item["recommendationExecutable"] = True
            else:
                item["recommendationExecutable"] = (
                    item["recommendedAction"] == "exclude"
                    and item.get("recommendedReason") in _EXCLUSION_REASONS
                )
            item["similarityKey"] = _review_similarity_key(
                item["issueCode"],
                item["recommendedAction"],
                actions,
                group["role"],
                group["target"]["scope"],
            )
        return groups, exceptions, resolutions

    def _split_exception(self, item, split_before, groups, exceptions, resolutions):
        if item["kind"] != "unit-cluster" or len(item["groupIds"]) != 1:
            raise ValueError("split requires one unit exception group")
        members = item["memberUnitIds"]
        if split_before not in members or split_before == members[0]:
            raise ValueError("splitBeforeUnitId must be a nonfirst exception member")
        group_index = next(
            index
            for index, group in enumerate(groups)
            if group["groupId"] == item["groupIds"][0]
        )
        group = groups[group_index]
        split_index = members.index(split_before)
        member_parts = (members[:split_index], members[split_index:])
        new_groups = []
        new_exceptions = []
        next_group_number = self._next_group_number
        next_exception_number = self._next_exception_number
        allowed_actions = tuple(
            action
            for action in ("assign", "exclude", "split")
            if action in item["allowedActions"]
        )
        for part in member_parts:
            first = self._units_by_id[part[0]]
            last = self._units_by_id[part[-1]]
            new_group = copy.deepcopy(group)
            new_group["groupId"] = f"group-{next_group_number:04d}"
            next_group_number += 1
            new_group["memberUnitIds"] = tuple(part)
            new_group["firstUnitIndex"] = first.unit_index
            new_group["lastUnitIndex"] = last.unit_index
            new_groups.append(new_group)
            new_exceptions.append(
                {
                    **{
                        key: copy.deepcopy(value)
                        for key, value in item.items()
                        if key not in {"exceptionId", "groupIds", "memberUnitIds"}
                    },
                    "exceptionId": f"exception-{next_exception_number:04d}",
                    "groupIds": (new_group["groupId"],),
                    "memberUnitIds": tuple(part),
                    "allowedActions": allowed_actions,
                    "similarityKey": _review_similarity_key(
                        item["issueCode"],
                        item["recommendedAction"],
                        allowed_actions,
                        new_group["role"],
                        new_group["target"]["scope"],
                    ),
                }
            )
            next_exception_number += 1
        groups[group_index:group_index + 1] = new_groups
        exceptions[:] = [
            value for value in exceptions if value["exceptionId"] != item["exceptionId"]
        ] + new_exceptions
        resolutions.pop(item["exceptionId"], None)
        groups, exceptions, resolutions = self._canonicalize_review(
            groups, exceptions, resolutions
        )
        return (
            groups,
            exceptions,
            resolutions,
            next_group_number,
            next_exception_number,
        )

    def _merge_next_exception(self, item, groups, exceptions, resolutions):
        if item["kind"] != "unit-cluster" or len(item["groupIds"]) != 1:
            raise ValueError("merge-next requires one unit exception group")
        group_index = next(
            index
            for index, group in enumerate(groups)
            if group["groupId"] == item["groupIds"][0]
        )
        if group_index + 1 >= len(groups):
            raise ValueError("merge-next requires a following group")
        group = groups[group_index]
        next_group = groups[group_index + 1]
        next_exception = next(
            (
                value
                for value in exceptions
                if value["kind"] == "unit-cluster"
                and value["groupIds"] == (next_group["groupId"],)
                and value["exceptionId"] not in resolutions
            ),
            None,
        )
        if (
            next_exception is None
            or group["evidenceId"] != next_group["evidenceId"]
            or group["unitKind"] != next_group["unitKind"]
            or group["lastUnitIndex"] + 1 != next_group["firstUnitIndex"]
        ):
            raise ValueError("merge-next must remain same-source and contiguous")
        members = group["memberUnitIds"] + next_group["memberUnitIds"]
        role = group["role"] if group["role"] == next_group["role"] else "unknown"
        target = (
            copy.deepcopy(group["target"])
            if group["target"] == next_group["target"]
            else {"scope": "case", "participantHandles": ()}
        )
        issue_code = (
            item["issueCode"]
            if item["issueCode"] == next_exception["issueCode"]
            else "role-uncertain"
        )
        allowed_actions = ("assign", "exclude", "split", "merge-next")
        merged_group = {
            **copy.deepcopy(group),
            "groupId": f"group-{self._next_group_number:04d}",
            "memberUnitIds": members,
            "lastUnitIndex": next_group["lastUnitIndex"],
            "role": role,
            "target": target,
            "state": "exception",
            "checkCodes": tuple(
                code
                for code in group["checkCodes"]
                if code in next_group["checkCodes"]
            ),
            "issueCodes": tuple(
                code for code in _FIXED_GROUP_ISSUES if code == issue_code
            ),
        }
        merged_exception = {
            "exceptionId": f"exception-{self._next_exception_number:04d}",
            "kind": "unit-cluster",
            "groupIds": (merged_group["groupId"],),
            "memberUnitIds": members,
            "issueCode": issue_code,
            "recommendedAction": "assign",
            "allowedActions": allowed_actions,
            "similarityKey": _review_similarity_key(
                issue_code,
                "assign",
                allowed_actions,
                role,
                target["scope"],
            ),
        }
        groups[group_index:group_index + 2] = [merged_group]
        removed_ids = {item["exceptionId"], next_exception["exceptionId"]}
        exceptions[:] = [
            value for value in exceptions if value["exceptionId"] not in removed_ids
        ] + [merged_exception]
        for exception_id in removed_ids:
            resolutions.pop(exception_id, None)
        groups, exceptions, resolutions = self._canonicalize_review(
            groups, exceptions, resolutions
        )
        return (
            groups,
            exceptions,
            resolutions,
            self._next_group_number + 1,
            self._next_exception_number + 1,
        )

    def _choose_grouped_roster(self, item, roster_unit_id):
        if item["kind"] != "roster":
            raise ValueError("choose-roster requires the roster exception")
        candidate = self._roster_candidates_by_id.get(roster_unit_id)
        if (
            candidate is None
            or roster_unit_id not in self._roster_selection.candidate_unit_ids
            or candidate.blocking_issue_codes
            or candidate.package_issue_codes
            or not candidate.rows
        ):
            raise ValueError("rosterUnitId must identify an eligible roster candidate")
        selection = RosterSelection(
            status="selected",
            roster_unit_id=roster_unit_id,
            candidate_unit_ids=self._roster_selection.candidate_unit_ids,
            issue_codes=(),
        )
        transition = self._prepare_grouped_roster_transition(
            candidate, selection, retire_existing_ids=True
        )
        self._commit_grouped_roster_transition(transition)

    def resolve_exception(self, mapping):
        _exact_mapping_keys(mapping)
        action = _enum(mapping.get("action"), _EXCEPTION_ACTIONS, "action")
        required = {
            "accept-recommendation": {"exceptionId", "action", "applyToSimilar"},
            "assign": {"exceptionId", "action", "role", "target", "applyToSimilar"},
            "exclude": {"exceptionId", "action", "reason", "applyToSimilar"},
            "split": {"exceptionId", "action", "splitBeforeUnitId", "applyToSimilar"},
            "merge-next": {"exceptionId", "action", "applyToSimilar"},
            "choose-roster": {"exceptionId", "action", "rosterUnitId", "applyToSimilar"},
        }[action]
        _mapping(mapping, required)
        exception_id = _string(
            mapping["exceptionId"], _EXCEPTION_ID, "exceptionId"
        )
        apply_to_similar = mapping["applyToSimilar"]
        if type(apply_to_similar) is not bool:
            raise ValueError("applyToSimilar must be a Boolean")
        item = next(
            (
                value
                for value in self._review_exceptions
                if value["exceptionId"] == exception_id
            ),
            None,
        )
        if item is None or exception_id in self._exception_resolutions:
            raise ValueError("exceptionId must identify a current unresolved exception")
        if action == "accept-recommendation" and not item.get(
            "recommendationExecutable", True
        ):
            raise ValueError("exception has no executable recommendation")
        if action == "choose-roster":
            if apply_to_similar:
                raise ValueError("choose-roster cannot apply to similar exceptions")
            roster_unit_id = _string(
                mapping["rosterUnitId"], _UNIT_ID, "rosterUnitId"
            )
            self._choose_grouped_roster(item, roster_unit_id)
            return
        if item["kind"] == "roster":
            raise ValueError("roster exception requires choose-roster")
        if action in {"split", "merge-next"} and apply_to_similar:
            raise ValueError("structural actions must identify one exception")
        effective_action = (
            item["recommendedAction"]
            if action == "accept-recommendation"
            else action
        )
        if effective_action not in item["allowedActions"]:
            raise ValueError("action must be allowed for the current exception")

        previous = self._transition_state()
        groups, exceptions, resolutions, operations = self._transition_state()
        next_group_number = None
        next_exception_number = None
        candidate_item = next(
            value for value in exceptions if value["exceptionId"] == exception_id
        )
        targets = [candidate_item]
        if apply_to_similar:
            targets.extend(
                value
                for value in exceptions
                if value["exceptionId"] != exception_id
                and value["exceptionId"] not in resolutions
                and value["kind"] == candidate_item["kind"]
                and value["similarityKey"] == candidate_item["similarityKey"]
                and value["allowedActions"] == candidate_item["allowedActions"]
                and effective_action in value["allowedActions"]
            )
        if effective_action == "assign":
            if action != "accept-recommendation":
                role = mapping["role"]
                if type(role) is not str:
                    raise ValueError("role must be an approved value")
                target = self._target(mapping["target"])
            for target_item in targets:
                if action == "accept-recommendation":
                    target_group = next(
                        group
                        for group in groups
                        if group["groupId"] == target_item["groupIds"][0]
                    )
                    target_role = target_group["role"]
                    target_value = copy.deepcopy(target_group["target"])
                else:
                    target_role = role
                    target_value = copy.deepcopy(target)
                resolutions[target_item["exceptionId"]] = {
                    "action": "assign",
                    "requestedAction": action,
                    "role": target_role,
                    "target": target_value,
                }
        elif effective_action == "exclude":
            if action == "accept-recommendation":
                reason = self._recommended_exclusion_reason(candidate_item)
            else:
                reason = _enum(
                    mapping["reason"], _EXCLUSION_REASONS, "reason"
                )
            for target_item in targets:
                target_reason = (
                    self._recommended_exclusion_reason(target_item)
                    if action == "accept-recommendation"
                    else reason
                )
                resolutions[target_item["exceptionId"]] = {
                    "action": "exclude",
                    "requestedAction": action,
                    "reason": target_reason,
                }
        elif effective_action == "split":
            split_before = _string(
                mapping["splitBeforeUnitId"], _UNIT_ID, "splitBeforeUnitId"
            )
            (
                groups,
                exceptions,
                resolutions,
                next_group_number,
                next_exception_number,
            ) = self._split_exception(
                candidate_item, split_before, groups, exceptions, resolutions
            )
            operations.append(
                {
                    "action": "split",
                    "memberUnitIds": list(candidate_item["memberUnitIds"]),
                    "splitBeforeUnitId": split_before,
                }
            )
        elif effective_action == "merge-next":
            (
                groups,
                exceptions,
                resolutions,
                next_group_number,
                next_exception_number,
            ) = self._merge_next_exception(
                candidate_item, groups, exceptions, resolutions
            )
            operations.append(
                {
                    "action": "merge-next",
                    "memberUnitIds": list(candidate_item["memberUnitIds"]),
                }
            )
        self._commit_review(
            groups,
            exceptions,
            resolutions,
            operations,
            next_group_number=next_group_number,
            next_exception_number=next_exception_number,
        )
        self._undo_states = {exception_id: previous}

    def undo_exception(self, mapping):
        mapping = _mapping(mapping, {"exceptionId"})
        exception_id = _string(
            mapping["exceptionId"], _EXCEPTION_ID, "exceptionId"
        )
        previous = self._undo_states.get(exception_id)
        if previous is None:
            raise ValueError("exceptionId has no current undo transition")
        groups, exceptions, resolutions, operations = copy.deepcopy(previous)
        self._commit_review(groups, exceptions, resolutions, operations)
        self._undo_states = {}

    def reopen_group(self, mapping):
        mapping = _mapping(mapping, {"groupId"})
        group_id = _string(mapping["groupId"], _GROUP_ID, "groupId")
        live_group = next(
            (
                group
                for group in self._review_groups
                if group["groupId"] == group_id
            ),
            None,
        )
        if live_group is None:
            raise ValueError("groupId must identify a current group")
        item = next(
            (
                value
                for value in self._review_exceptions
                if value["kind"] == "unit-cluster"
                and group_id in value["groupIds"]
                and value["exceptionId"] in self._exception_resolutions
            ),
            None,
        )
        groups, exceptions, resolutions, operations = self._transition_state()
        next_exception_number = None
        if item is not None:
            resolutions.pop(item["exceptionId"])
        elif live_group["state"] == "automatically-organized":
            group = next(
                group for group in groups if group["groupId"] == group_id
            )
            group["state"] = "exception"
            group["issueCodes"] = ("target-unresolved",)
            is_automatic_exclusion = bool(group.get("automaticExclusion"))
            actions = ["assign", "exclude"]
            if len(group["memberUnitIds"]) > 1:
                actions.append("split")
            recommended_action = (
                "exclude" if is_automatic_exclusion else "assign"
            )
            exception = {
                "exceptionId": f"exception-{self._next_exception_number:04d}",
                "kind": "unit-cluster",
                "issueCode": "target-unresolved",
                "recommendedAction": recommended_action,
                "allowedActions": tuple(actions),
                "similarityKey": _review_similarity_key(
                    "target-unresolved",
                    recommended_action,
                    tuple(actions),
                    group["role"],
                    group["target"]["scope"],
                ),
                "groupIds": (group_id,),
                "memberUnitIds": tuple(group["memberUnitIds"]),
            }
            if is_automatic_exclusion:
                exception["recommendedReason"] = "duplicate"
            exceptions.append(exception)
            next_exception_number = self._next_exception_number + 1
        else:
            raise ValueError(
                "groupId must identify an automatic or user-resolved group"
            )
        self._commit_review(
            groups,
            exceptions,
            resolutions,
            operations,
            next_exception_number=next_exception_number,
        )
        self._undo_states = {}

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

    @staticmethod
    def _roster_candidate_state(candidate: RosterCandidate):
        participant_handles = tuple(
            f"participant-{index:04d}"
            for index, _row in enumerate(candidate.rows, start=1)
        )
        participant_display = tuple(
            {
                "participantHandle": handle,
                "name": row["name"],
                "identityHint": f"***-{row['identity'][-3:]}",
            }
            for handle, candidate_row in zip(
                participant_handles, candidate.rows
            )
            for row in (dict(candidate_row.values),)
        )
        roster_rows_private = tuple(
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
                participant_handles, candidate.rows
            )
            for row in (dict(candidate_row.values),)
        )
        return {
            "unitId": candidate.unit_id,
            "participantHandles": participant_handles,
            "participantDisplay": participant_display,
            "issues": candidate.blocking_issue_codes,
            "packageIssues": candidate.package_issue_codes,
            "rows": roster_rows_private,
            "columns": candidate.canonical_to_source_columns,
        }

    def _commit_roster_state(self, state):
        self._roster_unit_id = state["unitId"]
        self._participant_handles = state["participantHandles"]
        self._participant_display = state["participantDisplay"]
        self._roster_issues = state["issues"]
        self._roster_package_issues = state["packageIssues"]
        self._roster_rows_private = state["rows"]
        self._roster_columns_private = state["columns"]

    def _apply_roster_candidate(self, candidate: RosterCandidate):
        unit_id = candidate.unit_id
        if self._roster_unit_id is not None and self._roster_unit_id != unit_id:
            self._unit_decisions = {
                decision_unit_id: record
                for decision_unit_id, record in self._unit_decisions.items()
                if not (
                    record["decision"] in {"accepted", "reassigned"}
                    and record["target"]["participantHandles"]
                )
            }
        self._commit_roster_state(self._roster_candidate_state(candidate))
        self._invalidate_approved_package()

    def select_roster(self, mapping):
        mapping = _mapping(mapping, {"rosterUnitId"})
        unit_id = _string(mapping["rosterUnitId"], _UNIT_ID, "rosterUnitId")
        candidate = self._roster_candidates_by_id.get(unit_id)
        if candidate is None:
            raise ValueError(
                "rosterUnitId must identify an inspected roster worksheet"
            )
        if self._grouping_evidence is None:
            self._apply_roster_candidate(candidate)
            return
        if (
            unit_id not in self._roster_selection.candidate_unit_ids
            or candidate.blocking_issue_codes
            or candidate.package_issue_codes
            or not candidate.rows
        ):
            raise ValueError(
                "rosterUnitId must identify an eligible roster candidate"
            )
        selection = RosterSelection(
            status="selected",
            roster_unit_id=unit_id,
            candidate_unit_ids=self._roster_selection.candidate_unit_ids,
            issue_codes=(),
        )
        transition = self._prepare_grouped_roster_transition(
            candidate, selection, retire_existing_ids=True
        )
        self._commit_grouped_roster_transition(transition)

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
        _exact_mapping_keys(mapping)
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
        _exact_mapping_keys(mapping)
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

    def _group_review_digest(self):
        resolutions = []
        for exception_id in sorted(
            self._exception_resolutions, key=_numeric_opaque_id
        ):
            record = self._exception_resolutions[exception_id]
            value = {
                "exceptionId": exception_id,
                "action": record["action"],
                "requestedAction": record["requestedAction"],
            }
            if record["action"] == "assign":
                value["role"] = record["role"]
                value["target"] = {
                    "scope": record["target"]["scope"],
                    "participantHandles": list(
                        record["target"]["participantHandles"]
                    ),
                }
            else:
                value["reason"] = record["reason"]
            resolutions.append(value)
        automatic_exclusions = (
            [
                {
                    "unitId": item.unit_id,
                    "decision": item.decision,
                    "state": item.state,
                    "reason": item.reason,
                }
                for item in self._grouping_plan.automatic_exclusions
            ]
            if self._grouping_plan is not None
            else []
        )
        return {
            "groups": [
                self._group_projection(group) for group in self._review_groups
            ],
            "exceptions": [
                self._exception_projection(item)
                for item in self._review_exceptions
            ],
            "resolutions": resolutions,
            "operations": copy.deepcopy(self._review_operations),
            "automaticExclusions": automatic_exclusions,
            "coverage": self._review_coverage(),
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
        value = {
            "observationId": self._inspection.observation_id, "rosterUnitId": self._roster_unit_id,
            "participantHandles": list(self._participant_handles), "unitAssignments": assignments,
            "sourceDispositions": dispositions, "issueCodes": self._issue_codes(), "counts": self._counts(),
        }
        if self._grouping_evidence is not None:
            value["groupReview"] = self._group_review_digest()
        return value

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

    def _approved_result(self, summary):
        assignments, dispositions = self._public_assignments()
        return {
            "version": _VERSION, "outcome": "approved", "observationId": self._inspection.observation_id,
            "proposalDigest": summary["proposalDigest"], "readyToPrepare": True,
            "rosterUnitId": self._roster_unit_id, "participantHandles": list(self._participant_handles),
            "unitAssignments": assignments, "sourceDispositions": dispositions, "counts": self._counts(),
            "issueCodes": self._issue_codes(),
            "approval": {"status": "user-approved", "approvedProposalDigest": summary["proposalDigest"]},
        }

    def approve(self, expected_digest):
        if type(expected_digest) is not str or not re.fullmatch(r"[a-f0-9]{64}", expected_digest):
            raise ValueError("expected proposal digest must be a SHA-256 digest")
        summary = self.approval_summary()
        if not self._ready() or not hmac.compare_digest(expected_digest, summary["proposalDigest"]):
            raise ValueError("proposal is not ready for approval")
        self._approved_package_digest = summary["proposalDigest"]
        return self._approved_result(summary)

    def _authoritative_terminal_result(self, outcome, proposal_digest=None):
        """Return the exact state-owned terminal after a callback has completed."""
        if type(outcome) is not str:
            raise ValueError("terminal outcome must be an exact string")
        if outcome == "cancelled":
            if proposal_digest is not None:
                raise ValueError("cancelled terminal must not carry an approval digest")
            return self.cancelled_result()
        if outcome == "draft":
            if proposal_digest is not None:
                raise ValueError("draft terminal must not carry an approval digest")
            return self.draft_result()
        if outcome != "approved":
            raise ValueError("terminal outcome must be fixed")
        if (
            type(proposal_digest) is not str
            or re.fullmatch(r"[a-f0-9]{64}", proposal_digest) is None
            or self._approved_package_digest is None
            or not hmac.compare_digest(
                proposal_digest,
                self._approved_package_digest,
            )
        ):
            raise ValueError("approved terminal is not owned by this state")
        summary = self.approval_summary()
        if not hmac.compare_digest(proposal_digest, summary["proposalDigest"]):
            raise ValueError("approved terminal no longer matches proposal state")
        return self._approved_result(summary)

    def _clear_private_review_facts(self):
        """Drop caller-owned roster/grouping references after local review."""
        self._roster_candidates_by_id.clear()
        self._roster_rows_private = ()
        self._roster_columns_private = ()
        self._participant_display = ()
        self._snapshot_source = None
        self._observation = None
        self._grouping_evidence = None

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
