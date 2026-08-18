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
        self._roster_selection = selection
        if selection.status == "selected":
            self._apply_roster_candidate(
                self._roster_candidates_by_id[selection.roster_unit_id]
            )
            if grouping_evidence is not None:
                self._rebuild_grouping_plan()
        else:
            self._roster_issues = selection.issue_codes
            if grouping_evidence is not None:
                self._review_exceptions = [self._roster_exception(selection)]

    @classmethod
    def from_inspection(
        cls,
        observation,
        inspection,
        *,
        _snapshot_source=None,
        _grouping_evidence=None,
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
        return cls(
            observation,
            inspection,
            _snapshot_source,
            _grouping_evidence,
        )

    def _rebuild_grouping_plan(self):
        if self._grouping_evidence is None or self._roster_unit_id is None:
            self._grouping_plan = None
            self._review_groups = []
            self._review_exceptions = []
            self._exception_resolutions = {}
            self._review_operations = []
            self._undo_states = {}
            self._unit_decisions = {}
            self._source_dispositions = {}
            return
        candidate = self._roster_candidates_by_id[self._roster_unit_id]
        plan = build_grouping_plan(
            self._inspection,
            candidate,
            self._grouping_evidence,
        )
        expanded = plan.expand()
        _require_exact_unit_coverage(expanded, self._units_by_id)
        self._grouping_plan = plan
        self._review_groups = [
            self._review_group_from_plan(group) for group in plan.groups
        ]
        self._review_exceptions = [
            self._review_exception_from_plan(item, source=False)
            for item in plan.exceptions
        ] + [
            self._review_exception_from_plan(item, source=True)
            for item in plan.source_exceptions
        ]
        self._exception_resolutions = {}
        self._review_operations = []
        self._undo_states = {}
        self._unit_decisions = _proposal_decisions(expanded, self._units_by_id)
        self._source_dispositions = {
            item.evidence_id: {"decision": "unresolved"}
            for item in plan.source_exceptions
        }
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

    def _group_projection(self, group):
        resolved = any(
            item["kind"] == "unit-cluster"
            and group["groupId"] in item["groupIds"]
            and item["exceptionId"] in self._exception_resolutions
            for item in self._review_exceptions
        )
        return {
            "groupId": group["groupId"],
            "evidenceId": group["evidenceId"],
            "unitKind": group["unitKind"],
            "memberUnitIds": list(group["memberUnitIds"]),
            "firstUnitIndex": group["firstUnitIndex"],
            "lastUnitIndex": group["lastUnitIndex"],
            "role": group["role"],
            "target": self._target_projection(group["target"]),
            "state": "user-resolved" if resolved else group["state"],
            "checkCodes": list(group["checkCodes"]),
            "issueCodes": list(group["issueCodes"]),
        }

    @staticmethod
    def _exception_projection(item):
        value = {
            "exceptionId": item["exceptionId"],
            "kind": item["kind"],
            "issueCode": item["issueCode"],
            "recommendedAction": item["recommendedAction"],
            "allowedActions": list(item["allowedActions"]),
            "similarityKey": item["similarityKey"],
        }
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
        if self._grouping_plan is not None:
            covered_ids.update(
                item.unit_id for item in self._grouping_plan.automatic_exclusions
            )
        return {
            "groups": len(self._review_groups),
            "automaticallyOrganizedUnits": (
                (
                    len(self._grouping_plan.automatic_exclusions)
                    if self._grouping_plan is not None
                    else 0
                )
                + sum(
                    len(group["memberUnitIds"])
                    for group in self._review_groups
                    if group["state"] == "automatically-organized"
                )
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
        groups = [self._group_projection(group) for group in self._review_groups]
        exceptions = [
            self._exception_projection(item)
            for item in self._review_exceptions
            if item["exceptionId"] not in self._exception_resolutions
        ]
        summary = self.approval_summary()
        return {
            "roster": {
                "status": self._roster_selection.status,
                "rosterUnitId": self._roster_unit_id,
                "candidateUnitIds": list(
                    self._roster_selection.candidate_unit_ids
                ),
                "participantHandles": list(self._participant_handles),
                "issueCodes": list(self._roster_issues),
            },
            "review": {
                "groups": groups,
                "exceptions": exceptions,
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

    def _expanded_review(self, groups, exceptions, resolutions):
        if self._grouping_plan is None:
            raise ValueError("group review is unavailable until roster selection")
        if len({group["groupId"] for group in groups}) != len(groups):
            raise ValueError("group review IDs must be unique")
        if [group["groupId"] for group in groups] != [
            f"group-{index:04d}" for index in range(1, len(groups) + 1)
        ]:
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
            item.unit_id for item in self._grouping_plan.automatic_exclusions
        )
        if len(covered) != len(set(covered)) or set(covered) != set(self._units_by_id):
            raise ValueError("group review coverage must equal inspection units")

        exception_ids = [item["exceptionId"] for item in exceptions]
        if len(exception_ids) != len(set(exception_ids)) or exception_ids != [
            f"exception-{index:04d}"
            for index in range(1, len(exceptions) + 1)
        ]:
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
            item.evidence_id for item in self._grouping_plan.source_exceptions
        }
        if len(source_evidence_ids) != len(set(source_evidence_ids)) or set(
            source_evidence_ids
        ) != expected_source_ids:
            raise ValueError("source exception coverage must remain exact")

        expanded_by_id = {
            item.unit_id: item for item in self._grouping_plan.expand()
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
                target = GroupTarget(
                    resolution["target"]["scope"],
                    resolution["target"]["participantHandles"],
                )
                if any(
                    resolution["role"] not in _ROLES_BY_KIND[
                        self._units_by_id[unit_id].unit_kind
                    ]
                    for unit_id in item["memberUnitIds"]
                ):
                    raise ValueError("assigned role must support every exception unit")
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

    def _commit_review(self, groups, exceptions, resolutions, operations):
        expanded, source_dispositions = self._expanded_review(
            groups, exceptions, resolutions
        )
        self._review_groups = groups
        self._review_exceptions = exceptions
        self._exception_resolutions = resolutions
        self._review_operations = operations
        self._unit_decisions = _proposal_decisions(expanded, self._units_by_id)
        self._source_dispositions = source_dispositions
        self._invalidate_approved_package()

    @staticmethod
    def _recommended_source_reason(item):
        return {
            "source-exact-duplicate": "duplicate",
            "source-unreadable": "unreadable-replacement-available",
            "source-opaque": "intentionally-omitted",
            "source-unsupported": "intentionally-omitted",
            "source-encrypted": "intentionally-omitted",
            "source-over-limit": "intentionally-omitted",
            "source-not-applicable": "intentionally-omitted",
        }[item["issueCode"]]

    @staticmethod
    def _canonicalize_review(groups, exceptions, resolutions):
        groups.sort(
            key=lambda group: (
                _numeric_opaque_id(group["evidenceId"]),
                _numeric_opaque_id(group["memberUnitIds"][0]),
            )
        )
        group_id_map = {}
        for index, group in enumerate(groups, start=1):
            old_id = group["groupId"]
            new_id = f"group-{index:04d}"
            group_id_map[old_id] = new_id
            group["groupId"] = new_id
        for item in exceptions:
            if item["kind"] == "unit-cluster":
                item["groupIds"] = tuple(
                    group_id_map[group_id] for group_id in item["groupIds"]
                )
        group_by_id = {group["groupId"]: group for group in groups}
        exceptions.sort(
            key=lambda item: (
                _numeric_opaque_id(
                    item["evidenceId"]
                    if item["kind"] == "source"
                    else group_by_id[item["groupIds"][0]]["evidenceId"]
                ),
                0
                if item["kind"] == "source"
                else _numeric_opaque_id(item["memberUnitIds"][0]),
            )
        )
        new_resolutions = {}
        for index, item in enumerate(exceptions, start=1):
            old_id = item["exceptionId"]
            new_id = f"exception-{index:04d}"
            item["exceptionId"] = new_id
            if old_id in resolutions:
                new_resolutions[new_id] = resolutions[old_id]
        return groups, exceptions, new_resolutions

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
        allowed_actions = tuple(
            action
            for action in ("assign", "exclude", "split", "merge-next")
            if action in item["allowedActions"] or action == "merge-next"
        )
        for suffix, part in zip(("left", "right"), member_parts):
            first = self._units_by_id[part[0]]
            last = self._units_by_id[part[-1]]
            new_group = copy.deepcopy(group)
            new_group["groupId"] = f"temporary-{suffix}-{group_index}"
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
                    "exceptionId": f"temporary-{suffix}-{group_index}",
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
        groups[group_index:group_index + 1] = new_groups
        exceptions[:] = [
            value for value in exceptions if value["exceptionId"] != item["exceptionId"]
        ] + new_exceptions
        resolutions.pop(item["exceptionId"], None)
        return self._canonicalize_review(groups, exceptions, resolutions)

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
            "groupId": f"temporary-merge-{group_index}",
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
            "exceptionId": f"temporary-merge-{group_index}",
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
        return self._canonicalize_review(groups, exceptions, resolutions)

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
        plan = build_grouping_plan(
            self._inspection, candidate, self._grouping_evidence
        )
        _require_exact_unit_coverage(plan.expand(), self._units_by_id)
        self._apply_roster_candidate(candidate)
        self._roster_selection = RosterSelection(
            status="selected",
            roster_unit_id=roster_unit_id,
            candidate_unit_ids=self._roster_selection.candidate_unit_ids,
            issue_codes=(),
        )
        self._rebuild_grouping_plan()

    def resolve_exception(self, mapping):
        if type(mapping) is not dict:
            raise ValueError("proposal request must use its exact object shape")
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
            if action == "accept-recommendation":
                group = next(
                    group
                    for group in groups
                    if group["groupId"] == candidate_item["groupIds"][0]
                )
                role = group["role"]
                target = copy.deepcopy(group["target"])
            else:
                role = mapping["role"]
                if type(role) is not str:
                    raise ValueError("role must be an approved value")
                target = self._target(mapping["target"])
            for target_item in targets:
                resolutions[target_item["exceptionId"]] = {
                    "action": "assign",
                    "requestedAction": action,
                    "role": role,
                    "target": copy.deepcopy(target),
                }
        elif effective_action == "exclude":
            if action == "accept-recommendation":
                reason = self._recommended_source_reason(candidate_item)
            else:
                reason = _enum(
                    mapping["reason"], _EXCLUSION_REASONS, "reason"
                )
            for target_item in targets:
                target_reason = (
                    self._recommended_source_reason(target_item)
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
            groups, exceptions, resolutions = self._split_exception(
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
            groups, exceptions, resolutions = self._merge_next_exception(
                candidate_item, groups, exceptions, resolutions
            )
            operations.append(
                {
                    "action": "merge-next",
                    "memberUnitIds": list(candidate_item["memberUnitIds"]),
                }
            )
        self._commit_review(groups, exceptions, resolutions, operations)
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
        if not any(group["groupId"] == group_id for group in self._review_groups):
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
        if item is None:
            raise ValueError("groupId must identify a user-resolved group")
        groups, exceptions, resolutions, operations = self._transition_state()
        resolutions.pop(item["exceptionId"])
        self._commit_review(groups, exceptions, resolutions, operations)
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
