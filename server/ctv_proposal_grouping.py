"""Pure deterministic grouping and eligibility for local CTV proposal review."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import re
from typing import Literal
import unicodedata

from ctv_grouping_evidence import GroupingEvidence
from ctv_inspection_model import InspectionResult
from ctv_proposal_roster import RosterCandidate


GroupState = Literal["automatically-organized", "exception", "user-resolved"]
Scope = Literal["individual", "shared", "case"]
Decision = Literal["assign", "exclude", "unresolved"]


_MAX_UNITS = 10_000
_MAX_GROUPS = 10_000
_MAX_EXCEPTIONS = 10_000
_UNIT_ID = re.compile(r"unit-[0-9]{4,}\Z", re.ASCII)
_EVIDENCE_ID = re.compile(r"evidence-[0-9]{4,}\Z", re.ASCII)
_GROUP_ID = re.compile(r"group-[0-9]{4,}\Z", re.ASCII)
_EXCEPTION_ID = re.compile(r"exception-[0-9]{4,}\Z", re.ASCII)
_PARTICIPANT_HANDLE = re.compile(r"participant-[0-9]{4,}\Z", re.ASCII)
_SIMILARITY_KEY = re.compile(r"similarity-[a-f0-9]{16}\Z", re.ASCII)
_UNIT_KINDS = frozenset({"pdf-page", "worksheet", "image"})
_SCOPES = frozenset({"individual", "shared", "case"})
_GROUP_STATES = frozenset(
    {"automatically-organized", "exception", "user-resolved"}
)
_CONCRETE_ROLES = frozenset(
    {
        "payment-roster",
        "service-contract",
        "acceptance-record",
        "payment-tax-form",
        "identity-front",
        "identity-back",
        "shared-supporting-evidence",
        "other-supporting-evidence",
    }
)
_ROLES_BY_KIND = {
    "pdf-page": _CONCRETE_ROLES,
    "worksheet": frozenset({"payment-roster", "other-supporting-evidence"}),
    "image": frozenset(
        {
            "identity-front",
            "identity-back",
            "shared-supporting-evidence",
            "other-supporting-evidence",
        }
    ),
}
_SCOPES_BY_ROLE = {
    "payment-roster": frozenset({"case"}),
    "service-contract": frozenset({"individual", "shared", "case"}),
    "acceptance-record": frozenset({"individual", "shared", "case"}),
    "payment-tax-form": frozenset({"individual"}),
    "identity-front": frozenset({"individual"}),
    "identity-back": frozenset({"individual"}),
    "shared-supporting-evidence": frozenset({"shared", "case"}),
    "other-supporting-evidence": frozenset({"individual", "shared", "case"}),
}
_AUTO_CHECK_ORDER = (
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
_CHECK_POSITION = {code: index for index, code in enumerate(_AUTO_CHECK_ORDER)}
_UNIT_ISSUE_ORDER = (
    "private-fact-incomplete",
    "participant-name-only",
    "participant-identity-only",
    "participant-no-match",
    "participant-multiple-match",
    "participant-identity-conflict",
    "role-uncertain",
    "role-gap-conflict",
    "role-scope-unsupported",
    "packet-structure-incoherent",
    "source-issue-present",
    "unit-issue-present",
)
_SOURCE_ISSUE_ORDER = (
    "source-opaque",
    "source-unsupported",
    "source-unreadable",
    "source-encrypted",
    "source-over-limit",
    "source-not-applicable",
    "source-exact-duplicate",
)
_UNIT_ISSUES = frozenset(_UNIT_ISSUE_ORDER)
_SOURCE_ISSUES = frozenset(_SOURCE_ISSUE_ORDER)
_ACTION_ORDER = (
    "accept-recommendation",
    "assign",
    "exclude",
    "split",
    "merge-next",
    "choose-roster",
)
_ACTION_POSITION = {action: index for index, action in enumerate(_ACTION_ORDER)}
_EXCLUSION_REASONS = frozenset(
    {
        "duplicate",
        "irrelevant",
        "unreadable-replacement-available",
        "intentionally-omitted",
        "other",
    }
)


def _exact_string(value, name: str) -> str:
    if type(value) is not str:
        raise TypeError(f"{name} must be an exact string")
    return value


def _opaque_id(value, pattern: re.Pattern[str], name: str) -> str:
    value = _exact_string(value, name)
    if pattern.fullmatch(value) is None:
        raise ValueError(f"{name} must be a valid opaque ID")
    return value


def _exact_tuple(value, name: str) -> tuple:
    if type(value) is not tuple:
        raise TypeError(f"{name} must be an exact tuple")
    return value


def _numeric_id(value: str) -> int:
    return int(value.rsplit("-", 1)[1])


def _opaque_ids(value, pattern: re.Pattern[str], name: str) -> tuple[str, ...]:
    values = _exact_tuple(value, name)
    for item in values:
        _opaque_id(item, pattern, name)
    return values


def _ordered_codes(value, positions: dict[str, int], name: str) -> tuple[str, ...]:
    values = _exact_tuple(value, name)
    if any(type(item) is not str or item not in positions for item in values):
        raise ValueError(f"{name} must use approved codes")
    if len(values) != len(set(values)) or values != tuple(
        sorted(values, key=positions.__getitem__)
    ):
        raise ValueError(f"{name} must use unique canonical order")
    return values


def _require_role_scope(role: str, target: "GroupTarget") -> None:
    if role not in _CONCRETE_ROLES:
        raise ValueError("role must be a concrete supported role")
    if target.scope not in _SCOPES_BY_ROLE[role]:
        raise ValueError("role is unsupported for target scope")


def _automatic_checks(target: "GroupTarget") -> tuple[str, ...]:
    participant_checks = (
        ("participant-name-match", "participant-identity-match")
        if target.scope in {"individual", "shared"}
        else ()
    )
    required = {
        "roster-selected",
        *participant_checks,
        "role-concrete",
        "role-scope-supported",
        "source-range-contiguous",
        "packet-structure-coherent",
        "target-unambiguous",
        "source-issues-clear",
        "unit-issues-clear",
        "coverage-exact",
    }
    return tuple(code for code in _AUTO_CHECK_ORDER if code in required)


@dataclass(frozen=True)
class GroupTarget:
    scope: Scope
    participant_handles: tuple[str, ...]

    def __post_init__(self) -> None:
        scope = _exact_string(self.scope, "scope")
        if scope not in _SCOPES:
            raise ValueError("scope must be supported")
        handles = _opaque_ids(
            self.participant_handles,
            _PARTICIPANT_HANDLE,
            "participant_handles",
        )
        numeric = tuple(_numeric_id(handle) for handle in handles)
        if len(handles) > _MAX_UNITS:
            raise ValueError("participant handle count exceeds hard limit")
        if len(handles) != len(set(handles)) or numeric != tuple(sorted(numeric)):
            raise ValueError("participant_handles must be unique and ordered")
        if (
            (scope == "individual" and len(handles) != 1)
            or (scope == "shared" and len(handles) < 2)
            or (scope == "case" and handles)
        ):
            raise ValueError("participant_handles must agree with scope")


@dataclass(frozen=True)
class ReviewGroup:
    group_id: str
    evidence_id: str
    unit_kind: str
    member_unit_ids: tuple[str, ...]
    first_unit_index: int
    last_unit_index: int
    role: str
    target: GroupTarget
    state: GroupState
    check_codes: tuple[str, ...]
    issue_codes: tuple[str, ...]

    def __post_init__(self) -> None:
        _opaque_id(self.group_id, _GROUP_ID, "group_id")
        _opaque_id(self.evidence_id, _EVIDENCE_ID, "evidence_id")
        unit_kind = _exact_string(self.unit_kind, "unit_kind")
        if unit_kind not in _UNIT_KINDS:
            raise ValueError("unit_kind must be supported")
        members = _opaque_ids(self.member_unit_ids, _UNIT_ID, "member_unit_ids")
        if not members or len(members) > _MAX_UNITS:
            raise ValueError("member_unit_ids must be nonempty and bounded")
        numeric_members = tuple(_numeric_id(member) for member in members)
        if numeric_members != tuple(sorted(numeric_members)):
            raise ValueError("member_unit_ids must be in numeric order")
        if len(members) != len(set(members)):
            raise ValueError("group coverage must equal inspection units")
        if type(self.first_unit_index) is not int or type(self.last_unit_index) is not int:
            raise TypeError("unit indexes must be exact integers")
        maximum = {"pdf-page": 10_000, "worksheet": 100, "image": 1}[unit_kind]
        if not (
            1 <= self.first_unit_index <= self.last_unit_index <= maximum
            and self.last_unit_index - self.first_unit_index + 1 == len(members)
        ):
            raise ValueError("unit indexes must describe one contiguous bounded range")
        state = _exact_string(self.state, "state")
        if state not in _GROUP_STATES:
            raise ValueError("state must be supported")
        role = _exact_string(self.role, "role")
        if not (
            role in _ROLES_BY_KIND[unit_kind]
            or (state == "exception" and role == "unknown")
        ):
            raise ValueError("role must be supported for unit_kind")
        if type(self.target) is not GroupTarget:
            raise TypeError("target must be an exact GroupTarget")
        self.target.__post_init__()
        if state != "exception":
            _require_role_scope(role, self.target)
        checks = _ordered_codes(self.check_codes, _CHECK_POSITION, "check_codes")
        issues = _exact_tuple(self.issue_codes, "issue_codes")
        if any(type(issue) is not str or issue not in _UNIT_ISSUES for issue in issues):
            raise ValueError("issue_codes must use approved unit issue codes")
        positions = {code: index for index, code in enumerate(_UNIT_ISSUE_ORDER)}
        if len(issues) != len(set(issues)) or issues != tuple(
            sorted(issues, key=positions.__getitem__)
        ):
            raise ValueError("issue_codes must use unique canonical order")
        if state == "automatically-organized":
            if checks != _automatic_checks(self.target) or issues:
                raise ValueError("automatic groups must retain every eligibility check")
        elif state == "exception" and not issues:
            raise ValueError("exception groups must retain a blocking issue")


@dataclass(frozen=True)
class ExceptionCluster:
    exception_id: str
    group_ids: tuple[str, ...]
    member_unit_ids: tuple[str, ...]
    issue_code: str
    recommended_action: str
    allowed_actions: tuple[str, ...]
    similarity_key: str

    def __post_init__(self) -> None:
        _opaque_id(self.exception_id, _EXCEPTION_ID, "exception_id")
        group_ids = _opaque_ids(self.group_ids, _GROUP_ID, "group_ids")
        members = _opaque_ids(self.member_unit_ids, _UNIT_ID, "member_unit_ids")
        if not group_ids or not members:
            raise ValueError("exception clusters must identify groups and units")
        if len(group_ids) > _MAX_GROUPS or len(members) > _MAX_UNITS:
            raise ValueError("exception cluster exceeds hard limit")
        if (
            len(group_ids) != len(set(group_ids))
            or tuple(map(_numeric_id, group_ids))
            != tuple(sorted(map(_numeric_id, group_ids)))
            or len(members) != len(set(members))
            or tuple(map(_numeric_id, members))
            != tuple(sorted(map(_numeric_id, members)))
        ):
            raise ValueError("exception cluster IDs must be unique and ordered")
        issue = _exact_string(self.issue_code, "issue_code")
        if issue not in _UNIT_ISSUES:
            raise ValueError("issue_code must be an approved unit issue")
        action = _exact_string(self.recommended_action, "recommended_action")
        if action not in _ACTION_POSITION:
            raise ValueError("recommended_action must be approved")
        actions = _ordered_codes(
            self.allowed_actions, _ACTION_POSITION, "allowed_actions"
        )
        if not actions or action not in actions:
            raise ValueError("recommended_action must be allowed")
        key = _exact_string(self.similarity_key, "similarity_key")
        if _SIMILARITY_KEY.fullmatch(key) is None:
            raise ValueError("similarity_key must be a fixed opaque key")


@dataclass(frozen=True)
class SourceException:
    exception_id: str
    evidence_id: str
    issue_code: str
    recommended_action: str
    allowed_actions: tuple[str, ...]
    similarity_key: str

    def __post_init__(self) -> None:
        _opaque_id(self.exception_id, _EXCEPTION_ID, "exception_id")
        _opaque_id(self.evidence_id, _EVIDENCE_ID, "evidence_id")
        issue = _exact_string(self.issue_code, "issue_code")
        if issue not in _SOURCE_ISSUES:
            raise ValueError("issue_code must be an approved source issue")
        action = _exact_string(self.recommended_action, "recommended_action")
        if action not in _ACTION_POSITION:
            raise ValueError("recommended_action must be approved")
        actions = _ordered_codes(
            self.allowed_actions, _ACTION_POSITION, "allowed_actions"
        )
        if not actions or action not in actions:
            raise ValueError("recommended_action must be allowed")
        key = _exact_string(self.similarity_key, "similarity_key")
        if _SIMILARITY_KEY.fullmatch(key) is None:
            raise ValueError("similarity_key must be a fixed opaque key")


@dataclass(frozen=True)
class ExpandedDecision:
    unit_id: str
    decision: Decision
    group_id: str | None
    state: GroupState
    role: str
    target: GroupTarget | None
    reason: str

    def __post_init__(self) -> None:
        _opaque_id(self.unit_id, _UNIT_ID, "unit_id")
        decision = _exact_string(self.decision, "decision")
        if decision not in {"assign", "exclude", "unresolved"}:
            raise ValueError("decision must be supported")
        if self.group_id is not None:
            _opaque_id(self.group_id, _GROUP_ID, "group_id")
        state = _exact_string(self.state, "state")
        if state not in _GROUP_STATES:
            raise ValueError("state must be supported")
        role = _exact_string(self.role, "role")
        reason = _exact_string(self.reason, "reason")
        if decision == "assign":
            if (
                self.group_id is None
                or state not in {"automatically-organized", "user-resolved"}
                or type(self.target) is not GroupTarget
                or reason
            ):
                raise ValueError("assign decision fields must use the closed shape")
            self.target.__post_init__()
            _require_role_scope(role, self.target)
        elif decision == "exclude":
            if (
                self.group_id is not None
                or state not in {"automatically-organized", "user-resolved"}
                or role
                or self.target is not None
                or reason not in _EXCLUSION_REASONS
                or (state == "automatically-organized" and reason != "duplicate")
            ):
                raise ValueError("exclude decision fields must use the closed shape")
        elif (
            state != "exception"
            or role
            or self.target is not None
            or reason
        ):
            raise ValueError("unresolved decision fields must use the closed shape")


@dataclass(frozen=True)
class GroupingPlan:
    roster_unit_id: str
    groups: tuple[ReviewGroup, ...]
    exceptions: tuple[ExceptionCluster, ...]
    source_exceptions: tuple[SourceException, ...]
    expected_unit_ids: tuple[str, ...]
    automatic_exclusions: tuple[ExpandedDecision, ...] = ()

    def __post_init__(self) -> None:
        roster_unit_id = _opaque_id(
            self.roster_unit_id, _UNIT_ID, "roster_unit_id"
        )
        groups = _exact_tuple(self.groups, "groups")
        exceptions = _exact_tuple(self.exceptions, "exceptions")
        source_exceptions = _exact_tuple(
            self.source_exceptions, "source_exceptions"
        )
        exclusions = _exact_tuple(
            self.automatic_exclusions, "automatic_exclusions"
        )
        expected = _opaque_ids(
            self.expected_unit_ids, _UNIT_ID, "expected_unit_ids"
        )
        if len(groups) > _MAX_GROUPS:
            raise ValueError("group count exceeds hard limit")
        if len(exceptions) + len(source_exceptions) > _MAX_EXCEPTIONS:
            raise ValueError("exception count exceeds hard limit")
        if len(expected) > _MAX_UNITS or len(exclusions) > _MAX_UNITS:
            raise ValueError("unit count exceeds hard limit")
        if any(type(group) is not ReviewGroup for group in groups):
            raise TypeError("groups must contain exact ReviewGroup records")
        if any(type(item) is not ExceptionCluster for item in exceptions):
            raise TypeError("exceptions must contain exact ExceptionCluster records")
        if any(type(item) is not SourceException for item in source_exceptions):
            raise TypeError("source_exceptions must contain exact SourceException records")
        if any(type(item) is not ExpandedDecision for item in exclusions):
            raise TypeError("automatic_exclusions must contain exact ExpandedDecision records")
        for record in (*groups, *exceptions, *source_exceptions, *exclusions):
            record.__post_init__()
        expected_group_ids = tuple(
            f"group-{index:04d}" for index in range(1, len(groups) + 1)
        )
        if tuple(group.group_id for group in groups) != expected_group_ids:
            raise ValueError("groups must use canonical ordered IDs")
        group_order = tuple(
            (_numeric_id(group.evidence_id), _numeric_id(group.member_unit_ids[0]))
            for group in groups
        )
        if group_order != tuple(sorted(group_order)):
            raise ValueError("groups must follow canonical source/unit order")
        expected_numeric = tuple(map(_numeric_id, expected))
        if (
            len(expected) != len(set(expected))
            or expected_numeric != tuple(sorted(expected_numeric))
        ):
            raise ValueError("expected unit IDs must be unique and ordered")
        if roster_unit_id not in expected:
            raise ValueError("roster_unit_id must identify an expected unit")
        exception_ids = tuple(
            item.exception_id for item in (*exceptions, *source_exceptions)
        )
        exception_numbers = tuple(sorted(map(_numeric_id, exception_ids)))
        if (
            len(exception_ids) != len(set(exception_ids))
            or exception_numbers != tuple(range(1, len(exception_ids) + 1))
        ):
            raise ValueError("exceptions must use unique canonical IDs")
        groups_by_id = {group.group_id: group for group in groups}
        clustered_group_ids = []
        for cluster in exceptions:
            if any(group_id not in groups_by_id for group_id in cluster.group_ids):
                raise ValueError("exception clusters must reference known groups")
            clustered_group_ids.extend(cluster.group_ids)
            clustered_members = tuple(
                member
                for group_id in cluster.group_ids
                for member in groups_by_id[group_id].member_unit_ids
            )
            if (
                cluster.member_unit_ids != clustered_members
                or any(
                    groups_by_id[group_id].state != "exception"
                    or cluster.issue_code not in groups_by_id[group_id].issue_codes
                    for group_id in cluster.group_ids
                )
            ):
                raise ValueError("exception clusters must match failed groups")
        failed_group_ids = tuple(
            group.group_id for group in groups if group.state == "exception"
        )
        if (
            tuple(sorted(clustered_group_ids, key=_numeric_id)) != failed_group_ids
            or len(clustered_group_ids) != len(set(clustered_group_ids))
        ):
            raise ValueError("exception groups must match clusters")
        if any(
            item.decision != "exclude"
            or item.state != "automatically-organized"
            or item.reason != "duplicate"
            for item in exclusions
        ):
            raise ValueError("automatic exclusions must be exact duplicate decisions")
        if tuple(map(lambda item: _numeric_id(item.unit_id), exclusions)) != tuple(
            sorted(_numeric_id(item.unit_id) for item in exclusions)
        ):
            raise ValueError("automatic exclusions must be ordered")
        coverage = [
            member for group in groups for member in group.member_unit_ids
        ] + [item.unit_id for item in exclusions]
        if (
            len(coverage) != len(set(coverage))
            or set(coverage) != set(expected)
        ):
            raise ValueError("group coverage must equal inspection units")
        source_ids = tuple(item.evidence_id for item in source_exceptions)
        if len(source_ids) != len(set(source_ids)):
            raise ValueError("source exceptions must identify unique sources")
        if tuple(map(_numeric_id, source_ids)) != tuple(
            sorted(map(_numeric_id, source_ids))
        ):
            raise ValueError("source exceptions must be ordered")

    @property
    def covered_unit_ids(self) -> tuple[str, ...]:
        return tuple(sorted(self.expected_unit_ids, key=_numeric_id))

    def expand(self) -> tuple[ExpandedDecision, ...]:
        expanded = list(self.automatic_exclusions)
        for group in self.groups:
            for unit_id in group.member_unit_ids:
                if group.state == "exception":
                    expanded.append(
                        ExpandedDecision(
                            unit_id=unit_id,
                            decision="unresolved",
                            group_id=group.group_id,
                            state="exception",
                            role="",
                            target=None,
                            reason="",
                        )
                    )
                else:
                    expanded.append(
                        ExpandedDecision(
                            unit_id=unit_id,
                            decision="assign",
                            group_id=group.group_id,
                            state=group.state,
                            role=group.role,
                            target=group.target,
                            reason="",
                        )
                    )
        expanded.sort(key=lambda item: _numeric_id(item.unit_id))
        unit_ids = tuple(item.unit_id for item in expanded)
        if (
            len(unit_ids) != len(set(unit_ids))
            or unit_ids != self.covered_unit_ids
        ):
            raise ValueError("expanded coverage must equal inspection units")
        return tuple(expanded)

    def to_digest_input(self) -> bytes:
        def target_value(target: GroupTarget) -> dict[str, object]:
            return {
                "scope": target.scope,
                "participantHandles": list(target.participant_handles),
            }

        value = {
            "rosterUnitId": self.roster_unit_id,
            "groups": [
                {
                    "groupId": group.group_id,
                    "evidenceId": group.evidence_id,
                    "unitKind": group.unit_kind,
                    "memberUnitIds": list(group.member_unit_ids),
                    "firstUnitIndex": group.first_unit_index,
                    "lastUnitIndex": group.last_unit_index,
                    "role": group.role,
                    "target": target_value(group.target),
                    "state": group.state,
                    "checkCodes": list(group.check_codes),
                    "issueCodes": list(group.issue_codes),
                }
                for group in self.groups
            ],
            "exceptions": [
                {
                    "exceptionId": item.exception_id,
                    "groupIds": list(item.group_ids),
                    "memberUnitIds": list(item.member_unit_ids),
                    "issueCode": item.issue_code,
                    "recommendedAction": item.recommended_action,
                    "allowedActions": list(item.allowed_actions),
                    "similarityKey": item.similarity_key,
                }
                for item in self.exceptions
            ],
            "sourceExceptions": [
                {
                    "exceptionId": item.exception_id,
                    "evidenceId": item.evidence_id,
                    "issueCode": item.issue_code,
                    "recommendedAction": item.recommended_action,
                    "allowedActions": list(item.allowed_actions),
                    "similarityKey": item.similarity_key,
                }
                for item in self.source_exceptions
            ],
            "automaticExclusions": [
                {
                    "unitId": item.unit_id,
                    "decision": item.decision,
                    "groupId": item.group_id,
                    "state": item.state,
                    "role": item.role,
                    "target": None,
                    "reason": item.reason,
                }
                for item in self.automatic_exclusions
            ],
            "coveredUnitIds": list(self.covered_unit_ids),
        }
        return json.dumps(
            value,
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("ascii")


@dataclass(frozen=True)
class _UnitDraft:
    unit: object
    role: str
    target: GroupTarget
    issue_code: str | None
    participant_established: bool
    source_issues_clear: bool
    unit_issues_clear: bool


@dataclass
class _UnitSeed:
    unit: object
    complete: bool
    participant_handle: str | None
    participant_issue: str | None
    target: GroupTarget | None
    participant_established: bool
    role: str
    issue_code: str | None


def _normalize_private(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value)
    characters = []
    previous_space = True
    for character in normalized.upper():
        if unicodedata.combining(character):
            continue
        if character.isalnum():
            characters.append(character)
            previous_space = False
        elif not previous_space:
            characters.append(" ")
            previous_space = True
    return "".join(characters).strip()


def _contains_words(words: tuple[str, ...], pattern: tuple[str, ...]) -> bool:
    if not pattern or len(pattern) > len(words):
        return False
    width = len(pattern)
    return any(words[index : index + width] == pattern for index in range(len(words) - width + 1))


def _participant_fact(
    normalized_text: str,
    roster_patterns: tuple[tuple[str, tuple[str, ...], tuple[str, ...]], ...],
) -> tuple[str | None, str | None]:
    words = tuple(normalized_text.split())
    name_handles = tuple(
        handle
        for handle, name_words, _identity_words in roster_patterns
        if _contains_words(words, name_words)
    )
    identity_handles = tuple(
        handle
        for handle, _name_words, identity_words in roster_patterns
        if _contains_words(words, identity_words)
    )
    if not name_handles and not identity_handles:
        return None, None
    if len(name_handles) == 1 and len(identity_handles) == 1:
        if name_handles[0] == identity_handles[0]:
            return name_handles[0], None
        return None, "participant-identity-conflict"
    if name_handles and not identity_handles:
        return None, (
            "participant-name-only"
            if len(name_handles) == 1
            else "participant-multiple-match"
        )
    if identity_handles and not name_handles:
        return None, (
            "participant-identity-only"
            if len(identity_handles) == 1
            else "participant-multiple-match"
        )
    return None, "participant-multiple-match"


def _source_drafts(
    source,
    source_units: tuple,
    roster: RosterCandidate,
    roster_patterns: tuple[tuple[str, tuple[str, ...], tuple[str, ...]], ...],
    evidence: GroupingEvidence,
) -> tuple[_UnitDraft, ...]:
    source_has_issues = bool(source.issue_codes)
    seeds = []
    for unit in source_units:
        complete = evidence.complete_for(
            unit.evidence_id, unit.unit_kind, unit.unit_index
        )
        participant_handle = None
        participant_issue = None
        if complete and unit.unit_id != roster.unit_id:
            participant_handle, participant_issue = _participant_fact(
                evidence.text_for(
                    unit.evidence_id, unit.unit_kind, unit.unit_index
                ),
                roster_patterns,
            )
        role = (
            unit.suggested_role
            if unit.suggested_role != "unknown" and unit.confidence_band == "high"
            else "unknown"
        )
        issue_code = None
        if not complete:
            issue_code = "private-fact-incomplete"
        elif participant_issue is not None:
            issue_code = participant_issue
        elif source_has_issues:
            issue_code = "source-issue-present"
        elif unit.issue_codes:
            issue_code = "unit-issue-present"
        elif "multiple-role-signals" in unit.signal_codes:
            issue_code = "role-uncertain"
        elif unit.suggested_role != "unknown" and unit.confidence_band != "high":
            issue_code = "role-uncertain"
        seeds.append(
            _UnitSeed(
                unit=unit,
                complete=complete,
                participant_handle=participant_handle,
                participant_issue=participant_issue,
                target=None,
                participant_established=False,
                role=role,
                issue_code=issue_code,
            )
        )

    current_handle = None
    for seed in seeds:
        if seed.unit.unit_id == roster.unit_id:
            current_handle = None
            seed.target = GroupTarget("case", ())
        elif not seed.complete or seed.participant_issue is not None:
            current_handle = None
            seed.target = GroupTarget("case", ())
        elif seed.participant_handle is not None:
            current_handle = seed.participant_handle
            seed.participant_established = True
            seed.target = GroupTarget("individual", (current_handle,))
        elif current_handle is not None:
            seed.participant_established = True
            seed.target = GroupTarget("individual", (current_handle,))
        else:
            seed.target = GroupTarget("case", ())

    expected_indexes = tuple(range(1, len(seeds) + 1))
    actual_indexes = tuple(seed.unit.unit_index for seed in seeds)
    if actual_indexes != expected_indexes:
        for seed in seeds:
            if seed.issue_code is None:
                seed.issue_code = "packet-structure-incoherent"

    participant_anchors = tuple(
        index for index, seed in enumerate(seeds) if seed.participant_handle is not None
    )
    role_anchors = tuple(
        index
        for index, seed in enumerate(seeds)
        if seed.role != "unknown" and seed.issue_code is None
    )
    for index, seed in enumerate(seeds):
        if seed.role != "unknown" or seed.issue_code is not None:
            continue
        previous = None
        cursor = index - 1
        while cursor >= 0:
            candidate = seeds[cursor]
            if (
                (
                    candidate.issue_code is not None
                    and candidate.issue_code != "role-gap-conflict"
                )
                or candidate.target != seed.target
                or candidate.unit.unit_kind != seed.unit.unit_kind
            ):
                break
            if candidate.role != "unknown":
                previous = candidate
                break
            cursor -= 1
        following = None
        cursor = index + 1
        while cursor < len(seeds):
            candidate = seeds[cursor]
            if (
                (
                    candidate.issue_code is not None
                    and candidate.issue_code != "role-gap-conflict"
                )
                or candidate.target != seed.target
                or candidate.unit.unit_kind != seed.unit.unit_kind
            ):
                break
            if candidate.role != "unknown":
                following = candidate
                break
            cursor += 1
        if previous is not None and following is not None:
            if previous.role == following.role:
                seed.role = previous.role
            else:
                seed.issue_code = "role-gap-conflict"
        elif (
            previous is not None
            and following is None
            and not participant_anchors
            and seed.target == GroupTarget("case", ())
            and len(role_anchors) == 1
            and role_anchors[0] < index
        ):
            seed.role = previous.role
        else:
            seed.issue_code = "role-uncertain"

    for seed in seeds:
        assert seed.target is not None
        if seed.issue_code is not None or seed.role == "unknown":
            continue
        if seed.target.scope not in _SCOPES_BY_ROLE[seed.role]:
            if (
                not seed.participant_established
                and _SCOPES_BY_ROLE[seed.role] == frozenset({"individual"})
            ):
                seed.issue_code = "participant-no-match"
            else:
                seed.issue_code = "role-scope-unsupported"

    return tuple(
        _UnitDraft(
            unit=seed.unit,
            role=seed.role,
            target=seed.target,
            issue_code=seed.issue_code,
            participant_established=seed.participant_established,
            source_issues_clear=not source_has_issues,
            unit_issues_clear=not seed.unit.issue_codes,
        )
        for seed in seeds
    )


_ISOLATED_ISSUES = frozenset(
    {
        "private-fact-incomplete",
        "participant-name-only",
        "participant-identity-only",
        "participant-no-match",
        "participant-multiple-match",
        "participant-identity-conflict",
    }
)


def _draft_ranges(drafts: tuple[_UnitDraft, ...]) -> tuple[tuple[_UnitDraft, ...], ...]:
    ranges = []
    current = []
    for draft in drafts:
        compatible = bool(current) and (
            current[-1].unit.unit_index + 1 == draft.unit.unit_index
            and current[-1].unit.unit_kind == draft.unit.unit_kind
            and current[-1].role == draft.role
            and current[-1].target == draft.target
            and current[-1].issue_code == draft.issue_code
            and current[-1].issue_code not in _ISOLATED_ISSUES
            and draft.issue_code not in _ISOLATED_ISSUES
        )
        if current and not compatible:
            ranges.append(tuple(current))
            current = []
        current.append(draft)
    if current:
        ranges.append(tuple(current))
    return tuple(ranges)


def _exception_checks(draft: _UnitDraft) -> tuple[str, ...]:
    checks = {"roster-selected", "source-range-contiguous", "coverage-exact"}
    if draft.participant_established:
        checks.update({"participant-name-match", "participant-identity-match"})
    if draft.role != "unknown":
        checks.add("role-concrete")
        if draft.target.scope in _SCOPES_BY_ROLE[draft.role]:
            checks.add("role-scope-supported")
    if draft.issue_code != "packet-structure-incoherent":
        checks.add("packet-structure-coherent")
    if draft.issue_code not in {
        "private-fact-incomplete",
        "participant-name-only",
        "participant-identity-only",
        "participant-no-match",
        "participant-multiple-match",
        "participant-identity-conflict",
    }:
        checks.add("target-unambiguous")
    if draft.source_issues_clear:
        checks.add("source-issues-clear")
    if draft.unit_issues_clear:
        checks.add("unit-issues-clear")
    return tuple(code for code in _AUTO_CHECK_ORDER if code in checks)


def _similarity_key(
    issue_code: str,
    recommended_action: str,
    allowed_actions: tuple[str, ...],
    role: str,
    scope: str,
) -> str:
    fixed = "|".join(
        (issue_code, recommended_action, ",".join(allowed_actions), role, scope)
    )
    return "similarity-" + hashlib.sha256(fixed.encode("ascii")).hexdigest()[:16]


def _make_exception(
    number: int,
    group: ReviewGroup,
    issue_code: str,
) -> ExceptionCluster:
    allowed_actions = (
        ("assign", "exclude", "split")
        if issue_code in {"role-uncertain", "role-gap-conflict"}
        else ("assign", "exclude")
    )
    recommended_action = "assign"
    return ExceptionCluster(
        exception_id=f"exception-{number:04d}",
        group_ids=(group.group_id,),
        member_unit_ids=group.member_unit_ids,
        issue_code=issue_code,
        recommended_action=recommended_action,
        allowed_actions=allowed_actions,
        similarity_key=_similarity_key(
            issue_code,
            recommended_action,
            allowed_actions,
            group.role,
            group.target.scope,
        ),
    )


def _source_issue(status: str) -> str:
    return {
        "opaque": "source-opaque",
        "unsupported": "source-unsupported",
        "unreadable": "source-unreadable",
        "encrypted": "source-encrypted",
        "over-limit": "source-over-limit",
        "not-applicable": "source-not-applicable",
        "inspected": "source-not-applicable",
    }[status]


def _make_source_exception(
    number: int,
    evidence_id: str,
    issue_code: str,
) -> SourceException:
    allowed_actions = ("exclude",)
    recommended_action = "exclude"
    return SourceException(
        exception_id=f"exception-{number:04d}",
        evidence_id=evidence_id,
        issue_code=issue_code,
        recommended_action=recommended_action,
        allowed_actions=allowed_actions,
        similarity_key=_similarity_key(
            issue_code,
            recommended_action,
            allowed_actions,
            "unknown",
            "case",
        ),
    )


def build_grouping_plan(inspection, roster, evidence) -> GroupingPlan:
    """Build a deterministic review grouping plan from bounded local facts."""
    if type(inspection) is not InspectionResult:
        raise TypeError("inspection must be an exact InspectionResult")
    if type(roster) is not RosterCandidate:
        raise TypeError("roster must be an exact RosterCandidate")
    if type(evidence) is not GroupingEvidence:
        raise TypeError("evidence must be exact GroupingEvidence")
    inspection.__post_init__()
    roster.__post_init__()
    if roster.blocking_issue_codes or roster.package_issue_codes or not roster.rows:
        raise ValueError("roster must be uniquely eligible and package-complete")

    units_by_id = {unit.unit_id: unit for unit in inspection.units}
    if len(units_by_id) != len(inspection.units):
        raise ValueError("inspection units must use unique opaque IDs")
    roster_unit = units_by_id.get(roster.unit_id)
    if roster_unit is None or (
        roster_unit.evidence_id != roster.evidence_id
        or roster_unit.unit_kind != "worksheet"
        or roster_unit.unit_index != roster.worksheet_index
        or roster_unit.suggested_role != "payment-roster"
    ):
        raise ValueError("roster must identify the selected payment worksheet")

    canonical_sources = tuple(
        sorted(inspection.sources, key=lambda item: _numeric_id(item.evidence_id))
    )
    units_by_evidence = {source.evidence_id: [] for source in canonical_sources}
    for unit in inspection.units:
        units_by_evidence[unit.evidence_id].append(unit)
    for source_units in units_by_evidence.values():
        source_units.sort(key=lambda item: (item.unit_index, _numeric_id(item.unit_id)))
    canonical_units = tuple(
        unit
        for source in canonical_sources
        for unit in units_by_evidence[source.evidence_id]
    )
    canonical_numeric_ids = tuple(_numeric_id(unit.unit_id) for unit in canonical_units)
    if canonical_numeric_ids != tuple(sorted(canonical_numeric_ids)):
        raise ValueError("inspection units must follow canonical numeric source order")
    expected_unit_ids = tuple(
        unit.unit_id for unit in sorted(inspection.units, key=lambda item: _numeric_id(item.unit_id))
    )

    roster_patterns = tuple(
        (
            f"participant-{index:04d}",
            tuple(_normalize_private(row.name).split()),
            tuple(_normalize_private(row.identity).split()),
        )
        for index, row in enumerate(roster.rows, start=1)
    )
    if any(not name_words or not identity_words for _handle, name_words, identity_words in roster_patterns):
        raise ValueError("roster private matching keys must be nonempty")

    groups: list[ReviewGroup] = []
    exceptions: list[ExceptionCluster] = []
    source_exceptions: list[SourceException] = []
    exclusions: list[ExpandedDecision] = []
    seen_duplicate_groups: dict[str, str] = {}
    exception_number = 0

    for source in canonical_sources:
        source_units = tuple(units_by_evidence[source.evidence_id])
        duplicate_group = evidence.duplicate_group_for(source.evidence_id)
        if duplicate_group is not None and duplicate_group in seen_duplicate_groups:
            if source_units:
                exclusions.extend(
                    ExpandedDecision(
                        unit_id=unit.unit_id,
                        decision="exclude",
                        group_id=None,
                        state="automatically-organized",
                        role="",
                        target=None,
                        reason="duplicate",
                    )
                    for unit in source_units
                )
            else:
                exception_number += 1
                source_exceptions.append(
                    _make_source_exception(
                        exception_number,
                        source.evidence_id,
                        "source-exact-duplicate",
                    )
                )
            continue
        if duplicate_group is not None:
            seen_duplicate_groups[duplicate_group] = source.evidence_id

        if not source_units:
            exception_number += 1
            source_exceptions.append(
                _make_source_exception(
                    exception_number,
                    source.evidence_id,
                    _source_issue(source.inspection_status),
                )
            )
            continue

        drafts = _source_drafts(
            source,
            source_units,
            roster,
            roster_patterns,
            evidence,
        )
        for draft_range in _draft_ranges(drafts):
            first = draft_range[0]
            group_number = len(groups) + 1
            group_id = f"group-{group_number:04d}"
            member_unit_ids = tuple(draft.unit.unit_id for draft in draft_range)
            issue_codes = (first.issue_code,) if first.issue_code else ()
            state: GroupState = (
                "exception" if first.issue_code else "automatically-organized"
            )
            check_codes = (
                _exception_checks(first)
                if first.issue_code
                else _automatic_checks(first.target)
            )
            group = ReviewGroup(
                group_id=group_id,
                evidence_id=source.evidence_id,
                unit_kind=first.unit.unit_kind,
                member_unit_ids=member_unit_ids,
                first_unit_index=first.unit.unit_index,
                last_unit_index=draft_range[-1].unit.unit_index,
                role=first.role,
                target=first.target,
                state=state,
                check_codes=check_codes,
                issue_codes=issue_codes,
            )
            groups.append(group)
            if first.issue_code:
                exception_number += 1
                exceptions.append(
                    _make_exception(
                        exception_number,
                        group,
                        first.issue_code,
                    )
                )

    return GroupingPlan(
        roster_unit_id=roster.unit_id,
        groups=tuple(groups),
        exceptions=tuple(exceptions),
        source_exceptions=tuple(source_exceptions),
        expected_unit_ids=expected_unit_ids,
        automatic_exclusions=tuple(sorted(exclusions, key=lambda item: _numeric_id(item.unit_id))),
    )
